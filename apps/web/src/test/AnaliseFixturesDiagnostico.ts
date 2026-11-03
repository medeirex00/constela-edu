/**
 * Exemplos INVENTADOS (regra D13 — nenhum nome, código ou arquivo real) para os testes das
 * abas novas da análise educacional: catálogo, diagnóstico exploratório, evolução por
 * bimestre e plataformas no período, no formato do contrato (DESENHO B.1/B.2 e o endpoint
 * das plataformas). Não é arquivo de teste (o vitest só roda `*.test.tsx`).
 *
 * O mundo: 4 escolas de uma rede sintética, entregues FORA de ordem alfabética (a tela é que
 * ordena — nunca ranking):
 *  - Alfa (2): "acompanhar" — LP divergente com uso baixo; MT pela base GERAL (IEE), em
 *    atenção, com uso alto; IEE com meta não atingida; SARESP 5º LP acima da rede;
 *  - Beta (3): "prioritário" — LP convergente em atenção; SARESP MT com média instável;
 *  - Gama (4): "dados insuficientes" — sem código INEP, Elefante protegido (k);
 *  - Delta (5): "sem sinal" — Ideb 2023 na média da rede.
 */
import type { FonteOficial } from "../components/SeloFonte";
import type {
  IndicadorAnalise, RespostaIndicadoresRede, RespostaPlataformas,
} from "../pages/analise/tipos";
import type {
  EscolaDiagnostico, OficialDiagnostico, RespostaDiagnostico, RespostaEvolucao, SinalDiagnostico,
} from "../pages/analise/tiposDiagnostico";
import { usuarioFake } from "./utils";

export const secretaria = usuarioFake({ nome: "Secretaria", cargo: "coordenador", rede_id: 1, escola_id: null });
export const admin = usuarioFake({ nome: "Root", cargo: "admin", is_global: true, escola_id: null });

export const FONTE: FonteOficial = {
  importacao_id: 21, fonte_nome: "SEDUC-SP — arquivo sintético por escola",
  arquivo_nome: "iee_sintetico_2025.csv", arquivo_data: null, last_modified_origem: null,
  url_origem: null, edicao_arquivo: 2025, versao_rotulo: null, importado_em: "2026-10-17T12:00:00",
  coletado_em: null, citacao: null, licenca: "Dados abertos sintéticos: citar a fonte.",
  parser: "seduc_iee", modo: "upload", notas: [], data_arquivo: "2026-01-12", data_arquivo_origem: "last_modified",
};

function indicador(over: Partial<IndicadorAnalise>): IndicadorAnalise {
  return {
    chave: "x", nome: "X", orgao: "INEP", oficial: true, unidade: "pontos", escala: "escala_saresp",
    disponivel: true, motivo_indisponivel: null, abrangencias: ["rede", "escola"], por_escola: true,
    etapas: ["5_ano"], componentes: ["lp", "mt"], edicoes: [2024, 2025], edicao_mais_recente: 2025,
    tem_meta: false, avisos: [], ...over,
  };
}

export const ESCOLAS_REDE = [
  { id: 3, nome: "EMEF Sintética Beta", codigo_inep: "35990003", pendencia: null },
  { id: 2, nome: "EMEF Sintética Alfa", codigo_inep: "35990002", pendencia: null },
  { id: 4, nome: "EMEI Sintética Gama", codigo_inep: null, pendencia: "sem_codigo_inep" },
  { id: 5, nome: "EMEF Sintética Delta", codigo_inep: "35990005", pendencia: null },
];

