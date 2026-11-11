/**
 * Análises avançadas (/rede/analise) — a área técnica da rede, e as peças que saíram dela:
 *
 *  - a aba padrão (Diagnóstico exploratório), o período global indo para a API, os filtros
 *    (período, escola, série) dizendo onde valem; a Secretaria usa a própria rede;
 *  - SEM DUPLICAÇÃO: o que a antiga Visão geral mostrava tem um lugar só — destaques, avisos
 *    do catálogo, notas e metodologia em Avaliações externas; cartões, cobertura e lacunas em
 *    Elefante e Matific (as telas da Secretaria têm os testes delas). Aqui fica "o que dá para
 *    relacionar hoje", que abre a aba Relação;
 *  - os cartões, a cobertura e as limitações das plataformas (hoje na tela Elefante e
 *    Matific) e o detalhe de um indicador — série histórica e escolas numa edição (hoje em
 *    Avaliações externas) — conferidos DIRETO nos componentes, com o mesmo arranjo: ausência
 *    por extenso (nunca 0), referência só quando comparável, "Detalhes e fontes" recolhido,
 *    escolas em ordem de NOME, grupo pequeno protegido;
 *  - Relação: "não calculável" com o motivo + lado a lado; calculável com o coeficiente,
 *    o IC e o n; SEMPRE o aviso de causalidade e a metodologia recolhível;
 *  - Análise detalhada por escola: a escola do filtro, a sem código INEP dizendo a pendência
 *    e a frase de que avaliação oficial e plataformas são de períodos diferentes;
 *  - o admin global escolhe a rede; a Secretaria usa a própria.
 *
 * Números, nomes, códigos e arquivos INVENTADOS (regra D13): nada de arquivo oficial.
 */
import { describe, expect, it } from "vitest";

import type { FonteOficial } from "../components/SeloFonte";
import { useApp } from "../context/AppContext";
import AnaliseEducacional from "../pages/analise/AnaliseEducacional";
import type {
  IndicadorAnalise, LinhaEscolaAnalise, PontoAnalise, RespostaAnaliseEscola, RespostaIndicador,
  RespostaIndicadoresRede, RespostaPlataformas, RespostaRelacao, SerieAnalise,
} from "../pages/analise/tipos";
import { diagnostico } from "./AnaliseFixturesDiagnostico";
import { IndicadorEmDetalhe, PlataformasNoPeriodo } from "./AnaliseHarness";
import {
  api, renderComApp, responder, responderErro, screen, userEvent, usuarioFake, waitFor, within,
} from "./utils";

const secretaria = usuarioFake({ nome: "Secretaria", cargo: "coordenador", rede_id: 1, escola_id: null });
const admin = usuarioFake({ nome: "Root", cargo: "admin", is_global: true, escola_id: null });

// =============================================================================
// Fixtures (inventadas)
// =============================================================================

const FONTE_MUN: FonteOficial = {
  importacao_id: 21, fonte_nome: "SEDUC-SP — Proficiência do SARESP por município",
  arquivo_nome: "saresp_municipio_sintetico_2025.csv", arquivo_data: null, last_modified_origem: null,
  url_origem: null, edicao_arquivo: 2025, versao_rotulo: null, importado_em: "2026-10-17T12:00:00",
  coletado_em: null, citacao: null, licenca: "Dados abertos sintéticos: citar a fonte.",
  parser: "seduc_saresp_municipio", modo: "upload", notas: [], data_arquivo: "2026-01-12",
  data_arquivo_origem: "last_modified",
};
const FONTE_ICA: FonteOficial = {
  ...FONTE_MUN, importacao_id: 5, fonte_nome: "INEP — Indicador Criança Alfabetizada",
  arquivo_nome: "ica_sintetico_2025.xlsx", parser: "inep_ica_municipios", arquivo_data: "2031-05-20T10:30:00",
  data_arquivo: null, data_arquivo_origem: null,
};

function indicador(over: Partial<IndicadorAnalise>): IndicadorAnalise {
  return {
    chave: "x", nome: "X", orgao: "INEP", oficial: true, unidade: "pontos", escala: "escala_saresp",
    disponivel: true, motivo_indisponivel: null, abrangencias: ["rede", "escola"], por_escola: true,
    etapas: ["5_ano"], componentes: ["lp", "mt"], edicoes: [2022, 2023, 2025], edicao_mais_recente: 2025,
    tem_meta: false, avisos: [], ...over,
  };
}

const ICA = indicador({
  chave: "ica", nome: "Indicador Criança Alfabetizada", orgao: "INEP", unidade: "%", escala: "percentual",
  abrangencias: ["rede"], por_escola: false, etapas: ["2_ano"], componentes: ["lp"], edicoes: [2023, 2024, 2025],
  tem_meta: true, avisos: ["O ICA é o indicador da REDE municipal: não existe por escola."],
});
const SARESP = indicador({
  chave: "saresp", nome: "SARESP", orgao: "SEDUC-SP", etapas: ["5_ano", "2_ano"],
  avisos: ["O SARESP tem escala própria, da SEDUC-SP: não se compara com o Saeb."],
});
const IDEB = indicador({
  chave: "ideb", nome: "Ideb", orgao: "INEP", unidade: "índice", escala: "indice_ideb", disponivel: false,
  motivo_indisponivel: "sem_importacao",
  texto_indisponivel: "nenhum arquivo oficial deste indicador foi importado para esta rede",
  etapas: ["anos_iniciais"], componentes: [], edicoes: [], edicao_mais_recente: null, tem_meta: true,
});

const ESCOLAS = [
  { id: 3, nome: "EMEF Sintética Beta", codigo_inep: "35990003", pendencia: null },
  { id: 2, nome: "EMEF Sintética Alfa", codigo_inep: "35990002", pendencia: null },
  { id: 4, nome: "EMEI Sintética Gama", codigo_inep: null, pendencia: "sem_codigo_inep" },
];

function base(over: Partial<RespostaIndicadoresRede> = {}): RespostaIndicadoresRede {
  return {
    rede: { id: 1, nome: "Rede Sintética Norte", codigo_ibge: "3599999" },
    indicadores: [ICA, SARESP, IDEB],
    destaques: [
      { indicador: "ica", rotulo: "ICA da rede (2º ano)", edicao: 2025, valor: 47, casas: 0, unidade: "%",
        meta: 51, meta_casas: 0, diferenca_meta: -4, diferenca_casas: 0, situacao_meta: "nao_atingiu",
        etapa: "2_ano", componente: "lp", fonte_id: 5,
        serie: [{ edicao: 2023, valor: 41 }, { edicao: 2024, valor: null }, { edicao: 2025, valor: 47 }] },
      { indicador: "saresp", rotulo: "SARESP da rede — 5º ano, Língua Portuguesa", edicao: 2025, valor: 212.4,
        casas: 1, unidade: "pontos", meta: null, diferenca_meta: null, situacao_meta: null, etapa: "5_ano",
        componente: "lp", fonte_id: 21,
        serie: [{ edicao: 2022, valor: 205.3 }, { edicao: 2023, valor: null }, { edicao: 2025, valor: 212.4 }] },
    ],
    estimativas: [{ chave: "crianca_alfabetizada",
      nome: "Estimativa Constela de alfabetização — não é o indicador oficial", edicoes: [2025] }],
    escolas: ESCOLAS,
    alertas: [
      { tipo: "cadastro", texto: "1 escola(s) sem código INEP no cadastro: os números oficiais não casam.",
        escolas: [4] },
      { tipo: "insuficiente", indicador: "saresp", escolas: [4, 2],
        texto: "SARESP 2025: 2 de 3 escola(s) sem resultado oficial — o motivo de cada uma está na visão por escolas." },
      { tipo: "metodologia", escolas: [],
        texto: "As plataformas têm dados do ano letivo 2026; as avaliações por escola vão até 2025." },
    ],
    metodologia_resumo: [
      "Sem resultado não é zero: cada falta vem com o motivo (texto sintético).",
      "Sem ranking: as escolas aparecem sempre em ordem alfabética (texto sintético).",
    ],
    fontes: { "5": FONTE_ICA, "21": FONTE_MUN },
    ...over,
  };
}

// O denominador é o dos alunos MEDIDOS (Elefante: com conta; Matific: com dado no
// período): 410 de 600 = 68,3%. Os 40 sem conta ficam fora (não contam como zero).
const ELEFANTE_REDE = {
  alunos_medidos: 600, alunos_sem_conta: 40, alunos_com_leitura: 410, participacao_pct: 68.3,
  livros_por_aluno: 3.71, minutos_por_aluno: 88.4, nivel_medio: "K", taxa_acerto_pct: 72.5,
  janela_questoes: { inicio: "2026-09-22", fim: "2026-10-19" }, coleta_parcial: false, coberto_ate: null,
  texto_cobertura: null,
};
const MATIFIC_REDE = {
  alunos_medidos: 500, alunos_com_retrato: 500, participacao_pct: 78.1, atividades_por_aluno: 14.25,
  estrelas_por_aluno: null, desempenho_medio: 2.6, coleta_parcial: false, coberto_ate: null, texto_cobertura: null,
};
const TEXTO_SUPRESSAO = "poucos alunos neste recorte (ou escondido junto com um recorte pequeno, para que nenhum "
  + "seja descoberto pela diferença do total): os números não aparecem, para proteger as crianças";

