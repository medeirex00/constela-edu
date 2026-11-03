/**
 * Análise educacional da escola na Visão da Escola (`AnaliseDaEscola`,
 * `GET /escolas/{id}/analise`):
 *
 *  - o coordenador lê a da própria escola (indicadores oficiais dela, com a rede como
 *    referência; plataformas por série; o que não dá para comparar) — a ausência por
 *    extenso, nunca 0, e a fonte só em "Detalhes e fontes";
 *  - a Secretaria lê a da escola em que entrou; o PROFESSOR não vê e a API nem é chamada;
 *  - a Visão da Escola usa esta seção (não chama mais `/escolas/{id}/indicadores`) — para a
 *    Secretaria, no modo SIMPLES (o fluxo principal dela chega lá pela ficha da escola);
 *  - ao trocar de escola, nunca ficam os números da anterior.
 *
 * Números, nomes e arquivos INVENTADOS (D13).
 */
import { describe, expect, it, vi } from "vitest";

import type { FonteOficial } from "../components/SeloFonte";
import { useApp } from "../context/AppContext";
import VisaoEscola from "../pages/VisaoEscola";
import AnaliseDaEscola, {
  ConteudoAnaliseEscola, porqueSemResultadoOficial, temResultadoOficial,
} from "../pages/analise/AnaliseDaEscola";
import type { PontoAnalise, RespostaAnaliseEscola } from "../pages/analise/tipos";
import { REDE_SINTETICA, indicadoresSemNumeroDaEscola } from "./EscolasRedeFixtures";
import {
  api, escolaFake, renderComApp, responder, responderErro, screen, userEvent, usuarioFake, within,
} from "./utils";

const secretaria = usuarioFake({ nome: "Secretaria", cargo: "coordenador", rede_id: 1, escola_id: null });
const coordenador = usuarioFake({ nome: "Coordenadora", cargo: "coordenador", escola_id: 1 });
const professor = usuarioFake({ nome: "Professora", cargo: "professor", escola_id: 1 });
const admin = usuarioFake({ nome: "Root", cargo: "admin", is_global: true, escola_id: null });

const FONTE: FonteOficial = {
  importacao_id: 31, fonte_nome: "SEDUC-SP — Índice de Excelência Educacional (IEE)",
  arquivo_nome: "iee_sintetico_2025.csv", arquivo_data: null, last_modified_origem: null, url_origem: null,
  edicao_arquivo: 2025, versao_rotulo: null, importado_em: "2026-10-17T12:00:00", coletado_em: null,
  citacao: null, licenca: "Dados abertos sintéticos: citar a fonte.", parser: "seduc_iee", modo: "upload",
  notas: [], data_arquivo: "2026-01-12", data_arquivo_origem: "last_modified",
};

function ponto(edicao: number, valor: number | null, over: Partial<PontoAnalise> = {}): PontoAnalise {
  return {
    edicao, valor, casas: valor == null ? null : 1, motivo_ausencia: valor == null ? "fora_do_arquivo" : null,
    texto_ausencia: valor == null ? "a escola não está no arquivo oficial importado desta edição" : null,
    meta: null, meta_casas: null, diferenca_meta: null, situacao_meta: null, instavel: false, fonte_id: 31, ...over,
  };
}

