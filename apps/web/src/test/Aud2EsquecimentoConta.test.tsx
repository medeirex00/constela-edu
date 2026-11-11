/**
 * G_LGPD-1: o modal da exclusão permanente prometia “será removido por completo …
 * Excluir para sempre” e não dizia que a conta da criança continua ativa no Matific
 * ou no Elefante Letrado. Agora o Constela ignora nas coletas as contas ligadas ao
 * cadastro excluído, e o modal diz as duas coisas que dependem de quem exclui:
 * pedir o encerramento da conta na plataforma, e que um relatório só com o nome
 * (sem a conta) pode cadastrar a criança de novo. Dados fictícios.
 */
import { expect, test, vi } from "vitest";

import AcoesAluno from "../components/AcoesAluno";
import type { Aluno } from "../lib/types";
import { renderComApp, screen, userEvent, usuarioFake } from "./utils";

const aluno: Aluno = {
  id: 10, nome: "Quiteria Ficticia", foto_url: null, numero_chamada: 1,
  status: "ativo", turma: "3º Ano A", ano_escolar: "3º Ano",
  data_nascimento: null, observacoes: null,
};

test("o modal da exclusão permanente avisa da conta que continua na plataforma", async () => {
  renderComApp(<AcoesAluno aluno={aluno} escolaId={1} aoMudar={vi.fn()} />,
               { usuario: usuarioFake({ cargo: "admin", is_global: true }) });
  await userEvent.click(await screen.findByLabelText("Ações de Quiteria Ficticia"));
  await userEvent.click(await screen.findByText("Excluir permanentemente"));

  const aviso = await screen.findByText(/peça o encerramento/);
  expect(aviso).toHaveTextContent(/Matific ou no Elefante Letrado/);
  expect(aviso).toHaveTextContent(/o Constela ignora nas próximas coletas/);
  expect(aviso).toHaveTextContent(/só o nome, sem a conta da plataforma/);
});
