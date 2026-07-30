import { describe, expect, it } from "vitest";

import RankingGeral from "../pages/RankingGeral";
import {
  rankingItemFake,
  renderComApp,
  responder,
  responderErro,
  screen,
  turmaFake,
  userEvent,
} from "./utils";

const URL_TURMAS = "/escolas/1/turmas";
const URL_RANKING = "/escolas/1/ranking";
const URL_EVOLUCAO = "/escolas/1/ranking-evolucao";

const opcoes = { rota: "/ranking" };

describe("RankingGeral", () => {
  it("carrega e mostra a classificação acumulada (Todo o histórico)", async () => {
    responder("GET", URL_TURMAS, [turmaFake()]);
    responder("GET", URL_RANKING, [
      rankingItemFake({ posicao: 1, aluno_id: 10, nome: "Ana Beatriz Souza" }),
      rankingItemFake({ posicao: 2, aluno_id: 11, nome: "João Pedro Barbosa" }),
    ]);

    renderComApp(<RankingGeral />, opcoes);

    // Nome dos alunos vira link para o perfil.
    expect(
      await screen.findByRole("link", { name: "Ana Beatriz Souza" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "João Pedro Barbosa" }),
    ).toBeInTheDocument();

    // Colunas específicas da visão acumulada.
    expect(screen.getByText("Matific")).toBeInTheDocument();
    expect(screen.getByText("Leitura")).toBeInTheDocument();
  });

  it("mostra o estado vazio quando não há nenhuma nota calculada", async () => {
    responder("GET", URL_TURMAS, []);
    responder("GET", URL_RANKING, []);

    renderComApp(<RankingGeral />, opcoes);

    expect(
      await screen.findByText("Nenhuma nota calculada ainda"),
    ).toBeInTheDocument();
  });

  it("mostra a mensagem de falha quando a API do ranking erra", async () => {
    responder("GET", URL_TURMAS, []);
    responderErro("GET", URL_RANKING, 500, "Erro interno");

    renderComApp(<RankingGeral />, opcoes);

    expect(
      await screen.findByText("Não foi possível carregar"),
    ).toBeInTheDocument();
  });

  it("ao escolher um período, troca para a classificação do período", async () => {
    responder("GET", URL_TURMAS, [turmaFake()]);
    responder("GET", URL_RANKING, [
      rankingItemFake({ nome: "Ana Beatriz Souza" }),
    ]);
    responder("GET", URL_EVOLUCAO, [
      {
        posicao: 1,
        aluno_id: 10,
        nome: "Marina Lopes",
        turma: "3º Ano A",
        nota_evolucao: 12,
        ganhos: {
          atividades: 5,
          estrelas: 3,
          livros: 2,
          tempo_leitura_min: 40,
          acertos: 7,
        },
      },
    ]);

    const u = userEvent.setup();
    renderComApp(<RankingGeral />, opcoes);

    // Estado inicial: visão acumulada.
    await screen.findByRole("link", { name: "Ana Beatriz Souza" });

    await u.selectOptions(
      screen.getByLabelText("Período de análise"),
      "hoje",
    );

    // Agora exibe a classificação do período (fonte ranking-evolucao).
    expect(
      await screen.findByRole("link", { name: "Marina Lopes" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("calculado só com o período selecionado"),
    ).toBeInTheDocument();
    expect(screen.getByText("Nota do período")).toBeInTheDocument();
  });

  it("filtra por turma e refaz a busca do ranking com turma_id", async () => {
    responder("GET", URL_TURMAS, [turmaFake({ id: 1, nome: "3º Ano A" })]);
    responder("GET", URL_RANKING, (caminho: string) =>
      caminho.includes("turma_id=1")
        ? [rankingItemFake({ aluno_id: 20, nome: "Aluno Da Turma A" })]
        : [rankingItemFake({ aluno_id: 10, nome: "Ana Beatriz Souza" })],
    );

    const u = userEvent.setup();
    renderComApp(<RankingGeral />, opcoes);

    await screen.findByRole("link", { name: "Ana Beatriz Souza" });

    await u.selectOptions(screen.getByLabelText("Filtrar por turma ou série"), "turma:1");

    expect(
      await screen.findByRole("link", { name: "Aluno Da Turma A" }),
    ).toBeInTheDocument();
  });

  it("consolida por série e busca o ranking com ano_escolar", async () => {
    responder("GET", URL_TURMAS, [
      turmaFake({ id: 1, nome: "1º Ano A", ano_escolar: "1º Ano" }),
      turmaFake({ id: 2, nome: "1º Ano B", ano_escolar: "1º Ano" }),
    ]);
    responder("GET", URL_RANKING, (caminho: string) =>
      caminho.includes("ano_escolar=1%C2%BA+Ano") || caminho.includes("ano_escolar=1%C2%BA%20Ano")
        ? [rankingItemFake({ aluno_id: 30, nome: "Aluno Da Serie" })]
        : [rankingItemFake({ aluno_id: 10, nome: "Ana Beatriz Souza" })],
    );

    const u = userEvent.setup();
    renderComApp(<RankingGeral />, opcoes);

    await screen.findByRole("link", { name: "Ana Beatriz Souza" });

    await u.selectOptions(
      screen.getByLabelText("Filtrar por turma ou série"),
      "serie:1º Ano",
    );

    expect(
      await screen.findByRole("link", { name: "Aluno Da Serie" }),
    ).toBeInTheDocument();
  });
});