function resposta(id: number, nome: string, over: Partial<RespostaAnaliseEscola> = {}): RespostaAnaliseEscola {
  return {
    escola: { id, nome, codigo_inep: `3599000${id}`, pendencia: null },
    rede: { id: 1, nome: "Rede Sintética Norte" },
    indicadores: [
      { chave: "saresp", nome: "SARESP", unidade: "pontos", avisos: ["O SARESP tem escala própria (sintético)."],
        series: [
          { id: `escola_${id}`, rotulo: nome, papel: "principal", abrangencia: "escola", escola_id: id,
            rede_ensino: "municipal", mesma_rede: true, comparavel: true, motivo_nao_comparavel: null,
            etapa: "2_ano", componente: "mt", pontos: [ponto(2024, null), ponto(2025, 151.8, { instavel: true })] },
          { id: "rede_municipal", rotulo: "Cidade Sintética — rede municipal", papel: "referencia", abrangencia: "rede",
            escola_id: null, rede_ensino: "municipal", mesma_rede: true, comparavel: true, motivo_nao_comparavel: null,
            etapa: "2_ano", componente: "mt", pontos: [ponto(2024, 140.2), ponto(2025, 144.9)] },
        ] },
      { chave: "iee", nome: "IEE", unidade: "índice", avisos: [],
        series: [
          { id: `escola_${id}`, rotulo: nome, papel: "principal", abrangencia: "escola", escola_id: id,
            rede_ensino: "municipal", mesma_rede: true, comparavel: true, motivo_nao_comparavel: null,
            etapa: "anos_iniciais", componente: null,
            pontos: [ponto(2025, 5.21, { casas: 2, meta: 5.4, meta_casas: 2, diferenca_meta: -0.19,
                                         situacao_meta: "nao_atingiu" })] },
        ] },
    ],
    plataformas: {
      janela: { inicio: "2026-01-01", fim: "2026-12-31", rotulo: "Ano letivo de 2026" }, alunos: 88,
      modulos: { elefante: true, matific: false }, k_minimo: 5,
      elefante: { alunos_com_leitura: 52, participacao_pct: 59.1, livros_por_aluno: 2.4, minutos_por_aluno: 61.5,
                  nivel_medio: "H", taxa_acerto_pct: null, janela_questoes: null },
      matific: null,
      series: [{ serie: 3, alunos: 18, suprimido: false, matific: null,
                 elefante: { alunos_com_leitura: 11, participacao_pct: 61.1, livros_por_aluno: 2.9,
                             minutos_por_aluno: 70.2, nivel_medio: "I", taxa_acerto_pct: null, janela_questoes: null } }],
    },
    comparacoes_indisponiveis: [
      { tema: "ica", texto: "O ICA é da rede: não existe por escola." },
      { tema: "relacao", texto: "Relação com as plataformas: período sem sobreposição (texto sintético)." },
    ],
    fontes: { "31": FONTE },
    ...over,
  };
}

const chamouAnalise = () => api.mock.calls.some(([c]) => String(c).includes("/analise"));

