/**
 * Relatório por Período — a tela não pode transformar lacuna em zero nem somar
 * os dois eixos de data do Elefante.
 *
 * O backend já devolve `tempo_min_por_evento: null`, `questoes: null` e
 * `livros_novos` separado de `livros_com_atividade`. Um componente que
 * imprimisse `?? 0` ou que exibisse um único "livros" apagaria exatamente a
 * distinção que custou uma medição em produção para ficar de pé:
 *
 *   livros_novos         = `Leitura.data` — o número que BATE com a premiação;
 *   livros_com_atividade = `EventoAluno.ocorrido_em` — o único que vê releitura.
 *
 * Aqui também fica travado que a tela PUBLICA a janela efetiva dos números que
 * vêm de coleta (o ganho entre retratos pode cobrir mais que o mês pedido).
 */
import { describe, expect, it } from "vitest";

import RelatorioPeriodo from "../pages/RelatorioPeriodo";
import {
  ApiError,
  apiDownload,
  escolaFake,
  renderComApp,
  responder,
  responderErro,
  screen,
  userEvent,
  usuarioFake,
  within,
} from "./utils";

const texto = () => (document.body.textContent ?? "").replace(/\s+/g, " ").trim();

/** Vocabulário interno que o relatório não mostra a quem o lê (D5): nome de campo,
 *  classificação técnica, jargão do banco. Vale para TODO texto da tela — inclusive os
 *  avisos de cobertura que chegaram depois (S9: as questões que não vieram). */
const TERMOS_INTERNOS = ["SUPORTADO", "Leitura.data", "EventoAluno", "SnapshotMatific",
  "SnapshotElefante", "NULLABLE", "PISO", "totalTimeSpent", "retrato", "Ressalva",
  "tempo min por evento", "livros_relidos", "responses", "questoes_tentativas",
  "campos_nao_atualizados", "conector"];
function semVocabularioInterno(t: string) {
  for (const termo of TERMOS_INTERNOS) {
    expect(t, termo).not.toContain(termo);
  }
  expect(t).not.toMatch(/\bde o início/);
}

const SUPORTE_ELEFANTE = {
  livros_novos: {
    campo: "Leitura.data (COUNT)",
    classificacao: "SUPORTADO",
    por_que: "é o MESMO campo e filtro da premiação oficial 'Mais Livros'",
    ressalva: "releitura não entra aqui — entra em livros_relidos",
  },
  tempo_min: {
    campo: "Leitura.tempo_leitura_min (SUM, filtrado por Leitura.data)",
    classificacao: "SUPORTADO COM RESSALVA",
    por_que: "é o MESMO campo da premiação oficial 'Mais Tempo'",
    ressalva: "o campo é NULLABLE e nulo entra como 0, então o total é um PISO",
  },
  livros_com_atividade: {
    campo: "EventoAluno.ocorrido_em (COUNT DISTINCT livro_id)",
    classificacao: "SUPORTADO",
    por_que: "o espelho registra TODA linha do relatório, inclusive a releitura",
  },
  tempo_min_por_evento: {
    classificacao: "NÃO SUPORTADO",
    por_que: "o tempo do evento vem do totalTimeSpent da API, por LIVRO",
  },
};

