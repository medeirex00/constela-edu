/**
 * “Transferir de turma” a partir do painel de uma turma (3ª revisão de
 * integração, contas-turmas-push). O painel de uma turma de OUTRO ano letivo
 * lista os alunos pela matrícula daquele ano (histórico), mas transferir movia a
 * matrícula do ano ATIVO — a da turma atual da criança, em outra sala. Agora:
 *   - o painel manda ``turma_origem_id`` (a API move só a matrícula que está nela);
 *   - em turma de outro ano letivo a tela não oferece “Transferir” (nem no menu,
 *     nem na massa) e explica o porquê;
 *   - os destinos do modal seguem só as turmas ativas do ano ativo;
 *   - a tela de Turmas orienta “Arquivar” (não “Transferir”) para excluir turma
 *     de ano anterior com alunos.
 * Dados fictícios.
 */
import { Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { api } from "../lib/__mocks__/api";
import type { Usuario } from "../lib/types";
import TurmaDetalhe from "../pages/TurmaDetalhe";
import Turmas from "../pages/Turmas";
import { renderComApp, responder, screen, turmaFake, userEvent, usuarioFake, within } from "./utils";

const ADMIN_ESCOLA = usuarioFake({ cargo: "admin", is_global: false });

const TURMAS = [
  turmaFake({ id: 5, nome: "3º Ano A" }),
  turmaFake({ id: 6, nome: "3º Ano B" }),
  turmaFake({ id: 7, nome: "2º Ano A", ano_escolar: "2º Ano", ano_letivo: 2025 }),
  turmaFake({ id: 8, nome: "3º Ano Z", status: "arquivada", total_alunos: 0 }),
];

function resumo(id: number, nome: string, ano_escolar: string) {
  return {
    turma: { id, nome, ano_escolar },
    total_alunos: 1, media_geral: 80, media_matific: 80, media_elefante: 80,
    indicadores: { livros_unicos: 3, tempo_leitura_min: 40 },
  };
}

function montarPainel(turmaId: number, nome: string, anoEscolar: string,
                      usuario: Usuario = ADMIN_ESCOLA) {
  responder("GET", `/escolas/1/turmas/${turmaId}/resumo`, resumo(turmaId, nome, anoEscolar));
  responder("GET", "/escolas/1/turmas", TURMAS);
  responder("GET", new RegExp(`/escolas/1/turmas/${turmaId}/alunos`), [{
    id: 10, nome: "Ana Ficticia", foto_url: null, numero_chamada: 1, status: "ativo",
    turma: nome, ano_escolar: anoEscolar, created_at: null,
  }]);
  responder("POST", /\/alunos\/acoes/, { mensagem: "1 aluno(s) transferido(s).", afetados: 1, avisos: [] });
  renderComApp(
    <Routes>
      <Route path="/turmas/:id" element={<TurmaDetalhe />} />
    </Routes>,
    { rota: `/turmas/${turmaId}`, usuario },
  );
}

async function abrirMenuDoAluno() {
  await userEvent.click(await screen.findByLabelText("Ações de Ana Ficticia"));
  expect(await screen.findByText("Excluir")).toBeInTheDocument();
}

describe("TurmaDetalhe — transferir a partir do painel", () => {
  it("turma de OUTRO ano letivo: sem “Transferir” no menu nem na massa, com a explicação", async () => {
    montarPainel(7, "2º Ano A", "2º Ano");

    expect(await screen.findByText(/a\s+lista mostra as matrículas daquele ano/))
      .toBeInTheDocument();
    await abrirMenuDoAluno();
    expect(screen.queryByText("Transferir de turma")).toBeNull();
    // As demais ações seguem (arquivar o aluno, por exemplo).
    expect(screen.getByText("Arquivar")).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");

    await userEvent.click(screen.getByLabelText("Selecionar Ana Ficticia"));
    expect(await screen.findByText("1 selecionado")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Transferir/ })).toBeNull();
    expect(screen.getByRole("button", { name: /Arquivar/ })).toBeInTheDocument();
  });

  it("turma do ano ativo: transferir manda turma_origem_id e só oferece turmas ativas do ano", async () => {
    montarPainel(5, "3º Ano A", "3º Ano");

    await abrirMenuDoAluno();
    expect(screen.queryByText(/a\s+lista mostra as matrículas daquele ano/)).toBeNull();
    await userEvent.click(screen.getByText("Transferir de turma"));

    const destino = await screen.findByRole("combobox", { name: /Turma de destino/ });
    const opcoes = within(destino).getAllByRole("option").map((o) => o.textContent);
    // Nem a turma de 2025 nem a arquivada são destino (nem a própria turma).
    expect(opcoes).toEqual(["3º Ano B"]);
    await userEvent.selectOptions(destino, "6");
    await userEvent.click(screen.getByRole("button", { name: /^Transferir$/ }));

    await vi.waitFor(() => expect(
      api.mock.calls.some(([caminho, o]) => String(caminho) === "/escolas/1/alunos/acoes"
        && (o as RequestInit)?.method === "POST"),
    ).toBe(true));
    const chamada = api.mock.calls.find(
      ([caminho, o]) => String(caminho) === "/escolas/1/alunos/acoes"
        && (o as RequestInit)?.method === "POST");
    expect(JSON.parse(String((chamada![1] as RequestInit).body))).toEqual({
      aluno_ids: [10], acao: "transferir", turma_id: 6, turma_origem_id: 5,
    });
  });

  it("as outras ações não mandam turma_origem_id", async () => {
    montarPainel(5, "3º Ano A", "3º Ano");

    await abrirMenuDoAluno();
    await userEvent.click(screen.getByText("Arquivar"));

    await vi.waitFor(() => expect(
      api.mock.calls.some(([caminho]) => String(caminho) === "/escolas/1/alunos/acoes"),
    ).toBe(true));
    const chamada = api.mock.calls.find(
      ([caminho]) => String(caminho) === "/escolas/1/alunos/acoes");
    expect(JSON.parse(String((chamada![1] as RequestInit).body))).toEqual({
      aluno_ids: [10], acao: "arquivar", turma_id: null,
    });
  });
});

