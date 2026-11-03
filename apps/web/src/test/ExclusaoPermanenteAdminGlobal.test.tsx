/**
 * D19 sem atalho: a exclusão FÍSICA de aluno é exclusiva do Admin Global (a API
 * responde 403 para os demais). A tela não oferece “Excluir permanentemente” a
 * admin e coordenação da escola — nem no menu do aluno (AcoesAluno), nem no menu
 * da turma, nem na barra de ações em massa (TurmaDetalhe) —, como Turmas.tsx já
 * fazia com a exclusão da turma junto com os alunos. A exclusão lógica
 * (reversível) continua para eles. Dados fictícios.
 */
import { Route, Routes } from "react-router-dom";
import { expect, test, vi } from "vitest";

import AcoesAluno from "../components/AcoesAluno";
import type { Aluno, Usuario } from "../lib/types";
import TurmaDetalhe from "../pages/TurmaDetalhe";
import { renderComApp, responder, screen, userEvent, usuarioFake } from "./utils";

const aluno: Aluno = {
  id: 10, nome: "Ana Ficticia", foto_url: null, numero_chamada: 1,
  status: "ativo", turma: "3º Ano A", ano_escolar: "3º Ano",
  data_nascimento: null, observacoes: null,
};

const COORDENACAO = usuarioFake({ cargo: "coordenador", is_global: false });
const ADMIN_ESCOLA = usuarioFake({ cargo: "admin", is_global: false });
const ADMIN_GLOBAL = usuarioFake({ cargo: "admin", is_global: true });

async function abrirMenuDoAluno() {
  await userEvent.click(await screen.findByLabelText("Ações de Ana Ficticia"));
  // O menu abriu: a exclusão lógica está lá para todos que editam.
  expect(await screen.findByText("Excluir")).toBeInTheDocument();
}

test.each([
  ["coordenação", COORDENACAO],
  ["admin da escola", ADMIN_ESCOLA],
])("AcoesAluno: %s não vê “Excluir permanentemente”", async (_rotulo, usuario: Usuario) => {
  renderComApp(<AcoesAluno aluno={aluno} escolaId={1} aoMudar={vi.fn()} />, { usuario });
  await abrirMenuDoAluno();
  expect(screen.queryByText("Excluir permanentemente")).toBeNull();

  // E o texto da exclusão lógica não manda usar um botão que não existe.
  await userEvent.click(screen.getByText("Excluir"));
  expect(await screen.findByText(/Apagar tudo de vez é exclusivo do Admin Global/))
    .toBeInTheDocument();
  expect(screen.queryByText(/use “Excluir permanentemente”/)).toBeNull();
});

test("AcoesAluno: o Admin Global segue com “Excluir permanentemente”", async () => {
  renderComApp(<AcoesAluno aluno={aluno} escolaId={1} aoMudar={vi.fn()} />,
               { usuario: ADMIN_GLOBAL });
  await abrirMenuDoAluno();
  expect(screen.getByText("Excluir permanentemente")).toBeInTheDocument();
});

// --- Painel da turma ---------------------------------------------------------

const RESUMO = {
  turma: { id: 5, nome: "3º Ano A", ano_escolar: "3º Ano" },
  total_alunos: 1, media_geral: 80, media_matific: 80, media_elefante: 80,
  indicadores: { livros_unicos: 3, tempo_leitura_min: 40 },
};

function montarTurma(usuario: Usuario) {
  responder("GET", "/escolas/1/turmas/5/resumo", RESUMO);
  responder("GET", "/escolas/1/turmas", []);
  // Sem nota (a linha mostra “sem nota”): o que importa aqui é o menu.
  responder("GET", /\/escolas\/1\/turmas\/5\/alunos/, [{
    id: 10, nome: "Ana Ficticia", foto_url: null, numero_chamada: 1, status: "ativo",
    turma: "3º Ano A", ano_escolar: "3º Ano", created_at: null,
  }]);
  renderComApp(
    <Routes>
      <Route path="/turmas/:id" element={<TurmaDetalhe />} />
    </Routes>,
    { rota: "/turmas/5", usuario },
  );
}

test.each([
  ["coordenação", COORDENACAO],
  ["admin da escola", ADMIN_ESCOLA],
])("TurmaDetalhe: %s não vê “Excluir permanentemente” no menu nem na massa",
  async (_rotulo, usuario: Usuario) => {
    montarTurma(usuario);
    await abrirMenuDoAluno();
    expect(screen.queryByText("Excluir permanentemente")).toBeNull();
    await userEvent.keyboard("{Escape}");

    await userEvent.click(screen.getByLabelText("Selecionar Ana Ficticia"));
    expect(await screen.findByText("1 selecionado")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Excluir permanentemente/ })).toBeNull();
    expect(screen.getByRole("button", { name: /Arquivar/ })).toBeInTheDocument();
  });

test("TurmaDetalhe: o Admin Global vê “Excluir permanentemente” no menu e na massa",
  async () => {
    montarTurma(ADMIN_GLOBAL);
    await abrirMenuDoAluno();
    expect(screen.getByText("Excluir permanentemente")).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");

    await userEvent.click(screen.getByLabelText("Selecionar Ana Ficticia"));
    expect(await screen.findByRole("button", { name: /Excluir permanentemente/ }))
      .toBeInTheDocument();
  });