function relatorioFake(sobrepor: Record<string, unknown> = {}) {
  return {
    escola: { id: 1, nome: "ESCOLA TESTE", ano_letivo: 2026 },
    periodo: {
      preset: "mes_anterior", rotulo: "setembro de 2026",
      inicio: "2026-09-01T00:00:00", fim: "2026-09-30T23:59:59.999999",
      inclusivo: true,
    },
    escopo: { tipo: "escola", turma_id: null, aluno_id: null, restrito_a_turmas: null },
    plataformas: ["elefante", "matific"],
    plataformas_rotulo: "Elefante Letrado + Matific",
    alunos: { considerados: 30, com_atividade: 18, sem_atividade: 12 },
    nao_suportado: [
      {
        plataforma: "elefante", metrica: "tempo_min_por_evento",
        por_que: "o campo é acumulado por livro: a soma repete o mesmo tempo",
      },
      {
        plataforma: "matific", metrica: "questoes",
        por_que: "não existe contador de questões no retrato do Matific",
      },
    ],
    elefante: {
      livros_novos: 12, tempo_min: 95, alunos_com_livro_novo: 7,
      livros_com_atividade: 20, livros_relidos: 8, eventos_leitura: 23,
      tempo_min_por_evento: null,
      alunos_com_atividade: 9,
      questoes_tentativas: null, questoes_acertos: null,
      alunos_sem_retrato: 30, janela_efetiva_questoes: null,
      sem_atividade: 21, primeiro_evento_da_escola: "2025-08-01T10:00:00",
      suporte: SUPORTE_ELEFANTE,
    },
    matific: {
      atividades: 44, estrelas: 19, alunos_com_atividade: 5,
      alunos_sem_retrato: 25, questoes: null,
      janela_efetiva: {
        data_base_mais_antiga: "2026-08-15T12:00:00",
        data_base_mais_recente: "2026-08-20T12:00:00",
        data_atual_mais_antiga: "2026-09-28T12:00:00",
        data_atual_mais_recente: "2026-09-29T12:00:00",
        observacao: "o número vem da diferença entre COLETAS; este é o intervalo "
          + "real que ele cobre, que pode ser mais largo que o período pedido",
      },
      sem_atividade: 25,
      suporte: {
        campo: "SnapshotMatific.data_referencia (diferença de acumulados)",
        classificacao: "SUPORTADO COM RESSALVA",
        por_que: "o Matific entrega contador ACUMULADO do ano, não evento datado",
        ressalva: "sem retrato DENTRO da janela o aluno não é elegível",
        questoes: {
          classificacao: "NÃO SUPORTADO",
          por_que: "não existe contador de questões",
        },
      },
    },
    por_turma: [{
      turma_id: 9, turma: "3º Ano A", ano_escolar: "3º Ano", turno: "manha",
      alunos: 30, com_atividade: 18,
      elefante: { livros_novos: 12, tempo_min: 95, livros_com_atividade: 20, livros_relidos: 8, eventos_leitura: 23 },
      matific: { atividades: 44, estrelas: 19 },
    }],
    por_aluno: [
      {
        aluno_id: 5, nome: "Ana Beatriz Souza", turma: "3º Ano A", turma_id: 9,
        ano_escolar: "3º Ano",
        elefante: { livros_novos: 3, tempo_min: 21, livros_com_atividade: 5, livros_relidos: 2, eventos_leitura: 6 },
        matific: { atividades: 10, estrelas: 4 }, sem_atividade: false,
      },
      {
        aluno_id: 6, nome: "Joao Pedro Barbosa", turma: "3º Ano A", turma_id: 9,
        ano_escolar: "3º Ano", elefante: null, matific: null, sem_atividade: true,
      },
    ],
    ...sobrepor,
  };
}

function montar(dados: Record<string, unknown> = relatorioFake()) {
  responder("GET", /\/escolas\/1\/turmas/, [
    { id: 9, nome: "3º Ano A", ano_escolar: "3º Ano", ano_letivo: 2026, professor_id: null, turno: "manha", capacidade_maxima: null, observacoes: null },
  ]);
  responder("GET", /\/escolas\/1\/alunos/, { itens: [], total: 0 });
  responder("GET", /\/escolas\/1\/relatorios\/periodo/, dados);
  return renderComApp(<RelatorioPeriodo />, {
    rota: "/relatorios/periodo",
    usuario: usuarioFake(),
    escolas: [escolaFake({ id: 1 })],
    escolaSelecionada: 1,
    periodo: { preset: "mes_anterior" },
  });
}

