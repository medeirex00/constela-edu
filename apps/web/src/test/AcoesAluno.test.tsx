/**
 * Arquivar/Reativar um aluno partem direto do menu (sem modal próprio): a falha
 * NÃO pode ser silenciosa. Antes, o erro era setado mas nunca renderizado.
 */
import { vi } from "vitest";

import AcoesAluno from "../components/AcoesAluno";
import { api } from "../lib/__mocks__/api";
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

// --- Marcar como transferido (saiu da escola) --------------------------------
// O verbo é novo e tem vizinho perigoso: "Transferir de turma" move de sala,
// "Marcar como transferido" tira da escola. Estes testes travam (a) que a ação
// enviada ao backend é a certa e (b) que ela some quando o aluno já está inativo
// — oferecer "marcar transferido" para quem já saiu seria ruído.

test("marcar como transferido envia a ação correta ao backend", async () => {
  responder("POST", /\/alunos\/acoes/, { ok: true });
  const aoMudar = vi.fn();
  renderComApp(<AcoesAluno aluno={aluno} escolaId={1} aoMudar={aoMudar} />);

  await userEvent.click(screen.getByLabelText("Ações de Ana Souza"));
  await userEvent.click(await screen.findByText("Marcar como transferido"));

  await vi.waitFor(() => expect(aoMudar).toHaveBeenCalled());
  const chamada = api.mock.calls.find(
    ([caminho]) => String(caminho) === "/escolas/1/alunos/acoes");
  expect(chamada).toBeDefined();
  expect(JSON.parse(String((chamada![1] as RequestInit).body)))
    .toEqual({ aluno_ids: [10], acao: "marcar_transferido" });
});

test("quem já está fora da escola não recebe a opção de novo", async () => {
  renderComApp(
    <AcoesAluno aluno={{ ...aluno, status: "transferido" }} escolaId={1}
                aoMudar={vi.fn()} />,
  );
  await userEvent.click(screen.getByLabelText("Ações de Ana Souza"));

  expect(await screen.findByText("Reativar")).toBeInTheDocument();
  expect(screen.queryByText("Marcar como transferido")).toBeNull();
});