function plataformas(over: Partial<RespostaPlataformas> = {}): RespostaPlataformas {
  return {
    janela: { inicio: "2026-01-01", fim: "2026-12-31", rotulo: "Ano letivo de 2026" },
    modulos: { elefante: true, matific: true }, k_minimo: 5,
    rede: { alunos: 640, elefante: ELEFANTE_REDE, matific: MATIFIC_REDE, escopo_blocos: "escolas_visiveis",
            texto_blocos: "Os números da rede somam só as escolas e as séries mostradas (texto sintético)." },
    escolas: [
      { escola_id: 3, nome: "EMEF Sintética Beta", alunos: 120,
        elefante: { ...ELEFANTE_REDE, alunos_medidos: 100, alunos_com_leitura: 85, participacao_pct: 85 },
        matific: { ...MATIFIC_REDE, alunos_medidos: 90, alunos_com_retrato: 90, participacao_pct: 75 },
        blocos_parciais: true, texto_blocos: "Os números desta escola somam só as séries mostradas (sintético).",
        series: [
          { serie: 2, alunos: 60, suprimido: false,
            elefante: { ...ELEFANTE_REDE, alunos_medidos: 55, participacao_pct: 70 },
            matific: { ...MATIFIC_REDE, participacao_pct: null, motivo_sem_dado: "poucos_alunos_medidos",
                       texto_sem_dado: "menos de 5 alunos com dado desta plataforma no período" } },
          { serie: 3, alunos: null, suprimido: true, motivo_supressao: "suprimido", texto_supressao: TEXTO_SUPRESSAO,
            elefante: null, matific: null },
          { serie: 5, alunos: 55, suprimido: false, elefante: { ...ELEFANTE_REDE, participacao_pct: 60 },
            matific: { ...MATIFIC_REDE, participacao_pct: 80 } },
        ] },
      { escola_id: 2, nome: "EMEF Sintética Alfa", alunos: 300,
        elefante: ELEFANTE_REDE, matific: MATIFIC_REDE,
        series: [
          { serie: 2, alunos: 150, suprimido: false, elefante: { ...ELEFANTE_REDE, participacao_pct: 50 },
            matific: { ...MATIFIC_REDE, participacao_pct: 40 } },
          { serie: 5, alunos: 150, suprimido: false, elefante: { ...ELEFANTE_REDE, participacao_pct: 55 },
            matific: { ...MATIFIC_REDE, participacao_pct: 45 } },
        ] },
      // Escola suprimida: nem a cobertura, nem as datas, nem as séries.
      { escola_id: 4, nome: "EMEI Sintética Gama", alunos: null, suprimido: true, motivo_supressao: "suprimido",
        texto_supressao: TEXTO_SUPRESSAO, cobertura: null, ultima_coleta: null, coberto_ate: null,
        dias_desde_ultima_coleta: null, elefante: null, matific: null, series: [] },
    ],
    cobertura: { escopo: "escolas_visiveis",
                 ultima_coleta: { elefante: "2026-10-18T03:10:00", matific: "2026-10-19T03:12:00" },
                 escolas_sem_coleta: [], escolas_sem_coleta_no_periodo: { elefante: [], matific: [] },
                 escolas_coleta_parcial: { elefante: [], matific: [] },
                 primeiro_evento_elefante: "2026-02-03", dias_desde_ultima_coleta: 1 },
    limitacoes: ["Questões do Elefante: o intervalo real é o das coletas."],
    ...over,
  };
}

function ponto(edicao: number, valor: number | null, over: Partial<PontoAnalise> = {}): PontoAnalise {
  return {
    edicao, valor, casas: valor == null ? null : 1, motivo_ausencia: valor == null ? "nao_divulgado" : null,
    texto_ausencia: valor == null ? "não divulgado no arquivo oficial" : null, meta: null, meta_casas: null,
    diferenca_meta: null, situacao_meta: null, instavel: false, fonte_id: 21, ...over,
  };
}

function serie(over: Partial<SerieAnalise>): SerieAnalise {
  return {
    id: "rede_municipal", rotulo: "Cidade Sintética — rede municipal", papel: "principal", abrangencia: "rede",
    escola_id: null, rede_ensino: "municipal", mesma_rede: true, comparavel: true, motivo_nao_comparavel: null,
    pontos: [], ...over,
  };
}

function detalheSaresp(over: Partial<RespostaIndicador> = {}): RespostaIndicador {
  return {
    indicador: SARESP,
    filtros: { etapa: "5_ano", componente: "lp", escola_id: null, de: null, ate: null, visao: "serie", edicao: null },
    opcoes: { etapas: ["5_ano", "2_ano"], componentes: ["lp", "mt"], edicoes: [2022, 2023, 2025],
              escolas: ESCOLAS.map((e) => ({ id: e.id, nome: e.nome, tem_dado: e.id !== 4 })) },
    series: [
      serie({ pontos: [ponto(2022, 205.3), ponto(2023, null), ponto(2025, 212.4)] }),
      serie({ id: "uf_redes_municipais", rotulo: "Estado de São Paulo — redes municipais", papel: "referencia",
              abrangencia: "uf", pontos: [ponto(2022, 208.8), ponto(2023, 210.1), ponto(2025, 214.6)] }),
      serie({ id: "uf_rede_estadual", rotulo: "Estado de São Paulo — rede estadual", papel: "contexto",
              abrangencia: "uf", rede_ensino: "estadual", mesma_rede: false, comparavel: false,
              motivo_nao_comparavel: "Outra rede: é a rede ESTADUAL. Só contexto.",
              pontos: [ponto(2025, 231.9)] }),
    ],
    escolas: [],
    quebras: [],
    avisos: ["O SARESP tem escala própria, da SEDUC-SP: não se compara com o Saeb."],
    fontes: { "21": FONTE_MUN },
    ...over,
  };
}

function detalheIca(): RespostaIndicador {
  return {
    indicador: ICA,
    filtros: { etapa: "2_ano", componente: "lp", escola_id: null, de: null, ate: null, visao: "serie", edicao: null },
    opcoes: { etapas: ["2_ano"], componentes: ["lp"], edicoes: [2023, 2024, 2025], escolas: [] },
    series: [serie({ pontos: [
      ponto(2023, 41, { casas: 0, meta: null, fonte_id: 5 }),
      ponto(2024, null, { motivo_ausencia: "participacao_baixa", texto_ausencia: "sem resultado: participação abaixo de 70%",
                          fonte_id: 5 }),
      ponto(2025, 47, { casas: 0, meta: 51, meta_casas: 0, diferenca_meta: -4, diferenca_casas: 0,
                        situacao_meta: "nao_atingiu", fonte_id: 5 }),
    ] })],
    escolas: [], quebras: [], avisos: [], fontes: { "5": FONTE_ICA },
  };
}

function linhaEscola(id: number, nome: string, valor: number | null, over: Partial<LinhaEscolaAnalise> = {}) {
  return {
    escola_id: id, nome, valor, casas: valor == null ? null : 1,
    motivo_ausencia: valor == null ? "nao_divulgado" : null,
    texto_ausencia: valor == null ? "não divulgado no arquivo oficial" : null,
    meta: null, diferenca_meta: null, instavel: false, fonte_id: 21, ...over,
  } as LinhaEscolaAnalise;
}

const CRITERIOS = { metodo: "Spearman", n_minimo: 8, k_minimo_alunos: 5, exige_mesmo_ano_letivo: true,
                    exige_mesma_serie: true, so_oficial: true, mesma_escala: true };

function relacao(over: Partial<RespostaRelacao> = {}): RespostaRelacao {
  return {
    calculavel: false, motivos: ["periodo_sem_sobreposicao"],
    textos: ["Período sem sobreposição: a avaliação é de 2025 e o período das plataformas é o ano letivo de 2026."],
    criterios: CRITERIOS, indicador: SARESP,
    metrica: { chave: "livros_por_aluno", rotulo: "Livros novos por aluno (Elefante)", plataforma: "elefante" },
    pares: [
      { escola_id: 3, nome: "EMEF Sintética Beta", valor_oficial: 214.2, casas_oficial: 1, edicao: 2025,
        valor_plataforma: 3.4, janela: "2026", incluido: false,
        motivo_exclusao: "Período sem sobreposição: a avaliação é de 2025." },
      { escola_id: 2, nome: "EMEF Sintética Alfa", valor_oficial: null, edicao: 2025,
        texto_ausencia_oficial: "não divulgado no arquivo oficial", valor_plataforma: 2.9, janela: "2026",
        incluido: false, motivo_exclusao: "Período sem sobreposição: a avaliação é de 2025." },
    ],
    n: 0, coeficiente: null, ic95: null,
    metodologia: "Unidade: a escola. Só números oficiais, na mesma série e no mesmo ano letivo (texto sintético).",
    ...over,
  };
}

function analiseEscola(id: number, nome: string, over: Partial<RespostaAnaliseEscola> = {}): RespostaAnaliseEscola {
  return {
    escola: { id, nome, codigo_inep: `3599000${id}`, pendencia: null },
    rede: { id: 1, nome: "Rede Sintética Norte" },
    indicadores: [{
      chave: "saresp", nome: "SARESP", unidade: "pontos", avisos: [],
      series: [
        serie({ id: `escola_${id}`, rotulo: nome, abrangencia: "escola", escola_id: id, etapa: "5_ano",
                componente: "lp", pontos: [ponto(2023, null), ponto(2025, 219.6)] }),
        serie({ papel: "referencia", etapa: "5_ano", componente: "lp",
                pontos: [ponto(2023, 210.1), ponto(2025, 212.4)] }),
      ],
    }],
    plataformas: {
      janela: { inicio: "2026-01-01", fim: "2026-12-31", rotulo: "Ano letivo de 2026" }, alunos: 120,
      elefante: ELEFANTE_REDE, matific: MATIFIC_REDE, modulos: { elefante: true, matific: true }, k_minimo: 5,
      series: [
        { serie: 2, alunos: null, suprimido: true,
          motivo_supressao: "suprimido", texto_supressao: TEXTO_SUPRESSAO,
          elefante: null, matific: null },
        { serie: 5, alunos: 31, suprimido: false, elefante: { ...ELEFANTE_REDE, participacao_pct: 58.1 },
          matific: MATIFIC_REDE },
      ],
    },
    comparacoes_indisponiveis: [{ tema: "ica", texto: "O ICA é da rede: não existe por escola." }],
    fontes: { "21": FONTE_MUN },
    ...over,
  };
}

function semear(over: Partial<RespostaIndicadoresRede> = {}) {
  responder("GET", "/redes/1/analise/indicadores", base(over));
  responder("GET", "/redes/1/analise/plataformas", plataformas());
  // A aba padrão é o Diagnóstico exploratório (o mundo sintético das abas novas).
  responder("GET", "/redes/1/analise/diagnostico", diagnostico());
}

