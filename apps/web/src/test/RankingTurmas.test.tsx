/**
 * Ranking de TURMAS: ordena, no cliente, as turmas de `/resumo-escola` pela
 * MÉDIA das notas oficiais dos alunos aferidos na matéria escolhida. Turma sem
 * ninguém aferido na matéria NÃO entra (não há média para competir); o turno
 * global filtra pelas turmas do cadastro; só o módulo contratado aparece.
 */
import { describe, expect, it } from "vitest";

import RankingTurmas from "../pages/RankingTurmas";
import type { Turma } from "../lib/types";
import { renderComApp, responder, screen, turmaFake, userEvent, usuarioFake, within } from "./utils";

const URL_TURMAS = "/escolas/1/turmas";
const URL_RESUMO = "/escolas/1/resumo-escola";

const turmas: Turma[] = [
  turmaFake({ id: 1, nome: "3º Ano A", ano_escolar: "3º Ano", turno: "manha" }),
  turmaFake({ id: 2, nome: "3º Ano B", ano_escolar: "3º Ano", turno: "tarde" }),
  turmaFake({ id: 3, nome: "4º Ano A", ano_escolar: "4º Ano", turno: "manha" }),
];

function resumo(id: number, nome: string, ano: string, over: Record<string, unknown>) {
  return {
    turma: { id, nome, ano_escolar: ano }, total_alunos: 20,
    media_geral: 0, media_matific: 0, media_elefante: 0, indicadores: {},
    ...over,
  };
}

const RESUMO = {
  escola: { id: 1, nome: "Escola Modelo Constela" },
  turmas: [
    resumo(1, "3º Ano A", "3º Ano", { media_leitura: 70, n_leitura: 10, media_matematica: 55, n_matematica: 8 }),
    resumo(2, "3º Ano B", "3º Ano", { media_leitura: 85, n_leitura: 5, media_matematica: 0, n_matematica: 0 }),
    resumo(3, "4º Ano A", "4º Ano", { media_leitura: 0, n_leitura: 0, media_matematica: 90, n_matematica: 12 }),
  ],
};

/** Nomes das turmas na ordem em que aparecem na tabela. */
function ordem(): string[] {
  return within(screen.getByRole("table")).getAllByRole("link").map((l) => l.textContent ?? "");
}

describe("Ranking de Turmas", () => {
  it("ordena pela média de Leitura e deixa de fora a turma sem aluno aferido", async () => {
    responder("GET", URL_TURMAS, turmas);
    responder("GET", URL_RESUMO, RESUMO);
    renderComApp(<RankingTurmas />, { rota: "/ranking?ver=turmas" });

    expect(await screen.findByRole("link", { name: "3º Ano B" })).toBeInTheDocument();
    // 3º B (85) antes do 3º A (70); 4º A não tem ninguém aferido em Leitura.
    expect(ordem()).toEqual(["3º Ano B", "3º Ano A"]);
    expect(screen.queryByRole("link", { name: "4º Ano A" })).not.toBeInTheDocument();
    expect(screen.getByText("1º")).toBeInTheDocument();
    expect(screen.getByText("2º")).toBeInTheDocument();
    expect(screen.getByText("85,0")).toBeInTheDocument();
    // Colunas prometidas + denominador "aferidos de total".
    for (const coluna of ["Posição", "Turma", "Série", "Turno", "Média de Leitura", "Alunos aferidos"]) {
      expect(screen.getByRole("columnheader", { name: coluna })).toBeInTheDocument();
    }
    expect(screen.getByText("5 de 20")).toBeInTheDocument();
    expect(await screen.findAllByText("Tarde")).not.toHaveLength(0);
    // Explicação do critério (no cabeçalho da página e na barra de filtros).
    expect(screen.getAllByText(/média das notas oficiais/i).length).toBeGreaterThan(0);
  });

  it("troca a matéria para Matemática e reordena", async () => {
    responder("GET", URL_TURMAS, turmas);
    responder("GET", URL_RESUMO, RESUMO);
    const u = userEvent.setup();
    renderComApp(<RankingTurmas />, { rota: "/ranking?ver=turmas" });

    await screen.findByRole("link", { name: "3º Ano B" });
    await u.selectOptions(screen.getByLabelText("Matéria"), "matematica");

    expect(await screen.findByRole("link", { name: "4º Ano A" })).toBeInTheDocument();
    expect(ordem()).toEqual(["4º Ano A", "3º Ano A"]);
    expect(screen.queryByRole("link", { name: "3º Ano B" })).not.toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Média de Matemática" })).toBeInTheDocument();
  });

  it("respeita o turno global (filtra pelas turmas do cadastro)", async () => {
    responder("GET", URL_TURMAS, turmas);
    responder("GET", URL_RESUMO, RESUMO);
    const u = userEvent.setup();
    renderComApp(<RankingTurmas />, { rota: "/ranking?ver=turmas", turno: "manha" });

    // Manhã: só o 3º A tem Leitura (o 4º A é da manhã mas sem aferidos).
    expect(await screen.findByRole("link", { name: "3º Ano A" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "3º Ano B" })).not.toBeInTheDocument();
    expect(ordem()).toEqual(["3º Ano A"]);

    await u.selectOptions(screen.getByLabelText("Turno"), "tarde");
    expect(await screen.findByRole("link", { name: "3º Ano B" })).toBeInTheDocument();
    expect(ordem()).toEqual(["3º Ano B"]);
  });

  it("estado vazio quando nenhuma turma tem aluno aferido na matéria", async () => {
    responder("GET", URL_TURMAS, turmas);
    responder("GET", URL_RESUMO, {
      ...RESUMO,
      turmas: [resumo(1, "3º Ano A", "3º Ano", { media_leitura: 0, n_leitura: 0 })],
    });
    renderComApp(<RankingTurmas />, { rota: "/ranking?ver=turmas" });

    expect(await screen.findByText("Nenhuma turma com alunos aferidos em Leitura")).toBeInTheDocument();
  });

  it("rede só com Leitura: não há seletor de matéria", async () => {
    responder("GET", URL_TURMAS, turmas);
    responder("GET", URL_RESUMO, RESUMO);
    renderComApp(<RankingTurmas />, {
      rota: "/ranking?ver=turmas",
      usuario: usuarioFake({ modulos: ["leitura"] }),
    });

    expect(await screen.findByRole("link", { name: "3º Ano B" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Matéria")).not.toBeInTheDocument();
  });
});