export function baseRede(over: Partial<RespostaIndicadoresRede> = {}): RespostaIndicadoresRede {
  return {
    rede: { id: 1, nome: "Rede Sintética Norte", codigo_ibge: "3599999" },
    indicadores: [
      indicador({ chave: "iee", nome: "IEE", orgao: "SEDUC-SP", unidade: "índice", escala: "indice_iee",
                  abrangencias: ["escola"], etapas: ["anos_iniciais"], componentes: [], tem_meta: true }),
      indicador({ chave: "ideb", nome: "Ideb", unidade: "índice", escala: "indice_ideb", etapas: ["anos_iniciais"],
                  componentes: [], edicoes: [2021, 2023], edicao_mais_recente: 2023, tem_meta: true }),
      indicador({ chave: "saresp", nome: "SARESP", orgao: "SEDUC-SP", etapas: ["5_ano", "2_ano"] }),
    ],
    destaques: [
      { indicador: "saresp", rotulo: "SARESP da rede — 5º ano, Língua Portuguesa", edicao: 2025, valor: 212.4,
        casas: 1, unidade: "pontos", meta: null, diferenca_meta: null, situacao_meta: null, etapa: "5_ano",
        componente: "lp", fonte_id: 21, serie: [{ edicao: 2024, valor: 210.0 }, { edicao: 2025, valor: 212.4 }] },
    ],
    estimativas: [],
    escolas: ESCOLAS_REDE,
    alertas: [
      { tipo: "metodologia", escolas: [],
        texto: "As plataformas têm dados do ano letivo 2026; as avaliações por escola vão até 2025 (sintético)." },
    ],
    metodologia_resumo: ["Sem resultado não é zero (texto sintético)."],
    fontes: { "21": FONTE },
    ...over,
  };
}

export function oficial(over: Partial<OficialDiagnostico>): OficialDiagnostico {
  return {
    indicador: "saresp", rotulo: "SARESP · 5º ano · LP", etapa: "5_ano", componente: "lp", edicao: 2025,
    valor: 200, casas: 1, meta: null, situacao_meta: null, instavel: false, fonte_id: 21, valor_rede: 212.4,
    diferenca_rede: null, posicao_rede: null, motivo_sem_comparacao: null, anterior: null, tendencia: null,
    ...over,
  };
}

function sinal(over: Partial<SinalDiagnostico>): SinalDiagnostico {
  return {
    codigo: "x", eixo: "avaliacao", componente: "lp", natureza: "calculado", direcao: "informativo",
    texto: "texto sintético", referencia: "referência sintética", ...over,
  };
}

const JANELA = "Elefante · 01/01/2026–31/12/2026";

const ALFA: EscolaDiagnostico = {
  id: 2, nome: "EMEF Sintética Alfa", codigo_inep: "35990002", pendencias: [],
  oficiais: [
    oficial({ valor: 219.6, diferenca_rede: 7.2, posicao_rede: "acima", anterior: { edicao: 2024, valor: 214.0 },
              tendencia: "subiu" }),
    oficial({ indicador: "iee", rotulo: "IEE · anos iniciais", etapa: "anos_iniciais", componente: null, valor: 4.8,
              casas: 2, meta: 5.2, situacao_meta: "nao_atingiu", valor_rede: null,
              motivo_sem_comparacao: "o IEE só existe por escola: não há número da rede para comparar" }),
  ],
  plataformas: {
    cobertura: { elefante: "ok", matific: "ok" },
    ultima_coleta: { elefante: "2026-10-18T03:10:00", matific: "2026-10-19T03:12:00" },
    elefante: { participacao_pct: 55, livros_por_aluno: 2.1, minutos_por_aluno: 40.5, taxa_acerto_pct: 70,
                suprimido: false, posicao_participacao: "abaixo", posicao_intensidade: "na_media" },
    matific: { participacao_pct: 90, atividades_por_aluno: 20.5, desempenho_medio: 3.1, suprimido: false,
               posicao_participacao: "acima", posicao_intensidade: "acima" },
  },
  sinais: [
    sinal({ codigo: "meta_iee", natureza: "oficial", direcao: "atencao", componente: "geral",
            texto: "IEE 2025: 4,80, abaixo da meta 5,20 (não atingiu).", referencia: "IEE 2025" }),
    sinal({ codigo: "posicao_rede", natureza: "calculado", direcao: "favoravel",
            texto: "SARESP 2025, 5º ano, LP: 219,6 — 7,2 pontos acima da rede municipal (212,4).",
            referencia: "SARESP 2025 · 5º ano · LP" }),
    sinal({ codigo: "participacao", eixo: "plataforma", natureza: "plataforma", direcao: "atencao",
            texto: "Elefante: participação de 55% — abaixo da rede (68,3%).", referencia: JANELA }),
    sinal({ codigo: "coleta_parcial", eixo: "dados", natureza: "dados", direcao: "informativo", componente: "geral",
            texto: "Matific: a última coleta é de 19/10/2026.", referencia: "Matific · 01/01/2026–31/12/2026" }),
  ],
  leituras: {
    lp: { avaliacao: "favoravel", base: "componente", plataforma: "atencao", categoria: "divergente_uso_baixo",
          texto: "Leitura: avaliação favorável e uso do Elefante abaixo da rede (sintético).",
          anos: { avaliacao: 2025, plataforma: 2026 }, comparabilidade: "exploratoria" },
    // A forma "objeto" do eixo (estado + base): a tela aceita as duas.
    mt: { avaliacao: { estado: "atencao", base: "geral" }, plataforma: "favoravel", categoria: "divergente_uso_alto",
          texto: "Matemática: IEE em atenção e uso do Matific acima da rede (sintético).",
          anos: { avaliacao: 2025, plataforma: 2026 }, comparabilidade: "exploratoria" },
  },
  acompanhamento: { nivel: "acompanhar", motivos: ["IEE 2025: meta oficial não atingida (IEE 2025)",
    "Matemática: uso alto do Matific com avaliação em atenção (Matific · 01/01/2026–31/12/2026)"] },
};

