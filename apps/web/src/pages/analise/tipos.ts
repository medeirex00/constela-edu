/**
 * Tipos da ANÁLISE EDUCACIONAL integrada — o formato EXATO do contrato técnico dos
 * endpoints de leitura (frente B, `backend/app/routers/analise.py`):
 *
 *  1. `GET /redes/{rede_id}/analise/indicadores`            → RespostaIndicadoresRede
 *  2. `GET /redes/{rede_id}/analise/indicadores/{chave}`    → RespostaIndicador
 *  3. `GET /redes/{rede_id}/analise/plataformas`            → RespostaPlataformas
 *  4. `GET /redes/{rede_id}/analise/relacao`                → RespostaRelacao
 *  5. `GET /escolas/{escola_id}/analise`                    → RespostaAnaliseEscola
 *
 * Regras que os tipos carregam (e as telas respeitam):
 *  - AUSÊNCIA ≠ ZERO: `valor: null` vem com `motivo_ausencia`/`texto_ausencia`; a tela
 *    escreve o motivo por extenso, nunca "0".
 *  - PRECISÃO: `casas` é a precisão publicada — a tela formata nela, sem inventar casas.
 *  - FONTE: cada ponto aponta `fonte_id` para `fontes` (o formato canônico de fonte dos
 *    indicadores oficiais, o mesmo do `SeloFonte`); a fonte só aparece em "Detalhes e
 *    fontes", nunca no cartão da interface principal.
 *  - NENHUM dado de aluno: as plataformas chegam agregadas por escola e série, com as
 *    células pequenas (< k alunos) suprimidas pelo backend (motivo único "suprimido":
 *    a célula pequena e a escondida junto têm o MESMO texto).
 *  - PROVENIÊNCIA: o número com valor diz de onde vem — "oficial" (com o registro do
 *    arquivo) ou "sem_registro" (gravado antes, pelo botão de 1 clique, sem o registro do
 *    arquivo). O "sem_registro" aparece MARCADO (*) nas séries e na visão por escolas e
 *    não é a Estimativa Constela (que só vem em `estimativas`, à parte).
 */
import type { FonteOficial } from "../../components/SeloFonte";

export type ChaveIndicador = "ica" | "saresp" | "iee" | "ideb" | "saeb";
export type SituacaoMeta = "atingiu" | "nao_atingiu" | "inconclusivo";
/** "oficial" = com o registro do arquivo; "sem_registro" = gravado antes, sem esse registro. */
export type Proveniencia = "oficial" | "sem_registro";

/** Os campos de proveniência de um número com valor (sem valor: null). */
export interface ComProveniencia {
  proveniencia?: Proveniencia | string | null;
  /** "número gravado antes, sem o registro do arquivo oficial" (+ "; difere do arquivo oficial"). */
  texto_proveniencia?: string | null;
  /** O número sem registro é diferente do que o arquivo oficial importado traz. */
  difere_do_oficial?: boolean;
}

/** Um indicador oficial do catálogo da análise (item do endpoint 1). */
export interface IndicadorAnalise {
  chave: ChaveIndicador | string;
  nome: string;
  orgao: string;
  oficial: boolean;
  /** "%" | "pontos" | "índice" */
  unidade: string;
  /** percentual | escala_saresp | escala_saeb | indice_ideb | indice_iee */
  escala: string;
  disponivel: boolean;
  motivo_indisponivel: string | null;
  /** O motivo em linguagem simples (quando o backend o manda). */
  texto_indisponivel?: string | null;
  /** "rede" e/ou "escola" — o ICA é só da rede; o IEE, só da escola. */
  abrangencias: string[];
  por_escola: boolean;
  etapas: string[];
  componentes: string[];
  edicoes: number[];
  edicao_mais_recente: number | null;
  tem_meta: boolean;
  /** Textos curtos de comparabilidade (escala própria, outra rede, amostral…). */
  avisos: string[];
  /** Rótulos das etapas e dos componentes como o backend os escreve. */
  rotulos_etapas?: Record<string, string>;
  rotulos_componentes?: Record<string, string>;
}

/** Um número de capa da Visão geral (o mais recente divulgado, da rede). */
export interface DestaqueAnalise {
  indicador: string;
  rotulo: string;
  edicao: number;
  valor: number | null;
  casas: number | null;
  unidade: string;
  meta: number | null;
  meta_casas?: number | null;
  diferenca_meta: number | null;
  /** A precisão da diferença (a menor dos dois lados), quando o backend a manda. */
  diferenca_casas?: number | null;
  situacao_meta: SituacaoMeta | null;
  motivo_ausencia?: string | null;
  texto_ausencia?: string | null;
  texto_sem_meta?: string | null;
  etapa?: string | null;
  componente?: string | null;
  fonte_id?: number | null;
  /** Minitendência: as edições anteriores (valor nulo = sem resultado, nunca 0). */
  serie: { edicao: number; valor: number | null; casas?: number | null }[];
}

