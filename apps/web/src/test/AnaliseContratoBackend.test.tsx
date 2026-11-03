/**
 * Análise educacional × as respostas REAIS do backend (frente B): os exemplos de
 * `fixtures/analise/*.json` são gravados por `backend/tests/test_analise_fixtures.py`
 * pelas mesmas rotas que a tela chama (mundos INVENTADOS — D13). Aqui as telas os
 * consomem sem adaptação: se a forma da API mudar, o teste do backend regrava os
 * exemplos e estes testes acusam o que a tela deixou de entender.
 *
 * As Análises avançadas (`/rede/analise`) ficaram com o Diagnóstico, a Relação e a análise
 * por escola. O que a antiga Visão geral e a aba "Avaliações externas" mostravam mora hoje nas
 * telas da Secretaria: os avisos do catálogo, as notas e a metodologia em Avaliações externas;
 * as lacunas por série em Elefante e Matific — conferidos NESSAS telas, com as respostas reais;
 * os cartões das plataformas e o detalhe de um indicador, direto nos componentes
 * (`AnaliseHarness`).
 */
import { describe, expect, it } from "vitest";

import AnaliseDaEscola from "../pages/analise/AnaliseDaEscola";
import AnaliseEducacional from "../pages/analise/AnaliseEducacional";
import type { RespostaPlataformas } from "../pages/analise/tipos";
import AvaliacoesExternasRede from "../pages/rede/secretaria/AvaliacoesExternasRede";
import PlataformasRedePagina from "../pages/rede/secretaria/PlataformasRedePagina";
import { IndicadorEmDetalhe, PlataformasNoPeriodo } from "./AnaliseHarness";
import erroIcaPorEscola from "./fixtures/analise/erro_ica_por_escola.json";
import escola from "./fixtures/analise/escola.json";
import escolaSemInep from "./fixtures/analise/escola_sem_inep.json";
import indicadorIca from "./fixtures/analise/indicador_ica.json";
import indicadorIdeb from "./fixtures/analise/indicador_ideb.json";
import indicadorIdebEscolas from "./fixtures/analise/indicador_ideb_escolas.json";
import indicadorIeeEscolas from "./fixtures/analise/indicador_iee_escolas.json";
import indicadorSarespEscola from "./fixtures/analise/indicador_saresp_escola.json";
import indicadorSarespEscolas from "./fixtures/analise/indicador_saresp_escolas.json";
import indicadorSarespSerie from "./fixtures/analise/indicador_saresp_serie.json";
import indicadores from "./fixtures/analise/indicadores.json";
import plataformas from "./fixtures/analise/plataformas.json";
import relacaoCalculavel from "./fixtures/analise/relacao_calculavel.json";
import relacaoNaoCalculavel from "./fixtures/analise/relacao_nao_calculavel.json";
import {
  api, renderComApp, responder, responderErro, screen, userEvent, usuarioFake, waitFor, within,
} from "./utils";

const secretaria = usuarioFake({ nome: "Secretaria", cargo: "coordenador", rede_id: 1, escola_id: null });
const coordenador = usuarioFake({ nome: "Coordenadora", cargo: "coordenador", escola_id: 2 });

const chamadas = (prefixo: string) => api.mock.calls.map(([c]) => String(c)).filter((c) => c.startsWith(prefixo));
const query = (url: string) => new URLSearchParams(url.split("?")[1] ?? "");

function semear() {
  responder("GET", "/redes/1/analise/indicadores", indicadores);
  responder("GET", "/redes/1/analise/plataformas", plataformas);
}