const BETA: EscolaDiagnostico = {
  id: 3, nome: "EMEF Sintética Beta", codigo_inep: "35990003", pendencias: [],
  oficiais: [
    oficial({ valor: 198.0, diferenca_rede: -14.4, posicao_rede: "abaixo", anterior: { edicao: 2024, valor: 205.1 },
              tendencia: "caiu" }),
    oficial({ rotulo: "SARESP · 5º ano · MT", componente: "mt", valor: 230.1, instavel: true, valor_rede: 221.0,
              motivo_sem_comparacao: "média instável (TPS = 0): sem posição nem tendência" }),
  ],
  plataformas: {
    cobertura: { elefante: "ok", matific: "ok" }, ultima_coleta: { elefante: "2026-10-18T03:10:00", matific: null },
    elefante: { participacao_pct: 40, livros_por_aluno: 0.9, minutos_por_aluno: 12, taxa_acerto_pct: null,
                suprimido: false, posicao_participacao: "abaixo", posicao_intensidade: "abaixo" },
    matific: null,
  },
  sinais: [
    sinal({ codigo: "posicao_rede", natureza: "calculado", direcao: "atencao",
            texto: "SARESP 2025, 5º ano, LP: 198,0 — 14,4 pontos abaixo da rede municipal (212,4).",
            referencia: "SARESP 2025 · 5º ano · LP" }),
    sinal({ codigo: "tendencia", natureza: "calculado", direcao: "atencao",
            texto: "SARESP 5º ano, LP: caiu de 205,1 (2024) para 198,0 (2025).", referencia: "SARESP 2024–2025 · 5º ano · LP" }),
    sinal({ codigo: "participacao", eixo: "plataforma", natureza: "plataforma", direcao: "atencao",
            texto: "Elefante: participação de 40% — abaixo da rede (68,3%).", referencia: JANELA }),
    sinal({ codigo: "instavel", eixo: "dados", natureza: "dados", direcao: "informativo", componente: "mt",
            texto: "SARESP 2025, 5º ano, MT: média instável (TPS = 0).", referencia: "SARESP 2025 · 5º ano · MT" }),
  ],
  leituras: {
    lp: { avaliacao: "atencao", base: "componente", plataforma: "atencao", categoria: "convergente_atencao",
          texto: "Leitura: avaliação e uso do Elefante em atenção (sintético).",
          anos: { avaliacao: 2025, plataforma: 2026 }, comparabilidade: "exploratoria" },
    mt: { avaliacao: "sem_dado", base: "componente", plataforma: "sem_dado", categoria: "inconclusiva",
          motivo: "sem sinal de avaliação (média instável) nem Matific contratado", texto: "Matemática: inconclusiva (sintético).",
          anos: { avaliacao: 2025, plataforma: 2026 }, comparabilidade: "exploratoria" },
  },
  acompanhamento: { nivel: "prioritario", motivos: ["Leitura: avaliação e plataforma em atenção (SARESP 2025 · 5º ano · LP)"] },
};

