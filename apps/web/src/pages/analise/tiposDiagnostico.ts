/**
 * Tipos do DIAGNÓSTICO PEDAGÓGICO (exploratório) e da EVOLUÇÃO DAS PLATAFORMAS POR
 * BIMESTRE — o contrato das duas rotas novas, só de leitura (`exigir_rede`):
 *
 *  6. `GET /redes/{rede_id}/analise/diagnostico?periodo&inicio&fim`   → RespostaDiagnostico
 *  7. `GET /redes/{rede_id}/analise/plataformas/evolucao?serie&escola_id&so_escola` → RespostaEvolucao
 *     (com `so_escola`, a ficha: só a escola é medida e `bimestres[].rede` vem nulo)
 *
 * O diagnóstico COMPÕE o que já existe (indicadores oficiais por escola com a rede municipal
 * como referência comparável + as plataformas da janela, com a mesma supressão k da análise):
 * não relê tabela oficial, não grava nada e não traz aluno, nome de criança nem turma.
 *
 * Regras que os tipos carregam (e as telas respeitam):
 *  - SEM RANKING: as escolas chegam em ordem alfabética e a tela mantém (nunca ordena por nível);
 *  - AUSÊNCIA ≠ ZERO: posição, tendência ou métrica nula vêm com o motivo (texto) — a tela
 *    escreve "—" e o motivo, nunca 0;
 *  - NATUREZA: cada sinal diz de onde vem (oficial, calculado pelo Constela, plataforma ou dado/
 *    cadastro) — a tela põe o selo em cada um;
 *  - HIPÓTESE: categoria e nível são leituras EXPLORATÓRIAS calculadas pelo Constela (anos e
 *    coortes diferentes) — associação, nunca causa.
 *
 * Onde o desenho deixa a forma em aberto (a leitura do eixo como texto ou como objeto, o motivo
 * da posição de plataforma, as pendências como código ou como texto, as contagens de escolas
 * como número ou por plataforma), o tipo aceita as duas e `formato.ts` normaliza. Os campos
 * opcionais a mais (casas da diferença, motivo da tendência, cobertura por plataforma…) são os
 * que o serviço do backend (`services/analise/diagnostico.py`, `evolucao.py`) também manda.
 */
import type { FonteOficial } from "../../components/SeloFonte";
import type { JanelaAnalise, SituacaoMeta } from "./tipos";

export type PosicaoRede = "acima" | "abaixo" | "na_media";
export type Tendencia = "subiu" | "caiu" | "estavel";
export type EixoSinal = "avaliacao" | "plataforma" | "dados";
export type ComponenteSinal = "lp" | "mt" | "geral";
/** oficial = número/meta do órgão; calculado = conta do Constela (posição, tendência);
 *  plataforma = Elefante/Matific; dados = cadastro, cobertura, proteção (informativo). */
export type NaturezaSinal = "oficial" | "calculado" | "plataforma" | "dados";
export type DirecaoSinal = "atencao" | "favoravel" | "informativo";
export type EstadoEixo = "favoravel" | "atencao" | "misto" | "sem_dado";
export type CategoriaLeitura =
  | "convergente_favoravel" | "convergente_atencao" | "divergente_uso_alto" | "divergente_uso_baixo"
  | "inconclusiva";
export type NivelAcompanhamento = "prioritario" | "acompanhar" | "oportunidade" | "dados_insuficientes" | "sem_sinal";
export type Comparabilidade = "exploratoria" | "mesmo_ano";

/** Por plataforma — o mesmo formato do endpoint das plataformas. */
export type PorPlataformaDiag<T> = Partial<Record<"elefante" | "matific", T>>;

/** A ÚLTIMA edição com número OFICIAL da escola numa série (indicador × etapa × componente). */
export interface OficialDiagnostico {
  indicador: string;
  /** "SARESP 2025 · 5º ano · LP" ou parecido — o nome da série como o backend escreve. */
  rotulo: string;
  etapa: string | null;
  componente: string | null;
  edicao: number;
  valor: number;
  casas: number | null;
  meta: number | null;
  meta_casas?: number | null;
  situacao_meta: SituacaoMeta | null;
  /** TPS = 0: a média é instável (nunca gera sinal de posição nem de tendência). */
  instavel: boolean;
  /** IEE calculado com médias de TPS = 0. */
  tps_zero?: boolean;
  fonte_id: number | null;
  /** "SARESP 2025 · 5º ano · LP" — o caminho até o número. */
  referencia?: string | null;
  /** A rede municipal na MESMA edição — só quando comparável. */
  valor_rede: number | null;
  casas_rede?: number | null;
  fonte_rede_id?: number | null;
  /** Escola − rede, já arredondada às casas publicadas. */
  diferenca_rede: number | null;
  /** A precisão da diferença (a menor dos dois lados). */
  casas_diferenca?: number | null;
  /** Calculado pelo Constela com a tolerância do critério (diferença menor = "na média"). */
  posicao_rede: PosicaoRede | null;
  /** Por que não há posição (sem rede comparável, instável, IEE sem número da rede…). */
  motivo_sem_comparacao: string | null;
  /** A edição oficial anterior da MESMA série (null se houver quebra de escala entre as duas). */
  anterior: { edicao: number; valor: number; casas?: number | null; instavel?: boolean } | null;
  tendencia: Tendencia | null;
  diferenca_anterior?: number | null;
  /** Por que não há tendência (primeira edição, quebra de escala, média instável…). */
  motivo_sem_tendencia?: string | null;
}

