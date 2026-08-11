/**
 * "Como esta nota foi calculada" — a explicação tem de FECHAR com a nota.
 *
 * Numa rede que contratou um módulo só, o motor grava em `detalhes.geral.pesos`
 * apenas a plataforma contratada, com 100%. A tela não pode assumir a dupla
 * Matific + Elefante: se assumisse, exibiria "Matific 100 × 50% + Elefante 70 ×
 * 50% = 70" — uma conta que dá 85 terminando em 70, justamente no recurso que
 * existe para o professor auditar a nota.
 */
import { describe, expect, it } from "vitest";
import { Route, Routes } from "react-router-dom";

import PerfilAluno from "../pages/PerfilAluno";
import { renderComApp, responder, screen, usuarioFake } from "./utils";

const ALUNO = {
  id: 10, nome: "Ana Beatriz Souza", turma: "3º Ano A", ano_escolar: "3º Ano",
  status: "ativo",
};

function perfil(pesos: Record<string, number>, notaGeral: number) {
  return {
    aluno: ALUNO,
    posicao: 1,
    nota_matific: 100,
    nota_elefante: 70,
    nota_geral: notaGeral,
    ficha: {},
    detalhes: {
      matific: { indicadores: [], nota: 100 },
      elefante: { indicadores: [], questoes: null, nota: 70 },
      geral: { pesos, nota: notaGeral },
    },
  };
}

/** Renderiza o perfil e devolve o texto do cartão "Nota Geral" da seção de
 *  cálculo, com os espaços normalizados. */
async function contaExibida(pesos: Record<string, number>, notaGeral: number) {
  responder("GET", "/escolas/1/alunos/10/perfil", perfil(pesos, notaGeral));
  responder("GET", "/escolas/1/gamificacao/alunos/10", null);
  renderComApp(
    <Routes>
      <Route path="/alunos/:id" element={<PerfilAluno />} />
    </Routes>,
    { rota: "/alunos/10", usuario: usuarioFake({ cargo: "coordenador" }) },
  );
  await screen.findByText("Como esta nota foi calculada");
  // "Nota Geral" aparece duas vezes na página (o indicador do topo e o cartão do
  // cálculo). O do cálculo é o único cujo cartão traz a conta com "×".
  const cartao = screen.getAllByText("Nota Geral")
    .map((el) => el.parentElement)
    .find((pai) => (pai?.textContent ?? "").includes("×"));
  expect(cartao, "cartão da conta da Nota Geral não encontrado").toBeTruthy();
  return (cartao?.textContent ?? "").replace(/\s+/g, " ").trim();
}

describe("Explicação da Nota Geral", () => {
  it("ambos contratados: mostra as duas parcelas e fecha", async () => {
    const texto = await contaExibida({ matific: 50, elefante: 50 }, 85);
    // 100,0 × 0,50 + 70,0 × 0,50 = 85,0 — a conta exibida bate com a nota.
    expect(texto).toContain("Matific 100,0 × 50%");
    expect(texto).toContain("Elefante 70,0 × 50%");
    expect(texto).toContain("= 85,0");
  });

  it("só Leitura: mostra apenas o Elefante, com 100%, e fecha", async () => {
    const texto = await contaExibida({ elefante: 100 }, 70);
    expect(texto).toContain("Elefante 70,0 × 100%");
    expect(texto).not.toContain("Matific");   // a plataforma não contratada some
    expect(texto).toContain("= 70,0");
    expect(texto).not.toContain("+");         // uma parcela só: sem soma pendurada
  });

  it("só Matemática: mostra apenas o Matific, com 100%, e fecha", async () => {
    const texto = await contaExibida({ matific: 100 }, 100);
    expect(texto).toContain("Matific 100,0 × 100%");
    expect(texto).not.toContain("Elefante");
    expect(texto).toContain("= 100,0");
  });

  it("pesos personalizados da escola continuam sendo respeitados", async () => {
    const texto = await contaExibida({ matific: 60, elefante: 40 }, 88);
    expect(texto).toContain("Matific 100,0 × 60%");
    expect(texto).toContain("Elefante 70,0 × 40%");
    expect(texto).toContain("= 88,0");
  });
});
