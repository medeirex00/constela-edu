/**
 * Tipos e textos do SARESP oficial da rede (etapa E5) — o formato é o de
 * `GET /redes/{id}/indicadores/saresp`. Comuns ao cartão (`CartaoSARESP`) e à aba
 * (`AbaSARESP`).
 */
import type { FonteOficial } from "../../components/SeloFonte";
import { numeroBR } from "./ica";

export type FonteSARESP = FonteOficial;
export type Etapa = "2_ano" | "5_ano";
export type Componente = "lp" | "mt";

export interface NivelSARESP {
  /** "a_confirmar" enquanto o corte da edição não for conferido na fonte. */
  situacao: string;
  nivel: string | null;
  distancia_adequado: number | null;
  calculo_do_constela: boolean;
}

export interface NumeroSARESP {
  edicao: number;
  valor: number | null;
  casas_decimais: number | null;
  unidade: string;
  motivo_ausencia: string | null;
  fonte: FonteSARESP | null;
  /** Só nas proficiências. */
  nivel?: NivelSARESP;
}

export interface SerieSARESP {
  etapa: Etapa;
  componente: Componente;
  numeros: NumeroSARESP[];
}

export interface TerritorioSARESP {
  chave: "rede_municipal" | "estado_redes_municipais" | "rede_estadual_no_municipio" | "estado_rede_estadual";
  abrangencia: "municipio" | "uf";
  codigo_territorio: string;
  rede_ensino: "municipal" | "estadual";
  /** A mesma rede da rede municipal? A rede estadual é OUTRA rede (só contexto). */
  mesma_rede: boolean;
  nome: string | null;
  rotulo: string;
  series: SerieSARESP[];
  tem_dados: boolean;
}

export interface EdicaoEscola {
  edicao: number;
  proficiencia: Record<Etapa, Record<Componente, NumeroSARESP | null>>;
  participacao: Record<Etapa, NumeroSARESP | null>;
  tps: NumeroSARESP | null;
  iee: NumeroSARESP | null;
  meta: NumeroSARESP | null;
  icm: NumeroSARESP | null;
  /** Ao menos uma proficiência oficial com número. */
  tem_resultado: boolean;
  /** Há números da escola gravados do arquivo oficial da edição, casados pelo código
   *  INEP ATUAL (mesmo que sejam só ausências). */
  no_arquivo: boolean;
  /** Por que não há resultado oficial nesta edição (chave de `MOTIVOS_SARESP`); nulo
   *  quando há. O mesmo motivo da cobertura. */
  motivo: string | null;
  /** Há estimativa do Constela DESTA edição para a escola. */
  tem_estimativa: boolean;
}

export interface LinhaEscola {
  escola_id: number;
  nome: string;
  codigo_inep: string | null;
  status: string;
  /** "codigo_inep" = escola sem código INEP no cadastro (não casa com os arquivos). */
  pendencia: string | null;
  /** Há estimativa do Constela em QUALQUER edição (a da edição está em `por_edicao`). */
  tem_estimativa: boolean;
  por_edicao: EdicaoEscola[];
}

export interface Estimativa {
  escola_id: number;
  nome: string;
  codigo_inep: string | null;
  edicao: number;
  etapa: Etapa | null;
  componente: string | null;
  valor: number;
  casas_decimais: number | null;
  unidade: string;
  fonte_texto: string | null;
  gravado_em: string | null;
}

export interface EscolaSemResultado {
  escola_id: number;
  nome: string;
  codigo_inep: string | null;
  motivo: string;
  tem_estimativa: boolean;
}

export interface CoberturaEdicao {
  edicao: number;
  total_escolas: number;
  com_resultado: number;
  sem_resultado: EscolaSemResultado[];
  sem_inep: { escola_id: number; nome: string; codigo_inep: string | null }[];
  fora_do_cadastro: { codigo_inep: string | null; cie: string | null; nome_no_arquivo: string | null }[];
  fonte: FonteSARESP | null;
}

