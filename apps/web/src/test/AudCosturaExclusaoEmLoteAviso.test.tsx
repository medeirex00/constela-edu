/**
 * G_LGPD-1 (modal em lote): a exclusão permanente pela barra de ações em massa do
 * painel da turma prometia "serão removidos por completo … Excluir para sempre" e não
 * dizia que a conta da criança continua ativa no Matific ou no Elefante Letrado, nem
 * que um relatório só com o nome pode cadastrá-la de novo — o aviso que o menu do
 * aluno (AcoesAluno) já dá. Agora o modal em lote dá o mesmo aviso, no plural quando
 * há mais de uma criança. Dados fictícios.
 */
import { Route, Routes } from "react-router-dom";
import { expect, test } from "vitest";

import TurmaDetalhe from "../pages/TurmaDetalhe";
import { renderComApp, responder, screen, userEvent, usuarioFake, within } from "./utils";

const RESUMO = {
  turma: { id: 5, nome: "3º Ano A", ano_escolar: "3º Ano" },
  total_alunos: 2, media_geral: 80, media_matific: 80, media_elefante: 80,
  indicadores: { livros_unicos: 3, tempo_leitura_min: 40 },
};

function aluno(id: number, nome: string, numero: number) {
  return { id, nome, foto_url: null, numero_chamada: numero, status: "ativo",
           turma: "3º Ano A", ano_escolar: "3º Ano", created_at: null };
}

function montar() {
  responder("GET", "/escolas/1/turmas/5/resumo", RESUMO);
  responder("GET", "/escolas/1/turmas", []);
  responder("GET", /\/escolas\/1\/turmas\/5\/alunos/, [
    aluno(10, "Ana Ficticia", 1), aluno(11, "Bruno Ficticio", 2)]);
  renderComApp(
    <Routes><Route path="/turmas/:id" element={<TurmaDetalhe />} /></Routes>,
    { rota: "/turmas/5", usuario: usuarioFake({ cargo: "admin", is_global: true }) },
  );
}

async function abrirModal(nomes: string[]) {
  for (const nome of nomes) {
    await userEvent.click(await screen.findByLabelText(`Selecionar ${nome}`));
  }
  await userEvent.click(await screen.findByRole("button", { name: /Excluir permanentemente/ }));
  return screen.findByRole("dialog", { name: "Excluir permanentemente" });
}

test("duas crianças: o modal em lote avisa, no plural, da conta que continua na plataforma",
  async () => {
    montar();
    const modal = await abrirModal(["Ana Ficticia", "Bruno Ficticio"]);
    const aviso = within(modal).getByText(/peça o encerramento/);
    expect(aviso).toHaveTextContent(/Se as crianças ainda tiverem conta no Matific ou no Elefante Letrado/);
    expect(aviso).toHaveTextContent(/encerramento delas na plataforma/);
    expect(aviso).toHaveTextContent(/o Constela ignora nas próximas coletas as contas ligadas a estes cadastros/);
    expect(aviso).toHaveTextContent(/só o nome, sem a conta da plataforma, pode cadastrar as crianças de novo/);
  });

test("uma criança: o mesmo aviso do menu do aluno, no singular", async () => {
  montar();
  const modal = await abrirModal(["Ana Ficticia"]);
  const aviso = within(modal).getByText(/peça o encerramento/);
  expect(aviso).toHaveTextContent(/Se a criança ainda tiver conta no Matific ou no Elefante Letrado/);
  expect(aviso).toHaveTextContent(/as contas ligadas a este cadastro/);
  expect(aviso).toHaveTextContent(/pode cadastrar a criança de novo/);
});
