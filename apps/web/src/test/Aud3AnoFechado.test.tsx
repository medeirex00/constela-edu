/**
 * S_G_VIRADA-2 — período de um ano letivo ENCERRADO, consultado depois da virada.
 *
 * A cerimônia de 2026 feita em fevereiro de 2027: o backend monta os pódios, o Ranking
 * de Leitura por período e o Relatório por Período com as crianças e as turmas de 2026
 * e diz isso (`populacao`; nas linhas do ranking, `ano_letivo` + `populacao`). As telas
 * avisam — antes a lista saía com as turmas de 2027, calada. Também avisam quando o
 * período passa por dois anos letivos (valem as crianças de agora). No caso de sempre,
 * nada muda. Dados fictícios.
 */
import { describe, expect, it } from "vitest";

import Premiacoes from "../pages/Premiacoes";
import RankingLeitura from "../pages/RankingLeitura";
import RelatorioPeriodo from "../pages/RelatorioPeriodo";
import relatorioReal from "./fixtures/relatorio_periodo/setembro_inicio_sem_questoes.json";
import { escolaFake, renderComApp, responder, screen, turmaFake, usuarioFake } from "./utils";

const texto = () => (document.body.textContent ?? "").replace(/\s+/g, " ").trim();

const DO_ANO_FECHADO = { ano_letivo: 2026, origem: "ano_do_periodo", ano_letivo_ativo: 2027 };
const ATRAVESSA = { ano_letivo: 2027, origem: "atravessa_anos", ano_letivo_ativo: 2027 };
const DE_SEMPRE = { ano_letivo: 2027, origem: "ano_ativo", ano_letivo_ativo: 2027 };

const AVISO_ANO_FECHADO = "Período do ano letivo de 2026, que já terminou: entram as crianças "
  + "matriculadas em 2026, com a turma e a série daquele ano.";
// A professora vê só as crianças que estão HOJE nas turmas dela (REV3-PERIODO-2): a tela
// diz isso, como o Relatório por Período já dizia.
const AVISO_SUAS_TURMAS = "Suas turmas são as de agora: aparecem as crianças delas, com a turma "
  + "que tinham em 2026.";
const PROFESSORA = usuarioFake({ cargo: "professor", nome: "Professora Ficticia" });
const AVISO_ATRAVESSA = "O período passa por mais de um ano letivo: entram as crianças matriculadas "
  + "em 2027, o ano letivo atual da escola, com a turma de agora. Quem não tem matrícula em 2027 "
  + "não aparece.";

// ---------------------------------------------------------------------------
// Premiações
// ---------------------------------------------------------------------------
function premiacoes(populacao: Record<string, unknown>) {
  return {
    periodo: { chave: "personalizado", rotulo: "01/10/2026 a 15/12/2026",
               inicio: "2026-10-01T00:00:00", fim: "2026-12-15T23:59:59.999999" },
    categorias: [{
      chave: "mais_livros", titulo: "Mais Livros Lidos", icone: "📚", descricao: "d",
      unidade: "livros",
      podio: [{ posicao: 1, aluno_id: 3, nome: "Dora Ficticia Melo", turma: "5º Ano A", valor: 4 }],
    }],
    turnos: [],
    populacao,
  };
}

function montarPremiacoes(populacao: Record<string, unknown>, usuario?: ReturnType<typeof usuarioFake>) {
  responder("GET", "/escolas/1/turmas", [turmaFake({ id: 1, nome: "5º Ano A", turno: "manha" })]);
  responder("GET", "/escolas/1/premiacoes", premiacoes(populacao));
  responder("GET", "/escolas/1/ranking-evolucao", []);
  renderComApp(<Premiacoes />, { usuario });
}

describe("Premiações de um período de ano letivo encerrado", () => {
  it("avisa que as crianças e as turmas são as daquele ano", async () => {
    montarPremiacoes(DO_ANO_FECHADO);
    expect(await screen.findByText("Dora Ficticia Melo")).toBeInTheDocument();
    expect(texto()).toContain(AVISO_ANO_FECHADO);
    // A coordenação vê a escola inteira: nada de "suas turmas".
    expect(texto()).not.toContain("Suas turmas");
  });

  it("para a professora, diz também que as turmas dela são as de agora", async () => {
    montarPremiacoes(DO_ANO_FECHADO, PROFESSORA);
    expect(await screen.findByText("Dora Ficticia Melo")).toBeInTheDocument();
    expect(texto()).toContain(`${AVISO_ANO_FECHADO} ${AVISO_SUAS_TURMAS}`);
  });

  it("período que passa por dois anos: avisa que valem as crianças de agora", async () => {
    montarPremiacoes(ATRAVESSA);
    expect(await screen.findByText("Dora Ficticia Melo")).toBeInTheDocument();
    expect(texto()).toContain(AVISO_ATRAVESSA);
  });

  it("no ano letivo de agora, nenhum aviso", async () => {
    montarPremiacoes(DE_SEMPRE);
    expect(await screen.findByText("Dora Ficticia Melo")).toBeInTheDocument();
    expect(texto()).not.toContain("que já terminou");
    expect(texto()).not.toContain("mais de um ano letivo");
  });
});

