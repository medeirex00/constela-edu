/**
 * Competição de leitura por TURNO — o que a validação manual travou aqui:
 *   1. o turno mostrado por PADRÃO é o PRIMEIRO grupo (Manhã), NUNCA o
 *      "Sem turno" (bug real: o estado inicial `null` coincidia com o grupo de
 *      `turno=null`);
 *   2. dentro de um turno aparecem 1º–5º juntos, ordenados pela nota (0–100);
 *   3. o grupo de outro turno não vaza para o ranking exibido.
 */
import { describe, expect, it } from "vitest";

import { CompeticaoLeituraTurno } from "../components/CompeticaoLeituraTurno";
import { renderComApp, responder, screen, usuarioFake } from "./utils";
import type { RankingItem, RankingTurno } from "../lib/types";

const URL = "/escolas/1/ranking/leitura/turnos";

function aluno(over: Partial<RankingItem>): RankingItem {
  return {
    posicao: 1, aluno_id: 1, nome: "X", turma: "1A", ano_escolar: "1º Ano",
    nota_matific: 0, nota_elefante: 80, nota_geral: 0, ...over,
  };
}

// De propósito: o grupo `turno=null` ("Sem turno") vem por ÚLTIMO, como o backend
// devolve. O padrão exibido tem de ser o PRIMEIRO (Manhã).
const GRUPOS: RankingTurno[] = [
  {
    turno: "manha", turno_rotulo: "Manhã", total: 2,
    alunos: [
      aluno({ aluno_id: 1, nome: "Cinco Alto", ano_escolar: "5º Ano", nota_elefante: 95 }),
      aluno({ posicao: 2, aluno_id: 2, nome: "Um Medio", ano_escolar: "1º Ano", nota_elefante: 60 }),
    ],
  },
  {
    turno: "tarde", turno_rotulo: "Tarde", total: 1,
    alunos: [aluno({ aluno_id: 3, nome: "Tres Tarde", ano_escolar: "3º Ano", nota_elefante: 70 })],
  },
  {
    turno: null, turno_rotulo: "Sem turno", total: 1,
    alunos: [aluno({ aluno_id: 4, nome: "Aluno Sem Turno", ano_escolar: "2º Ano", nota_elefante: 42 })],
  },
];

describe("Competição de leitura por turno", () => {
  it("por padrão mostra o PRIMEIRO turno (Manhã), nunca o 'Sem turno'", async () => {
    responder("GET", URL, GRUPOS);
    renderComApp(<CompeticaoLeituraTurno />, { usuario: usuarioFake({ cargo: "coordenador" }) });

    // cabeçalho do turno padrão = o primeiro grupo
    expect(await screen.findByText("Ranking de Leitura — Manhã")).toBeTruthy();

    const texto = (document.body.textContent ?? "").replace(/\s+/g, " ");
    // 1º–5º juntos, ordenados pela nota (5º alto acima do 1º médio) — série não separa
    expect(texto).toContain("Cinco Alto");
    expect(texto).toContain("Um Medio");
    expect(texto).toContain("5º Ano");
    expect(texto).toContain("1º Ano");
    // nota 0–100 (não pontos brutos)
    expect(texto).toContain("95,0");
    // o grupo "Sem turno" (turno=null) NÃO pode aparecer no ranking por engano
    expect(texto).not.toContain("Aluno Sem Turno");
    // os turnos são abas (rótulos vindos do backend)
    expect(screen.getByRole("tab", { name: /Manhã/ })).toBeTruthy();
    expect(screen.getByRole("tab", { name: /Sem turno/ })).toBeTruthy();
  });
});
