import { describe, expect, it } from "vitest";

import Dashboard from "../pages/Dashboard";
import {
  dashboardFake,
  renderComApp,
  responder,
  responderErro,
  screen,
} from "./utils";

const URL_DASH = "/escolas/1/dashboard";

describe("Dashboard", () => {
  it("mostra os indicadores e o Top 10 da escola", async () => {
    responder("GET", URL_DASH, dashboardFake());
    renderComApp(<Dashboard />);

    // Cartões de indicadores.
    expect(await screen.findByText("Alunos")).toBeInTheDocument();
    expect(screen.getByText("42")).toBeInTheDocument(); // total_alunos
    expect(screen.getByText("Professores")).toBeInTheDocument();

    // Tabela Top 10.
    expect(screen.getByText("Top 10 — Ranking Geral")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Ana Beatriz Souza" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "João Pedro Barbosa" })).toBeInTheDocument();
  });

  it("mostra estado vazio quando ainda não há notas calculadas", async () => {
    responder("GET", URL_DASH, dashboardFake({ top10: [] }));
    renderComApp(<Dashboard />);

    expect(await screen.findByText("Ainda não há notas calculadas")).toBeInTheDocument();
  });

  it("mostra mensagem de falha quando a API de indicadores erra", async () => {
    responderErro("GET", URL_DASH, 500, "Erro interno");
    renderComApp(<Dashboard />);

    expect(
      await screen.findByText("Não foi possível carregar os indicadores"),
    ).toBeInTheDocument();
  });

  it("no primeiro acesso (escola sem turmas nem alunos) mostra só o Comece aqui", async () => {
    // Escola nova: sem turmas e sem alunos → tela inicial limpa.
    responder("GET", URL_DASH, dashboardFake({ total_turmas: 0, total_alunos: 0, top10: [] }));
    renderComApp(<Dashboard />);

    expect(await screen.findByText("Bem-vindo(a) ao Constela Edu")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Comece aqui/ })).toBeInTheDocument();
    // Nada de indicadores nem ranking na tela limpa.
    expect(screen.queryByText("Top 10 — Ranking Geral")).not.toBeInTheDocument();
  });
});
