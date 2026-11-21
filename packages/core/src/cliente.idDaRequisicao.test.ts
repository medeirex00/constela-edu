/**
 * O id da requisição (X-Request-ID) chega a quem vê o erro.
 *
 * O servidor põe o id em toda resposta e o expõe no CORS "para o relato de suporte", mas
 * o cliente compartilhado descartava os cabeçalhos ao montar o ApiError: a coordenadora
 * via "Erro interno. Tente novamente em instantes." e o suporte não tinha como achar o
 * traceback no log (auditoria, achado OBSERVABILIDADE-9). Dados fictícios.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, api, apiBlob, configurarApi, loginRequest } from "./cliente";

const ID = "4f1c2b9a0d8e4c6b8a7f5e3d2c1b0a99";
const INTERNO = "Erro interno. Tente novamente em instantes.";

function responder(status: number, detail: unknown, cabecalhos: Record<string, string> = {}) {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ detail }), {
    status, headers: { "content-type": "application/json", ...cabecalhos },
  })));
}

async function erroDe(promessa: Promise<unknown>): Promise<ApiError> {
  const erro = await promessa.catch((e: unknown) => e);
  expect(erro).toBeInstanceOf(ApiError);
  return erro as ApiError;
}

describe("cliente HTTP: id da requisição no erro", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    configurarApi({ base: "/api/v1" });
  });

  it("um 500 leva o id inteiro no ApiError e o começo dele na mensagem", async () => {
    configurarApi({ base: "http://api.exemplo.test/api/v1" });
    responder(500, INTERNO, { "x-request-id": ID });
    const erro = await erroDe(api("/escolas/1/dashboard"));
    expect(erro.status).toBe(500);
    expect(erro.requestId).toBe(ID);
    expect(erro.message).toBe(`${INTERNO} (código: 4f1c2b9a)`);
  });

  it("um 502 da plataforma também mostra o código", async () => {
    responder(502, "A plataforma não respondeu. Tente mais tarde.", { "X-Request-ID": ID });
    const erro = await erroDe(api("/escolas/1/sync/matific/placar-ao-vivo"));
    expect(erro.message).toBe("A plataforma não respondeu. Tente mais tarde. (código: 4f1c2b9a)");
  });

  it("num erro de quem pediu (4xx) a mensagem não muda; o id fica no ApiError", async () => {
    responder(400, "Requisição inválida.", { "x-request-id": ID });
    const erro = await erroDe(api("/qualquer"));
    expect(erro.message).toBe("Requisição inválida.");
    expect(erro.requestId).toBe(ID);
  });

  it("sem o cabeçalho, nada muda", async () => {
    responder(500, INTERNO);
    const erro = await erroDe(api("/qualquer"));
    expect(erro.message).toBe(INTERNO);
    expect(erro.requestId).toBeUndefined();
  });

  it("um id fora do formato não vai para a mensagem", async () => {
    responder(500, INTERNO, { "x-request-id": "<script>alert(1)</script>" });
    const erro = await erroDe(api("/qualquer"));
    expect(erro.message).toBe(INTERNO);
    expect(erro.requestId).toBeUndefined();
  });

  it("download e login seguem a mesma regra", async () => {
    responder(500, INTERNO, { "x-request-id": ID });
    expect((await erroDe(apiBlob("/escolas/1/relatorios/alunos"))).message)
      .toBe(`${INTERNO} (código: 4f1c2b9a)`);
    responder(503, "Serviço indisponível.", { "x-request-id": ID });
    const login = await erroDe(loginRequest("pessoa@exemplo.test", "senha-ficticia"));
    expect(login.message).toBe("Serviço indisponível. (código: 4f1c2b9a)");
    expect(login.requestId).toBe(ID);
  });

  it("resposta sem objeto de cabeçalhos (dublê de teste) não quebra", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({
      ok: false, status: 500, json: async () => ({ detail: INTERNO }),
    })));
    const erro = await erroDe(api("/qualquer"));
    expect(erro.message).toBe(INTERNO);
  });
});