describe("Contrato com o backend — rede", () => {
  it("Avaliações externas: a conclusão de cada cartão vem dos destaques da API — só número oficial", async () => {
    semear();
    renderComApp(<AvaliacoesExternasRede />, { rota: "/rede/avaliacoes-externas", usuario: secretaria });
    // Os destaques (que moravam na antiga Visão geral) são a conclusão dos cartões: valor, edição e meta.
    expect(await screen.findByTestId("indicador-conclusao-ica")).toHaveTextContent("Rede em 2025: 58% — abaixo da meta de 60%.");
    expect(screen.getByTestId("indicador-conclusao-saresp")).toHaveTextContent("201,4");
    expect(screen.getByTestId("indicador-conclusao-ideb")).toHaveTextContent("Rede em 2023: 6,1");
    expect(screen.getByTestId("indicador-conclusao-saeb")).toHaveTextContent("210,00");
    // O IEE não tem número da rede: o cartão diz que é por escola (nunca um 0 ou um vazio mudo).
    expect(screen.getByTestId("indicador-conclusao-iee")).toHaveTextContent("Por escola: cada escola tem o seu resultado");
    // O número gravado sem o registro do arquivo oficial (o 7,7 do Ideb) nunca vira resultado da rede.
    expect(screen.getByTestId("indicadores-disponiveis")).not.toHaveTextContent("7,7");
  });

  it("Avaliações externas: os avisos do catálogo, as notas da Estimativa e do sem registro e a metodologia, como a API manda", async () => {
    semear();
    renderComApp(<AvaliacoesExternasRede />, { rota: "/rede/avaliacoes-externas", usuario: secretaria });
    // A Estimativa Constela e o número sem registro oficial vêm separados, cada um rotulado.
    const estimativas = await screen.findByTestId("estimativas-fora");
    expect(estimativas).toHaveTextContent("Estimativa Constela");
    expect(estimativas).not.toHaveTextContent("sem o registro");
    expect(screen.getByTestId("sem-registro-fora"))
      .toHaveTextContent("IDEB — números gravados antes, sem o registro do arquivo oficial (2023)");
    // Os avisos (recolhidos): o cadastro sem INEP nomeia a escola; nenhum nome de arquivo.
    await userEvent.click(within(screen.getByTestId("avisos-dados-oficiais")).getByRole("button"));
    const alertas = screen.getByTestId("alertas-analise");
    expect(alertas).toHaveTextContent("sem código INEP no cadastro");
    expect(alertas).toHaveTextContent("EMEF Fictícia Gama");
    expect(alertas).toHaveTextContent("Sem registro oficial: IDEB 2023");
    expect(alertas).not.toHaveTextContent(/\.zip|\.xlsx/);
    // A metodologia em linguagem simples (da API), recolhida.
    await userEvent.click(within(screen.getByTestId("metodologia-resumo")).getByRole("button"));
    expect(screen.getByTestId("metodologia-resumo")).toHaveTextContent("Sem resultado não é zero");
  });

  it("os cartões e a cobertura das plataformas, como a API manda (denominador, quem fica fora, sem coleta)", async () => {
    renderComApp(<PlataformasNoPeriodo dados={plataformas as unknown as RespostaPlataformas}
                                       escolas={indicadores.escolas} />, { usuario: secretaria });
    // O "X de Y" com o MESMO denominador do percentual: 5 de 7 = 71,4% (não "de 25", o
    // total do recorte com as escolas sem coleta e as séries suprimidas).
    const elefante = await screen.findByTestId("plataforma-elefante");
    expect(elefante).toHaveTextContent("71,4%");
    expect(elefante).toHaveTextContent("5 de 7 alunos com conta leram no período");
    expect(elefante).not.toHaveTextContent("de 25 alunos com conta");
    expect(screen.getByTestId("fora-da-conta-elefante")).toHaveTextContent("18 de 25 alunos do recorte não entram");
    expect(elefante).toHaveTextContent("1,14");
    expect(elefante).toHaveTextContent("medido de 01/03/2026 a 30/09/2026");
    const matific = screen.getByTestId("plataforma-matific");
    expect(matific).toHaveTextContent("100%");
    expect(matific).toHaveTextContent("sobre 14 alunos com dado no período");
    expect(matific).toHaveTextContent("19,71");
    expect(screen.getByTestId("texto-blocos")).toHaveTextContent("somam só as escolas e as séries mostradas");
    expect(screen.getByTestId("cobertura-coletas"))
      .toHaveTextContent("Elefante sem coleta que cubra o período: EMEF Fictícia Beta");
  });

  it("Elefante e Matific: lacunas por série com o exemplo real (as séries suprimidas da Alfa, o Elefante que falta na Beta)", async () => {
    semear();
    renderComApp(<PlataformasRedePagina />, { rota: "/rede/plataformas", usuario: secretaria });
    await userEvent.click(within(await screen.findByTestId("sobre-os-dados")).getByRole("button"));
    const linhas = within(await screen.findByTestId("tabela-lacunas-serie")).getAllByRole("row").slice(1);
    expect(linhas[1]).toHaveTextContent("2º ano1 (1 com a série oculta: poucos alunos)");
    expect(linhas[2]).toHaveTextContent("3º ano1"); // a Alfa, visível
    expect(linhas[4]).toHaveTextContent("0 de 1 · falta em 1"); // 5º ano: a Beta sem Elefante
    expect(linhas[4]).toHaveTextContent("SARESP; SAEB");
  });

  it("a escola sem aluno no recorte diz o motivo (não zero)", async () => {
    renderComApp(<PlataformasNoPeriodo dados={plataformas as unknown as RespostaPlataformas}
                                       escolas={indicadores.escolas} escolaId={6} />, { usuario: secretaria });
    expect(await screen.findByTestId("plataforma-elefante"))
      .toHaveTextContent("nenhum aluno ativo do 1º ao 5º ano matriculado no ano letivo");
    expect(screen.getByTestId("plataforma-matific")).not.toHaveTextContent(/\b0,0\b|\b0%/);
  });

  it("ICA: o empate é inconclusivo, a ausência tem motivo, SP/Brasil (outra rede) ficam fora da comparação", async () => {
    semear();
    responder("GET", "/redes/1/analise/indicadores/ica", indicadorIca);
    // Se a tela pedisse o ICA por escola, receberia a recusa — ela não pede.
    responder("GET", (c) => c.startsWith("/redes/1/analise/indicadores/ica") && c.includes("escola_id"),
      () => { throw new Error(erroIcaPorEscola.detail); });
    renderComApp(<IndicadorEmDetalhe />, {
      rota: "/rede/avaliacoes-externas?indicador=ica&abrangencia=escola&escola=2", usuario: secretaria });
    const linhas = within(await screen.findByTestId("indicador-tabela")).getAllByRole("row");
    expect(linhas[1]).toHaveTextContent(/2025.*58%.*60%.*−2 p\.p\..*não atingiu/);
    expect(linhas[2]).toHaveTextContent(/2024.*55%.*55%.*inconclusivo/);
    expect(linhas[3]).toHaveTextContent("sem resultado: participação abaixo de 70%");
    expect(screen.getByTestId("fora-da-comparacao")).toHaveTextContent("rede pública");
    expect(chamadas("/redes/1/analise/indicadores/ica").every((c) => !query(c).has("escola_id"))).toBe(true);
    expect(screen.getByTestId("motivo-sem-escola")).toHaveTextContent("O ICA é da rede: não existe por escola.");
  });

  it("SARESP: a série da rede, a de uma escola (com as quebras do 2º ano) e a visão por escolas", async () => {
    semear();
    responder("GET", "/redes/1/analise/indicadores/saresp", indicadorSarespSerie);
    responder("GET", (c) => c.startsWith("/redes/1/analise/indicadores/saresp") && c.includes("escola_id=2"),
      indicadorSarespEscola);
    responder("GET", (c) => c.startsWith("/redes/1/analise/indicadores/saresp") && c.includes("visao=escolas"),
      indicadorSarespEscolas);
    renderComApp(<IndicadorEmDetalhe />, { rota: "/rede/avaliacoes-externas?indicador=saresp", usuario: secretaria });
    expect(await screen.findByTestId("indicador-tabela")).toHaveTextContent("201,4");

    // Uma escola: a ausência por extenso e as quebras do 2º ano nos avisos.
    await userEvent.selectOptions(screen.getByLabelText("Escola"), "2");
    await userEvent.click(await screen.findByRole("radio", { name: "Escola do filtro: EMEF Fictícia Alfa" }));
    const tabela = await screen.findByTestId("indicador-tabela");
    await waitFor(() => expect(tabela).toHaveTextContent("não divulgado no arquivo oficial"));
    expect(screen.getByTestId("avisos-comparabilidade")).toHaveTextContent("Possível quebra de escala no 2º ano");

    // Visão por escolas: ordem de nome, instável marcada, sem INEP com o motivo.
    await userEvent.click(screen.getByRole("radio", { name: "Escolas numa edição" }));
    const escolas = await screen.findByTestId("indicador-escolas");
    const nomes = within(escolas).getAllByRole("rowheader").map((th) => th.textContent);
    expect(nomes).toEqual(["EMEF Ébano Fictícia", "EMEF Fictícia Alfa", "EMEF Fictícia Beta", "EMEF Fictícia Delta",
                           "EMEF Fictícia Gamasem código INEP"]);
    const linhas = within(escolas).getAllByRole("row").slice(1);
    expect(linhas[2]).toHaveTextContent("média instável (TPS = 0)");
    expect(linhas[3]).toHaveTextContent("a escola não está no arquivo oficial importado desta edição");
    expect(linhas[4]).toHaveTextContent("a escola está sem código INEP no cadastro");
  });

  it("Ideb: metas só até 2021 (o texto da API) e o IEE por escola com a meta", async () => {
    semear();
    responder("GET", "/redes/1/analise/indicadores/ideb", indicadorIdeb);
    responder("GET", "/redes/1/analise/indicadores/iee", indicadorIeeEscolas);
    renderComApp(<IndicadorEmDetalhe />, { rota: "/rede/avaliacoes-externas?indicador=ideb", usuario: secretaria });
    const linhas = within(await screen.findByTestId("indicador-tabela")).getAllByRole("row");
    expect(linhas[1]).toHaveTextContent("o INEP não definiu meta do Ideb depois de 2021");
    expect(linhas[3]).toHaveTextContent(/2019.*5,8.*5,8.*atingiu a meta/);

    // O IEE é só por escola: sem escola escolhida, abre direto nas escolas da edição.
    await userEvent.click(screen.getByRole("radio", { name: /IEE/ }));
    const escolas = await screen.findByTestId("indicador-escolas");
    expect(query(chamadas("/redes/1/analise/indicadores/iee")[0]).get("visao")).toBe("escolas");
    expect(escolas).toHaveTextContent("5,12");
    // Na série histórica, a rede fica desabilitada com o motivo (não há IEE da rede).
    await userEvent.click(screen.getByRole("radio", { name: "Série histórica" }));
    expect(await screen.findByTestId("motivo-so-escola")).toHaveTextContent("é por escola");
    expect(screen.getByRole("radio", { name: "Rede municipal" })).toBeDisabled();
    expect(await screen.findByTestId("indicador-sem-serie")).toHaveTextContent("escolha uma escola");
  });

  it("relação não calculável (SARESP 2025 × plataformas 2026): o motivo e os pares lado a lado", async () => {
    semear();
    responder("GET", "/redes/1/analise/relacao", relacaoNaoCalculavel);
    renderComApp(<AnaliseEducacional />, {
      rota: "/rede/analise?ver=relacao&indicador=saresp&componente=mt&metrica=estrelas_por_aluno", usuario: secretaria });
    expect(await screen.findByTestId("relacao-nao-calculavel")).toHaveTextContent("Período sem sobreposição");
    const q = query(chamadas("/redes/1/analise/relacao")[0]);
    expect(q.get("componente")).toBe("mt");
    expect(q.get("metrica")).toBe("estrelas_por_aluno");
    const lado = screen.getByTestId("relacao-lado-a-lado");
    const beta = within(lado).getByRole("rowheader", { name: "EMEF Fictícia Beta" }).closest("tr")!;
    expect(beta).toHaveTextContent(/199,0.*2025.*12.*2026/);
    const delta = within(lado).getByRole("rowheader", { name: "EMEF Fictícia Delta" }).closest("tr")!;
    expect(delta).toHaveTextContent("a escola não está no arquivo oficial importado desta edição");
    expect(delta).toHaveTextContent("sem dado no período");
    // Cada escola com o motivo PRÓPRIO (mesmo com o motivo geral do período); a média
    // instável aparece marcada ao lado do número oficial.
    expect(beta).toHaveTextContent("não: média instável (TPS = 0");
    expect(within(beta).getAllByRole("cell")[0]).toHaveTextContent("199,0média instável");
    const alfa = within(lado).getByRole("rowheader", { name: "EMEF Fictícia Alfa" }).closest("tr")!;
    expect(alfa).toHaveTextContent("não: célula suprimida: poucos alunos neste recorte");
    expect(lado).not.toHaveTextContent("fica de fora pelo motivo geral");
    // O texto do motivo geral não repete o ano letivo.
    expect(screen.getByTestId("relacao-nao-calculavel")).not.toHaveTextContent("(ano letivo 2026)");
    // A lista de métricas vem da API (as mesmas chaves do backend), sem "retrato".
    expect(screen.getByRole("option", { name: "Estrelas por aluno com dado no período (Matific)" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /retrato/ })).not.toBeInTheDocument();
    expect(screen.queryByTestId("relacao-coeficiente")).not.toBeInTheDocument();
    // A metodologia é o texto da API, legível (sem caminho de arquivo do repositório).
    expect(screen.getByTestId("relacao-metodologia")).toHaveTextContent("Unidade: a escola.");
    expect(screen.getByTestId("relacao-metodologia")).not.toHaveTextContent(/docs\/|\.md\b/);
    expect(screen.getByTestId("relacao-criterios")).toHaveTextContent("Coleta da plataforma em dia no período: sim");
  });

  it("relação calculável (cenário sintético do mesmo ano): coeficiente, IC 95% e n", async () => {
    const segunda = usuarioFake({ nome: "Secretaria 2", cargo: "coordenador", rede_id: 2, escola_id: null });
    const base2 = {
      ...indicadores, rede: { ...indicadores.rede, id: 2 },
      indicadores: indicadores.indicadores.map((i) => (i.chave === "saresp" ? { ...i, edicoes: [2025, 2026] } : i)),
    };
    responder("GET", "/redes/2/analise/indicadores", base2);
    responder("GET", "/redes/2/analise/plataformas", plataformas);
    responder("GET", "/redes/2/analise/relacao", relacaoCalculavel);
    renderComApp(<AnaliseEducacional />, {
      rota: "/rede/analise?ver=relacao&indicador=saresp&etapa=5_ano&componente=lp&edicao=2026&metrica=livros_por_aluno",
      usuario: segunda });
    expect(await screen.findByTestId("relacao-coeficiente"))
      .toHaveTextContent("Coeficiente de Spearman: 0,97 · IC 95%: 0,83 a 0,99 · n = 9 escolas");
    expect(query(chamadas("/redes/2/analise/relacao")[0]).get("edicao")).toBe("2026");
    expect(screen.getByTestId("relacao-interpretacao")).toHaveTextContent("tendem a ter");
    // O aviso de causalidade fica na caixa fixa — a interpretação não o repete.
    expect(screen.getByTestId("relacao-interpretacao")).not.toHaveTextContent(/causalidade/i);
    expect(screen.getByTestId("relacao-dispersao")).toBeInTheDocument();
    expect(screen.getByTestId("aviso-causalidade")).toHaveTextContent("Correlação não é causalidade");
  });

  it("Ideb por escola: o número sem registro oficial aparece marcado (*), com a legenda — não é estimativa", async () => {
    semear();
    responder("GET", "/redes/1/analise/indicadores/ideb", indicadorIdebEscolas);
    renderComApp(<IndicadorEmDetalhe />, {
      rota: "/rede/avaliacoes-externas?indicador=ideb&visao=escolas&edicao=2023", usuario: secretaria });
    const escolas = await screen.findByTestId("indicador-escolas");
    const delta = within(escolas).getByRole("rowheader", { name: "EMEF Fictícia Delta" }).closest("tr")!;
    expect(delta).toHaveTextContent("7,7*");
    expect(delta.querySelector("[data-proveniencia=sem_registro]"))
      .toHaveAttribute("title", "número gravado antes, sem o registro do arquivo oficial");
    const alfa = within(escolas).getByRole("rowheader", { name: "EMEF Fictícia Alfa" }).closest("tr")!;
    expect(alfa).toHaveTextContent("6,3");
    expect(alfa).not.toHaveTextContent("*");
    const legenda = screen.getByTestId("legenda-sem-registro");
    expect(legenda).toHaveTextContent("* número gravado antes, sem o registro do arquivo oficial");
    expect(legenda).toHaveTextContent("Não é a Estimativa Constela");
    // A meta que não existe diz por quê (não um "—" mudo).
    expect(delta).toHaveTextContent("o INEP não definiu meta do Ideb depois de 2021");
  });

  it("IEE por escola: o índice calculado com médias de TPS = 0 aparece marcado", async () => {
    semear();
    responder("GET", "/redes/1/analise/indicadores/iee", indicadorIeeEscolas);
    renderComApp(<IndicadorEmDetalhe />, { rota: "/rede/avaliacoes-externas?indicador=iee", usuario: secretaria });
    const escolas = await screen.findByTestId("indicador-escolas");
    const beta = within(escolas).getByRole("rowheader", { name: "EMEF Fictícia Beta" }).closest("tr")!;
    expect(beta).toHaveTextContent("calculado com médias de TPS = 0");
    const alfa = within(escolas).getByRole("rowheader", { name: "EMEF Fictícia Alfa" }).closest("tr")!;
    expect(alfa).not.toHaveTextContent("TPS = 0");
  });
});

