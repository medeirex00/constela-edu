/**
 * G_QUEST-1 (cliente): o download dos cartões do Quest (`@constela/quest-core`,
 * `baixarCartaoDoAluno` / `baixarCartoesDaTurma`) diz o que a API respondeu.
 *
 * Antes, `baixarPdf` lançava `ApiError(status, "Não foi possível gerar o PDF.")` sem ler
 * o `detail` da resposta (o professor não sabia o porquê: módulo fora do plano, aluno de
 * outra turma…) e, no 204 da revogação sem cartão novo (ficha inativa), devolvia um blob
 * vazio — o painel da turma dependia de `blob.size === 0`. Agora o erro traz o `detail`
 * da API e o 204 volta como `{ blob: null, revogado: true }`. O fetch é falso; dados
 * fictícios.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import { baixarCartaoDoAluno, baixarCartoesDaTurma } from "@constela/quest-core";
import { ApiError } from "@constela/core";

function resposta(status: number, corpo: BodyInit | null, cabecalhos: Record<string, string> = {}) {
  return new Response(corpo, { status, headers: cabecalhos });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("download dos cartões do Quest", () => {
  it("204 (só revogou): blob nulo e revogado, sem depender do tamanho", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(resposta(204, null)));
    const pdf = await baixarCartaoDoAluno(1, 22, true);
    expect(pdf).toEqual({ blob: null, nomeArquivo: "cartao-quest.pdf", revogado: true });
  });

  it("erro com detail: a mensagem da API chega à tela", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(resposta(
      403, JSON.stringify({ detail: "O Constela Quest não faz parte do plano desta rede." }),
      { "Content-Type": "application/json" })));
    const erro = await baixarCartoesDaTurma(1, 5).catch((e: unknown) => e);
    expect(erro).toBeInstanceOf(ApiError);
    expect((erro as ApiError).status).toBe(403);
    expect((erro as ApiError).message).toBe("O Constela Quest não faz parte do plano desta rede.");
  });

  it("erro sem corpo JSON: a mensagem genérica de antes", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(resposta(500, "falhou")));
    const erro = await baixarCartoesDaTurma(1, 5).catch((e: unknown) => e);
    expect((erro as ApiError).message).toBe("Não foi possível gerar o PDF.");
  });

  it("200: o PDF e o nome do arquivo do cabeçalho", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(resposta(
      200, "%PDF-1.4", { "Content-Disposition": 'attachment; filename="cartoes-3-ano-a.pdf"' })));
    const pdf = await baixarCartoesDaTurma(1, 5);
    expect(pdf.revogado).toBe(false);
    expect(pdf.nomeArquivo).toBe("cartoes-3-ano-a.pdf");
    expect(pdf.blob?.size).toBeGreaterThan(0);
  });
});
