/**
 * "Ainda não aferidos" da classificação oficial por matéria (DesempenhoDimensao):
 * a lista existe para que a criança sem dado NÃO suma da tela (ausência não é zero).
 * O componente lia só `dados` do `/nao-aferidos` — e o useApi mantém de propósito a
 * resposta da URL anterior quando a URL muda e quando a nova busca falha. Então:
 *   1. com o `/nao-aferidos` em erro, o bloco sumia sem aviso (parecia que todas as
 *      crianças tinham sido aferidas);
 *   2. trocando a turma A pela B, enquanto a B carregava ou quando ela falhava, o bloco
 *      listava as crianças da turma A como "não aferidas" da B, com link para a ficha.
 * Dados fictícios.
 */
import { useState } from "react";
import { describe, expect, it } from "vitest";

import { DesempenhoDimensao } from "../components/DesempenhoDimensao";
import type { NaoAferidos, RankingItem } from "../lib/types";
import { ApiError, rankingItemFake, renderComApp, responder, screen, userEvent, waitFor } from "./utils";

const URL_RANKING = "/escolas/1/ranking";
const URL_NAO_AFERIDOS = "/escolas/1/nao-aferidos";
const AVISO = /^Não foi possível carregar quem ainda não foi aferido em Leitura/;

function itemDimensao(over: Partial<RankingItem> = {}): RankingItem {
  return {
    ...rankingItemFake({ posicao: 1, aluno_id: 10, nome: "Ana Leitora" }),
    dimensao: "leitura", nota: 91, aferido: true, n_aferidos: 1,
    dados: { livros_unicos: 12, atividades: 30 }, adocao: 100,
    ...over,
  };
}

function naoAferidosDe(aluno_id: number, nome: string, turma: string): NaoAferidos {
  return {
    contratadas: ["leitura", "matematica"], total_alunos: 2,
    dimensoes: [{ dimensao: "leitura", plataforma: "Elefante Letrado", n_aferidos: 1, total: 2,
      alunos: [{ aluno_id, nome, turma, ano_escolar: "3º Ano" }] }],
    sem_nenhuma: [],
  };
}

/** A tela dona troca o filtro de turma (A = 1, B = 2). */
function Tela() {
  const [turma, setTurma] = useState("1");
  return (
    <>
      <button type="button" onClick={() => setTurma("2")}>ir para a turma B</button>
      <DesempenhoDimensao dimensao="leitura" filtros={{ turma_id: turma, turno: "todos" }} />
    </>
  );
}

describe("Ainda não aferidos: erro e resposta de outro filtro", () => {
  it("com o /nao-aferidos em erro, a tela avisa e oferece tentar de novo", async () => {
    let falhar = true;
    responder("GET", URL_RANKING, [itemDimensao()]);
    responder("GET", URL_NAO_AFERIDOS, () => (falhar
      ? new ApiError(500, "Erro interno. Tente novamente em instantes.")
      : naoAferidosDe(77, "Bruno Sem Leitura", "3º Ano A")));
    const u = userEvent.setup();
    renderComApp(<DesempenhoDimensao dimensao="leitura" filtros={{ turno: "todos" }} />);

    // A classificação carregou; a lista de quem falta, não — e a tela diz isso.
    await screen.findByRole("link", { name: "Ana Leitora" });
    expect(await screen.findByText(AVISO, {}, { timeout: 3000 })).toBeInTheDocument();
    expect(screen.queryByText(/Ainda não aferidos em Leitura/)).toBeNull();

    falhar = false;
    await u.click(screen.getByRole("button", { name: "Tentar de novo" }));
    expect(await screen.findByRole("link", { name: "Bruno Sem Leitura" })).toBeInTheDocument();
    expect(screen.queryByText(AVISO)).toBeNull();
  });

  it("turma A → B com o /nao-aferidos da B em erro: nenhuma criança da A fica na lista", async () => {
    responder("GET", URL_RANKING, (caminho: string) =>
      caminho.includes("turma_id=2")
        ? [itemDimensao({ aluno_id: 20, nome: "Davi Turma B" })]
        : [itemDimensao()]);
    responder("GET", URL_NAO_AFERIDOS, (caminho: string) =>
      caminho.includes("turma_id=2")
        ? new ApiError(500, "Erro interno. Tente novamente em instantes.")
        : naoAferidosDe(77, "Bruno Da Turma A", "3º Ano A"));
    const u = userEvent.setup();
    renderComApp(<Tela />);
    await screen.findByRole("link", { name: "Bruno Da Turma A" });

    await u.click(screen.getByRole("button", { name: "ir para a turma B" }));
    await screen.findByRole("link", { name: "Davi Turma B" });
    // A criança da turma A sai já durante a busca da B, e não volta depois do erro
    // (o 5xx é tentado mais uma vez antes de virar erro).
    expect(screen.queryByRole("link", { name: "Bruno Da Turma A" })).toBeNull();
    expect(await screen.findByText(AVISO, {}, { timeout: 3000 })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Bruno Da Turma A" })).toBeNull();
  });

  it("turma A → B enquanto a B carrega: a lista da A não aparece como se fosse da B", async () => {
    let liberarB: (v: NaoAferidos) => void = () => {};
    responder("GET", URL_RANKING, (caminho: string) =>
      caminho.includes("turma_id=2")
        ? [itemDimensao({ aluno_id: 20, nome: "Davi Turma B" })]
        : [itemDimensao()]);
    responder("GET", URL_NAO_AFERIDOS, (caminho: string) =>
      caminho.includes("turma_id=2")
        ? new Promise<NaoAferidos>((resolve) => { liberarB = resolve; })
        : naoAferidosDe(77, "Bruno Da Turma A", "3º Ano A"));
    const u = userEvent.setup();
    renderComApp(<Tela />);
    await screen.findByRole("link", { name: "Bruno Da Turma A" });

    await u.click(screen.getByRole("button", { name: "ir para a turma B" }));
    await screen.findByRole("link", { name: "Davi Turma B" });
    expect(screen.queryByRole("link", { name: "Bruno Da Turma A" })).toBeNull();

    liberarB(naoAferidosDe(88, "Eva Da Turma B", "3º Ano B"));
    expect(await screen.findByRole("link", { name: "Eva Da Turma B" })).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("link", { name: "Bruno Da Turma A" })).toBeNull());
  });
});
