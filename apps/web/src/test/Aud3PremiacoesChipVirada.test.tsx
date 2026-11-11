/**
 * REG_TELAS-2 / REG_NUMEROS-7 — o chip "Fim do Nº bimestre" das Premiações na virada.
 *
 * Desde a PERIODOS-2 o "Nº bimestre" é resolvido pelo backend no ANO LETIVO da escola. Em
 * fevereiro e março de 2027, com o calendário de 2027 cadastrado e a escola ainda em 2026
 * (a troca do ano letivo é manual), o "1º bimestre" é o de 2026, já encerrado — e a web
 * punha ao lado dele o chip do 1º bimestre de 2027, que estava em curso, como se aquele
 * pódio ainda estivesse em disputa. O chip vale só quando o período RESPONDIDO contém hoje.
 *
 * Datas de 2027 e nomes fictícios.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import Premiacoes from "../pages/Premiacoes";
import { renderComApp, responder, screen, turmaFake } from "./utils";

const CAL_2027 = {
  ano: 2027,
  bimestres: [
    { numero: 1, inicio: "2027-02-01", fim: "2027-04-23" },
    { numero: 2, inicio: "2027-04-26", fim: "2027-07-09" },
    { numero: 3, inicio: "2027-07-26", fim: "2027-10-01" },
    { numero: 4, inicio: "2027-10-04", fim: "2027-12-17" },
  ],
};

const categoria = {
  chave: "melhor_leitor", titulo: "Melhor Leitor", icone: "x", descricao: "d", unidade: "pontos",
  podio: [{ posicao: 1, aluno_id: 1, nome: "Criança Fictícia", turma: "3A", valor: 5 }],
};

function cenario(hoje: Date, periodo: { chave: string; rotulo: string; inicio: string; fim: string }) {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(hoje);
  responder("GET", "/escolas/1/turmas", [turmaFake({ id: 1, nome: "3º Ano A", turno: "manha" })]);
  responder("GET", "/escolas/1/configuracoes/calendario-bimestres", CAL_2027);
  responder("GET", "/escolas/1/premiacoes", { periodo, categorias: [categoria], turnos: [] });
  responder("GET", "/escolas/1/ranking-evolucao", []);
}

/** O que o backend devolve para ?periodo=bimestre_1 com a escola no ano letivo 2026. */
const PRIMEIRO_DE_2026 = {
  chave: "bimestre_1", rotulo: "1º bimestre de 2026 (02/02 a 22/04)",
  inicio: "2026-02-02T00:00:00", fim: "2026-04-22T23:59:59.999999",
};
/** E com a escola já em 2027 (ou para "Este bimestre", que segue o relógio). */
const PRIMEIRO_DE_2027 = {
  chave: "bimestre_1", rotulo: "1º bimestre (01/02 a 23/04)",
  inicio: "2027-02-01T00:00:00", fim: "2027-04-23T23:59:59.999999",
};

describe("Premiações — chip do fim do bimestre na virada do ano", () => {
  afterEach(() => vi.useRealTimers());

  it.each([
    ["01/03/2027", new Date(2027, 2, 1, 12, 0, 0)],
    ["10/03/2027", new Date(2027, 2, 10, 12, 0, 0)],
  ])("'1º bimestre' de 2026 (escola ainda em 2026) em %s: sem o chip do 1º de 2027", async (_, hoje) => {
    cenario(hoje, PRIMEIRO_DE_2026);
    renderComApp(<Premiacoes />, { periodo: { preset: "bimestre_1" } });

    expect(await screen.findByText("1º bimestre de 2026 (02/02 a 22/04)")).toBeInTheDocument();
    // O pódio já chegou; o calendário de 2027 também (o chip do 1º dele estaria aqui).
    await new Promise((r) => setTimeout(r, 30));
    expect(screen.queryByText(/Fim do \d+º bimestre/)).not.toBeInTheDocument();
    expect(screen.queryByText(/bimestre termina hoje/)).not.toBeInTheDocument();
  });

  it("'1º bimestre' com a escola já em 2027: o chip continua", async () => {
    cenario(new Date(2027, 2, 10, 12, 0, 0), PRIMEIRO_DE_2027);
    renderComApp(<Premiacoes />, { periodo: { preset: "bimestre_1" } });

    expect(await screen.findByText("Fim do 1º bimestre · em 44 dias")).toBeInTheDocument();
  });

  it("'Este bimestre' (segue o relógio) com a escola ainda em 2026: o chip continua", async () => {
    cenario(new Date(2027, 2, 1, 12, 0, 0), { ...PRIMEIRO_DE_2027, chave: "bimestre" });
    renderComApp(<Premiacoes />, { periodo: { preset: "bimestre" } });

    expect(await screen.findByText("Fim do 1º bimestre · em 53 dias")).toBeInTheDocument();
  });
});
