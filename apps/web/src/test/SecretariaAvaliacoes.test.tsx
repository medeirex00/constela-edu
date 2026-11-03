/**
 * AVALIAÇÕES EXTERNAS (`/rede/avaliacoes-externas`) — DESENHO2 §2.3.4 e DESENHO3 §4: "Antes de
 * comparar"; um cartão por indicador do catálogo (o que mede, quem publica, frequência, a
 * DISPONIBILIDADE — edição mais recente importada ou "nenhuma edição oficial importada" e o
 * motivo —, o resultado da rede e a meta — ou "por escola" no IEE); a Estimativa Constela e o
 * número sem registro à parte; o DETALHE (o `PorIndicador` inteiro) ao clicar "Ver série histórica
 * e escolas" — as tabelas rolam no cartão com o aviso "Deslize…" e a 1ª coluna presa, e o nome da
 * escola numa edição leva à ficha —; os links antigos com `?indicador=…` abrem o detalhe e rolam
 * até ele — só nessa chegada; "Todas as escolas na edição mais recente de cada avaliação" (o
 * diagnóstico só é lido quando a seção chega à tela ou é pedida; a conclusão conta só a edição de
 * referência de cada série; o nome leva à ficha da escola); avisos e metodologia
 * recolhidos; o link de fonte vai aos arquivos oficiais (nada de Análises avançadas nem
 * Relatórios). A tabela das escolas em detalhe: AnaliseAvaliacoes.
 *
 * Números e nomes INVENTADOS (D13).
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import PorIndicador from "../pages/analise/PorIndicador";
import type { LinhaEscolaAnalise, PontoAnalise, RespostaIndicador } from "../pages/analise/tipos";
import AvaliacoesExternasRede from "../pages/rede/secretaria/AvaliacoesExternasRede";
import { INDICADORES_EXPLICADOS } from "../pages/rede/secretaria/oQueMede";
import { FONTE, oficial } from "./AnaliseFixturesDiagnostico";
import {
  METODOLOGIA_COM_RELACAO, admin, antes, caminhosLidos, catalogo, chamadas, consulta, diagnostico, renderTela,
  secretaria, semCausalidade, semJargao, semearSecretaria,
} from "./SecretariaFixtures";
import { act, renderComApp, responder, responderErro, screen, userEvent, waitFor, within } from "./utils";

const ROTA = "/rede/avaliacoes-externas";

function ponto(edicao: number, valor: number, over: Partial<PontoAnalise> = {}): PontoAnalise {
  return { edicao, valor, casas: 1, motivo_ausencia: null, texto_ausencia: null, meta: null, meta_casas: null,
           diferenca_meta: null, situacao_meta: null, instavel: false, fonte_id: 21, ...over };
}

function linha(escola_id: number, nome: string, valor: number, over: Partial<LinhaEscolaAnalise> = {}): LinhaEscolaAnalise {
  return { escola_id, nome, valor, casas: 2, motivo_ausencia: null, texto_ausencia: null, meta: null,
           diferenca_meta: null, instavel: false, fonte_id: 21, ...over };
}

const indicadorDe = (chave: string) => catalogo().indicadores.find((i) => i.chave === chave)!;

/** O SARESP da rede, 5º ano LP, com um aviso do servidor que traz a sigla técnica. */
function detalheSaresp(over: Partial<RespostaIndicador> = {}): RespostaIndicador {
  return {
    indicador: indicadorDe("saresp"),
    filtros: { etapa: "5_ano", componente: "lp", escola_id: null, de: null, ate: null, visao: "serie", edicao: null },
    opcoes: { etapas: ["5_ano", "2_ano"], componentes: ["lp", "mt"], edicoes: [2024, 2025],
              escolas: [{ id: 2, nome: "EMEF Sintética Alfa", tem_dado: true }] },
    series: [{ id: "rede_municipal", rotulo: "Rede municipal", papel: "principal", abrangencia: "rede", escola_id: null,
               rede_ensino: "municipal", mesma_rede: true, comparavel: true, motivo_nao_comparavel: null,
               pontos: [ponto(2024, 210.0), ponto(2025, 212.4)] }],
    escolas: [
      linha(2, "EMEF Sintética Alfa", 219.6, { casas: 1 }),
      linha(3, "EMEF Sintética Beta", 230.1, { casas: 1, instavel: true }),
    ],
    quebras: [],
    // Os dois avisos como o servidor escreve (com a sigla técnica).
    avisos: ["TPS = 0: a escola não atingiu a taxa mínima de participação do SARESP; a média dela é instável.",
             "IEE de escola com TPS = 0 (participação abaixo do mínimo do SARESP): o índice é o oficial."],
    fontes: { "21": FONTE },
    ...over,
  };
}

/** O IEE por escola numa edição: uma escola com o índice calculado de médias instáveis. */
function ieeEscolas(): RespostaIndicador {
  return {
    indicador: indicadorDe("iee"),
    filtros: { etapa: "anos_iniciais", componente: null, escola_id: null, de: null, ate: null, visao: "escolas", edicao: 2025 },
    opcoes: { etapas: ["anos_iniciais"], componentes: [], edicoes: [2024, 2025], escolas: [] },
    series: [],
    escolas: [
      linha(2, "EMEF Sintética Alfa", 4.8, { meta: 5.2, meta_casas: 2, diferenca_meta: -0.4, situacao_meta: "nao_atingiu" }),
      linha(3, "EMEF Sintética Beta", 4.9, { meta: 4.5, meta_casas: 2, diferenca_meta: 0.4, situacao_meta: "atingiu",
                                             tps_zero: true }),
    ],
    quebras: [],
    avisos: [],
    fontes: { "21": FONTE },
  };
}

function semear() {
  semearSecretaria();
  responder("GET", "/redes/1/analise/indicadores/saresp", detalheSaresp());
  responder("GET", (c: string) => c.startsWith("/redes/1/analise/indicadores/iee"), ieeEscolas());
}

const cartao = (chave: string) => screen.getByTestId(`indicador-cartao-${chave}`);

afterEach(() => vi.restoreAllMocks());