/** Estimativa do Constela: separada e rotulada — nunca entra em série oficial. */
export interface EstimativaAnalise {
  chave: string;
  nome: string;
  edicoes: number[];
  /** Sempre "estimativa_constela" (calculada pelo Constela). */
  tipo?: string;
  oficial?: boolean;
  escolas?: number;
}

/** Números gravados antes, sem o registro do arquivo oficial (o "1 clique"): NÃO são a
 *  Estimativa Constela — aparecem marcados nas séries e fora dos destaques e da relação. */
export interface SemRegistroAnalise {
  chave: string;
  nome: string;
  tipo?: string;
  oficial?: boolean;
  edicoes: number[];
  escolas_por_edicao?: Record<string, number>;
  numeros?: number;
  /** Quantos desses números diferem do arquivo oficial importado. */
  difere_do_oficial?: number;
  texto?: string | null;
}

export interface EscolaDaRede {
  id: number;
  nome: string;
  codigo_inep: string | null;
  /** "sem_codigo_inep" quando o cadastro não tem o código (os arquivos oficiais não casam). */
  pendencia: string | null;
}

export interface AlertaAnalise {
  tipo: "cadastro" | "desatualizado" | "insuficiente" | "sem_registro" | "ausente" | "metodologia" | string;
  texto: string;
  /** Ids das escolas envolvidas (o nome vem de `escolas`). */
  escolas: number[];
  /** O indicador do alerta (quando é de um indicador): leva à visão por escolas. */
  indicador?: string | null;
}

/** Endpoint 1 — catálogo + destaques + escolas + alertas da rede. */
export interface RespostaIndicadoresRede {
  rede: { id: number; nome: string; codigo_ibge: string | null };
  indicadores: IndicadorAnalise[];
  destaques: DestaqueAnalise[];
  /** Só a Estimativa Constela (calculada pelo Constela). */
  estimativas: EstimativaAnalise[];
  /** Os números gravados antes, sem o registro do arquivo oficial (marcados nas séries). */
  sem_registro_oficial?: SemRegistroAnalise[];
  escolas: EscolaDaRede[];
  alertas: AlertaAnalise[];
  /** Como a análise é feita, em linguagem simples (sem caminho de arquivo). */
  metodologia_resumo?: string[];
  /** As fontes dos números dos destaques (para "Detalhes e fontes"). */
  fontes?: Record<string, FonteOficial>;
}

/** Um ponto (edição) de uma série oficial. */
export interface PontoAnalise extends ComProveniencia {
  edicao: number;
  valor: number | null;
  casas: number | null;
  /** Mais casas, de outro arquivo (ex.: microdados) — só para conferência, em "Detalhes". */
  valor_detalhado?: number | null;
  casas_detalhe?: number | null;
  /** ">" / ">=" quando a fonte publica "acima de" (ICA). */
  operador?: string | null;
  motivo_ausencia: string | null;
  texto_ausencia: string | null;
  meta: number | null;
  meta_casas: number | null;
  operador_meta?: string | null;
  /** Por que a edição não tem meta (texto do backend). */
  texto_sem_meta?: string | null;
  diferenca_meta: number | null;
  /** A precisão da diferença (a menor dos dois lados), quando o backend a manda. */
  diferenca_casas?: number | null;
  situacao_meta: SituacaoMeta | null;
  /** TPS = 0 no SARESP: a média da escola é instável. */
  instavel: boolean;
  /** IEE: o índice oficial foi calculado com médias de TPS = 0 (fica fora da relação). */
  tps_zero?: boolean;
  fonte_id: number | null;
}

/** Uma série: a principal (rede ou escola), uma referência (UF/Brasil na mesma rede) ou
 *  um contexto (outra rede — `comparavel=false` com o motivo). */
export interface SerieAnalise {
  id: string;
  rotulo: string;
  papel: "principal" | "referencia" | "contexto";
  abrangencia: "rede" | "escola" | "uf" | "brasil" | string;
  escola_id: number | null;
  rede_ensino: "municipal" | "publica" | "estadual" | string;
  mesma_rede: boolean;
  comparavel: boolean;
  motivo_nao_comparavel: string | null;
  /** Só na análise por escola (endpoint 5), quando o backend separa as séries. */
  etapa?: string | null;
  componente?: string | null;
  pontos: PontoAnalise[];
}