const GAMA: EscolaDiagnostico = {
  id: 4, nome: "EMEI Sintética Gama", codigo_inep: null, pendencias: ["sem_codigo_inep"],
  oficiais: [],
  plataformas: {
    cobertura: null, ultima_coleta: null,
    elefante: { participacao_pct: null, livros_por_aluno: null, minutos_por_aluno: null, taxa_acerto_pct: null,
                suprimido: true, texto_supressao: "poucos alunos: os números não aparecem, para proteger as crianças",
                posicao_participacao: null, posicao_intensidade: null },
    matific: null,
  },
  sinais: [
    sinal({ codigo: "sem_inep", eixo: "dados", natureza: "dados", direcao: "informativo", componente: "geral",
            texto: "Sem código INEP no cadastro: os arquivos oficiais não casam.", referencia: "Cadastro da escola" }),
    sinal({ codigo: "protegido", eixo: "dados", natureza: "dados", direcao: "informativo", componente: "lp",
            texto: "Elefante: célula protegida (poucos alunos).", referencia: JANELA }),
  ],
  leituras: {
    lp: { avaliacao: "sem_dado", plataforma: "sem_dado", categoria: "inconclusiva", motivo: "sem dado nos dois eixos",
          texto: "Leitura: sem dado (sintético).", anos: { avaliacao: null, plataforma: 2026 }, comparabilidade: "exploratoria" },
    mt: { avaliacao: "sem_dado", plataforma: "sem_dado", categoria: "inconclusiva", motivo: "sem dado nos dois eixos",
          texto: "Matemática: sem dado (sintético).", anos: { avaliacao: null, plataforma: 2026 }, comparabilidade: "exploratoria" },
  },
  acompanhamento: { nivel: "dados_insuficientes", motivos: ["Sem número oficial e sem plataforma medida"] },
};

const DELTA: EscolaDiagnostico = {
  id: 5, nome: "EMEF Sintética Delta", codigo_inep: "35990005", pendencias: [],
  oficiais: [
    oficial({ indicador: "ideb", rotulo: "Ideb · anos iniciais", etapa: "anos_iniciais", componente: null, edicao: 2023,
              valor: 6.1, casas: 1, valor_rede: 6.0, diferenca_rede: 0.1, posicao_rede: "na_media" }),
  ],
  plataformas: {
    cobertura: { elefante: "coleta_parcial", matific: "ok" }, ultima_coleta: { elefante: "2026-09-20T00:10:00", matific: null },
    elefante: { participacao_pct: 70, livros_por_aluno: 3, minutos_por_aluno: 50, taxa_acerto_pct: 72, suprimido: false,
                posicao_participacao: null, posicao_intensidade: null,
                motivo_sem_comparacao: "coleta parcial: a escola não entra na comparação com a rede" },
    matific: null,
  },
  sinais: [
    sinal({ codigo: "posicao_rede", natureza: "calculado", direcao: "informativo", componente: "geral",
            texto: "Ideb 2023: 6,1 — na média da rede municipal (6,0).", referencia: "Ideb 2023" }),
  ],
  leituras: {
    lp: { avaliacao: "sem_dado", plataforma: "sem_dado", categoria: "inconclusiva", motivo: "sem sinal nos dois eixos",
          texto: "Leitura: inconclusiva (sintético).", anos: { avaliacao: 2023, plataforma: 2026 }, comparabilidade: "exploratoria" },
    mt: { avaliacao: "sem_dado", plataforma: "sem_dado", categoria: "inconclusiva", motivo: "sem sinal nos dois eixos",
          texto: "Matemática: inconclusiva (sintético).", anos: { avaliacao: 2023, plataforma: 2026 }, comparabilidade: "exploratoria" },
  },
  acompanhamento: { nivel: "sem_sinal", motivos: [] },
};