describe("Avaliações externas — os indicadores disponíveis", () => {
  it("um cartão por indicador do catálogo, com a conclusão, o que mede, quem publica, frequência, edição e meta", async () => {
    semear();
    renderTela(ROTA, <AvaliacoesExternasRede />);
    const grade = await screen.findByTestId("indicadores-disponiveis");
    expect(screen.getByRole("heading", { level: 1, name: "Avaliações externas" })).toBeInTheDocument();
    expect(within(grade).getAllByRole("article").map((a) => a.getAttribute("data-testid"))).toEqual([
      "indicador-cartao-ica", "indicador-cartao-iee", "indicador-cartao-ideb", "indicador-cartao-saresp",
      "indicador-cartao-saeb",
    ]);
    // "Antes de comparar" vem antes dos cartões.
    expect(antes(screen.getByTestId("antes-de-comparar"), grade)).toBe(true);
    expect(screen.getByTestId("antes-de-comparar")).toHaveTextContent("Compare cada uma com ela mesma");

    const ica = cartao("ica");
    expect(within(ica).getByTestId("indicador-conclusao-ica")).toHaveTextContent("Rede em 2025: 58% — abaixo da meta de 60%.");
    expect(ica).toHaveTextContent(`O que mede: ${INDICADORES_EXPLICADOS.ica.oQueMede}`);
    expect(ica).toHaveTextContent("Existe só para a rede (não por escola).");
    expect(ica).toHaveTextContent("Quem publicaINEP");
    expect(ica).toHaveTextContent("FrequênciaAnual");
    expect(within(ica).getByTestId("indicador-disponibilidade-ica"))
      .toHaveTextContent("edição mais recente importada: 2025 (2 edições: 2024 e 2025)");
    expect(ica).toHaveTextContent("Disponibilidadeedição mais recente importada: 2025");
    expect(ica.querySelector("[data-natureza=oficial]")).toHaveTextContent("Oficial");
    // A rede edição a edição, em miniatura (o texto alternativo lê a série).
    expect(within(ica).getByRole("img")).toHaveAttribute("aria-label", expect.stringContaining("2024: 55%; 2025: 58%"));

    expect(within(cartao("iee")).getByTestId("indicador-conclusao-iee")).toHaveTextContent(
      "Por escola: cada escola tem o seu resultado e a sua meta (não existe número da rede). Edição mais recente: 2025.");
    expect(cartao("iee")).toHaveTextContent(INDICADORES_EXPLICADOS.iee.oQueMede);
    expect(within(cartao("saresp")).getByTestId("indicador-conclusao-saresp"))
      .toHaveTextContent("Rede em 2025 (5º ano, Língua Portuguesa): 212,4.");
    expect(within(cartao("ideb")).getByTestId("indicador-conclusao-ideb"))
      .toHaveTextContent("Só há resultado por escola importado (sem número oficial da rede). Edição mais recente: 2023.");
    expect(within(cartao("ideb")).getByTestId("indicador-disponibilidade-ideb"))
      .toHaveTextContent("edição mais recente importada: 2023 (2 edições: 2021 e 2023)");
  });

  it("a disponibilidade de cada cartão: a única edição, várias (de … a …) ou nenhuma — sem 0 no lugar do ano", async () => {
    semear();
    const c = catalogo();
    responder("GET", "/redes/1/analise/indicadores", catalogo({
      indicadores: c.indicadores.map((i) => (
        i.chave === "ideb" ? { ...i, edicoes: [2017, 2019, 2021, 2023], edicao_mais_recente: 2023 }
          : i.chave === "iee" ? { ...i, edicoes: [2025], edicao_mais_recente: 2025 }
            : i.chave === "saeb" ? { ...i, motivo_indisponivel: "so_estimativa",
                                     texto_indisponivel: "só há a Estimativa Constela (calculada pelo Constela): ela não "
                                       + "é o indicador oficial" }
              : i)),
    }));
    renderTela(ROTA, <AvaliacoesExternasRede />);
    await screen.findByTestId("indicadores-disponiveis");
    expect(screen.getByTestId("indicador-disponibilidade-ideb"))
      .toHaveTextContent("edição mais recente importada: 2023 (4 edições, de 2017 a 2023)");
    expect(screen.getByTestId("indicador-disponibilidade-iee")).toHaveTextContent("edição mais recente importada: 2025 (a única)");
    // Indisponível: nenhuma edição oficial e o motivo no mesmo cartão.
    const saeb = cartao("saeb");
    expect(within(saeb).getByTestId("indicador-disponibilidade-saeb")).toHaveTextContent("nenhuma edição oficial importada");
    expect(within(saeb).getByTestId("indicador-indisponivel-saeb"))
      .toHaveTextContent("Ainda não disponível: só há a Estimativa Constela (calculada pelo Constela)");
    expect(within(saeb).getByTestId("indicador-disponibilidade-saeb")).not.toHaveTextContent(/\d/);
  });

  it("o indicador indisponível diz o motivo (sem botão); estimativa e sem registro ficam à parte", async () => {
    semear();
    renderTela(ROTA, <AvaliacoesExternasRede />);
    await screen.findByTestId("indicadores-disponiveis");
    const saeb = cartao("saeb");
    expect(within(saeb).getByTestId("indicador-indisponivel-saeb"))
      .toHaveTextContent("Ainda não disponível: nenhum arquivo oficial deste indicador foi importado para esta rede.");
    expect(within(saeb).queryByRole("button")).toBeNull();
    expect(within(saeb).getByTestId("indicador-disponibilidade-saeb")).toHaveTextContent("nenhuma edição oficial importada");
    expect(screen.getByTestId("estimativas-fora")).toHaveTextContent("Estimativa Constela");
    expect(screen.getByTestId("estimativas-fora")).not.toHaveTextContent("sem o registro");
    expect(screen.getByTestId("sem-registro-fora")).toHaveTextContent("sem o registro do arquivo oficial");
    // Fonte só sob demanda.
    expect(within(screen.getByTestId("detalhes-fontes-destaques")).getByRole("button"))
      .toHaveAttribute("aria-expanded", "false");
  });

  it("sem indicador escolhido, só o catálogo é lido e o detalhe diz como abrir", async () => {
    semear();
    renderTela(ROTA, <AvaliacoesExternasRede />);
    expect(await screen.findByTestId("detalhe-vazio")).toHaveTextContent("Escolha “Ver série histórica e escolas”");
    // A tabela das escolas (o diagnóstico, leitura pesada) espera a seção chegar à tela.
    expect(screen.getByTestId("escolas-a-carregar")).toHaveTextContent("As escolas aparecem quando esta parte da página");
    expect(caminhosLidos()).toEqual(["/redes/1/analise/indicadores"]);
  });
});

