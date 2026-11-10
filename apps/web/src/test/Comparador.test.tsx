/**
 * Comparador (aluno×aluno, aluno×turma, turma×turma; escola×escola só no global):
 * a tela pede `/comparar` com os dois lados escolhidos e mostra as notas e os
 * indicadores EXATAMENTE como a API devolve (sem calcular diferença nem média);
 * o lado "Escola" só existe para o Admin Global; a busca de alunos da escola traz só
 * os 100 primeiros e a tela diz isso quando há mais — e a turma do aluno (em cada
 * lado) traz todos os alunos dela, então ninguém fica fora do alcance.
 */
import { describe, expect, it } from "vitest";

import Comparador from "../pages/Comparador";
import type { PaginaAlunos, Turma } from "../lib/types";
import {
  api, renderComApp, responder, responderErro, screen, turmaFake, userEvent, usuarioFake, within,
} from "./utils";

const ALUNOS = {
  total: 2, pagina: 1, por_pagina: 100,
  itens: [
    { id: 7, nome: "Ana Beatriz Souza" },
    { id: 8, nome: "Bruno Lima" },
  ],
} as unknown as PaginaAlunos;

function lado(tipo: string, id: number, nome: string, notas: Record<string, number | null>, extra = {}) {
  return {
    tipo, id, nome,
    indicadores: {
      atividades: 12, estrelas: 40, pontuacao_media: 3.33, livros_unicos: 9,
      tempo_leitura_min: 125, questoes_tentativas: 30, questoes_acertos: 21,
    },
    notas: { matific: 80, elefante: 90, geral: 85, posicao: null, ...notas },
    ...extra,
  };
}

function preparar(alunos: PaginaAlunos = ALUNOS) {
  responder("GET", "/escolas/1/turmas", [turmaFake({ id: 3, nome: "3º Ano A" })] as Turma[]);
  responder("GET", "/escolas/1/alunos", alunos);
}

