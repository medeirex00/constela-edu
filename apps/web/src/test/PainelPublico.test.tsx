/**
 * Painel Público (telão da escola): um erro TRANSITÓRIO (rede caiu, servidor
 * reiniciando) não pode virar "Painel não encontrado ou desativado" — isso é
 * reservado ao token inválido/painel desativado de verdade (404).
 */
import { Route, Routes } from "react-router-dom";
import { vi } from "vitest";

import PainelPublico from "../pages/publico/PainelPublico";
import { ApiError, renderComApp, responder, responderErro, screen } from "./utils";

function abrirPainel(token = "tok123") {
  return renderComApp(
    <Routes>
      <Route path="/p/:token" element={<PainelPublico />} />
    </Routes>,
    { rota: `/p/${token}`, autenticado: false },
  );
}

const painelFake = () => ({
  escola: { nome: "Escola do Telão", cor_primaria: "#123456" },
  slides: ["ranking"],
  intervalo_s: 8,
  ranking: [],
  evolucao: [],
  destaques: { dia: null, semana: null, mes: null },
  mural: [],
});

test("erro transitório (sem rede, status 0) mostra 'Reconectando', não 'não encontrado'", async () => {
  responderErro("GET", /\/publico\/.+\/painel/, 0, "sem rede");
  abrirPainel();

  expect(await screen.findByText(/Reconectando ao painel/i)).toBeInTheDocument();
  expect(screen.queryByText(/não encontrado ou desativado/i)).toBeNull();
});

test("erro transitório (5xx) também mostra 'Reconectando'", async () => {
  responderErro("GET", /\/publico\/.+\/painel/, 503, "indisponível");
  abrirPainel();

  expect(await screen.findByText(/Reconectando ao painel/i)).toBeInTheDocument();
});

test("erro transitório (timeout 408) também mostra 'Reconectando'", async () => {
  responderErro("GET", /\/publico\/.+\/painel/, 408, "timeout");
  abrirPainel();

  expect(await screen.findByText(/Reconectando ao painel/i)).toBeInTheDocument();
});

test("token inválido/painel desativado (404) mostra 'não encontrado ou desativado'", async () => {
  responderErro("GET", /\/publico\/.+\/painel/, 404, "not found");
  abrirPainel();

  expect(await screen.findByText(/não encontrado ou desativado/i)).toBeInTheDocument();
});

test("erro transitório APÓS carregar mantém o último quadro (o telão não pisca)", async () => {
  vi.useFakeTimers();
  try {
    let n = 0;
    responder("GET", /\/publico\/.+\/painel/, () => {
      n += 1;
      return n === 1 ? painelFake() : new ApiError(0, "sem rede");
    });
    abrirPainel();
    await vi.advanceTimersByTimeAsync(0); // resolve a 1ª carga
    expect(screen.getByText("Escola do Telão")).toBeInTheDocument();

    await vi.advanceTimersByTimeAsync(60_000); // refresh de 60s falha (transitório)
    // Regressão original: os dados eram trocados por "não encontrado". Agora não.
    expect(screen.getByText("Escola do Telão")).toBeInTheDocument();
    expect(screen.queryByText(/Reconectando|não encontrado/i)).toBeNull();
  } finally {
    vi.useRealTimers();
  }
});

test("usa o fundo COMPARTILHADO com a vitrine (aria-hidden, sem o SVG esticado) e o nome inteiro no h1", async () => {
  responder("GET", /\/publico\/.+\/painel/, {
    ...painelFake(),
    escola: { nome: "EMEI/EMEF PROFª ESCOLA INVENTADA DO TELÃO COM NOME LONGO", cor_primaria: "#123456" },
  });
  abrirPainel();

  const h1 = await screen.findByRole("heading", { level: 1 });
  // Nome inteiro no DOM (leitor de tela) e no title; o visual quebra em até 2 linhas.
  expect(h1).toHaveTextContent("EMEI/EMEF PROFª ESCOLA INVENTADA DO TELÃO COM NOME LONGO");
  expect(h1).toHaveAttribute("title", "EMEI/EMEF PROFª ESCOLA INVENTADA DO TELÃO COM NOME LONGO");
  expect(h1).toHaveClass("line-clamp-2");
  expect(h1).not.toHaveClass("truncate");
  // Fim da cópia duplicada do fundo: o telão monta o FundoConstela da vitrine.
  const fundos = document.querySelectorAll("[data-fundo-constela]");
  expect(fundos).toHaveLength(1);
  expect(fundos[0]).toHaveAttribute("aria-hidden", "true");
  expect(document.querySelector('svg[preserveAspectRatio="none"]')).toBeNull();
});

test("valor ausente aparece como ausência ('—', 'sem dado'), nunca como 0 — e a tela não quebra", async () => {
  responder("GET", /\/publico\/.+\/painel/, {
    ...painelFake(),
    slides: ["evolucao"],
    // A 2ª criança chega SEM o valor (campo ausente): antes virava "0,0" e barra de 6%.
    evolucao: [
      { posicao: 1, aluno_id: 1, nome: "Aluna Teste A", turma: null, nota_evolucao: 12.5 },
      { posicao: 2, aluno_id: 2, nome: "Aluno Teste B", turma: null },
    ],
    // Plataforma sem coleta: a faixa diz "—", não "0 livros lidos".
    estatisticas: { alunos: 30, atividades: 120, estrelas: 400, livros: null },
  });
  abrirPainel();

  const linhaB = (await screen.findByText("Aluno Teste B")).parentElement as HTMLElement;
  expect(linhaB).toHaveTextContent("sem dado");
  expect(linhaB).not.toHaveTextContent(/\b0,0\b/);
  expect((linhaB.querySelector("[data-barra]") as HTMLElement).style.width).toBe("0%");
  const numeros = screen.getByRole("region", { name: "Números da escola" });
  expect(numeros).toHaveTextContent("Livros lidos");
  expect(numeros).toHaveTextContent("sem dado");
  expect(numeros).toHaveTextContent("400");
});

test("posições em texto para o leitor de tela; o ponto do slide atual tem aria-current", async () => {
  responder("GET", /\/publico\/.+\/painel/, {
    ...painelFake(),
    slides: ["evolucao", "mural"],
    evolucao: [1, 2, 3, 4].map((p) => ({
      posicao: p, aluno_id: p, nome: `Aluna Teste ${p}`, turma: null, nota_evolucao: 20 - p,
    })),
  });
  abrirPainel();
  await screen.findByText("Aluna Teste 1");
  // Medalha = emoji decorativo + "Nº lugar" oculto (aria-label num <span> não é lido).
  expect(screen.getByText("1º lugar")).toHaveClass("sr-only");
  expect(screen.getByText("3º lugar")).toHaveClass("sr-only");
  expect((screen.getByText("Aluna Teste 4").parentElement as HTMLElement)).toHaveTextContent("4º lugar");
  expect(screen.getByRole("button", { name: "Ir para Quem mais cresceu" })).toHaveAttribute("aria-current", "true");
  expect(screen.getByRole("button", { name: "Ir para Mural da Escola" })).not.toHaveAttribute("aria-current");
});

test("o aviso de erro é anunciado (role=status)", async () => {
  responderErro("GET", /\/publico\/.+\/painel/, 404, "not found");
  abrirPainel();
  expect(await screen.findByText(/não encontrado ou desativado/i)).toHaveAttribute("role", "status");
});
