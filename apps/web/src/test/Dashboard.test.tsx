/**
 * Painel da ESCOLA. O "Top 5 — Ranking Geral" (ordem única pela nota geral,
 * vinda do `top10` do `/dashboard`) virou um Top 5 POR MATÉRIA contratada, lido
 * da classificação oficial `/ranking?dimensao=` — Decisão 1 do dono
 * (2026-10-12), plano de retirada itens 4 e 7. Os testes do Top 5 antigo foram
 * reescritos porque a regra aprovada mudou; o `/dashboard` ainda manda o
 * `top10` legado (o app em campo lê), e a tela tem de IGNORÁ-LO.
 */
import { describe, expect, it } from "vitest";

import type { RankingItem } from "../lib/types";
import Dashboard from "../pages/Dashboard";
import {
  api,
  dashboardFake,
  rankingItemFake,
  renderComApp,
  responder,
  responderErro,
  screen,
  usuarioFake,
  waitFor,
  within,
} from "./utils";

const URL_DASH = "/escolas/1/dashboard";
const URL_RANKING = "/escolas/1/ranking";

const parametros = (caminho: string) => new URLSearchParams(caminho.split("?")[1] ?? "");
const chamadasRanking = () =>
  api.mock.calls.map((c) => String(c[0]))
    .filter((p) => p === URL_RANKING || p.startsWith(`${URL_RANKING}?`));

/** Item da classificação POR MATÉRIA (como a API carimba com `?dimensao=`). */
function itemMateria(over: Partial<RankingItem> = {}): RankingItem {
  return { ...rankingItemFake(), aferido: true, n_aferidos: 30, ...over };
}

/** `/ranking?dimensao=` responde por matéria: Leitura com 6 aferidos (o Top 5
 *  corta), Matemática com 1. */
function mockarTopPorMateria() {
  responder("GET", URL_RANKING, (caminho: string) =>
    parametros(caminho).get("dimensao") === "matematica"
      ? [itemMateria({ aluno_id: 30, nome: "Davi Contas", dimensao: "matematica", nota: 77,
                       n_aferidos: 1 })]
      : Array.from({ length: 6 }, (_, i) => itemMateria({
        posicao: i + 1, aluno_id: 40 + i, nome: `Leitor ${i + 1}`, dimensao: "leitura",
        nota: 95 - i, n_aferidos: 6,
      })));
}

/** O cartão do Top 5 de uma matéria (a partir do título). */
function cartaoTop(rotulo: string): HTMLElement {
  const titulo = screen.getByRole("heading", { name: `Top 5 — ${rotulo}` });
  return titulo.closest(".card") as HTMLElement;
}

describe("Dashboard", () => {
  it("mostra os indicadores e um Top 5 por matéria, pela nota da matéria", async () => {
    responder("GET", URL_DASH, dashboardFake());
    mockarTopPorMateria();
    renderComApp(<Dashboard />);

    // Cartões de indicadores.
    expect(await screen.findByText("Alunos")).toBeInTheDocument();
    expect(screen.getByText("42")).toBeInTheDocument(); // total_alunos
    expect(screen.getByText("Professores")).toBeInTheDocument();

    // Top 5 de LEITURA: corta em 5, mostra a nota da matéria e o denominador.
    expect(await screen.findByRole("link", { name: "Leitor 1" })).toBeInTheDocument();
    const leitura = cartaoTop("Leitura");
    expect(within(leitura).getAllByRole("listitem")).toHaveLength(5);
    expect(within(leitura).queryByRole("link", { name: "Leitor 6" })).not.toBeInTheDocument();
    expect(within(leitura).getByText("95,0")).toBeInTheDocument();
    expect(within(leitura).getByText("6 alunos aferidos em Leitura")).toBeInTheDocument();
    expect(within(leitura).getByRole("link", { name: /Ver classificação completa/ }))
      .toHaveAttribute("href", "/ranking?materia=leitura");

    // Top 5 de MATEMÁTICA, independente.
    expect(await screen.findByRole("link", { name: "Davi Contas" })).toBeInTheDocument();
    const matematica = cartaoTop("Matemática");
    expect(within(matematica).getByText("77,0")).toBeInTheDocument();
    expect(within(matematica).getByText("1 aluno aferido em Matemática")).toBeInTheDocument();

    // A ordem única saiu do painel: nem o título antigo, nem os alunos do
    // `top10` legado (que o /dashboard ainda manda).
    expect(screen.queryByText("Top 5 — Ranking Geral")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "João Pedro Barbosa" })).not.toBeInTheDocument();
    // Toda consulta ao /ranking leva a dimensão.
    expect(chamadasRanking().every((p) => parametros(p).has("dimensao"))).toBe(true);
  });

  it("rede só com Leitura: um Top 5 só, e nenhuma consulta de Matemática", async () => {
    responder("GET", URL_DASH, dashboardFake());
    mockarTopPorMateria();
    renderComApp(<Dashboard />, { usuario: usuarioFake({ modulos: ["leitura"] }) });

    expect(await screen.findByRole("link", { name: "Leitor 1" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Top 5 — Leitura" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Top 5 — Matemática" })).not.toBeInTheDocument();
    expect(chamadasRanking().some((p) => parametros(p).get("dimensao") === "matematica")).toBe(false);
  });

  it("matéria sem ninguém aferido mostra o estado vazio da matéria", async () => {
    responder("GET", URL_DASH, dashboardFake());
    responder("GET", URL_RANKING, []);
    renderComApp(<Dashboard />);

    expect(await screen.findByText("Ainda não há alunos aferidos em Leitura")).toBeInTheDocument();
    expect(screen.getByText("Ainda não há alunos aferidos em Matemática")).toBeInTheDocument();
  });

  it("falha do ranking de uma matéria fica no cartão dela (o painel continua)", async () => {
    responder("GET", URL_DASH, dashboardFake());
    responderErro("GET", URL_RANKING, 500, "Erro interno");
    renderComApp(<Dashboard />);

    expect(await screen.findByText("Não foi possível carregar o Top 5 de Leitura")).toBeInTheDocument();
    expect(screen.getByText("Alunos")).toBeInTheDocument();
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
    // Nada de indicadores nem ranking na tela limpa — e nem a consulta dele.
    expect(screen.queryByText(/Top 5/)).not.toBeInTheDocument();
    await waitFor(() => expect(chamadasRanking()).toHaveLength(0));
  });
});
