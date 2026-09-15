/**
 * Premiações: "Melhor Matemática" pela nota oficial (não atividades), o TURNO
 * GLOBAL como seletor (opções derivadas das turmas da escola; sem misturar
 * turnos; sem opção extra quando há só um turno) e as duas "Melhor Evolução"
 * (com o rótulo do critério e o estado vazio quando a Matemática não tem
 * snapshots suficientes). Aviso e evolução usam SÓ a resposta do recorte atual.
 */
import { describe, expect, it } from "vitest";

import Premiacoes from "../pages/Premiacoes";
import type { CategoriaPremiacao } from "../lib/types";
import { api, renderComApp, responder, screen, turmaFake, userEvent, waitFor, within } from "./utils";

const URL_TURMAS = "/escolas/1/turmas";
const URL_PREM = "/escolas/1/premiacoes";
const URL_EVOL = "/escolas/1/ranking-evolucao";

// Turmas da escola: é DELAS que saem as opções do seletor de turno.
const turmasManhaTarde = [
  turmaFake({ id: 1, nome: "3º Ano A", turno: "manha" }),
  turmaFake({ id: 2, nome: "3º Ano B", turno: "tarde" }),
];

const turnoDe = (caminho: string) =>
  new URLSearchParams(caminho.split("?")[1] ?? "").get("turno");
/** Caminhos com que `/ranking-evolucao` foi chamado. */
const chamadasEvolucao = () =>
  api.mock.calls.map((c) => String(c[0])).filter((p) => p.startsWith(`${URL_EVOL}?`));

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

// Pódio da escola inteira ("Todos") com um nome próprio, para não confundir
// com o pódio de um turno.
const categoriasTodos = [cat("melhor_matematica", "Melhor Matemática", "nota", [[5, "Mat Todos", 90]])];

// Evolução por dimensão: leitura tem pódio; matemática vem VAZIA (L1). O pódio de
// leitura muda com o TURNO da query (prova que a evolução respeita o turno lockado).
function evolucaoPorDimensao(caminho: string) {
  if (caminho.includes("dimensao=matematica")) return [];
  const nome = caminho.includes("turno=tarde") ? "Evo Leitura Tarde" : "Evo Leitura";
  return [{ aluno_id: 9, nome, turma: "3A", posicao: 1, nota: 44.4, n_aferidos: 3 }];
}