describe("Avaliações externas — o detalhe de um indicador", () => {
  it("'Ver série histórica e escolas' abre o PorIndicador daquele indicador (sem repetir a escolha) e rola até ele", async () => {
    semear();
    const rolar = vi.spyOn(Element.prototype, "scrollIntoView").mockImplementation(() => undefined);
    const { container } = renderTela(ROTA, <AvaliacoesExternasRede />);
    await screen.findByTestId("indicadores-disponiveis");
    await userEvent.click(screen.getByRole("button", { name: "Ver série histórica e escolas — SARESP" }));
    expect(screen.getByTestId("onde")).toHaveTextContent(`${ROTA}?indicador=saresp`);
    const detalhe = screen.getByTestId("avaliacoes-detalhe");
    expect(await within(detalhe).findByRole("heading", { name: "Série histórica e escolas — SARESP" })).toBeInTheDocument();
    expect(await within(detalhe).findByTestId("indicador-tabela")).toHaveTextContent("212,4");
    expect(within(detalhe).getByTestId("indicador-grafico")).toBeInTheDocument();
    // A escolha dos indicadores não se repete no detalhe (os cartões já escolhem).
    expect(within(detalhe).queryByRole("group", { name: "Indicador oficial (um por vez)" })).toBeNull();
    expect(rolar).toHaveBeenCalledTimes(1);
    // O aviso do servidor sai sem a sigla técnica.
    const avisos = within(detalhe).getByTestId("avisos-comparabilidade");
    expect(avisos).toHaveTextContent("Média instável: a escola não atingiu a taxa mínima de participação do SARESP");
    expect(avisos).toHaveTextContent("IEE de escola com média instável (participação abaixo do mínimo do SARESP)");
    semJargao(container);
    semCausalidade(container);
  });

  it("o link antigo (?indicador=…&visao=escolas&edicao=…) abre o detalhe e rola só na chegada", async () => {
    semear();
    const rolar = vi.spyOn(Element.prototype, "scrollIntoView").mockImplementation(() => undefined);
    renderTela(`${ROTA}?indicador=saresp&visao=escolas&edicao=2025`, <AvaliacoesExternasRede />);
    const escolas = await screen.findByTestId("indicador-escolas");
    expect(consulta(chamadas("/redes/1/analise/indicadores/saresp")[0]).get("visao")).toBe("escolas");
    expect(consulta(chamadas("/redes/1/analise/indicadores/saresp")[0]).get("edicao")).toBe("2025");
    expect(within(escolas).getAllByRole("rowheader").map((r) => r.textContent))
      .toEqual(["EMEF Sintética Alfa", "EMEF Sintética Beta"]);
    expect(escolas).toHaveTextContent("média instável (poucos alunos fizeram a prova)");
    expect(rolar).toHaveBeenCalledTimes(1);
    // Mexer nas dimensões do detalhe não rola de novo.
    await userEvent.click(screen.getByRole("radio", { name: "Série histórica" }));
    await screen.findByTestId("indicador-tabela");
    expect(rolar).toHaveBeenCalledTimes(1);
  });

  it("a escola vem de um campo do próprio detalhe (a tela não tem filtros no topo)", async () => {
    semear();
    renderTela(`${ROTA}?indicador=saresp`, <AvaliacoesExternasRede />);
    await screen.findByTestId("indicador-tabela");
    expect(screen.getByTestId("motivo-sem-escola")).toHaveTextContent("Escolha uma escola no campo Escola.");
    await userEvent.selectOptions(screen.getByLabelText("Escola"), "2");
    expect(screen.getByTestId("onde")).toHaveTextContent("escola=2");
    const radio = screen.getByRole("radio", { name: "Escola escolhida: EMEF Sintética Alfa" });
    expect(radio).toBeEnabled();
    await userEvent.click(radio);
    await waitFor(() => expect(chamadas("/redes/1/analise/indicadores/saresp")
      .some((c) => consulta(c).get("escola_id") === "2")).toBe(true));
  });

  it("IEE por escola: o índice de médias instáveis aparece marcado em língua simples", async () => {
    semear();
    renderTela(`${ROTA}?indicador=iee`, <AvaliacoesExternasRede />);
    const escolas = await screen.findByTestId("indicador-escolas");
    const beta = within(escolas).getByRole("rowheader", { name: "EMEF Sintética Beta" }).closest("tr")!;
    expect(beta).toHaveTextContent("calculado com médias instáveis");
    expect(beta).toHaveTextContent("atingiu a meta");
    semJargao(screen.getByTestId("avaliacoes-detalhe"));
  });
});