describe("Relatório por Período", () => {
  it("mostra os DOIS eixos de livro, rotulados, sem somá-los", async () => {
    montar();
    // "Livros novos" aparece no cartão E nas duas tabelas — findAllByText.
    expect((await screen.findAllByText("Livros novos")).length).toBeGreaterThan(1);
    const t = texto();
    expect(t).toContain("Livros com atividade");
    expect(t).toContain("8 relido(s)");
    // 12 + 20 = 32 seria a soma errada dos dois eixos.
    expect(t).not.toContain("32 livros");
  });

  it("o tempo do período é o da Leitura, e o por evento não aparece como número", async () => {
    montar();
    expect(await screen.findByText("Tempo de leitura")).toBeTruthy();
    expect(texto()).toContain("1h 35min");
  });

  it("questão sem dado é '—' com o motivo, nunca zero", async () => {
    montar();
    await screen.findByText("Tempo de leitura");
    const t = texto();
    expect(t).toContain("não existe este contador no Matific");
    expect(t).toContain("sem coleta na janela (não contam como zero)");
  });

  it("declara, em linguagem de professor, se dá para confiar em cada número", async () => {
    montar();
    await screen.findByText("Tempo de leitura");
    const detalhes = await screen.findByText("Como ler estes números");
    detalhes.click();
    const t = texto();
    expect(t).toContain("Confiável, com um cuidado");
    expect(t).toContain("O que este relatório NÃO responde");
    // A mesma informação de antes, dita para quem lê o relatório.
    expect(t).toContain("É a mesma conta da premiação “Mais livros”");
    expect(t).toContain("Por isso um livro lido de novo não entra aqui");
    // A data do livro novo é a de quando ele apareceu no relatório da plataforma (a
    // 1ª importação dele), não a da primeira leitura.
    expect(t).toContain("Vale a data em que o livro apareceu pela primeira vez no relatório da plataforma");
    expect(t).not.toContain("primeira leitura");
    expect(t).toContain("o total é o mínimo lido no período — o tempo real pode ser maior");
    // O colapso no mesmo minuto afeta a contagem de vezes (que a tela não mostra), não
    // o número de livros diferentes: “Livros com atividade” não é um piso.
    expect(t).not.toContain("Duas leituras do mesmo livro no mesmo minuto");
    expect(t).not.toContain("o número de leituras é um mínimo");
    expect(t).toContain("Não dá para saber quanto durou cada leitura");
    expect(t).toContain("O Matific guarda atividades, estrelas e pontuação média, mas não conta questões");
    expect(t).toContain("o total no fim menos o de antes do início — a mesma regra das premiações");
    // Nada de vocabulário interno: nome de campo, classificação técnica, jargão do banco.
    semVocabularioInterno(t);
    expect(document.querySelector("code")).toBeNull();
  });

  it("'Tempo de cada leitura' aparece uma vez só, em 'O que este relatório NÃO responde'", async () => {
    montar();
    await screen.findByText("Tempo de leitura");
    (await screen.findByText("Como ler estes números")).click();
    const t = texto();
    const vezes = (s: string) => t.split(s).length - 1;
    // O backend o manda em `suporte` (NÃO SUPORTADO) e em `nao_suportado`: a tela
    // explicava duas vezes, com o mesmo texto. Fica o item com o nome da plataforma.
    expect(vezes("Não dá para saber quanto durou cada leitura")).toBe(1);
    expect(vezes("Tempo de cada leitura")).toBe(1);
    expect(t).toContain("Tempo de cada leitura (Elefante Letrado)");
    expect(t.indexOf("Tempo de cada leitura")).toBeGreaterThan(t.indexOf("O que este relatório NÃO responde"));
  });

  it("número não calculado que o backend não lista em 'NÃO responde' continua com o selo", async () => {
    const dados = relatorioFake();
    dados.nao_suportado = dados.nao_suportado.filter((n) => n.metrica !== "tempo_min_por_evento");
    montar(dados);
    await screen.findByText("Tempo de leitura");
    (await screen.findByText("Como ler estes números")).click();
    const t = texto();
    expect(t).toContain("Não calculado");
    expect(t.split("Não dá para saber quanto durou cada leitura").length - 1).toBe(1);
  });

  it("publica a janela EFETIVA quando o número vem de coleta", async () => {
    montar();
    await screen.findByText("Tempo de leitura");
    expect(texto()).toContain("mais largo que o período pedido");
  });

  it("avisa quando a janela começa antes do histórico registrado", async () => {
    const dados = relatorioFake();
    (dados.elefante as Record<string, unknown>).primeiro_evento_da_escola =
      "2026-09-15T10:00:00";
    montar(dados);
    await screen.findByText("Tempo de leitura");
    expect(texto()).toContain("falta de registro");
  });

  it("lista o aluno sem atividade em vez de escondê-lo", async () => {
    montar();
    expect(await screen.findByText("Joao Pedro Barbosa")).toBeTruthy();
    expect(texto()).toContain("30 alunos ativos no recorte");
  });

  it("celular: indicadores 2 por linha, data do período em linha própria e Questões que quebra na barra", async () => {
    const dados = relatorioFake();
    Object.assign(dados.elefante as Record<string, unknown>, { questoes_tentativas: 2345, questoes_acertos: 1234 });
    montar(dados);
    await screen.findByText("Tempo de leitura");

    // Os 4 + 4 cartões de indicador: duas colunas já no celular (eram uma só).
    const grade = (screen.getByText("Tempo de leitura").closest(".card") as HTMLElement).parentElement as HTMLElement;
    expect(grade).toHaveClass("grid", "grid-cols-2", "xl:grid-cols-4");
    expect(grade).not.toHaveClass("grid-cols-1");
    // "1.234/2.345" pode quebrar depois da barra no cartão estreito (espaço de largura zero).
    expect(textoDaSecao("Elefante Letrado")).toContain("1.234/\u200B2.345");

    // A data do período desce para a linha própria no celular, sem o "·" na frente.
    const ponto = screen.getByText((_, el) => el?.tagName === "SPAN" && el.textContent === "· ");
    expect(ponto).toHaveClass("max-sm:hidden");
    expect(ponto.parentElement).toHaveClass("max-sm:basis-full");
    expect(ponto.parentElement).toHaveTextContent("· 01/09/2026 a 30/09/2026");
  });

  it("o botão de PDF pede o MESMO recorte que a tela está mostrando", async () => {
    montar();
    await screen.findByText("Tempo de leitura");
    await userEvent.click(screen.getByRole("button", { name: /Gerar PDF/ }));
    expect(apiDownload).toHaveBeenCalledTimes(1);
    const pedido = (apiDownload as unknown as { mock: { calls: string[][] } })
      .mock.calls[0][0];
    // mesma rota, mesmo recorte — só o formato muda
    expect(pedido).toContain("/escolas/1/relatorios/periodo.pdf?");
    expect(pedido).toContain("periodo=mes_anterior");
    expect(pedido).toContain("plataformas=elefante");
    expect(pedido).toContain("plataformas=matific");
    expect(pedido).toContain("escopo=escola");
  });

  it("mostra o erro do PDF sem apagar o relatório da tela", async () => {
    montar();
    await screen.findByText("Tempo de leitura");
    (apiDownload as unknown as { mockRejectedValueOnce: (e: unknown) => void })
      .mockRejectedValueOnce(new ApiError(500, "Falha ao montar o documento."));
    await userEvent.click(screen.getByRole("button", { name: /Gerar PDF/ }));
    expect(await screen.findByText("Falha ao montar o documento.")).toBeTruthy();
    // os números continuam na tela: o erro é do download, não da consulta
    expect(texto()).toContain("Livros com atividade");
  });

  it("não deixa clicar duas vezes enquanto gera", async () => {
    montar();
    await screen.findByText("Tempo de leitura");
    let liberar: (() => void) | undefined;
    (apiDownload as unknown as { mockImplementationOnce: (f: () => Promise<void>) => void })
      .mockImplementationOnce(() => new Promise<void>((r) => { liberar = r; }));
    const botao = screen.getByRole("button", { name: /Gerar PDF/ });
    await userEvent.click(botao);
    expect(await screen.findByRole("button", { name: /Gerando PDF/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: /Gerando PDF/ })).toHaveProperty(
      "disabled", true);
    liberar?.();
  });

  it("não oferece PDF de um recorte que a tela ainda não tem", async () => {
    responder("GET", /\/escolas\/1\/turmas/, []);
    responder("GET", /\/escolas\/1\/alunos/, { itens: [], total: 0 });
    renderComApp(<RelatorioPeriodo />, {
      rota: "/relatorios/periodo",
      usuario: usuarioFake(),
      escolas: [escolaFake({ id: 1 })],
      escolaSelecionada: 1,
      periodo: { preset: "personalizado" },
    });
    const botao = await screen.findByRole("button", { name: /Gerar PDF/ });
    expect(botao).toHaveProperty("disabled", true);
  });

  it("falha ao montar o relatório: diz o motivo e deixa tentar de novo", async () => {
    responder("GET", /\/escolas\/1\/turmas/, []);
    responder("GET", /\/escolas\/1\/alunos/, { itens: [], total: 0 });
    responderErro("GET", /\/escolas\/1\/relatorios\/periodo/, 500, "Falha no servidor.");
    renderComApp(<RelatorioPeriodo />, {
      rota: "/relatorios/periodo",
      usuario: usuarioFake(),
      escolas: [escolaFake({ id: 1 })],
      escolaSelecionada: 1,
      periodo: { preset: "mes_anterior" },
    });
    expect(await screen.findByText("Não foi possível montar o relatório")).toBeInTheDocument();
    expect(screen.getByText("Falha no servidor.")).toBeInTheDocument();
    responder("GET", /\/escolas\/1\/relatorios\/periodo/, relatorioFake());
    await userEvent.click(screen.getByRole("button", { name: "Tentar de novo" }));
    expect(await screen.findByText("Tempo de leitura")).toBeInTheDocument();
  });

  it("não consulta o backend em personalizado sem as duas datas", async () => {
    responder("GET", /\/escolas\/1\/turmas/, []);
    responder("GET", /\/escolas\/1\/alunos/, { itens: [], total: 0 });
    renderComApp(<RelatorioPeriodo />, {
      rota: "/relatorios/periodo",
      usuario: usuarioFake(),
      escolas: [escolaFake({ id: 1 })],
      escolaSelecionada: 1,
      periodo: { preset: "personalizado" },
    });
    // Sem handler para /relatorios/periodo: se a tela consultasse, o mock
    // lançaria 404 e a mensagem de erro apareceria.
    expect(await screen.findByText(/Escolha a data inicial e a final/)).toBeTruthy();
  });
});