/** Uma escola na visão "escolas numa edição" — em ordem de NOME, nunca ranking. */
export interface LinhaEscolaAnalise extends ComProveniencia {
  escola_id: number;
  nome: string;
  codigo_inep?: string | null;
  pendencia?: string | null;
  valor: number | null;
  casas: number | null;
  motivo_ausencia: string | null;
  texto_ausencia: string | null;
  meta: number | null;
  meta_casas?: number | null;
  texto_sem_meta?: string | null;
  diferenca_meta: number | null;
  diferenca_casas?: number | null;
  situacao_meta?: SituacaoMeta | null;
  instavel: boolean;
  /** IEE calculado com médias de TPS = 0. */
  tps_zero?: boolean;
  fonte_id: number | null;
}

export interface FiltrosIndicador {
  etapa: string | null;
  componente: string | null;
  escola_id: number | null;
  de: number | null;
  ate: number | null;
  visao: "serie" | "escolas" | string;
  edicao: number | null;
}

/** Endpoint 2 — um indicador, recortado pelos filtros. */
export interface RespostaIndicador {
  indicador: IndicadorAnalise;
  filtros: FiltrosIndicador;
  opcoes: {
    etapas: string[];
    componentes: string[];
    edicoes: number[];
    escolas: { id: number; nome: string; tem_dado: boolean }[];
  };
  series: SerieAnalise[];
  escolas: LinhaEscolaAnalise[];
  quebras: { entre: [number, number]; texto: string }[];
  avisos: string[];
  /** Fonte canônica por id (a chave é o id em texto, como no JSON). */
  fontes: Record<string, FonteOficial>;
}

// --- Plataformas ---------------------------------------------------------------------

export interface JanelaAnalise {
  inicio: string | null;
  fim: string | null;
  rotulo: string;
  preset?: string;
  /** O ano letivo de referência das escolas (o das plataformas). */
  ano_letivo?: number | null;
  anos_letivos?: number[];
}

/** Até onde a coleta de uma plataforma vale no recorte (coleta parada = parcial). */
export interface CoberturaDoBloco {
  /** A última coleta usada é de mais de 7 dias antes do fim do período (ou de hoje). */
  coleta_parcial?: boolean;
  /** Até quando os números valem (ISO, horário de Brasília). */
  coberto_ate?: string | null;
  /** O texto da coleta parcial ("a coleta parou antes do fim do período…"). */
  texto_cobertura?: string | null;
  /** Bloco da REDE: escolas com coleta parcial que entram na soma (cobrem ≥ 90% do período). */
  escolas_coleta_parcial_na_soma?: number;
  /** Bloco da REDE: até quando vale a coleta mais antiga das parciais que entram na soma. */
  coberto_ate_parcial?: string | null;
  /** Bloco da REDE: o texto dessas parciais ("N escola(s) entram com a coleta até …"). */
  texto_parcial_na_soma?: string | null;
  /**
   * Total (escola, rede ou rede numa série): as médias escondidas EM COMPLEMENTO — o total
   * soma um grupo de menos de k alunos escondido numa parte dele, e a diferença o revelaria.
   */
  metricas_protegidas?: string[];
  texto_metricas_protegidas?: string | null;
}

/** Métricas do Elefante Letrado no período (null = sem dado, nunca 0 por ausência). */
export interface MetricasElefante extends CoberturaDoBloco {
  /** O DENOMINADOR: os alunos com conta no Elefante (alguma coleta) ou leitura no período. */
  alunos_medidos?: number | null;
  /** Alunos do recorte sem conta no Elefante (ficam fora da conta, não contam como zero). */
  alunos_sem_conta?: number | null;
  alunos_com_leitura: number | null;
  /** Sobre `alunos_medidos`. */
  participacao_pct: number | null;
  livros_por_aluno: number | null;
  minutos_por_aluno: number | null;
  nivel_medio: string | null;
  taxa_acerto_pct: number | null;
  /** A janela que as coletas realmente cobrem para as questões (pode ser menor). */
  janela_questoes: { inicio: string | null; fim: string | null; observacao?: string | null } | null;
  /** Algum aluno saiu do acerto porque o contador de questões dele diminuiu (sim/não). */
  contador_regrediu?: boolean | null;
  texto_contador_regrediu?: string | null;
  /** Posição média do nível (AA = 0 … Z = 29), quando há livros com nível. */
  nivel_medio_posicao?: number | null;
  /** Sem dado (sem coleta no período, módulo, sem alunos, poucos medidos): o porquê — nunca 0. */
  motivo_sem_dado?: string | null;
  texto_sem_dado?: string | null;
}