describe("Análise da escola — por perfil", () => {
  it("o coordenador vê a escola: indicadores dela com a rede como referência, plataformas e o que não se compara", async () => {
    responder("GET", "/escolas/1/analise", resposta(1, "EMEF Sintética Alfa"));
    renderComApp(<AnaliseDaEscola escolaId={1} />, { usuario: coordenador });
    const saresp = await screen.findByTestId("analise-escola-indicador-saresp");
    expect(screen.getByRole("heading", { name: /Análise educacional da escola/ })).toBeInTheDocument();
    expect(screen.getByTestId("analise-escola-nome")).toHaveTextContent("EMEF Sintética Alfa");
    expect(api).toHaveBeenCalledWith("/escolas/1/analise?periodo=ano_letivo", expect.anything());
    // Ausência por extenso; número na precisão recebida; instável marcada; a rede como referência.
    expect(saresp).toHaveTextContent("2º ano · Matemática");
    expect(saresp).toHaveTextContent("a escola não está no arquivo oficial importado desta edição");
    expect(saresp).toHaveTextContent("151,8");
    expect(saresp).toHaveTextContent("média instável");
    expect(saresp).toHaveTextContent("Cidade Sintética — rede municipal");
    expect(saresp).toHaveTextContent("referência");
    expect(saresp).not.toHaveTextContent(/\b0,0\b/);
    const iee = screen.getByTestId("analise-escola-indicador-iee");
    expect(iee).toHaveTextContent("5,21");
    // Meta, diferença (na menor precisão dos dois lados) e situação.
    expect(iee).toHaveTextContent("meta 5,40 · −0,19 · não atingiu a meta");
    // Plataformas: só o módulo contratado; a métrica sem dado diz isso.
    expect(screen.getByTestId("plataforma-elefante")).toHaveTextContent("59,1%");
    expect(screen.queryByTestId("plataforma-matific")).not.toBeInTheDocument();
    expect(within(screen.getByTestId("plataforma-elefante")).getByText("Acerto nas questões").parentElement)
      .toHaveTextContent("sem dado no período");
    expect(screen.getByTestId("tabela-series-plataformas")).toHaveTextContent("3º ano");
    expect(screen.getByTestId("analise-escola-indisponiveis")).toHaveTextContent("O ICA é da rede: não existe por escola.");
    // A fonte só sob demanda.
    expect(screen.queryByText(/iee_sintetico_2025\.csv/)).not.toBeInTheDocument();
    await userEvent.click(within(screen.getByTestId("detalhes-fontes-escola")).getByRole("button"));
    expect(screen.getByText(/iee_sintetico_2025\.csv/)).toBeInTheDocument();
  });

  it("a Secretaria também vê a da escola em que entrou", async () => {
    responder("GET", "/escolas/1/analise", resposta(1, "EMEF Sintética Alfa"));
    renderComApp(<AnaliseDaEscola escolaId={1} />, { usuario: secretaria });
    expect(await screen.findByTestId("analise-escola-indicador-saresp")).toBeInTheDocument();
  });

  it("o professor não vê a seção e a API nem é chamada", async () => {
    responder("GET", "/escolas/1/analise", resposta(1, "EMEF Sintética Alfa"));
    renderComApp(<><p>tela</p><AnaliseDaEscola escolaId={1} /></>, { usuario: professor });
    expect(await screen.findByText("tela")).toBeInTheDocument();
    expect(screen.queryByTestId("analise-escola")).not.toBeInTheDocument();
    expect(chamouAnalise()).toBe(false);
  });

  it("a recusa da API aparece (não some em silêncio)", async () => {
    responderErro("GET", "/escolas/1/analise", 403, "Acesso negado aos dados desta escola.");
    renderComApp(<AnaliseDaEscola escolaId={1} />, { usuario: coordenador });
    expect(await screen.findByText(/Acesso negado aos dados desta escola/)).toBeInTheDocument();
  });

  it("trocar o período refaz a leitura com o período novo", async () => {
    responder("GET", "/escolas/1/analise", resposta(1, "EMEF Sintética Alfa"));
    renderComApp(<AnaliseDaEscola escolaId={1} />, { usuario: coordenador });
    await screen.findByTestId("analise-escola-indicador-saresp");
    await userEvent.selectOptions(screen.getByLabelText("Período de análise"), "bimestre_3");
    expect(await screen.findByTestId("analise-escola-indicador-saresp")).toBeInTheDocument();
    expect(api).toHaveBeenCalledWith("/escolas/1/analise?periodo=bimestre_3", expect.anything());
  });

  it("a meta, a diferença e a situação aparecem em toda série com meta — a da rede de referência também", async () => {
    const ica = {
      chave: "ica", nome: "ICA", unidade: "%", avisos: [],
      series: [{ id: "rede_municipal", rotulo: "Cidade Sintética — rede municipal", papel: "referencia" as const,
                 abrangencia: "rede", escola_id: null, rede_ensino: "municipal", mesma_rede: true, comparavel: true,
                 motivo_nao_comparavel: null, etapa: "2_ano", componente: "lp",
                 pontos: [ponto(2025, 47, { casas: 0, meta: 51, meta_casas: 0, diferenca_meta: -4, diferenca_casas: 0,
                                            situacao_meta: "nao_atingiu" })] }],
    };
    responder("GET", "/escolas/1/analise", resposta(1, "EMEF Sintética Alfa", {
      indicadores: [...resposta(1, "EMEF Sintética Alfa").indicadores, ica],
    }));
    renderComApp(<AnaliseDaEscola escolaId={1} />, { usuario: coordenador });
    const bloco = await screen.findByTestId("analise-escola-indicador-ica");
    expect(bloco).toHaveTextContent("47%");
    expect(bloco).toHaveTextContent("meta 51% · −4 p.p. · não atingiu a meta");
  });

  it("os títulos seguem a hierarquia (h2 › h3 › h4) e o recorte da tabela é cabeçalho de grupo de LINHAS", async () => {
    responder("GET", "/escolas/1/analise", resposta(1, "EMEF Sintética Alfa"));
    renderComApp(<AnaliseDaEscola escolaId={1} />, { usuario: coordenador });
    const saresp = await screen.findByTestId("analise-escola-indicador-saresp");
    expect(screen.getByRole("heading", { level: 2, name: /Análise educacional da escola/ })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 3, name: "Indicadores oficiais da escola" })).toBeInTheDocument();
    expect(within(saresp).getByRole("heading", { level: 4, name: "SARESP" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 4, name: /Elefante Letrado/ })).toBeInTheDocument();
    const grupo = within(saresp).getByText("2º ano · Matemática");
    expect(grupo.tagName).toBe("TH");
    expect(grupo).toHaveAttribute("scope", "rowgroup");
  });

  it("sem filtro de série, o texto não cita um filtro de série que não existe na tela", async () => {
    responder("GET", "/escolas/1/analise", resposta(1, "EMEF Sintética Alfa"));
    renderComApp(<AnaliseDaEscola escolaId={1} />, { usuario: coordenador });
    const filtros = await screen.findByTestId("analise-escola-filtros");
    expect(filtros).toHaveTextContent("Vale aqui: o período (Ano letivo de 2026). A tabela mostra cada série do 1º ao 5º ano.");
    expect(filtros).not.toHaveTextContent("e série");
  });

  it("celular: no 'Uso das plataformas por série' a série fica presa à esquerda e a rolagem é avisada", async () => {
    // A moldura mede 300 px e a tabela pede 800: há colunas escondidas à direita.
    const largura = vi.spyOn(Element.prototype, "clientWidth", "get").mockReturnValue(300);
    const rolagem = vi.spyOn(Element.prototype, "scrollWidth", "get").mockReturnValue(800);
    try {
      responder("GET", "/escolas/1/analise", resposta(1, "EMEF Sintética Alfa"));
      renderComApp(<AnaliseDaEscola escolaId={1} />, { usuario: coordenador });

      const tabela = await screen.findByTestId("tabela-series-plataformas");
      const regiao = screen.getByRole("region", { name: /^Uso das plataformas por série — .*: tabela completa$/ });
      expect(regiao).toContainElement(tabela);
      expect(screen.getByText(/Deslize a tabela para o lado para ver todas as colunas/)).toBeInTheDocument();
      // A série (cabeçalho de linha) e o cabeçalho "Série" presos à esquerda só abaixo de sm.
      const serie = within(tabela).getByRole("rowheader", { name: "3º ano" });
      expect(serie).toHaveClass("presa-esquerda-celular");
      expect(serie).not.toHaveClass("sticky");
      expect(within(tabela).getByRole("columnheader", { name: "Série" })).toHaveClass("presa-esquerda-celular");
      // As colunas do Elefante continuam na mesma tabela (uma vez só no DOM).
      expect(within(tabela).getByRole("columnheader", { name: "Elefante: participação" })).toBeInTheDocument();
      expect(within(tabela).getByRole("columnheader", { name: "Min/aluno" })).toBeInTheDocument();
    } finally {
      largura.mockRestore();
      rolagem.mockRestore();
    }
  });
});

