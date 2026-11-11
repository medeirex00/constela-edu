/**
 * ESCOLAS (`/rede/escolas`) — DESENHO3 §3: TODAS as escolas da rede no período (inclusive a
 * protegida, a sem dado e a inativa), em ordem alfabética, com o nome levando à ficha; a coluna
 * "Comparar" (de 2 a 4 escolas, na URL `?comparar=`) e a comparação LADO A LADO — Elefante e
 * Matific no período e, separadas pela frase dos períodos, as avaliações externas (lidas só das
 * escolas marcadas), UMA edição por linha: a mais recente com resultado entre as escolas marcadas;
 * a escola de edição anterior diz de quando é o último oficial dela, sem o número. A escola
 * inativa no cadastro leva o selo (pelo painel da rede); sem o uso (as plataformas com erro), as
 * escolas continuam listadas pelo cadastro, com o link para a ficha. A aba "Avaliações externas"
 * saiu daqui (é a tela Avaliações externas); o Ranking da Rede fica a um link. (O conteúdo de
 * cada célula da tabela está em AnalisePlataformas.)
 *
 * Números e nomes INVENTADOS (D13).
 */
import { describe, expect, it } from "vitest";

import CompararEscolas, { marcadasAntesDasPlataformas } from "../pages/rede/secretaria/CompararEscolas";
import { METRICAS_ELEFANTE } from "../pages/rede/secretaria/oQueMede";
import { TEXTO_SUPRESSAO } from "./AnaliseFixturesDiagnostico";
import {
  ESCOLAS_DO_CONTEXTO, analiseEscola, indicadorDaEscola, plataformasComEpsilon, renderEscolas, semearEscolas,
} from "./EscolasRedeFixtures";
import {
  admin, antes, caminhosLidos, chamadas, consulta, renderTela, semCausalidade, semJargao,
} from "./SecretariaFixtures";
import { api, responder, responderErro, screen, userEvent, waitFor, within } from "./utils";

const NOMES_EM_ORDEM = [
  "EMEF Sintética Alfa", "EMEF Sintética Beta", "EMEF Sintética Delta", "EMEF Sintética Épsilon", "EMEI Sintética Gama",
];
const leuAnaliseDeEscola = () => api.mock.calls.some(([c]) => /^\/escolas\/\d+\/analise/.test(String(c)));
const abrir = (caminho = "/rede/escolas") => renderEscolas(caminho);
const caixa = (nome: string) => screen.getByRole("checkbox", { name: `Comparar ${nome}` });

