/**
 * Perfil do Aluno: o seletor de período das abas Evolução, Leituras e Linha do tempo
 * diz o período que a consulta pede (auditoria PERIODOS-8).
 *
 * As três abas abrem pedindo o histórico TODO (`{preset: "tudo"}`), mas "tudo" não era
 * uma opção do seletor: o <select> controlado mostrava a 1ª opção, "Hoje". E o preset
 * escolhido viaja como `periodo=<preset>` — o contrato de /leituras, que as rotas
 * /evolucao-leitura e /linha-do-tempo passaram a aceitar (backend:
 * tests/test_aud_per_perfil_aluno_periodo.py).
 */
import { describe, expect, it } from "vitest";

import EvolucaoAlunoAba from "../components/EvolucaoAlunoAba";
import HistoricoLeituras from "../components/HistoricoLeituras";
import LinhaDoTempoAluno from "../components/LinhaDoTempoAluno";
import { SeletorPeriodo } from "../components/SeletorPeriodo";
import { api, render, renderComApp, responder, screen, userEvent, waitFor, within } from "./utils";

const BASE = "/escolas/1/alunos/5";
const chamadas = (rota: string) =>
  api.mock.calls.map((c) => String(c[0])).filter((u) => u.startsWith(`${BASE}/${rota}`));

function semear() {
  responder("GET", `${BASE}/espelho`, { espelho: { total_eventos: 0, primeira_atividade: null,
    ultima_atividade: null, tempo_total_segundos: 0, por_tipo: {}, por_plataforma: {} } });
  responder("GET", `${BASE}/linha-do-tempo`, { itens: [], proximo_cursor: null });
  responder("GET", `${BASE}/evolucao-leitura`, { granularidade: "mes", series: [] });
  responder("GET", `${BASE}/leituras`, {
    periodo: { chave: "tudo", rotulo: "Todo o histórico", inicio: null, fim: null },
    resumo: { total_livros: 0, pontos: 0, tempo_total_min: 0 }, itens: [] });
}

const ABAS = [
  { nome: "Linha do tempo", rota: "linha-do-tempo", ui: <LinhaDoTempoAluno escolaId={1} alunoId={5} /> },
  { nome: "Evolução", rota: "evolucao-leitura", ui: <EvolucaoAlunoAba escolaId={1} alunoId={5} /> },
  { nome: "Leituras", rota: "leituras", ui: <HistoricoLeituras escolaId={1} alunoId={5} /> },
];

describe("Perfil do Aluno — o seletor diz o período que a consulta pede", () => {
  for (const aba of ABAS) {
    it(`${aba.nome}: abre em "Todo o histórico" (não em "Hoje") e manda o preset escolhido`, async () => {
      semear();
      renderComApp(aba.ui, { rota: "/alunos/5" });
      const seletor = await screen.findByLabelText("Período de análise") as HTMLSelectElement;

      expect(seletor.value).toBe("tudo");
      expect(within(seletor).getByRole("option", { selected: true })).toHaveTextContent("Todo o histórico");
      await waitFor(() => expect(chamadas(aba.rota).at(-1)).toMatch(/[?&]periodo=tudo(&|$)/));

      await userEvent.setup().selectOptions(seletor, "bimestre_3");
      expect(seletor.value).toBe("bimestre_3");
      await waitFor(() => expect(chamadas(aba.rota).at(-1)).toMatch(/[?&]periodo=bimestre_3(&|$)/));
    });
  }

  it("as outras telas não ganham a opção: 'Todo o histórico' é só para quem pede (comTudo)", () => {
    render(<SeletorPeriodo valor={{ preset: "mes" }} onChange={() => undefined} />);
    const opcoes = within(screen.getByLabelText("Período de análise"))
      .getAllByRole("option").map((o) => (o as HTMLOptionElement).value);
    expect(opcoes).not.toContain("tudo");
    expect(opcoes[0]).toBe("hoje");
  });
});