describe("Avaliações externas — avisos, metodologia e links", () => {
  it("os avisos sobre os dados oficiais e a metodologia ficam recolhidos; os links levam ao lugar certo", async () => {
    semear();
    renderTela(ROTA, <AvaliacoesExternasRede />);
    await screen.findByTestId("indicadores-disponiveis");
    const avisos = screen.getByTestId("avisos-dados-oficiais");
    // O catálogo manda 2 (o de cadastro e o de "metodologia"); o da metodologia fala da relação com
    // as plataformas — esta tela não mostra plataformas (o "Antes de comparar" orienta a leitura).
    const botao = within(avisos).getByRole("button", { name: "Avisos sobre os dados oficiais (1)" });
    expect(botao).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(botao);
    const lista = screen.getByTestId("alertas-analise");
    expect(lista).toHaveTextContent("Cadastro");
    expect(lista).toHaveTextContent("EMEI Sintética Gama");
    expect(lista).not.toHaveTextContent("As plataformas têm dados do ano letivo");
    await userEvent.click(within(screen.getByTestId("metodologia-resumo")).getByRole("button"));
    expect(screen.getByTestId("metodologia-resumo")).toHaveTextContent("Sem resultado não é zero");
    expect(screen.getByRole("link", { name: /Escolas: comparar lado a lado/ })).toHaveAttribute("href", "/rede/escolas");
    expect(screen.getByRole("link", { name: /Arquivos oficiais de cada número/ })).toHaveAttribute("href", "/rede/avaliacoes");
    // Nenhum link para as Análises avançadas nem para os Relatórios (fora do menu da Secretaria).
    const destinos = screen.getAllByRole("link").map((l) => l.getAttribute("href") ?? "");
    expect(destinos.filter((h) => /^\/rede\/(analise|relatorios)/.test(h))).toEqual([]);
  });

  it("'Como ler estes números' aberto: sem a metodologia da relação estatística (Spearman, intervalo, causa e efeito)", async () => {
    semear();
    responder("GET", "/redes/1/analise/indicadores", catalogo({ metodologia_resumo: METODOLOGIA_COM_RELACAO }));
    const { container } = renderTela(ROTA, <AvaliacoesExternasRede />);
    await screen.findByTestId("indicadores-disponiveis");
    const metodologia = screen.getByTestId("metodologia-resumo");
    await userEvent.click(within(metodologia).getByRole("button", { name: "Como ler estes números" }));
    expect(within(metodologia).getAllByRole("listitem")).toHaveLength(1);
    expect(metodologia).toHaveTextContent("Sem resultado não é zero");
    semJargao(container);
    semCausalidade(container);
  });

  it("sem jargão interno (1 clique, D2, CODMUN, destaques, relação) nem ordem de importar: só o admin global importa", async () => {
    semear();
    const c = catalogo();
    responder("GET", "/redes/1/analise/indicadores", catalogo({
      // Textos no MOLDE dos do servidor (indicadores.py).
      indicadores: c.indicadores.map((i) => (i.chave !== "saeb" ? i : {
        ...i, motivo_indisponivel: "so_sem_registro",
        texto_indisponivel: "só há números gravados antes, sem o registro do arquivo oficial: importe o arquivo oficial "
          + "desta edição" })),
      alertas: [...c.alertas,
        { tipo: "cadastro", indicador: "saresp", escolas: [],
          texto: "A rede não tem o código do município na SEDUC (CODMUN): o SARESP da rede por município não pode ser "
            + "recortado." },
        { tipo: "sem_registro", indicador: "ideb", escolas: [5],
          texto: "Ideb 2023: 1 de 4 escola(s) com número gravado antes, sem o registro do arquivo oficial — o número "
            + "aparece marcado e não entra nos destaques nem na relação." }],
      metodologia_resumo: ["Oficial × estimativa: só os números com o registro do arquivo oficial entram nos destaques e "
        + "na relação com as plataformas. A Estimativa Constela aparece à parte."],
    }));
    const { container } = renderTela(ROTA, <AvaliacoesExternasRede />);
    await screen.findByTestId("indicadores-disponiveis");
    expect(within(cartao("saeb")).getByTestId("indicador-indisponivel-saeb")).toHaveTextContent(
      "falta importar o arquivo oficial desta edição — quem importa é o administrador global");
    await userEvent.click(within(screen.getByTestId("avisos-dados-oficiais")).getByRole("button"));
    await userEvent.click(within(screen.getByTestId("metodologia-resumo")).getByRole("button"));
    expect(screen.getByTestId("alertas-analise")).toHaveTextContent("Quem cadastra é o administrador global.");
    expect(screen.getByTestId("alertas-analise")).toHaveTextContent("não entra nos resultados da rede nos cartões.");
    expect(screen.getByTestId("metodologia-resumo"))
      .toHaveTextContent("entram nos resultados da rede nos cartões. A Estimativa Constela aparece à parte.");
    expect(screen.getByTestId("sem-registro-fora")).not.toHaveTextContent("1 clique");
    expect(container).not.toHaveTextContent(/1 clique|importe o arquivo|\bD2\b|CODMUN|destaques|rela[çc][ãa]o/);
  });
});

describe("Avaliações externas — o detalhe abre no recorte do cartão; a nota das escolas depende da meta", () => {
  it("'Ver série histórica e escolas' leva a etapa e o componente do resultado que o cartão mostra", async () => {
    semear();
    vi.spyOn(Element.prototype, "scrollIntoView").mockImplementation(() => undefined);
    // O destaque do SARESP é o do 2º ano (a edição mais nova), não o 5º ano (o padrão da API).
    const c = catalogo();
    responder("GET", "/redes/1/analise/indicadores", catalogo({
      destaques: c.destaques.map((d) => (d.indicador === "saresp" ? { ...d, etapa: "2_ano", componente: "lp" } : d)),
    }));
    renderTela(ROTA, <AvaliacoesExternasRede />);
    await screen.findByTestId("indicadores-disponiveis");
    expect(within(cartao("saresp")).getByTestId("indicador-conclusao-saresp")).toHaveTextContent("(2º ano, Língua Portuguesa)");
    await userEvent.click(screen.getByRole("button", { name: "Ver série histórica e escolas — SARESP" }));
    expect(screen.getByTestId("onde")).toHaveTextContent("etapa=2_ano");
    expect(screen.getByTestId("onde")).toHaveTextContent("componente=lp");
    await waitFor(() => expect(chamadas("/redes/1/analise/indicadores/saresp").length).toBeGreaterThan(0));
    const lida = consulta(chamadas("/redes/1/analise/indicadores/saresp")[0]);
    expect(lida.get("etapa")).toBe("2_ano");
    expect(lida.get("componente")).toBe("lp");
  });

  it("'Escolas numa edição': sem meta (SARESP), compare com ela mesma e com a rede; com meta e só por escola (IEE), com a meta", async () => {
    semear();
    renderTela(`${ROTA}?indicador=saresp&visao=escolas&edicao=2025`, <AvaliacoesExternasRede />);
    await screen.findByTestId("indicador-escolas");
    const nota = screen.getByTestId("escolas-sem-ranking");
    expect(nota).toHaveTextContent("não é ranking");
    expect(nota).toHaveTextContent("Este indicador não tem meta: compare cada escola com ela mesma nas outras edições "
      + "(série histórica) e com a rede municipal na mesma edição.");
    expect(nota).not.toHaveTextContent("própria meta");
  });

  it("'Escolas numa edição' do IEE (com meta, só por escola): compare com a meta e com ela mesma — sem rede municipal", async () => {
    semear();
    renderTela(`${ROTA}?indicador=iee`, <AvaliacoesExternasRede />);
    await screen.findByTestId("indicador-escolas");
    const nota = screen.getByTestId("escolas-sem-ranking");
    expect(nota).toHaveTextContent("não é ranking. Compare cada escola com a sua meta e com ela mesma nas outras edições "
      + "(série histórica).");
    expect(nota).not.toHaveTextContent("rede municipal");
  });

  it("as células e a legenda do '*' sem 'decisão D2', 'reimporte' nem '1 clique'", async () => {
    semear();
    responder("GET", "/redes/1/analise/indicadores/saresp", detalheSaresp({
      filtros: { etapa: "5_ano", componente: "lp", escola_id: null, de: null, ate: null, visao: "escolas", edicao: 2025 },
      escolas: [
        linha(2, "EMEF Sintética Alfa", 219.6, { casas: 1, proveniencia: "sem_registro" }),
        linha(3, "EMEF Sintética Beta", null as unknown as number, {
          casas: null, motivo_ausencia: "estimativa_mantida_d2",
          texto_ausencia: "o número oficial não foi gravado: a estimativa do Constela foi mantida (decisão D2)" }),
        linha(5, "EMEF Sintética Delta", null as unknown as number, {
          casas: null, motivo_ausencia: "cadastrado_depois_da_importacao",
          texto_ausencia: "o código INEP foi cadastrado depois da importação; reimporte o arquivo oficial desta edição" }),
      ],
    }));
    renderTela(`${ROTA}?indicador=saresp&visao=escolas&edicao=2025`, <AvaliacoesExternasRede />);
    const escolas = await screen.findByTestId("indicador-escolas");
    const linhaDe = (nome: string) => within(escolas).getByRole("rowheader", { name: nome }).closest("tr")!;
    expect(linhaDe("EMEF Sintética Beta")).toHaveTextContent("a estimativa do Constela foi mantida");
    expect(linhaDe("EMEF Sintética Delta")).toHaveTextContent(
      "o arquivo oficial desta edição precisa ser importado de novo — quem importa é o administrador global");
    const legenda = screen.getByTestId("legenda-sem-registro");
    expect(legenda).toHaveTextContent("* número gravado antes, sem o registro do arquivo oficial.");
    expect(legenda).toHaveTextContent("não entra nos resultados da rede nos cartões.");
    expect(screen.getByTestId("avaliacoes-detalhe")).not.toHaveTextContent(/decisão D2|reimporte|1 clique|destaques|rela[çc][ãa]o/);
  });
});

