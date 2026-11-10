/**
 * FICHA DA ESCOLA (`/rede/escolas/:escolaId`) — DESENHO3 §3: o "‹ Escolas" (com a consulta da
 * lista), o cadastro (ativa/inativa, cidade, alunos, turmas, professores), a situação de uso no
 * ano letivo (a mesma função do Panorama), o Elefante e o Matific no período (com o seletor), a
 * evolução SÓ da escola (sem número nenhum: uma frase só, com o motivo uma vez), as avaliações
 * externas da escola no modo simples (os avisos de cada indicador recolhidos; sem resultado: o
 * porquê), "Ver as turmas da escola" (só para a escola que está no contexto — a inativa no cadastro
 * não está: o porquê por extenso) e a escola de outra rede com a mensagem clara — sem chamar a API
 * dela. O admin global leva o `?rede=` nos links.
 *
 * Números e nomes INVENTADOS (D13).
 */
import { describe, expect, it } from "vitest";

import { TEXTO_SUPRESSAO, evolucao } from "./AnaliseFixturesDiagnostico";
import {
  ESCOLAS_DO_CONTEXTO, TEXTO_SERIES_SUPRIMIDAS, evolucaoSeriesSuprimidas, plataformasComEpsilon, renderEscolas,
  semearEscolas,
} from "./EscolasRedeFixtures";
import { admin, antes, chamadas, consulta, semCausalidade, semJargao } from "./SecretariaFixtures";
import { api, escolaFake, responder, responderErro, screen, userEvent, waitFor, within } from "./utils";

const abrirFicha = async (caminho: string, opcoes = {}) => {
  const r = renderEscolas(caminho, opcoes);
  await screen.findByTestId("ficha-cadastro");
  return r;
};
const leuDaEscola = (id: number) => api.mock.calls.some(([c]) => {
  const url = String(c);
  return url.startsWith(`/escolas/${id}/`) || (url.includes("/plataformas/evolucao") && consulta(url).get("escola_id") === String(id));
});

