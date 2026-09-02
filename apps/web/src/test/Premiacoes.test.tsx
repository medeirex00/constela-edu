/**
 * Premiações: "Melhor Matemática" pela nota oficial (não atividades), abas de
 * TURNO derivadas dos dados (sem misturar turnos, sem aba quando há só um) e as
 * duas "Melhor Evolução" (com o rótulo do critério e o estado vazio quando a
 * Matemática não tem snapshots suficientes).
 */
import { describe, expect, it } from "vitest";

import Premiacoes from "../pages/Premiacoes";
import type { CategoriaPremiacao } from "../lib/types";
import { renderComApp, responder, screen, turmaFake, userEvent } from "./utils";

const URL_TURMAS = "/escolas/1/turmas";
const URL_PREM = "/escolas/1/premiacoes";
const URL_EVOL = "/escolas/1/ranking-evolucao";

function cat(chave: string, titulo: string, unidade: string,
             podio: Array<[number, string, number]>): CategoriaPremiacao {
  return {
    chave, titulo, icone: "🧮", descricao: "d", unidade,
    podio: podio.map(([aluno_id, nome, valor], i) => ({
      posicao: i + 1, aluno_id, nome, turma: "3A", valor,
    })),
  };
}

function premiacoesResp(over: Record<string, unknown> = {}) {
  const catsManha = [
    cat("melhor_leitor", "Melhor Leitor", "pontos", [[1, "Leo Manha", 30]]),
    cat("melhor_matematica", "Melhor Matemática", "nota", [[2, "Mat Manha", 82.5]]),
    cat("mais_livros", "Mais Livros Lidos", "livros", [[1, "Leo Manha", 5]]),
    cat("mais_tempo", "Mais Tempo de Leitura", "min", [[1, "Leo Manha", 60]]),
  ];
  const catsTarde = [
    cat("melhor_leitor", "Melhor Leitor", "pontos", [[3, "Leo Tarde", 20]]),
    cat("melhor_matematica", "Melhor Matemática", "nota", [[4, "Mat Tarde", 71.0]]),
    cat("mais_livros", "Mais Livros Lidos", "livros", [[3, "Leo Tarde", 3]]),
    cat("mais_tempo", "Mais Tempo de Leitura", "min", [[3, "Leo Tarde", 40]]),
  ];
  return {
    periodo: { chave: "mes", rotulo: "Este mês", inicio: null, fim: null },
    categorias: catsManha,
    turnos: [
      { turno: "manha", turno_rotulo: "Manhã", total: 2, categorias: catsManha },
      { turno: "tarde", turno_rotulo: "Tarde", total: 1, categorias: catsTarde },
    ],
    ...over,
  };
}

// Evolução por dimensão: leitura tem pódio; matemática vem VAZIA (L1). O pódio de
// leitura muda com o TURNO da query (prova que a evolução respeita o turno lockado).
function evolucaoPorDimensao(caminho: string) {
  if (caminho.includes("dimensao=matematica")) return [];
  const nome = caminho.includes("turno=tarde") ? "Evo Leitura Tarde" : "Evo Leitura";
  return [{ aluno_id: 9, nome, turma: "3A", posicao: 1, nota: 44.4, n_aferidos: 3 }];
}

describe("Premiações", () => {
  it("mostra Melhor Matemática pela NOTA e as abas de turno; troca de turno não mistura", async () => {
    responder("GET", URL_TURMAS, [turmaFake()]);
    responder("GET", URL_PREM, premiacoesResp());
    responder("GET", URL_EVOL, evolucaoPorDimensao);
    const u = userEvent.setup();
    renderComApp(<Premiacoes />);

    // Melhor Matemática (nota, não atividades) — campeão da Manhã por padrão.
    expect(await screen.findByText("Melhor Matemática")).toBeInTheDocument();
    expect(screen.getByText("Mat Manha")).toBeInTheDocument();

    // Abas de turno derivadas do backend.
    expect(screen.getByRole("tab", { name: /Todas/ })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Manhã/ })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Tarde/ })).toBeInTheDocument();

    // Troca para Tarde: mostra o campeão da Tarde, não o da Manhã.
    await u.click(screen.getByRole("tab", { name: /Tarde/ }));
    expect(await screen.findByText("Mat Tarde")).toBeInTheDocument();
    expect(screen.queryByText("Mat Manha")).not.toBeInTheDocument();
    // E a EVOLUÇÃO acompanha o turno selecionado (refez a busca com &turno=tarde).
    expect(await screen.findByText("Evo Leitura Tarde")).toBeInTheDocument();
  });

  it("Melhor Evolução: Leitura com pódio; Matemática vazia mostra o aviso (L1)", async () => {
    responder("GET", URL_TURMAS, [turmaFake()]);
    responder("GET", URL_PREM, premiacoesResp());
    responder("GET", URL_EVOL, evolucaoPorDimensao);
    renderComApp(<Premiacoes />);

    expect(await screen.findByText("Melhor Evolução — Leitura")).toBeInTheDocument();
    expect(screen.getByText("Evo Leitura")).toBeInTheDocument();
    expect(screen.getByText("Melhor Evolução — Matemática")).toBeInTheDocument();
    expect(screen.getByText(/Sem dados suficientes no período para medir evolução de Matemática/)).toBeInTheDocument();
  });

  it("não mostra abas de turno quando há só um turno", async () => {
    responder("GET", URL_TURMAS, [turmaFake()]);
    responder("GET", URL_PREM, premiacoesResp({
      turnos: [{ turno: "manha", turno_rotulo: "Manhã", total: 2,
                 categorias: premiacoesResp().categorias }],
    }));
    responder("GET", URL_EVOL, evolucaoPorDimensao);
    renderComApp(<Premiacoes />);

    expect(await screen.findByText("Melhor Matemática")).toBeInTheDocument();
    expect(screen.queryByRole("tab")).not.toBeInTheDocument();
  });
});