describe("Avaliações externas — todas as escolas na edição mais recente de cada avaliação", () => {
  afterEach(() => vi.unstubAllGlobals());

  /** Um observador que "vê" a seção quando o teste manda (o do setup nunca vê nada). */
  function observadorQueVe() {
    const avisos: IntersectionObserverCallback[] = [];
    class Observador {
      constructor(cb: IntersectionObserverCallback) { avisos.push(cb); }
      observe() {}
      unobserve() {}
      disconnect() {}
      takeRecords() { return []; }
    }
    vi.stubGlobal("IntersectionObserver", Observador);
    return () => act(() => {
      for (const cb of avisos) cb([{ isIntersecting: true } as IntersectionObserverEntry], {} as IntersectionObserver);
    });
  }

  const secao = () => screen.getByTestId("todas-as-escolas");
  const pedirAsEscolas = async () => {
    await userEvent.click(within(await screen.findByTestId("todas-as-escolas"))
      .getByRole("button", { name: "Mostrar as escolas agora" }));
  };

  it("vem depois do detalhe, antes dos avisos; o diagnóstico só é lido quando pedido, no ano letivo; nome → ficha", async () => {
    semear();
    renderTela(ROTA, <AvaliacoesExternasRede />);
    await screen.findByTestId("indicadores-disponiveis");
    expect(within(secao()).getByRole("heading", { level: 2 }))
      .toHaveTextContent("Todas as escolas na edição mais recente de cada avaliação");
    expect(antes(screen.getByTestId("avaliacoes-detalhe"), secao())).toBe(true);
    expect(antes(secao(), screen.getByTestId("avisos-dados-oficiais"))).toBe(true);
    expect(chamadas("/redes/1/analise/diagnostico")).toEqual([]);

    await pedirAsEscolas();
    const tabela = await within(secao()).findByTestId("tabela-comparacao-escolas");
    expect(consulta(chamadas("/redes/1/analise/diagnostico")[0]).get("periodo")).toBe("ano_letivo");
    // A conclusão e a natureza de cada número à vista.
    // A edição de cada avaliação (a de referência de cada coluna), nunca "edições de 2023 a 2025".
    expect(screen.getByTestId("conclusao-escolas-avaliacoes")).toHaveTextContent(
      "3 de 4 escolas têm resultado oficial na edição mais recente de cada avaliação (IEE 2025, Ideb 2023, SARESP "
      + "2025). Em ao menos uma avaliação, 1 fica abaixo da rede municipal e 1 acima.");
    expect(screen.getByTestId("natureza-escolas").querySelector("[data-natureza=oficial]")).not.toBeNull();
    expect(screen.getByTestId("natureza-escolas").querySelector("[data-natureza=calculado]")).not.toBeNull();
    // Todas as escolas, em ordem alfabética, cada nome levando à ficha da escola.
    expect(within(tabela).getAllByRole("rowheader").map((r) => r.textContent)).toEqual([
      "EMEF Sintética Alfa", "EMEF Sintética Beta", "EMEF Sintética Delta", "EMEI Sintética Gama",
    ]);
    expect(within(tabela).getAllByRole("link").map((l) => l.getAttribute("href"))).toEqual([
      "/rede/escolas/2", "/rede/escolas/3", "/rede/escolas/5", "/rede/escolas/4",
    ]);
    await userEvent.click(within(tabela).getByRole("link", { name: "EMEF Sintética Beta" }));
    expect(screen.getByTestId("onde")).toHaveTextContent("/rede/escolas/3");
  });

  it("todas as escolas: a célula fica curta e cada explicação do servidor aparece UMA vez (cabeçalho ou notas)", async () => {
    // Os textos como o servidor escreve (services/analise/diagnostico.py), em várias escolas: antes,
    // cada célula repetia o porquê por extenso; agora ele fica uma vez, e a célula diz o curto.
    const IEE_SEM_REDE = "o IEE é um índice por escola: não existe número da rede para comparar (só a meta oficial e a tendência)";
    const INSTAVEL = "média instável (TPS = 0: participação abaixo do mínimo do SARESP): não se compara com a rede nem com a edição anterior";
    const INSTAVEL_SIMPLES = "média instável (poucos alunos fizeram a prova): não se compara com a rede nem com a edição anterior";
    const PRIMEIRA = "primeira edição com número oficial: não há anterior para comparar";
    const SAEB_SEM_REDE = "a rede municipal não tem resultado oficial do Saeb em 2023";
    const iee = (valor: number) => oficial({ indicador: "iee", rotulo: "IEE · anos iniciais", etapa: "anos_iniciais",
      componente: null, valor, casas: 2, meta: 5.0, situacao_meta: "atingiu", valor_rede: null,
      motivo_sem_comparacao: IEE_SEM_REDE, motivo_sem_tendencia: PRIMEIRA });
    const saresp = (componente: "lp" | "mt", valor: number, instavel = false) => oficial({
      componente, rotulo: `SARESP · 5º ano · ${componente.toUpperCase()}`, valor, motivo_sem_tendencia: PRIMEIRA,
      ...(instavel ? { instavel: true, motivo_sem_comparacao: INSTAVEL }
        : { diferenca_rede: Math.round((valor - 212.4) * 10) / 10,
            posicao_rede: valor > 217.4 ? "acima" as const : "na_media" as const }) });
    const saeb = () => oficial({ indicador: "saeb", rotulo: "Saeb · 5º ano · LP", edicao: 2023, valor: 210, casas: 2,
      valor_rede: null, motivo_sem_comparacao: SAEB_SEM_REDE, motivo_sem_tendencia: PRIMEIRA });
    const oficiais: Record<number, ReturnType<typeof oficial>[]> = {
      2: [iee(5.12), saresp("lp", 220.1), saresp("mt", 190.7, true), saeb()],
      3: [iee(4.8), saresp("lp", 199.0, true), saresp("mt", 214.0), saeb()],
      5: [iee(5.0), saresp("lp", 213.0), saresp("mt", 216.0)],
    };
    semear();
    const padrao = diagnostico();
    responder("GET", "/redes/1/analise/diagnostico",
              diagnostico({ escolas: padrao.escolas.map((e) => ({ ...e, oficiais: oficiais[e.id] ?? [] })) }));
    renderTela(ROTA, <AvaliacoesExternasRede />);
    await pedirAsEscolas();
    const tabela = await within(secao()).findByTestId("tabela-comparacao-escolas");
    // Cada explicação longa, uma vez na seção inteira — antes, uma por célula.
    for (const texto of [IEE_SEM_REDE, INSTAVEL_SIMPLES, PRIMEIRA, SAEB_SEM_REDE]) {
      expect((secao().textContent ?? "").split(texto)).toHaveLength(2);
    }
    // O porquê da coluna toda (o IEE; a rede sem o Saeb de 2023) fica no cabeçalho da coluna.
    const notaNoCabecalho = (nome: string) => within(tabela).getAllByRole("columnheader")
      .find((th) => th.querySelector("[data-nome-coluna]")?.textContent === nome)!.querySelector("[data-nota-coluna]");
    expect(notaNoCabecalho("IEE")).toHaveTextContent("sem comparação com a rede (obs. 1)");
    expect(notaNoCabecalho("Saeb 5º ano · LP")).toHaveTextContent("sem comparação com a rede (obs. 2)");
    expect(notaNoCabecalho("SARESP 5º ano · LP")).toBeNull();
    // A célula: o essencial curto. A média instável é o selo + a falta com a nota (a mesma nas duas).
    const celulas = (escola: string) =>
      within(within(tabela).getByRole("rowheader", { name: escola }).closest("tr")!).getAllByRole("cell");
    const [ieeAlfa, lpAlfa, mtAlfa] = celulas("EMEF Sintética Alfa");
    expect(ieeAlfa).toHaveTextContent(/^5,122025meta 5,00atingiu a meta$/);
    expect(lpAlfa).toHaveTextContent(/^220,12025▲acima da rede\(\+7,7; rede 212,4\)$/);
    expect(mtAlfa).toHaveTextContent(/^190,72025média instávelsem comparação com a rede \(obs\. 3\)$/);
    expect(celulas("EMEF Sintética Beta")[1]).toHaveTextContent(/^199,02025média instávelsem comparação com a rede \(obs\. 3\)$/);
    // A ausência continua por extenso, em cada célula.
    expect(celulas("EMEF Sintética Delta")[3]).toHaveTextContent("sem resultado oficial");
    expect(within(tabela).getAllByText("sem código INEP no cadastro")).toHaveLength(4);
    expect(within(screen.getByTestId("notas-comparacao")).getAllByRole("listitem").map((li) => li.textContent)).toEqual([
      `Obs. 1 — ${IEE_SEM_REDE}.`, `Obs. 2 — ${SAEB_SEM_REDE}.`, `Obs. 3 — ${INSTAVEL_SIMPLES}.`,
      `Célula sem linha de tendência — ${PRIMEIRA}.`,
    ]);
    expect(secao()).not.toHaveTextContent("sem tendência");
    semJargao(secao());
    semCausalidade(secao());
  });

  it("chegar perto da seção (rolando) carrega a tabela sem clique", async () => {
    semear();
    const ver = observadorQueVe();
    renderTela(ROTA, <AvaliacoesExternasRede />);
    await screen.findByTestId("escolas-a-carregar");
    expect(chamadas("/redes/1/analise/diagnostico")).toEqual([]);
    ver();
    expect(await within(secao()).findByTestId("tabela-comparacao-escolas")).toBeInTheDocument();
    expect(chamadas("/redes/1/analise/diagnostico")).toHaveLength(1);
    expect(screen.queryByTestId("escolas-a-carregar")).toBeNull();
  });

  it("enquanto o diagnóstico não chega, a seção diz 'carregando' e o resto da página já funciona", async () => {
    semear();
    responder("GET", "/redes/1/analise/diagnostico", () => new Promise(() => undefined));
    vi.spyOn(Element.prototype, "scrollIntoView").mockImplementation(() => undefined);
    renderTela(ROTA, <AvaliacoesExternasRede />);
    await pedirAsEscolas();
    expect(within(secao()).getByText("Carregando as escolas...")).toBeInTheDocument();
    // Os cartões e o detalhe não esperam pela tabela.
    await userEvent.click(screen.getByRole("button", { name: "Ver série histórica e escolas — SARESP" }));
    expect(await within(screen.getByTestId("avaliacoes-detalhe")).findByTestId("indicador-tabela")).toHaveTextContent("212,4");
  });

  it("se o diagnóstico falha, a seção diz o erro e o resto da página continua", async () => {
    semear();
    responderErro("GET", "/redes/1/analise/diagnostico", 500, "FALHA-DIAG");
    renderTela(ROTA, <AvaliacoesExternasRede />);
    await pedirAsEscolas();
    expect(await within(secao()).findByText("Não foi possível carregar as escolas: FALHA-DIAG")).toBeInTheDocument();
    expect(screen.getByTestId("indicadores-disponiveis")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Arquivos oficiais de cada número/ })).toBeInTheDocument();
  });

  it("admin global: o link da ficha leva o ?rede= da rede escolhida", async () => {
    semear();
    responder("GET", "/redes", [{ id: 1, nome: "Rede Sintética Norte" }, { id: 2, nome: "Rede Sintética Sul" }]);
    renderTela(`${ROTA}?rede=1`, <AvaliacoesExternasRede />, { usuario: admin });
    await pedirAsEscolas();
    const tabela = await within(secao()).findByTestId("tabela-comparacao-escolas");
    expect(within(tabela).getByRole("link", { name: "EMEF Sintética Alfa" })).toHaveAttribute("href", "/rede/escolas/2?rede=1");
    // O global continua com o nome de sempre para a tela onde ele importa.
    expect(screen.getByRole("link", { name: /Importações e fontes/ })).toHaveAttribute("href", "/rede/avaliacoes");
  });

  it("rede sem nenhum resultado oficial: a frase diz por quê e todas as escolas continuam listadas, cada uma com o que falta", async () => {
    semear();
    const padrao = diagnostico();
    responder("GET", "/redes/1/analise/diagnostico",
              diagnostico({ escolas: padrao.escolas.map((e) => ({ ...e, oficiais: [], sinais: [] })) }));
    // Nenhuma avaliação por escola importada: só o ICA (da rede) está disponível.
    const c = catalogo();
    responder("GET", "/redes/1/analise/indicadores", catalogo({
      indicadores: c.indicadores.map((i) => (i.chave === "ica" ? i : {
        ...i, disponivel: false, motivo_indisponivel: "sem_importacao", edicoes: [], edicao_mais_recente: null })),
      destaques: c.destaques.filter((d) => d.indicador === "ica"),
    }));
    const { container } = renderTela(ROTA, <AvaliacoesExternasRede />);
    await pedirAsEscolas();
    const vazia = await within(secao()).findByTestId("comparacao-vazia");
    expect(vazia).toHaveTextContent("Nenhuma escola da rede tem resultado oficial importado ainda: nenhuma avaliação com "
      + "resultado por escola (IEE, Ideb, SARESP ou Saeb) foi importada para esta rede.");
    expect(screen.queryByTestId("tabela-comparacao-escolas")).toBeNull();
    // A conclusão não repete a frase (a própria seção já explica).
    expect(screen.queryByTestId("conclusao-escolas-avaliacoes")).toBeNull();
    const lista = within(vazia).getByTestId("escolas-sem-resultado");
    expect(within(lista).getAllByRole("listitem").map((li) => li.textContent)).toEqual([
      "EMEF Sintética Alfasem resultado oficial importado", "EMEF Sintética Betasem resultado oficial importado",
      "EMEF Sintética Deltasem resultado oficial importado", "EMEI Sintética Gamasem código INEP no cadastro",
    ]);
    expect(within(lista).getByRole("link", { name: "EMEI Sintética Gama" })).toHaveAttribute("href", "/rede/escolas/4");
    // Ausência por extenso: nenhum número no lugar do "sem resultado".
    expect(lista).not.toHaveTextContent(/\d/);
    semJargao(container);
    semCausalidade(container);
  });

  it("com o detalhe e a seção abertos, a página inteira fica sem termo técnico nem palavra causal", async () => {
    semear();
    vi.spyOn(Element.prototype, "scrollIntoView").mockImplementation(() => undefined);
    const { container } = renderTela(`${ROTA}?indicador=saresp&visao=escolas&edicao=2025`, <AvaliacoesExternasRede />);
    await screen.findByTestId("indicador-escolas");
    await pedirAsEscolas();
    await within(secao()).findByTestId("tabela-comparacao-escolas");
    await userEvent.click(within(screen.getByTestId("avisos-dados-oficiais")).getByRole("button"));
    await userEvent.click(within(screen.getByTestId("metodologia-resumo")).getByRole("button"));
    semJargao(container);
    semCausalidade(container);
    expect(container).not.toHaveTextContent(/Análises avançadas|Relatórios/);
  });
});