describe("Contrato com o backend — escola", () => {
  it("a análise de uma escola: SARESP por etapa e componente, a rede de referência e as plataformas por série", async () => {
    responder("GET", "/escolas/2/analise", escola);
    renderComApp(<AnaliseDaEscola escolaId={2} />, { usuario: coordenador });
    const saresp = await screen.findByTestId("analise-escola-indicador-saresp");
    expect(saresp).toHaveTextContent("5º ano · Língua Portuguesa");
    expect(saresp).toHaveTextContent("2º ano · Matemática");
    expect(saresp).toHaveTextContent("210,3");
    const saeb = screen.getByTestId("analise-escola-indicador-saeb");
    expect(saeb).toHaveTextContent("sem resultado nesta edição");
    expect(saeb).toHaveTextContent("218,31");
    // A rede não tem Saeb 2023: a célula diz isso por extenso (não um "—" mudo).
    const referencias = within(saeb).getAllByRole("rowheader")
      .filter((th) => /referência/.test(th.textContent ?? "")).map((th) => th.closest("tr")!);
    expect(referencias).toHaveLength(2);
    for (const tr of referencias) expect(tr).toHaveTextContent("sem resultado nesta edição");
    // Meta e diferença em TODA série com meta — inclusive o ICA, que só chega como referência.
    const ica = screen.getByTestId("analise-escola-indicador-ica");
    expect(ica).toHaveTextContent("58%");
    expect(ica).toHaveTextContent("meta 60% · −2 p.p. · não atingiu a meta");
    expect(screen.getByTestId("analise-escola-indicador-iee")).toHaveTextContent("meta 5,46 · −0,34 · não atingiu a meta");
    // Supressão com o motivo ÚNICO: a célula pequena e a escondida junto dizem o mesmo.
    const tabela = screen.getByTestId("tabela-series-plataformas");
    const suprimidas = within(tabela).getAllByText(/poucos alunos neste recorte \(ou escondido junto/);
    expect(suprimidas).toHaveLength(2);
    expect(tabela).not.toHaveTextContent(/menos de 5 alunos|complementar/);
    // Os blocos da escola somam só as séries mostradas; o denominador é o dos alunos com conta.
    expect(screen.getByTestId("texto-blocos")).toHaveTextContent("somam só as séries mostradas");
    expect(screen.getByTestId("plataforma-elefante")).toHaveTextContent("5 de 7 alunos com conta leram no período");
    // Sem filtro de série na Visão da Escola: o texto não cita um filtro que não existe.
    expect(screen.getByTestId("analise-escola-filtros"))
      .toHaveTextContent("Vale aqui: o período (Ano letivo 2026). A tabela mostra cada série do 1º ao 5º ano.");
    expect(screen.getByTestId("analise-escola-indisponiveis")).toHaveTextContent("não compara a escola com as outras");
  });

  it("a escola sem código INEP: o aviso, o motivo em cada célula e as plataformas sem aluno", async () => {
    responder("GET", "/escolas/5/analise", escolaSemInep);
    renderComApp(<AnaliseDaEscola escolaId={5} />, { usuario: secretaria });
    expect(await screen.findByTestId("analise-escola-sem-inep")).toBeInTheDocument();
    expect(screen.getByTestId("analise-escola-indicador-saresp")).toHaveTextContent("a escola está sem código INEP no cadastro");
    expect(screen.getByTestId("plataforma-elefante")).toHaveTextContent("nenhum aluno ativo do 1º ao 5º ano");
    // O cadastro sem INEP não se repete na lista do que não se compara.
    expect(screen.getByTestId("analise-escola-indisponiveis")).not.toHaveTextContent("números oficiais dela não podem ser casados");
  });

  it("a recusa da API para o ICA por escola é a mensagem do backend (caso alguém a peça)", async () => {
    semear();
    responderErro("GET", "/redes/1/analise/indicadores/ica", 400, erroIcaPorEscola.detail);
    renderComApp(<IndicadorEmDetalhe />, { rota: "/rede/avaliacoes-externas?indicador=ica", usuario: secretaria });
    expect(await screen.findByText(/O ICA não existe por escola/)).toBeInTheDocument();
  });
});