describe("Ficha da escola — o que ela mostra", () => {
  it("cabeçalho e cadastro: o nome, ativa no cadastro (não é uso), cidade, alunos, turmas e professores", async () => {
    semearEscolas();
    await abrirFicha("/rede/escolas/2");
    expect(screen.getByRole("heading", { level: 1, name: "EMEF Sintética Alfa" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Voltar para Escolas" })).toHaveAttribute("href", "/rede/escolas");
    const cadastro = screen.getByTestId("ficha-cadastro");
    expect(cadastro).toHaveTextContent("Situação do cadastroAtivasituação do cadastro; não indica uso");
    expect(cadastro).toHaveTextContent("CidadeCidade Sintética");
    expect(cadastro).toHaveTextContent("Alunos no ano letivo150matriculados, todas as etapas");
    expect(cadastro).toHaveTextContent("Turmas6");
    expect(cadastro).toHaveTextContent("Professores8");
    expect(await screen.findByTestId("secretaria-rede-nome")).toHaveTextContent("Rede Sintética Norte");
  });

  it("a situação de uso no ano letivo: a geral e a de cada plataforma, por extenso (protegido não é zero)", async () => {
    semearEscolas();
    await abrirFicha("/rede/escolas/2");
    const uso = await screen.findByTestId("ficha-situacao-uso");
    expect(uso).toHaveTextContent("Situação: Com uso no ano letivo");
    // Cada plataforma com o rótulo curto DELA (`ROTULO_PLATAFORMA`), o mesmo do Panorama — não o da escola.
    // O número do Elefante conta também a releitura: "um livro", nunca "um livro novo".
    expect(screen.getByTestId("ficha-uso-elefante"))
      .toHaveTextContent("Elefante: Com uso 70% dos alunos com conta leram ao menos um livro");
    expect(screen.getByTestId("ficha-uso-elefante")).not.toHaveTextContent("livro novo");
    expect(screen.getByTestId("ficha-uso-matific"))
      .toHaveTextContent("Matific: Protegido (poucos alunos) menos de 5 alunos com dado desta plataforma no período");
    expect(screen.getByTestId("ficha-uso-elefante")).not.toHaveTextContent("Com uso no ano letivo");
    expect(screen.getByTestId("ficha-uso-matific")).not.toHaveTextContent("Protegida");
    const oQueMede = uso.querySelector("[data-o-que-mede]");
    expect(oQueMede).toHaveTextContent("pelo menos um aluno do 1º ao 5º ano leu um livro no Elefante ou fez uma "
      + "atividade no Matific no ano letivo, pelas coletas");
    expect(oQueMede).not.toHaveTextContent("livro novo");
    // A situação é sempre do ano letivo: a leitura das plataformas sem série, no ano letivo.
    expect(chamadas("/redes/1/analise/plataformas").some((c) => consulta(c).get("periodo") === "ano_letivo"
      && !consulta(c).has("serie"))).toBe(true);
  });

  it("Elefante e Matific no período: os cartões da escola; trocar o período refaz a leitura e fica na URL", async () => {
    semearEscolas();
    await abrirFicha("/rede/escolas/2");
    const bloco = await screen.findByTestId("ficha-plataformas");
    expect(within(bloco).getByTestId("plataforma-elefante")).toHaveTextContent("70%");
    expect(within(bloco).getByTestId("plataforma-matific")).toHaveTextContent("Sem dado do Matific");
    expect(screen.getByTestId("ficha-recorte-plataformas")).toHaveTextContent("Vale aqui: período (Ano letivo de 2026) e série (1º ao 5º ano).");
    expect(screen.getByTestId("ficha-ultima-coleta")).toHaveTextContent("Última coleta: Elefante 18/10/2026 · Matific 19/10/2026.");
    expect(bloco.querySelector("[data-natureza=plataforma]")).toHaveTextContent("Plataforma");
    expect(screen.getByLabelText("Período")).toHaveValue("ano_letivo");
    await userEvent.selectOptions(screen.getByLabelText("Período"), "mes");
    await waitFor(() => expect(chamadas("/redes/1/analise/plataformas").some((c) => consulta(c).get("periodo") === "mes"))
      .toBe(true));
    expect(screen.getByTestId("onde")).toHaveTextContent("/rede/escolas/2?periodo=mes");
    // A situação de uso continua sendo a do ano letivo.
    expect(screen.getByTestId("ficha-situacao-uso")).toHaveTextContent("Com uso no ano letivo");
    const oQueMede = screen.getByTestId("ficha-o-que-mede");
    await userEvent.click(within(oQueMede).getByRole("button"));
    expect(oQueMede).toHaveTextContent("Elefante — Participação");
    expect(oQueMede).toHaveTextContent("“Sem dado” não é zero");
  });

  it("a evolução por bimestre é SÓ da escola (sem a tabela da rede)", async () => {
    semearEscolas();
    await abrirFicha("/rede/escolas/2");
    const escola = await screen.findByTestId("tabela-evolucao-escola");
    expect(screen.queryByTestId("tabela-evolucao-rede")).toBeNull();
    expect(within(escola).getAllByRole("row")[1]).toHaveTextContent(/58%.*1,25.*72%.*6,5/);
    // O Matific sem coleta no 2º bimestre: a célula diz só "sem dado" (o serviço não manda porquê,
    // então não há nota de motivos — a legenda diz que sem dado não é zero).
    const segundo = within(within(escola).getAllByRole("row")[2]).getAllByRole("cell");
    expect(segundo[2]).toHaveTextContent(/^sem dado$/);
    expect(screen.queryByTestId("motivos-evolucao-escola")).toBeNull();
    expect(chamadas("/redes/1/analise/plataformas/evolucao").map((c) => consulta(c).get("escola_id"))).toEqual(["2"]);
    // Só a escola é medida no servidor (a rede inteira custava uma medição por escola).
    expect(chamadas("/redes/1/analise/plataformas/evolucao").map((c) => consulta(c).get("so_escola"))).toEqual(["true"]);
    expect(screen.getByTestId("grafico-evolucao")).toHaveTextContent("Participação na escola, por bimestre");
  });

  it("com so_escola o servidor manda a rede nula: a ficha mostra a escola igual", async () => {
    semearEscolas();
    const base = evolucao();
    responder("GET", "/redes/1/analise/plataformas/evolucao",
              { ...base, filtros: { serie: null, escola_id: 2, so_escola: true },
                bimestres: base.bimestres.map((b) => ({ ...b, rede: null })) });
    await abrirFicha("/rede/escolas/2");
    const escola = await screen.findByTestId("tabela-evolucao-escola");
    expect(within(escola).getAllByRole("row")[1]).toHaveTextContent(/58%.*1,25.*72%.*6,5/);
    expect(screen.getByTestId("grafico-evolucao")).toHaveTextContent("Participação na escola, por bimestre");
    expect(screen.queryByText(/Não foi possível carregar a evolução/)).toBeNull();
  });

  it("escola sem número em nenhum bimestre (todas as séries pequenas): uma frase só no lugar da tabela", async () => {
    semearEscolas();
    responder("GET", "/redes/1/analise/plataformas/evolucao", evolucaoSeriesSuprimidas(4));
    await abrirFicha("/rede/escolas/4");
    const frase = await screen.findByTestId("evolucao-escola-sem-numero");
    // "Protegido", como a situação de uso lá em cima — o motivo por extenso, UMA vez.
    expect(frase).toHaveTextContent(
      `Nenhum número desta escola do 1º ao 4º bimestre do ano letivo de 2026 — protegido: ${TEXTO_SERIES_SUPRIMIDAS}.`);
    expect(screen.queryByTestId("tabela-evolucao-escola")).toBeNull();
    expect(screen.queryByTestId("grafico-evolucao")).toBeNull();
    const evolucao = screen.getByTestId("evolucao-escola");
    expect((evolucao.textContent ?? "").split(TEXTO_SERIES_SUPRIMIDAS)).toHaveLength(2);
    expect(evolucao).not.toHaveTextContent(/\d+([,.]\d+)?%/);
    expect(screen.getByTestId("ficha-situacao-uso")).toHaveTextContent("Situação: Protegida (poucos alunos)");
  });

  it("as avaliações externas da escola, no modo simples, separadas das plataformas pela frase dos períodos", async () => {
    semearEscolas();
    const { container } = await abrirFicha("/rede/escolas/2");
    const saresp = await screen.findByTestId("analise-escola-indicador-saresp");
    expect(within(saresp).getByRole("heading", { level: 3, name: "SARESP" })).toBeInTheDocument();
    expect(saresp).toHaveTextContent("219,6");
    expect(saresp).toHaveTextContent("Cidade Sintética — rede municipal");
    // Os avisos do indicador: recolhidos (fechados), depois da tabela; o texto só ao abrir.
    const avisos = within(saresp).getByTestId("avisos-indicador-saresp");
    expect(within(avisos).getByRole("button", { name: "Avisos sobre estes números (1)" }))
      .toHaveAttribute("aria-expanded", "false");
    expect(saresp).not.toHaveTextContent("O SARESP tem escala própria");
    expect(antes(within(saresp).getByRole("table"), avisos)).toBe(true);
    await userEvent.click(within(avisos).getByRole("button"));
    expect(avisos).toHaveTextContent("O SARESP tem escala própria (texto sintético).");
    expect(screen.getByTestId("analise-escola-indicador-iee")).toHaveTextContent("meta 5,20 · −0,40 · não atingiu a meta");
    // O ICA é só da rede: não vira bloco da escola; o porquê fica em "O que não dá para comparar".
    expect(screen.queryByTestId("analise-escola-indicador-ica")).toBeNull();
    const indisponiveis = screen.getByTestId("analise-escola-indisponiveis");
    expect(indisponiveis).toHaveTextContent("O ICA é da rede: não existe por escola.");
    expect(indisponiveis).not.toHaveTextContent("Relação com as plataformas");
    // A ordem: plataformas e evolução, a frase, as avaliações.
    const frase = screen.getByTestId("frase-separacao");
    expect(frase).toHaveTextContent("As avaliações oficiais são de outras edições (até 2025)");
    expect(antes(screen.getByTestId("tabela-evolucao-escola"), frase) && antes(frase, saresp)).toBe(true);
    expect(antes(screen.getByTestId("ficha-cadastro"), screen.getByTestId("ficha-situacao-uso"))).toBe(true);
    expect(antes(screen.getByTestId("ficha-situacao-uso"), screen.getByTestId("ficha-plataformas"))).toBe(true);
    // Uma leitura só da análise da escola, no ano letivo (a mesma da comparação lado a lado).
    expect(chamadas("/escolas/2/analise")).toEqual(["/escolas/2/analise?periodo=ano_letivo&so_avaliacoes=true"]);
    for (const botao of screen.getAllByRole("button", { expanded: false })) await userEvent.click(botao);
    semCausalidade(container);
    semJargao(container);
  });

  it("escola inativa e sem dado: 'Inativa', 'Sem dado' e o porquê de não ter resultado oficial", async () => {
    semearEscolas();
    await abrirFicha("/rede/escolas/6");
    expect(screen.getByRole("heading", { level: 1, name: "EMEF Sintética Épsilon" })).toBeInTheDocument();
    expect(screen.getByTestId("ficha-cadastro")).toHaveTextContent("Inativa");
    expect(await screen.findByTestId("ficha-situacao-uso")).toHaveTextContent("Situação: Sem dado");
    expect(screen.getByTestId("ficha-uso-elefante")).toHaveTextContent("Elefante: Sem dado a escola não tem nenhuma coleta desta plataforma");
    expect(screen.getByTestId("ficha-plataformas")).toHaveTextContent("Sem dado do Elefante: a escola não tem nenhuma coleta desta plataforma");
    expect(screen.getByTestId("ficha-plataformas")).not.toHaveTextContent(/(^|\D)0(,0)?%/);
    // O formato REAL do servidor: os indicadores vêm todos, a série da escola sem ponto e a rede com
    // número — o porquê é o das séries (não "nada importado", que seria falso aqui).
    expect(await screen.findByTestId("avaliacoes-escola-sem-resultado")).toHaveTextContent(
      "Esta escola ainda não tem resultado oficial no Constela: as edições importadas trazem resultados da rede "
      + "municipal, mas nenhum desta escola.");
    for (const chave of ["saresp", "iee", "ideb", "saeb"]) {
      expect(screen.getByTestId(`analise-escola-indicador-${chave}`)).toBeInTheDocument();
    }
    expect(screen.getByTestId("analise-escola-indicador-saresp")).toHaveTextContent("Cidade Sintética — rede municipal");
    expect(screen.getByTestId("analise-escola-indicador-iee")).toHaveTextContent("Sem número oficial desta escola importado.");
    expect(screen.queryByTestId("analise-escola-sem-indicadores")).toBeNull();
  });

  it("escola protegida e sem código INEP: 'Protegida' e números ocultos; o aviso do INEP", async () => {
    semearEscolas();
    await abrirFicha("/rede/escolas/4");
    expect(await screen.findByTestId("ficha-situacao-uso")).toHaveTextContent("Situação: Protegida (poucos alunos)");
    expect(screen.getByTestId("plataformas-suprimidas")).toHaveTextContent(`Números ocultos: ${TEXTO_SUPRESSAO}.`);
    expect(await screen.findByTestId("analise-escola-sem-inep")).toHaveTextContent("sem código INEP no cadastro");
    // Formato real (as edições importadas com o motivo de cada uma): o aviso do INEP basta, sem a frase repetida.
    expect(screen.getByTestId("analise-escola-indicador-saresp")).toHaveTextContent("a escola está sem código INEP no cadastro");
    expect(screen.queryByTestId("avaliacoes-escola-sem-resultado")).toBeNull();
  });

  it("'Ver as turmas da escola': a escola vai para o contexto e a Visão da Escola volta para a ficha", async () => {
    semearEscolas();
    await abrirFicha("/rede/escolas/3?periodo=mes");
    await userEvent.click(screen.getByRole("link", { name: /Ver as turmas da escola/ }));
    expect(await screen.findByText("TELA:escola")).toBeInTheDocument();
    const onde = screen.getByTestId("onde");
    expect(onde).toHaveAttribute("data-voltar-caminho", "/rede/escolas/3?periodo=mes");
    expect(onde).toHaveAttribute("data-voltar-texto", "Voltar para a ficha da escola");
    expect(onde).toHaveAttribute("data-escola-contexto", "3");
  });

  it("escola inativa (fora da lista do contexto): sem 'Ver as turmas', o porquê por extenso — o contexto não muda", async () => {
    semearEscolas();
    await abrirFicha("/rede/escolas/6");
    expect(screen.getByTestId("ficha-cadastro")).toHaveTextContent("Inativa");
    expect(screen.queryByTestId("ver-turmas")).toBeNull();
    expect(screen.queryByRole("link", { name: /Ver as turmas da escola/ })).toBeNull();
    expect(screen.getByTestId("ver-turmas-indisponivel"))
      .toHaveTextContent("Escola inativa no cadastro: as turmas dela não ficam disponíveis na Visão da Escola.");
    expect(screen.getByTestId("onde")).toHaveAttribute("data-escola-contexto", "");
  });

  it("escola ativa que não está na lista do contexto da conta: sem o link, a frase geral", async () => {
    semearEscolas();
    await abrirFicha("/rede/escolas/3", { escolas: [escolaFake({ id: 2, nome: "EMEF Sintética Alfa" })] });
    expect(screen.queryByTestId("ver-turmas")).toBeNull();
    expect(screen.getByTestId("ver-turmas-indisponivel"))
      .toHaveTextContent("As turmas desta escola não estão disponíveis na Visão da Escola para a sua conta.");
  });

  it("o '‹ Escolas' continua voltando à consulta da lista depois de trocar o período NA ficha", async () => {
    semearEscolas();
    renderEscolas("/rede/escolas?periodo=mes&serie=3&comparar=2,5");
    await screen.findByTestId("tabela-escolas-periodo");
    await userEvent.click(within(screen.getByTestId("escola-periodo-2")).getByRole("link", { name: "EMEF Sintética Alfa" }));
    await screen.findByTestId("ficha-cadastro");
    const lista = "/rede/escolas?periodo=mes&serie=3&comparar=2,5";
    expect(screen.getByRole("link", { name: "Voltar para Escolas" })).toHaveAttribute("href", lista);
    // Trocar o período grava a URL da ficha (com `replace`, sem o estado da navegação): a volta fica.
    await userEvent.selectOptions(screen.getByLabelText("Período"), "bimestre_2");
    await waitFor(() => expect(screen.getByTestId("onde")).toHaveTextContent("/rede/escolas/2?periodo=bimestre_2"));
    expect(screen.getByRole("link", { name: "Voltar para Escolas" })).toHaveAttribute("href", lista);
    await userEvent.selectOptions(screen.getByLabelText("Período"), "ano_letivo");
    await waitFor(() => expect(screen.getByTestId("onde")).toHaveTextContent(/^\/rede\/escolas\/2$/));
    expect(screen.getByRole("link", { name: "Voltar para Escolas" })).toHaveAttribute("href", lista);
    await userEvent.click(screen.getByRole("link", { name: "Voltar para Escolas" }));
    expect(await screen.findByTestId("tabela-escolas-periodo")).toBeInTheDocument();
    expect(screen.getByTestId("onde")).toHaveTextContent(lista);
  });
});

describe("Ficha da escola — escola que não é da rede", () => {
  it.each([["/rede/escolas/999"], ["/rede/escolas/abc"]])(
    "%s: a mensagem clara, sem chamar a API da escola", async (caminho) => {
      semearEscolas();
      renderEscolas(caminho);
      expect(await screen.findByTestId("ficha-nao-encontrada")).toHaveTextContent("Esta escola não está nesta rede");
      expect(screen.getByRole("heading", { level: 1, name: "Escola não encontrada" })).toBeInTheDocument();
      expect(screen.getByRole("link", { name: "Ver todas as escolas" })).toHaveAttribute("href", "/rede/escolas");
      expect(leuDaEscola(999)).toBe(false);
      expect(api.mock.calls.some(([c]) => /^\/escolas\/\d+\/analise/.test(String(c)))).toBe(false);
    });

  it("o painel falha, mas as plataformas confirmam a escola: a ficha abre e diz que falta o cadastro", async () => {
    semearEscolas();
    responderErro("GET", "/redes/1/dashboard", 500, "FALHA-DO-PAINEL");
    renderEscolas("/rede/escolas/2");
    expect(await screen.findByRole("heading", { level: 1, name: "EMEF Sintética Alfa" })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId("ficha-sem-cadastro")).toHaveTextContent("FALHA-DO-PAINEL"), { timeout: 3000 });
    expect(await screen.findByTestId("analise-escola-indicador-saresp")).toBeInTheDocument();
  });

  it("as duas listas da rede falham e a escola não está na lista da sessão: o erro aparece, sem ler a escola", async () => {
    semearEscolas();
    responderErro("GET", "/redes/1/dashboard", 500, "FALHA-DO-PAINEL");
    responderErro("GET", "/redes/1/analise/plataformas", 500, "FALHA-DAS-PLATAFORMAS");
    // A inativa (6) não está na lista da sessão: só o painel ou as plataformas a confirmariam.
    renderEscolas("/rede/escolas/6");
    expect(await screen.findByText(/FALHA-DO-PAINEL/, undefined, { timeout: 3000 })).toBeInTheDocument();
    expect(screen.queryByTestId("ficha-cadastro-carregando")).toBeNull();
    expect(leuDaEscola(6)).toBe(false);
  });

  it("as duas listas falham com a escola na lista da sessão (Secretaria): a ficha abre e cada bloco diz o erro", async () => {
    semearEscolas();
    responderErro("GET", "/redes/1/dashboard", 500, "FALHA-DO-PAINEL");
    responderErro("GET", "/redes/1/analise/plataformas", 500, "FALHA-DAS-PLATAFORMAS");
    renderEscolas("/rede/escolas/2");
    // O nome vem da lista da sessão (só escolas da rede dela): nunca a ficha de outra escola.
    expect(await screen.findByRole("heading", { level: 1, name: "EMEF Sintética Alfa" })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId("ficha-sem-cadastro")).toHaveTextContent("FALHA-DO-PAINEL"),
                  { timeout: 3000 });
    await waitFor(() => expect(screen.getByText(/Não foi possível carregar o uso das plataformas: FALHA-DAS-PLATAFORMAS/))
      .toBeInTheDocument(), { timeout: 3000 });
    // As avaliações da escola não dependem das listas da rede.
    expect(await screen.findByTestId("analise-escola-indicador-saresp")).toHaveTextContent("219,6");
  });

  // A lista da sessão é lida no login: a escola movida para outra rede (ou excluída) depois dele
  // continua nela até recarregar. Quando uma lista da rede CHEGA sem a escola, a sessão não confirma
  // mais nada — a ficha diz que a escola não é desta rede (nunca quebra a página nem mostra a ficha
  // de uma escola que a rede não tem).
  it.each([
    ["o painel e as plataformas chegam sem ela", () => {}],
    ["o painel falha e as plataformas chegam sem ela",
     () => responderErro("GET", "/redes/1/dashboard", 500, "FALHA-DO-PAINEL")],
    ["as plataformas falham e o painel chega sem ela",
     () => responderErro("GET", "/redes/1/analise/plataformas", 500, "FALHA-DAS-PLATAFORMAS")],
  ])("escola na lista VELHA da sessão (saiu da rede depois do login), %s: 'Escola não encontrada'", async (_, falha) => {
    semearEscolas();
    falha();
    // O servidor barra a escola que não é mais da rede.
    responderErro("GET", (c) => c.startsWith("/escolas/77/"), 403, "Acesso negado: a escola não é da sua rede.");
    renderEscolas("/rede/escolas/77", {
      escolas: [...ESCOLAS_DO_CONTEXTO, escolaFake({ id: 77, nome: "EMEF Sintética Movida" })],
    });
    expect(await screen.findByTestId("ficha-nao-encontrada", undefined, { timeout: 3000 }))
      .toHaveTextContent("Esta escola não está nesta rede");
    expect(screen.getByRole("heading", { level: 1, name: "Escola não encontrada" })).toBeInTheDocument();
    // E continua assim (nada de a ficha voltar depois, nem a página quebrar).
    await new Promise((r) => setTimeout(r, 100));
    expect(screen.getByTestId("ficha-nao-encontrada")).toBeInTheDocument();
    expect(screen.queryByTestId("ficha-situacao-uso")).toBeNull();
    expect(screen.queryByText("EMEF Sintética Movida")).toBeNull();
  });
});

describe("Ficha da escola — a Secretaria não espera o painel nem as plataformas", () => {
  /** O painel e as plataformas da rede nunca respondem (a leitura lenta da rede). */
  const listasDaRedePresas = () => {
    responder("GET", "/redes/1/dashboard", () => new Promise(() => {}));
    responder("GET", "/redes/1/analise/plataformas", () => new Promise(() => {}));
  };

  it("escola da lista da sessão: as avaliações e a evolução saem já; o cadastro diz 'carregando', nunca 'sem cadastro'", async () => {
    semearEscolas();
    listasDaRedePresas();
    renderEscolas("/rede/escolas/2");
    expect(await screen.findByRole("heading", { level: 1, name: "EMEF Sintética Alfa" })).toBeInTheDocument();
    await waitFor(() => expect(chamadas("/escolas/2/analise"))
      .toEqual(["/escolas/2/analise?periodo=ano_letivo&so_avaliacoes=true"]));
    expect(chamadas("/redes/1/analise/plataformas/evolucao").map((c) => consulta(c).get("escola_id"))).toEqual(["2"]);
    expect(screen.getByTestId("ficha-cadastro-carregando")).toHaveTextContent("Carregando o cadastro da escola...");
    expect(screen.queryByTestId("ficha-sem-cadastro")).toBeNull();
    expect(screen.queryByTestId("ficha-cadastro")).toBeNull();
    expect(screen.getByText("Carregando o uso das plataformas...")).toBeInTheDocument();
    // As avaliações aparecem sem esperar as listas da rede.
    expect(await screen.findByTestId("analise-escola-indicador-saresp")).toHaveTextContent("219,6");
    expect(screen.queryByTestId("ficha-nao-encontrada")).toBeNull();
  });

  it("escola fora da lista da sessão (inativa, de outra rede ou inexistente): nenhuma leitura dela enquanto as listas não chegam", async () => {
    semearEscolas();
    listasDaRedePresas();
    renderEscolas("/rede/escolas/6");
    await waitFor(() => expect(chamadas("/redes/1/dashboard").length).toBeGreaterThan(0));
    await new Promise((r) => setTimeout(r, 50));
    expect(leuDaEscola(6)).toBe(false);
    expect(screen.queryByRole("heading", { level: 1 })).toBeNull();
  });

  it("o admin global não confirma pela lista da sessão (ela não diz a rede da escola): espera, como antes", async () => {
    semearEscolas();
    listasDaRedePresas();
    responder("GET", "/redes", [{ id: 1, nome: "Rede Sintética Norte" }, { id: 2, nome: "Rede Sintética Sul" }]);
    renderEscolas("/rede/escolas/2?rede=1", { usuario: admin });
    await waitFor(() => expect(chamadas("/redes/1/dashboard").length).toBeGreaterThan(0));
    await new Promise((r) => setTimeout(r, 50));
    expect(leuDaEscola(2)).toBe(false);
    expect(screen.queryByTestId("ficha-cadastro-carregando")).toBeNull();
  });
});

describe("Ficha da escola — admin global e módulos", () => {
  it("o admin global leva o ?rede= nos links da ficha", async () => {
    semearEscolas();
    responder("GET", "/redes", [{ id: 1, nome: "Rede Sintética Norte" }, { id: 2, nome: "Rede Sintética Sul" }]);
    await abrirFicha("/rede/escolas/2?rede=1", { usuario: admin });
    expect(screen.getByRole("link", { name: "Voltar para Escolas" })).toHaveAttribute("href", "/rede/escolas?rede=1");
    expect(screen.getByRole("link", { name: /Ver as avaliações externas de toda a rede/ }))
      .toHaveAttribute("href", "/rede/avaliacoes-externas?rede=1");
  });

  it("rede só com o Elefante: a situação e os cartões sem o Matific", async () => {
    semearEscolas();
    responder("GET", "/redes/1/analise/plataformas", plataformasComEpsilon({ modulos: { elefante: true, matific: false } }));
    await abrirFicha("/rede/escolas/2");
    expect(await screen.findByTestId("ficha-uso-elefante")).toBeInTheDocument();
    expect(screen.queryByTestId("ficha-uso-matific")).toBeNull();
    // "Com uso" fala só da plataforma contratada.
    const oQueMede = screen.getByTestId("ficha-situacao-uso").querySelector("[data-o-que-mede]");
    expect(oQueMede).toHaveTextContent("pelo menos um aluno do 1º ao 5º ano leu um livro no Elefante no ano letivo, pelas coletas");
    expect(oQueMede).not.toHaveTextContent("Matific");
    expect(screen.queryByTestId("plataforma-matific")).toBeNull();
    expect(screen.getByRole("heading", { level: 2, name: /Elefante Letrado no período/ })).toBeInTheDocument();
  });
});
