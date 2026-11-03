/**
 * D17 pelo outro lado: turma arquivada não recebe aluno ativo. A API recusa com
 * 409 o “Reativar” de quem tem a matrícula do ano numa turma arquivada (e o
 * transferir/cadastrar nela), explicando a saída — transferir antes. No painel
 * da turma essa explicação aparece e fica tempo bastante para ser lida (o erro
 * sumia em 6 s, como as mensagens de sucesso). Dados fictícios.
 */
import { Route, Routes } from "react-router-dom";
import { expect, test, vi } from "vitest";

import TurmaDetalhe from "../pages/TurmaDetalhe";
import { fireEvent, renderComApp, responder, responderErro, screen, usuarioFake } from "./utils";

const RESUMO = {
  turma: { id: 5, nome: "3º Ano A", ano_escolar: "3º Ano" },
  total_alunos: 0, media_geral: 0, media_matific: 0, media_elefante: 0,
  indicadores: { livros_unicos: 0, tempo_leitura_min: 0 },
};

const RECUSA_D17 =
  "1 aluno(s) selecionado(s) não pode(m) ser reativado(s): a matrícula do ano letivo " +
  "2026 está em turma arquivada (“3º Ano A”). Turma arquivada não recebe aluno ativo: " +
  "arquivar não encerra as matrículas, e o aluno continuaria nos rankings, premiações e " +
  "relatórios ligado a uma turma fora dos filtros. Antes de reativar, use “Transferir " +
  "de turma” para levá-los a uma turma ativa.";
const TEM_RECUSA = /não pode\(m\) ser reativado\(s\).*Transferir de turma/;

test("reativar aluno de turma arquivada mostra a recusa do D17 e ela fica na tela", async () => {
  vi.useFakeTimers();
  try {
    responder("GET", "/escolas/1/turmas/5/resumo", RESUMO);
    responder("GET", "/escolas/1/turmas", []);
    responder("GET", /\/escolas\/1\/turmas\/5\/alunos/, [{
      id: 22, nome: "Carla Ficticia", foto_url: null, numero_chamada: 2,
      status: "arquivado", turma: "3º Ano A", ano_escolar: "3º Ano", created_at: null,
    }]);
    responderErro("POST", /\/alunos\/acoes/, 409, RECUSA_D17);
    renderComApp(
      <Routes>
        <Route path="/turmas/:id" element={<TurmaDetalhe />} />
      </Routes>,
      { rota: "/turmas/5", usuario: usuarioFake({ cargo: "coordenador" }) },
    );
    for (let i = 0; i < 5 && !screen.queryByLabelText("Ações de Carla Ficticia"); i++) {
      await vi.advanceTimersByTimeAsync(50);
    }

    fireEvent.click(screen.getByLabelText("Ações de Carla Ficticia"));
    fireEvent.click(screen.getByText("Reativar"));
    await vi.advanceTimersByTimeAsync(0);
    expect(screen.getByText(TEM_RECUSA)).toBeInTheDocument();

    // Passados os 6 s de uma mensagem comum, a recusa ainda está lá…
    await vi.advanceTimersByTimeAsync(7000);
    expect(screen.queryByText(TEM_RECUSA)).not.toBeNull();
    // …e sai depois do tempo dela.
    await vi.advanceTimersByTimeAsync(14_000);
    expect(screen.queryByText(TEM_RECUSA)).toBeNull();
  } finally {
    vi.useRealTimers();
  }
});