export function diagnostico(over: Partial<RespostaDiagnostico> = {}): RespostaDiagnostico {
  return {
    rede: { id: 1, nome: "Rede Sintética Norte" },
    janela: { inicio: "2026-01-01", fim: "2026-12-31", rotulo: "Ano letivo de 2026", ano_letivo: 2026 },
    gerado_em: "2026-10-20T09:30:00",
    criterios: {
      tolerancias: { participacao_pp: 5, intensidade_pct: 15, ideb: 0.2, iee: 0.2, saresp: 5, saeb: 5 },
      n_minimo_escolas_comparacao: 3,
      regras: ["Sem ranking: as escolas aparecem em ordem alfabética (texto sintético).",
               "Média instável (TPS = 0) não gera sinal de posição nem de tendência (texto sintético)."],
    },
    referencias_rede: [
      { indicador: "saresp", etapa: "5_ano", componente: "lp", edicao: 2025, valor: 212.4, casas: 1, fonte_id: 21 },
    ],
    // Fora de ordem alfabética de propósito: a tela ordena.
    escolas: [DELTA, BETA, GAMA, ALFA],
    resumo: {
      por_nivel: { prioritario: 1, acompanhar: 1, oportunidade: 0, dados_insuficientes: 1, sem_sinal: 1 },
      por_categoria: { lp: { convergente_atencao: 1, divergente_uso_baixo: 1, inconclusiva: 2 },
                       mt: { divergente_uso_alto: 1, inconclusiva: 3 } },
      escolas_total: 4, escolas_com_oficial: 3, escolas_com_plataforma: 3,
      anos: { avaliacao_mais_recente: 2025, plataforma: 2026 },
    },
    limitacoes: ["Os resultados oficiais são de outra coorte de alunos (texto sintético)."],
    metodologia: ["A posição contra a rede usa uma tolerância por indicador (texto sintético)."],
    fontes: { "21": FONTE },
    ...over,
  };
}

/** O rótulo vem como o backend manda (`periodos._bimestre`): "1º bimestre (02/02 a 17/04)" — já com as datas. */
export function evolucao(over: Partial<RespostaEvolucao> = {}): RespostaEvolucao {
  const escolas = (pE: number | null, pM: number | null) => [
    { id: 2, nome: "EMEF Sintética Alfa", cobertura: { elefante: "ok", matific: "ok" },
      elefante: pE == null ? null : { participacao_pct: pE, livros_por_aluno: 1.25 },
      matific: pM == null ? null : { participacao_pct: pM, atividades_por_aluno: 6.5 } },
    { id: 3, nome: "EMEF Sintética Beta", cobertura: { elefante: "sem_coleta_no_periodo", matific: "ok" },
      elefante: null, matific: { participacao_pct: 50, atividades_por_aluno: 4 } },
  ];
  return {
    ano_letivo: 2026, k_minimo: 5,
    bimestres: [
      { numero: 1, rotulo: "1º bimestre (02/02 a 17/04)", inicio: "2026-02-02", fim: "2026-04-17", em_andamento: false,
        rede: { elefante: { participacao_pct: 61.2, livros_por_aluno: 1.4, minutos_por_aluno: 38.5 },
                matific: { participacao_pct: 70.4, atividades_por_aluno: 8.25 },
                escolas_com_dado: { elefante: 3, matific: 3 }, escolas_parciais: { elefante: 0, matific: 0 } },
        escolas: escolas(58, 72) },
      { numero: 2, rotulo: "2º bimestre (20/04 a 03/07)", inicio: "2026-04-20", fim: "2026-07-03", em_andamento: false,
        rede: { elefante: { participacao_pct: 66, livros_por_aluno: 1.7, minutos_por_aluno: 41 },
                // Sem coleta do Matific no bimestre: sem dado (nunca 0).
                matific: { participacao_pct: null, atividades_por_aluno: null },
                escolas_com_dado: { elefante: 3, matific: 0 }, escolas_parciais: 1 },
        escolas: escolas(60, null) },
      { numero: 3, rotulo: "3º bimestre (03/08 a 09/10)", inicio: "2026-08-03", fim: "2026-10-09", em_andamento: false,
        rede: { elefante: { participacao_pct: 64.5, livros_por_aluno: 1.6, minutos_por_aluno: 40 },
                matific: { participacao_pct: 75, atividades_por_aluno: 9 },
                escolas_com_dado: 3, escolas_parciais: 0 },
        escolas: escolas(62, 70) },
      { numero: 4, rotulo: "4º bimestre (13/10 a 18/12)", inicio: "2026-10-13", fim: "2026-12-18", em_andamento: true,
        rede: { elefante: { participacao_pct: 30.1, livros_por_aluno: 0.4, minutos_por_aluno: 10 },
                matific: { participacao_pct: 35, atividades_por_aluno: 2 },
                escolas_com_dado: 3, escolas_parciais: 0 },
        escolas: escolas(25, 30) },
    ],
    limitacoes: ["O bimestre em andamento ainda não terminou (texto sintético)."],
    ...over,
  };
}