describe("Premiações", () => {
  it("mostra Melhor Matemática pela NOTA e o seletor de turno; trocar de turno não mistura", async () => {
    responder("GET", URL_TURMAS, turmasManhaTarde);
    responder("GET", URL_PREM, premiacoesResp());
    responder("GET", URL_EVOL, evolucaoPorDimensao);
    const u = userEvent.setup();
    renderComApp(<Premiacoes />);

    // Melhor Matemática (nota, não atividades) — "Todos" por padrão.
    expect(await screen.findByText("Melhor Matemática")).toBeInTheDocument();
    expect(screen.getByText("Mat Manha")).toBeInTheDocument();

    // Seletor de turno (global) com as opções derivadas das turmas da escola.
    const seletor = await screen.findByLabelText("Turno");
    expect(within(seletor).getByRole("option", { name: "Todos os turnos" })).toBeInTheDocument();
    expect(within(seletor).getByRole("option", { name: "Manhã" })).toBeInTheDocument();
    expect(within(seletor).getByRole("option", { name: "Tarde" })).toBeInTheDocument();
    // As abas locais de turno deixaram de existir (o turno é global).
    expect(screen.queryByRole("tab")).not.toBeInTheDocument();

    // Troca para Tarde: mostra o campeão da Tarde, não o da Manhã.
    await u.selectOptions(seletor, "tarde");
    expect(await screen.findByText("Mat Tarde")).toBeInTheDocument();
    expect(screen.queryByText("Mat Manha")).not.toBeInTheDocument();
    // E a EVOLUÇÃO acompanha o turno selecionado (refez a busca com &turno=tarde).
    expect(await screen.findByText("Evo Leitura Tarde")).toBeInTheDocument();
    // Rodapé com a verdade do backend (régua da Matemática = escola inteira).
    expect(screen.getByText(/Vencedores calculados só com os alunos do turno selecionado/)).toBeInTheDocument();
    // Persistiu no eixo próprio do turno (separado do período).
    expect(localStorage.getItem("sgpe_turno")).toBe("tarde");
  });

  it("Melhor Evolução: Leitura com pódio; Matemática vazia mostra o aviso (L1)", async () => {
    responder("GET", URL_TURMAS, turmasManhaTarde);
    responder("GET", URL_PREM, premiacoesResp());
    responder("GET", URL_EVOL, evolucaoPorDimensao);
    renderComApp(<Premiacoes />);

    expect(await screen.findByText("Melhor Evolução — Leitura")).toBeInTheDocument();
    expect(screen.getByText("Evo Leitura")).toBeInTheDocument();
    expect(screen.getByText("Melhor Evolução — Matemática")).toBeInTheDocument();
    expect(screen.getByText(/Sem dados suficientes no período para medir evolução de Matemática/)).toBeInTheDocument();
  });

  it("com um turno só, o seletor não ganha opção extra", async () => {
    responder("GET", URL_TURMAS, [turmaFake({ turno: "manha" })]);
    responder("GET", URL_PREM, premiacoesResp({
      turnos: [{ turno: "manha", turno_rotulo: "Manhã", total: 2,
                 categorias: premiacoesResp().categorias }],
    }));
    responder("GET", URL_EVOL, evolucaoPorDimensao);
    renderComApp(<Premiacoes />);

    expect(await screen.findByText("Melhor Matemática")).toBeInTheDocument();
    const seletor = await screen.findByLabelText("Turno");
    // Espera as turmas chegarem (a opção "Manhã" deriva delas).
    await within(seletor).findByRole("option", { name: "Manhã" });
    expect(within(seletor).getAllByRole("option").map((o) => o.textContent))
      .toEqual(["Todos os turnos", "Manhã"]);
  });

  it("turno global já escolhido abre direto nele; com uma turma selecionada, a turma vence", async () => {
    responder("GET", URL_TURMAS, turmasManhaTarde);
    responder("GET", URL_PREM, premiacoesResp());
    responder("GET", URL_EVOL, evolucaoPorDimensao);
    const u = userEvent.setup();
    renderComApp(<Premiacoes />, { turno: "tarde" });

    // Já abre na Tarde (turno persistido).
    expect(await screen.findByText("Mat Tarde")).toBeInTheDocument();
    expect(await screen.findByText("Evo Leitura Tarde")).toBeInTheDocument();
    expect(screen.queryByText("Com uma turma escolhida, o turno não se aplica.")).not.toBeInTheDocument();

    // Seleciona uma turma: o turno fica desabilitado (a turma define o recorte)
    // e os pódios passam a ser os da resposta filtrada por turma.
    await u.selectOptions(screen.getByLabelText("Filtrar por turma"), "1");
    const seletor = screen.getByLabelText("Turno");
    expect(seletor).toBeDisabled();
    expect((seletor as HTMLSelectElement).value).toBe("todos");
    // O MOTIVO está em texto visível e ligado ao seletor (não só num title).
    expect(screen.getByText("Com uma turma escolhida, o turno não se aplica.")).toBeVisible();
    expect(seletor).toHaveAccessibleDescription("Com uma turma escolhida, o turno não se aplica.");
    // O turno guardado NÃO foi sobrescrito.
    expect(localStorage.getItem("sgpe_turno")).toBe("tarde");
  });

  it("turno guardado sem ninguém matriculado nele: avisa, mostra o pódio de 'Todos' e a evolução vai SEM turno", async () => {
    responder("GET", URL_TURMAS, turmasManhaTarde);
    // O backend agrupa TODOS os alunos matriculados no ano: só existe a Manhã.
    responder("GET", URL_PREM, premiacoesResp({
      categorias: categoriasTodos,
      turnos: [{ turno: "manha", turno_rotulo: "Manhã", total: 2,
                 categorias: [cat("melhor_matematica", "Melhor Matemática", "nota", [[2, "Mat Manha", 82.5]])] }],
    }));
    responder("GET", URL_EVOL, evolucaoPorDimensao);
    renderComApp(<Premiacoes />, { turno: "tarde" });

    expect(await screen.findByText(
      "Nenhum aluno matriculado no turno Tarde neste ano letivo; mostrando todos os turnos.",
    )).toBeInTheDocument();
    // Pódio da escola inteira, não o de outro turno nem um pódio vazio.
    expect(screen.getByText("Mat Todos")).toBeInTheDocument();
    expect(screen.queryByText("Mat Manha")).not.toBeInTheDocument();
    // A evolução acompanha: vai sem turno (nunca com turno=tarde).
    expect(await screen.findByText("Evo Leitura")).toBeInTheDocument();
    expect(chamadasEvolucao().length).toBeGreaterThan(0);
    expect(chamadasEvolucao().every((p) => turnoDe(p) === null)).toBe(true);
    expect(screen.queryByText(/Vencedores calculados só com os alunos do turno/)).not.toBeInTheDocument();
    // A escolha guardada continua (vale quando houver alunos na Tarde).
    expect(localStorage.getItem("sgpe_turno")).toBe("tarde");
  });

  it("trocar a turma não reaproveita a resposta anterior: nada de aviso nem evolução sem turno no meio do caminho", async () => {
    responder("GET", URL_TURMAS, turmasManhaTarde);
    // Com turma, o backend não manda a quebra por turno (não foi pedida).
    responder("GET", URL_PREM, (caminho: string) =>
      caminho.includes("turma_id=") ? premiacoesResp({ turnos: undefined }) : premiacoesResp());
    responder("GET", URL_EVOL, evolucaoPorDimensao);
    const u = userEvent.setup();
    renderComApp(<Premiacoes />, { turno: "tarde" });

    expect(await screen.findByText("Evo Leitura Tarde")).toBeInTheDocument();
    await u.selectOptions(screen.getByLabelText("Filtrar por turma"), "1");
    expect(await screen.findByText("Evo Leitura")).toBeInTheDocument();

    // Volta para "Todas as turmas": enquanto a resposta nova não chega, a
    // anterior (sem grupos de turno) NÃO pode decidir o recorte da evolução.
    api.mockClear();
    await u.selectOptions(screen.getByLabelText("Filtrar por turma"), "");
    expect(await screen.findByText("Evo Leitura Tarde")).toBeInTheDocument();
    expect(chamadasEvolucao().length).toBeGreaterThan(0);
    expect(chamadasEvolucao().every((p) => turnoDe(p) === "tarde")).toBe(true);
    expect(screen.queryByText(/Nenhum aluno matriculado/)).not.toBeInTheDocument();
  });

  it("escola sem turmas + turno guardado: evolução sem turno, seletor em 'Todos os turnos' e sem aviso", async () => {
    responder("GET", URL_TURMAS, []);
    responder("GET", URL_PREM, premiacoesResp({ categorias: categoriasTodos, turnos: [] }));
    responder("GET", URL_EVOL, evolucaoPorDimensao);
    renderComApp(<Premiacoes />, { turno: "manha" });

    expect(await screen.findByText("Mat Todos")).toBeInTheDocument();
    // A consulta que vale (a última) vai SEM turno.
    await waitFor(() => {
      const chamadas = chamadasEvolucao();
      expect(chamadas.length).toBeGreaterThan(0);
      expect(turnoDe(chamadas[chamadas.length - 1])).toBeNull();
    });
    const seletor = screen.getByLabelText("Turno") as HTMLSelectElement;
    expect(seletor.value).toBe("todos");
    expect(within(seletor).getAllByRole("option").map((o) => o.textContent)).toEqual(["Todos os turnos"]);
    await waitFor(() => expect(screen.queryByText(/Nenhum aluno matriculado/)).not.toBeInTheDocument());
    expect(localStorage.getItem("sgpe_turno")).toBe("manha");
  });
});
