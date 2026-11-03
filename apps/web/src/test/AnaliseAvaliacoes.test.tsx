/**
 * A tabela de comparação entre escolas nas AVALIAÇÕES EXTERNAS (`TabelaComparacaoEscolas`, de
 * `pages/analise/AvaliacoesExternas`), hoje na seção "Todas as escolas na edição mais recente de
 * cada avaliação" da tela Avaliações externas (`/rede/avaliacoes-externas`, DESENHO3 §4): a
 * última edição oficial de cada indicador por escola, a posição contra a rede rotulada "Calculado
 * pelo Constela", a meta OFICIAL, a tendência e a ausência por extenso (nunca 0), em ordem
 * alfabética, com o nome levando à ficha da escola — na língua simples do fluxo principal (sem
 * a sigla técnica da média instável). NÃO MISTURA edições: cada coluna fica na edição mais
 * recente com resultado entre as escolas, e a escola cujo último resultado é de edição anterior
 * não mostra valor, posição, meta nem tendência ali — só o ano dele, por extenso; a conclusão
 * conta só essa edição de cada série. A escola inativa no cadastro leva o selo "inativa no
 * cadastro"; sem número oficial em escola nenhuma, a frase diz por quê (o motivo que o catálogo
 * dá a cada avaliação) e as escolas continuam listadas. Os cartões, o detalhe e a carga da seção:
 * SecretariaAvaliacoes.
 *
 * Números e nomes INVENTADOS (D13).
 */
import { describe, expect, it } from "vitest";

import type { OficialDiagnostico } from "../pages/analise/tiposDiagnostico";
import AvaliacoesExternasRede from "../pages/rede/secretaria/AvaliacoesExternasRede";
import { catalogo, diagnostico, renderTela, semCausalidade, semJargao } from "./SecretariaFixtures";
import { responder, responderErro, screen, userEvent, within } from "./utils";

function semear(diag = diagnostico()) {
  responder("GET", "/redes/1/analise/indicadores", catalogo());
  responder("GET", "/redes/1/analise/diagnostico", diag);
}

/** Abre a tela e pede a seção das escolas (no navegador, ela carrega ao chegar à tela). */
async function abrir() {
  renderTela("/rede/avaliacoes-externas", <AvaliacoesExternasRede />);
  await userEvent.click(within(await screen.findByTestId("todas-as-escolas"))
    .getByRole("button", { name: "Mostrar as escolas agora" }));
}

const linhaDe = (tabela: HTMLElement, escola: string) =>
  within(tabela).getByRole("rowheader", { name: escola }).closest("tr") as HTMLElement;

/** O nome de cada coluna (sem a nota que o cabeçalho pode trazer embaixo). */
const nomesDasColunas = (tabela: HTMLElement) => within(tabela).getAllByRole("columnheader")
  .map((c) => (c.querySelector("[data-nome-coluna]") ?? c).textContent);

/** As notas sob a tabela, como aparecem. */
const notasDaTabela = () => within(screen.getByTestId("notas-comparacao")).getAllByRole("listitem").map((li) => li.textContent);

/** Quantas vezes o texto aparece na seção (cada explicação longa: uma vez só). */
const vezes = (el: HTMLElement, texto: string) => (el.textContent ?? "").split(texto).length - 1;

