import { beforeEach, describe, expect, it, vi } from "vitest";

// SecureStore fake (Keystore/Keychain do SO). Compartilhado via vi.hoisted para
// o factory do mock enxergá-lo apesar do hoisting do vi.mock.
const { cofre, disco } = vi.hoisted(() => ({
  cofre: new Map<string, string>(),
  disco: {
    dados: new Map<string, string>(),
    esperar: false,
    liberar: null as (() => void) | null,
    remover: vi.fn(),
  },
}));

vi.mock("@react-native-async-storage/async-storage", () => ({
  default: {
    getItem: async (chave: string) => disco.dados.get(chave) ?? null,
    setItem: async (chave: string, valor: string) => {
      if (disco.esperar) {
        disco.esperar = false;
        await new Promise<void>((resolver) => { disco.liberar = resolver; });
      }
      disco.dados.set(chave, valor);
    },
    removeItem: async (chave: string) => {
      disco.remover(chave);
      disco.dados.delete(chave);
    },
  },
}));

vi.mock("expo-secure-store", () => ({
  getItemAsync: async (chave: string) => cofre.get(chave) ?? null,
  setItemAsync: async (chave: string, valor: string) => {
    cofre.set(chave, valor);
  },
  deleteItemAsync: async (chave: string) => {
    cofre.delete(chave);
  },
}));

// CSPRNG determinístico (LCG): basta variar os bytes entre chamadas para os IVs
// saírem diferentes. O estado vive DENTRO do factory (hoisting).
vi.mock("expo-crypto", () => {
  let estado = 0x12345678;
  return {
    getRandomBytesAsync: async (n: number) => {
      const bytes = new Uint8Array(n);
      for (let i = 0; i < n; i++) {
        estado = (estado * 1664525 + 1013904223) >>> 0;
        bytes[i] = (estado >>> 24) & 0xff;
      }
      return bytes;
    },
  };
});

import { cifrar, decifrar, esquecerChave } from "../armazenamento/cifra";
import { armazenamentoCifrado } from "../armazenamento/armazenamentoCifrado";

describe("cifra AES-256 do cache em repouso (LGPD: dados no aparelho)", () => {
  beforeEach(async () => {
    cofre.clear();
    disco.dados.clear();
    disco.esperar = false;
    disco.liberar = null;
    disco.remover.mockClear();
    await esquecerChave(); // zera a chave em memória entre os testes
  });

  it("faz ida e volta (cifrar → decifrar) preservando o texto", async () => {
    const blob = await cifrar("dados sensíveis da criança");
    expect(blob).not.toContain("criança"); // nada em texto plano
    expect(await decifrar(blob)).toBe("dados sensíveis da criança");
  });

  it("usa IV novo por gravação: o mesmo texto vira blobs diferentes", async () => {
    const a = await cifrar("igual");
    const b = await cifrar("igual");
    expect(a).not.toBe(b); // IVs distintos
    expect(await decifrar(a)).toBe("igual");
    expect(await decifrar(b)).toBe("igual");
  });

  it("as primeiras gravações simultâneas usam a mesma chave do cofre", async () => {
    const [sessao, cache] = await Promise.all([cifrar("sessão fictícia"), cifrar("cache fictício")]);

    expect(await decifrar(sessao)).toBe("sessão fictícia");
    expect(await decifrar(cache)).toBe("cache fictício");
  });

  it("apagar a chave antes da primeira gravação terminar invalida o conteúdo antigo", async () => {
    const gravacao = cifrar("cache fictício da sessão encerrada");
    await esquecerChave();

    expect(await decifrar(await gravacao)).toBeNull();
  });

  it("gera a chave de 256 bits no SecureStore (nunca no AsyncStorage claro)", async () => {
    expect(cofre.size).toBe(0);
    await cifrar("x");
    expect(cofre.has("constela_cache_chave_v1")).toBe(true);
  });

  it("blob corrompido ou sem IV devolve null (trata como 'sem cache')", async () => {
    expect(await decifrar("sem-dois-pontos")).toBeNull();
    expect(await decifrar("QUJD:conteudo-invalido")).toBeNull();
  });

  it("esquecerChave (logout) torna o cache do usuário anterior ilegível", async () => {
    const blob = await cifrar("do usuário anterior");
    await esquecerChave(); // rotaciona a chave
    expect(cofre.has("constela_cache_chave_v1")).toBe(false);
    // Próximo acesso gera nova chave; o blob antigo não decifra mais.
    expect(await decifrar(blob)).toBeNull();
  });

  it("uma gravação antiga no disco termina antes da remoção do cache", async () => {
    disco.esperar = true;
    const antiga = armazenamentoCifrado.setItem("cache", "dado anterior");
    await vi.waitFor(() => expect(disco.liberar).not.toBeNull());

    const remover = armazenamentoCifrado.removeItem("cache");
    const atual = armazenamentoCifrado.setItem("cache", "dado atual");
    expect(disco.remover).not.toHaveBeenCalled();

    disco.liberar!();
    await Promise.all([antiga, remover, atual]);
    expect(await armazenamentoCifrado.getItem("cache")).toBe("dado atual");
  });
});