// =============================================================================
// Modo SIMPLES (a ficha da escola da Secretaria) × modo completo (o de sempre)
// =============================================================================

/** A resposta com o que o fluxo principal reescreve: o IEE com TPS = 0, o motivo técnico, o aviso
 *  com a relação, as limitações com termo técnico e o tema da relação. */
function respostaTecnica(): RespostaAnaliseEscola {
  const base = resposta(1, "EMEF Sintética Alfa");
  return {
    ...base,
    indicadores: [
      { ...base.indicadores[0],
        avisos: ["Média instável (TPS = 0: participação abaixo do mínimo do SARESP) — ele fica fora da relação com as plataformas."] },
      { chave: "iee", nome: "IEE", unidade: "índice", avisos: [],
        series: [{ id: "escola_1", rotulo: "EMEF Sintética Alfa", papel: "principal", abrangencia: "escola", escola_id: 1,
                   rede_ensino: "municipal", mesma_rede: true, comparavel: false,
                   motivo_nao_comparavel: "escola com TPS = 0 (participação abaixo do mínimo)", etapa: "anos_iniciais",
                   componente: null, pontos: [ponto(2025, 4.8, { casas: 2, tps_zero: true })] }] },
    ],
    plataformas: { ...base.plataformas!, limitacoes: ["Coorte: alunos ativos do 1º ao 5º ano (texto sintético).",
      "Relação por correlação de postos de Spearman com intervalo de 95% (texto sintético)."] },
  };
}