const chamadas = (prefixo: string) =>
  api.mock.calls.map(([c]) => String(c)).filter((c) => c.startsWith(prefixo));
const query = (url: string) => new URLSearchParams(url.split("?")[1] ?? "");

// =============================================================================
// Análises avançadas: cabeçalho, filtros e o Diagnóstico (a aba padrão)
// =============================================================================

describe("Análises avançadas — cabeçalho, filtros e a aba padrão", () => {
  it("abre no Diagnóstico exploratório, com o período global indo para a API — a Secretaria usa a própria rede", async () => {
    semear();
    renderComApp(<AnaliseEducacional />, { rota: "/rede/analise", usuario: secretaria });
    expect(await screen.findByRole("heading", { level: 1, name: "Análises avançadas" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Diagnóstico exploratório" })).toHaveAttribute("aria-selected", "true");
    expect(await screen.findByTestId("tabela-diagnostico")).toBeInTheDocument();
    expect(query(chamadas("/redes/1/analise/diagnostico")[0]).get("periodo")).toBe("ano_letivo");
    // A Secretaria usa a própria rede (não lista redes).
    expect(api.mock.calls.some(([c]) => c === "/redes")).toBe(false);
    // Sem duplicação: o que tem tela própria não se repete aqui (destaques, avisos do catálogo,
    // notas, metodologia, cartões e lacunas das plataformas).
    for (const testId of ["destaque-ica", "alertas-analise", "estimativas-fora", "sem-registro-fora",
                          "metodologia-resumo", "plataforma-elefante", "lacunas-por-serie"]) {
      expect(screen.queryByTestId(testId)).not.toBeInTheDocument();
    }
    expect(chamadas("/redes/1/analise/plataformas")).toHaveLength(0);
  });

  it("os filtros dizem onde valem: a escola e a série vão para a análise detalhada por escola", async () => {
    semear();
    responder("GET", /^\/escolas\/\d+\/analise/, (c: string) => {
      const id = Number(c.split("/")[2]);
      return analiseEscola(id, ESCOLAS.find((e) => e.id === id)?.nome ?? `escola ${id}`);
    });
    renderComApp(<AnaliseEducacional />, { rota: "/rede/analise?ver=escola", usuario: secretaria });
    expect(await screen.findByTestId("onde-valem-os-filtros"))
      .toHaveTextContent("O período vale para o lado das plataformas (Elefante e Matific); as avaliações oficiais têm edição própria. "
        + "A série vale para a análise detalhada por escola.");
    // A escola sem INEP aparece marcada no filtro.
    expect(screen.getByRole("option", { name: "EMEI Sintética Gama (sem código INEP)" })).toBeInTheDocument();

    await userEvent.selectOptions(screen.getByLabelText("Escola"), "3");
    await waitFor(() => expect(chamadas("/escolas/3/analise")).toHaveLength(1));
    expect(await screen.findByTestId("por-escola-nome")).toHaveTextContent("EMEF Sintética Beta");
    await userEvent.selectOptions(screen.getByLabelText("Série"), "5");
    expect(await screen.findByTestId("analise-escola-filtros")).toHaveTextContent("e série (5º ano)");
  });

  it("a recusa da API aparece (não some em silêncio)", async () => {
    responderErro("GET", "/redes/1/analise/indicadores", 403, "Acesso negado a esta rede.");
    renderComApp(<AnaliseEducacional />, { rota: "/rede/analise", usuario: secretaria });
    expect(await screen.findByText(/Acesso negado a esta rede/)).toBeInTheDocument();
  });
});

// =============================================================================
// Plataformas no período — os componentes que a antiga Visão geral mostrava (hoje na tela
// Elefante e Matific): conferidos direto, com o mesmo arranjo, para não perder a proteção
// =============================================================================

describe("Plataformas no período — cartões, cobertura e limitações (ausência ≠ zero, grupo pequeno)", () => {
  it("o 'X de Y' usa o denominador do percentual; quem fica fora é dito à parte; sem dado nunca vira 0", async () => {
    renderComApp(<PlataformasNoPeriodo escolas={ESCOLAS} dados={plataformas()} />, { usuario: secretaria });
    const elefante = await screen.findByTestId("plataforma-elefante");
    expect(elefante).toHaveTextContent("68,3%");
    expect(elefante).toHaveTextContent("410 de 600 alunos com conta leram no período");
    expect(elefante).not.toHaveTextContent("410 de 640");
    expect(screen.getByTestId("fora-da-conta-elefante"))
      .toHaveTextContent("40 de 640 alunos do recorte não entram na conta: sem conta no Elefante");
    expect(elefante).toHaveTextContent("3,71");
    expect(elefante).toHaveTextContent("medido de 22/09/2026 a 19/10/2026");
    const matific = screen.getByTestId("plataforma-matific");
    expect(matific).toHaveTextContent("sobre 500 alunos com dado no período");
    expect(screen.getByTestId("fora-da-conta-matific")).toHaveTextContent("140 de 640 alunos do recorte");
    expect(within(matific).getByText("Estrelas por aluno").parentElement).toHaveTextContent("sem dado no período");
    expect(matific).not.toHaveTextContent(/\b0,0\b/);
    // Os blocos da rede somam só o que está à vista (o texto do backend).
    expect(screen.getByTestId("texto-blocos")).toHaveTextContent("somam só as escolas e as séries mostradas");
    // A escola suprimida não aparece nas listas da cobertura (nem as datas dela).
    const cobertura = screen.getByTestId("cobertura-coletas");
    expect(cobertura).not.toHaveTextContent("EMEI Sintética Gama");
    expect(cobertura).toHaveTextContent("As escolas com poucos alunos não aparecem nestas listas");
  });

  it("o recorte de uma escola com série suprimida: os blocos dela somam só as séries mostradas", async () => {
    renderComApp(<PlataformasNoPeriodo escolas={ESCOLAS} dados={plataformas()} escolaId={3} />, { usuario: secretaria });
    expect(await screen.findByText("85 de 100 alunos com conta leram no período")).toBeInTheDocument();
    expect(screen.getByTestId("texto-blocos")).toHaveTextContent("somam só as séries mostradas");
  });

  it("coleta parcial: a escola fora da soma da rede aparece na cobertura e no cartão, com a data", async () => {
    const padrao = plataformas();
    const alfa = padrao.escolas.find((e) => e.escola_id === 2)!;
    const texto = "a coleta parou antes do fim do período: os números valem só até 20/09/2026 (o resto do período "
      + "não foi medido — sem dado não é zero)";
    const dados = plataformas({
      cobertura: { ...padrao.cobertura, escolas_coleta_parcial: { elefante: [2], matific: [] } },
      escolas: padrao.escolas.map((e) => (e.escola_id !== 2 ? e : {
        ...alfa, coberto_ate: { elefante: "2026-09-20T00:10:00-03:00", matific: null },
        elefante: { ...ELEFANTE_REDE, coleta_parcial: true, coberto_ate: "2026-09-20T00:10:00-03:00",
                    texto_cobertura: texto },
      })),
    });
    const { unmount } = renderComApp(<PlataformasNoPeriodo escolas={ESCOLAS} dados={dados} />, { usuario: secretaria });
    expect(await screen.findByTestId("coleta-parcial-rede-elefante"))
      .toHaveTextContent("Elefante com a coleta parada antes do fim do período: EMEF Sintética Alfa (até 20/09/2026)");
    expect(screen.getByTestId("coleta-parcial-rede-elefante"))
      .toHaveTextContent("entram na soma da rede só se a coleta cobre ao menos 90% do período");
    unmount();
    renderComApp(<PlataformasNoPeriodo escolas={ESCOLAS} dados={dados} escolaId={2} />, { usuario: secretaria });
    expect(await screen.findByTestId("coleta-parcial-elefante")).toHaveTextContent(`Coleta parcial: ${texto}`);
  });

  it("coleta parcial que cobre quase todo o período: entra na soma da rede, com a data junto", async () => {
    const padrao = plataformas();
    const texto = "2 escola(s) entram com a coleta até 01/10/2026 (cobrem ao menos 90% do período; o restante não foi "
      + "medido — sem dado não é zero).";
    renderComApp(<PlataformasNoPeriodo escolas={ESCOLAS} dados={plataformas({
      rede: { ...padrao.rede, elefante: { ...ELEFANTE_REDE, escolas_coleta_parcial_na_soma: 2,
                                          coberto_ate_parcial: "2026-10-01T06:56:53-03:00",
                                          texto_parcial_na_soma: texto } },
    })} />, { usuario: secretaria });
    expect(await screen.findByTestId("coleta-parcial-elefante-na-soma"))
      .toHaveTextContent(`Coleta parcial: ${texto}`);
  });

  it("contador regredido e médias ocultas em complemento: o cartão diz o porquê (texto do backend)", async () => {
    const padrao = plataformas();
    const regrediu = "o contador de questões de algum aluno diminuiu entre as coletas (texto sintético)";
    const protegidas = "algumas médias deste total não aparecem (texto sintético)";
    renderComApp(<PlataformasNoPeriodo escolas={ESCOLAS} dados={plataformas({
      rede: { ...padrao.rede,
              elefante: { ...ELEFANTE_REDE, contador_regrediu: true, texto_contador_regrediu: regrediu },
              matific: { ...MATIFIC_REDE, desempenho_medio: null,
                         metricas_protegidas: ["estrelas_por_aluno", "desempenho_medio"],
                         texto_metricas_protegidas: protegidas } },
    })} />, { usuario: secretaria });
    expect(await screen.findByTestId("contador-regrediu-elefante")).toHaveTextContent(`Questões: ${regrediu}.`);
    expect(screen.getByTestId("metricas-protegidas-matific")).toHaveTextContent(`Médias ocultas: ${protegidas}.`);
    expect(screen.queryByTestId("metricas-protegidas-elefante")).not.toBeInTheDocument();
  });

  it("sem contador regredido nem média oculta: nenhuma nota a mais", async () => {
    renderComApp(<PlataformasNoPeriodo escolas={ESCOLAS} dados={plataformas()} />, { usuario: secretaria });
    await screen.findAllByTestId("plataforma-elefante");
    expect(screen.queryByTestId("contador-regrediu-elefante")).not.toBeInTheDocument();
    expect(screen.queryByTestId("metricas-protegidas-matific")).not.toBeInTheDocument();
  });

  it("a coleta do dia é '(hoje)', não '(há 0 dias)'; a de ontem continua '(há 1 dia)'", async () => {
    const base = plataformas();
    const { unmount } = renderComApp(
      <PlataformasNoPeriodo escolas={ESCOLAS} dados={plataformas({ cobertura: { ...base.cobertura, dias_desde_ultima_coleta: 0 } })} />,
      { usuario: secretaria });
    const cobertura = await screen.findByTestId("cobertura-coletas");
    expect(cobertura).toHaveTextContent("Matific 19/10/2026 (hoje).");
    expect(cobertura).not.toHaveTextContent("há 0 dias");
    unmount();
    renderComApp(<PlataformasNoPeriodo escolas={ESCOLAS} dados={plataformas()} />, { usuario: secretaria });   // dias = 1
    expect(await screen.findByTestId("cobertura-coletas")).toHaveTextContent("Matific 19/10/2026 (há 1 dia).");
  });
});

// =============================================================================
// Indicador em detalhe (PorIndicador) — a série histórica e as escolas numa edição, hoje
// em "Avaliações externas"; conferido direto, com os filtros na URL como a página os passa:
// escolha, série, dimensões, escolas numa edição
// =============================================================================

describe("Indicador em detalhe — escolha, série, dimensões e escolas numa edição", () => {
  it("escolhe UM indicador; o indisponível fica desabilitado e diz por quê", async () => {
    semear();
    responder("GET", "/redes/1/analise/indicadores/ica", detalheIca());
    responder("GET", "/redes/1/analise/indicadores/saresp", detalheSaresp());
    renderComApp(<IndicadorEmDetalhe />, { rota: "/rede/avaliacoes-externas", usuario: secretaria });

    // Padrão: o primeiro disponível (o ICA), com a meta e a ausência por extenso.
    const tabelaIca = await screen.findByTestId("indicador-tabela");
    expect(within(tabelaIca).getAllByRole("row")[1]).toHaveTextContent(/2025.*47%.*51%.*−4 p\.p\..*não atingiu/);
    expect(within(tabelaIca).getAllByRole("row")[2]).toHaveTextContent("participação abaixo de 70%");
    // O ICA não existe por escola: a abrangência "Escola" fica desabilitada com o motivo.
    expect(screen.getByRole("radio", { name: /Escola do filtro/ })).toBeDisabled();
    expect(screen.getByTestId("motivo-sem-escola")).toHaveTextContent("O ICA é da rede: não existe por escola.");

    const ideb = screen.getByRole("radio", { name: /Ideb/ });
    expect(ideb).toBeDisabled();
    expect(ideb.closest("label")).toHaveTextContent("nenhum arquivo oficial deste indicador foi importado para esta rede");

    await userEvent.click(screen.getByRole("radio", { name: /SARESP/ }));
    await waitFor(() => expect(chamadas("/redes/1/analise/indicadores/saresp")).toHaveLength(1));
    expect(query(chamadas("/redes/1/analise/indicadores/saresp")[0]).get("visao")).toBe("serie");
    expect(await screen.findByRole("radio", { name: /SARESP/ })).toBeChecked();
  });

  it("série: ausência ≠ zero, referência só se comparável, avisos uma vez e fonte recolhida", async () => {
    semear();
    responder("GET", "/redes/1/analise/indicadores/saresp", detalheSaresp());
    renderComApp(<IndicadorEmDetalhe />, { rota: "/rede/avaliacoes-externas?indicador=saresp", usuario: secretaria });

    const tabela = await screen.findByTestId("indicador-tabela");
    const linhas = within(tabela).getAllByRole("row");
    expect(linhas[0]).toHaveTextContent("Estado de São Paulo — redes municipais");     // referência comparável
    expect(linhas[0]).not.toHaveTextContent("rede estadual");                           // contexto fora da tabela
    expect(linhas[1]).toHaveTextContent(/2025.*212,4.*214,6/);
    expect(linhas[2]).toHaveTextContent("2023");
    expect(linhas[2]).toHaveTextContent("não divulgado no arquivo oficial");
    expect(within(linhas[2]).queryByText(/^0([,.]0)?$/)).not.toBeInTheDocument();
    // O contexto (outra rede) não entra no gráfico: fica listado com o motivo.
    const grafico = screen.getByTestId("indicador-grafico");
    expect(grafico).not.toHaveTextContent("rede estadual");
    expect(screen.getByTestId("fora-da-comparacao"))
      .toHaveTextContent("Estado de São Paulo — rede estadual — Outra rede: é a rede ESTADUAL. Só contexto.");
    // O aviso de comparabilidade aparece UMA vez (catálogo + resposta repetem o mesmo texto).
    expect(screen.getAllByText("O SARESP tem escala própria, da SEDUC-SP: não se compara com o Saeb.")).toHaveLength(1);
    // A fonte: só sob demanda, com o arquivo de cada ponto mostrado.
    expect(screen.queryByText(/saresp_municipio_sintetico_2025\.csv/)).not.toBeInTheDocument();
    await userEvent.click(within(screen.getByTestId("detalhes-fontes-indicador")).getByRole("button"));
    const fonte = screen.getByTestId("detalhe-fonte");
    expect(fonte).toHaveTextContent(
      "Fonte: SEDUC-SP — Proficiência do SARESP por município, SARESP 2025, arquivo de 12/01/2026 (saresp_municipio_sintetico_2025.csv)");
    expect(fonte).toHaveTextContent("2023 — Cidade Sintética — rede municipal");
  });

  it("as dimensões (etapa, componente) vão para a API e para a URL", async () => {
    semear();
    responder("GET", "/redes/1/analise/indicadores/saresp", detalheSaresp());
    renderComApp(<IndicadorEmDetalhe />, { rota: "/rede/avaliacoes-externas?indicador=saresp", usuario: secretaria });
    await screen.findByTestId("indicador-tabela");
    await userEvent.selectOptions(screen.getByLabelText("Etapa"), "2_ano");
    await waitFor(() => expect(chamadas("/redes/1/analise/indicadores/saresp")
      .some((c) => query(c).get("etapa") === "2_ano")).toBe(true));
    await userEvent.selectOptions(screen.getByLabelText("Componente"), "mt");
    await waitFor(() => expect(chamadas("/redes/1/analise/indicadores/saresp")
      .some((c) => query(c).get("etapa") === "2_ano" && query(c).get("componente") === "mt")).toBe(true));
    // Com a escola do filtro, a abrangência "Escola" manda o escola_id.
    await userEvent.selectOptions(screen.getByLabelText("Escola"), "3");
    await userEvent.click(await screen.findByRole("radio", { name: "Escola do filtro: EMEF Sintética Beta" }));
    await waitFor(() => expect(chamadas("/redes/1/analise/indicadores/saresp")
      .some((c) => query(c).get("escola_id") === "3")).toBe(true));
  });

  it("escolas numa edição: em ordem de NOME (não ranking), instável marcada, escola sem INEP com o motivo", async () => {
    semear();
    responder("GET", "/redes/1/analise/indicadores/saresp", detalheSaresp({
      filtros: { etapa: "5_ano", componente: "lp", escola_id: null, de: null, ate: null, visao: "escolas", edicao: 2025 },
      series: [],
      escolas: [
        linhaEscola(3, "EMEF Sintética Beta", 231.2, { instavel: true }),
        linhaEscola(4, "EMEI Sintética Gama", null, { pendencia: "sem_codigo_inep", motivo_ausencia: "sem_codigo_inep",
                                                      texto_ausencia: "a escola está sem código INEP no cadastro" }),
        linhaEscola(2, "EMEF Sintética Alfa", 198.7),
      ],
    }));
    renderComApp(<IndicadorEmDetalhe />, {
      rota: "/rede/avaliacoes-externas?indicador=saresp&visao=escolas", usuario: secretaria });
    const tabela = await screen.findByTestId("indicador-escolas");
    const chamada = chamadas("/redes/1/analise/indicadores/saresp")[0];
    expect(query(chamada).get("visao")).toBe("escolas");
    expect(query(chamada).get("edicao")).toBe("2025");                 // a visão por escolas exige a edição
    const linhas = within(tabela).getAllByRole("row").slice(1);
    expect(linhas.map((l) => within(l).getByRole("rowheader").textContent)).toEqual([
      "EMEF Sintética Alfa", "EMEF Sintética Beta", "EMEI Sintética Gamasem código INEP",
    ]);
    expect(linhas[0]).toHaveTextContent("198,7");
    expect(linhas[1]).toHaveTextContent("média instável (TPS = 0)");
    expect(linhas[2]).toHaveTextContent("a escola está sem código INEP no cadastro");
    expect(linhas[2]).not.toHaveTextContent(/\b0,0\b/);
    expect(screen.getByTestId("escolas-sem-ranking")).toHaveTextContent("não é ranking");
    // Como comparar (o mesmo do Comparar escolas): com ela mesma nas outras edições — nunca "só
    // com a própria meta" (o SARESP nem tem meta).
    expect(screen.getByTestId("escolas-sem-ranking")).toHaveTextContent("com ela mesma nas outras edições (série histórica)");
    expect(screen.getByTestId("escolas-sem-ranking")).not.toHaveTextContent("só com a própria meta");
    expect(tabela).not.toHaveTextContent(/1º lugar|posição/i);
  });
});

// =============================================================================
// Indicador em detalhe: o que faltava cobrir
// =============================================================================

describe("Indicador em detalhe — estados e filtros", () => {
  it("indicador indisponível aberto pela URL: o motivo por extenso, nunca a chave técnica", async () => {
    semear({ indicadores: [ICA, SARESP, { ...IDEB, texto_indisponivel: null }] });
    renderComApp(<IndicadorEmDetalhe />, { rota: "/rede/avaliacoes-externas?indicador=ideb", usuario: secretaria });
    expect(await screen.findByTestId("indicador-indisponivel"))
      .toHaveTextContent("Ideb: nenhum arquivo oficial deste indicador foi importado para esta rede.");
    expect(screen.getByRole("radio", { name: /Ideb/ }).closest("label"))
      .toHaveTextContent("nenhum arquivo oficial deste indicador foi importado");
    expect(screen.queryByText(/sem_importacao/)).not.toBeInTheDocument();
    expect(chamadas("/redes/1/analise/indicadores/")).toHaveLength(0);
  });

  it("o gráfico: a meta tracejada (cor própria) e a quebra de escala sem linha entre os dois lados", async () => {
    semear();
    responder("GET", "/redes/1/analise/indicadores/ica", detalheIca());
    responder("GET", "/redes/1/analise/indicadores/saresp", detalheSaresp({
      series: [serie({ pontos: [ponto(2022, 205.3), ponto(2023, 207.0), ponto(2025, 212.4)] })],
      quebras: [{ entre: [2022, 2023], texto: "Possível quebra de escala (texto sintético)." }],
    }));
    const { container } = renderComApp(<IndicadorEmDetalhe />,
      { rota: "/rede/avaliacoes-externas?indicador=ica", usuario: secretaria });
    const grafico = await screen.findByTestId("indicador-grafico");
    expect(grafico).toHaveTextContent("Meta — Cidade Sintética — rede municipal (tracejada)");
    const tracejadas = [...container.querySelectorAll("polyline")].filter((l) => l.getAttribute("stroke-dasharray"));
    expect(tracejadas.length).toBeGreaterThan(0);
    expect(tracejadas.every((l) => l.getAttribute("stroke") === "#64748B")).toBe(true);

    await userEvent.click(screen.getByRole("radio", { name: /SARESP/ }));
    const img = await screen.findByRole("img", { name: /quebra de escala/ });
    expect(img).toHaveAttribute("aria-label", expect.stringContaining("Sem linha de 2022 para 2023 (quebra de escala)"));
    // A linha principal liga só 2023 → 2025: 2022 fica sozinho do outro lado da quebra
    // (um trecho de 1 ponto e outro de 2 — nunca um de 3).
    const principais = [...img.querySelectorAll("polyline")].filter((l) => l.getAttribute("stroke") === "#6C5CE7");
    expect(principais.map((l) => l.getAttribute("points")?.trim().split(/\s+/).length)).toEqual([1, 2]);
    expect(screen.getByTestId("avisos-comparabilidade"))
      .toHaveTextContent("Entre 2022 e 2023: Possível quebra de escala (texto sintético).");
  });

  it("De e Até vão para a API; De depois de Até nunca vai (o outro lado acompanha)", async () => {
    semear();
    responder("GET", "/redes/1/analise/indicadores/saresp", detalheSaresp());
    renderComApp(<IndicadorEmDetalhe />, { rota: "/rede/avaliacoes-externas?indicador=saresp", usuario: secretaria });
    await screen.findByTestId("indicador-tabela");
    await userEvent.selectOptions(screen.getByLabelText("Até"), "2023");
    await waitFor(() => expect(chamadas("/redes/1/analise/indicadores/saresp")
      .some((c) => query(c).get("ate") === "2023")).toBe(true));
    await userEvent.selectOptions(screen.getByLabelText("De"), "2025");
    await waitFor(() => expect(chamadas("/redes/1/analise/indicadores/saresp")
      .some((c) => query(c).get("de") === "2025" && query(c).get("ate") === "2025")).toBe(true));
    expect(chamadas("/redes/1/analise/indicadores/saresp").every((c) => {
      const de = Number(query(c).get("de") ?? 0), ate = Number(query(c).get("ate") ?? 9999);
      return de <= ate;
    })).toBe(true);
  });

  it("um link com De > Até chega à API com os dois na ordem certa", async () => {
    semear();
    responder("GET", "/redes/1/analise/indicadores/saresp", detalheSaresp());
    renderComApp(<IndicadorEmDetalhe />, {
      rota: "/rede/avaliacoes-externas?indicador=saresp&de=2025&ate=2022", usuario: secretaria });
    await screen.findByTestId("indicador-tabela");
    const q = query(chamadas("/redes/1/analise/indicadores/saresp")[0]);
    expect([q.get("de"), q.get("ate")]).toEqual(["2022", "2025"]);
  });

  it("IEE é só por escola: sem escola abre nas escolas da edição; na série, a rede fica desabilitada", async () => {
    const IEE = indicador({ chave: "iee", nome: "IEE", orgao: "SEDUC-SP", unidade: "índice", escala: "indice_iee",
                            abrangencias: ["escola"], etapas: ["anos_iniciais"], componentes: [], edicoes: [2025],
                            tem_meta: true });
    semear({ indicadores: [IEE, SARESP] });
    responder("GET", "/redes/1/analise/indicadores/iee", detalheSaresp({
      indicador: IEE, series: [],
      filtros: { etapa: "anos_iniciais", componente: null, escola_id: null, de: null, ate: null, visao: "escolas",
                 edicao: 2025 },
      escolas: [linhaEscola(3, "EMEF Sintética Beta", 4.8, { casas: 2, meta: 4.5, meta_casas: 2, diferenca_meta: 0.3,
                                                              situacao_meta: "atingiu", tps_zero: true })],
    }));
    renderComApp(<IndicadorEmDetalhe />, { rota: "/rede/avaliacoes-externas?indicador=iee", usuario: secretaria });
    const escolas = await screen.findByTestId("indicador-escolas");
    expect(query(chamadas("/redes/1/analise/indicadores/iee")[0]).get("visao")).toBe("escolas");
    expect(escolas).toHaveTextContent("4,80");
    expect(escolas).toHaveTextContent("calculado com médias de TPS = 0");
    await userEvent.click(screen.getByRole("radio", { name: "Série histórica" }));
    expect(await screen.findByTestId("motivo-so-escola")).toHaveTextContent("é por escola");
    expect(screen.getByRole("radio", { name: "Rede municipal" })).toBeDisabled();
  });

  it("número sem registro oficial: marcado com * na tabela, com a legenda, e fora do gráfico", async () => {
    semear();
    responder("GET", "/redes/1/analise/indicadores/saresp", detalheSaresp({
      series: [serie({ pontos: [
        ponto(2022, 205.3), ponto(2023, 207.0),
        ponto(2025, 219.9, { fonte_id: null, proveniencia: "sem_registro",
                             texto_proveniencia: "número gravado antes, sem o registro do arquivo oficial" }),
      ] })],
    }));
    renderComApp(<IndicadorEmDetalhe />, { rota: "/rede/avaliacoes-externas?indicador=saresp", usuario: secretaria });
    const tabela = await screen.findByTestId("indicador-tabela");
    const linha2025 = within(tabela).getAllByRole("row")[1];
    expect(linha2025).toHaveTextContent("219,9*");
    expect(linha2025).toHaveTextContent("(sem registro oficial: número gravado antes, sem o registro do arquivo oficial)");
    expect(screen.getByTestId("legenda-sem-registro"))
      .toHaveTextContent("* número gravado antes, sem o registro do arquivo oficial");
    expect(screen.getByTestId("legenda-sem-registro")).toHaveTextContent("Não é a Estimativa Constela");
    // Fora do gráfico: a linha principal vai só de 2022 a 2023.
    expect(screen.getByTestId("grafico-sem-registro")).toHaveTextContent("ficam fora do gráfico");
    const img = within(screen.getByTestId("indicador-grafico")).getByRole("img");
    const principais = [...img.querySelectorAll("polyline")].filter((l) => l.getAttribute("stroke") === "#6C5CE7");
    expect(principais.flatMap((l) => l.getAttribute("points")?.trim().split(/\s+/) ?? [])).toHaveLength(2);
    expect(img).not.toHaveTextContent("219,9");
  });

  it("a edição que uma referência não tem diz isso por extenso (não um '—' mudo)", async () => {
    semear();
    responder("GET", "/redes/1/analise/indicadores/saresp", detalheSaresp({
      series: [
        serie({ pontos: [ponto(2022, 205.3), ponto(2025, 212.4)] }),
        serie({ id: "uf_redes_municipais", rotulo: "Estado de São Paulo — redes municipais", papel: "referencia",
                abrangencia: "uf", pontos: [ponto(2025, 214.6)] }),
      ],
    }));
    renderComApp(<IndicadorEmDetalhe />, { rota: "/rede/avaliacoes-externas?indicador=saresp", usuario: secretaria });
    const linhas = within(await screen.findByTestId("indicador-tabela")).getAllByRole("row");
    expect(linhas[2]).toHaveTextContent(/2022.*205,3.*sem resultado nesta edição/);
  });

  it("o indicador carregando e a recusa da API aparecem (não somem em silêncio)", async () => {
    semear();
    responder("GET", "/redes/1/analise/indicadores/saresp", () => new Promise(() => {}));
    const { unmount } = renderComApp(<IndicadorEmDetalhe />,
                                     { rota: "/rede/avaliacoes-externas?indicador=saresp", usuario: secretaria });
    expect(await screen.findByText("Carregando o indicador...")).toBeInTheDocument();
    unmount();
    responderErro("GET", "/redes/1/analise/indicadores/saresp", 500, "FALHA-X");
    renderComApp(<IndicadorEmDetalhe />, { rota: "/rede/avaliacoes-externas?indicador=saresp", usuario: secretaria });
    expect(await screen.findByText("Não foi possível carregar o indicador: FALHA-X")).toBeInTheDocument();
  });
});

// =============================================================================
// Relação com plataformas
// =============================================================================

describe("Análises avançadas — relação com as plataformas", () => {
  it("não calculável: o motivo em linguagem simples, lado a lado com o ano de cada lado, sem coeficiente", async () => {
    semear();
    responder("GET", "/redes/1/analise/relacao", relacao());
    renderComApp(<AnaliseEducacional />, { rota: "/rede/analise?ver=relacao", usuario: secretaria });

    const recusa = await screen.findByTestId("relacao-nao-calculavel");
    expect(recusa).toHaveTextContent("Não dá para calcular a relação");
    expect(recusa).toHaveTextContent("Período sem sobreposição: a avaliação é de 2025");
    expect(screen.queryByTestId("relacao-coeficiente")).not.toBeInTheDocument();
    expect(screen.queryByText(/Coeficiente de Spearman/)).not.toBeInTheDocument();
    // O pedido: o indicador por escola (o ICA fica de fora), a edição e a métrica do componente.
    const q = query(chamadas("/redes/1/analise/relacao")[0]);
    expect(Object.fromEntries(q)).toMatchObject({
      indicador: "saresp", etapa: "5_ano", componente: "lp", edicao: "2025", metrica: "livros_por_aluno",
      periodo: "ano_letivo",
    });
    const ica = screen.getByRole("radio", { name: /Indicador Criança Alfabetizada/ });
    expect(ica).toBeDisabled();
    expect(ica.closest("label")).toHaveTextContent("o ICA é da rede");
    // Lado a lado: em ordem de nome, cada lado com o seu ano; a ausência por extenso.
    const lado = screen.getByTestId("relacao-lado-a-lado");
    const linhas = within(lado).getAllByRole("row").slice(1);
    expect(linhas[0]).toHaveTextContent("EMEF Sintética Alfa");
    expect(linhas[0]).toHaveTextContent("não divulgado no arquivo oficial");
    expect(linhas[1]).toHaveTextContent(/EMEF Sintética Beta.*214,2.*2025.*3,4.*2026/);
    expect(linhas[1]).toHaveTextContent("não: Período sem sobreposição");
    // SEMPRE: o aviso de causalidade e a metodologia recolhível.
    expect(screen.getByTestId("aviso-causalidade")).toHaveTextContent("Correlação não é causalidade");
    const metodologia = screen.getByRole("button", { name: /Metodologia da relação/ });
    expect(metodologia).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(metodologia);
    expect(metodologia).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByTestId("relacao-metodologia")).toHaveTextContent("Unidade: a escola.");
    expect(screen.getByTestId("relacao-criterios")).toHaveTextContent("Mínimo de escolas com os dois números: 8");
  });

  it("calculável: dispersão, coeficiente de Spearman, IC 95% e n — e o aviso de causalidade continua", async () => {
    semear();
    responder("GET", "/redes/1/analise/relacao", relacao({
      calculavel: true, motivos: [], textos: [], n: 9, coeficiente: 0.47,
      ic95: { inferior: 0.12, superior: 0.74 },
      interpretacao: "Entre as escolas da rede, as que têm mais livros tendem a ter o SARESP mais alto (associação de postos).",
      pares: Array.from({ length: 9 }, (_, i) => ({
        escola_id: 10 + i, nome: `EMEF Sintética ${String.fromCharCode(65 + i)}`, valor_oficial: 200 + i * 2.5,
        casas_oficial: 1, edicao: 2025, valor_plataforma: 2 + i * 0.3, janela: "2025", incluido: true,
        motivo_exclusao: null,
      })),
    }));
    renderComApp(<AnaliseEducacional />, { rota: "/rede/analise?ver=relacao", usuario: secretaria });
    const ok = await screen.findByTestId("relacao-calculavel");
    expect(ok).toHaveTextContent("Dá para calcular");
    expect(screen.getByTestId("relacao-coeficiente"))
      .toHaveTextContent("Coeficiente de Spearman: 0,47 · IC 95%: 0,12 a 0,74 · n = 9 escolas");
    expect(screen.getByTestId("relacao-dispersao")).toHaveAttribute("aria-label", expect.stringContaining("9 escolas"));
    expect(screen.getByTestId("relacao-interpretacao")).toHaveTextContent("associação de postos");
    expect(screen.getByTestId("aviso-causalidade")).toHaveTextContent("Correlação não é causalidade");
    expect(screen.queryByTestId("relacao-nao-calculavel")).not.toBeInTheDocument();
  });
});

// =============================================================================
// Relação: trocas de filtro, motivo de cada escola, texto sem repetição
// =============================================================================

describe("Análises avançadas — relação (filtros e textos)", () => {
  it("trocar edição e métrica vai para a API; trocar o componente volta à métrica dele", async () => {
    semear();
    responder("GET", "/redes/1/analise/relacao", () => relacao({ textos: [], motivos: ["n_insuficiente"] }));
    const { container } = renderComApp(<AnaliseEducacional />, {
      rota: "/rede/analise?ver=relacao", usuario: secretaria });
    // Sem texto da API: o motivo em linguagem simples, pelo código.
    expect(await screen.findByTestId("relacao-nao-calculavel"))
      .toHaveTextContent("Poucas escolas têm os dois números: não dá para calcular com segurança.");
    const ultima = () => query(chamadas("/redes/1/analise/relacao").at(-1) ?? "");

    await userEvent.selectOptions(screen.getByLabelText("Edição"), "2023");
    await waitFor(() => expect(ultima().get("edicao")).toBe("2023"));
    await userEvent.selectOptions(screen.getByLabelText("Métrica da plataforma"), "minutos_por_aluno");
    await waitFor(() => expect(ultima().get("metrica")).toBe("minutos_por_aluno"));

    await userEvent.selectOptions(within(screen.getByTestId("dimensoes-relacao")).getByLabelText("Componente"), "mt");
    await waitFor(() => expect(ultima().get("componente")).toBe("mt"));
    // A métrica do Elefante não fica presa na Matemática: volta à do componente.
    expect(ultima().get("metrica")).toBe("estrelas_por_aluno");
    expect(screen.getByLabelText("Métrica da plataforma")).toHaveValue("estrelas_por_aluno");
    // As métricas da outra área aparecem marcadas.
    expect(container.querySelector('optgroup[label="Elefante Letrado — outra área (Língua Portuguesa)"]'))
      .not.toBeNull();
    expect(container.querySelector('optgroup[label="Matific"]')).not.toBeNull();
  });

  it("lado a lado: cada escola diz o motivo PRÓPRIO; o texto não repete o ano letivo", async () => {
    semear();
    responder("GET", "/redes/1/analise/relacao", relacao({
      textos: ["Período sem sobreposição: a avaliação é de 2025 e o período das plataformas é Ano letivo 2026 "
               + "(ano letivo 2026). Só se relacionam números do MESMO ano letivo."],
      pares: [
        { escola_id: 3, nome: "EMEF Sintética Beta", valor_oficial: 199, casas_oficial: 1, edicao: 2025,
          valor_plataforma: 12, janela: "2026", incluido: false, instavel: true,
          motivo_escola: "média instável (TPS = 0: participação abaixo do mínimo do SARESP)",
          motivo_exclusao: "média instável (TPS = 0: participação abaixo do mínimo do SARESP)" },
        { escola_id: 2, nome: "EMEF Sintética Alfa", valor_oficial: 220.1, casas_oficial: 1, edicao: 2025,
          valor_plataforma: 3, janela: "2026", incluido: false, motivo_escola: null,
          motivo_exclusao: "fica de fora pelo motivo geral da relação" },
      ],
    }));
    renderComApp(<AnaliseEducacional />, { rota: "/rede/analise?ver=relacao", usuario: secretaria });
    const recusa = await screen.findByTestId("relacao-nao-calculavel");
    expect(recusa).toHaveTextContent("o período das plataformas é Ano letivo 2026. Só se relacionam");
    expect(recusa).not.toHaveTextContent("(ano letivo 2026)");
    const lado = screen.getByTestId("relacao-lado-a-lado");
    const linha = (nome: string) => within(lado).getByRole("rowheader", { name: nome }).closest("tr")!;
    expect(linha("EMEF Sintética Beta")).toHaveTextContent("não: média instável (TPS = 0");
    expect(linha("EMEF Sintética Alfa")).toHaveTextContent("não: fica de fora pelo motivo geral da relação");
  });

  it("calculável: a interpretação não repete o aviso de causalidade (ele está na caixa fixa)", async () => {
    const CAUSALIDADE = "Correlação não é causalidade: escolas que leem mais podem ser diferentes em muitas outras "
      + "coisas (texto sintético).";
    semear();
    responder("GET", "/redes/1/analise/relacao", relacao({
      calculavel: true, motivos: [], textos: [], n: 9, coeficiente: 0.5, ic95: { inferior: 0.1, superior: 0.8 },
      avisos: [CAUSALIDADE],
      interpretacao: "Entre as escolas da rede, as que têm mais livros tendem a ter o SARESP mais alto "
        + `(associação de postos). ${CAUSALIDADE}`,
      pares: Array.from({ length: 9 }, (_, i) => ({
        escola_id: 10 + i, nome: `EMEF Sintética ${String.fromCharCode(65 + i)}`, valor_oficial: 200 + i,
        casas_oficial: 1, edicao: 2025, valor_plataforma: 1 + i, janela: "2025", incluido: true, motivo_exclusao: null,
      })),
    }));
    renderComApp(<AnaliseEducacional />, { rota: "/rede/analise?ver=relacao", usuario: secretaria });
    const interpretacao = await screen.findByTestId("relacao-interpretacao");
    expect(interpretacao).toHaveTextContent("tendem a ter o SARESP mais alto (associação de postos).");
    expect(interpretacao).not.toHaveTextContent(/causalidade/i);
    expect(screen.getByTestId("aviso-causalidade")).toHaveTextContent("Correlação não é causalidade");
  });
});

// =============================================================================
// Por escola
// =============================================================================

describe("Análises avançadas — análise detalhada por escola", () => {
  it("sem escola escolhida pede a escola; com ela, os indicadores dela, as plataformas por série e o que não se compara", async () => {
    semear();
    responder("GET", "/escolas/3/analise", analiseEscola(3, "EMEF Sintética Beta"));
    renderComApp(<AnaliseEducacional />, { rota: "/rede/analise?ver=escola", usuario: secretaria });
    expect(await screen.findByText("Escolha uma escola")).toBeInTheDocument();
    expect(chamadas("/escolas/")).toHaveLength(0);

    await userEvent.selectOptions(screen.getByLabelText("Escola"), "3");
    const nome = await screen.findByTestId("analise-escola-indicador-saresp");
    expect(query(chamadas("/escolas/3/analise")[0]).get("periodo")).toBe("ano_letivo");
    expect(screen.getByTestId("por-escola-nome")).toHaveTextContent("EMEF Sintética Beta");
    expect(nome).toHaveTextContent("5º ano · Língua Portuguesa");
    expect(nome).toHaveTextContent("219,6");
    expect(nome).toHaveTextContent("não divulgado no arquivo oficial");
    expect(nome).toHaveTextContent("referência");
    const tabela = screen.getByTestId("tabela-series-plataformas");
    // Supressão com o texto ÚNICO (a célula pequena e a escondida junto dizem o mesmo).
    expect(tabela).toHaveTextContent(TEXTO_SUPRESSAO);
    expect(tabela).not.toHaveTextContent(/menos de 5 alunos|complementar/);
    expect(tabela).toHaveTextContent("58,1%");
    expect(screen.getByTestId("analise-escola-indisponiveis")).toHaveTextContent("O ICA é da rede: não existe por escola.");
  });

  it("a escola sem código INEP diz a pendência (não 'sem resultado' mudo)", async () => {
    semear();
    responder("GET", "/escolas/4/analise", analiseEscola(4, "EMEI Sintética Gama", {
      escola: { id: 4, nome: "EMEI Sintética Gama", codigo_inep: null, pendencia: "sem_codigo_inep" },
      indicadores: [],
      comparacoes_indisponiveis: [
        { tema: "cadastro", texto: "A escola está sem código INEP no cadastro: os números oficiais dela não podem ser casados." },
      ],
    }));
    renderComApp(<AnaliseEducacional />, { rota: "/rede/analise?ver=escola&escola=4", usuario: secretaria });
    expect(await screen.findByTestId("analise-escola-sem-inep")).toHaveTextContent("sem código INEP no cadastro");
    expect(screen.getByTestId("analise-escola-sem-indicadores")).toBeInTheDocument();
    // O aviso do topo não se repete na lista das comparações.
    expect(screen.getAllByText(/sem código INEP no cadastro/)).toHaveLength(1);
  });

  it("avaliação oficial e plataformas aparecem perto, nunca na mesma conta: a frase diz de quando é cada uma", async () => {
    semear();
    responder("GET", "/escolas/3/analise", analiseEscola(3, "EMEF Sintética Beta"));
    renderComApp(<AnaliseEducacional />, { rota: "/rede/analise?ver=escola&escola=3", usuario: secretaria });
    expect(await screen.findByTestId("frase-periodos-diferentes")).toHaveTextContent(
      "As avaliações oficiais são de outras edições (até 2025) e as plataformas, do período escolhido (ano letivo de "
      + "2026): são medidas e períodos diferentes — não se comparam diretamente.");
  });
});

// =============================================================================
// Rede: Secretaria × admin global
// =============================================================================

describe("Análises avançadas — qual rede", () => {
  it("o admin global escolhe a rede (seletor quando há mais de uma)", async () => {
    responder("GET", "/redes", [{ id: 2, nome: "Rede Sintética Sul" }, { id: 1, nome: "Rede Sintética Norte" }]);
    semear();
    responder("GET", "/redes/2/analise/indicadores", base({ rede: { id: 2, nome: "Rede Sintética Sul", codigo_ibge: null } }));
    responder("GET", "/redes/2/analise/plataformas", plataformas());
    responder("GET", "/redes/2/analise/diagnostico", { ...diagnostico(), rede: { id: 2, nome: "Rede Sintética Sul" } });
    renderComApp(<AnaliseEducacional />, { rota: "/rede/analise", usuario: admin });
    const seletor = await screen.findByLabelText("Rede analisada");
    // Padrão: a primeira em ordem de nome.
    expect(seletor).toHaveValue("1");
    expect(await screen.findByTestId("analise-rede-nome")).toHaveTextContent("Rede Sintética Norte");
    await userEvent.selectOptions(seletor, "2");
    expect(await screen.findByText("Rede Sintética Sul", { selector: "[data-testid=analise-rede-nome]" }))
      .toBeInTheDocument();
    expect(chamadas("/redes/2/analise/indicadores")).toHaveLength(1);
  });

  it("a Secretaria não vê o seletor de rede", async () => {
    semear();
    renderComApp(<AnaliseEducacional />, { rota: "/rede/analise", usuario: secretaria });
    await screen.findByTestId("tabela-diagnostico");
    expect(screen.queryByLabelText("Rede analisada")).not.toBeInTheDocument();
  });

  it("a Secretaria ignora ?rede= de outra rede: só a própria rede é lida", async () => {
    semear();
    responder("GET", (c) => c.startsWith("/redes/2/"), () => { throw new Error("NÃO DEVIA LER A REDE 2"); });
    renderComApp(<AnaliseEducacional />, { rota: "/rede/analise?rede=2", usuario: secretaria });
    expect(await screen.findByTestId("analise-rede-nome")).toHaveTextContent("Rede Sintética Norte");
    await screen.findByTestId("tabela-diagnostico");
    const analise = api.mock.calls.map(([c]) => String(c)).filter((c) => c.includes("/analise"));
    expect(analise.length).toBeGreaterThan(0);
    expect(analise.every((c) => c.startsWith("/redes/1/"))).toBe(true);
    expect(chamadas("/redes/2")).toHaveLength(0);
  });

  it("o admin global sem rede nenhuma é levado a criar a primeira", async () => {
    responder("GET", "/redes", []);
    renderComApp(<AnaliseEducacional />, { rota: "/rede/analise", usuario: admin });
    expect(await screen.findByText("Nenhuma rede disponível")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Gerenciar redes/ })).toBeInTheDocument();
    expect(chamadas("/redes/")).toHaveLength(0);
  });
});

