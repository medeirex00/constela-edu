import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import Dashboard from "../pages/Dashboard";
import {
  api,
  dashboardFake,
  renderComApp,
  responder,
  responderErro,
  screen,
  userEvent,
  usuarioFake,
  within,
} from "./utils";

const URL_DASH = "/escolas/1/dashboard";

describe("Dashboard", () => {
  it("mostra os indicadores e o Top 5 da escola", async () => {
    responder("GET", URL_DASH, dashboardFake());
    renderComApp(<Dashboard />);

    // Cartões de indicadores.
    expect(await screen.findByText("Alunos")).toBeInTheDocument();
    expect(screen.getByText("42")).toBeInTheDocument(); // total_alunos
    expect(screen.getByText("Professores")).toBeInTheDocument();

    // Ranking compacto (Top 5).
    expect(screen.getByText("Top 5 — Ranking Geral")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Ana Beatriz Souza" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "João Pedro Barbosa" })).toBeInTheDocument();
  });

  it("mostra estado vazio quando ainda não há notas calculadas", async () => {
    responder("GET", URL_DASH, dashboardFake({ top10: [] }));
    renderComApp(<Dashboard />);

    expect(await screen.findByText("Ainda não há notas calculadas")).toBeInTheDocument();
  });

  it("mostra mensagem de falha quando a API de indicadores erra", async () => {
    responderErro("GET", URL_DASH, 500, "Erro interno");
    renderComApp(<Dashboard />);

    expect(
      await screen.findByText("Não foi possível carregar os indicadores"),
    ).toBeInTheDocument();
  });

  it("no primeiro acesso (escola sem turmas nem alunos) mostra só o Comece aqui", async () => {
    // Escola nova: sem turmas e sem alunos → tela inicial limpa.
    responder("GET", URL_DASH, dashboardFake({ total_turmas: 0, total_alunos: 0, top10: [] }));
    renderComApp(<Dashboard />);

    expect(await screen.findByText("Bem-vindo(a) ao Constela Edu")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Comece aqui/ })).toBeInTheDocument();
    // Nada de indicadores nem ranking na tela limpa.
    expect(screen.queryByText("Top 5 — Ranking Geral")).not.toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// Visão Geral (identidade visual v2, referência 1): os blocos novos, cada um com
// a sua rota REAL. Dados fictícios. A data do sistema é fixada (só o `Date`) em
// 31/10/2026 12:00 UTC: o cartão do fim do bimestre e o "há 2 h" dependem dela.
// ---------------------------------------------------------------------------

const URL_VISAO = "/escolas/1/visao-geral";
const URL_SEMANAL = "/escolas/1/atividade-semanal";
const URL_PREMIACOES = "/escolas/1/premiacoes";
const URL_RESUMO = "/escolas/1/resumo-escola";
const URL_MURAL = "/escolas/1/gamificacao/mural";
const URL_INSIGHTS = "/escolas/1/insights";

function visaoGeralFake(over: Record<string, unknown> = {}) {
  return {
    periodo: {
      chave: "bimestre", rotulo: "4º bimestre (05/10 a 31/12)", inicio: "2026-10-05",
      fim: "2026-12-31", dias_decorridos: 27, dias_total: 88,
    },
    comparacao: { rotulo: "mesmo ponto do 3º bimestre", inicio: "2026-07-24", fim: "2026-08-19" },
    alunos: { total: 312, ativos: 180, ativos_anterior: 150, ativos_leitura: 160, ativos_matematica: 120 },
    // Livros: anterior 0 → SEM pílula. Tempo: anterior real → pílula de queda.
    leitura: { contratado: true, livros: 420, livros_anterior: 0, tempo_min: 2033, tempo_min_anterior: 2100 },
    // Atividades: sem anterior (cobertura parcial) → SEM pílula.
    matematica: { contratado: true, atividades: 950, atividades_anterior: null, cobertura: "parcial" },
    atualizado_em: "2026-10-31T10:30:00+00:00",
    ...over,
  };
}

const INICIOS = ["2026-09-07", "2026-09-14", "2026-09-21", "2026-09-28", "2026-10-05", "2026-10-12", "2026-10-19", "2026-10-26"];
function domingo(inicio: string): string {
  const [ano, mes, dia] = inicio.split("-").map(Number);
  return new Date(Date.UTC(ano, mes - 1, dia + 6)).toISOString().slice(0, 10);
}

function semanalFake(over: Record<string, unknown> = {}) {
  const leitura = [40, 42.5, null, 45, 50, 48, 52.3, 20.1];
  const matematica = [30, 31, 33, null, null, 35, 36, 10];
  return {
    denominador: 312,
    leitura_contratado: true,
    matematica_contratado: true,
    observacao: "Aluno ativo na semana: na Leitura, leu ou releu ao menos um livro no Elefante Letrado.",
    semanas: INICIOS.map((inicio, i) => ({
      inicio,
      fim: domingo(inicio),
      leitura_alunos: leitura[i] == null ? null : Math.round((leitura[i] as number) * 3.12),
      leitura_pct: leitura[i],
      matematica_alunos: matematica[i] == null ? null : Math.round((matematica[i] as number) * 3.12),
      matematica_pct: matematica[i],
    })),
    ...over,
  };
}

function premiacoesFake() {
  return {
    periodo: {
      chave: "bimestre", rotulo: "4º bimestre (05/10 a 31/12)",
      inicio: "2026-10-05T00:00:00", fim: "2026-12-31T23:59:59.999999",
    },
    categorias: [
      {
        chave: "melhor_leitor", titulo: "Melhor Leitor", icone: "🏆",
        descricao: "Mais pontos de dificuldade no período", unidade: "pontos", total: 40,
        podio: [
          { posicao: 1, aluno_id: 21, nome: "Helena Prado Lima", turma: "4º Ano A", valor: 1240 },
          { posicao: 2, aluno_id: 22, nome: "Davi Nunes Rocha", turma: "5º Ano B", valor: 1105.5 },
          { posicao: 3, aluno_id: 23, nome: "Lia Castro Melo", turma: "3º Ano A", valor: 990 },
        ],
      },
      {
        chave: "melhor_matematica", titulo: "Melhor Matemática", icone: "🧮",
        descricao: "Maior média ajustada de estrelas por atividade no período",
        unidade: "estrelas/atividade", total: 4,
        // Poucos alunos com atividade: o backend oculta o índice (valor null).
        podio: [
          { posicao: 1, aluno_id: 31, nome: "Rafael Souto Dias", turma: "5º Ano A", valor: null },
          { posicao: 2, aluno_id: 32, nome: "Bia Torres Lopes", turma: "4º Ano B", valor: null },
          { posicao: 3, aluno_id: 33, nome: "Caio Reis Pinto", turma: "4º Ano A", valor: null },
        ],
      },
      {
        chave: "mais_livros", titulo: "Mais Livros Lidos", icone: "📚",
        descricao: "Maior quantidade de livros no período", unidade: "livros", total: 0, podio: [],
      },
    ],
  };
}

function turmaResumo(i: number, over: Record<string, unknown> = {}) {
  return {
    turma: { id: 100 + i, nome: `${(i % 5) + 1}º Ano ${"ABCDEFGH"[i]}`, ano_escolar: `${(i % 5) + 1}º Ano` },
    total_alunos: 30,
    indicadores: { livros_unicos: 50 + i, tempo_leitura_min: 600, atividades: 200, estrelas: 490, pontuacao_media: 2.5 },
    n_leitura: 28, n_matematica: 25, contratadas: ["leitura", "matematica"],
    adocao: 85.5, adocao_leitura: 90, adocao_matematica: 81, alcance: 93.3,
    ...over,
  };
}

function resumoFake() {
  return {
    escola: { id: 1, nome: "Escola Modelo Constela" },
    turmas: [
      // Turma sem nenhum retrato do Elefante: "sem dado", nunca 0 livros / 0 min.
      turmaResumo(0, {
        indicadores: { livros_unicos: 0, tempo_leitura_min: 0, atividades: 200, estrelas: 490, pontuacao_media: 2.5 },
        n_leitura: 0, adocao_leitura: 0,
      }),
      // Turma sem Matific no ano: "sem dado" na coluna da matemática.
      turmaResumo(1, {
        indicadores: { livros_unicos: 51, tempo_leitura_min: 600, atividades: 0, estrelas: 0, pontuacao_media: 0 },
        n_matematica: 0,
      }),
      ...[2, 3, 4, 5, 6, 7].map((i) => turmaResumo(i)),
    ],
  };
}

function muralFake() {
  return {
    destaques: { dia: null, semana: null, mes: null },
    eventos: [
      { tipo: "conquista", icone: "📚", texto: "Helena Prado Lima desbloqueou “Leitor de Bronze”", data: "2026-10-31T10:00:00" },
      { tipo: "conquista", icone: "⭐", texto: "Davi Nunes Rocha desbloqueou “Primeira estrela”", data: "2026-10-29T09:00:00" },
    ],
  };
}

function insightsFake() {
  return {
    indices: [
      { aluno_id: 41, nome: "Otávio Fernandes Cruz", turma: "4º Ano A", engajamento: 78.4, evolucao: 10, persistencia: 50 },
    ],
    alertas: [
      { tipo: "nota_baixa", gravidade: "alta", aluno_id: 42, nome: "Bruno Lima", turma: "4º Ano A", texto: "Bruno Lima está com nota 23,2 em Leitura." },
    ],
  };
}

function semearTudo() {
  responder("GET", URL_DASH, dashboardFake());
  responder("GET", URL_VISAO, visaoGeralFake());
  responder("GET", URL_SEMANAL, semanalFake());
  responder("GET", URL_PREMIACOES, premiacoesFake());
  responder("GET", URL_RESUMO, resumoFake());
  responder("GET", URL_MURAL, muralFake());
  responder("GET", URL_INSIGHTS, insightsFake());
}

/** Razão de contraste WCAG 2.x entre duas cores "#RRGGBB". */
function contraste(a: string, b: string): number {
  const luminancia = (hex: string) => {
    const [r, g, bl] = [1, 3, 5]
      .map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
      .map((v) => (v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
    return 0.2126 * r + 0.7152 * g + 0.0722 * bl;
  };
  const [claro, escuro] = [luminancia(a), luminancia(b)].sort((x, y) => y - x);
  return (claro + 0.05) / (escuro + 0.05);
}

function chamou(trecho: string): boolean {
  return api.mock.calls.some(([caminho]) => String(caminho).includes(trecho));
}

describe("Visão geral — identidade v2 (painel da escola)", () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-10-31T12:00:00Z"));
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("cumprimenta pelo primeiro nome e mostra o período que vem da rota", async () => {
    semearTudo();
    renderComApp(<Dashboard />);

    expect(await screen.findByRole("heading", { level: 1, name: /^Olá, Coordenadora/ })).toBeInTheDocument();
    expect(screen.getByText("Acompanhe a leitura e a matemática da escola neste bimestre.")).toBeInTheDocument();
    // Chip INFORMATIVO (não é um seletor): o rótulo e o ano saem da resposta.
    expect(await screen.findByText("4º bimestre · 2026")).toBeInTheDocument();
    expect(api).toHaveBeenCalledWith("/escolas/1/visao-geral?periodo=bimestre", expect.anything());
  });

  it("4 indicadores do bimestre; a variação só aparece com o valor anterior real (> 0)", async () => {
    semearTudo();
    renderComApp(<Dashboard />);

    expect(await screen.findByText("Alunos ativos")).toBeInTheDocument();
    expect(screen.getByText("180")).toBeInTheDocument();
    expect(screen.getByText("de 312 alunos")).toBeInTheDocument();
    expect(screen.getByText("160 na leitura · 120 no Matific")).toBeInTheDocument();
    expect(screen.getByText("Livros lidos no bimestre")).toBeInTheDocument();
    expect(screen.getByText("420")).toBeInTheDocument();
    expect(screen.getByText("Horas de leitura")).toBeInTheDocument();
    expect(screen.getByText("33h 53min")).toBeInTheDocument();
    expect(screen.getByText("Atividades no Matific")).toBeInTheDocument();
    expect(screen.getByText("950")).toBeInTheDocument();
    // Cobertura parcial do Matific: aviso leve, não alarme. O backend devolve "parcial"
    // por três causas (início tardio, aluno interrompido, coleta parada): o texto não
    // afirma uma só.
    expect(screen.getByText(
      "Cobertura parcial: parte do período ou dos alunos ainda não foi coletada pelo Matific.",
    )).toBeInTheDocument();
    expect(screen.queryByText(/começou a ser coletada depois do início/)).not.toBeInTheDocument();

    // Pílulas: alunos ativos (180 × 150 = +20%) e horas (2033 × 2100 = −3,2%). Livros
    // (anterior 0) e atividades (sem anterior) ficam SEM pílula.
    expect(screen.getAllByText("em relação ao mesmo ponto do 3º bimestre")).toHaveLength(2);
    expect(screen.getByText("20%")).toBeInTheDocument();
    expect(screen.getByText("3,2%")).toBeInTheDocument();
    expect(screen.getByText("aumento de")).toBeInTheDocument();
    expect(screen.getByText("queda de")).toBeInTheDocument();
  });

  it("Leitura parada no meio do bimestre: os cartões de Leitura e 'Alunos ativos' dizem até quando contam", async () => {
    semearTudo();
    responder("GET", URL_VISAO, visaoGeralFake({
      comparacao: null,
      leitura: {
        contratado: true, livros: 120, livros_anterior: null, tempo_min: 600, tempo_min_anterior: null,
        cobertura: "parcial", coletado_ate: "2026-10-07",
      },
    }));
    renderComApp(<Dashboard />);

    expect(await screen.findByText("Livros lidos no bimestre")).toBeInTheDocument();
    const indicadores = screen.getByTestId("indicadores-do-bimestre");
    // Livros e Horas de leitura: a mesma nota, com a data da última coleta (dd/mm).
    expect(within(indicadores).getAllByText(
      "Cobertura parcial: o Elefante Letrado foi coletado até 07/10; o número conta só até essa data.",
    )).toHaveLength(2);
    // Alunos ativos soma leitores até 07/10 com o Matific até hoje (também parcial aqui).
    expect(within(indicadores).getByText(
      /Cobertura parcial: na leitura, contado até 07\/10; no Matific, parte do período/,
    )).toBeInTheDocument();
  });

  it("Leitura completa: nenhuma nota de cobertura nos cartões de Leitura", async () => {
    semearTudo();
    responder("GET", URL_VISAO, visaoGeralFake({
      leitura: {
        contratado: true, livros: 420, livros_anterior: 0, tempo_min: 2033, tempo_min_anterior: 2100,
        cobertura: "completa", coletado_ate: "2026-10-30",
      },
    }));
    renderComApp(<Dashboard />);

    expect(await screen.findByText("Livros lidos no bimestre")).toBeInTheDocument();
    expect(screen.queryByText(/Elefante Letrado foi coletado até/)).not.toBeInTheDocument();
    expect(screen.queryByText(/na leitura, contado até/)).not.toBeInTheDocument();
  });

  it("sem comparação equivalente, nenhuma pílula de variação", async () => {
    semearTudo();
    responder("GET", URL_VISAO, visaoGeralFake({ comparacao: null }));
    renderComApp(<Dashboard />);

    expect(await screen.findByText("Alunos ativos")).toBeInTheDocument();
    expect(screen.queryByText("em relação ao mesmo ponto do 3º bimestre")).not.toBeInTheDocument();
    expect(screen.getByText("Sem comparação com o período anterior.")).toBeInTheDocument();
  });

  it("gráfico semanal: denominador declarado, lacuna em semana sem coleta e a nota da semana em curso", async () => {
    semearTudo();
    renderComApp(<Dashboard />);

    expect(await screen.findByText("% dos alunos (de 312) que usaram cada plataforma")).toBeInTheDocument();
    const grafico = screen.getByRole("img", { name: /^Alunos ativos por semana, 8 semanas/ });
    expect(grafico).toHaveAccessibleName(expect.stringContaining("Leitura · Elefante Letrado: 20,1%"));
    // 1 semana sem coleta na Leitura + 2 na Matemática: "sem coleta", nunca 0%.
    const tabela = screen.getByRole("table", { name: "Alunos ativos por semana: valores por semana" });
    expect(within(tabela).getAllByText("sem coleta")).toHaveLength(3);
    expect(screen.getByText("A semana atual ainda está em curso: o número dela pode crescer até domingo."))
      .toBeInTheDocument();
    expect(api).toHaveBeenCalledWith("/escolas/1/atividade-semanal?semanas=8", expect.anything());
  });

  it("gráfico sem nenhuma coleta mostra o vazio honesto", async () => {
    semearTudo();
    const vazio = semanalFake();
    vazio.semanas = vazio.semanas.map((s) => ({
      ...s, leitura_alunos: null, leitura_pct: null, matematica_alunos: null, matematica_pct: null,
    }));
    responder("GET", URL_SEMANAL, vazio);
    renderComApp(<Dashboard />);

    expect(await screen.findByText("Ainda não há coleta nas últimas 8 semanas")).toBeInTheDocument();
    expect(screen.queryByRole("img", { name: /Alunos ativos por semana/ })).not.toBeInTheDocument();
  });

  it("cartão escuro: fim do bimestre pelo calendário oficial e o top 3 real com a unidade", async () => {
    semearTudo();
    renderComApp(<Dashboard />);

    // Não existe data de premiação: o cartão conta até o FIM do bimestre.
    expect(await screen.findByRole("heading", { name: "Fim do 4º bimestre" })).toBeInTheDocument();
    expect(screen.getByText("em 61 dias")).toBeInTheDocument();
    expect(screen.getByText("31/12/2026 · calendário oficial")).toBeInTheDocument();
    expect(screen.queryByText(/Próxima premiação/i)).not.toBeInTheDocument();

    const leitura = await screen.findByRole("list", { name: "Top 3 · Melhor Leitor" });
    expect(within(leitura).getAllByRole("listitem")).toHaveLength(3);
    expect(within(leitura).getByText("Helena Prado Lima")).toBeInTheDocument();
    expect(within(leitura).getByText("1.240")).toBeInTheDocument();
    expect(within(leitura).getAllByText("pontos")).toHaveLength(3);
    expect(within(leitura).getByText("1º lugar")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Leitura" })).toHaveAttribute("aria-selected", "true");
    expect(api).toHaveBeenCalledWith("/escolas/1/premiacoes?periodo=bimestre&limite=3", expect.anything());

    // Matemática com o índice oculto pelo backend: "—" e o porquê, na ordem do backend.
    await userEvent.click(screen.getByRole("tab", { name: "Matemática" }));
    const mat = screen.getByRole("list", { name: "Top 3 · Melhor Matemática" });
    expect(within(mat).getAllByText("—")).toHaveLength(3);
    expect(screen.getByText(/Índice não exibido: poucos alunos fizeram atividade no bimestre/)).toBeInTheDocument();
  });

  it("'Gerar certificados' abre o lote com o top 3 da aba e o modelo da plataforma", async () => {
    semearTudo();
    renderComApp(<Dashboard />);

    await screen.findByRole("list", { name: "Top 3 · Melhor Leitor" });
    await userEvent.click(screen.getByRole("tab", { name: "Matemática" }));
    await userEvent.click(screen.getByRole("button", { name: "Gerar certificados" }));

    const janela = await screen.findByRole("dialog", { name: "Gerar certificados" });
    expect(within(janela).getByText("Visão geral · Melhor Matemática · 4º bimestre")).toBeInTheDocument();
    expect(within(janela).getByRole("radio", { name: /Matific/ })).toBeChecked();
    const lote = within(janela).getByRole("list", { name: "Alunos do lote" });
    expect(within(lote).getAllByRole("listitem")).toHaveLength(3);
    expect(within(lote).getByText("Rafael Souto Dias")).toBeInTheDocument();
  });

  it("desempenho por turma: até 6 turmas, link para todas, Matific em estrelas/atividade e 'sem dado' no lugar de 0", async () => {
    semearTudo();
    renderComApp(<Dashboard />);

    const tabela = await screen.findByRole("table", { name: /Desempenho por turma do ano letivo/ });
    // Cabeçalho + 6 turmas (das 8).
    expect(within(tabela).getAllByRole("row")).toHaveLength(7);
    expect(screen.getByRole("link", { name: "Ver as 8 turmas" })).toHaveAttribute("href", "/turmas");
    expect(within(tabela).getByRole("columnheader", { name: /Matific/ })).toHaveTextContent("estrelas/atividade");
    expect(within(tabela).queryByText(/acertos/i)).not.toBeInTheDocument();

    const semElefante = within(tabela).getByRole("row", { name: /1º Ano A/ });
    expect(within(semElefante).getAllByText("sem dado")).toHaveLength(2);
    expect(within(semElefante).getByText("2,45")).toBeInTheDocument(); // 490 ÷ 200
    expect(within(semElefante).getByText("85,5%")).toBeInTheDocument();
    const semMatific = within(tabela).getByRole("row", { name: /2º Ano B/ });
    expect(within(semMatific).getByText("sem dado")).toBeInTheDocument();
    expect(within(tabela).getByRole("link", { name: "3º Ano C" })).toHaveAttribute("href", "/turmas/102");
  });

  it("destaques recentes: conquistas do mural com o tempo relativo da COLETA", async () => {
    semearTudo();
    renderComApp(<Dashboard />);

    expect(await screen.findByText("Helena Prado Lima desbloqueou “Leitor de Bronze”")).toBeInTheDocument();
    expect(screen.getByText("há 2 h")).toBeInTheDocument();
    expect(screen.getByText("há 2 dias")).toBeInTheDocument();
    expect(screen.getByText("A data é a do dado em que a conquista apareceu (numa coleta por período, o fim do período), não o momento exato na plataforma."))
      .toBeInTheDocument();
  });

  it("desempenho por turma: o Elefante é contador vitalício — 'acumulado', nunca 'no ano'", async () => {
    semearTudo();
    renderComApp(<Dashboard />);

    const tabela = await screen.findByRole("table", { name: /Desempenho por turma do ano letivo/ });
    const livros = within(tabela).getByRole("columnheader", { name: /^Livros/ });
    expect(livros).toHaveTextContent("acumulado");
    expect(livros).not.toHaveTextContent(/no ano/);
    const tempo = within(tabela).getByRole("columnheader", { name: /^Leitura/ });
    expect(tempo).toHaveTextContent("tempo acumulado");
    expect(tempo).not.toHaveTextContent(/no ano/);
    // Rodapé: cada plataforma com o seu acumulado (Elefante desde o início, Matific no ano).
    expect(screen.getByText(/Leitura: acumulado desde o início no Elefante Letrado\./)).toBeInTheDocument();
    expect(screen.getByText(/Matific: estrelas ganhas por atividade concluída, acumuladas no ano letivo\./))
      .toBeInTheDocument();
    expect(screen.queryByText(/Acumulado do ano letivo/)).not.toBeInTheDocument();
    expect(screen.getByText("Leitura e matemática de cada turma do ano letivo")).toBeInTheDocument();
  });

  it("'No ano letivo': livros e tempo de leitura dizem que são desde o início no Elefante", async () => {
    semearTudo();
    renderComApp(<Dashboard />);

    await screen.findByRole("heading", { name: "No ano letivo 2026" });
    const livros = screen.getByText("Livros lidos").parentElement as HTMLElement;
    expect(livros).toHaveTextContent("títulos únicos, desde o início no Elefante");
    const tempo = screen.getByText("Tempo de leitura").parentElement as HTMLElement;
    expect(tempo).toHaveTextContent("desde o início no Elefante");
    // O Matific do /dashboard é do ano letivo: sem o detalhe do Elefante.
    const atividades = screen.getByText("Atividades Matific").parentElement as HTMLElement;
    expect(atividades).not.toHaveTextContent(/Elefante/);
    expect(screen.queryByRole("heading", { name: "Totais do ano letivo" })).not.toBeInTheDocument();
  });

  it("destaques: o engajamento é dos últimos 30 dias, não do ano letivo", async () => {
    semearTudo();
    renderComApp(<Dashboard />);

    // Espera o /insights chegar (o bloco remonta quando os dados do painel chegam).
    expect(await screen.findByRole("link", { name: "Otávio Fernandes Cruz" })).toBeInTheDocument();
    expect(screen.getByText("Maior engajamento nos últimos 30 dias")).toBeInTheDocument();
    expect(screen.queryByText("Maior engajamento no ano letivo")).not.toBeInTheDocument();
  });

  it("gráfico: a série do Matific tem contraste de traço (≥ 3:1) e a pílula, de texto (≥ 4,5:1)", async () => {
    semearTudo();
    const { container } = renderComApp(<Dashboard />);

    await screen.findByRole("img", { name: /^Alunos ativos por semana, 8 semanas/ });
    const serie = container.querySelector('[data-serie="Matemática · Matific"]') as SVGGElement;
    const traco = serie.querySelector("path[data-trecho]") as SVGPathElement;
    const cor = traco.getAttribute("stroke") as string;
    expect(cor).toBe("#0D9488");
    expect(contraste(cor, "#FFFFFF")).toBeGreaterThanOrEqual(3);
    const pilula = container.querySelector('[data-rotulo-final="Matemática · Matific"]') as SVGGElement;
    const fundo = pilula.querySelector("rect")?.getAttribute("fill") as string;
    const texto = pilula.querySelector("text")?.getAttribute("fill") as string;
    expect(fundo).toBe(cor);
    expect(contraste(fundo, texto)).toBeGreaterThanOrEqual(4.5);
  });

  it("o que já existia continua: média geral, totais, Top 5, destaques e alertas", async () => {
    semearTudo();
    renderComApp(<Dashboard />);

    expect(await screen.findByRole("heading", { name: "No ano letivo 2026" })).toBeInTheDocument();
    expect(screen.getByText("Média geral")).toBeInTheDocument();
    expect(screen.getByText("78,5")).toBeInTheDocument();
    expect(screen.getByText("Professores")).toBeInTheDocument();
    expect(screen.getByText("Top 5 — Ranking Geral")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Ana Beatriz Souza" })).toBeInTheDocument();
    expect(await screen.findByRole("link", { name: "Otávio Fernandes Cruz" })).toBeInTheDocument();
    const alerta = screen.getByRole("link", { name: /Gravidade alta: Bruno Lima está com nota 23,2/ });
    expect(alerta).toHaveAttribute("href", "/alunos/42");
    // A turma do alerta é um trecho só (não se parte entre "4º" e "Ano A").
    expect(within(alerta).getByText("· 4º Ano A")).toHaveClass("whitespace-nowrap");
    // Gestão vê os atalhos das plataformas.
    expect(screen.getByRole("link", { name: "Elefante Letrado" })).toHaveAttribute("href", "/elefante");
    expect(screen.getByRole("link", { name: "Matific" })).toHaveAttribute("href", "/matific");
  });

  it("um bloco com erro não derruba os outros e tem 'Tentar de novo'", async () => {
    semearTudo();
    responderErro("GET", URL_VISAO, 500, "Erro interno");
    renderComApp(<Dashboard />);

    const titulo = await screen.findByText("Não foi possível carregar os números do bimestre");
    // Os outros blocos seguem de pé.
    expect(screen.getByText("Top 5 — Ranking Geral")).toBeInTheDocument();
    expect(await screen.findByRole("list", { name: "Top 3 · Melhor Leitor" })).toBeInTheDocument();

    responder("GET", URL_VISAO, visaoGeralFake());
    const alerta = titulo.closest('[role="alert"]') as HTMLElement;
    await userEvent.click(within(alerta).getByRole("button", { name: "Tentar de novo" }));
    expect(await screen.findByText("Alunos ativos")).toBeInTheDocument();
    expect(screen.queryByText("Não foi possível carregar os números do bimestre")).not.toBeInTheDocument();
  });

  it("falha do /insights vira erro — nunca 'nenhuma situação crítica'", async () => {
    semearTudo();
    responderErro("GET", URL_INSIGHTS, 500, "Erro interno");
    renderComApp(<Dashboard />);

    expect(await screen.findByText("Não foi possível carregar os destaques e alertas")).toBeInTheDocument();
    expect(screen.queryByText("Nenhuma situação crítica identificada no momento.")).not.toBeInTheDocument();
  });

  it("módulo fora do plano: o cartão, a série e a aba dele não aparecem", async () => {
    semearTudo();
    responder("GET", URL_VISAO, visaoGeralFake({
      matematica: { contratado: false, atividades: null, atividades_anterior: null, cobertura: "sem_dado" },
    }));
    responder("GET", URL_SEMANAL, semanalFake({ matematica_contratado: false }));
    renderComApp(<Dashboard />, { usuario: usuarioFake({ modulos: ["leitura"] }) });

    expect(await screen.findByText("Alunos ativos")).toBeInTheDocument();
    expect(screen.queryByText("Atividades no Matific")).not.toBeInTheDocument();
    await screen.findByRole("img", { name: /Alunos ativos por semana/ });
    expect(screen.queryByText("Matemática · Matific")).not.toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Matemática" })).not.toBeInTheDocument();
    const tabela = await screen.findByRole("table", { name: /Desempenho por turma/ });
    expect(within(tabela).queryByRole("columnheader", { name: /Matific/ })).not.toBeInTheDocument();
  });

  it("professor: sem as rotas que o negam (turmas e mural); vê os destaques e alertas das turmas dele", async () => {
    semearTudo();
    renderComApp(<Dashboard />, { usuario: usuarioFake({ cargo: "professor", nome: "Paula Mendes" }) });

    expect(await screen.findByRole("heading", { level: 1, name: /^Olá, Paula/ })).toBeInTheDocument();
    expect(screen.getByText("Acompanhe a leitura e a matemática das suas turmas neste bimestre.")).toBeInTheDocument();
    expect(await screen.findByRole("heading", { level: 2, name: "Destaques das suas turmas" })).toBeInTheDocument();
    expect(await screen.findByText("Alunos ativos")).toBeInTheDocument();
    // Premiação: o backend recorta o pódio às turmas dele e libera o certificado dos seus.
    expect(await screen.findByRole("list", { name: "Top 3 · Melhor Leitor" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Gerar certificados" })).toBeEnabled();

    expect(screen.queryByText("Desempenho por turma")).not.toBeInTheDocument();
    expect(screen.queryByText("Destaques recentes")).not.toBeInTheDocument();
    expect(chamou("/resumo-escola")).toBe(false);
    expect(chamou("/gamificacao/mural")).toBe(false);
    // Atalhos de plataforma são telas de gestão (a guarda mandaria o professor de volta).
    expect(screen.queryByRole("link", { name: "Elefante Letrado" })).not.toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// Celular (revisão das capturas, 31/10): KPIs 2 por linha, a turma do Top 5 sob o nome
// (uma vez só no DOM) e "Desempenho por turma" com Leitura e Matific alcançáveis.
// ---------------------------------------------------------------------------

describe("Visão geral — celular", () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-10-31T12:00:00Z"));
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("os 4 indicadores do bimestre ficam 2 por linha (do sm para cima, o de antes)", async () => {
    semearTudo();
    renderComApp(<Dashboard />);

    const grade = await screen.findByTestId("indicadores-do-bimestre");
    expect(grade).toHaveClass("grid-cols-2", "gap-3", "sm:gap-5", "xl:grid-cols-4");
    expect(grade).not.toHaveClass("grid-cols-1");
    expect(grade.children).toHaveLength(4);
    expect(within(grade).getByText("Alunos ativos")).toBeInTheDocument();
    expect(within(grade).getByText("Atividades no Matific")).toBeInTheDocument();
  });

  it("Top 5: a turma aparece em toda largura (sob o nome no celular, ao lado no desktop), uma vez só", async () => {
    semearTudo();
    renderComApp(<Dashboard />);

    const nome = await screen.findByRole("link", { name: "Ana Beatriz Souza" });
    const item = nome.closest("li") as HTMLElement;
    const turmas = within(item).getAllByText("3º Ano A");
    expect(turmas).toHaveLength(1);
    // Antes: `hidden sm:inline-flex` — no celular a turma sumia da linha.
    expect(turmas[0]).not.toHaveClass("hidden");
    // Nome e turma num invólucro que vira coluna no celular e some (`contents`) do sm para cima.
    const involucro = nome.parentElement as HTMLElement;
    expect(involucro).toContainElement(turmas[0]);
    expect(involucro).toHaveClass("flex-col", "sm:contents");
    // O nome pode quebrar em duas linhas no celular; no desktop segue truncado, com o title.
    expect(nome).toHaveClass("truncate", "max-sm:whitespace-normal", "max-sm:line-clamp-2");
    expect(nome).toHaveAttribute("title", "Ana Beatriz Souza");
  });

  it("Desempenho por turma: a turma fica presa à esquerda no celular e Leitura e Matific seguem na linha", async () => {
    semearTudo();
    renderComApp(<Dashboard />);

    const tabela = await screen.findByRole("table", { name: /Desempenho por turma do ano letivo/ });
    const turma = within(tabela).getByRole("link", { name: "3º Ano C" });
    const celula = turma.closest("td") as HTMLElement;
    expect(celula).toHaveClass("presa-esquerda-celular");
    expect(celula).not.toHaveClass("sticky");
    expect(within(tabela).getByRole("columnheader", { name: "Turma" })).toHaveClass("presa-esquerda-celular");
    const linha = within(tabela).getByRole("row", { name: /3º Ano C/ });
    expect(within(linha).getAllByRole("cell")).toHaveLength(6);
    expect(within(linha).getByText("2,45")).toBeInTheDocument();
  });

  it("Desempenho por turma: tabela que não cabe avisa em texto, acima dela, que desliza de lado", async () => {
    vi.spyOn(Element.prototype, "clientWidth", "get").mockReturnValue(300);
    vi.spyOn(Element.prototype, "scrollWidth", "get").mockReturnValue(700);
    semearTudo();
    renderComApp(<Dashboard />);

    const regiao = await screen.findByRole("region", { name: "Desempenho por turma: tabela completa" });
    expect(within(regiao).getByRole("columnheader", { name: /Matific/ })).toBeInTheDocument();
    expect(within(regiao).getByRole("columnheader", { name: /Adoção/ })).toBeInTheDocument();
    const aviso = screen.getByText(/Deslize a tabela para o lado para ver todas as colunas/);
    expect(aviso.compareDocumentPosition(regiao) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
});