/** Métricas do Matific no período (null = sem dado, nunca 0 por ausência). */
export interface MetricasMatific extends CoberturaDoBloco {
  /** O DENOMINADOR: os alunos com coleta dentro do período (= `alunos_com_retrato`). */
  alunos_medidos?: number | null;
  alunos_com_retrato: number | null;
  alunos_sem_retrato?: number | null;
  /** % dos `alunos_medidos` que fizeram atividade no período. */
  participacao_pct: number | null;
  atividades_por_aluno: number | null;
  /** Nulo com menos de k alunos com atividade (senão refaria o desempenho). */
  estrelas_por_aluno: number | null;
  /** Estrelas ÷ atividades (escala 0–5). */
  desempenho_medio: number | null;
  janela_efetiva?: { inicio: string | null; fim: string | null; observacao?: string | null } | null;
  motivo_sem_dado?: string | null;
  texto_sem_dado?: string | null;
}

/** Uma série escolar (1º–5º ano) de uma escola. `suprimido` = poucos alunos (ou junto). */
export interface SeriePlataforma {
  serie: number;
  alunos: number | null;
  suprimido: boolean;
  /** Só "suprimido" (motivo único: a célula pequena e a escondida junto). */
  motivo_supressao?: string | null;
  /** O texto único da supressão (do backend). */
  texto_supressao?: string | null;
  elefante: MetricasElefante | null;
  matific: MetricasMatific | null;
}

/** Por plataforma (`elefante`, `matific`). */
type PorPlataforma<T> = { elefante: T; matific: T };

export interface EscolaPlataformas {
  escola_id: number;
  nome: string;
  ano_letivo?: number | null;
  alunos: number | null;
  /** A escola inteira com poucos alunos (ou suprimida junto): sem número nenhum — nem a
   *  cobertura, as datas ou a última coleta (vêm nulas). */
  suprimido?: boolean;
  motivo_supressao?: string | null;
  texto_supressao?: string | null;
  /** "ok" | "coleta_parcial" | "sem_coleta" | "sem_coleta_no_periodo" | … (null se suprimida). */
  cobertura?: PorPlataforma<string | null> | null;
  ultima_coleta?: PorPlataforma<string | null> | null;
  coberto_ate?: PorPlataforma<string | null> | null;
  dias_desde_ultima_coleta?: PorPlataforma<number | null> | null;
  /** Os blocos da escola somam só as séries mostradas (há série suprimida). */
  blocos_parciais?: boolean;
  texto_blocos?: string | null;
  elefante: MetricasElefante | null;
  matific: MetricasMatific | null;
  series: SeriePlataforma[];
}

export interface CoberturaPlataformas {
  /** "escolas_visiveis": as listas só têm as escolas mostradas (nenhuma suprimida). */
  escopo?: string;
  ultima_coleta: { elefante: string | null; matific: string | null };
  escolas_sem_coleta: number[];
  /** Por plataforma, as escolas sem coleta que cubra o período (ficam sem número). */
  escolas_sem_coleta_no_periodo?: Record<string, number[]>;
  /** Por plataforma, as escolas com a coleta parada antes do fim do período (fora da soma). */
  escolas_coleta_parcial?: Record<string, number[]>;
  primeiro_evento_elefante: string | null;
  dias_desde_ultima_coleta: number | null;
}

/** Endpoint 3 — engajamento nas plataformas no período, por rede/escola/série. */
export interface RespostaPlataformas {
  janela: JanelaAnalise;
  modulos: { elefante: boolean; matific: boolean };
  k_minimo: number;
  rede: {
    alunos: number | null;
    alunos_fora_do_recorte?: number | null;
    suprimido?: boolean;
    motivo_supressao?: string | null;
    texto_supressao?: string | null;
    /** Quantas escolas entraram na soma de cada plataforma. */
    escolas_com_dado?: Partial<PorPlataforma<number>>;
    /** "escolas_visiveis": os blocos somam só as escolas mostradas, com a coleta em dia. */
    escopo_blocos?: string;
    texto_blocos?: string | null;
    elefante: MetricasElefante | null;
    matific: MetricasMatific | null;
  };
  escolas: EscolaPlataformas[];
  cobertura: CoberturaPlataformas;
  limitacoes: string[];
}

// --- Relação ---------------------------------------------------------------------------