describe("ConteudoAnaliseEscola — modo simples (ficha da escola) e completo", () => {
  it("simples + só avaliações: sem sigla técnica, textos em língua simples, sem a relação nem as plataformas", async () => {
    const { container } = renderComApp(<ConteudoAnaliseEscola dados={respostaTecnica()} simples soAvaliacoes />,
                                       { usuario: secretaria });
    const saresp = await screen.findByTestId("analise-escola-indicador-saresp");
    // Os indicadores sobem um nível (h3, sob o h2 do cartão da ficha); sem o h3 do meio.
    expect(within(saresp).getByRole("heading", { level: 3, name: "SARESP" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Indicadores oficiais da escola" })).toBeNull();
    // Os avisos ficam recolhidos (ver o teste próprio, abaixo): abertos, em língua simples.
    await userEvent.click(within(within(saresp).getByTestId("avisos-indicador-saresp")).getByRole("button"));
    expect(saresp).toHaveTextContent("Média instável (poucos alunos fizeram a prova)");
    expect(saresp).not.toHaveTextContent("relação");
    const iee = screen.getByTestId("analise-escola-indicador-iee");
    expect(iee).toHaveTextContent("calculado com médias instáveis");
    expect(iee).toHaveTextContent("escola com média instável (participação abaixo do mínimo)");
    expect(screen.getAllByTestId("legenda-instavel")[0]).toHaveTextContent("poucos alunos fizeram a prova");
    // O ICA (só da rede) fica no "O que não dá para comparar"; a relação não aparece.
    const indisponiveis = screen.getByTestId("analise-escola-indisponiveis");
    expect(indisponiveis).toHaveTextContent("O ICA é da rede: não existe por escola.");
    expect(indisponiveis).not.toHaveTextContent("Relação com as plataformas");
    // Só as avaliações: nada das plataformas nem da frase dos períodos (a ficha tem as dela).
    expect(screen.queryByTestId("plataforma-elefante")).toBeNull();
    expect(screen.queryByTestId("frase-periodos-diferentes")).toBeNull();
    expect(container.textContent).not.toMatch(/\bTPS\b|Spearman|coorte|correla/i);
  });

  it("simples: os avisos de cada indicador num recolhível FECHADO, depois da tabela — os mesmos textos, um por linha", async () => {
    const base = respostaTecnica();
    const dados: RespostaAnaliseEscola = {
      ...base,
      indicadores: [{
        ...base.indicadores[0],
        avisos: ["O SARESP tem escala própria (sintético).", "Média instável (TPS = 0: participação abaixo do mínimo)."],
        quebras: [{ entre: [2024, 2025], etapa: "2_ano", texto: "a escala mudou (sintético)." }],
      }, base.indicadores[1]],
    };
    renderComApp(<ConteudoAnaliseEscola dados={dados} simples soAvaliacoes />, { usuario: secretaria });
    const saresp = await screen.findByTestId("analise-escola-indicador-saresp");
    // A tabela da escola e a rede de referência à vista; nenhuma lista âmbar aberta na frente.
    expect(saresp).toHaveTextContent("151,8");
    expect(saresp).toHaveTextContent("Cidade Sintética — rede municipal");
    expect(saresp).not.toHaveTextContent("escala própria");
    const avisos = within(saresp).getByTestId("avisos-indicador-saresp");
    const botao = within(avisos).getByRole("button", { name: "Avisos sobre estes números (3)" });
    expect(botao).toHaveAttribute("aria-expanded", "false");
    expect(within(saresp).getByRole("table").compareDocumentPosition(avisos) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    // Abertos: os mesmos textos (avisos e quebras), em língua simples, cada um uma vez.
    await userEvent.click(botao);
    expect(within(avisos).getAllByRole("listitem").map((li) => li.textContent)).toEqual([
      "O SARESP tem escala própria (sintético).",
      "Média instável (poucos alunos fizeram a prova).",
      "Entre 2024 e 2025 (2º ano): a escala mudou (sintético).",
    ]);
    // O indicador sem aviso não ganha recolhível vazio.
    expect(within(screen.getByTestId("analise-escola-indicador-iee")).queryByTestId("avisos-indicador-iee")).toBeNull();
  });

  it("simples com as plataformas: as limitações passam pela língua do fluxo principal", async () => {
    renderComApp(<ConteudoAnaliseEscola dados={respostaTecnica()} simples />, { usuario: secretaria });
    const limitacoes = await screen.findByTestId("limitacoes-plataformas");
    await userEvent.click(within(limitacoes).getByRole("button"));
    expect(limitacoes).toHaveTextContent("Grupo de alunos: alunos ativos do 1º ao 5º ano");
    expect(limitacoes).not.toHaveTextContent(/Spearman|Coorte/);
  });

  it("o modo completo (Visão da Escola, Análises avançadas) continua igual: o termo técnico e a relação ficam", async () => {
    renderComApp(<ConteudoAnaliseEscola dados={respostaTecnica()} />, { usuario: coordenador });
    const iee = await screen.findByTestId("analise-escola-indicador-iee");
    expect(iee).toHaveTextContent("calculado com médias de TPS = 0");
    expect(iee).toHaveTextContent("escola com TPS = 0");
    expect(screen.getByRole("heading", { level: 3, name: "Indicadores oficiais da escola" })).toBeInTheDocument();
    expect(within(iee).getByRole("heading", { level: 4, name: "IEE" })).toBeInTheDocument();
    expect(screen.getByTestId("analise-escola-indisponiveis")).toHaveTextContent("Relação com as plataformas");
    expect(screen.getByTestId("plataforma-elefante")).toBeInTheDocument();
    expect(screen.queryByTestId("legenda-instavel")).toBeNull();
    // Os avisos continuam abertos, antes da tabela (sem o recolhível do modo simples).
    const saresp = screen.getByTestId("analise-escola-indicador-saresp");
    expect(saresp).toHaveTextContent("Média instável (TPS = 0");
    expect(screen.queryByTestId("avisos-indicador-saresp")).toBeNull();
    expect(within(saresp).getByText(/Média instável \(TPS = 0/).compareDocumentPosition(within(saresp).getByRole("table"))
      & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  // O formato REAL do servidor (`indicadores_da_escola`): os indicadores vêm SEMPRE, com a série da
  // escola mesmo sem número — o porquê sai do conteúdo das séries, nunca da lista vazia.
  it("simples sem resultado oficial, nada importado: os indicadores todos, sem ponto — o porquê certo", async () => {
    const semNada = { ...resposta(1, "EMEF Sintética Alfa"), indicadores: indicadoresSemNumeroDaEscola(1, "EMEF Sintética Alfa") };
    renderComApp(<ConteudoAnaliseEscola dados={semNada} simples soAvaliacoes />, { usuario: secretaria });
    expect(await screen.findByTestId("avaliacoes-escola-sem-resultado")).toHaveTextContent(
      "Esta escola ainda não tem resultado oficial no Constela: nenhuma edição importada das avaliações com resultado "
      + "por escola (SARESP, IEE, Ideb, Saeb) traz resultados desta escola nem da rede municipal.");
    // Os blocos da escola (o ICA é só da rede) dizem a falta por extenso; nada de "nenhum indicador".
    for (const chave of ["saresp", "iee", "ideb", "saeb"]) {
      expect(screen.getByTestId(`analise-escola-indicador-${chave}`)).toHaveTextContent("Sem número oficial desta escola importado.");
    }
    expect(screen.queryByTestId("analise-escola-indicador-ica")).toBeNull();
    expect(screen.queryByTestId("analise-escola-sem-indicadores")).toBeNull();
  });

  it("simples sem resultado oficial, só a rede com número: 'trazem resultados da rede municipal, mas nenhum desta escola'", async () => {
    const soRede = { ...resposta(1, "EMEF Sintética Alfa"),
      indicadores: indicadoresSemNumeroDaEscola(1, "EMEF Sintética Alfa", { daRede: REDE_SINTETICA }) };
    renderComApp(<ConteudoAnaliseEscola dados={soRede} simples soAvaliacoes />, { usuario: secretaria });
    expect(await screen.findByTestId("avaliacoes-escola-sem-resultado")).toHaveTextContent(
      "Esta escola ainda não tem resultado oficial no Constela: as edições importadas trazem resultados da rede "
      + "municipal, mas nenhum desta escola.");
    expect(screen.getByTestId("analise-escola-indicador-saresp")).toHaveTextContent("212,4");
  });

  it("só o ICA da rede importado (ele não existe por escola): o porquê não diz que a escola ficou fora dos arquivos", async () => {
    const soIca = { ...resposta(1, "EMEF Sintética Alfa"),
      indicadores: indicadoresSemNumeroDaEscola(1, "EMEF Sintética Alfa", {
        daRede: { "ica|2_ano|lp": [ponto(2025, 58, { casas: 0 })] } }) };
    expect(porqueSemResultadoOficial(soIca)).toBe("nenhuma edição importada das avaliações com resultado por escola "
      + "(SARESP, IEE, Ideb, Saeb) traz resultados desta escola nem da rede municipal");
    renderComApp(<ConteudoAnaliseEscola dados={soIca} simples soAvaliacoes />, { usuario: secretaria });
    const frase = await screen.findByTestId("avaliacoes-escola-sem-resultado");
    expect(frase).not.toHaveTextContent("trazem resultados da rede municipal, mas nenhum desta escola");
  });

  it("o porquê pelas edições da escola: o motivo comum a todas, ou a frase geral; com número, nenhuma frase", async () => {
    const base = resposta(1, "EMEF Sintética Alfa");
    const comMotivos = (...motivos: string[]): RespostaAnaliseEscola => ({
      ...base,
      indicadores: indicadoresSemNumeroDaEscola(1, "EMEF Sintética Alfa", {
        daRede: REDE_SINTETICA,
        pontosDaEscola: () => motivos.map((m, i) => ponto(2023 + i, null, {
          motivo_ausencia: m, texto_ausencia: `motivo ${m} (sintético)` })),
      }),
    });
    expect(porqueSemResultadoOficial(comMotivos("fora_do_arquivo", "fora_do_arquivo")))
      .toBe("a escola não aparece nos arquivos oficiais importados");
    expect(porqueSemResultadoOficial(comMotivos("nao_divulgado")))
      .toBe("os arquivos oficiais importados não divulgam número desta escola");
    expect(porqueSemResultadoOficial(comMotivos("codigo_inep_alterado", "cadastrado_depois_da_importacao")))
      .toMatch(/^o código INEP da escola foi cadastrado ou mudou depois da importação: .*quem importa é o administrador global$/);
    expect(porqueSemResultadoOficial(comMotivos("fora_do_arquivo", "nao_divulgado"))).toBe(
      "as edições importadas não trazem número desta escola; cada avaliação, abaixo, diz o motivo de cada edição");
    // Com número da escola, não há frase de falta.
    expect(temResultadoOficial(base)).toBe(true);
    renderComApp(<ConteudoAnaliseEscola dados={base} simples soAvaliacoes />, { usuario: secretaria });
    await screen.findByTestId("analise-escola-indicador-saresp");
    expect(screen.queryByTestId("avaliacoes-escola-sem-resultado")).toBeNull();
  });

  it("simples sem resultado oficial e sem código INEP: o aviso do INEP, sem a frase repetida", async () => {
    const semInep: RespostaAnaliseEscola = {
      ...resposta(1, "EMEF Sintética Alfa"),
      escola: { id: 1, nome: "EMEF Sintética Alfa", codigo_inep: null, pendencia: "sem_codigo_inep" },
      indicadores: indicadoresSemNumeroDaEscola(1, "EMEF Sintética Alfa", { daRede: REDE_SINTETICA }),
    };
    expect(porqueSemResultadoOficial(semInep)).toMatch(/^a escola está sem código INEP no cadastro/);
    renderComApp(<ConteudoAnaliseEscola dados={semInep} simples soAvaliacoes />, { usuario: secretaria });
    expect(await screen.findByTestId("analise-escola-sem-inep")).toHaveTextContent("sem código INEP no cadastro");
    expect(screen.queryByTestId("avaliacoes-escola-sem-resultado")).toBeNull();
  });
});

// =============================================================================
// Na Visão da Escola
// =============================================================================

function TrocarParaB() {
  const { selecionarEscola } = useApp();
  return <button type="button" onClick={() => selecionarEscola(2)}>trocar para a escola B</button>;
}

function resumoEscola(id: number, turma: string) {
  return { escola: { id, nome: `Escola ${id}` }, turmas: [{ turma: { id: id * 10, nome: turma, ano_escolar: "5º Ano" },
    total_alunos: 10, media_geral: 50, media_matific: 50, media_elefante: 50, indicadores: {} }] };
}

function montarVisao(usuario: ReturnType<typeof usuarioFake>, analiseA = resposta(1, "EMEF Sintética A")) {
  responder("GET", "/escolas/1/resumo-escola", resumoEscola(1, "TURMA-DE-A"));
  responder("GET", "/escolas/2/resumo-escola", resumoEscola(2, "TURMA-DE-B"));
  responder("GET", "/escolas/1/analise", analiseA);
  renderComApp(<><TrocarParaB /><VisaoEscola /></>, {
    usuario, rota: "/escola", escolaSelecionada: 1,
    escolas: [escolaFake({ id: 1, nome: "Escola A" }), escolaFake({ id: 2, nome: "Escola B" })],
  });
}

describe("Visão da Escola — a análise da escola entra no lugar dos indicadores", () => {
  it("a seção é a da análise (não chama mais /escolas/{id}/indicadores)", async () => {
    montarVisao(coordenador);
    expect(await screen.findByTestId("analise-escola-nome")).toHaveTextContent("EMEF Sintética A");
    expect(api.mock.calls.some(([c]) => String(c).includes("/indicadores"))).toBe(false);
  });

  it.each([["admin global", admin], ["Secretaria", secretaria]])(
    "%s: se a leitura da escola B falha, mostra o erro — nunca os números da escola A", async (_nome, usuario) => {
      responderErro("GET", "/escolas/2/analise", 500, "FALHA-DA-ESCOLA-B");
      montarVisao(usuario);
      expect(await screen.findByTestId("analise-escola-nome")).toHaveTextContent("EMEF Sintética A");
      await userEvent.click(screen.getByRole("button", { name: "trocar para a escola B" }));
      expect(await screen.findByText("TURMA-DE-B")).toBeInTheDocument();
      // Os números de A saem já no carregamento de B (sem esperar a resposta).
      expect(screen.queryByText("EMEF Sintética A")).not.toBeInTheDocument();
      expect(await screen.findByText(/FALHA-DA-ESCOLA-B/, undefined, { timeout: 3000 })).toBeInTheDocument();
      expect(screen.queryByTestId("analise-escola-indicador-saresp")).not.toBeInTheDocument();
      expect(screen.queryByTestId("analise-escola-nome")).not.toBeInTheDocument();
    });

  it("a Secretaria (Escolas › ficha › Ver as turmas) vê o modo SIMPLES: sem sigla técnica nem a relação", async () => {
    montarVisao(secretaria, respostaTecnica());
    const iee = await screen.findByTestId("analise-escola-indicador-iee");
    expect(iee).toHaveTextContent("calculado com médias instáveis");
    const secao = screen.getByTestId("analise-escola");
    expect(secao).not.toHaveTextContent(/\bTPS\b|Spearman|coorte|correla/i);
    expect(screen.getByTestId("analise-escola-indisponiveis")).not.toHaveTextContent("Relação com as plataformas");
  });

  it.each([["admin global", admin], ["coordenação", coordenador]])(
    "%s: continua no modo completo na Visão da Escola", async (_nome, usuario) => {
      montarVisao(usuario, respostaTecnica());
      const iee = await screen.findByTestId("analise-escola-indicador-iee");
      expect(iee).toHaveTextContent("calculado com médias de TPS = 0");
      expect(screen.getByTestId("analise-escola-indisponiveis")).toHaveTextContent("Relação com as plataformas");
    });

  it("com sucesso, a seção passa a mostrar a escola B (com o nome dela)", async () => {
    responder("GET", "/escolas/2/analise", resposta(2, "EMEF Sintética B"));
    montarVisao(admin);
    expect(await screen.findByTestId("analise-escola-nome")).toHaveTextContent("EMEF Sintética A");
    await userEvent.click(screen.getByRole("button", { name: "trocar para a escola B" }));
    expect(await screen.findByText("EMEF Sintética B", { selector: "[data-testid=analise-escola-nome]" }))
      .toBeInTheDocument();
    expect(screen.queryByText("EMEF Sintética A")).not.toBeInTheDocument();
  });
});