describe("Turmas — excluir turma de ano anterior orienta “Arquivar”", () => {
  it("admin da escola: turma de 2025 com alunos não manda “Transferir de turma”", async () => {
    responder("GET", "/escolas/1/turmas", [
      turmaFake({ id: 7, nome: "2º Ano A", ano_escolar: "2º Ano", ano_letivo: 2025,
                  total_alunos: 3 }),
    ]);
    responder("GET", "/escolas/1/professores", []);
    renderComApp(<Turmas />, { rota: "/turmas", usuario: ADMIN_ESCOLA });

    // Turma de outro ano letivo só aparece com “Mostrar … de outros anos letivos”.
    await userEvent.click(await screen.findByLabelText(/Mostrar turmas arquivadas e de outros anos/));
    await userEvent.click(await screen.findByRole("button", { name: /Excluir turma 2º Ano A/i }));

    expect(await screen.findByText(/as matrículas dela\s+são histórico/)).toBeInTheDocument();
    expect(screen.getByText(/use\s+“Arquivar” para tirá-la da lista/)).toBeInTheDocument();
    expect(screen.queryByText(/abra-a e use “Transferir de turma”/)).toBeNull();
    const soATurma = screen.getByRole("button", { name: /Excluir só a turma/i });
    expect(soATurma).toBeDisabled();
    expect(soATurma).toHaveAttribute("title", expect.stringMatching(/use “Arquivar”/));
  });

  it("admin da escola: turma do ano ativo com alunos continua orientando transferir", async () => {
    responder("GET", "/escolas/1/turmas", [turmaFake({ id: 5, nome: "3º Ano A", total_alunos: 3 })]);
    responder("GET", "/escolas/1/professores", []);
    renderComApp(<Turmas />, { rota: "/turmas", usuario: ADMIN_ESCOLA });

    await userEvent.click(await screen.findByRole("button", { name: /Excluir turma 3º Ano A/i }));

    expect(await screen.findByText(/abra-a e use “Transferir de turma”/)).toBeInTheDocument();
    expect(screen.queryByText(/as matrículas dela\s+são histórico/)).toBeNull();
  });

  it("exclusão em massa com turma de ano anterior com alunos orienta arquivá-la", async () => {
    responder("GET", "/escolas/1/turmas", [
      turmaFake({ id: 5, nome: "3º Ano A", total_alunos: 3 }),
      turmaFake({ id: 7, nome: "2º Ano A", ano_escolar: "2º Ano", ano_letivo: 2025,
                  total_alunos: 3 }),
    ]);
    responder("GET", "/escolas/1/professores", []);
    renderComApp(<Turmas />, { rota: "/turmas", usuario: ADMIN_ESCOLA });

    await userEvent.click(await screen.findByLabelText(/Mostrar turmas arquivadas e de outros anos/));
    await userEvent.click(await screen.findByRole("checkbox", { name: /Selecionar todas/i }));
    await userEvent.click(await screen.findByRole("button", { name: /Excluir selecionadas/i }));

    expect(await screen.findByText(/Turmas de ano anterior \(1\) não se esvaziam assim/))
      .toBeInTheDocument();
  });
});