// ---------------------------------------------------------------------------
// Período PEDIDO × cobertura das COLETAS (caso real: escola 17, set/2026)
// ---------------------------------------------------------------------------
// A primeira coleta do Elefante foi em 22/09 16:53 UTC (13:53 em Brasília) e
// a última de setembro em 30/09 10:58 UTC (07:58). A tela dizia "a conta vai de
// 22/09 a 30/09 ... pode ser mais largo que o período pedido" — era mais
// ESTREITO, e o número saía como se fosse o mês inteiro.
const COBERTURA_BASE = {
  regra: "diferenca_de_coletas", em_andamento: false,
  periodo_inicio: "2026-09-01", periodo_fim: "2026-09-30", periodo_fim_efetivo: "2026-09-30",
  coleta_inicio: "2026-09-22T16:53:12", coleta_inicio_mais_tardio: "2026-09-22T16:53:12",
  coleta_fim: "2026-09-30T10:58:22", coleta_fim_mais_cedo: "2026-09-30T10:58:22",
  inicio_coberto: false, fim_coberto: false, inclui_antes_do_inicio: false,
  inicio_do_contador_anual: false, antecedencia_max_horas: null,
  status: "parcial", completa: false,
  alunos_cobertura_completa: 0, alunos_cobertura_parcial: 1, alunos_sem_inicio: 1,
  alunos_sem_fim: 1, alunos_ampliados: 0, alunos_sem_intervalo: 0,
};
const MARCA_ANTIGA = "MARCA_DO_AVISO_ANTIGO";