export interface CriteriosRelacao {
  metodo: string;
  n_minimo: number;
  k_minimo_alunos: number;
  exige_mesmo_ano_letivo: boolean;
  exige_mesma_serie: boolean;
  so_oficial: boolean;
  mesma_escala: boolean;
  /** A escola com a coleta parada antes do fim do período fica de fora. */
  exige_coleta_em_dia?: boolean;
  /** Médias instáveis (TPS = 0) ficam de fora. */
  exclui_instavel?: boolean;
  unidade?: string;
  ic?: string;
}

/** Uma escola "lado a lado": o número oficial (com o ano) e o da plataforma (com a janela). */
export interface ParRelacao {
  escola_id: number;
  nome: string;
  valor_oficial: number | null;
  /** Precisão publicada do número oficial, quando o backend a manda. */
  casas_oficial?: number | null;
  edicao: number | null;
  /** Sem número oficial: o porquê (texto do backend). */
  texto_ausencia_oficial?: string | null;
  instavel?: boolean;
  valor_plataforma: number | null;
  janela: string | null;
  ano_plataforma?: number | null;
  incluido: boolean;
  /** O motivo PRÓPRIO da escola (sempre calculado, mesmo quando há um motivo geral). */
  motivo_escola?: string | null;
  /** `motivo_escola` ou "fica de fora pelo motivo geral da relação". */
  motivo_exclusao: string | null;
}

/** IC 95%: o backend manda o objeto {inferior, superior, metodo}; o par também é aceito. */
export type IntervaloConfianca = [number, number] | { inferior: number; superior: number; metodo?: string };

export interface MetricaRelacao {
  chave: string;
  rotulo: string;
  plataforma: string;
  componente?: string | null;
}

/** Endpoint 4 — relação (Spearman) entre um indicador oficial e uma métrica de plataforma. */
export interface RespostaRelacao {
  calculavel: boolean;
  motivos: string[];
  textos: string[];
  criterios: CriteriosRelacao;
  indicador: IndicadorAnalise | null;
  metrica: MetricaRelacao | null;
  /** As métricas que a relação aceita (para o seletor). */
  metricas_disponiveis?: MetricaRelacao[];
  /** Avisos (o de causalidade, o do índice que junta LP e MT…). */
  avisos?: string[];
  janela?: JanelaAnalise | null;
  pares: ParRelacao[];
  n: number;
  coeficiente: number | null;
  ic95: IntervaloConfianca | null;
  /** A leitura do coeficiente em linguagem simples (sem causalidade). */
  interpretacao?: string | null;
  metodologia: string;
}

// --- Escola ---------------------------------------------------------------------------

export interface IndicadorDaEscola {
  chave: string;
  nome: string;
  orgao?: string;
  por_escola?: boolean;
  disponivel?: boolean;
  /** Opcional (o catálogo do endpoint 1 tem a unidade; aqui pode vir junto). */
  unidade?: string | null;
  series: SerieAnalise[];
  /** Quebras de escala (por etapa): a tendência não liga os dois lados. */
  quebras?: { entre: [number, number]; etapa?: string | null; texto: string }[];
  avisos: string[];
}

export interface PlataformasDaEscola {
  janela: JanelaAnalise;
  alunos: number | null;
  suprimido?: boolean;
  motivo_supressao?: string | null;
  texto_supressao?: string | null;
  cobertura?: PorPlataforma<string | null> | null;
  ultima_coleta?: PorPlataforma<string | null> | null;
  coberto_ate?: PorPlataforma<string | null> | null;
  dias_desde_ultima_coleta?: PorPlataforma<number | null> | null;
  /** Os blocos da escola somam só as séries mostradas. */
  blocos_parciais?: boolean;
  texto_blocos?: string | null;
  elefante: MetricasElefante | null;
  matific: MetricasMatific | null;
  series: SeriePlataforma[];
  /** Opcionais (o endpoint da rede os tem; o da escola pode trazê-los). */
  modulos?: { elefante: boolean; matific: boolean };
  k_minimo?: number;
  limitacoes?: string[];
}

/** Endpoint 5 — a análise de UMA escola (coordenador na Visão da Escola, Secretaria e global). */
export interface RespostaAnaliseEscola {
  escola: { id: number; nome: string; codigo_inep: string | null; pendencia: string | null };
  rede: { id: number; nome: string } | null;
  indicadores: IndicadorDaEscola[];
  plataformas: PlataformasDaEscola | null;
  comparacoes_indisponiveis: { tema: string; texto: string }[];
  fontes: Record<string, FonteOficial>;
}