const ELEFANTE = {
  alunos_medidos: 100, alunos_com_leitura: 70, participacao_pct: 70, livros_por_aluno: 3.25, minutos_por_aluno: 45.5,
  nivel_medio: "K", taxa_acerto_pct: 72.5, janela_questoes: null, coleta_parcial: false, coberto_ate: null,
  texto_cobertura: null,
};
const MATIFIC = {
  alunos_medidos: 90, alunos_com_retrato: 90, participacao_pct: 80, atividades_por_aluno: 14.25,
  estrelas_por_aluno: 30, desempenho_medio: 2.6, coleta_parcial: false, coberto_ate: null, texto_cobertura: null,
};
export const TEXTO_SUPRESSAO = "poucos alunos neste recorte (texto sintético): os números não aparecem, para proteger as crianças";

export function plataformasRede(over: Partial<RespostaPlataformas> = {}): RespostaPlataformas {
  return {
    janela: { inicio: "2026-01-01", fim: "2026-12-31", rotulo: "Ano letivo de 2026" },
    modulos: { elefante: true, matific: true }, k_minimo: 5,
    rede: { alunos: 400, elefante: ELEFANTE, matific: MATIFIC },
    escolas: [
      { escola_id: 3, nome: "EMEF Sintética Beta", alunos: 120,
        cobertura: { elefante: "coleta_parcial", matific: "ok" },
        coberto_ate: { elefante: "2026-09-20T00:10:00-03:00", matific: null },
        elefante: { ...ELEFANTE, participacao_pct: 85, coleta_parcial: true }, matific: { ...MATIFIC, participacao_pct: 75 },
        series: [] },
      { escola_id: 2, nome: "EMEF Sintética Alfa", alunos: 150, cobertura: { elefante: "ok", matific: "ok" },
        elefante: ELEFANTE,
        matific: { ...MATIFIC, participacao_pct: null, atividades_por_aluno: null, desempenho_medio: null,
                   estrelas_por_aluno: null, motivo_sem_dado: "poucos_alunos_medidos",
                   texto_sem_dado: "menos de 5 alunos com dado desta plataforma no período" },
        series: [] },
      { escola_id: 4, nome: "EMEI Sintética Gama", alunos: null, suprimido: true, motivo_supressao: "suprimido",
        texto_supressao: TEXTO_SUPRESSAO, cobertura: null, ultima_coleta: null, coberto_ate: null,
        dias_desde_ultima_coleta: null, elefante: null, matific: null, series: [] },
      { escola_id: 5, nome: "EMEF Sintética Delta", alunos: 130, cobertura: { elefante: "ok", matific: "ok" },
        elefante: { ...ELEFANTE, taxa_acerto_pct: null },
        matific: { ...MATIFIC, desempenho_medio: null, metricas_protegidas: ["desempenho_medio"],
                   texto_metricas_protegidas: "média escondida em complemento (texto sintético)" },
        series: [] },
    ],
    cobertura: { escopo: "escolas_visiveis",
                 ultima_coleta: { elefante: "2026-10-18T03:10:00", matific: "2026-10-19T03:12:00" },
                 escolas_sem_coleta: [], escolas_sem_coleta_no_periodo: { elefante: [], matific: [] },
                 escolas_coleta_parcial: { elefante: [3], matific: [] },
                 primeiro_evento_elefante: "2026-02-03", dias_desde_ultima_coleta: 1 },
    limitacoes: ["Questões do Elefante: o intervalo real é o das coletas (texto sintético)."],
    ...over,
  };
}

/** A família de cada leitura da API (para conferir que cada aba só lê o que precisa). */
export function familia(url: string): string | null {
  const caminho = url.split("?")[0];
  if (caminho === "/redes/1/analise/indicadores") return "indicadores";
  if (caminho.startsWith("/redes/1/analise/indicadores/")) return "indicador";
  if (caminho === "/redes/1/analise/plataformas") return "plataformas";
  if (caminho === "/redes/1/analise/plataformas/evolucao") return "evolucao";
  if (caminho === "/redes/1/analise/diagnostico") return "diagnostico";
  if (caminho === "/redes/1/analise/relacao") return "relacao";
  if (/^\/escolas\/\d+\/analise$/.test(caminho)) return "escola";
  if (caminho === "/redes/1/boletim") return "boletim";
  return null;
}