describe("Avaliações externas — o detalhe na língua simples (os textos do servidor)", () => {
  it("'Fora da comparação': o motivo do servidor sai sem termo técnico", async () => {
    semear();
    const padrao = detalheSaresp();
    responder("GET", "/redes/1/analise/indicadores/saresp", detalheSaresp({
      series: [...padrao.series,
        { id: "contexto_estadual", rotulo: "Estado sintético — rede estadual", papel: "contexto", abrangencia: "uf",
          escola_id: null, rede_ensino: "estadual", mesma_rede: false, comparavel: false,
          motivo_nao_comparavel: "Série de outra edição/coorte (TPS = 0 em parte das escolas): só contexto (texto sintético).",
          pontos: [ponto(2025, 205.0)] }],
    }));
    renderTela(`${ROTA}?indicador=saresp`, <AvaliacoesExternasRede />);
    const fora = await screen.findByTestId("fora-da-comparacao");
    expect(fora).toHaveTextContent("Estado sintético — rede estadual — Série de outra edição (outro grupo de alunos) "
      + "(poucos alunos fizeram a prova): só contexto (texto sintético).");
    semJargao(fora);
  });

  it("indicador indisponível dentro do detalhe: o motivo na língua simples; sem `simples`, o texto do servidor de sempre", async () => {
    const c = catalogo({
      indicadores: catalogo().indicadores.map((i) => (i.chave !== "saeb" ? i : {
        ...i, motivo_indisponivel: "so_sem_registro",
        texto_indisponivel: "só há números gravados antes, sem o registro do arquivo oficial: importe o arquivo oficial "
          + "desta edição" })),
    });
    const Detalhe = ({ simples }: { simples?: boolean }) => (
      <PorIndicador redeId={1} base={c} params={new URLSearchParams("indicador=saeb")} atualizar={() => undefined}
                    escolaId={null} simples={simples} />
    );
    const { unmount } = renderComApp(<Detalhe simples />, { usuario: secretaria });
    expect(await screen.findByTestId("indicador-indisponivel")).toHaveTextContent(
      "Saeb: só há números gravados antes, sem o registro do arquivo oficial: falta importar o arquivo oficial desta "
      + "edição — quem importa é o administrador global.");
    unmount();
    // A área avançada (sem `simples`) continua com o texto do servidor.
    renderComApp(<Detalhe />, { usuario: secretaria });
    expect(await screen.findByTestId("indicador-indisponivel"))
      .toHaveTextContent("Saeb: só há números gravados antes, sem o registro do arquivo oficial: importe o arquivo oficial desta edição.");
    expect(chamadas("/redes/1/analise/indicadores/saeb")).toEqual([]);
  });
});