describe("legenda: o acumulado que a primeira coleta trouxe", () => {
  it("mostra quantas questões a primeira coleta já trazia, sem data", async () => {
    montar(comCoberturaDeQuestoes({ ...COBERTURA_BASE, acumulado_na_primeira_coleta: 25307 }));
    await screen.findByText("Tempo de leitura");
    expect(texto()).toContain("a primeira coleta já trazia 25.307 questões acumuladas, de datas que o contador não informa");
  });
});

function comCoberturaDeQuestoes(cobertura: Record<string, unknown>,
                                valores: { t: number | null; a: number | null } = { t: 30, a: 21 }) {
  const dados = relatorioFake();
  Object.assign(dados.elefante as Record<string, unknown>, {
    questoes_tentativas: valores.t, questoes_acertos: valores.a, alunos_sem_retrato: 0,
    janela_efetiva_questoes: {
      data_base_mais_antiga: "2026-09-22T16:53:12", data_base_mais_recente: "2026-09-22T16:53:12",
      data_atual_mais_antiga: "2026-09-30T10:58:22", data_atual_mais_recente: "2026-09-30T10:58:22",
      observacao: MARCA_ANTIGA,
    },
    cobertura_questoes: cobertura,
  });
  return dados;
}

/** Só o texto de UMA seção (o Matific também tem um cartão "Questões"). */
function textoDaSecao(titulo: string): string {
  const secao = screen.getByRole("heading", { name: titulo }).closest("section");
  return (secao?.textContent ?? "").replace(/\s+/g, " ");
}