// ---------------------------------------------------------------------------
// Ranking de Leitura por período
// ---------------------------------------------------------------------------
function leitores(ano_letivo: number, populacao: string) {
  return [
    { posicao: 1, aluno_id: 3, nome: "Dora Ficticia Melo", turma: "5º Ano A", ano_escolar: "5º Ano",
      livros: 4, pontos: 16, tempo_leitura_min: 120, ano_letivo, populacao },
    { posicao: 2, aluno_id: 1, nome: "Ana Clara Ficticia Souza", turma: "4º Ano A",
      ano_escolar: "4º Ano", livros: 2, pontos: 8, tempo_leitura_min: 60, ano_letivo, populacao },
  ];
}

function montarRanking(itens: unknown[], usuario?: ReturnType<typeof usuarioFake>) {
  responder("GET", "/escolas/1/turmas", [turmaFake({ id: 1, nome: "5º Ano A", turno: "manha" })]);
  responder("GET", "/escolas/1/ranking/leitura", itens);
  renderComApp(<RankingLeitura />, { rota: "/ranking-leitura", usuario });
}

describe("Ranking de Leitura de um período de ano letivo encerrado", () => {
  it("avisa que as crianças e as turmas da lista são as daquele ano", async () => {
    montarRanking(leitores(2026, "ano_do_periodo"));
    expect(await screen.findByRole("link", { name: /Dora Ficticia Melo/ })).toBeInTheDocument();
    expect(texto()).toContain(AVISO_ANO_FECHADO);
    expect(texto()).not.toContain("Suas turmas");
  });

  it("para a professora, diz também que as turmas dela são as de agora", async () => {
    montarRanking(leitores(2026, "ano_do_periodo"), PROFESSORA);
    expect(await screen.findByRole("link", { name: /Dora Ficticia Melo/ })).toBeInTheDocument();
    expect(texto()).toContain(`${AVISO_ANO_FECHADO} ${AVISO_SUAS_TURMAS}`);
  });

  it("período que passa por dois anos: avisa", async () => {
    montarRanking(leitores(2027, "atravessa_anos"));
    expect(await screen.findByRole("link", { name: /Dora Ficticia Melo/ })).toBeInTheDocument();
    expect(texto()).toContain(AVISO_ATRAVESSA);
  });

  it("no ano letivo de agora (ou resposta sem o campo), nenhum aviso", async () => {
    montarRanking(leitores(2027, "ano_ativo"));
    expect(await screen.findByRole("link", { name: /Dora Ficticia Melo/ })).toBeInTheDocument();
    expect(texto()).not.toContain("que já terminou");
    expect(texto()).not.toContain("mais de um ano letivo");
  });
});

// ---------------------------------------------------------------------------
// Relatório por Período
// ---------------------------------------------------------------------------
function montarRelatorio(dados: Record<string, unknown>) {
  responder("GET", /\/escolas\/1\/turmas/, []);
  responder("GET", /\/escolas\/1\/alunos/, { itens: [], total: 0 });
  responder("GET", /\/escolas\/1\/relatorios\/periodo/, dados);
  renderComApp(<RelatorioPeriodo />, {
    rota: "/relatorios/periodo",
    usuario: usuarioFake(),
    escolas: [escolaFake({ id: 1 })],
    escolaSelecionada: 1,
    periodo: { preset: "mes_anterior" },
  });
}

describe("Relatório por Período de um ano letivo encerrado", () => {
  const real = () => structuredClone(relatorioReal) as unknown as Record<string, unknown>;

  it("o cabeçalho diz o ano das crianças, não o ano ativo da escola, e avisa", async () => {
    const dados = { ...real(), escola: { id: 1, nome: "ESCOLA TESTE", ano_letivo: 2027 },
                    populacao: DO_ANO_FECHADO };
    montarRelatorio(dados);
    await screen.findByText("Tempo de leitura");
    expect(texto()).toContain("ESCOLA TESTE · ano letivo 2026");
    expect(texto()).not.toContain("ano letivo 2027");
    expect(texto()).toContain(AVISO_ANO_FECHADO);
  });

  it("com as turmas do professor, diz que elas são as de agora", async () => {
    const dados = { ...real(), escola: { id: 1, nome: "ESCOLA TESTE", ano_letivo: 2027 },
                    populacao: DO_ANO_FECHADO,
                    escopo: { tipo: "escola", turma_id: null, aluno_id: null, restrito_a_turmas: [7] } };
    montarRelatorio(dados);
    await screen.findByText("Tempo de leitura");
    expect(texto()).toContain("Suas turmas são as de agora: aparecem as crianças delas, com a turma "
      + "que tinham em 2026.");
  });

  it("a resposta real de um mês do ano de agora não ganha aviso", async () => {
    montarRelatorio(real());
    await screen.findByText("Tempo de leitura");
    expect(texto()).toContain("ESCOLA TESTE · ano letivo 2026");
    expect(texto()).not.toContain("que já terminou");
    expect(texto()).not.toContain("mais de um ano letivo");
  });
});
