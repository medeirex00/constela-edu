/**
 * G_MODULOS-4 (web) — o Comparador não mostra o módulo fora do plano da rede.
 *
 * Numa rede só com Leitura, a tela mostrava "Nota Matific" e o grupo
 * "Matemática · Matific" (atividades, estrelas). Agora a nota e o grupo do módulo
 * não contratado não aparecem (nem zerados). O Admin Global (que compara escolas de
 * redes diferentes) continua vendo os dois, e o lado sem o módulo chega nulo: "—".
 */
import { describe, expect, it } from "vitest";

import Comparador from "../pages/Comparador";
import type { PaginaAlunos, Turma } from "../lib/types";
import { renderComApp, responder, screen, turmaFake, userEvent, usuarioFake, within } from "./utils";

const ALUNOS = {
  total: 2, pagina: 1, por_pagina: 100,
  itens: [{ id: 7, nome: "Aluna Inventada" }, { id: 8, nome: "Aluno Inventado" }],
} as unknown as PaginaAlunos;

function lado(id: number, nome: string, matematica: boolean) {
  return {
    tipo: "aluno", id, nome,
    indicadores: {
      atividades: matematica ? 30 : null, estrelas: matematica ? 600 : null,
      pontuacao_media: matematica ? 3.5 : null, livros_unicos: 4,
      tempo_leitura_min: 50, questoes_tentativas: 10, questoes_acertos: 8,
    },
    notas: { matific: matematica ? 100 : null, elefante: 70, geral: 70, posicao: 1 },
  };
}

async function comparar(usuario = usuarioFake({ modulos: ["leitura"] }), matematicaB = false) {
  responder("GET", "/escolas/1/turmas", [turmaFake({ id: 3, nome: "3º Ano A" })] as Turma[]);
  responder("GET", "/escolas/1/alunos", ALUNOS);
  responder("GET", "/escolas", []);
  responder("GET", "/escolas/1/comparar", {
    a: lado(7, "Aluna Inventada", false), b: lado(8, "Aluno Inventado", matematicaB),
  });
  const u = userEvent.setup();
  renderComApp(<Comparador />, { rota: "/comparador", usuario });
  await screen.findByRole("option", { name: "Aluna Inventada" });
  // Lado B começa em "turma": a resposta fingida da API é que manda nos números.
  await u.selectOptions(screen.getByLabelText("Lado A"), "7");
  await u.selectOptions(screen.getByLabelText("Lado B"), "3");
  await u.click(screen.getByRole("button", { name: "Comparar" }));
  await screen.findByText("Nota Elefante Letrado");
}

describe("Comparador e o contrato da rede", () => {
  it("rede só com Leitura: sem 'Nota Matific' nem o grupo do Matific", async () => {
    await comparar();
    expect(screen.queryByText(/Nota Matific/)).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Matemática · Matific" })).not.toBeInTheDocument();
    expect(screen.queryByText("Atividades (Matific)")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Leitura · Elefante Letrado" })).toBeInTheDocument();
    expect(screen.getByText("Nota Geral")).toBeInTheDocument();
  });

  it("Admin Global vê as duas; o lado sem o módulo mostra '—', não 0,0", async () => {
    await comparar(usuarioFake({ is_global: true, cargo: "admin" }), true);
    const cartao = (await screen.findByText(/^Nota Matific/)).closest(".card") as HTMLElement;
    expect(within(cartao).getByText("—")).toBeInTheDocument();
    expect(within(cartao).getByText("100,0")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Matemática · Matific" })).toBeInTheDocument();
  });
});