describe("Questões: período pedido × cobertura das coletas", () => {
  it("cobertura parcial: diz que o valor NÃO é o período e mostra o pedido e o disponível", async () => {
    montar(comCoberturaDeQuestoes(COBERTURA_BASE));
    await screen.findByText("Tempo de leitura");
    const t = texto();
    expect(t).toContain("Questões: cobertura parcial — o valor NÃO representa o período completo");
    expect(t).toContain("Período solicitado01/09/2026 a 30/09/2026");
    // instantes de coleta convertidos para Brasília; o período não é convertido
    expect(t).toContain("Intervalo medido pelas coletas22/09/2026, 13:53 a 30/09/2026, 07:58");
    // não afirma que o histórico "não existe": só que não sai das coletas
    expect(t).not.toContain("não é recuperável");
    expect(t).toContain("O Elefante guarda o histórico datado por aluno (Questões Respondidas)");
    expect(t).toContain("o que foi feito de 01/09/2026 até a primeira coleta (até 22/09/2026, 13:53)");
    expect(t).toContain("A última coleta é de 30/09/2026, 07:58: o que veio depois, até 30/09/2026, não está na conta.");
    expect(textoDaSecao("Elefante Letrado")).toContain("cobertura parcial do período — veja o aviso");
    // o aviso antigo ("a conta vai de ...") não aparece junto
    expect(t).not.toContain("Questões: a conta vai de");
    expect(t).not.toContain(MARCA_ANTIGA);
  });

  it("cobertura completa: o período solicitado é o que se comunica", async () => {
    montar(comCoberturaDeQuestoes({
      ...COBERTURA_BASE, coleta_inicio: "2026-09-01T03:10:00", coleta_inicio_mais_tardio: null,
      coleta_fim: "2026-10-01T03:10:00", coleta_fim_mais_cedo: "2026-10-01T03:10:00",
      inicio_coberto: true, fim_coberto: true, status: "completa", completa: true,
      alunos_cobertura_completa: 1, alunos_cobertura_parcial: 0, alunos_sem_inicio: 0, alunos_sem_fim: 0,
    }, { t: 340, a: 250 }));
    await screen.findByText("Tempo de leitura");
    const t = texto();
    expect(t).toContain("Questões: período solicitado 01/09/2026 a 30/09/2026, medido pelas coletas de 01/09/2026, 00:10 a 01/10/2026, 00:10.");
    expect(t).not.toContain("cobertura parcial");
    expect(t).not.toContain("INCLUI");
  });

  it("sem coleta-base: 'desde o início do contador', nunca 'coletas de o início'", async () => {
    montar(comCoberturaDeQuestoes({
      ...COBERTURA_BASE, coleta_inicio: null, coleta_inicio_mais_tardio: null,
      coleta_fim: "2026-10-01T03:10:00", coleta_fim_mais_cedo: "2026-10-01T03:10:00",
      inicio_coberto: true, fim_coberto: true, status: "completa", completa: true,
      alunos_cobertura_completa: 1, alunos_cobertura_parcial: 0, alunos_sem_inicio: 0, alunos_sem_fim: 0,
    }, { t: 340, a: 250 }));
    await screen.findByText("Tempo de leitura");
    const t = texto();
    expect(t).toContain("medido pelas coletas desde o início do contador até 01/10/2026, 00:10.");
    expect(t).not.toMatch(/\bde o início/);
  });

  it("ampliada: a base é bem anterior ao início e o valor INCLUI esse intervalo", async () => {
    montar(comCoberturaDeQuestoes({
      ...COBERTURA_BASE, coleta_inicio: "2026-08-15T12:00:00", coleta_inicio_mais_tardio: null,
      coleta_fim: "2026-10-01T03:10:00", coleta_fim_mais_cedo: "2026-10-01T03:10:00",
      inicio_coberto: true, fim_coberto: true, inclui_antes_do_inicio: true, antecedencia_max_horas: 399,
      status: "ampliada", alunos_cobertura_parcial: 0, alunos_sem_inicio: 0, alunos_sem_fim: 0,
      alunos_ampliados: 1,
    }, { t: 40, a: 30 }));
    await screen.findByText("Tempo de leitura");
    const t = texto();
    expect(t).toContain("Questões: o valor INCLUI atividade de antes do período — não é só o período pedido.");
    expect(t).toContain("a coleta-base é de 15/08/2026, 09:00, 16 dias antes de 01/09/2026 — o número INCLUI a atividade desse intervalo.");
    expect(textoDaSecao("Elefante Letrado")).toContain("inclui antes do período — veja o aviso");
  });

  it("sem intervalo medido: '—' e o motivo, nunca 0/0", async () => {
    montar(comCoberturaDeQuestoes({
      ...COBERTURA_BASE, coleta_inicio: null, coleta_inicio_mais_tardio: null, coleta_fim: null,
      coleta_fim_mais_cedo: null, status: "sem_intervalo", alunos_cobertura_parcial: 0,
      alunos_sem_inicio: 0, alunos_sem_fim: 0, alunos_sem_intervalo: 4,
    }, { t: null, a: null }));
    await screen.findByText("Tempo de leitura");
    expect(texto()).toContain("Questões: sem número para 01/09/2026 a 30/09/2026.");
    const ele = textoDaSecao("Elefante Letrado");
    expect(ele).toContain("Questões—");
    expect(ele).not.toMatch(/Questões\s*0/);
  });

  it("mistura: cada causa diz para quantos alunos vale", async () => {
    montar(comCoberturaDeQuestoes({
      ...COBERTURA_BASE, coleta_inicio: "2026-09-01T03:10:00",
      coleta_fim: "2026-10-01T03:10:00", coleta_fim_mais_cedo: "2026-09-17T03:10:00",
      alunos_cobertura_completa: 1, alunos_cobertura_parcial: 2, alunos_sem_inicio: 1, alunos_sem_fim: 1,
    }));
    await screen.findByText("Tempo de leitura");
    const t = texto();
    expect(t).toContain("Sem coleta no início do período para 1 aluno(s)");
    expect(t).toContain("A última coleta para 1 aluno(s) é de 17/09/2026, 00:10");
  });

  it("período em andamento: diz até quando vão os dados", async () => {
    montar(comCoberturaDeQuestoes({
      ...COBERTURA_BASE, periodo_inicio: "2026-10-01", periodo_fim: "2026-10-31",
      periodo_fim_efetivo: "2026-10-06", em_andamento: true,
      coleta_inicio: "2026-10-01T03:10:00", coleta_inicio_mais_tardio: null,
      coleta_fim: "2026-10-06T03:10:00", coleta_fim_mais_cedo: "2026-10-06T03:10:00",
      inicio_coberto: true, fim_coberto: true, status: "completa", completa: true,
      alunos_cobertura_completa: 1, alunos_cobertura_parcial: 0, alunos_sem_inicio: 0, alunos_sem_fim: 0,
    }, { t: 12, a: 10 }));
    await screen.findByText("Tempo de leitura");
    expect(texto()).toContain("período solicitado 01/10/2026 a 31/10/2026 (em andamento, até hoje 06/10/2026)");
    expect(texto()).toContain("Em andamento: os dados vão até a coleta de 06/10/2026, 00:10.");
  });

  it("Matific com coleta única: '—' nos cartões e o 0 oficial explicado", async () => {
    const dados = relatorioFake();
    Object.assign(dados.matific as Record<string, unknown>, {
      atividades: 0, estrelas: 0,
      cobertura: {
        ...COBERTURA_BASE, regra: "oficial_matific", coleta_inicio: null, coleta_inicio_mais_tardio: null,
        coleta_fim: null, coleta_fim_mais_cedo: null, status: "sem_intervalo",
        alunos_cobertura_parcial: 0, alunos_sem_inicio: 0, alunos_sem_fim: 0, alunos_sem_intervalo: 3,
      },
    });
    montar(dados);
    await screen.findByText("Tempo de leitura");
    const tm = textoDaSecao("Matific");
    expect(tm).toContain("Atividades—sem intervalo medido — veja o aviso");
    expect(tm).toContain("O 0 da regra oficial (a mesma das premiações)");
    expect(tm).toContain("NÃO quer dizer que não houve atividade");
  });

  it("Matific nunca se declara completo: explica a regra oficial", async () => {
    const dados = relatorioFake();
    Object.assign(dados.matific as Record<string, unknown>, {
      cobertura: {
        ...COBERTURA_BASE, regra: "oficial_matific", coleta_inicio: "2026-08-31T03:10:00",
        coleta_inicio_mais_tardio: null, coleta_fim: "2026-09-30T03:10:00",
        inicio_coberto: true, fim_coberto: true, status: "regra_oficial",
        alunos_cobertura_parcial: 0, alunos_sem_inicio: 0, alunos_sem_fim: 0,
      },
    });
    montar(dados);
    await screen.findByText("Tempo de leitura");
    const t = texto();
    expect(t).toContain("O número segue a regra oficial do Matific (a mesma das premiações)");
    expect(t).not.toContain("Matific: a conta vai de");
  });

  it("dia 1º: a única coleta é a que mede o início — não 'nenhuma antes'", async () => {
    montar(comCoberturaDeQuestoes({
      ...COBERTURA_BASE, periodo_inicio: "2026-10-01", periodo_fim: "2026-10-31",
      periodo_fim_efetivo: "2026-10-01", em_andamento: true, coleta_inicio: null,
      coleta_inicio_mais_tardio: null, coleta_fim: null, coleta_fim_mais_cedo: null,
      status: "sem_intervalo", alunos_cobertura_parcial: 0, alunos_sem_inicio: 0, alunos_sem_fim: 0,
      alunos_sem_intervalo: 2, alunos_sem_intervalo_so_inicio: 2, alunos_medidos: 0,
    }, { t: null, a: null }));
    await screen.findByText("Tempo de leitura");
    const t = texto();
    expect(t).toContain("A única coleta do período é a que mede o início; a próxima medirá o que veio depois");
    expect(t).not.toContain("e nenhuma antes");
  });

  it("contador que diminui e lacuna no período são ditos", async () => {
    montar(comCoberturaDeQuestoes({
      ...COBERTURA_BASE, coleta_inicio: "2026-09-01T03:10:00", coleta_inicio_mais_tardio: null,
      coleta_fim: "2026-10-01T03:10:00", coleta_fim_mais_cedo: "2026-10-01T03:10:00",
      inicio_coberto: true, fim_coberto: true, alunos_cobertura_completa: 1, alunos_cobertura_parcial: 0,
      alunos_sem_inicio: 0, alunos_sem_fim: 0, alunos_medidos: 1,
      alunos_contador_regrediu: 1, alunos_sem_coleta_no_periodo: 2,
    }));
    await screen.findByText("Tempo de leitura");
    const t = texto();
    expect(t).toContain("1 aluno(s) com o contador da plataforma DIMINUINDO no período");
    expect(t).toContain("2 aluno(s) coletados antes e depois do período, mas sem nenhuma coleta dentro dele");
  });

  it("coleta interrompida e turma sem coleta são ditas (o número é parcial)", async () => {
    montar(comCoberturaDeQuestoes({
      ...COBERTURA_BASE, coleta_inicio: "2026-09-01T03:10:00", coleta_inicio_mais_tardio: null,
      coleta_fim: "2026-10-01T03:10:00", coleta_fim_mais_cedo: "2026-10-01T03:10:00",
      inicio_coberto: true, fim_coberto: true, alunos_cobertura_completa: 3, alunos_cobertura_parcial: 0,
      alunos_sem_inicio: 0, alunos_sem_fim: 0, alunos_medidos: 3,
      alunos_coleta_interrompida: 2,
      turmas_sem_coleta: [{ turma_id: 9, turma: "4º Ano B", alunos: 2 }],
    }));
    await screen.findByText("Tempo de leitura");
    const t = texto();
    expect(t).toContain("cobertura parcial — o valor NÃO representa o período completo");
    expect(t).toContain("2 aluno(s) coletados antes do período e sem nenhuma coleta que entre na conta");
    expect(t).toContain("Turma(s) sem nenhuma coleta no período, fora da conta: 4º Ano B.");
  });

  it("questões que não vieram da plataforma (S9) são ditas como causa da cobertura parcial", async () => {
    montar(comCoberturaDeQuestoes({
      ...COBERTURA_BASE, coleta_inicio: "2026-09-01T03:10:00", coleta_inicio_mais_tardio: null,
      coleta_fim: "2026-09-20T03:10:00", coleta_fim_mais_cedo: "2026-09-20T03:10:00",
      inicio_coberto: true, alunos_cobertura_completa: 0, alunos_cobertura_parcial: 1,
      alunos_sem_inicio: 0, alunos_sem_fim: 1, alunos_medidos: 1, alunos_questoes_nao_vieram: 2,
    }));
    await screen.findByText("Tempo de leitura");
    const t = texto();
    expect(t).toContain("cobertura parcial — o valor NÃO representa o período completo");
    expect(t).toContain("2 aluno(s) com coleta no período em que a plataforma não mandou as questões");
    // O aviso novo também na língua de quem lê o relatório (D5), com o "Como ler" aberto.
    await userEvent.setup().click(await screen.findByText("Como ler estes números"));
    semVocabularioInterno(texto());
  });

  it("sem número porque as questões não vieram: o motivo é esse, não 'uma coleta só'", async () => {
    montar(comCoberturaDeQuestoes({
      ...COBERTURA_BASE, coleta_inicio: null, coleta_inicio_mais_tardio: null, coleta_fim: null,
      coleta_fim_mais_cedo: null, status: "sem_intervalo", alunos_cobertura_parcial: 0,
      alunos_sem_inicio: 0, alunos_sem_fim: 0, alunos_sem_intervalo: 0, alunos_medidos: 0,
      alunos_questoes_nao_vieram: 2,
    }, { t: null, a: null }));
    await screen.findByText("Tempo de leitura");
    const t = texto();
    expect(t).toContain("Questões: sem número para 01/09/2026 a 30/09/2026.");
    expect(t).toContain("A plataforma não mandou as questões nas coletas do período");
    expect(t).not.toContain("Há uma única coleta por aluno no período");
    expect(textoDaSecao("Elefante Letrado")).toContain("Questões—");
    await userEvent.setup().click(await screen.findByText("Como ler estes números"));
    semVocabularioInterno(texto());
  });

  it("Matific: 'para N aluno(s)' usa os alunos medidos, não só os parciais", async () => {
    const dados = relatorioFake();
    Object.assign(dados.matific as Record<string, unknown>, {
      cobertura: {
        ...COBERTURA_BASE, regra: "oficial_matific", coleta_inicio: "2026-08-31T03:10:00",
        coleta_inicio_mais_tardio: "2026-09-22T16:00:00", coleta_fim: "2026-09-30T03:10:00",
        fim_coberto: true, alunos_cobertura_parcial: 2, alunos_sem_inicio: 2, alunos_sem_fim: 0,
        alunos_medidos: 302,
      },
    });
    montar(dados);
    await screen.findByText("Tempo de leitura");
    expect(textoDaSecao("Matific")).toContain("Sem coleta no início do período para 2 aluno(s)");
  });

  it("o cartão do período mostra as datas pedidas, sem deslocar o dia", async () => {
    montar();
    await screen.findByText("Tempo de leitura");
    expect(texto()).toContain("setembro de 2026· 01/09/2026 a 30/09/2026");
  });
  it("as tabelas mantêm as colunas do Matific, e a turma do aluno vai sob o nome", async () => {
    montar();
    await screen.findByText("Joao Pedro Barbosa");
    const [porTurma, porAluno] = screen.getAllByRole("table");
    const colunas = (tabela: HTMLElement) =>
      within(tabela).getAllByRole("columnheader").map((th) => th.textContent);
    expect(colunas(porTurma)).toEqual([
      "Turma", "Alunos", "Com atividade", "Livros novos", "Tempo", "Relidos", "Atividades", "Estrelas",
    ]);
    // A turma saiu da coluna própria para o chip sob o nome: uma coluna a menos é o que
    // deixa Atividades e Estrelas caberem inteiras a partir de 768 px.
    expect(colunas(porAluno)).toEqual([
      "Aluno", "Livros novos", "Tempo", "Com atividade", "Relidos", "Atividades", "Estrelas",
    ]);
    const linhaAna = within(porAluno).getByText("Ana Beatriz Souza").closest("tr")!;
    expect(within(linhaAna).getByText("3º Ano A")).toBeInTheDocument();
    expect(within(linhaAna).getAllByRole("cell").map((td) => td.textContent).slice(1))
      .toEqual(["3", "21 min", "5", "2", "10", "4"]);
    // O aluno sem atividade continua com a turma E o aviso, na mesma célula do nome.
    const linhaJoao = within(porAluno).getByText("Joao Pedro Barbosa").closest("tr")!;
    expect(within(linhaJoao).getByText("3º Ano A")).toBeInTheDocument();
    expect(within(linhaJoao).getByText("sem atividade no período")).toBeInTheDocument();
  });

  it("os quatro filtros continuam selects nativos com o rótulo de sempre", async () => {
    montar();
    await screen.findByText("Tempo de leitura");
    expect(screen.getByLabelText("Período de análise").tagName).toBe("SELECT");
    for (const rotulo of ["Plataforma", "Turma", "Aluno"]) {
      expect(screen.getByLabelText(rotulo).tagName).toBe("SELECT");
    }
    await userEvent.selectOptions(screen.getByLabelText("Plataforma"), "matific");
    expect((screen.getByLabelText("Plataforma") as HTMLSelectElement).value).toBe("matific");
  });
});