// =============================================================================
// Filtro Escola × seletor de contexto do topo (o MESMO)
// =============================================================================

/** O seletor de contexto do topo, de fora da página (o Layout real faz o mesmo). */
function Topo() {
  const { escolaId, selecionarEscola } = useApp();
  return (
    <div>
      <p data-testid="contexto-topo">{escolaId == null ? "toda a rede" : `escola ${escolaId}`}</p>
      <button type="button" onClick={() => selecionarEscola(2)}>topo: escola 2</button>
      <button type="button" onClick={() => selecionarEscola(null)}>topo: toda a rede</button>
    </div>
  );
}

/** A análise detalhada de qualquer escola (a aba "escola" lê `/escolas/{id}/analise`). */
function semearEscolas() {
  responder("GET", /^\/escolas\/\d+\/analise/, (c: string) => {
    const id = Number(c.split("/")[2]);
    return analiseEscola(id, ESCOLAS.find((e) => e.id === id)?.nome ?? `escola ${id}`);
  });
}
const ultimaEscolaLida = () => (chamadas("/escolas/").at(-1) ?? "").split("?")[0];

describe("Análises avançadas — o filtro Escola é o seletor de contexto do topo", () => {
  it("Secretaria: mudar um muda o outro, e 'Toda a rede' é o 'Toda a Rede Municipal' (escolaId nulo)", async () => {
    semear();
    semearEscolas();
    renderComApp(<><Topo /><AnaliseEducacional /></>, { rota: "/rede/analise?ver=escola", usuario: secretaria });
    await screen.findByTestId("analise-rede-nome");
    const topo = screen.getByTestId("contexto-topo");
    expect(topo).toHaveTextContent("toda a rede");
    expect(screen.getByLabelText("Escola")).toHaveValue("");

    // A página leva o topo junto…
    await userEvent.selectOptions(screen.getByLabelText("Escola"), "3");
    expect(topo).toHaveTextContent("escola 3");
    await userEvent.selectOptions(screen.getByLabelText("Escola"), "");
    expect(topo).toHaveTextContent("toda a rede");

    // …e o topo traz a página junto (com a leitura da escola nova).
    await userEvent.click(screen.getByRole("button", { name: "topo: escola 2" }));
    await waitFor(() => expect(screen.getByLabelText("Escola")).toHaveValue("2"));
    await waitFor(() => expect(ultimaEscolaLida()).toBe("/escolas/2/analise"));
    await userEvent.click(screen.getByRole("button", { name: "topo: toda a rede" }));
    await waitFor(() => expect(screen.getByLabelText("Escola")).toHaveValue(""));
    expect(await screen.findByText("Escolha uma escola")).toBeInTheDocument();
  });

  it("Secretaria que já estava numa escola no topo abre a análise nela", async () => {
    semear();
    semearEscolas();
    renderComApp(<><Topo /><AnaliseEducacional /></>,
                 { rota: "/rede/analise?ver=escola", usuario: secretaria, escolaSelecionada: 3 });
    await waitFor(() => expect(screen.getByLabelText("Escola")).toHaveValue("3"));
    await waitFor(() => expect(ultimaEscolaLida()).toBe("/escolas/3/analise"));
    expect(screen.getByTestId("contexto-topo")).toHaveTextContent("escola 3");
  });

  it("um link com ?escola= manda: o topo vai para a escola do link", async () => {
    semear();
    renderComApp(<><Topo /><AnaliseEducacional /></>, { rota: "/rede/analise?escola=4", usuario: secretaria });
    await waitFor(() => expect(screen.getByTestId("contexto-topo")).toHaveTextContent("escola 4"));
    expect(screen.getByLabelText("Escola")).toHaveValue("4");
  });

  it("admin global: abre em 'Toda a rede'; escolher aqui leva o topo; o topo nunca fica sem escola", async () => {
    responder("GET", "/redes", [{ id: 1, nome: "Rede Sintética Norte" }]);
    semear();
    renderComApp(<><Topo /><AnaliseEducacional /></>, { rota: "/rede/analise", usuario: admin });
    await screen.findByTestId("analise-rede-nome");
    const topo = screen.getByTestId("contexto-topo");
    expect(topo).toHaveTextContent("escola 1");            // a escola do topo é de fora desta rede
    expect(screen.getByLabelText("Escola")).toHaveValue("");
    await userEvent.selectOptions(screen.getByLabelText("Escola"), "3");
    expect(topo).toHaveTextContent("escola 3");
    await userEvent.selectOptions(screen.getByLabelText("Escola"), "");
    expect(topo).toHaveTextContent("escola 3");            // o topo do global sempre tem uma escola
    await userEvent.click(screen.getByRole("button", { name: "topo: escola 2" }));
    await waitFor(() => expect(screen.getByLabelText("Escola")).toHaveValue("2"));
  });
});