describe("Comparador", () => {
  it("compara aluno × turma com os números da API e diz que nota de turma é média", async () => {
    preparar();
    responder("GET", "/escolas/1/comparar", {
      a: lado("aluno", 7, "Ana Beatriz Souza", { posicao: 4 }),
      b: lado("turma", 3, "3º Ano A", { matific: 70.5, elefante: 66, geral: 68.25 }, { total_alunos: 28 }),
    });
    const u = userEvent.setup();
    renderComApp(<Comparador />, { rota: "/comparador" });

    expect(screen.getByText("Escolha os dois lados e clique em Comparar")).toBeInTheDocument();
    // Celular: o estado vazio tem folga lateral (o texto ia de borda a borda do cartão).
    expect(screen.getByText("Escolha os dois lados e clique em Comparar").parentElement).toHaveClass("px-5");
    const comparar = screen.getByRole("button", { name: "Comparar" });
    expect(comparar).toBeDisabled();

    await screen.findByRole("option", { name: "Ana Beatriz Souza" });
    await u.selectOptions(screen.getByLabelText("Lado A"), "7");
    await u.selectOptions(screen.getByLabelText("Lado B"), "3");
    await u.click(comparar);

    expect(await screen.findByText("Nota Matific (média)")).toBeInTheDocument();
    const chamada = api.mock.calls.map((c) => String(c[0])).find((c) => c.startsWith("/escolas/1/comparar?"));
    expect(chamada).toBe("/escolas/1/comparar?tipo_a=aluno&id_a=7&tipo_b=turma&id_b=3");
    // Notas como vieram (a turma é média; nada calculado na tela).
    const cartaoMatific = screen.getByText("Nota Matific (média)").closest(".card") as HTMLElement;
    expect(within(cartaoMatific).getByText("80,0")).toBeInTheDocument();
    expect(within(cartaoMatific).getByText("70,5")).toBeInTheDocument();
    // Posição no Ranking Geral do aluno e o tamanho da turma, quando a API manda.
    expect(screen.getByText("4º no Ranking Geral")).toBeInTheDocument();
    expect(screen.getByText("28 aluno(s)")).toBeInTheDocument();
    // Indicadores agrupados por plataforma, com os dois lados.
    expect(screen.getByRole("heading", { name: "Leitura · Elefante Letrado" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Matemática · Matific" })).toBeInTheDocument();
    expect(screen.getAllByText("2h 5min")).toHaveLength(2);
  });

  it("Escola como lado só para o Admin Global", async () => {
    preparar();
    responder("GET", "/escolas", [{ id: 1, nome: "Escola Modelo Constela" }]);
    const { unmount } = renderComApp(<Comparador />, { rota: "/comparador" });
    await screen.findByRole("option", { name: "Ana Beatriz Souza" });
    expect(within(screen.getByLabelText("Lado A — tipo")).queryByRole("option", { name: "Escola" }))
      .not.toBeInTheDocument();
    unmount();

    preparar();
    renderComApp(<Comparador />, {
      rota: "/comparador", usuario: usuarioFake({ cargo: "admin", is_global: true }),
    });
    expect(await within(screen.getByLabelText("Lado A — tipo")).findByRole("option", { name: "Escola" }))
      .toBeInTheDocument();
  });

  it("avisa quando a escola tem mais alunos que os 100 da lista e mostra o erro da API", async () => {
    preparar({ ...ALUNOS, total: 340 } as PaginaAlunos);
    responderErro("GET", "/escolas/1/comparar", 403, "Sem permissão para comparar este aluno.");
    const u = userEvent.setup();
    renderComApp(<Comparador />, { rota: "/comparador" });

    expect(await screen.findByText(/A lista de alunos mostra os 2 primeiros de 340 da escola\. Para achar qualquer aluno, escolha antes a turma dele\./))
      .toBeInTheDocument();
    await u.selectOptions(screen.getByLabelText("Lado A"), "7");
    await u.selectOptions(screen.getByLabelText("Lado B — tipo"), "aluno");
    await u.selectOptions(screen.getByLabelText("Lado B"), "8");
    await u.click(screen.getByRole("button", { name: "Comparar" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Sem permissão para comparar este aluno.");
  });

  it("escola grande: o aluno fora dos 100 primeiros é alcançável pela turma dele", async () => {
    // A 1ª página da escola (100 de 340) não traz o Zeca; a página da turma dele, sim.
    const daTurma = {
      total: 2, pagina: 1, por_pagina: 1000,
      itens: [{ id: 7, nome: "Ana Beatriz Souza" }, { id: 412, nome: "Zeca Depois Dos Cem" }],
    } as unknown as PaginaAlunos;
    responder("GET", "/escolas/1/turmas", [turmaFake({ id: 3, nome: "3º Ano A" })] as Turma[]);
    responder("GET", "/escolas/1/alunos",
      (caminho: string) => (caminho.includes("turma_id=3") ? daTurma : { ...ALUNOS, total: 340 }));
    responder("GET", "/escolas/1/comparar", {
      a: lado("aluno", 412, "Zeca Depois Dos Cem", {}),
      b: lado("turma", 3, "3º Ano A", {}, { total_alunos: 28 }),
    });
    const u = userEvent.setup();
    renderComApp(<Comparador />, { rota: "/comparador" });

    await screen.findByRole("option", { name: "Ana Beatriz Souza" });
    expect(screen.queryByRole("option", { name: "Zeca Depois Dos Cem" })).not.toBeInTheDocument();
    await u.selectOptions(screen.getByLabelText("Lado A — turma do aluno"), "3");
    const opcao = await within(screen.getByLabelText("Lado A")).findByRole("option", { name: "Zeca Depois Dos Cem" });
    // Só a turma escolhida, numa página que cabe a turma inteira.
    const pedido = api.mock.calls.map((c) => String(c[0])).find((c) => c.includes("turma_id=3"));
    expect(pedido).toBe("/escolas/1/alunos?turma_id=3&por_pagina=1000");
    await u.selectOptions(screen.getByLabelText("Lado A"), opcao);
    await u.selectOptions(screen.getByLabelText("Lado B"), "3");
    await u.click(screen.getByRole("button", { name: "Comparar" }));
    expect(await screen.findByText("Nota Matific (média)")).toBeInTheDocument();
    expect(api.mock.calls.map((c) => String(c[0])))
      .toContain("/escolas/1/comparar?tipo_a=aluno&id_a=412&tipo_b=turma&id_b=3");
  });

  it("o lado Turma não ganha o filtro de turma do aluno", async () => {
    preparar();
    renderComApp(<Comparador />, { rota: "/comparador" });
    await screen.findByRole("option", { name: "Ana Beatriz Souza" });
    expect(screen.getByLabelText("Lado A — turma do aluno")).toBeInTheDocument();
    expect(screen.queryByLabelText("Lado B — turma do aluno")).not.toBeInTheDocument();
  });
});
