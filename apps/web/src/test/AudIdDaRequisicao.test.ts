/**
 * O download por POST (lote de certificados) monta o erro por conta própria
 * (`erroDaResposta`): o id da requisição (X-Request-ID) também chega a quem vê o erro,
 * como no cliente compartilhado (auditoria, achado OBSERVABILIDADE-9). Dados fictícios.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

const ID = "4f1c2b9a0d8e4c6b8a7f5e3d2c1b0a99";
const LOTE = "/escolas/1/certificados/lote";
const real = () => vi.importActual<typeof import("../lib/api")>("../lib/api");

function responder(resposta: Response) {
  vi.stubGlobal("fetch", vi.fn(async () => resposta));
}

describe("apiDownloadPost: id da requisição no erro", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("um 500 leva o id no ApiError e o começo dele na mensagem; o corpo vai junto", async () => {
    const corpo = { detail: "Erro interno. Tente novamente em instantes." };
    responder(new Response(JSON.stringify(corpo), {
      status: 500, headers: { "Content-Type": "application/json", "X-Request-ID": ID },
    }));
    const { apiDownloadPost } = await real();
    await expect(apiDownloadPost(LOTE, { aluno_ids: [101] })).rejects.toMatchObject({
      status: 500,
      requestId: ID,
      message: "Erro interno. Tente novamente em instantes. (código: 4f1c2b9a)",
      corpo,
    });
  });

  it("um 422 mantém a mensagem do backend", async () => {
    responder(new Response(JSON.stringify({ detail: "Nenhum aluno apto para o certificado." }), {
      status: 422, headers: { "Content-Type": "application/json", "X-Request-ID": ID },
    }));
    const { apiDownloadPost } = await real();
    await expect(apiDownloadPost(LOTE, { aluno_ids: [101] })).rejects.toMatchObject({
      status: 422, requestId: ID, message: "Nenhum aluno apto para o certificado.",
    });
  });
});