// =============================================================================
// Abas: teclado e o painel que sempre existe
// =============================================================================

describe("Análises avançadas — abas", () => {
  it("setas, Home e End trocam de aba e levam o foco junto (tabindex móvel)", async () => {
    semear();
    responder("GET", "/redes/1/analise/relacao", relacao());
    renderComApp(<AnaliseEducacional />, { rota: "/rede/analise", usuario: secretaria });
    const diag = await screen.findByRole("tab", { name: "Diagnóstico exploratório" });
    expect(diag).toHaveAttribute("tabindex", "0");
    expect(screen.getByRole("tab", { name: "Relação com as plataformas" })).toHaveAttribute("tabindex", "-1");
    diag.focus();
    const aba = (nome: string) => screen.getByRole("tab", { name: nome });
    await userEvent.keyboard("{ArrowRight}");
    expect(aba("Relação com as plataformas")).toHaveAttribute("aria-selected", "true");
    expect(aba("Relação com as plataformas")).toHaveFocus();
    await userEvent.keyboard("{End}");
    expect(aba("Análise detalhada por escola")).toHaveAttribute("aria-selected", "true");
    await userEvent.keyboard("{ArrowRight}");
    expect(aba("Diagnóstico exploratório")).toHaveAttribute("aria-selected", "true");
    expect(aba("Diagnóstico exploratório")).toHaveFocus();
    await userEvent.keyboard("{ArrowLeft}");
    expect(aba("Análise detalhada por escola")).toHaveFocus();
    await userEvent.keyboard("{Home}");
    expect(aba("Diagnóstico exploratório")).toHaveAttribute("aria-selected", "true");
  });

  it("enquanto carrega, o painel das abas já existe (o aria-controls aponta para ele)", async () => {
    responder("GET", "/redes/1/analise/indicadores", () => new Promise(() => {}));
    renderComApp(<AnaliseEducacional />, { rota: "/rede/analise", usuario: secretaria });
    const painel = await screen.findByRole("tabpanel");
    expect(painel).toHaveTextContent("Carregando a análise da rede...");
    expect(screen.getByRole("tab", { name: "Diagnóstico exploratório" })).toHaveAttribute("aria-controls", painel.id);
  });
});

