/**
 * Arquivar/Reativar um aluno partem direto do menu (sem modal próprio): a falha
 * NÃO pode ser silenciosa. Antes, o erro era setado mas nunca renderizado.
 */
import { vi } from "vitest";

import AcoesAluno from "../components/AcoesAluno";
import type { Aluno } from "../lib/types";
import { renderComApp, responder, responderErro, screen, userEvent } from "./utils";

const aluno: Aluno = {
  id: 10, nome: "Ana Souza", foto_url: null, numero_chamada: 1,
  status: "ativo", turma: "3º Ano A", ano_escolar: "3º Ano",
  data_nascimento: null, observacoes: null,
};

async function abrirMenuEArquivar() {
  await userEvent.click(screen.getByLabelText("Ações de Ana Souza"));
  await userEvent.click(await screen.findByText("Arquivar"));
}

test("falha ao arquivar aparece para o usuário (não é silenciosa)", async () => {
  responderErro("POST", /\/alunos\/acoes/, 400, "Não foi possível arquivar agora.");
  renderComApp(<AcoesAluno aluno={aluno} escolaId={1} aoMudar={vi.fn()} />);

  await abrirMenuEArquivar();

  expect(await screen.findByText("Não foi possível arquivar agora.")).toBeInTheDocument();
});

test("falha ao REATIVAR (mesmo caminho) também aparece", async () => {
  responderErro("POST", /\/alunos\/acoes/, 400, "Não foi possível reativar agora.");
  renderComApp(
    <AcoesAluno aluno={{ ...aluno, status: "arquivado" }} escolaId={1} aoMudar={vi.fn()} />,
  );
  await userEvent.click(screen.getByLabelText("Ações de Ana Souza"));
  await userEvent.click(await screen.findByText("Reativar"));
  expect(await screen.findByText("Não foi possível reativar agora.")).toBeInTheDocument();
});

test("arquivar com sucesso avisa a tela e não mostra erro", async () => {
  responder("POST", /\/alunos\/acoes/, { ok: true });
  const aoMudar = vi.fn();
  renderComApp(<AcoesAluno aluno={aluno} escolaId={1} aoMudar={aoMudar} />);

  await abrirMenuEArquivar();

  await vi.waitFor(() => expect(aoMudar).toHaveBeenCalled());
  expect(screen.queryByText(/Não foi possível concluir a ação/i)).toBeNull();
});
