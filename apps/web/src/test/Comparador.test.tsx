/**
 * Comparador — as notas comparadas são POR MATÉRIA (Decisão 1 do dono,
 * 2026-10-12; plano de retirada, item 9). A tela lê o bloco `dimensoes` de cada
 * lado e não mais `notas.geral`/`notas.posicao` (que a API ainda manda por
 * contrato):
 *   1. um cartão por matéria, com a nota do aluno + "Nº de N na escola", ou a
 *      média da turma + "média de N alunos com dado";
 *   2. sem dado da matéria: "—" e o motivo, nunca 0,0;
 *   3. sem cartão "Nota Geral", e o valor legado não aparece;
 *   4. matéria fora do plano da rede não aparece.
 */
import { describe, expect, it } from "vitest";

import Comparador from "../pages/Comparador";
import { renderComApp, responder, screen, turmaFake, userEvent, usuarioFake, within } from "./utils";

const LADO_ALUNO = {
  tipo: "aluno", id: 10, nome: "Ana Beatriz Souza",
  indicadores: { livros_unicos: 12 },
  dimensoes: {
    leitura: { plataforma: "elefante", contratada: true, aferido: true, nota: 72.4, posicao: 3,
               n_aferidos: 21 },
    matematica: { plataforma: "matific", contratada: true, aferido: false, nota: null, posicao: null,
                  n_aferidos: 18 },
  },
  // LEGADO (contrato): a tela tem de ignorar.
  notas: { matific: 0, elefante: 72.4, geral: 85.5, posicao: 1 },
};

const LADO_TURMA = {
  tipo: "turma", id: 1, nome: "3º Ano A", total_alunos: 25,
  indicadores: { livros_unicos: 120 },
  dimensoes: {
    leitura: { plataforma: "elefante", contratada: true, aferido: true, nota: 68, posicao: null,
               n_aferidos: 18 },
    matematica: { plataforma: "matific", contratada: true, aferido: true, nota: 58.2, posicao: null,
                  n_aferidos: 1 },
  },
  notas: { matific: 58.2, elefante: 68, geral: 63.1, posicao: null },
};

function cartao(titulo: string): HTMLElement {
  return screen.getByText(titulo).closest(".card") as HTMLElement;
}

async function comparar(usuario = usuarioFake()) {
  responder("GET", "/escolas/1/turmas", [turmaFake({ id: 1, nome: "3º Ano A" })]);
  responder("GET", "/escolas/1/alunos", {
    total: 1, pagina: 1, por_pagina: 100, itens: [{ id: 10, nome: "Ana Beatriz Souza" }],
  });
  responder("GET", "/escolas/1/comparar", { a: LADO_ALUNO, b: LADO_TURMA });
  const u = userEvent.setup();
  renderComApp(<Comparador />, { usuario });

  const ladoA = screen.getByLabelText("Lado A");
  await within(ladoA).findByRole("option", { name: "Ana Beatriz Souza" });
  await u.selectOptions(ladoA, "10");
  const ladoB = screen.getByLabelText("Lado B");
  await within(ladoB).findByRole("option", { name: "3º Ano A" });
  await u.selectOptions(ladoB, "1");
  await u.click(screen.getByRole("button", { name: /Comparar/ }));
  await screen.findByText(/Indicadores lado a lado/);
}

describe("Comparador — notas por matéria", () => {
  it("um cartão por matéria, com posição e denominador do aluno e a média da turma", async () => {
    await comparar();

    const leitura = cartao("Nota de Leitura (média)");
    expect(within(leitura).getByText("72,4")).toBeInTheDocument();
    expect(within(leitura).getByText("3º de 21 na escola")).toBeInTheDocument();
    expect(within(leitura).getByText("68,0")).toBeInTheDocument();
    expect(within(leitura).getByText("média de 18 alunos com dado")).toBeInTheDocument();

    // Aluno sem Matific: "—" e o motivo — nunca 0,0 ao lado da média da turma.
    const matematica = cartao("Nota de Matemática (média)");
    expect(within(matematica).getByText("—")).toBeInTheDocument();
    expect(within(matematica).getByText("sem dado da plataforma")).toBeInTheDocument();
    expect(within(matematica).queryByText("0,0")).not.toBeInTheDocument();
    expect(within(matematica).getByText("58,2")).toBeInTheDocument();
    expect(within(matematica).getByText("média de 1 aluno com dado")).toBeInTheDocument();
  });

  it("não há cartão de Nota Geral e o valor legado não aparece", async () => {
    await comparar();

    expect(screen.queryByText(/Nota Geral/)).not.toBeInTheDocument();
    expect(screen.queryByText("85,5")).not.toBeInTheDocument();
    expect(screen.queryByText("63,1")).not.toBeInTheDocument();
  });

  it("rede só com Leitura: o cartão de Matemática não aparece", async () => {
    await comparar(usuarioFake({ modulos: ["leitura"] }));

    expect(screen.getByText("Nota de Leitura (média)")).toBeInTheDocument();
    expect(screen.queryByText(/Nota de Matemática/)).not.toBeInTheDocument();
  });
});
