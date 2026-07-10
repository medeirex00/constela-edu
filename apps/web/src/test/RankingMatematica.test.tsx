import { describe, expect, it } from "vitest";

import RankingMatematica from "../pages/RankingMatematica";
import {
  renderComApp,
  responder,
  responderErro,
  screen,
  turmaFake,
  userEvent,
} from "./utils";

// A escola atual é id=1 (sessão autenticada por padrão).
const URL_RANKING = "/escolas/1/ranking/matematica"; // casa com qualquer query (?periodo=...)
const URL_TURMAS = "/escolas/1/turmas";

// Não há fábrica pronta para RankingMatematicaItem — construímos o shape inline
// (ver packages/core/src/tipos.ts).
function itemMat(over: Record<string, unknown> = {}) {
  return {
    posicao: 1,
    aluno_id: 21,
    nome: "Marina Duarte",
    turma: "4º Ano B",
    ano_escolar: "4º Ano",
    estrelas: 120,
    atividades: 34,
    pontuacao_media: 87.5,
    ...over,
  };
}

const abrirTela = () =>
  renderComApp(<RankingMatematica />, { rota: "/ranking-matematica" });

describe("RankingMatematica", () => {
  it("mostra o cabeçalho e o ranking de matemática do período", async () => {
    responder("GET", URL_TURMAS, [turmaFake()]);
    responder("GET", URL_RANKING, [
      itemMat(),
      itemMat({ posicao: 2, aluno_id: 22, nome: "Rafael Nogueira" }),
    ]);

    abrirTela();

    // Cabeçalho da página.
    expect(
      await screen.findByRole("heading", { name: "Ranking de Matemática" }),
    ).toBeInTheDocument();

    // Colunas e linhas de alunos.
    expect(screen.getByText("Estrelas")).toBeInTheDocument();
    expect(screen.getByText("Atividades")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /Marina Duarte/ }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /Rafael Nogueira/ }),
    ).toBeInTheDocument();
  });

  it("mostra o estado vazio quando não há atividade no período", async () => {
    responder("GET", URL_TURMAS, []);
    responder("GET", URL_RANKING, []);

    abrirTela();

    expect(
      await screen.findByText("Nenhuma atividade de matemática no período"),
    ).toBeInTheDocument();
  });

  it("mostra a falha quando a API do ranking erra", async () => {
    responder("GET", URL_TURMAS, []);
    responderErro("GET", URL_RANKING, 500, "Erro interno");

    abrirTela();

    expect(
      await screen.findByText("Não foi possível carregar"),
    ).toBeInTheDocument();
  });

  it("rebusca o ranking ao trocar o período", async () => {
    const u = userEvent.setup();
    responder("GET", URL_TURMAS, [turmaFake()]);
    responder("GET", URL_RANKING, (caminho: string) =>
      caminho.includes("periodo=bimestre")
        ? [itemMat({ aluno_id: 30, nome: "Rafael Nogueira" })]
        : [itemMat({ aluno_id: 21, nome: "Marina Duarte" })],
    );

    abrirTela();

    // Período padrão ("Este mês").
    expect(
      await screen.findByRole("link", { name: /Marina Duarte/ }),
    ).toBeInTheDocument();

    // Troca para "Este bimestre" -> a URL muda e o hook rebusca sozinho.
    await u.selectOptions(
      screen.getByLabelText("Período de análise"),
      "bimestre",
    );

    expect(
      await screen.findByRole("link", { name: /Rafael Nogueira/ }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: /Marina Duarte/ }),
    ).not.toBeInTheDocument();
  });

  it("filtra o ranking por turma", async () => {
    const u = userEvent.setup();
    responder("GET", URL_TURMAS, [turmaFake({ id: 7, nome: "5º Ano C" })]);
    responder("GET", URL_RANKING, (caminho: string) =>
      caminho.includes("turma_id=7")
        ? [itemMat({ aluno_id: 40, nome: "Sofia Lima" })]
        : [itemMat({ aluno_id: 21, nome: "Marina Duarte" })],
    );

    abrirTela();

    expect(
      await screen.findByRole("link", { name: /Marina Duarte/ }),
    ).toBeInTheDocument();

    // Seleciona a turma no filtro -> acrescenta &turma_id=7 à URL.
    await u.selectOptions(screen.getByLabelText("Filtrar por turma"), "7");

    expect(
      await screen.findByRole("link", { name: /Sofia Lima/ }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: /Marina Duarte/ }),
    ).not.toBeInTheDocument();
  });
});
