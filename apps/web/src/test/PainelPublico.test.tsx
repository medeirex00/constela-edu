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
