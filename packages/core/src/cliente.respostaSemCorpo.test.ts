/**
 * Resposta OK SEM CORPO (204 No Content ou corpo vazio).
 *
 * O backend responde 204 em ações que DÃO CERTO: resolver alerta da
 * sincronização, remover credencial, desvincular a escola externa, marcar
 * notificações como lidas. O cliente fazia `resposta.json()` mesmo assim, o
 * que lança SyntaxError ("Unexpected end of JSON input"): a tela tratava o
 * sucesso como "Falha de conexão" e não recarregava.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import { api, apiUpload } from "./cliente";

describe("cliente HTTP: resposta OK sem corpo devolve undefined", () => {
  const fetchOriginal = globalThis.fetch;
  afterEach(() => {
    globalThis.fetch = fetchOriginal;
    vi.restoreAllMocks();
  });

  function responderCom(fabrica: () => Response) {
    globalThis.fetch = vi.fn(async () => fabrica()) as unknown as typeof fetch;
  }

  it("POST com 204 resolve undefined (não lança SyntaxError)", async () => {
    responderCom(() => new Response(null, { status: 204 }));
    await expect(
      api("/escolas/1/sync/alertas/7/resolver", { method: "POST" }),
    ).resolves.toBeUndefined();
  });

  it("DELETE com 204 resolve undefined", async () => {
    responderCom(() => new Response(null, { status: 204 }));
    await expect(
      api("/escolas/1/sync/credenciais/elefante", { method: "DELETE" }),
    ).resolves.toBeUndefined();
  });

  it("200 com corpo vazio resolve undefined", async () => {
    responderCom(() => new Response("", { status: 200 }));
    await expect(api("/qualquer", { method: "POST" })).resolves.toBeUndefined();
  });

  it("upload com 204 resolve undefined", async () => {
    responderCom(() => new Response(null, { status: 204 }));
    await expect(apiUpload("/escolas/1/importacoes", new FormData())).resolves.toBeUndefined();
  });

  it("200 com JSON continua devolvendo o corpo (inclusive null literal)", async () => {
    responderCom(() => new Response(JSON.stringify({ id: 3, nome: "Turma Ficticia" }), {
      status: 200, headers: { "Content-Type": "application/json" },
    }));
    await expect(api("/qualquer")).resolves.toEqual({ id: 3, nome: "Turma Ficticia" });

    responderCom(() => new Response("null", {
      status: 200, headers: { "Content-Type": "application/json" },
    }));
    await expect(api("/qualquer")).resolves.toBeNull();
  });

  it("200 com corpo que NÃO é JSON continua sendo erro (não vira undefined)", async () => {
    responderCom(() => new Response("<html>proxy</html>", { status: 200 }));
    await expect(api("/qualquer")).rejects.toBeInstanceOf(SyntaxError);
  });
});
