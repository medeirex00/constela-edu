/**
 * Painel da turma: o aviso de uma ação (inclusive o do D10 — conta da plataforma
 * que continua valendo em outra escola) fica o tempo dele na tela. Antes, cada
 * `avisar` armava um temporizador novo sem cancelar o anterior: o de 6 s de uma
 * ação feita logo antes apagava o aviso de 30 s do D10. Dados fictícios.
 */
import { expect, test, vi } from "vitest";
import { Route, Routes } from "react-router-dom";

import TurmaDetalhe from "../pages/TurmaDetalhe";
import { fireEvent, renderComApp, responder, screen, usuarioFake } from "./utils";

const RESUMO = {
  turma: { id: 5, nome: "3º Ano A", ano_escolar: "3º Ano" },
  total_alunos: 2, media_geral: 80, media_matific: 80, media_elefante: 80,
  indicadores: { livros_unicos: 3, tempo_leitura_min: 40 },
};

function alunoGestao(id: number, nome: string, status: string) {
  return {
    id, nome, foto_url: null, numero_chamada: id, status, turma: "3º Ano A",
    ano_escolar: "3º Ano", created_at: null, nota_geral: null, posicao: null,
  };
}

const AVISO = "Atenção: esta conta da plataforma continua vinculada a um aluno de outra " +
  "escola do Constela, que não foi alterada.";
const TEM_AVISO = /continua vinculada a um aluno de outra escola/;

test("o temporizador de uma ação anterior não apaga o aviso do D10 antes da hora", async () => {
  vi.useFakeTimers();
  try {
    responder("GET", "/escolas/1/turmas/5/resumo", RESUMO);
    responder("GET", "/escolas/1/turmas", []);
    responder("GET", /\/escolas\/1\/turmas\/5\/alunos/, [
      alunoGestao(21, "Bruno Ficticio", "ativo"),
      alunoGestao(22, "Carla Ficticia", "excluido"),
    ]);
    responder("POST", /\/alunos\/acoes/, (_c: string, o: RequestInit | FormData) => {
      const { acao } = JSON.parse(String((o as RequestInit).body));
      return acao === "reativar"
        ? { mensagem: "1 aluno(s) reativado(s).", afetados: 1, avisos: [AVISO] }
        : { mensagem: "1 aluno(s) arquivado(s).", afetados: 1, avisos: [] };
    });
    renderComApp(
      <Routes>
        <Route path="/turmas/:id" element={<TurmaDetalhe />} />
      </Routes>,
      { rota: "/turmas/5", usuario: usuarioFake({ cargo: "admin", is_global: true }) },
    );
    for (let i = 0; i < 5 && !screen.queryByLabelText("Ações de Bruno Ficticio"); i++) {
      await vi.advanceTimersByTimeAsync(50);
    }

    // 1ª ação (sem aviso): mensagem de 6 s.
    fireEvent.click(screen.getByLabelText("Ações de Bruno Ficticio"));
    fireEvent.click(screen.getByText("Arquivar"));
    await vi.advanceTimersByTimeAsync(0);
    expect(screen.getByText("1 aluno(s) arquivado(s).")).toBeInTheDocument();

    // 2 s depois, o Admin Global reativa a ficha excluída: aviso do D10 (30 s).
    await vi.advanceTimersByTimeAsync(2000);
    fireEvent.click(screen.getByLabelText("Ações de Carla Ficticia"));
    fireEvent.click(screen.getByText("Reativar"));
    await vi.advanceTimersByTimeAsync(0);
    expect(screen.getByText(TEM_AVISO)).toBeInTheDocument();

    // Passam os 6 s da 1ª ação: o aviso do D10 continua.
    await vi.advanceTimersByTimeAsync(5000);
    expect(screen.queryByText(TEM_AVISO)).not.toBeNull();

    // E sai depois dos 30 s dele.
    await vi.advanceTimersByTimeAsync(25_500);
    expect(screen.queryByText(TEM_AVISO)).toBeNull();
  } finally {
    vi.useRealTimers();
  }
});

test("média geral não mostra 0,0 de dimensão sem aluno aferido nem de plataforma fora do plano", async () => {
  responder("GET", "/escolas/1/turmas/5/resumo", {
    ...RESUMO,
    media_geral: 72.5, media_elefante: 72.5, media_matific: 0,
    contratadas: ["leitura", "matematica"], n_leitura: 2, n_matematica: 0,
    dimensoes_com_dados: ["leitura"], adocao_leitura: 100, adocao_matematica: 0, nao_aferidos: 0,
  });
  responder("GET", "/escolas/1/turmas", []);
  responder("GET", /\/escolas\/1\/turmas\/5\/alunos/, [alunoGestao(21, "Bruno Ficticio", "ativo")]);
  renderComApp(
    <Routes>
      <Route path="/turmas/:id" element={<TurmaDetalhe />} />
    </Routes>,
    { rota: "/turmas/5", usuario: usuarioFake({ cargo: "admin" }) },
  );

  const media = (await screen.findByText("Média geral")).parentElement as HTMLElement;
  expect(media).toHaveTextContent("72,5");
  expect(media).toHaveTextContent("Leitura 72,5");
  expect(media).toHaveTextContent("Matific —");
  expect(media).not.toHaveTextContent("Matific 0,0");
  // Cobertura real por plataforma contratada (barra + número em texto).
  expect(await screen.findByText("Uso das plataformas")).toBeInTheDocument();
  expect(screen.getByText("100%")).toBeInTheDocument();
});
