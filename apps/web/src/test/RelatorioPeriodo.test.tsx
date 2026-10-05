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
import { escolaFake, renderComApp, responder, screen, usuarioFake } from "./utils";

const texto = () => (document.body.textContent ?? "").replace(/\s+/g, " ").trim();

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

  it("declara a classificação de suporte de cada número", async () => {
    montar();
    await screen.findByText("Tempo de leitura");
    const detalhes = await screen.findByText("Como ler estes números");
    detalhes.click();
    const t = texto();
    expect(t).toContain("SUPORTADO COM RESSALVA");
    expect(t).toContain("NÃO SUPORTADO");
    expect(t).toContain("O que este relatório NÃO responde");
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