describe("Escolas — a lista", () => {
  it("TODAS as escolas em ordem alfabética (protegida, sem dado e inativa também), a conclusão antes da tabela", async () => {
    semearEscolas();
    const { container } = abrir();
    const tabela = await screen.findByTestId("tabela-escolas-periodo");
    expect(screen.getByRole("heading", { level: 1, name: "Escolas" })).toBeInTheDocument();
    // A aba das avaliações saiu: nenhuma aba, nenhuma tabela de avaliações de todas as escolas.
    expect(screen.queryAllByRole("tab")).toHaveLength(0);
    expect(screen.queryByTestId("tabela-comparacao-escolas")).toBeNull();
    expect(within(tabela).getAllByRole("rowheader").map((r) => within(r).getByRole("link").textContent))
      .toEqual(NOMES_EM_ORDEM);
    // A protegida e a sem dado aparecem, por extenso (nunca 0).
    expect(within(screen.getByTestId("escola-periodo-4")).getByTestId("escola-protegida"))
      .toHaveTextContent(`Protegido: ${TEXTO_SUPRESSAO}.`);
    expect(screen.getByTestId("escola-periodo-6")).toHaveTextContent("Sem dado: a escola não tem nenhuma coleta desta plataforma (texto sintético)");
    expect(screen.getByTestId("escola-periodo-6")).not.toHaveTextContent(/(^|\D)0(,0)?%/);
    // A inativa no cadastro (pelo painel da rede) leva o selo; as ativas, não.
    await waitFor(() => expect(within(screen.getByTestId("escola-periodo-6")).getByRole("rowheader")
      .querySelector("[data-escola-inativa]")).toHaveTextContent("inativa no cadastro"));
    expect(tabela.querySelectorAll("[data-escola-inativa]")).toHaveLength(1);
    const conclusao = screen.getByTestId("conclusao-escolas");
    expect(conclusao).toHaveTextContent("Ano letivo de 2026 (01/01/2026 a 31/12/2026): das 5 escolas");
    expect(antes(conclusao, tabela)).toBe(true);
    expect(screen.getByTestId("natureza-plataformas").querySelector("[data-natureza=plataforma]")).toHaveTextContent("Plataforma");
    expect(screen.getByTestId("como-comparar")).toHaveTextContent("ordem alfabética — não é ranking");
    expect(screen.getByLabelText("Período")).toHaveValue("ano_letivo");
    expect(screen.getByLabelText("Série")).toHaveValue("");
    semCausalidade(container);
    semJargao(container);
  });

  it("lê só o nome da rede e as plataformas do ano letivo: nada do diagnóstico nem das escolas sem escola marcada", async () => {
    semearEscolas();
    renderTela("/rede/escolas", <CompararEscolas />, { periodo: { preset: "mes" } });
    await screen.findByTestId("tabela-escolas-periodo");
    // O painel da rede (o cadastro: o selo da inativa) é a mesma leitura do Panorama e da ficha.
    await waitFor(() => expect(caminhosLidos().sort())
      .toEqual(["/redes", "/redes/1/analise/plataformas", "/redes/1/dashboard"]));
    expect(consulta(chamadas("/redes/1/analise/plataformas")[0]).get("periodo")).toBe("ano_letivo");
    expect(chamadas("/redes/1/analise/plataformas").every((c) => !consulta(c).has("escola_id"))).toBe(true);
    expect(leuAnaliseDeEscola()).toBe(false);
  });

  it("o nome da escola leva à ficha, com o período da lista; a ficha volta à lista com a mesma consulta", async () => {
    semearEscolas();
    // (A Secretaria escolhe o ano letivo ou um bimestre inteiro — G_GRUPO-2.)
    abrir("/rede/escolas?periodo=bimestre_3&serie=3");
    await screen.findByTestId("tabela-escolas-periodo");
    const link = within(screen.getByTestId("escola-periodo-2")).getByRole("link", { name: "EMEF Sintética Alfa" });
    expect(link).toHaveAttribute("href", "/rede/escolas/2?periodo=bimestre_3");
    await userEvent.click(link);
    expect(await screen.findByRole("heading", { level: 1, name: "EMEF Sintética Alfa" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Voltar para Escolas" }))
      .toHaveAttribute("href", "/rede/escolas?periodo=bimestre_3&serie=3");
  });

  it("o período e a série ficam na URL e refazem só a leitura das plataformas", async () => {
    semearEscolas();
    abrir("/rede/escolas?periodo=bimestre_3");
    await screen.findByTestId("tabela-escolas-periodo");
    expect(screen.getByLabelText("Período")).toHaveValue("bimestre_3");
    await userEvent.selectOptions(screen.getByLabelText("Período"), "bimestre_2");
    await waitFor(() => expect(chamadas("/redes/1/analise/plataformas").map((c) => consulta(c).get("periodo")))
      .toContain("bimestre_2"));
    expect(screen.getByTestId("onde")).toHaveTextContent("periodo=bimestre_2");
    await userEvent.selectOptions(screen.getByLabelText("Série"), "2");
    await waitFor(() => expect(chamadas("/redes/1/analise/plataformas").some((c) => consulta(c).get("serie") === "2"))
      .toBe(true));
    await waitFor(() => expect(screen.getByTestId("recorte-escolas")).toHaveTextContent("série (2º ano)"));
    expect(chamadas("/redes/1/analise/diagnostico")).toHaveLength(0);
    expect(screen.getByRole("link", { name: /Ver o uso da rede no período/ }))
      .toHaveAttribute("href", "/rede/plataformas?periodo=bimestre_2&serie=2");
    const legenda = screen.getByTestId("legenda-colunas-plataformas");
    await userEvent.click(within(legenda).getByRole("button"));
    expect(legenda).toHaveTextContent("Alunos matriculados no 2º ano na escola.");
    expect(legenda).toHaveTextContent(METRICAS_ELEFANTE[0].oQueMede);
    expect(legenda).toHaveTextContent("Marque de 2 a 4 escolas");
  });

  it("os links: o Ranking da Rede (outra medida) e as Avaliações externas de todas as escolas", async () => {
    semearEscolas();
    abrir();
    await screen.findByTestId("tabela-escolas-periodo");
    expect(screen.getByTestId("link-ranking")).toHaveTextContent("é outra medida");
    expect(screen.getByRole("link", { name: /Ranking da Rede \(pontuação do Constela\)/ })).toHaveAttribute("href", "/rede/ranking");
    expect(screen.getByRole("link", { name: /Abrir as Avaliações externas/ }))
      .toHaveAttribute("href", "/rede/avaliacoes-externas");
    expect(screen.getByTestId("link-avaliacoes"))
      .toHaveTextContent("Todas as escolas, na edição mais recente de cada avaliação, ficam em Avaliações externas.");
    expect(screen.queryByTestId("aviso-outra-rede")).toBeNull();
  });

  it("o uso (as plataformas) falha: as escolas continuam listadas pelo cadastro, com o link para a ficha — sem comparação", async () => {
    semearEscolas();
    responderErro("GET", "/redes/1/analise/plataformas", 500, "FALHA-DAS-PLATAFORMAS");
    const { container } = abrir("/rede/escolas?comparar=2,3");
    const lista = await screen.findByTestId("escolas-sem-uso", undefined, { timeout: 3000 });
    await waitFor(() => expect(lista).toHaveTextContent("FALHA-DAS-PLATAFORMAS"), { timeout: 3000 });
    await waitFor(() => expect(within(lista).getAllByRole("listitem")).toHaveLength(5));
    // TODAS as escolas do cadastro, em ordem alfabética, com o link para a ficha e o uso por extenso.
    const itens = within(lista).getAllByRole("listitem");
    expect(itens.map((i) => within(i).getByRole("link").textContent)).toEqual(NOMES_EM_ORDEM);
    expect(within(lista).getByRole("link", { name: "EMEF Sintética Alfa" })).toHaveAttribute("href", "/rede/escolas/2");
    for (const i of itens) expect(i).toHaveTextContent("o uso no período não pôde ser carregado");
    expect(within(screen.getByTestId("escola-sem-uso-6")).getByText("inativa no cadastro")).toBeInTheDocument();
    expect(lista.querySelectorAll("[data-escola-inativa]")).toHaveLength(1);
    // Nada de "sem uso", 0 ou comparação (ela depende do uso), mesmo com escolas na URL. (As avaliações das
    // marcadas da rede dela saem junto com as plataformas, antes de saber que elas falharam; nada aparece.)
    expect(lista).not.toHaveTextContent(/sem uso|(^|\D)0(,0)?%/i);
    expect(screen.queryByTestId("tabela-escolas-periodo")).toBeNull();
    expect(screen.queryByTestId("comparacao-lado-a-lado")).toBeNull();
    expect(screen.queryByTestId("comparacao-avaliacoes")).toBeNull();
    semCausalidade(container);
    semJargao(container);
  });

  it("o uso falha com o admin global: nenhuma escola lida (ele espera as plataformas para saber quais são da rede)", async () => {
    semearEscolas();
    responder("GET", "/redes", [{ id: 1, nome: "Rede Sintética Norte" }]);
    responderErro("GET", "/redes/1/analise/plataformas", 500, "FALHA-DAS-PLATAFORMAS");
    renderEscolas("/rede/escolas?rede=1&comparar=2,3", { usuario: admin });
    const lista = await screen.findByTestId("escolas-sem-uso", undefined, { timeout: 3000 });
    await waitFor(() => expect(lista).toHaveTextContent("FALHA-DAS-PLATAFORMAS"), { timeout: 3000 });
    expect(leuAnaliseDeEscola()).toBe(false);
  });

  it("sem o painel da rede, nenhum selo de inativa é inventado", async () => {
    semearEscolas();
    responderErro("GET", "/redes/1/dashboard", 500, "FALHA-DO-PAINEL");
    abrir();
    const tabela = await screen.findByTestId("tabela-escolas-periodo");
    await waitFor(() => expect(chamadas("/redes/1/dashboard").length).toBeGreaterThan(0));
    expect(within(tabela).getAllByRole("rowheader")).toHaveLength(5);
    expect(tabela.querySelector("[data-escola-inativa]")).toBeNull();
  });
});

describe("Escolas — comparar lado a lado", () => {
  it("marcar 2 escolas: a URL guarda, as duas aparecem lado a lado (plataformas, a frase e as avaliações)", async () => {
    semearEscolas();
    const { container } = abrir();
    await screen.findByTestId("tabela-escolas-periodo");
    expect(screen.getByTestId("resumo-comparar")).toHaveTextContent("marque de 2 a 4 escolas");
    await userEvent.click(caixa("EMEF Sintética Beta"));
    expect(screen.getByTestId("onde")).toHaveTextContent("/rede/escolas?comparar=3");
    expect(screen.getByTestId("resumo-comparar")).toHaveTextContent("1 escola marcada (EMEF Sintética Beta)");
    expect(screen.queryByTestId("comparacao-lado-a-lado")).toBeNull();
    await userEvent.click(caixa("EMEF Sintética Alfa"));
    expect(screen.getByTestId("onde")).toHaveTextContent("comparar=3%2C2");
    expect(screen.getByTestId("resumo-comparar"))
      .toHaveTextContent("2 escolas marcadas para comparar: EMEF Sintética Alfa e EMEF Sintética Beta.");
    const lado = await screen.findByTestId("comparacao-lado-a-lado");
    // Plataformas no período: uma coluna por escola, em ordem alfabética.
    const plataformas = within(lado).getByTestId("comparacao-plataformas");
    const colunas = within(plataformas).getAllByRole("columnheader").map((c) => c.textContent);
    expect(colunas).toEqual(["No período", "EMEF Sintética Alfa", "EMEF Sintética Beta"]);
    const participacao = within(plataformas).getAllByRole("row").find((r) => r.textContent?.startsWith("Participação"))!;
    expect(participacao).toHaveTextContent(/Participação70%85%/);
    // Alfa: o Matific escondido por poucos alunos medidos — "Protegido", com o porquê (nunca 0).
    expect(plataformas).toHaveTextContent("Protegido: menos de 5 alunos com dado desta plataforma no período");
    expect(plataformas).toHaveTextContent("coleta parcial (até 20/09/2026)");
    // A frase dos períodos ENTRE as plataformas e as avaliações.
    const frase = within(lado).getByTestId("frase-separacao");
    const avaliacoes = await within(lado).findByTestId("comparacao-avaliacoes");
    expect(antes(plataformas, frase) && antes(frase, avaliacoes)).toBe(true);
    // As avaliações: em cada linha, a edição mais recente entre as marcadas (aqui, a mesma nas duas), com o
    // número de cada escola; a falta por extenso.
    await waitFor(() => expect(avaliacoes).toHaveTextContent("219,6"));
    expect(within(avaliacoes).getByTestId("linha-oficial-saresp|5_ano|lp")).toHaveTextContent(/219,62025.*rede municipal: 212,4.*198,02025/);
    expect(within(avaliacoes).getByTestId("linha-oficial-saresp|5_ano|mt"))
      .toHaveTextContent(/sem resultado oficial.*230,12025.*média instável/);
    expect(within(avaliacoes).getByTestId("linha-oficial-iee|anos_iniciais|")).toHaveTextContent("meta 5,20 · não atingiu a meta");
    // O ICA (só da rede) não vira linha de escola.
    expect(within(avaliacoes).queryByTestId("linha-oficial-ica|2_ano|lp")).toBeNull();
    expect(frase).toHaveTextContent("até 2025");
    // A mesma edição nas duas escolas: o ano da linha e nenhuma célula de edição anterior.
    expect(within(within(avaliacoes).getByTestId("linha-oficial-saresp|5_ano|lp")).getByRole("rowheader"))
      .toHaveTextContent("edição 2025");
    expect(avaliacoes.querySelector("[data-edicao-anterior]")).toBeNull();
    expect(within(lado).queryByTestId("legenda-edicao-anterior")).toBeNull();
    // Só as escolas marcadas foram lidas, no ano letivo.
    const lidas = api.mock.calls.map(([c]) => String(c)).filter((c) => /^\/escolas\/\d+\/analise/.test(c));
    expect([...new Set(lidas)].sort()).toEqual(["/escolas/2/analise?periodo=ano_letivo&so_avaliacoes=true", "/escolas/3/analise?periodo=ano_letivo&so_avaliacoes=true"]);
    expect(chamadas("/redes/1/analise/diagnostico")).toHaveLength(0);
    semCausalidade(container);
    semJargao(container);
  });

  it("pela URL (?comparar=), com a escola sem INEP e a sem arquivo importado: o porquê de cada falta", async () => {
    semearEscolas();
    abrir("/rede/escolas?comparar=4,6");
    const avaliacoes = await screen.findByTestId("comparacao-avaliacoes");
    await waitFor(() => expect(avaliacoes).not.toHaveTextContent("carregando"));
    const linha = within(avaliacoes).getByRole("row", { name: /Resultado oficial/ });
    expect(linha).toHaveTextContent(/sem resultado oficial.*sem código INEP no cadastro/);
    expect(linha).not.toHaveTextContent(/\d/);
    // A protegida, nas plataformas: "Protegido" por extenso, nenhum número.
    const plataformas = screen.getByTestId("comparacao-plataformas");
    expect(plataformas).toHaveTextContent(`Protegido: ${TEXTO_SUPRESSAO}.`);
    expect(plataformas).toHaveTextContent("Sem dado: a escola não tem nenhuma coleta desta plataforma (texto sintético)");
    // A inativa no cadastro (Épsilon) leva o selo no cabeçalho da coluna; a Gama (ativa), não.
    await waitFor(() => expect(within(plataformas).getByRole("columnheader", { name: /EMEF Sintética Épsilon/ })
      .querySelector("[data-escola-inativa]")).toHaveTextContent("inativa no cadastro"));
    expect(within(plataformas).getByRole("columnheader", { name: /EMEI Sintética Gama/ })
      .querySelector("[data-escola-inativa]")).toBeNull();
  });

  it("uma edição por linha: a escola com o último resultado de edição anterior não mostra o número — diz de quando é", async () => {
    semearEscolas();
    // Beta com o Ideb só de 2019; Delta com 2021 e 2023: a linha do Ideb fica na de 2023.
    const beta = analiseEscola(3);
    responder("GET", "/escolas/3/analise", {
      ...beta, indicadores: [...beta.indicadores, indicadorDaEscola(3, "ideb", "Ideb", "anos_iniciais", null, [[2019, 5.4]])],
    });
    const { container } = abrir("/rede/escolas?comparar=3,5");
    const avaliacoes = await screen.findByTestId("comparacao-avaliacoes");
    await waitFor(() => expect(within(avaliacoes).getByTestId("linha-oficial-ideb|anos_iniciais|")).toHaveTextContent("6,1"));
    const linha = within(avaliacoes).getByTestId("linha-oficial-ideb|anos_iniciais|");
    expect(within(linha).getByRole("rowheader")).toHaveTextContent("edição 2023");
    const [celulaBeta, celulaDelta] = within(linha).getAllByRole("cell");
    // Beta (a 1ª coluna, ordem alfabética): nem o número, nem a rede, nem a meta de 2019.
    expect(celulaBeta.querySelector("[data-edicao-anterior]"))
      .toHaveTextContent("sem resultado em 2023 — o último oficial desta escola é de 2019 (na ficha da escola)");
    expect(celulaBeta).not.toHaveTextContent(/5,4|rede municipal|meta/);
    expect(within(celulaBeta).getByRole("link", { name: "na ficha da escola" })).toHaveAttribute("href", "/rede/escolas/3");
    // Delta, na edição da linha: o número, a edição e a rede na mesma edição.
    expect(celulaDelta).toHaveTextContent(/6,12023.*rede municipal: 6,0/);
    expect(celulaDelta.querySelector("[data-edicao-anterior]")).toBeNull();
    expect(screen.getByTestId("legenda-edicao-anterior")).toHaveTextContent("não mostra o número de uma edição anterior");
    // A linha em que as duas estão na mesma edição continua com os números (SARESP 5º ano · LP: só Beta).
    expect(within(avaliacoes).getByTestId("linha-oficial-saresp|5_ano|lp")).toHaveTextContent("198,02025");
    // As fontes listam só o que aparece (nada do Ideb 2019 da Beta).
    const fontes = screen.getByTestId("detalhes-fontes-comparacao");
    await userEvent.click(within(fontes).getByRole("button"));
    expect(fontes).toHaveTextContent("EMEF Sintética Delta — Ideb (2023)");
    expect(fontes).not.toHaveTextContent("Ideb (2019)");
    semCausalidade(container);
    semJargao(container);
  });

  it("no máximo 4: com 4 marcadas as outras travam; escola de outra rede na URL fica de fora e nunca é lida", async () => {
    semearEscolas();
    abrir("/rede/escolas?comparar=999,2,3,4,5,6");
    await screen.findByTestId("comparacao-lado-a-lado");
    expect(caixa("EMEF Sintética Alfa")).toBeChecked();
    expect(caixa("EMEF Sintética Delta")).toBeChecked();
    expect(caixa("EMEF Sintética Épsilon")).not.toBeChecked();
    expect(caixa("EMEF Sintética Épsilon")).toBeDisabled();
    expect(screen.getByTestId("resumo-comparar")).toHaveTextContent("4 escolas marcadas para comparar");
    // O porquê da caixa travada: escrito perto do resumo (o toque do celular não mostra o `title`) e
    // ligado à caixa travada (o leitor de tela o lê com ela). As marcadas não têm essa descrição.
    const porque = "Chegou ao máximo de 4 escolas: para marcar outra, desmarque uma.";
    expect(screen.getByTestId("porque-caixa-travada")).toHaveTextContent(porque);
    expect(screen.getByTestId("porque-caixa-travada")).toBeVisible();
    expect(caixa("EMEF Sintética Épsilon")).toHaveAccessibleDescription(porque);
    expect(caixa("EMEF Sintética Alfa")).not.toHaveAccessibleDescription(porque);
    expect(within(screen.getByTestId("comparacao-plataformas")).getAllByRole("columnheader")).toHaveLength(5);
    await waitFor(() => expect(chamadas("/escolas/5/analise")).toHaveLength(1));
    expect(chamadas("/escolas/999/analise")).toHaveLength(0);
    expect(chamadas("/escolas/6/analise")).toHaveLength(0);
    // Desmarcar uma: o porquê some e a caixa volta a funcionar.
    await userEvent.click(caixa("EMEF Sintética Alfa"));
    expect(screen.queryByTestId("porque-caixa-travada")).toBeNull();
    expect(caixa("EMEF Sintética Épsilon")).toBeEnabled();
    expect(caixa("EMEF Sintética Épsilon")).not.toHaveAccessibleDescription(porque);
  });

  it("tirar da comparação (o botão da coluna ou a caixa): com 1 só, o lado a lado some", async () => {
    semearEscolas();
    abrir("/rede/escolas?comparar=2,3,5");
    await screen.findByTestId("comparacao-lado-a-lado");
    await userEvent.click(within(screen.getByTestId("comparacao-plataformas"))
      .getByRole("button", { name: "Tirar EMEF Sintética Delta da comparação" }));
    expect(screen.getByTestId("onde")).toHaveTextContent("comparar=2%2C3");
    await userEvent.click(caixa("EMEF Sintética Beta"));
    expect(screen.getByTestId("onde")).toHaveTextContent("comparar=2");
    expect(screen.queryByTestId("comparacao-lado-a-lado")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Desmarcar todas" }));
    expect(screen.getByTestId("onde")).toHaveTextContent(/^\/rede\/escolas$/);
  });

  it("trocar o período mantém as marcadas e a comparação acompanha o período", async () => {
    semearEscolas();
    abrir("/rede/escolas?comparar=2,5");
    await screen.findByTestId("comparacao-lado-a-lado");
    // A leitura do 3º bimestre (a próxima) responde com a janela dele.
    responder("GET", "/redes/1/analise/plataformas", plataformasComEpsilon({
      janela: { inicio: "2026-07-24", fim: "2026-10-04", rotulo: "3º bimestre (24/07 a 04/10)" },
    }));
    await userEvent.selectOptions(screen.getByLabelText("Período"), "bimestre_3");
    expect(screen.getByTestId("onde")).toHaveTextContent("comparar=2%2C5");
    await waitFor(() => expect(screen.getByTestId("recorte-lado-a-lado")).toHaveTextContent("3º bimestre"));
    // As avaliações não dependem do período: a mesma leitura (ano letivo) de cada escola.
    expect(new Set(chamadas("/escolas/2/analise"))).toEqual(new Set(["/escolas/2/analise?periodo=ano_letivo&so_avaliacoes=true"]));
  });

  it("o nome na coluna leva à ficha; 'Ver lado a lado' existe com 2 ou mais", async () => {
    semearEscolas();
    abrir("/rede/escolas?comparar=2,5");
    const lado = await screen.findByTestId("comparacao-lado-a-lado");
    const nome = within(within(lado).getByTestId("comparacao-plataformas")).getByRole("link", { name: "EMEF Sintética Delta" });
    expect(nome).toHaveAttribute("href", "/rede/escolas/5");
    expect(screen.getByRole("button", { name: "Ver lado a lado" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Ver lado a lado" }));
    expect(within(lado).getByRole("heading", { level: 2, name: /Escolas lado a lado/ })).toHaveFocus();
  });
});

describe("Escolas — a comparação da Secretaria não espera as plataformas", () => {
  const plataformasPresas = () => responder("GET", "/redes/1/analise/plataformas", () => new Promise(() => {}));
  const lidas = () => [...new Set(api.mock.calls.map(([c]) => String(c)).filter((c) => /^\/escolas\/\d+\/analise/.test(c)))].sort();

  it("as avaliações das marcadas (escolas da lista da sessão) saem antes de as plataformas chegarem", async () => {
    semearEscolas();
    plataformasPresas();
    abrir("/rede/escolas?comparar=5,2");
    await waitFor(() => expect(lidas()).toEqual([
      "/escolas/2/analise?periodo=ano_letivo&so_avaliacoes=true", "/escolas/5/analise?periodo=ano_letivo&so_avaliacoes=true"]));
    // Sem as plataformas, nada da comparação aparece (ela depende do uso).
    expect(screen.queryByTestId("comparacao-lado-a-lado")).toBeNull();
  });

  it("uma escola marcada só, ou a 1ª fora da lista da sessão: nada é lido antes das plataformas", async () => {
    semearEscolas();
    plataformasPresas();
    abrir("/rede/escolas?comparar=2");
    await waitFor(() => expect(chamadas("/redes/1/dashboard").length).toBeGreaterThan(0));
    await new Promise((r) => setTimeout(r, 50));
    expect(leuAnaliseDeEscola()).toBe(false);
  });

  it.each([
    ["999,2,3", []], ["2,3,999", [2, 3]], ["2,6,3", [2]], ["2,3,4,5,999", [2, 3, 4, 5]], ["5,2,3,4,5", [5, 2, 3, 4]],
  ])("comparar=%s: lê antes só o começo que a sessão confirma (%j)", (consultaUrl, esperado) => {
    const ids = consultaUrl.split(",").map(Number).filter((n, i, a) => a.indexOf(n) === i);
    expect(marcadasAntesDasPlataformas(ids, ESCOLAS_DO_CONTEXTO)).toEqual(esperado);
  });

  it("as colunas casam a análise pelo id da escola (a URL em outra ordem que a alfabética)", async () => {
    semearEscolas();
    abrir("/rede/escolas?comparar=5,2");
    const avaliacoes = await screen.findByTestId("comparacao-avaliacoes");
    await waitFor(() => expect(within(avaliacoes).getByTestId("linha-oficial-ideb|anos_iniciais|")).toHaveTextContent("6,1"));
    const colunas = within(avaliacoes).getAllByRole("columnheader").map((c) => c.textContent);
    expect(colunas[1]).toContain("EMEF Sintética Alfa");
    expect(colunas[2]).toContain("EMEF Sintética Delta");
    // Alfa (1ª coluna) com o SARESP dela; Delta (2ª) com o Ideb dela — nunca trocados.
    const [alfaSaresp, deltaSaresp] = within(within(avaliacoes).getByTestId("linha-oficial-saresp|5_ano|lp")).getAllByRole("cell");
    expect(alfaSaresp).toHaveTextContent("219,6");
    expect(deltaSaresp).not.toHaveTextContent(/\d/);
    const [alfaIdeb, deltaIdeb] = within(within(avaliacoes).getByTestId("linha-oficial-ideb|anos_iniciais|")).getAllByRole("cell");
    expect(alfaIdeb).not.toHaveTextContent(/\d/);
    expect(deltaIdeb).toHaveTextContent("6,1");
  });

  it("o admin global espera as plataformas para ler as escolas (a lista da sessão não diz a rede delas)", async () => {
    semearEscolas();
    plataformasPresas();
    responder("GET", "/redes", [{ id: 1, nome: "Rede Sintética Norte" }]);
    renderEscolas("/rede/escolas?rede=1&comparar=2,3", { usuario: admin });
    await waitFor(() => expect(chamadas("/redes/1/dashboard").length).toBeGreaterThan(0));
    await new Promise((r) => setTimeout(r, 50));
    expect(leuAnaliseDeEscola()).toBe(false);
  });
});

describe("Escolas — admin global", () => {
  it("numa rede que o Ranking da Rede não abre: o aviso diz qual rede o Ranking mostra; os links levam ?rede=", async () => {
    semearEscolas();
    // O servidor lista Sul primeiro: o Ranking (que ainda não troca de rede) abre a Sul; aqui está a Norte.
    responder("GET", "/redes", [{ id: 2, nome: "Rede Sintética Sul" }, { id: 1, nome: "Rede Sintética Norte" }]);
    renderEscolas("/rede/escolas?rede=1", { usuario: admin });
    await screen.findByTestId("tabela-escolas-periodo");
    expect(screen.getByTestId("aviso-outra-rede"))
      .toHaveTextContent("O Ranking da Rede abre a rede “Rede Sintética Sul”, não a escolhida aqui");
    expect(within(screen.getByTestId("escola-periodo-3")).getByRole("link", { name: "EMEF Sintética Beta" }))
      .toHaveAttribute("href", "/rede/escolas/3?rede=1");
    expect(screen.getByRole("link", { name: /Abrir as Avaliações externas/ }))
      .toHaveAttribute("href", "/rede/avaliacoes-externas?rede=1");
  });

  it("na rede que o Ranking abre: sem aviso", async () => {
    semearEscolas();
    responder("GET", "/redes", [{ id: 1, nome: "Rede Sintética Norte" }, { id: 2, nome: "Rede Sintética Sul" }]);
    renderEscolas("/rede/escolas?rede=1", { usuario: admin });
    await screen.findByTestId("tabela-escolas-periodo");
    expect(screen.queryByTestId("aviso-outra-rede")).toBeNull();
  });
});

describe("Escolas — rede com um módulo só", () => {
  it("só Matific: o nome das plataformas e a comparação sem o Elefante", async () => {
    semearEscolas();
    responder("GET", "/redes/1/analise/plataformas", plataformasComEpsilon({ modulos: { elefante: false, matific: true } }));
    abrir("/rede/escolas?comparar=2,3");
    const lado = await screen.findByTestId("comparacao-lado-a-lado");
    expect(screen.getByRole("heading", { level: 2, name: /Todas as escolas — Matific no período/ })).toBeInTheDocument();
    expect(within(lado).queryByText("Elefante Letrado (leitura)")).toBeNull();
    expect(within(lado).getByText("Matific (matemática)")).toBeInTheDocument();
    expect(analiseEscola(2).indicadores.length).toBeGreaterThan(0);
  });
});
