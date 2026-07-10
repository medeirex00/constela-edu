import { beforeEach, describe, expect, it, vi } from "vitest";

// SecureStore fake (Keystore/Keychain do SO). Compartilhado via vi.hoisted para
// o factory do mock enxergá-lo apesar do hoisting do vi.mock.
const { cofre } = vi.hoisted(() => ({ cofre: new Map<string, string>() }));

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

describe("cifra AES-256 do cache em repouso (LGPD: dados no aparelho)", () => {
  beforeEach(async () => {
    cofre.clear();
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
});