// =============================================================================
// Carregando e erro de cada leitura (não somem em silêncio)
// =============================================================================

describe("Análises avançadas — carregando e erro de cada leitura", () => {
  const casos: [string, string, string, string, string][] = [
    ["o diagnóstico", "/rede/analise", "/redes/1/analise/diagnostico",
     "Carregando o diagnóstico...", "Não foi possível carregar o diagnóstico: FALHA-X"],
    ["a relação", "/rede/analise?ver=relacao", "/redes/1/analise/relacao",
     "Conferindo se dá para calcular...", "Não foi possível carregar a relação: FALHA-X"],
    ["a escola", "/rede/analise?ver=escola&escola=3", "/escolas/3/analise",
     "Carregando a análise da escola...", "Não foi possível carregar a análise da escola: FALHA-X"],
  ];

  it.each(casos)("%s: mostra o carregamento", async (_nome, rota, caminho, carregando) => {
    semear();
    responder("GET", caminho, () => new Promise(() => {}));
    renderComApp(<AnaliseEducacional />, { rota, usuario: secretaria });
    expect(await screen.findByText(carregando)).toBeInTheDocument();
  });

  it.each(casos)("%s: mostra a recusa da API", async (_nome, rota, caminho, _carregando, erro) => {
    semear();
    responderErro("GET", caminho, 500, "FALHA-X");
    renderComApp(<AnaliseEducacional />, { rota, usuario: secretaria });
    expect(await screen.findByText(erro)).toBeInTheDocument();
  });
});