export interface CorteSARESP {
  edicao: number;
  etapa: Etapa;
  componente: Componente;
  situacao: string;
  basico: number | null;
  adequado: number | null;
  avancado: number | null;
  fonte: string;
}

export interface QuebraDeEscala {
  etapa: Etapa;
  de: number;
  para: number;
  motivo: string;
}

export interface RespostaSARESP {
  rede_id: number;
  rede_nome: string;
  codigo_ibge: string | null;
  codigo_municipio_estadual: string | null;
  municipio: string | null;
  indicador: { chave: string; nome: string; orgao: string; descricao: string };
  pendencias: string[];
  avisos: Record<string, string>;
  etapas: { chave: Etapa; rotulo: string }[];
  componentes: { chave: Componente; rotulo: string }[];
  edicoes_rede: number[];
  territorios: TerritorioSARESP[];
  quebras_de_escala: QuebraDeEscala[];
  niveis: {
    rotulos: { nivel: string; rotulo: string }[];
    cortes: CorteSARESP[];
    edicoes_a_confirmar: number[];
    aviso: string;
  };
  escolas: { edicoes: number[]; linhas: LinhaEscola[] };
  estimativas: Estimativa[];
  cobertura: CoberturaEdicao[];
  fontes: FonteSARESP[];
  tem_dados: boolean;
}

export const ETAPAS: Etapa[] = ["2_ano", "5_ano"];
export const COMPONENTES: Componente[] = ["lp", "mt"];
export const ROTULO_ETAPA: Record<string, string> = { "2_ano": "2º ano", "5_ano": "5º ano" };
export const ROTULO_COMPONENTE: Record<string, string> = { lp: "Língua Portuguesa", mt: "Matemática" };
export const SIGLA_COMPONENTE: Record<string, string> = { lp: "LP", mt: "MT" };
/** Níveis do SARESP (nomenclatura da SEDUC). Só aparecem com o corte CONFIRMADO. */
export const ROTULO_NIVEL: Record<string, string> = {
  abaixo_do_basico: "Abaixo do Básico", basico: "Básico", adequado: "Adequado", avancado: "Avançado",
};

/** Motivos de "sem resultado" (nunca 0) — os da fonte e os da cobertura. */
export const MOTIVOS_SARESP: Record<string, string> = {
  nao_divulgado: "não divulgado no arquivo oficial",
  participacao_baixa: "sem resultado (participação baixa)",
  fora_do_arquivo: "a escola não está no arquivo oficial importado desta edição",
  sem_importacao: "nenhum arquivo oficial desta edição foi importado",
  sem_codigo_inep: "a escola está sem código INEP no cadastro",
  cadastrado_depois_da_importacao:
    "o código INEP foi cadastrado depois da importação; reimporte o arquivo oficial desta edição",
  codigo_inep_alterado:
    "o código INEP da escola mudou depois da importação; reimporte o arquivo oficial desta edição",
  estimativa_mantida_d2: "oficial não gravado: a estimativa do Constela foi mantida (decisão D2)",
};

/** "123,4" — na precisão publicada (a média do SARESP tem 1 casa). */
export function media(n: { valor: number | null; casas_decimais: number | null } | null | undefined): string {
  if (!n || n.valor == null) return "—";
  return numeroBR(n.valor, n.casas_decimais ?? 1);
}

export function serieDe(t: TerritorioSARESP | undefined, etapa: Etapa, componente: Componente): NumeroSARESP[] {
  return t?.series.find((s) => s.etapa === etapa && s.componente === componente)?.numeros ?? [];
}

/** O texto da ausência: o motivo da fonte, ou "sem resultado" (nunca 0). */
export function textoAusencia(n: { motivo_ausencia: string | null } | null | undefined): string {
  if (!n) return "sem resultado";
  return MOTIVOS_SARESP[n.motivo_ausencia ?? ""] ?? "sem resultado";
}
