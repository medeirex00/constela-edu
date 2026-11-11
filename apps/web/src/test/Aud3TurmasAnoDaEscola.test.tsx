/**
 * Turmas com a escola selecionada FORA da lista da sessão (S_G_VIRADA-5).
 *
 * O GET /escolas da sessão só traz as escolas ativas. Quando o Admin Global abre
 * uma escola inativa (Escolas › Usuários › “Gestão completa”) ou inativa a escola
 * que está aberta, o `escolaAtual` do contexto ficava nulo e Turmas caía no ano do
 * RELÓGIO: em janeiro de 2027, numa escola ainda em 2026, a tela dizia “Turmas
 * ativas em 2027 · Nenhuma turma ativa em 2027”, escondia as turmas de 2026 e o
 * formulário de turma nova nascia em 2027. Agora o contexto busca a escola aberta
 * fora da lista (com as inativas) e a tela nunca supõe o ano. Dados fictícios.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import Turmas from "../pages/Turmas";
import {
  autenticar,
  escolaFake,
  renderComApp,
  responder,
  responderErro,
  screen,
  turmaFake,
  userEvent,
  usuarioFake,
  within,
} from "./utils";

afterEach(() => {
  vi.useRealTimers();
});

const GLOBAL = usuarioFake({ is_global: true, cargo: "admin" });
const ATIVA = escolaFake({ id: 1, nome: "Escola Ficticia Aberta", ano_letivo_ativo: 2026 });
const INATIVA = escolaFake({
  id: 2, nome: "Escola Ficticia Inativa", ano_letivo_ativo: 2026, status: "inativa",
});

function janeiroDe2027() {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2027-01-15T12:00:00-03:00"));
}

function turmasDaInativa() {
  responder("GET", "/escolas/2/turmas", [
    turmaFake({ id: 5, nome: "3º Ano A", ano_letivo: 2026, status: "ativa", total_alunos: 20 }),
  ]);
  responder("GET", "/escolas/2/professores", []);
}

describe("Turmas da escola aberta fora da lista da sessão", () => {
  it("escola inativa aberta pelo Admin Global em janeiro de 2027 mostra o ano dela (2026)", async () => {
    janeiroDe2027();
    // A sessão só lista a escola ativa; a lista com as inativas traz a escola aberta.
    autenticar(GLOBAL, [ATIVA]);
    responder("GET", /incluir_inativas=true/, [ATIVA, INATIVA]);
    turmasDaInativa();
    const u = userEvent.setup();
    renderComApp(<Turmas />, { rota: "/turmas", autenticado: false, escolaSelecionada: 2 });

    const cartao = await screen.findByText("Turmas ativas em 2026");
    expect(within(cartao.parentElement as HTMLElement).getByText("1", { exact: true }))
      .toBeInTheDocument();
    expect(await screen.findByRole("link", { name: "3º Ano A" })).toBeInTheDocument();
    expect(screen.queryByText(/2027/)).toBeNull();

    // A turma nova nasce no ano letivo da escola, não no do relógio.
    await u.click(screen.getByRole("button", { name: /Adicionar Turma/ }));
    expect(await screen.findByDisplayValue("2026")).toBeInTheDocument();
    expect(screen.queryByDisplayValue("2027")).toBeNull();
  });

  it("sem conseguir saber o ano da escola, não supõe o do relógio: mostra todas as turmas", async () => {
    janeiroDe2027();
    autenticar(GLOBAL, [ATIVA]);
    responderErro("GET", /incluir_inativas=true/, 500, "Erro interno");
    turmasDaInativa();
    renderComApp(<Turmas />, { rota: "/turmas", autenticado: false, escolaSelecionada: 2 });

    expect(await screen.findByRole("link", { name: "3º Ano A" })).toBeInTheDocument();
    expect(screen.getByText("Todas as turmas")).toBeInTheDocument();
    expect(screen.queryByText(/2027/)).toBeNull();
    expect(screen.queryByText(/Nenhuma turma ativa/)).toBeNull();
  });
});