describe("Comparação entre escolas — avaliações externas", () => {
  it("as colunas são as séries oficiais que alguma escola tem; as escolas em ordem alfabética", async () => {
    semear();
    await abrir();
    const tabela = await screen.findByTestId("tabela-comparacao-escolas");
    expect(nomesDasColunas(tabela)).toEqual(["Escola", "IEE", "Ideb", "SARESP 5º ano · LP", "SARESP 5º ano · MT"]);
    // A resposta veio Delta, Beta, Gama, Alfa: a tabela é alfabética (não é ranking).
    expect(within(tabela).getAllByRole("rowheader").map((r) => r.textContent)).toEqual([
      "EMEF Sintética Alfa", "EMEF Sintética Beta", "EMEF Sintética Delta", "EMEI Sintética Gama",
    ]);
  });

  it("o nome de cada escola leva à ficha dela (inclusive a escola sem nenhum número oficial)", async () => {
    semear();
    await abrir();
    const tabela = await screen.findByTestId("tabela-comparacao-escolas");
    expect(within(linhaDe(tabela, "EMEF Sintética Alfa")).getByRole("link", { name: "EMEF Sintética Alfa" }))
      .toHaveAttribute("href", "/rede/escolas/2");
    expect(within(linhaDe(tabela, "EMEI Sintética Gama")).getByRole("link", { name: "EMEI Sintética Gama" }))
      .toHaveAttribute("href", "/rede/escolas/4");
  });

  it("cada célula: valor + edição, a posição calculada (com a diferença e a rede), a meta oficial e a tendência", async () => {
    semear();
    await abrir();
    const tabela = await screen.findByTestId("tabela-comparacao-escolas");
    // As células de dados (o nome da escola é o cabeçalho da linha): IEE, Ideb, SARESP LP, SARESP MT.
    const [iee, , sarespLp] = within(linhaDe(tabela, "EMEF Sintética Alfa")).getAllByRole("cell");
    expect(sarespLp).toHaveTextContent("219,6");
    expect(sarespLp).toHaveTextContent("2025");
    expect(sarespLp.querySelector("[data-posicao=acima]")).toHaveTextContent("▲acima da rede(+7,2; rede 212,4)");
    expect(sarespLp).toHaveTextContent("subiu desde 2024 (214,0)");
    // IEE: a meta e a situação são as oficiais; sem número da rede — o porquê vale para a coluna
    // toda: fica UMA vez, no cabeçalho dela ("sem comparação com a rede (obs. 1)") e nas notas.
    expect(iee).toHaveTextContent("4,80");
    expect(iee).toHaveTextContent("meta 5,20");
    expect(iee).toHaveTextContent("não atingiu a meta");
    expect(iee).not.toHaveTextContent("o IEE só existe por escola");
    expect(iee.querySelector("[data-posicao]")).toBeNull();
    const cabecalhoIee = within(tabela).getAllByRole("columnheader")[1];
    expect(cabecalhoIee.querySelector("[data-nota-coluna]")).toHaveTextContent("sem comparação com a rede (obs. 1)");
    expect(notasDaTabela()[0]).toBe("Obs. 1 — o IEE só existe por escola: não há número da rede para comparar.");
    // Todas da mesma edição na coluna: nenhum aviso de edição anterior.
    expect(tabela.querySelector("[data-edicao-anterior]")).toBeNull();
  });

  it("abaixo e na média: o texto diz a posição (o símbolo nunca sozinho)", async () => {
    semear();
    await abrir();
    const tabela = await screen.findByTestId("tabela-comparacao-escolas");
    expect(linhaDe(tabela, "EMEF Sintética Beta").querySelector("[data-posicao=abaixo]"))
      .toHaveTextContent("abaixo da rede(−14,4; rede 212,4)");
    expect(linhaDe(tabela, "EMEF Sintética Beta")).toHaveTextContent("caiu desde 2024");
    expect(linhaDe(tabela, "EMEF Sintética Delta").querySelector("[data-posicao=na_media]"))
      .toHaveTextContent("na média da rede");
  });

  it("média instável não recebe posição e é dita em língua simples; a ausência é texto — nunca 0", async () => {
    semear();
    await abrir();
    const tabela = await screen.findByTestId("tabela-comparacao-escolas");
    const beta = linhaDe(tabela, "EMEF Sintética Beta");
    // Na célula, o selo curto e a falta com a nota; o motivo do servidor ("média instável (TPS = 0):
    // …") fica nas notas, sem a sigla técnica.
    const mtBeta = within(beta).getAllByRole("cell")[3];
    expect(within(mtBeta).getByText("média instável")).toBeInTheDocument();
    expect(mtBeta.querySelector("[data-sem-comparacao]")).toHaveTextContent("sem comparação com a rede (obs. 2)");
    expect(mtBeta).not.toHaveTextContent("poucos alunos");
    expect(notasDaTabela()).toContain("Obs. 2 — média instável (poucos alunos fizeram a prova): sem posição nem tendência.");
    expect(beta.querySelectorAll("[data-posicao]")).toHaveLength(1);       // só a LP, a MT é instável
    // A escola sem INEP diz a pendência em cada coluna; a que não tem o número diz isso.
    const gama = linhaDe(tabela, "EMEI Sintética Gama");
    expect(within(gama).getAllByText("sem código INEP no cadastro")).toHaveLength(4);
    expect(linhaDe(tabela, "EMEF Sintética Delta")).toHaveTextContent("sem resultado oficial");
    expect(gama).not.toHaveTextContent(/\b0([,.]0+)?\b/);
    semJargao(tabela);
  });

  it("sem tendência: curto na célula, o porquê na nota (sem repetir o da posição); a primeira edição não escreve nada", async () => {
    const padrao = diagnostico();
    semear(diagnostico({
      escolas: padrao.escolas.map((e) => {
        if (e.id === 2) {
          // Alfa: o IEE calculado com médias de TPS = 0 (o número vale; a tendência não).
          return { ...e, oficiais: e.oficiais.map((o) => (o.indicador !== "iee" ? o : {
            ...o, tps_zero: true,
            motivo_sem_tendencia: "IEE calculado com médias de TPS = 0 (participação abaixo do mínimo): não gera sinal de tendência",
          })) };
        }
        if (e.id === 3) {
          // Beta: a MT instável — posição e tendência faltam pelo MESMO motivo (escrito uma vez).
          return { ...e, oficiais: e.oficiais.map((o) => (o.componente !== "mt" ? o : {
            ...o, motivo_sem_tendencia: o.motivo_sem_comparacao,
          })) };
        }
        if (e.id === 5) {
          return { ...e, oficiais: e.oficiais.map((o) => ({
            ...o, motivo_sem_tendencia: "primeira edição com número oficial (sintético)" })) };
        }
        return e;
      }),
    }));
    await abrir();
    const tabela = await screen.findByTestId("tabela-comparacao-escolas");
    // IEE de médias instáveis: o selo curto e "sem tendência (obs. 2)"; o porquê, na nota 2.
    const [iee] = within(linhaDe(tabela, "EMEF Sintética Alfa")).getAllByRole("cell");
    expect(within(iee).getByText("calculado com médias instáveis")).toBeInTheDocument();
    expect(iee.querySelector("[data-sem-tendencia]")).toHaveTextContent("sem tendência (obs. 2)");
    expect(iee).not.toHaveTextContent("não gera sinal de tendência");
    // Primeira edição: a célula não escreve nada sobre a tendência; a nota diz, uma vez, o que é.
    const [, ideb] = within(linhaDe(tabela, "EMEF Sintética Delta")).getAllByRole("cell");
    expect(ideb).not.toHaveTextContent(/tendência|primeira edição/);
    expect(ideb.querySelector("[data-posicao=na_media]")).not.toBeNull();
    // Média instável: a posição e a tendência faltam pelo MESMO motivo — uma linha, uma nota.
    const mtBeta = within(linhaDe(tabela, "EMEF Sintética Beta")).getAllByRole("cell")[3];
    expect(mtBeta.querySelector("[data-sem-comparacao]"))
      .toHaveTextContent("sem comparação com a rede nem tendência (obs. 3)");
    expect(mtBeta.querySelector("[data-sem-tendencia]")).toBeNull();
    expect(notasDaTabela()).toEqual([
      "Obs. 1 — o IEE só existe por escola: não há número da rede para comparar.",
      "Obs. 2 — IEE calculado com médias instáveis (poucos alunos fizeram a prova): não gera sinal de tendência.",
      "Obs. 3 — média instável (poucos alunos fizeram a prova): sem posição nem tendência.",
      "Célula sem linha de tendência — primeira edição com número oficial (sintético).",
    ]);
    semJargao(tabela);
    semJargao(screen.getByTestId("notas-comparacao"));
  });

  it("o porquê que é da escola fica na célula, com a nota; o mesmo texto ganha o mesmo número; cada um aparece uma vez", async () => {
    const padrao = diagnostico();
    const idebDaDelta = padrao.escolas.find((e) => e.id === 5)!.oficiais[0];
    const QUEBRA = "a escala do SARESP mudou entre 2024 e 2025: não se traça tendência (sintético)";
    const semTendenciaPorQuebra = (o: OficialDiagnostico) => (o.componente !== "lp" ? o
      : { ...o, anterior: null, tendencia: null, motivo_sem_tendencia: QUEBRA });
    semear(diagnostico({
      escolas: padrao.escolas.map((e) => {
        if (e.id === 2) {
          // Alfa: Ideb 2023 acima da rede, sem tendência porque a edição ANTERIOR é instável.
          return { ...e, oficiais: [...e.oficiais.map(semTendenciaPorQuebra), {
            ...idebDaDelta, valor: 6.4, diferenca_rede: 0.4, posicao_rede: "acima" as const,
            motivo_sem_tendencia: "a edição anterior (2021) tem média instável (TPS = 0: participação abaixo do "
              + "mínimo do SARESP): não se traça tendência" }] };
        }
        if (e.id === 3) return { ...e, oficiais: e.oficiais.map(semTendenciaPorQuebra) };
        // Delta: o Ideb sem posição por um porquê dela (a Alfa, na mesma coluna, tem posição).
        if (e.id === 5) {
          return { ...e, oficiais: [{ ...idebDaDelta, valor_rede: null, diferenca_rede: null, posicao_rede: null,
                                      motivo_sem_comparacao: "a rede municipal não tem resultado oficial do Ideb em 2023" }] };
        }
        return e;
      }),
    }));
    await abrir();
    const tabela = await screen.findByTestId("tabela-comparacao-escolas");
    const [, idebAlfa, lpAlfa] = within(linhaDe(tabela, "EMEF Sintética Alfa")).getAllByRole("cell");
    const [, , lpBeta, mtBeta] = within(linhaDe(tabela, "EMEF Sintética Beta")).getAllByRole("cell");
    const [, idebDelta] = within(linhaDe(tabela, "EMEF Sintética Delta")).getAllByRole("cell");
    expect(idebAlfa.querySelector("[data-posicao=acima]")).not.toBeNull();
    expect(idebAlfa.querySelector("[data-sem-tendencia]")).toHaveTextContent("sem tendência (obs. 2)");
    // A mesma quebra de escala em duas escolas: a mesma nota.
    expect(lpAlfa.querySelector("[data-sem-tendencia]")).toHaveTextContent("sem tendência (obs. 3)");
    expect(lpBeta.querySelector("[data-sem-tendencia]")).toHaveTextContent("sem tendência (obs. 3)");
    expect(mtBeta.querySelector("[data-sem-comparacao]")).toHaveTextContent("sem comparação com a rede (obs. 4)");
    expect(idebDelta.querySelector("[data-sem-comparacao]")).toHaveTextContent("sem comparação com a rede (obs. 5)");
    // Só o IEE (o porquê é da coluna toda) tem nota no cabeçalho. A coluna da MT, só com a média
    // instável da Beta, não sobe nada: a instabilidade é da escola.
    expect([...tabela.querySelectorAll("th [data-nota-coluna]")].map((n) => n.closest("th")!
      .querySelector("[data-nome-coluna]")!.textContent)).toEqual(["IEE"]);
    expect(notasDaTabela()).toEqual([
      "Obs. 1 — o IEE só existe por escola: não há número da rede para comparar.",
      "Obs. 2 — a edição anterior (2021) tem média instável (poucos alunos fizeram a prova): não se traça tendência.",
      `Obs. 3 — ${QUEBRA}.`,
      "Obs. 4 — média instável (poucos alunos fizeram a prova): sem posição nem tendência.",
      "Obs. 5 — a rede municipal não tem resultado oficial do Ideb em 2023.",
    ]);
    // Cada explicação longa: uma vez na seção inteira (nunca uma por célula).
    const secao = screen.getByTestId("todas-as-escolas");
    expect(vezes(secao, QUEBRA)).toBe(1);
    expect(vezes(secao, "não há número da rede para comparar")).toBe(1);
    expect(vezes(secao, "não se traça tendência")).toBe(2);           // a quebra e a edição anterior instável
    expect(secao).not.toHaveTextContent("sem tendência:");
    semJargao(secao);
    semCausalidade(secao);
  });

  it("sem nenhuma explicação longa (todas com posição e tendência), as notas não aparecem", async () => {
    const padrao = diagnostico();
    // Só a Alfa, só o SARESP LP: posição e tendência — nada a explicar.
    semear(diagnostico({ escolas: padrao.escolas.filter((e) => e.id === 2)
      .map((e) => ({ ...e, oficiais: e.oficiais.filter((o) => o.indicador === "saresp") })) }));
    await abrir();
    const tabela = await screen.findByTestId("tabela-comparacao-escolas");
    expect(tabela.querySelector("[data-ref-nota]")).toBeNull();
    expect(screen.queryByTestId("notas-comparacao")).toBeNull();
    expect(screen.getByTestId("legenda-comparacao")).toHaveTextContent("não é ranking");
  });

  it("edições diferentes na mesma coluna: a da edição anterior não mostra o número — só o ano dele, por extenso", async () => {
    const padrao = diagnostico();
    // Beta só tem o SARESP 5º ano LP de 2024 (com posição e tendência); Alfa já tem o de 2025.
    semear(diagnostico({
      escolas: padrao.escolas.map((e) => (e.id !== 3 ? e : {
        ...e, oficiais: e.oficiais.map((o) => (o.componente !== "lp" ? o : {
          ...o, edicao: 2024, valor: 205.1, valor_rede: 210.0, diferenca_rede: -4.9, posicao_rede: "na_media" as const,
          anterior: { edicao: 2023, valor: 201.0 }, tendencia: "subiu" as const })) })),
    }));
    await abrir();
    const tabela = await screen.findByTestId("tabela-comparacao-escolas");
    const [, , lpBeta, mtBeta] = within(linhaDe(tabela, "EMEF Sintética Beta")).getAllByRole("cell");
    // A coluna fica em 2025: a célula de 2024 não mostra o valor, a posição nem a tendência.
    expect(lpBeta.querySelector("[data-edicao-anterior]"))
      .toHaveTextContent("sem resultado em 2025 — o último oficial desta escola é de 2024 (na ficha da escola)");
    expect(lpBeta).not.toHaveTextContent("205,1");
    expect(lpBeta).not.toHaveTextContent(/rede 210|na média|subiu|2023/);
    expect(lpBeta.querySelector("[data-posicao]")).toBeNull();
    // A MT da Beta é de 2025 (a edição da coluna): continua com o número.
    expect(mtBeta).toHaveTextContent("230,1");
    expect(mtBeta.querySelector("[data-edicao-anterior]")).toBeNull();
    const [, , lpAlfa] = within(linhaDe(tabela, "EMEF Sintética Alfa")).getAllByRole("cell");
    expect(lpAlfa).toHaveTextContent("219,6");
    expect(lpAlfa.querySelector("[data-edicao-anterior]")).toBeNull();
    expect(tabela.querySelectorAll("[data-edicao-anterior]")).toHaveLength(1);
    expect(screen.getByTestId("legenda-edicao-de-referencia")).toHaveTextContent(
      "Cada coluna fica numa edição só — a mais recente com resultado entre as escolas; o ano está em cada célula. "
      + "Quando o último resultado de uma escola é de uma edição anterior, a célula não mostra o número: diz o ano "
      + "dele, e o resultado fica na ficha da escola.");
    // "Detalhes e fontes" só cita os números que a tabela mostra (o de 2024 fica na ficha).
    await userEvent.click(within(screen.getByTestId("detalhes-fontes-comparacao")).getByRole("button"));
    expect(screen.getByTestId("detalhes-fontes-comparacao")).toHaveTextContent("EMEF Sintética Alfa — SARESP 5º ano LP (2025)");
    expect(screen.getByTestId("detalhes-fontes-comparacao")).not.toHaveTextContent("(2024)");
    semJargao(tabela);
    semCausalidade(tabela);
  });

  it("a edição de referência é por COLUNA: o Ideb de 2021 fica sem número, meta nem tendência; a conclusão conta só a de referência", async () => {
    const padrao = diagnostico();
    // Alfa tem o Ideb de 2023; Delta só o de 2021 (com meta, situação, tendência e posição).
    const idebDaDelta = padrao.escolas.find((e) => e.id === 5)!.oficiais[0];
    semear(diagnostico({
      escolas: padrao.escolas.map((e) => (
        e.id === 2 ? { ...e, oficiais: [...e.oficiais, { ...idebDaDelta, edicao: 2023, valor: 6.3, diferenca_rede: 0.3,
                                                         posicao_rede: "acima" as const }] }
          : e.id === 5 ? { ...e, oficiais: [{ ...idebDaDelta, edicao: 2021, valor: 5.9, meta: 5.8,
                                              situacao_meta: "atingiu" as const, diferenca_rede: -0.4,
                                              posicao_rede: "abaixo" as const, anterior: { edicao: 2019, valor: 5.5 },
                                              tendencia: "subiu" as const }] }
            : e)),
    }));
    await abrir();
    const tabela = await screen.findByTestId("tabela-comparacao-escolas");
    const [ieeDelta, idebDelta] = within(linhaDe(tabela, "EMEF Sintética Delta")).getAllByRole("cell");
    expect(idebDelta).toHaveTextContent("sem resultado em 2023 — o último oficial desta escola é de 2021 (na ficha da escola)");
    expect(idebDelta).not.toHaveTextContent(/5,9|meta|atingiu|subiu|abaixo/);
    // A coluna do IEE (2025) não muda a do Ideb (2023): o Ideb de 2023 da Alfa aparece inteiro.
    const [, idebAlfa] = within(linhaDe(tabela, "EMEF Sintética Alfa")).getAllByRole("cell");
    expect(idebAlfa).toHaveTextContent("6,3");
    expect(idebAlfa).toHaveTextContent("2023");
    expect(idebAlfa.querySelector("[data-posicao=acima]")).not.toBeNull();
    expect(ieeDelta).toHaveTextContent("sem resultado oficial");
    // A conclusão: a Delta (só 2021) não conta como "com resultado" nem como "abaixo".
    expect(screen.getByTestId("conclusao-escolas-avaliacoes")).toHaveTextContent(
      "2 de 4 escolas têm resultado oficial na edição mais recente de cada avaliação (IEE 2025, Ideb 2023, SARESP "
      + "2025). Em ao menos uma avaliação, 1 fica abaixo da rede municipal e 1 acima. 1 escola só tem resultado de "
      + "edição anterior: o último oficial dela fica na ficha da escola.");
  });

  it("a legenda rotula a posição como 'Calculado pelo Constela' (com as tolerâncias) e a meta como oficial", async () => {
    semear();
    await abrir();
    const legenda = await screen.findByTestId("legenda-comparacao");
    expect(within(legenda).getByText("Calculado pelo Constela")).toBeInTheDocument();
    expect(within(legenda).getByText("Oficial")).toBeInTheDocument();
    expect(legenda).toHaveTextContent("Ideb 0,2; IEE 0,2 (só tendência); SARESP 5 pontos; Saeb 5 pontos");
    expect(legenda).not.toHaveTextContent("participação");             // a tolerância das plataformas fica no diagnóstico
    expect(legenda).toHaveTextContent("não é ranking");
    expect(legenda).toHaveTextContent("Média instável (poucos alunos fizeram a prova) não é comparada.");
    semJargao(legenda);
    semCausalidade(legenda);
    // A fonte de cada número: só sob demanda.
    const fontes = within(screen.getByTestId("detalhes-fontes-comparacao")).getByRole("button");
    expect(fontes).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(fontes);
    expect(screen.getByTestId("detalhes-fontes-comparacao")).toHaveTextContent("iee_sintetico_2025.csv");
  });

  it("sem número oficial nenhum (há avaliações por escola importadas): diz por quê e lista todas as escolas", async () => {
    const padrao = diagnostico();
    semear(diagnostico({ escolas: padrao.escolas.map((e) => ({ ...e, oficiais: [], sinais: [] })) }));
    await abrir();
    const vazia = await screen.findByTestId("comparacao-vazia");
    expect(vazia).toHaveTextContent("Nenhuma escola da rede tem resultado oficial importado ainda: as avaliações "
      + "importadas (IEE, Ideb, SARESP) não trazem número oficial de nenhuma escola da rede. Sem número oficial não há "
      + "o que comparar.");
    // Nunca uma tabela vazia nem escolas sumidas: cada escola, com o que falta e o link da ficha.
    const lista = within(vazia).getByTestId("escolas-sem-resultado");
    expect(within(lista).getAllByRole("link").map((l) => l.textContent)).toEqual([
      "EMEF Sintética Alfa", "EMEF Sintética Beta", "EMEF Sintética Delta", "EMEI Sintética Gama",
    ]);
    expect(within(lista).getByText("sem código INEP no cadastro")).toBeInTheDocument();
    expect(within(lista).getAllByText("sem resultado oficial importado")).toHaveLength(3);
    // Só "importada" ou "não importada": a frase única basta (sem a lista por avaliação).
    expect(within(vazia).queryByTestId("motivos-sem-resultado")).toBeNull();
  });

  it("sem número oficial nenhum, com avaliação indisponível por OUTRO motivo: o motivo do catálogo, avaliação por avaliação", async () => {
    // Antes, a frase olhava só "por escola e disponível" e dizia "nenhuma avaliação ... foi
    // importada" também quando havia números gravados antes, só a estimativa ou faltava o
    // código IBGE. Agora cada avaliação por escola diz o motivo que o catálogo dá a ela.
    const padrao = diagnostico();
    const c = catalogo();
    const motivo: Record<string, Partial<(typeof c.indicadores)[number]>> = {
      iee: { motivo_indisponivel: "so_estimativa" },
      // O texto do servidor (com a ordem de importar) passa pela língua simples.
      ideb: { motivo_indisponivel: "so_sem_registro", texto_indisponivel:
        "só há números gravados antes, sem o registro do arquivo oficial: importe o arquivo oficial desta edição" },
      saeb: { motivo_indisponivel: "sem_codigo_ibge" },
    };
    responder("GET", "/redes/1/analise/indicadores", catalogo({
      indicadores: c.indicadores.map((i) => (motivo[i.chave]
        ? { ...i, disponivel: false, edicoes: [], edicao_mais_recente: null, ...motivo[i.chave] } : i)),
    }));
    responder("GET", "/redes/1/analise/diagnostico",
              diagnostico({ escolas: padrao.escolas.map((e) => ({ ...e, oficiais: [], sinais: [] })) }));
    await abrir();
    const vazia = await screen.findByTestId("comparacao-vazia");
    expect(vazia).toHaveTextContent("Nenhuma escola da rede tem resultado oficial importado ainda. Sem número oficial "
      + "não há o que comparar. O que falta em cada avaliação com resultado por escola:");
    // Nunca "nada foi importado" quando o motivo é outro.
    expect(vazia).not.toHaveTextContent(/foi importada para esta rede|as avaliações importadas \(/);
    // Uma linha por avaliação por escola (IEE, Ideb, SARESP, Saeb — o ICA é só da rede).
    expect(within(within(vazia).getByTestId("motivos-sem-resultado")).getAllByRole("listitem").map((li) => li.textContent))
      .toEqual([
        "IEE: só há a Estimativa Constela (calculada pelo Constela): ela não é o indicador oficial.",
        "Ideb: só há números gravados antes, sem o registro do arquivo oficial: falta importar o arquivo oficial desta "
          + "edição — quem importa é o administrador global.",
        "SARESP: os arquivos importados não trazem número oficial de nenhuma escola da rede.",
        "Saeb: a rede não tem o código IBGE do município cadastrado: os números da rede não podem ser recortados.",
      ]);
    // As escolas continuam listadas, cada uma com o que falta e o link da ficha.
    const lista = within(vazia).getByTestId("escolas-sem-resultado");
    expect(within(lista).getAllByRole("link")).toHaveLength(4);
    expect(within(lista).getByText("sem código INEP no cadastro")).toBeInTheDocument();
    semJargao(vazia);
    semCausalidade(vazia);
  });

  it("escola inativa no cadastro: continua na tabela, com o selo ao lado do nome", async () => {
    const padrao = diagnostico();
    const comStatus = padrao.escolas.map((e) => ({ ...e, status: e.id === 3 ? "inativa" : "ativa" }));
    semear(diagnostico({ escolas: comStatus }));
    await abrir();
    const tabela = await screen.findByTestId("tabela-comparacao-escolas");
    // Continua na tabela (são todas as escolas da rede), com o selo por extenso.
    const beta = within(tabela).getByRole("rowheader", { name: /^EMEF Sintética Beta/ });
    expect(beta).toHaveTextContent("EMEF Sintética Beta inativa no cadastro");
    expect(within(beta).getByRole("link", { name: "EMEF Sintética Beta" })).toHaveAttribute("href", "/rede/escolas/3");
    expect(tabela.querySelectorAll("[data-escola-inativa]")).toHaveLength(1);
    expect(within(tabela).getByRole("rowheader", { name: "EMEF Sintética Alfa" })).not.toHaveTextContent(/inativa/);
  });

  it("escola inativa na lista sem resultado oficial: o mesmo selo", async () => {
    const padrao = diagnostico();
    semear(diagnostico({ escolas: padrao.escolas.map((e) => ({
      ...e, oficiais: [], sinais: [], status: e.id === 4 ? "inativa" : "ativa" })) }));
    await abrir();
    const lista = within(await screen.findByTestId("comparacao-vazia")).getByTestId("escolas-sem-resultado");
    expect(within(lista).getAllByRole("listitem").map((li) => li.textContent)).toEqual([
      "EMEF Sintética Alfasem resultado oficial importado", "EMEF Sintética Betasem resultado oficial importado",
      "EMEF Sintética Deltasem resultado oficial importado",
      "EMEI Sintética Gama inativa no cadastrosem código INEP no cadastro",
    ]);
    expect(lista.querySelectorAll("[data-escola-inativa]")).toHaveLength(1);
  });

  it("sem o status da escola (resposta antiga), nenhuma escola é marcada como inativa", async () => {
    semear();
    await abrir();
    const tabela = await screen.findByTestId("tabela-comparacao-escolas");
    expect(tabela.querySelector("[data-escola-inativa]")).toBeNull();
    expect(tabela).not.toHaveTextContent(/inativa/);
  });

  it("rede sem escolas: diz isso (nada de tabela vazia)", async () => {
    semear(diagnostico({ escolas: [] }));
    await abrir();
    expect(await screen.findByTestId("comparacao-vazia")).toHaveTextContent("A rede não tem escolas cadastradas.");
    expect(screen.queryByTestId("tabela-comparacao-escolas")).toBeNull();
  });

  it("se o diagnóstico falha, a seção diz o erro (e o resto da tela continua)", async () => {
    responder("GET", "/redes/1/analise/indicadores", catalogo());
    responderErro("GET", "/redes/1/analise/diagnostico", 500, "FALHA-DIAG");
    await abrir();
    expect(await screen.findByText("Não foi possível carregar as escolas: FALHA-DIAG")).toBeInTheDocument();
    expect(screen.getByTestId("indicadores-disponiveis")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Escolas: comparar lado a lado/ })).toBeInTheDocument();
  });
});
