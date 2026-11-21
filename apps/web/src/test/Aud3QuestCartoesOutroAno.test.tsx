/**
 * Painel de uma turma de OUTRO ano letivo (S_G_QUEST-1). A tela já trata essa
 * turma como histórico: explica que a lista "mostra as matrículas daquele ano" e
 * esconde "Transferir de turma". O botão "Cartões do Quest" continuava lá e
 * imprimia o cartão de cada criança com o nome da turma VELHA (o "3º Ano A" de
 * 2025 para quem já está no 4º Ano A). Agora o botão some como o "Transferir", a
 * explicação diz por quê e onde imprimir, e a turma do ano ativo segue com ele.
 * Dados fictícios.
 */
import { Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { api } from "../lib/__mocks__/api";
import TurmaDetalhe from "../pages/TurmaDetalhe";
import { renderComApp, responder, screen, turmaFake, usuarioFake } from "./utils";

const ADMIN_ESCOLA = usuarioFake({ cargo: "admin", is_global: false });
const COORDENACAO = usuarioFake({ cargo: "coordenador", is_global: false });

const TURMAS = [
  turmaFake({ id: 5, nome: "3º Ano A" }),
  turmaFake({ id: 7, nome: "2º Ano A", ano_escolar: "2º Ano", ano_letivo: 2025 }),
];

function montar(turmaId: number, nome: string, anoEscolar: string, usuario = ADMIN_ESCOLA) {
  responder("GET", `/escolas/1/turmas/${turmaId}/resumo`, {
    turma: { id: turmaId, nome, ano_escolar: anoEscolar },
    total_alunos: 1, media_geral: 80, media_matific: 80, media_elefante: 80,
    indicadores: { livros_unicos: 3, tempo_leitura_min: 40 },
  });
  responder("GET", "/escolas/1/turmas", TURMAS);
  responder("GET", new RegExp(`/escolas/1/turmas/${turmaId}/alunos`), [{
    id: 10, nome: "Ana Ficticia", foto_url: null, numero_chamada: 1, status: "ativo",
    turma: nome, ano_escolar: anoEscolar, created_at: null,
  }]);
  renderComApp(
    <Routes>
      <Route path="/turmas/:id" element={<TurmaDetalhe />} />
    </Routes>,
    { rota: `/turmas/${turmaId}`, usuario },
  );
}

describe("TurmaDetalhe — Cartões do Quest em turma de outro ano letivo", () => {
  it("turma do ano ativo: o botão segue no painel, sem o aviso de histórico", async () => {
    montar(5, "3º Ano A", "3º Ano");
    expect(await screen.findByRole("button", { name: /Cartões do Quest/ })).toBeInTheDocument();
    expect(screen.queryByText(/a\s+lista mostra as matrículas daquele ano/)).toBeNull();
  });

  it.each([
    ["admin da escola", ADMIN_ESCOLA],
    ["coordenação", COORDENACAO],
  ])("turma de 2025 (%s): sem o botão, e o aviso diz onde imprimir", async (_rotulo, usuario) => {
    montar(7, "2º Ano A", "2º Ano", usuario);
    const aviso = await screen.findByText(/a\s+lista mostra as matrículas daquele ano/);
    expect(screen.queryByRole("button", { name: /Cartões do Quest/ })).toBeNull();
    expect(aviso.textContent).toMatch(/Cartões do Quest/);
    expect(aviso.textContent).toMatch(/imprimir os cartões do Quest, abra a turma dele do ano\s+letivo 2026/);
    // Nada foi pedido à rota dos cartões só por abrir o painel.
    expect(api.mock.calls.some(([caminho]) => /\/quest\//.test(String(caminho)))).toBe(false);
  });
});
