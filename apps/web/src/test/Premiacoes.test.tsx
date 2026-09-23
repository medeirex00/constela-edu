/**
 * Premiações: "Melhor Matemática" pela média ajustada de estrelas por atividade
 * do período (valor pronto do backend, exibido com 2 casas e unidade), o TURNO
 * GLOBAL como seletor (opções derivadas das turmas da escola; sem misturar
 * turnos; sem opção extra quando há só um turno) e as duas "Melhor Evolução"
 * (com o rótulo do critério, pódio só com quem cresceu e o estado vazio quando
 * a Matemática não tem snapshots suficientes). Aviso e evolução usam SÓ a
 * resposta do recorte atual.
 */
import { describe, expect, it } from "vitest";

import Premiacoes from "../pages/Premiacoes";
import type { CategoriaPremiacao } from "../lib/types";
import { ApiError, api, renderComApp, responder, screen, turmaFake, userEvent, waitFor, within } from "./utils";

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
    cat("melhor_matematica", "Melhor Matemática", "estrelas/atividade", [[2, "Mat Manha", 4.07]]),
    cat("mais_livros", "Mais Livros Lidos", "livros", [[1, "Leo Manha", 5]]),
    cat("mais_tempo", "Mais Tempo de Leitura", "min", [[1, "Leo Manha", 60]]),
  ];
  const catsTarde = [
    cat("melhor_leitor", "Melhor Leitor", "pontos", [[3, "Leo Tarde", 20]]),
    cat("melhor_matematica", "Melhor Matemática", "estrelas/atividade", [[4, "Mat Tarde", 3.5]]),
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
const categoriasTodos = [cat("melhor_matematica", "Melhor Matemática", "estrelas/atividade", [[5, "Mat Todos", 4.5]])];

// Evolução por dimensão: leitura tem pódio; matemática vem VAZIA (L1). O pódio de
// leitura muda com o TURNO da query (prova que a evolução respeita o turno lockado).
function evolucaoPorDimensao(caminho: string) {
  if (caminho.includes("dimensao=matematica")) return [];
  const nome = caminho.includes("turno=tarde") ? "Evo Leitura Tarde" : "Evo Leitura";
  return [{ aluno_id: 9, nome, turma: "3A", posicao: 1, nota: 44.4, n_aferidos: 3 }];
}

describe("Premiações", () => {
  it("mostra Melhor Matemática pela MÉDIA AJUSTADA e o seletor de turno; trocar de turno não mistura", async () => {
    responder("GET", URL_TURMAS, turmasManhaTarde);
    responder("GET", URL_PREM, premiacoesResp());
    responder("GET", URL_EVOL, evolucaoPorDimensao);
    const u = userEvent.setup();
    renderComApp(<Premiacoes />);

    // Melhor Matemática (média ajustada, não atividades) — "Todos" por padrão.
    expect(await screen.findByText("Melhor Matemática")).toBeInTheDocument();
    expect(screen.getByText("Mat Manha")).toBeInTheDocument();
    // Valor pronto do backend, com 2 casas e a unidade (sem conta no front).
    expect(screen.getByText("4,07 estrelas/atividade")).toBeInTheDocument();
    expect(screen.getByText(/Média ajustada de estrelas por atividade no período/)).toBeInTheDocument();
    // Rodapé: fórmula em uma frase, régua da escola inteira, só atividades do período.
    expect(screen.getByText(/20% da mediana de atividades da escola/)).toBeInTheDocument();
    expect(screen.getByText(/A régua é a da escola inteira/)).toBeInTheDocument();
    expect(screen.getByText(/só entram atividades feitas dentro do período/)).toBeInTheDocument();
    expect(screen.queryByText(/nota oficial/)).not.toBeInTheDocument();

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
    expect(screen.getByText("3,50 estrelas/atividade")).toBeInTheDocument();
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

  it("Melhor Evolução: pódio só com quem cresceu (nota > 0); só zeros mostra o aviso", async () => {
    responder("GET", URL_TURMAS, turmasManhaTarde);
    responder("GET", URL_PREM, premiacoesResp());
    responder("GET", URL_EVOL, (caminho: string) => (caminho.includes("dimensao=matematica")
      ? [{ aluno_id: 7, nome: "Parado Mat", turma: "3A", posicao: 1, nota: 0, n_aferidos: 1 }]
      : [
          { aluno_id: 9, nome: "Cresceu Leitura", turma: "3A", posicao: 1, nota: 44.4, n_aferidos: 2 },
          { aluno_id: 8, nome: "Parado Leitura", turma: "3A", posicao: 2, nota: 0, n_aferidos: 2 },
        ]));
    renderComApp(<Premiacoes />);

    expect(await screen.findByText("Cresceu Leitura")).toBeInTheDocument();
    expect(screen.queryByText("Parado Leitura")).not.toBeInTheDocument();
    expect(screen.queryByText("Parado Mat")).not.toBeInTheDocument();
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
                 categorias: [cat("melhor_matematica", "Melhor Matemática", "estrelas/atividade", [[2, "Mat Manha", 4.07]])] }],
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

  // --- Régua da Matemática: período PEDIDO × janela USADA --------------------
  // O backend recorta a Matemática pelo ANO LETIVO e devolve `regua_matematica`.
  // A tela precisa mostrar a janela real e explicar o pódio vazio pelo modo.

  it("mostra a janela realmente usada quando ela difere do período pedido", async () => {
    responder("GET", URL_TURMAS, turmasManhaTarde);
    responder("GET", URL_PREM, premiacoesResp({
      periodo: { chave: "personalizado", rotulo: "01/12/2025 a 31/01/2026",
                 inicio: "2025-12-01T00:00:00", fim: "2026-01-31T23:59:59" },
      turnos: [],
      regua_matematica: { modo: "periodo", ano_letivo: 2026,
                          inicio_efetivo: "2026-01-01T00:00:00",
                          fim_efetivo: "2026-01-31T23:59:59.999999" },
    }));
    responder("GET", URL_EVOL, evolucaoPorDimensao);
    renderComApp(<Premiacoes />);

    expect(await screen.findByText(/Matemática: 01\/01\/2026 a 31\/01\/2026 \(ano letivo 2026\)/))
      .toBeInTheDocument();
    // O recorte por ano letivo fica EXPLÍCITO também no rodapé (requisito 8).
    expect(screen.getByText(/sempre recortado pelo ano letivo 2026/)).toBeInTheDocument();
  });

  it("pódio vazio de Matemática explica o motivo pelo MODO, não com 'ninguém fez atividade'", async () => {
    responder("GET", URL_TURMAS, turmasManhaTarde);
    responder("GET", URL_PREM, premiacoesResp({
      periodo: { chave: "personalizado", rotulo: "01/09/2025 a 30/09/2025",
                 inicio: "2025-09-01T00:00:00", fim: "2025-09-30T23:59:59" },
      categorias: [cat("melhor_matematica", "Melhor Matemática", "estrelas/atividade", [])],
      turnos: [],
      regua_matematica: { modo: "fora_do_ano_letivo", ano_letivo: 2026,
                          inicio_efetivo: null, fim_efetivo: null },
    }));
    responder("GET", URL_EVOL, evolucaoPorDimensao);
    renderComApp(<Premiacoes />);

    // O dado de set/2025 existe; quem o descartou foi o filtro de ano letivo.
    expect(await screen.findByText(/está fora do ano letivo 2026/)).toBeInTheDocument();
    expect(screen.queryByText("Nenhuma atividade do Matific feita dentro do período.")).toBeNull();
  });

  it("'Todo o histórico': o rodapé diz que a Matemática é o acumulado do ano letivo", async () => {
    responder("GET", URL_TURMAS, turmasManhaTarde);
    responder("GET", URL_PREM, premiacoesResp({
      periodo: { chave: "tudo", rotulo: "Todo o histórico", inicio: null, fim: null },
      turnos: [],
      regua_matematica: { modo: "situacao_atual", ano_letivo: 2026,
                          inicio_efetivo: null, fim_efetivo: null },
    }));
    responder("GET", URL_EVOL, evolucaoPorDimensao);
    renderComApp(<Premiacoes />);

    expect(await screen.findByText(/vale o acumulado do ano letivo 2026/)).toBeInTheDocument();
    expect(screen.getByText(/sem recorte de período/)).toBeInTheDocument();
    expect(screen.queryByText(/só entram atividades feitas dentro do período/)).toBeNull();
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

  // --- Ranking completo da premiação -------------------------------------
  // O cartão é o Top 5; "Ver ranking completo" abre a MESMA premiação com mais
  // linhas, pedidas ao backend com `limite`. A tela nunca reordena nada: exibe
  // na ordem e com a posição que vieram.

  /** Categoria com `n` alunos já ORDENADOS pelo backend, a partir da posição 1.
   *  `prefixo`/`baseId` dão nomes e ids próprios quando o teste precisa provar
   *  que uma lista não vazou para a outra. */
  function catGrande(chave: string, titulo: string, unidade: string, n: number,
                     total = n, prefixo = "Aluno", baseId = 100): CategoriaPremiacao {
    return {
      chave, titulo, icone: "🏆", descricao: "d", unidade, total,
      podio: Array.from({ length: n }, (_, i) => ({
        posicao: i + 1, aluno_id: baseId + i,
        nome: `${prefixo} ${String(i + 1).padStart(2, "0")}`,
        turma: "3A", valor: 1000 - i,
      })),
    };
  }

  /** Responde ao `/premiacoes` devolvendo tantas linhas quanto o `limite` pedir. */
  function respostaPorLimite(totalDisponivel: number) {
    return (caminho: string) => {
      const limite = Number(new URLSearchParams(caminho.split("?")[1] ?? "").get("limite") ?? 5);
      const n = Math.min(limite, totalDisponivel);
      return {
        periodo: { chave: "mes", rotulo: "Este mês", inicio: null, fim: null },
        categorias: [
          catGrande("melhor_leitor", "Melhor Leitor", "pontos", n, totalDisponivel),
          cat("melhor_matematica", "Melhor Matemática", "estrelas/atividade", [[2, "Mat Manha", 4.07]]),
          cat("mais_livros", "Mais Livros Lidos", "livros", [[1, "Leo Manha", 5]]),
          cat("mais_tempo", "Mais Tempo de Leitura", "min", [[1, "Leo Manha", 60]]),
        ],
      };
    };
  }

  /** Limites com que `/premiacoes` foi chamado, na ordem. */
  const limitesPedidos = () =>
    api.mock.calls.map((c) => String(c[0]))
      .filter((p) => p.startsWith(`${URL_PREM}?`))
      .map((p) => new URLSearchParams(p.split("?")[1]).get("limite"));

  /** Abre o ranking completo de uma premiação e devolve a JANELA (para escopar
   *  as buscas: o cartão atrás mostra os mesmos nomes). */
  async function abrirRanking(u: ReturnType<typeof userEvent.setup>, titulo: string) {
    await u.click(screen.getByRole("button", { name: `Ver ranking completo de ${titulo}` }));
    const cabecalho = await screen.findByRole("heading", { level: 2, name: new RegExp(titulo) });
    return cabecalho.closest("div") as HTMLElement;
  }

  it("Ver ranking completo abre o ranking da premiação com 50 e o Top 5 do cartão não muda", async () => {
    responder("GET", URL_TURMAS, turmasManhaTarde);
    responder("GET", URL_PREM, respostaPorLimite(120));
    responder("GET", URL_EVOL, evolucaoPorDimensao);
    const u = userEvent.setup();
    renderComApp(<Premiacoes />);

    // O cartão continua sendo o Top 5 (a primeira chamada não pede limite).
    expect(await screen.findByText("Melhor Leitor")).toBeInTheDocument();
    expect(screen.getByText("Aluno 01")).toBeInTheDocument();
    expect(screen.getByText("Aluno 05")).toBeInTheDocument();
    expect(screen.queryByText("Aluno 06")).not.toBeInTheDocument();
    expect(limitesPedidos()).toEqual([null]);

    const janela = await abrirRanking(u, "Melhor Leitor");

    // Pediu 50 ao backend, na MESMA URL da aba (só com o limite a mais).
    await waitFor(() => expect(limitesPedidos()).toEqual([null, "50"]));
    expect(api.mock.calls.map((c) => String(c[0]))
      .some((p) => p.includes("limite=50") && p.includes("turnos=true"))).toBe(true);
    // Mostra as 50 primeiras posições, com a posição REAL vinda do backend.
    expect(await within(janela).findByText("Aluno 50")).toBeInTheDocument();
    expect(within(janela).getByText("50º")).toBeInTheDocument();
    expect(within(janela).queryByText("Aluno 51")).not.toBeInTheDocument();
    expect(within(janela).getByText(/120 alunos no período/)).toBeInTheDocument();
  });

  it("ranking completo exibe na ORDEM do backend, sem reordenar no front", async () => {
    responder("GET", URL_TURMAS, turmasManhaTarde);
    // Ordem proposital NÃO decrescente por valor: se o front ordenasse, mudaria.
    responder("GET", URL_PREM, (caminho: string) => {
      const limite = Number(new URLSearchParams(caminho.split("?")[1] ?? "").get("limite") ?? 5);
      const podio = [
        { posicao: 1, aluno_id: 1, nome: "Primeiro Menor", turma: "3A", valor: 10 },
        { posicao: 2, aluno_id: 2, nome: "Segundo Maior", turma: "3A", valor: 99 },
        { posicao: 3, aluno_id: 3, nome: "Terceiro Meio", turma: "3A", valor: 50 },
      ].slice(0, limite);
      return {
        periodo: { chave: "mes", rotulo: "Este mês", inicio: null, fim: null },
        categorias: [{ chave: "melhor_leitor", titulo: "Melhor Leitor", icone: "🏆",
                       descricao: "d", unidade: "pontos", total: 3, podio }],
      };
    });
    responder("GET", URL_EVOL, evolucaoPorDimensao);
    const u = userEvent.setup();
    renderComApp(<Premiacoes />);
    await screen.findByText("Melhor Leitor");

    const janela = await abrirRanking(u, "Melhor Leitor");
    const nomes = within(janela).getAllByRole("listitem").map((li) => li.textContent ?? "");
    // A ordem exibida é EXATAMENTE a recebida (o valor maior no meio continua no meio).
    expect(nomes[0]).toContain("Primeiro Menor");
    expect(nomes[1]).toContain("Segundo Maior");
    expect(nomes[2]).toContain("Terceiro Meio");
  });

  it("Carregar mais pede o próximo limite e não duplica nem pula alunos", async () => {
    responder("GET", URL_TURMAS, turmasManhaTarde);
    responder("GET", URL_PREM, respostaPorLimite(120));
    responder("GET", URL_EVOL, evolucaoPorDimensao);
    const u = userEvent.setup();
    renderComApp(<Premiacoes />);
    await screen.findByText("Melhor Leitor");

    const janela = await abrirRanking(u, "Melhor Leitor");
    expect(await within(janela).findByText("Aluno 50")).toBeInTheDocument();

    await u.click(within(janela).getByRole("button", { name: "Carregar mais" }));
    await waitFor(() => expect(limitesPedidos()).toEqual([null, "50", "100"]));
    expect(await within(janela).findByText("Aluno 100")).toBeInTheDocument();
    // Ninguém repetido dentro da janela: cada nome aparece uma vez só.
    expect(within(janela).getAllByText("Aluno 01")).toHaveLength(1);
    expect(within(janela).getAllByText("Aluno 50")).toHaveLength(1);
    // Ninguém pulado: a 51ª posição está lá.
    expect(within(janela).getByText("Aluno 51")).toBeInTheDocument();
  });

  it("ranking completo respeita o turno selecionado (mesmo recorte do cartão)", async () => {
    responder("GET", URL_TURMAS, turmasManhaTarde);
    responder("GET", URL_PREM, premiacoesResp());
    responder("GET", URL_EVOL, evolucaoPorDimensao);
    const u = userEvent.setup();
    renderComApp(<Premiacoes />);

    await u.selectOptions(await screen.findByLabelText("Turno"), "tarde");
    await waitFor(() => expect(screen.getAllByText("Leo Tarde").length).toBeGreaterThan(0));

    const janela = await abrirRanking(u, "Melhor Leitor");
    // O ranking mostra o pódio do TURNO, não o da escola inteira.
    expect(within(janela).getByText("Leo Tarde")).toBeInTheDocument();
    expect(within(janela).queryByText("Leo Manha")).not.toBeInTheDocument();
    // E pediu o mesmo recorte (turnos=true) com o limite maior.
    expect(api.mock.calls.map((c) => String(c[0]))
      .some((p) => p.includes("limite=50") && p.includes("turnos=true"))).toBe(true);
  });
  // --- Ranking completo da EVOLUÇÃO -------------------------------------
  // Mesma janela das outras premiações, alimentada pela MESMA lista que o
  // cartão já buscou: o endpoint por dimensão devolve todos os aferidos,
  // ordenados e com a posição carimbada pelo motor. O front não ordena, não
  // desempata e não recalcula — só mostra mais linhas.

  /** Resposta do `/ranking-evolucao` de uma dimensão: `n` alunos que CRESCERAM
   *  (posições 1..n, nota decrescente) e 2 parados (nota 0) no fim, como o
   *  backend devolve — os parados ficam fora do pódio por decisão de produto. */
  function evolucaoGrande(prefixo: string, n: number) {
    return [
      ...Array.from({ length: n }, (_, i) => ({
        aluno_id: 1000 + i, nome: `${prefixo} ${String(i + 1).padStart(2, "0")}`,
        turma: "3A", posicao: i + 1, nota: 100 - i * 0.1, n_aferidos: n + 2,
      })),
      ...[0, 1].map((k) => ({
        aluno_id: 2000 + k, nome: `${prefixo} Parado ${k}`, turma: "3A",
        posicao: n + k + 1, nota: 0, n_aferidos: n + 2,
      })),
    ];
  }

  /** Leitura com `n` crescimentos; Matemática com nomes próprios, para provar
   *  que uma dimensão não contamina a outra. */
  const evolucaoDuasDimensoes = (nLeitura: number, nMatematica: number) => (caminho: string) =>
    (caminho.includes("dimensao=matematica")
      ? evolucaoGrande("Mat Evo", nMatematica)
      : evolucaoGrande("Leo Evo", nLeitura));

  it("Melhor Evolução — Leitura: ranking completo abre com 50, mantém o Top 5 e NÃO refaz a busca", async () => {
    responder("GET", URL_TURMAS, turmasManhaTarde);
    responder("GET", URL_PREM, premiacoesResp());
    responder("GET", URL_EVOL, evolucaoDuasDimensoes(120, 3));
    const u = userEvent.setup();
    renderComApp(<Premiacoes />);

    // O cartão é o Top 5 — nem um a mais.
    expect(await screen.findByText("Leo Evo 01")).toBeInTheDocument();
    expect(screen.getByText("Leo Evo 05")).toBeInTheDocument();
    expect(screen.queryByText("Leo Evo 06")).not.toBeInTheDocument();
    const buscasAntes = chamadasEvolucao().length;

    const janela = await abrirRanking(u, "Melhor Evolução — Leitura");

    // A lista já estava na mão: abrir o ranking não gera consulta nova.
    expect(chamadasEvolucao()).toHaveLength(buscasAntes);
    // 50 linhas de saída, com a posição REAL do motor (a 50ª é mesmo a 50ª).
    expect(within(janela).getAllByRole("listitem")).toHaveLength(50);
    expect(within(janela).getByText("Leo Evo 50")).toBeInTheDocument();
    expect(within(janela).getByText("50º")).toBeInTheDocument();
    expect(within(janela).queryByText("Leo Evo 51")).not.toBeInTheDocument();
    // Quem não cresceu continua fora (mesma régua do cartão).
    expect(within(janela).queryByText("Leo Evo Parado 0")).not.toBeInTheDocument();
    expect(within(janela).getByText(/120 alunos no período/)).toBeInTheDocument();

    // As 5 primeiras linhas do ranking são EXATAMENTE o Top 5 do cartão, na
    // mesma ordem e com as mesmas posições.
    const cinco = within(janela).getAllByRole("listitem").slice(0, 5)
      .map((li) => li.textContent ?? "");
    ["01", "02", "03", "04", "05"].forEach((n, i) => expect(cinco[i]).toContain(`Leo Evo ${n}`));
    expect(cinco[3]).toContain("4º");
    expect(cinco[4]).toContain("5º");
    // O cartão atrás não mudou: continua parando no 5º (o "06" só existe dentro
    // da janela do ranking).
    expect(screen.getAllByText("Leo Evo 06")).toHaveLength(1);
  });

  it("Carregar mais no ranking de evolução não duplica nem pula posições", async () => {
    responder("GET", URL_TURMAS, turmasManhaTarde);
    responder("GET", URL_PREM, premiacoesResp());
    responder("GET", URL_EVOL, evolucaoDuasDimensoes(120, 3));
    const u = userEvent.setup();
    renderComApp(<Premiacoes />);
    await screen.findByText("Leo Evo 01");

    const janela = await abrirRanking(u, "Melhor Evolução — Leitura");
    await u.click(within(janela).getByRole("button", { name: "Carregar mais" }));

    expect(within(janela).getAllByRole("listitem")).toHaveLength(100);
    // A 51ª posição (a primeira do novo lote) está lá: ninguém foi pulado.
    expect(within(janela).getByText("Leo Evo 51")).toBeInTheDocument();
    expect(within(janela).getByText("51º")).toBeInTheDocument();
    expect(within(janela).getByText("Leo Evo 100")).toBeInTheDocument();
    // E ninguém repetido: cada posição aparece uma vez só.
    expect(within(janela).getAllByText("Leo Evo 01")).toHaveLength(1);
    expect(within(janela).getAllByText("Leo Evo 50")).toHaveLength(1);
    expect(within(janela).getAllByText("50º")).toHaveLength(1);
    const posicoes = within(janela).getAllByRole("listitem")
      .map((li) => (li.textContent ?? "").match(/Leo Evo (\d+)/)?.[1]);
    expect(new Set(posicoes).size).toBe(100);

    // Último lote: o botão some quando a lista acaba (120 de 120).
    await u.click(within(janela).getByRole("button", { name: "Carregar mais" }));
    expect(within(janela).getAllByRole("listitem")).toHaveLength(120);
    expect(within(janela).queryByRole("button", { name: "Carregar mais" })).not.toBeInTheDocument();
  });

  it("ranking de evolução exibe na ORDEM e com o desempate do backend (o front não reordena)", async () => {
    responder("GET", URL_TURMAS, turmasManhaTarde);
    responder("GET", URL_PREM, premiacoesResp());
    // Empate real (mesma nota) já desempatado pelo motor, e um valor MAIOR no
    // meio: se o front ordenasse por nota, a ordem mudaria.
    responder("GET", URL_EVOL, (caminho: string) => (caminho.includes("dimensao=matematica") ? [] : [
      { aluno_id: 1, nome: "Empate Ana", turma: "3A", posicao: 1, nota: 10, n_aferidos: 4 },
      { aluno_id: 2, nome: "Empate Bruno", turma: "3A", posicao: 2, nota: 10, n_aferidos: 4 },
      { aluno_id: 3, nome: "Fora de Ordem", turma: "3A", posicao: 3, nota: 99, n_aferidos: 4 },
      { aluno_id: 4, nome: "Ultimo Colocado", turma: "3A", posicao: 4, nota: 1, n_aferidos: 4 },
    ]));
    const u = userEvent.setup();
    renderComApp(<Premiacoes />);
    await screen.findByText("Empate Ana");

    const janela = await abrirRanking(u, "Melhor Evolução — Leitura");
    const nomes = within(janela).getAllByRole("listitem").map((li) => li.textContent ?? "");
    expect(nomes[0]).toContain("Empate Ana");      // desempate do motor, mantido
    expect(nomes[1]).toContain("Empate Bruno");
    expect(nomes[2]).toContain("Fora de Ordem");   // nota maior segue no meio
    expect(nomes[3]).toContain("Ultimo Colocado");
  });

  it("ranking de evolução respeita período, turma e turno (o mesmo recorte do cartão)", async () => {
    responder("GET", URL_TURMAS, turmasManhaTarde);
    responder("GET", URL_PREM, premiacoesResp());
    responder("GET", URL_EVOL, (caminho: string) => {
      if (caminho.includes("dimensao=matematica")) return [];
      const p = new URLSearchParams(caminho.split("?")[1] ?? "");
      const marca = `${p.get("turno") ?? "todos"}/${p.get("turma_id") ?? "todas"}/${p.get("periodo") ?? "-"}`;
      return [{ aluno_id: 9, nome: `Recorte ${marca}`, turma: "3A", posicao: 1, nota: 7, n_aferidos: 1 }];
    });
    const u = userEvent.setup();
    renderComApp(<Premiacoes />);

    // Turno: o ranking abre com o recorte do turno selecionado.
    await u.selectOptions(await screen.findByLabelText("Turno"), "tarde");
    await screen.findByText("Recorte tarde/todas/ano_letivo");
    let janela = await abrirRanking(u, "Melhor Evolução — Leitura");
    expect(within(janela).getByText("Recorte tarde/todas/ano_letivo")).toBeInTheDocument();
    await u.click(screen.getByLabelText("Fechar janela"));

    // Turma: com turma escolhida o turno não se aplica e o ranking acompanha.
    await u.selectOptions(screen.getByLabelText("Filtrar por turma"), "2");
    await screen.findByText("Recorte todos/2/ano_letivo");
    janela = await abrirRanking(u, "Melhor Evolução — Leitura");
    expect(within(janela).getByText("Recorte todos/2/ano_letivo")).toBeInTheDocument();
    expect(within(janela).queryByText("Recorte tarde/todas/ano_letivo")).not.toBeInTheDocument();
    await u.click(screen.getByLabelText("Fechar janela"));

    // Período: trocar o preset global refaz a busca e o ranking segue junto.
    await u.selectOptions(screen.getByLabelText("Período de análise"), "semana");
    await screen.findByText("Recorte todos/2/semana");
    janela = await abrirRanking(u, "Melhor Evolução — Leitura");
    expect(within(janela).getByText("Recorte todos/2/semana")).toBeInTheDocument();
  });

  it("Leitura e Matemática têm rankings completos independentes", async () => {
    responder("GET", URL_TURMAS, turmasManhaTarde);
    responder("GET", URL_PREM, premiacoesResp());
    responder("GET", URL_EVOL, evolucaoDuasDimensoes(60, 8));
    const u = userEvent.setup();
    renderComApp(<Premiacoes />);
    await screen.findByText("Leo Evo 01");

    // Leitura: 50 na primeira abertura, com os nomes da leitura.
    let janela = await abrirRanking(u, "Melhor Evolução — Leitura");
    expect(within(janela).getAllByRole("listitem")).toHaveLength(50);
    expect(within(janela).queryByText("Mat Evo 01")).not.toBeInTheDocument();
    await u.click(screen.getByLabelText("Fechar janela"));

    // Matemática: a própria lista (8), sem "Carregar mais" e sem nomes da leitura.
    janela = await abrirRanking(u, "Melhor Evolução — Matemática");
    expect(within(janela).getAllByRole("listitem")).toHaveLength(8);
    expect(within(janela).getByText("Mat Evo 08")).toBeInTheDocument();
    expect(within(janela).getByText("8º")).toBeInTheDocument();
    expect(within(janela).queryByText("Leo Evo 01")).not.toBeInTheDocument();
    expect(within(janela).queryByRole("button", { name: "Carregar mais" })).not.toBeInTheDocument();
  });

  it("as quatro premiações e as duas evoluções oferecem o ranking completo; sem pódio, não há botão", async () => {
    responder("GET", URL_TURMAS, turmasManhaTarde);
    responder("GET", URL_PREM, premiacoesResp());
    // Leitura tem pódio; Matemática vem vazia (L1).
    responder("GET", URL_EVOL, evolucaoPorDimensao);
    renderComApp(<Premiacoes />);

    await screen.findByText("Evo Leitura");
    for (const titulo of ["Melhor Leitor", "Melhor Matemática", "Mais Livros Lidos",
                          "Mais Tempo de Leitura", "Melhor Evolução — Leitura"]) {
      expect(screen.getByRole("button", { name: `Ver ranking completo de ${titulo}` }))
        .toBeInTheDocument();
    }
    // Cartão sem ninguém no pódio não ganha o botão (nada a abrir).
    expect(screen.queryByRole("button", { name: "Ver ranking completo de Melhor Evolução — Matemática" }))
      .not.toBeInTheDocument();
  });
  it("o ranking completo nunca pede mais que o teto do endpoint (limite=500)", async () => {
    responder("GET", URL_TURMAS, turmasManhaTarde);
    // Premiação maior que o teto: a janela tem de parar em 500, não estourar em
    // 422 e virar tela de erro.
    responder("GET", URL_PREM, respostaPorLimite(600));
    responder("GET", URL_EVOL, evolucaoPorDimensao);
    const u = userEvent.setup();
    renderComApp(<Premiacoes />);
    await screen.findByText("Melhor Leitor");

    const janela = await abrirRanking(u, "Melhor Leitor");

    // Já na abertura a janela DIZ que mostra só o começo, e o total REAL
    // continua no cabeçalho, em separado.
    expect(await within(janela).findByText(/600 alunos no período/)).toBeInTheDocument();
    expect(within(janela).getByRole("note"))
      .toHaveTextContent("Esta janela mostra as 500 primeiras posições.");

    let botao = within(janela).queryByRole("button", { name: "Carregar mais" });
    for (let i = 0; i < 12 && botao; i += 1) {
      await u.click(botao);
      botao = within(janela).queryByRole("button", { name: "Carregar mais" });
    }

    // Parou no teto: 500 linhas, sem botão e sem nenhum pedido acima de 500.
    expect(within(janela).getAllByRole("listitem")).toHaveLength(500);
    expect(within(janela).queryByRole("button", { name: "Carregar mais" })).not.toBeInTheDocument();
    const pedidos = limitesPedidos().filter(Boolean).map(Number);
    expect(Math.max(...pedidos)).toBe(500);
    expect(within(janela).queryByText("Não foi possível carregar o ranking.")).not.toBeInTheDocument();
    // A 500ª posição existe, a 501ª não é inventada, e o aviso continua à vista.
    expect(within(janela).getByText("Aluno 500")).toBeInTheDocument();
    expect(within(janela).getByText("500º")).toBeInTheDocument();
    expect(within(janela).queryByText("Aluno 501")).not.toBeInTheDocument();
    expect(within(janela).getByRole("note")).toBeInTheDocument();
  });

  it("exatamente 500 premiáveis: sem aviso de limite", async () => {
    responder("GET", URL_TURMAS, turmasManhaTarde);
    responder("GET", URL_PREM, respostaPorLimite(500));
    responder("GET", URL_EVOL, evolucaoPorDimensao);
    const u = userEvent.setup();
    renderComApp(<Premiacoes />);
    await screen.findByText("Melhor Leitor");

    const janela = await abrirRanking(u, "Melhor Leitor");
    expect(await within(janela).findByText(/500 alunos no período/)).toBeInTheDocument();
    // O teto não corta nada aqui: nada de aviso, e o "Carregar mais" segue vivo.
    expect(within(janela).queryByRole("note")).not.toBeInTheDocument();
    expect(within(janela).getByRole("button", { name: "Carregar mais" })).toBeInTheDocument();
  });
  // --- Correções da auditoria pré-publicação -----------------------------

  /** Turmas de uma escola que tem turno cadastrado em umas e NÃO em outras —
   *  é só aí que o seletor oferece "Sem turno" (chave = string VAZIA). */
  const turmasComSemTurno = [
    turmaFake({ id: 1, nome: "3º Ano A", turno: "manha" }),
    turmaFake({ id: 2, nome: "3º Ano B", turno: "tarde" }),
    turmaFake({ id: 3, nome: "4ºC", turno: null }),
  ];

  /** Resposta com a escola inteira GRANDE e cada turno com nomes próprios: se a
   *  janela pegar o grupo errado, os nomes denunciam na hora. */
  function respostaPorTurno(caminho: string) {
    const limite = Number(new URLSearchParams(caminho.split("?")[1] ?? "").get("limite") ?? 5);
    const grupo = (prefixo: string, n: number, baseId: number) =>
      [catGrande("melhor_leitor", "Melhor Leitor", "pontos",
                 Math.min(n, limite), n, prefixo, baseId)];
    return {
      periodo: { chave: "mes", rotulo: "Este mês", inicio: null, fim: null },
      categorias: grupo("Escola Inteira", 40, 1000),
      turnos: [
        { turno: "manha", turno_rotulo: "Manhã", total: 20, categorias: grupo("Manha", 20, 2000) },
        { turno: "tarde", turno_rotulo: "Tarde", total: 13, categorias: grupo("Tarde", 13, 3000) },
        // O grupo do turno NULO — o que o backend devolve para turmas sem turno.
        { turno: null, turno_rotulo: "Sem turno", total: 7, categorias: grupo("Sem Turno", 7, 4000) },
      ],
    };
  }

  it("turno \"Sem turno\" (chave VAZIA): a janela usa o grupo do turno, não a escola inteira", async () => {
    responder("GET", URL_TURMAS, turmasComSemTurno);
    responder("GET", URL_PREM, respostaPorTurno);
    responder("GET", URL_EVOL, evolucaoPorDimensao);
    const u = userEvent.setup();
    renderComApp(<Premiacoes />);

    // "Sem turno" é uma opção de verdade, com value = "".
    const seletor = await screen.findByLabelText("Turno");
    const opcao = within(seletor).getByRole("option", { name: "Sem turno" }) as HTMLOptionElement;
    expect(opcao.value).toBe("");
    await u.selectOptions(seletor, opcao);

    // O cartão já é do turno: 7 alunos, nenhum da escola inteira.
    expect(await screen.findByText("Sem Turno 01")).toBeInTheDocument();
    expect(screen.queryByText("Escola Inteira 01")).not.toBeInTheDocument();

    const janela = await abrirRanking(u, "Melhor Leitor");

    // A janela lista os 7 do grupo "Sem turno" — e é o total DELE no cabeçalho.
    await waitFor(() => expect(within(janela).getAllByRole("listitem")).toHaveLength(7));
    expect(within(janela).getByText("Sem Turno 07")).toBeInTheDocument();
    expect(within(janela).getByText("7º")).toBeInTheDocument();
    expect(within(janela).getByText(/7 alunos no período/)).toBeInTheDocument();
    // Nenhum aluno de outro turno nem da escola inteira (a lista da escola tem
    // 40 nomes DIFERENTES: se a janela caísse nela, isto falharia).
    expect(within(janela).queryByText("Escola Inteira 01")).not.toBeInTheDocument();
    expect(within(janela).queryByText("Manha 01")).not.toBeInTheDocument();
    expect(within(janela).queryByText("Tarde 01")).not.toBeInTheDocument();
    expect(within(janela).queryByText(/40 alunos no período/)).not.toBeInTheDocument();
    // As 5 primeiras posições são as mesmas do cartão, na mesma ordem.
    const cinco = within(janela).getAllByRole("listitem").slice(0, 5).map((li) => li.textContent ?? "");
    ["01", "02", "03", "04", "05"].forEach((n, i) => expect(cinco[i]).toContain(`Sem Turno ${n}`));
    // Os 7 cabem de uma vez: nada de "Carregar mais".
    expect(within(janela).queryByRole("button", { name: "Carregar mais" })).not.toBeInTheDocument();
  });

  it("falha ao Carregar mais preserva o que já está na tela e o retry completa sem duplicar", async () => {
    responder("GET", URL_TURMAS, turmasManhaTarde);
    let falhar = true;
    responder("GET", URL_PREM, (caminho: string) => {
      const limite = Number(new URLSearchParams(caminho.split("?")[1] ?? "").get("limite") ?? 5);
      // 4xx: o useApi NÃO repete falha não transitória, então a contagem de
      // chamadas do teste é determinística.
      if (limite > 50 && falhar) return new ApiError(400, "falhou o lote novo");
      return respostaPorLimite(120)(caminho);
    });
    responder("GET", URL_EVOL, evolucaoPorDimensao);
    const u = userEvent.setup();
    renderComApp(<Premiacoes />);
    await screen.findByText("Melhor Leitor");

    const janela = await abrirRanking(u, "Melhor Leitor");
    expect(await within(janela).findByText("Aluno 50")).toBeInTheDocument();

    await u.click(within(janela).getByRole("button", { name: "Carregar mais" }));

    // As 50 continuam visíveis; o erro é do LOTE, não da janela.
    expect(await within(janela).findByRole("alert"))
      .toHaveTextContent("Não foi possível carregar mais posições.");
    expect(within(janela).getAllByRole("listitem")).toHaveLength(50);
    expect(within(janela).getByText("Aluno 01")).toBeInTheDocument();
    expect(within(janela).getByText("Aluno 50")).toBeInTheDocument();
    expect(within(janela).queryByText("Não foi possível carregar o ranking.")).not.toBeInTheDocument();
    // Enquanto o lote falhou, o caminho é tentar de novo — não pular adiante.
    expect(within(janela).queryByRole("button", { name: "Carregar mais" })).not.toBeInTheDocument();
    expect(within(janela).getByRole("button", { name: "Tentar de novo" })).toBeInTheDocument();

    // Nova tentativa, agora bem-sucedida: o MESMO limite volta inteiro.
    falhar = false;
    await u.click(within(janela).getByRole("button", { name: "Tentar de novo" }));

    await waitFor(() => expect(within(janela).getAllByRole("listitem")).toHaveLength(100));
    expect(within(janela).queryByRole("alert")).not.toBeInTheDocument();
    // Repetiu o limite 100 (não pulou para 150) e ninguém foi duplicado.
    expect(limitesPedidos()).toEqual([null, "50", "100", "100"]);
    expect(within(janela).getByText("Aluno 51")).toBeInTheDocument();
    expect(within(janela).getByText("Aluno 100")).toBeInTheDocument();
    expect(within(janela).getAllByText("Aluno 01")).toHaveLength(1);
    expect(within(janela).getAllByText("Aluno 50")).toHaveLength(1);
    const posicoes = within(janela).getAllByRole("listitem")
      .map((li) => (li.textContent ?? "").match(/Aluno (\d+)/)?.[1]);
    expect(new Set(posicoes).size).toBe(100);
  });

  it("trocar de premiação com a janela aberta reinicia o ranking na posição 1", async () => {
    responder("GET", URL_TURMAS, turmasManhaTarde);
    // Duas premiações GRANDES, com nomes próprios: uma não pode vazar na outra.
    responder("GET", URL_PREM, (caminho: string) => {
      const limite = Number(new URLSearchParams(caminho.split("?")[1] ?? "").get("limite") ?? 5);
      return {
        periodo: { chave: "mes", rotulo: "Este mês", inicio: null, fim: null },
        categorias: [
          catGrande("melhor_leitor", "Melhor Leitor", "pontos", Math.min(120, limite), 120),
          catGrande("mais_livros", "Mais Livros Lidos", "livros", Math.min(90, limite), 90,
                    "Leitor", 5000),
        ],
      };
    });
    responder("GET", URL_EVOL, evolucaoPorDimensao);
    const u = userEvent.setup();
    renderComApp(<Premiacoes />);
    await screen.findByText("Melhor Leitor");

    const janelaA = await abrirRanking(u, "Melhor Leitor");
    await u.click(within(janelaA).getByRole("button", { name: "Carregar mais" }));
    await waitFor(() => expect(within(janelaA).getAllByRole("listitem")).toHaveLength(100));
    expect(limitesPedidos()).toEqual([null, "50", "100"]);

    // Troca de premiação SEM fechar a janela.
    await u.click(screen.getByRole("button", { name: "Ver ranking completo de Mais Livros Lidos" }));
    const caixaB = (await screen.findByRole("heading", { level: 2, name: /Mais Livros Lidos/ }))
      .closest("div") as HTMLElement;

    // B começa do zero: 50 linhas a partir da posição 1.
    await waitFor(() => expect(within(caixaB).getAllByRole("listitem")).toHaveLength(50));
    expect(within(caixaB).getAllByRole("listitem")[0]).toHaveTextContent("Leitor 01");
    expect(within(caixaB).getByText(/90 alunos no período/)).toBeInTheDocument();
    // Nenhuma linha da premiação anterior sobrou.
    expect(within(caixaB).queryByText("Aluno 01")).not.toBeInTheDocument();
    expect(within(caixaB).queryByText("Aluno 100")).not.toBeInTheDocument();
    // E o limite de B NÃO herdou o de A: o pedido novo foi 50, não 100.
    expect(limitesPedidos()).toEqual([null, "50", "100", "50"]);
    expect(within(caixaB).queryByText("Leitor 51")).not.toBeInTheDocument();
    // A janela antiga saiu de cena: só uma está montada.
    expect(screen.queryByRole("heading", { level: 2, name: /Melhor Leitor/ })).not.toBeInTheDocument();
  });
});
