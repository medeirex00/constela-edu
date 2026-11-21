/**
 * Fila de escritas offline sob escrita CONCORRENTE (auditoria MOBILE-6).
 *
 * `processarFila` lia o disco uma vez e, a cada envio, regravava a SUA cópia
 * (`itens.slice(1)`); `enfileirar` fazia ler-acrescentar-gravar por conta própria.
 * Uma escrita enfileirada enquanto um item antigo estava em voo era apagada pela
 * regravação seguinte da drenagem. Código real de filaOffline.ts; só `api` e o
 * armazenamento são falsos. Dados fictícios.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, guardarToken } from "@constela/core";

const { disco, apiMock, online } = vi.hoisted(() => ({
  disco: new Map<string, string>(),
  apiMock: vi.fn(),
  online: { valor: true },
}));

vi.mock("@constela/core", async (real) => ({
  ...(await real<typeof import("@constela/core")>()),
  api: apiMock,
}));
vi.mock("@tanstack/react-query", () => ({
  onlineManager: { isOnline: () => online.valor, subscribe: () => () => undefined },
}));
vi.mock("../armazenamento/armazenamentoCifrado", () => ({
  armazenamentoCifrado: {
    // Leitura e gravação levam um "tique" cada, como o AsyncStorage + cifra reais.
    getItem: async (k: string) => {
      await Promise.resolve();
      return disco.get(k) ?? null;
    },
    setItem: async (k: string, v: string) => {
      await Promise.resolve();
      disco.set(k, v);
    },
    removeItem: async (k: string) => {
      await Promise.resolve();
      disco.delete(k);
    },
  },
}));

import { enviarOuEnfileirar, processarFila } from "../filaOffline";

const CHAVE = "constela_fila_offline_v1";
const fila = () =>
  (JSON.parse(disco.get(CHAVE) ?? "[]") as { caminho: string }[]).map((i) => i.caminho);
const tique = () => new Promise((r) => setTimeout(r, 0));

describe("fila offline: escrita nova durante a drenagem não se perde", () => {
  beforeEach(async () => {
    await guardarToken("sessao-ficticia");
    disco.clear();
    apiMock.mockReset();
    online.valor = true;
  });

  it("item enfileirado enquanto um item antigo está em voo continua no disco", async () => {
    online.valor = false;
    await enviarOuEnfileirar("/escolas/1/dispositivos", "POST", { token_push: "A" });
    online.valor = true;

    let liberar!: () => void;
    apiMock.mockImplementationOnce(() => new Promise<void>((r) => { liberar = r; })); // antigo em voo
    apiMock.mockRejectedValueOnce(new ApiError(503, "Serviço indisponível")); // novo falha → fila
    apiMock.mockRejectedValue(new ApiError(503, "Serviço indisponível")); // a drenagem para no novo

    const drenagem = processarFila();
    await tique();
    await enviarOuEnfileirar("/escolas/2/dispositivos", "POST", { token_push: "B" });
    expect(fila()).toEqual(["/escolas/1/dispositivos", "/escolas/2/dispositivos"]);
    liberar();
    await drenagem;
    // O antigo foi enviado e sai; o novo (5xx) fica para a próxima reconexão.
    expect(fila()).toEqual(["/escolas/2/dispositivos"]);
  });

  it("a drenagem também envia o que chegou no meio dela, na ordem", async () => {
    online.valor = false;
    await enviarOuEnfileirar("/primeiro", "POST");
    online.valor = true;

    let liberar!: () => void;
    apiMock.mockImplementationOnce(() => new Promise<void>((r) => { liberar = r; })); // /primeiro
    apiMock.mockRejectedValueOnce(new ApiError(0, "sem rede")); // /segundo na hora → fila
    apiMock.mockResolvedValue({}); // drenagem: /segundo

    const drenagem = processarFila();
    await tique();
    await enviarOuEnfileirar("/segundo", "POST");
    liberar();
    await drenagem;
    expect(apiMock.mock.calls.map((c) => c[0])).toEqual(["/primeiro", "/segundo", "/segundo"]);
    expect(fila()).toEqual([]);
  });

  it("duas escritas enfileiradas ao mesmo tempo ficam as duas", async () => {
    online.valor = false;
    await Promise.all([
      enviarOuEnfileirar("/a", "POST"),
      enviarOuEnfileirar("/b", "POST"),
    ]);
    expect(fila()).toEqual(["/a", "/b"]);
  });
});