// =============================================================================
// Relação: "o que dá para relacionar hoje" (vindo da antiga Visão geral)
// =============================================================================

describe("Análises avançadas — o que dá para relacionar hoje", () => {
  it("a aba Relação abre dizendo o que dá para relacionar hoje (o alerta de metodologia e a regra)", async () => {
    semear();
    responder("GET", "/redes/1/analise/relacao", relacao());
    renderComApp(<AnaliseEducacional />, { rota: "/rede/analise?ver=relacao", usuario: secretaria });
    const situacao = await screen.findByTestId("situacao-relacao");
    expect(situacao).toHaveTextContent("As plataformas têm dados do ano letivo 2026; as avaliações por escola vão até 2025.");
    expect(situacao).toHaveTextContent("MESMO ano letivo, em ao menos 8 escolas");
    // Vem antes da escolha do indicador (a conclusão primeiro).
    const escolha = screen.getByRole("group", { name: "Indicador oficial (por escola)" });
    expect(situacao.compareDocumentPosition(escolha) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("sem o alerta de metodologia, a regra continua (nada some em silêncio)", async () => {
    semear({ alertas: [] });
    responder("GET", "/redes/1/analise/relacao", relacao());
    renderComApp(<AnaliseEducacional />, { rota: "/rede/analise?ver=relacao", usuario: secretaria });
    expect(await screen.findByTestId("situacao-relacao"))
      .toHaveTextContent(/^A relação só é calculada com números oficiais e de plataforma do MESMO ano letivo/);
  });
});

// =============================================================================
// Revisão visual v2 — filtro de período e o estado vazio no cartão
// =============================================================================

describe("Análises avançadas — revisão visual v2", () => {
  it("o Período é um campo como Escola e Série (rótulo ligado, lista nativa) e o escolhido vai para a API", async () => {
    semear();
    renderComApp(<AnaliseEducacional />, { rota: "/rede/analise", usuario: secretaria });
    await screen.findByTestId("tabela-diagnostico");

    // O mesmo tipo de campo dos vizinhos: <select> com o rótulo visível ligado a ele.
    const periodo = screen.getByLabelText("Período");
    expect(periodo.tagName).toBe("SELECT");
    expect(periodo).toHaveValue("ano_letivo");
    expect(within(screen.getByTestId("filtros-compartilhados")).getByLabelText("Escola").tagName).toBe("SELECT");
    expect(within(periodo).getByRole("option", { name: "3º bimestre" })).toBeInTheDocument();

    // O período vale para o lado das plataformas do diagnóstico (a janela dele).
    await userEvent.selectOptions(periodo, "bimestre_3");
    await waitFor(() => expect(chamadas("/redes/1/analise/diagnostico")
      .some((c) => query(c).get("periodo") === "bimestre_3")).toBe(true));

    // A Secretaria escolhe o ano letivo ou um bimestre inteiro (G_GRUPO-2): sem o personalizado,
    // o dia, a semana e o mês — a diferença entre dois períodos sobrepostos mostraria uma criança.
    const opcoes = within(periodo).getAllByRole("option").map((o) => (o as HTMLOptionElement).value);
    expect(opcoes).toEqual(["bimestre", "bimestre_anterior", "bimestre_1", "bimestre_2", "bimestre_3",
                            "bimestre_4", "ano_letivo"]);
    expect(screen.getByTestId("onde-valem-os-filtros"))
      .toHaveTextContent("Para a Secretaria, o período é o ano letivo ou um bimestre inteiro");
  });

  it("o admin global continua com o personalizado (as duas datas) nas análises avançadas", async () => {
    responder("GET", "/redes", [{ id: 1, nome: "Rede Sintética Norte" }]);
    semear();
    renderComApp(<AnaliseEducacional />, { rota: "/rede/analise", usuario: admin });
    await screen.findByTestId("tabela-diagnostico");
    await userEvent.selectOptions(screen.getByLabelText("Período"), "personalizado");
    expect(screen.getByLabelText("Data inicial")).toBeInTheDocument();
    expect(screen.getByLabelText("Data final")).toBeInTheDocument();
    expect(screen.getByTestId("onde-valem-os-filtros")).not.toHaveTextContent("Para a Secretaria");
  });

  it("a Secretaria com um período guardado de outra tela (este mês) lê o ano letivo", async () => {
    semear();
    renderComApp(<AnaliseEducacional />, { rota: "/rede/analise", usuario: secretaria,
                                           periodo: { preset: "mes" } });
    await screen.findByTestId("tabela-diagnostico");
    expect(screen.getByLabelText("Período")).toHaveValue("ano_letivo");
    const pedidos = chamadas("/redes/1/analise/diagnostico");
    expect(pedidos.length).toBeGreaterThan(0);
    expect(pedidos.every((c) => query(c).get("periodo") === "ano_letivo")).toBe(true);
  });

  it("sem rede: a mensagem e o 'Gerenciar redes' ficam no MESMO cartão (como em /rede)", async () => {
    responder("GET", "/redes", []);
    renderComApp(<AnaliseEducacional />, { rota: "/rede/analise", usuario: admin });
    expect(await screen.findByRole("heading", { level: 1, name: "Análises avançadas" })).toBeInTheDocument();
    const titulo = await screen.findByText("Nenhuma rede disponível");
    const cartao = titulo.closest(".card") as HTMLElement;
    expect(cartao).not.toBeNull();
    expect(within(cartao).getByText(/Ainda não há redes cadastradas/)).toBeInTheDocument();
    expect(within(cartao).getByRole("button", { name: /Gerenciar redes/ })).toBeInTheDocument();
  });
});