interface PlataformaDiagBase {
  participacao_pct: number | null;
  /** Célula protegida (poucos alunos, k): sem número nenhum. */
  suprimido: boolean;
  texto_supressao?: string | null;
  /** A situação da coleta DESTA plataforma (ok, coleta_parcial…) e até quando vale. */
  cobertura?: string | null;
  coleta_parcial?: boolean;
  coberto_ate?: string | null;
  motivo_sem_dado?: string | null;
  /** Médias escondidas em complemento (o total revelaria um grupo pequeno). */
  metricas_protegidas?: string[];
  diferenca_participacao?: number | null;
  diferenca_intensidade_pct?: number | null;
  /** Contra o valor da REDE na mesma janela (null com o motivo: cobertura parcial, < 3 escolas…). */
  posicao_participacao: PosicaoRede | null;
  posicao_intensidade: PosicaoRede | null;
  /** O motivo de a posição faltar (um texto para as duas, ou um por posição). */
  motivo_sem_comparacao?: string | null;
  motivo_posicao_participacao?: string | null;
  motivo_posicao_intensidade?: string | null;
  texto_sem_dado?: string | null;
}

export interface ElefanteDiagnostico extends PlataformaDiagBase {
  livros_por_aluno: number | null;
  minutos_por_aluno: number | null;
  taxa_acerto_pct: number | null;
}

export interface MatificDiagnostico extends PlataformaDiagBase {
  atividades_por_aluno: number | null;
  desempenho_medio: number | null;
}

export interface PlataformasDiagnostico {
  /** A escola inteira protegida (poucos alunos): nem a cobertura nem as datas. */
  suprimido?: boolean;
  motivo_supressao?: string | null;
  texto_supressao?: string | null;
  /** A situação da coleta (ok, coleta_parcial, sem_coleta…) por plataforma. */
  cobertura: PorPlataformaDiag<string | null> | string | null;
  ultima_coleta: PorPlataformaDiag<string | null> | string | null;
  /** null = módulo não contratado. */
  elefante: ElefanteDiagnostico | null;
  matific: MatificDiagnostico | null;
}

export interface SinalDiagnostico {
  codigo: string;
  eixo: EixoSinal;
  componente: ComponenteSinal;
  natureza: NaturezaSinal;
  direcao: DirecaoSinal;
  /** pt-BR, com ano/período e os valores. */
  texto: string;
  /** "IEE 2025", "SARESP 2025 · 5º ano · LP", "Elefante · 01/02/2026–31/10/2026"… */
  referencia: string;
}

/** O estado de um eixo (o desenho aceita o texto puro ou o objeto com a base). */
export type EixoLeitura = EstadoEixo | { estado: EstadoEixo; base?: "geral" | "componente" | null };

export interface LeituraComponente {
  avaliacao: EixoLeitura;
  /** "geral": sem sinal de avaliação do componente, a leitura usou IEE/Ideb. */
  base?: "geral" | "componente" | null;
  plataforma: EixoLeitura;
  categoria: CategoriaLeitura;
  /** Por que é inconclusiva (misto, sem dado…). */
  motivo?: string | null;
  texto: string;
  anos: { avaliacao: number | null; plataforma: number | null };
  /** null = falta um dos lados (sem ano para comparar). */
  comparabilidade: Comparabilidade | null;
  /** A comparabilidade por extenso (o texto do backend). */
  texto_comparabilidade?: string | null;
  /** As referências dos sinais que decidiram a leitura. */
  referencias?: string[];
}

/** Pendência de cadastro/dado da escola: o código ("sem_codigo_inep") ou já o texto. */
export type PendenciaDiagnostico = string | { codigo?: string | null; texto?: string | null };