describe("Avaliações externas — as tabelas do detalhe no celular e o nome que leva à ficha", () => {
  /** A moldura mede 300 px e a tabela pede 800: há colunas escondidas à direita. */
  function tabelaLarga() {
    vi.spyOn(Element.prototype, "clientWidth", "get").mockReturnValue(300);
    vi.spyOn(Element.prototype, "scrollWidth", "get").mockReturnValue(800);
  }

  it("escolas numa edição: rola no cartão com o aviso, a escola fica presa à esquerda e o nome leva à ficha", async () => {
    semear();
    responder("GET", "/redes/1/analise/indicadores/saresp", detalheSaresp({
      filtros: { etapa: "5_ano", componente: "lp", escola_id: null, de: null, ate: null, visao: "escolas", edicao: 2025 },
    }));
    tabelaLarga();
    renderTela(`${ROTA}?indicador=saresp&visao=escolas&edicao=2025`, <AvaliacoesExternasRede />);
    const escolas = await screen.findByTestId("indicador-escolas");
    expect(screen.getByRole("region", { name: "SARESP 2025 por escola: tabela completa" })).toContainElement(escolas);
    expect(within(screen.getByTestId("avaliacoes-detalhe")).getByText(/Deslize a tabela para o lado/)).toBeInTheDocument();
    expect(within(escolas).getByRole("columnheader", { name: "Escola" })).toHaveClass("presa-esquerda-celular");
    const alfa = within(escolas).getByRole("rowheader", { name: "EMEF Sintética Alfa" });
    expect(alfa).toHaveClass("presa-esquerda-celular");
    expect(within(alfa).getByRole("link", { name: "EMEF Sintética Alfa" })).toHaveAttribute("href", "/rede/escolas/2");
    await userEvent.click(within(escolas).getByRole("link", { name: "EMEF Sintética Beta" }));
    expect(screen.getByTestId("onde")).toHaveTextContent("/rede/escolas/3");
  });

  it("série histórica: rola no cartão com o aviso e o ano fica preso à esquerda", async () => {
    semear();
    tabelaLarga();
    renderTela(`${ROTA}?indicador=saresp`, <AvaliacoesExternasRede />);
    const tabela = await screen.findByTestId("indicador-tabela");
    expect(screen.getByRole("region", { name: "SARESP — 5º ano · Língua Portuguesa: tabela completa" }))
      .toContainElement(tabela);
    expect(within(tabela).getByRole("columnheader", { name: "Ano" })).toHaveClass("presa-esquerda-celular");
    expect(within(tabela).getByRole("rowheader", { name: "2025" })).toHaveClass("presa-esquerda-celular");
  });

  it("admin global: o nome da escola numa edição leva à ficha com o ?rede= da rede escolhida", async () => {
    semear();
    responder("GET", "/redes", [{ id: 1, nome: "Rede Sintética Norte" }, { id: 2, nome: "Rede Sintética Sul" }]);
    renderTela(`${ROTA}?rede=1&indicador=saresp&visao=escolas&edicao=2025`, <AvaliacoesExternasRede />, { usuario: admin });
    const escolas = await screen.findByTestId("indicador-escolas");
    expect(within(escolas).getByRole("link", { name: "EMEF Sintética Alfa" })).toHaveAttribute("href", "/rede/escolas/2?rede=1");
  });

  it("a área avançada (sem `simples`) não muda: a moldura de sempre, sem coluna presa nem link", async () => {
    semear();
    tabelaLarga();
    const Detalhe = ({ consultaUrl }: { consultaUrl: string }) => (
      <PorIndicador redeId={1} base={catalogo()} params={new URLSearchParams(consultaUrl)} atualizar={() => undefined}
                    escolaId={null} />
    );
    const { unmount } = renderComApp(<Detalhe consultaUrl="indicador=saresp&visao=escolas&edicao=2025" />,
                                     { usuario: secretaria });
    const escolas = await screen.findByTestId("indicador-escolas");
    expect(screen.queryByRole("region", { name: /tabela completa/ })).toBeNull();
    expect(screen.queryByText(/Deslize a tabela/)).toBeNull();
    expect(within(escolas).getByRole("columnheader", { name: "Escola" })).not.toHaveClass("presa-esquerda-celular");
    expect(within(escolas).getByRole("rowheader", { name: "EMEF Sintética Alfa" })).not.toHaveClass("presa-esquerda-celular");
    expect(within(escolas).queryAllByRole("link")).toEqual([]);
    unmount();
    renderComApp(<Detalhe consultaUrl="indicador=saresp" />, { usuario: secretaria });
    const tabela = await screen.findByTestId("indicador-tabela");
    expect(screen.queryByRole("region", { name: /tabela completa/ })).toBeNull();
    expect(within(tabela).getByRole("columnheader", { name: "Ano" })).not.toHaveClass("presa-esquerda-celular");
  });
});
