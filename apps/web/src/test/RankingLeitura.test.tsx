import { describe, expect, it } from "vitest";

import RankingLeitura from "../pages/RankingLeitura";
import { renderComApp, responder, responderErro, screen, userEvent } from "./utils";

import type { RankingLeituraItem, Turma } from "../lib/types";

// A escola atual é id=1 (autenticado). O período padrão da tela é "mes".
const URL_RANKING = "/escolas/1/ranking/leitura";
const URL_TURMAS = "/escolas/1/turmas";

const turmasFake: Turma[] = [
  {
    id: 1, nome: "3º Ano A", ano_escolar: "3º Ano", ano_letivo: 2026,
    professor_id: null, turno: "manhã", capacidade_maxima: 30, observacoes: null,
    status: "ativa", professor_nome: null, total_alunos: 3,
  },
];

const itensFake: RankingLeituraItem[] = [
  {
    posicao: 1, aluno_id: 10, nome: "Ana Beatriz Souza", turma: "3º Ano A",
    ano_escolar: "3º Ano", livros: 12, pontos: 340, tempo_leitura_min: 125,
  },
  {
    posicao: 2, aluno_id: 11, nome: "João Pedro Barbosa", turma: "3º Ano B",
    ano_escolar: "3º Ano", livros: 8, pontos: 210, tempo_leitura_min: 45,
  },
];

describe("RankingLeitura", () => {
  it("mostra o ranking de leitura do período com alunos e cabeçalhos", async () => {
    responder("GET", URL_TURMAS, turmasFake);
    responder("GET", URL_RANKING, itensFake);
    renderComApp(<RankingLeitura />, { rota: "/ranking-leitura" });

    // Título da tela + alunos (âncoras estáveis).
    expect(await screen.findByText("Ranking de Leitura")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Ana Beatriz Souza/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /João Pedro Barbosa/ })).toBeInTheDocument();

    // Cabeçalhos da tabela e a posição.
    expect(screen.getByText("Livros")).toBeInTheDocument();
    expect(screen.getByText("Pontos")).toBeInTheDocument();
    expect(screen.getByText("Tempo")).toBeInTheDocument();
    expect(screen.getByText("1º")).toBeInTheDocument();
  });

  it("mostra estado vazio quando não há leituras no período", async () => {
    responder("GET", URL_TURMAS, turmasFake);
    responder("GET", URL_RANKING, []);
    renderComApp(<RankingLeitura />, { rota: "/ranking-leitura" });

    expect(await screen.findByText("Nenhuma leitura no período")).toBeInTheDocument();
  });

  it("mostra falha quando a API do ranking erra", async () => {
    responder("GET", URL_TURMAS, turmasFake);
    responderErro("GET", URL_RANKING, 500, "Erro interno");
    renderComApp(<RankingLeitura />, { rota: "/ranking-leitura" });

    expect(await screen.findByText("Não foi possível carregar")).toBeInTheDocument();
  });

  it("rebusca o ranking ao trocar o período", async () => {
    responder("GET", URL_TURMAS, turmasFake);
    // Responde de acordo com o período embutido na query string.
    responder("GET", URL_RANKING, (caminho: string) =>
      caminho.includes("periodo=semana")
        ? [{
            posicao: 1, aluno_id: 20, nome: "Leitor da Semana", turma: null,
            ano_escolar: null, livros: 3, pontos: 50, tempo_leitura_min: 30,
          }]
        : itensFake,
    );
    const u = userEvent.setup();
    renderComApp(<RankingLeitura />, { rota: "/ranking-leitura" });

    // Estado inicial (período "mes").
    expect(await screen.findByRole("link", { name: /Ana Beatriz Souza/ })).toBeInTheDocument();

    // Troca para "Esta semana" -> a URL muda e o hook rebusca.
    await u.selectOptions(screen.getByLabelText("Período de análise"), "semana");

    expect(await screen.findByRole("link", { name: /Leitor da Semana/ })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Ana Beatriz Souza/ })).not.toBeInTheDocument();
  });

  it("filtra por turma populando o seletor a partir de /turmas", async () => {
    responder("GET", URL_TURMAS, turmasFake);
    responder("GET", URL_RANKING, (caminho: string) =>
      caminho.includes("turma_id=1")
        ? [{
            posicao: 1, aluno_id: 30, nome: "Aluno da Turma A", turma: "3º Ano A",
            ano_escolar: "3º Ano", livros: 5, pontos: 90, tempo_leitura_min: 60,
          }]
        : itensFake,
    );
    const u = userEvent.setup();
    renderComApp(<RankingLeitura />, { rota: "/ranking-leitura" });

    expect(await screen.findByRole("link", { name: /Ana Beatriz Souza/ })).toBeInTheDocument();

    // O seletor de turma foi populado com o nome vindo de /turmas.
    await u.selectOptions(screen.getByLabelText("Filtrar por turma ou série"), "turma:1");

    expect(await screen.findByRole("link", { name: /Aluno da Turma A/ })).toBeInTheDocument();
  });

  it("consolida por série enviando ano_escolar na busca", async () => {
    responder("GET", URL_TURMAS, turmasFake);
    responder("GET", URL_RANKING, (caminho: string) =>
      caminho.includes("ano_escolar=3%C2%BA")
        ? [{
            posicao: 1, aluno_id: 40, nome: "Aluno da Serie", turma: "3º Ano B",
            ano_escolar: "3º Ano", livros: 7, pontos: 120, tempo_leitura_min: 30,
          }]
        : itensFake,
    );
    const u = userEvent.setup();
    renderComApp(<RankingLeitura />, { rota: "/ranking-leitura" });

    expect(await screen.findByRole("link", { name: /Ana Beatriz Souza/ })).toBeInTheDocument();

    await u.selectOptions(screen.getByLabelText("Filtrar por turma ou série"), "serie:3º Ano");

    expect(await screen.findByRole("link", { name: /Aluno da Serie/ })).toBeInTheDocument();
  });
});