export interface EscolaDiagnostico {
  id: number;
  nome: string;
  codigo_inep: string | null;
  status?: string | null;
  pendencias: PendenciaDiagnostico[];
  oficiais: OficialDiagnostico[];
  plataformas: PlataformasDiagnostico | null;
  sinais: SinalDiagnostico[];
  leituras: { lp: LeituraComponente; mt: LeituraComponente };
  acompanhamento: { nivel: NivelAcompanhamento; motivos: string[] };
}

export interface ReferenciaRede {
  indicador: string;
  etapa: string | null;
  componente: string | null;
  edicao: number;
  valor: number;
  casas: number | null;
  fonte_id: number | null;
}

/** Endpoint 6 — o diagnóstico exploratório da rede (todas as escolas, ordem alfabética). */
export interface RespostaDiagnostico {
  rede: { id: number; nome: string };
  janela: JanelaAnalise;
  gerado_em: string;
  k_minimo?: number;
  modulos?: { elefante: boolean; matific: boolean };
  criterios: {
    /** "Na média" = diferença menor que a tolerância (participação 5 p.p.; intensidade 15%…). */
    tolerancias: Record<string, number | string>;
    n_minimo_escolas_comparacao: number;
    regras: string[];
  };
  referencias_rede: ReferenciaRede[];
  escolas: EscolaDiagnostico[];
  resumo: {
    por_nivel: Partial<Record<NivelAcompanhamento, number>>;
    por_categoria: { lp: Partial<Record<CategoriaLeitura, number>>; mt: Partial<Record<CategoriaLeitura, number>> };
    escolas_total: number;
    escolas_com_oficial: number;
    escolas_com_plataforma: number;
    anos: { avaliacao_mais_recente: number | null; plataforma: number | null };
  };
  limitacoes: string[];
  metodologia: string[];
  fontes: Record<string, FonteOficial>;
}

// --- Evolução das plataformas por bimestre -----------------------------------------------

/** Quantas escolas: um número só, ou um por plataforma. */
export type ContagemEscolas = number | PorPlataformaDiag<number> | null;

/** Sem número: o porquê do serviço (ausência ≠ zero); a média escondida em complemento. */
export interface MotivoNoBimestre {
  motivo_sem_dado?: string | null;
  texto_sem_dado?: string | null;
  /** Coleta parada antes do fim do bimestre: o número VEM, mas vale só até a parada. */
  coleta_parcial?: boolean;
  /** Até quando a coleta parcial vale (opcional: o serviço da evolução ainda não repassa). */
  coberto_ate?: string | null;
  metricas_protegidas?: string[];
}

export interface RedeNoBimestre {
  /** null = módulo não contratado. */
  elefante: ({ participacao_pct: number | null; livros_por_aluno: number | null; minutos_por_aluno: number | null }
    & MotivoNoBimestre) | null;
  matific: ({ participacao_pct: number | null; atividades_por_aluno: number | null } & MotivoNoBimestre) | null;
  escolas_com_dado: ContagemEscolas;
  /** Escolas com a coleta parada antes do fim do bimestre. */
  escolas_parciais: ContagemEscolas;
  suprimido?: boolean;
}

export interface EscolaNoBimestre {
  id: number;
  nome: string;
  cobertura: PorPlataformaDiag<string | null> | string | null;
  /** Escola com poucos alunos: nenhum número (protegido). */
  suprimido?: boolean;
  elefante: ({ participacao_pct: number | null; livros_por_aluno: number | null } & MotivoNoBimestre) | null;
  matific: ({ participacao_pct: number | null; atividades_por_aluno: number | null } & MotivoNoBimestre) | null;
}

export interface BimestreEvolucao {
  numero: number;
  rotulo: string;
  inicio: string;
  fim: string;
  /** O bimestre de hoje: ainda não terminou (os números crescem até o fim). */
  em_andamento: boolean;
  /** Nulo com `so_escola` (a ficha da escola): só a escola foi medida, a rede não. */
  rede: RedeNoBimestre | null;
  escolas: EscolaNoBimestre[];
}

/** Endpoint 7 — cada bimestre do ano letivo que já começou (valores já protegidos). */
export interface RespostaEvolucao {
  ano_letivo: number;
  k_minimo: number;
  modulos?: { elefante: boolean; matific: boolean };
  /** O ano tem o calendário oficial de bimestres cadastrado (senão, o aviso vem nas limitações). */
  calendario_oficial?: boolean;
  filtros?: { serie: number | null; escola_id: number | null; so_escola?: boolean };
  bimestres: BimestreEvolucao[];
  limitacoes: string[];
}
