/**
 * Relatório por Período, aviso "Sem coleta no início do período": cada plataforma com
 * o SEU contador (achados RELATORIOS-7 e REVERIFICACAO-3).
 *
 * O contador das questões do Elefante é vitalício ("acumulado desde o início da conta");
 * o do Matific é do ANO e conta atividades e estrelas — a própria tela diz isso em
 * "Como ler": "O Matific informa o total do ano". O aviso do Matific repetia a frase do
 * Elefante, com "início da conta" e "questão". Parte da resposta REAL do backend
 * (fixtures/relatorio_periodo), com a cobertura trocada por uma primeira coleta no meio
 * de setembro. Dados INVENTADOS.
 */
import { describe, expect, it } from "vitest";

import RelatorioPeriodo from "../pages/RelatorioPeriodo";
import relatorioReal from "./fixtures/relatorio_periodo/setembro_inicio_sem_questoes.json";
import { escolaFake, renderComApp, responder, screen, usuarioFake } from "./utils";

function semColetaNoInicio(regra: "diferenca_de_coletas" | "oficial_matific") {
  return {
    regra, em_andamento: false,
    periodo_inicio: "2026-09-01", periodo_fim: "2026-09-30", periodo_fim_efetivo: "2026-09-30",
    coleta_inicio: "2026-09-15T12:00:00", coleta_inicio_mais_tardio: "2026-09-15T12:00:00",
    coleta_fim: "2026-09-29T12:00:00", coleta_fim_mais_cedo: "2026-09-29T12:00:00",
    inicio_coberto: false, fim_coberto: true, inclui_antes_do_inicio: false,
    inicio_do_contador_anual: false, antecedencia_max_horas: null,
    status: "parcial", completa: false,
    alunos_cobertura_completa: 0, alunos_cobertura_parcial: 1, alunos_sem_inicio: 1,
    alunos_sem_fim: 0, alunos_ampliados: 0, alunos_sem_intervalo: 0, alunos_medidos: 1,
  };
}

function montar() {
  const dados = structuredClone(relatorioReal) as unknown as {
    elefante: Record<string, unknown>; matific: Record<string, unknown>;
  };
  dados.elefante.cobertura_questoes = semColetaNoInicio("diferenca_de_coletas");
  dados.matific.cobertura = semColetaNoInicio("oficial_matific");
  responder("GET", /\/escolas\/1\/turmas/, []);
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

function textoDaSecao(titulo: string): string {
  const secao = screen.getByRole("heading", { name: titulo }).closest("section");
  return (secao?.textContent ?? "").replace(/\s+/g, " ");
}

describe("aviso 'Sem coleta no início do período' por plataforma", () => {
  it("Matific: fala do total do ano e de atividades, não de 'início da conta' nem de questões", async () => {
    montar();
    await screen.findByText("Tempo de leitura");
    const tm = textoDaSecao("Matific");
    expect(tm).toContain("Sem coleta no início do período: o que foi feito de 01/09/2026 até a primeira coleta");
    expect(tm).toContain(
      "o contador do Matific é o total do ano (atividades e estrelas) e não diz quando cada atividade foi feita, "
      + "então esse trecho não sai das coletas");
    expect(tm).not.toMatch(/início da conta|questão/);
  });

  it("Elefante: o aviso das questões continua com o contador vitalício", async () => {
    montar();
    await screen.findByText("Tempo de leitura");
    const te = textoDaSecao("Elefante Letrado");
    expect(te).toContain(
      "o contador que o Constela coleta é acumulado desde o início da conta e não diz quando cada questão foi "
      + "respondida, então esse trecho não sai das coletas");
    expect(te).toContain("O Elefante guarda o histórico datado por aluno (Questões Respondidas)");
  });
});
