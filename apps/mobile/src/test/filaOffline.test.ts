import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@constela/core";

// Estado compartilhado com os factories dos mocks (hoisting).
const { armazem, apiMock, online } = vi.hoisted(() => {
  const mapa = new Map<string, string>();
  return {
    armazem: {
      mapa,
      getItem: async (chave: string) => mapa.get(chave) ?? null,
      setItem: async (chave: string, valor: string) => {
        mapa.set(chave, valor);
      },
      removeItem: async (chave: string) => {
        mapa.delete(chave);
      },
    },
    apiMock: vi.fn(),
    online: { valor: true },
  };
});

// Mantém o ApiError REAL (o `instanceof` da fila depende dele); só o `api` é mock.
vi.mock("@constela/core", async (importarReal) => {
  const real = await importarReal<typeof import("@constela/core")>();
  return { ...real, api: apiMock };
});
vi.mock("@tanstack/react-query", () => ({
  onlineManager: {
    isOnline: () => online.valor,
    subscribe: () => () => undefined,
  },
}));
vi.mock("../armazenamento/armazenamentoCifrado", () => ({
  armazenamentoCifrado: {
    getItem: armazem.getItem,
    setItem: armazem.setItem,
    removeItem: armazem.removeItem,
  },
}));

import { enviarOuEnfileirar, processarFila } from "../filaOffline";

const CHAVE = "constela_fila_offline_v1";
const fila = () => JSON.parse(armazem.mapa.get(CHAVE) ?? "[]") as unknown[];

describe("fila de escritas offline (não perder ação sem rede)", () => {
  beforeEach(() => {
    armazem.mapa.clear();
    apiMock.mockReset();
    online.valor = true;
  });

  it("offline: NÃO chama a API e enfileira a ação", async () => {
    online.valor = false;
    await enviarOuEnfileirar("/escolas/1/dispositivos", "POST", { token: "abc" });
    expect(apiMock).not.toHaveBeenCalled();
    expect(fila()).toHaveLength(1);
  });

  it("online com sucesso: envia na hora e nada fica na fila", async () => {
    apiMock.mockResolvedValue({});
    await enviarOuEnfileirar("/x", "POST", { a: 1 });
    expect(apiMock).toHaveBeenCalledTimes(1);
    expect(fila()).toHaveLength(0);
  });

  it("erro de rede/servidor (5xx): NÃO propaga e enfileira p/ reenvio", async () => {
    apiMock.mockRejectedValue(new ApiError(503, "indisponível"));
    await expect(enviarOuEnfileirar("/x", "POST")).resolves.toBeUndefined();
    expect(fila()).toHaveLength(1);
  });

  it("erro 4xx (cliente) é definitivo: propaga e NÃO enfileira", async () => {
    apiMock.mockRejectedValue(new ApiError(422, "inválido"));
    await expect(enviarOuEnfileirar("/x", "POST")).rejects.toBeInstanceOf(ApiError);
    expect(fila()).toHaveLength(0);
  });

  it("processarFila drena em ordem FIFO quando a rede volta", async () => {
    online.valor = false;
    await enviarOuEnfileirar("/primeiro", "POST");
    await enviarOuEnfileirar("/segundo", "POST");
    online.valor = true;
    apiMock.mockResolvedValue({});
    await processarFila();
    expect(apiMock.mock.calls.map((c) => c[0])).toEqual(["/primeiro", "/segundo"]);
    expect(fila()).toHaveLength(0);
  });

  it("processarFila PARA no 1º erro de rede e preserva a fila inteira", async () => {
    online.valor = false;
    await enviarOuEnfileirar("/a", "POST");
    await enviarOuEnfileirar("/b", "POST");
    online.valor = true;
    apiMock.mockRejectedValue(new ApiError(500, "fora"));
    await processarFila();
    expect(fila()).toHaveLength(2); // nada perdido; tenta na próxima reconexão
  });

  it("processarFila DESCARTA item com erro 4xx permanente e segue o próximo", async () => {
    online.valor = false;
    await enviarOuEnfileirar("/ruim", "POST");
    await enviarOuEnfileirar("/bom", "POST");
    online.valor = true;
    apiMock
      .mockRejectedValueOnce(new ApiError(422, "inválido")) // descarta /ruim
      .mockResolvedValueOnce({}); // /bom envia
    await processarFila();
    expect(apiMock.mock.calls.map((c) => c[0])).toEqual(["/ruim", "/bom"]);
    expect(fila()).toHaveLength(0);
  });
});
