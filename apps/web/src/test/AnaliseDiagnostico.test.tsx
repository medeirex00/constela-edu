/**
 * Diagnóstico pedagógico (`?ver=diagnostico`) — hipótese EXPLORATÓRIA por escola:
 *  - a faixa fixa "Hipótese exploratória — calculada pelo Constela; não é causa e efeito" e a
 *    comparabilidade dos anos à vista;
 *  - os níveis em chips (filtram, não ordenam), as categorias de LP e MT por extenso;
 *  - sem ranking (ordem alfabética) e sem dispersão;
 *  - a linha expansível (botão com aria-expanded) com TODOS os sinais, cada um com o selo de
 *    natureza e a referência; o número protegido como "protegido";
 *  - critérios e limitações recolhidos; o CSV com a mesma tabela.
 *
 * Números e nomes INVENTADOS (D13).
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../lib/csvRanking", async (importOriginal) => {
  const original = await importOriginal<typeof import("../lib/csvRanking")>();
  return { ...original, baixarCsv: vi.fn() };
});

import { baixarCsv, conteudoCsv } from "../lib/csvRanking";
import AnaliseEducacional from "../pages/analise/AnaliseEducacional";
import { baseRede, diagnostico, secretaria } from "./AnaliseFixturesDiagnostico";
import { renderComApp, responder, responderErro, screen, userEvent, within } from "./utils";

function semear(diag = diagnostico()) {
  responder("GET", "/redes/1/analise/indicadores", baseRede());
  responder("GET", "/redes/1/analise/diagnostico", diag);
}

const ROTA = "/rede/analise?ver=diagnostico";

beforeEach(() => vi.mocked(baixarCsv).mockClear());

describe("Diagnóstico pedagógico — a hipótese à vista", () => {
  it("a faixa fixa da hipótese e a comparabilidade dos anos (exploratória)", async () => {
    semear();
    renderComApp(<AnaliseEducacional />, { rota: ROTA, usuario: secretaria });
    const faixa = await screen.findByTestId("faixa-hipotese");
    expect(faixa).toHaveTextContent("Hipótese exploratória — calculada pelo Constela; não é causa e efeito.");
    const comparabilidade = within(faixa).getByTestId("comparabilidade");
    expect(comparabilidade).toHaveTextContent("Resultados oficiais até 2025 e uso das plataformas no ano letivo de 2026");
    expect(comparabilidade).toHaveTextContent("leitura exploratória: não mede a mesma população nem o mesmo período");
    expect(screen.getByTestId("filtros-diagnostico")).toHaveTextContent("ano letivo de 2026");
    expect(screen.getByTestId("resumo-diagnostico")).toHaveTextContent("4 escola(s) · 3 com número oficial · 3 com plataforma");
  });

  it("no mesmo ano, a faixa conta as leituras do mesmo ano (associação, nunca causa) e as exploratórias", async () => {
    const padrao = diagnostico();
    const [primeira, ...resto] = padrao.escolas;
    const lp = { ...primeira.leituras.lp, anos: { avaliacao: 2026, plataforma: 2026 }, comparabilidade: "mesmo_ano" as const };
    semear(diagnostico({
      resumo: { ...padrao.resumo, anos: { avaliacao_mais_recente: 2026, plataforma: 2026 } },
      escolas: [{ ...primeira, leituras: { ...primeira.leituras, lp } }, ...resto],
    }));
    renderComApp(<AnaliseEducacional />, { rota: ROTA, usuario: secretaria });
    const faixa = await screen.findByTestId("comparabilidade");
    expect(faixa).toHaveTextContent("Em 1 leitura(s), avaliação oficial e plataformas são do mesmo ano letivo (2026)");
    expect(faixa).toHaveTextContent("ainda assim é associação");
    expect(faixa).toHaveTextContent("leitura exploratória");
  });

  it("a edição mais recente da rede ser do ano das plataformas NÃO basta: sem leitura do mesmo ano, é exploratória", async () => {
    const padrao = diagnostico();
    semear(diagnostico({ resumo: { ...padrao.resumo, anos: { avaliacao_mais_recente: 2026, plataforma: 2026 } } }));
    renderComApp(<AnaliseEducacional />, { rota: ROTA, usuario: secretaria });
    const faixa = await screen.findByTestId("comparabilidade");
    expect(faixa).toHaveTextContent("nenhuma leitura junta avaliação e plataformas do mesmo ano letivo");
    expect(faixa).not.toHaveTextContent("são do mesmo ano letivo");
  });

  it("sem ranking e sem dispersão: escolas em ordem alfabética, nenhum gráfico de pontos", async () => {
    semear();
    const { container } = renderComApp(<AnaliseEducacional />, { rota: ROTA, usuario: secretaria });
    const tabela = await screen.findByTestId("tabela-diagnostico");
    // A Beta é "prioritária", mas não vem primeiro: a ordem é a do nome.
    const nomes = within(tabela).getAllByRole("rowheader").map((r) => r.querySelector("span")?.textContent);
    expect(nomes).toEqual(["EMEF Sintética Alfa", "EMEF Sintética Beta", "EMEF Sintética Delta", "EMEI Sintética Gama"]);
    // Nenhum gráfico (os gráficos da análise são SVG role="img"; os ícones são decorativos).
    expect(container.querySelector('svg[role="img"]')).toBeNull();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(screen.queryByTestId("relacao-dispersao")).not.toBeInTheDocument();
  });
});

describe("Diagnóstico pedagógico — níveis e categorias", () => {
  it("os chips contam cada nível e filtram (sem reordenar)", async () => {
    semear();
    renderComApp(<AnaliseEducacional />, { rota: ROTA, usuario: secretaria });
    const chips = await screen.findByTestId("chips-nivel");
    expect(within(chips).getAllByRole("button").map((b) => b.textContent)).toEqual([
      "Todas (4)", "Prioritário (1)", "Acompanhar (1)", "Oportunidade (0)", "Dados insuficientes (1)", "Sem sinal (1)",
    ]);
    const todas = within(chips).getByRole("button", { name: "Todas (4)" });
    expect(todas).toHaveAttribute("aria-pressed", "true");
    const prioritario = within(chips).getByRole("button", { name: "Prioritário (1)" });
    await userEvent.click(prioritario);
    expect(prioritario).toHaveAttribute("aria-pressed", "true");
    expect(todas).toHaveAttribute("aria-pressed", "false");
    const tabela = screen.getByTestId("tabela-diagnostico");
    expect(within(tabela).getAllByRole("rowheader")).toHaveLength(1);
    expect(within(tabela).getByRole("rowheader")).toHaveTextContent("EMEF Sintética Beta");
    expect(screen.getByTestId("explica-nivel")).toHaveTextContent("Prioritário: avaliação e plataforma em atenção no mesmo componente");
    await userEvent.click(prioritario);                                       // de novo: volta a todas
    expect(within(tabela).getAllByRole("rowheader")).toHaveLength(4);
    await userEvent.click(within(chips).getByRole("button", { name: "Oportunidade (0)" }));
    expect(screen.getByTestId("diagnostico-vazio")).toHaveTextContent("Nenhuma escola neste nível.");
  });

  it("a matriz: o estado de cada eixo e a categoria de LP e MT, por extenso (com a base geral marcada)", async () => {
    semear();
    renderComApp(<AnaliseEducacional />, { rota: ROTA, usuario: secretaria });
    await screen.findByTestId("tabela-diagnostico");
    const [lp, mt, nivel] = within(screen.getByTestId("diagnostico-escola-2")).getAllByRole("cell");
    expect(lp).toHaveTextContent("Avaliação:Favorável");
    expect(lp).toHaveTextContent("Plataforma:Atenção");
    expect(lp).toHaveTextContent("Divergente: avaliação favorável, uso baixo");
    // MT veio na forma {estado, base: "geral"}: a avaliação foi lida pelo IEE/Ideb.
    expect(mt).toHaveTextContent("Avaliação:Atenção(pelos indicadores gerais: IEE/Ideb)");
    expect(mt).toHaveTextContent("Divergente: uso alto, avaliação em atenção");
    expect(nivel).toHaveTextContent("Acompanhar");
    const beta = within(screen.getByTestId("diagnostico-escola-3")).getAllByRole("cell");
    expect(beta[0]).toHaveTextContent("Convergente em atenção");
    expect(beta[1]).toHaveTextContent("Inconclusiva");
    expect(beta[2]).toHaveTextContent("Prioritário");
    // O resumo das categorias por componente (só as que têm escola).
    expect(screen.getByTestId("resumo-categorias")).toHaveTextContent("Leitura (LP): Convergente em atenção: 1");
  });
});

describe("Diagnóstico pedagógico — a linha que abre todos os sinais", () => {
  it("o botão tem aria-expanded/aria-controls e abre TODOS os sinais, com natureza e referência", async () => {
    semear();
    renderComApp(<AnaliseEducacional />, { rota: ROTA, usuario: secretaria });
    await screen.findByTestId("tabela-diagnostico");
    // O nome acessível começa pelo texto visível ("Ver sinais (4)") e diz de qual escola é.
    const botao = screen.getByRole("button", { name: "Ver sinais (4) — EMEF Sintética Alfa" });
    expect(botao).toHaveTextContent("Ver sinais (4)");
    expect(botao).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByTestId("detalhe-escola-2")).not.toBeInTheDocument();
    await userEvent.click(botao);
    expect(botao).toHaveAttribute("aria-expanded", "true");
    const detalhe = screen.getByTestId("detalhe-escola-2");
    expect(botao).toHaveAttribute("aria-controls", detalhe.id);
    const sinais = within(detalhe).getAllByTestId("sinal");
    expect(sinais).toHaveLength(4);
    // Cada sinal: o selo de natureza, a direção por extenso e a referência.
    expect(sinais.map((s) => s.querySelector("[data-natureza]")?.textContent)).toEqual([
      "Oficial", "Calculado pelo Constela", "Plataforma", "Dados",
    ]);
    // No sinal das plataformas, o número é delas e o "abaixo da rede" é critério do Constela.
    expect([...sinais[2].querySelectorAll("[data-natureza]")].map((s) => s.textContent))
      .toEqual(["Plataforma", "Calculado pelo Constela"]);
    expect(sinais[0]).toHaveTextContent("Atenção");
    expect(sinais[0]).toHaveTextContent("Referência: IEE 2025");
    expect(sinais[1]).toHaveTextContent("Favorável");
    expect(sinais[2]).toHaveTextContent("Referência: Elefante · 01/01/2026–31/12/2026");
    expect(sinais[3]).toHaveTextContent("Informativo");
    // A comparabilidade de cada leitura e os motivos do nível, rastreáveis até o número.
    expect(within(detalhe).getByTestId("comparabilidade-lp")).toHaveTextContent("Avaliação 2025 × plataformas 2026: leitura exploratória");
    expect(detalhe).toHaveTextContent("IEE 2025: meta oficial não atingida (IEE 2025)");
    expect(within(detalhe).getByTestId("oficiais-escola")).toHaveTextContent("SARESP · 5º ano · LP: 219,6 (2025) · rede 212,4 (+7,2)");
    expect(detalhe).toHaveTextContent("Elefante: 55% de participação · 2,1 livros novos/aluno");
    expect(detalhe.querySelector("[data-posicao=abaixo]")).toHaveTextContent("abaixo da rede");
    expect(botao).toHaveAccessibleName("Esconder sinais (4) — EMEF Sintética Alfa");
    await userEvent.click(botao);
    expect(botao).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByTestId("detalhe-escola-2")).not.toBeInTheDocument();
  });

  it("o número protegido aparece como 'protegido'; a pendência por extenso", async () => {
    semear();
    renderComApp(<AnaliseEducacional />, { rota: ROTA, usuario: secretaria });
    await userEvent.click(await screen.findByRole("button", { name: "Ver sinais (2) — EMEI Sintética Gama" }));
    const detalhe = screen.getByTestId("detalhe-escola-4");
    expect(detalhe).toHaveTextContent("Elefante: protegido — poucos alunos");
    expect(detalhe).toHaveTextContent("Pendências: sem código INEP no cadastro");
    expect(detalhe).toHaveTextContent("Nenhum número oficial desta escola.");
    expect(detalhe).not.toHaveTextContent(/\b0([,.]0+)?%/);
  });

  it("a escola do filtro já abre expandida", async () => {
    semear();
    renderComApp(<AnaliseEducacional />, { rota: `${ROTA}&escola=3`, usuario: secretaria });
    expect(await screen.findByTestId("detalhe-escola-3")).toBeInTheDocument();
    expect(screen.queryByTestId("detalhe-escola-2")).not.toBeInTheDocument();
  });
});

describe("Diagnóstico pedagógico — critérios, CSV e falha", () => {
  it("critérios, limitações e metodologia ficam recolhidos", async () => {
    semear();
    renderComApp(<AnaliseEducacional />, { rota: ROTA, usuario: secretaria });
    const criterios = await screen.findByTestId("criterios-diagnostico");
    const botao = within(criterios).getByRole("button", { name: /Critérios do diagnóstico/ });
    expect(botao).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(botao);
    expect(criterios).toHaveTextContent("Sem ranking: as escolas aparecem em ordem alfabética");
    expect(criterios).toHaveTextContent("participação 5 p.p.; intensidade 15% do valor da rede; Ideb 0,2");
    expect(criterios).toHaveTextContent("ao menos 3 escolas");
    expect(criterios).toHaveTextContent("Oportunidade: avaliação favorável com uso baixo da plataforma");
    expect(within(screen.getByTestId("limitacoes-diagnostico")).getByRole("button")).toHaveAttribute("aria-expanded", "false");
    expect(within(screen.getByTestId("metodologia-diagnostico")).getByRole("button")).toHaveAttribute("aria-expanded", "false");
  });

  it("exportar CSV: uma linha por escola (alfabética), o nível, as leituras e todos os sinais com a natureza", async () => {
    semear();
    renderComApp(<AnaliseEducacional />, { rota: ROTA, usuario: secretaria });
    await userEvent.click(await screen.findByRole("button", { name: /Exportar diagnóstico \(CSV\)/ }));
    expect(baixarCsv).toHaveBeenCalledTimes(1);
    const tabela = vi.mocked(baixarCsv).mock.calls[0][0];
    expect(tabela.nomeArquivo).toMatch(/^diagnostico-pedagogico-exploratorio_\d{4}-\d{2}-\d{2}\.csv$/);
    expect(tabela.cabecalho).toContain("Acompanhamento (hipótese exploratória)");
    expect(tabela.linhas.map((l) => l[0])).toEqual([
      "EMEF Sintética Alfa", "EMEF Sintética Beta", "EMEF Sintética Delta", "EMEI Sintética Gama",
    ]);
    const alfa = tabela.linhas[0];
    const col = (nome: string) => alfa[tabela.cabecalho.indexOf(nome)];
    expect(col("Acompanhamento (hipótese exploratória)")).toBe("Acompanhar");
    expect(col("Leitura (LP) — categoria")).toBe("Divergente: avaliação favorável, uso baixo");
    expect(col("Matemática (MT) — base da avaliação")).toBe("indicadores gerais (IEE/Ideb)");
    expect(col("Leitura (LP) — comparabilidade")).toBe("exploratória (anos e coortes diferentes)");
    // Anos como TEXTO: o número passaria por toLocaleString("pt-BR") e sairia "2.025" no arquivo.
    expect(col("Leitura (LP) — ano da avaliação usada")).toBe("2025");
    expect(col("Matemática (MT) — ano letivo das plataformas")).toBe("2026");
    const arquivo = conteudoCsv(tabela);
    expect(arquivo).toContain(";2025;2026;");
    expect(arquivo).not.toMatch(/2\.02[56]/);
    expect(String(col("Sinais (natureza: texto [referência])"))).toContain("Oficial: IEE 2025: 4,80, abaixo da meta 5,20 (não atingiu). [IEE 2025]");
    expect(tabela.linhas[3][1]).toBe("sem código INEP");
    expect(tabela.linhas[3][tabela.cabecalho.indexOf("Pendências")]).toContain("sem código INEP no cadastro");
    // Cada linha tem uma célula por coluna do cabeçalho.
    expect(tabela.linhas.every((l) => l.length === tabela.cabecalho.length)).toBe(true);
  });

  it("CSV: anos e comparabilidade são POR COMPONENTE (a LP sem avaliação não apaga a MT que tem)", async () => {
    const padrao = diagnostico();
    // Alfa só com SARESP de MT: a LP fica sem avaliação (sem ano, sem comparabilidade); a MT
    // tem 2025 × 2026 (exploratória). Uma coluna única, tirada da LP, diria "sem resultado".
    semear(diagnostico({
      escolas: padrao.escolas.map((e) => (e.id !== 2 ? e : {
        ...e,
        leituras: {
          lp: { ...e.leituras.lp, avaliacao: "sem_dado", base: null, categoria: "inconclusiva",
                anos: { avaliacao: null, plataforma: 2026 }, comparabilidade: null },
          mt: { ...e.leituras.mt, avaliacao: "atencao", base: "componente",
                anos: { avaliacao: 2025, plataforma: 2026 }, comparabilidade: "exploratoria" },
        },
      })),
    }));
    renderComApp(<AnaliseEducacional />, { rota: ROTA, usuario: secretaria });
    await userEvent.click(await screen.findByRole("button", { name: /Exportar diagnóstico \(CSV\)/ }));
    const tabela = vi.mocked(baixarCsv).mock.calls[0][0];
    const col = (nome: string) => tabela.linhas[0][tabela.cabecalho.indexOf(nome)];
    expect(col("Leitura (LP) — base da avaliação")).toBe("nenhuma avaliação entrou");
    expect(col("Leitura (LP) — ano da avaliação usada")).toBe("nenhuma avaliação entrou");
    expect(col("Leitura (LP) — comparabilidade")).toBe("sem comparação (falta a avaliação ou a plataforma)");
    expect(col("Matemática (MT) — base da avaliação")).toBe("do componente");
    expect(col("Matemática (MT) — ano da avaliação usada")).toBe("2025");
    expect(col("Matemática (MT) — comparabilidade")).toBe("exploratória (anos e coortes diferentes)");
  });

  it("a falha do diagnóstico aparece (com a faixa da hipótese), não some em silêncio", async () => {
    responder("GET", "/redes/1/analise/indicadores", baseRede());
    responderErro("GET", "/redes/1/analise/diagnostico", 403, "Acesso negado a esta rede.");
    renderComApp(<AnaliseEducacional />, { rota: ROTA, usuario: secretaria });
    expect(await screen.findByText("Não foi possível carregar o diagnóstico: Acesso negado a esta rede.")).toBeInTheDocument();
    expect(screen.getByTestId("faixa-hipotese")).toBeInTheDocument();
  });
});
