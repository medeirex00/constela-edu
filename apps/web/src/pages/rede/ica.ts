/**
 * Tipos e formatação do ICA oficial, comuns ao cartão (`CartaoICA`) e à aba ICA
 * (`AbaICA`) — o formato é o de `GET /redes/{id}/indicadores/ica`.
 */
import type { FonteOficial } from "../../components/SeloFonte";

export type FonteICA = FonteOficial;

export interface NumeroICA {
  edicao: number;
  valor: number | null;
  casas_decimais: number | null;
  /** Só na distribuição por nível ("0" a "8"). */
  nivel?: string | null;
  operador: string | null;
  unidade: string;
  motivo_ausencia: string | null;
  fonte: FonteICA | null;
  detalhe: { valor: number; casas_decimais: number; fonte: FonteICA | null } | null;
}
export interface ComparacaoICA {
  edicao: number;
  resultado: number;
  meta: number;
  operador: string | null;
  diferenca_pp: number;
  casas_decimais: number;
  diferenca_pp_detalhe: number | null;
  casas_decimais_detalhe: number | null;
  situacao: "atingiu" | "nao_atingiu" | "inconclusivo";
}
export interface DistribuicaoNiveis {
  edicao: number;
  niveis: NumeroICA[];
  soma: number | null;
}
export interface TerritorioICA {
  abrangencia: "municipio" | "uf" | "brasil";
  codigo_territorio: string;
  nome: string;
  rede_ensino: string;
  resultados: NumeroICA[];
  metas: NumeroICA[];
  nivel: NumeroICA[];
  participacao: NumeroICA[];
  /** Microdados agregados (E3): média de LP e distribuição por nível 0–8. */
  media_lp?: NumeroICA[];
  distribuicao_niveis?: DistribuicaoNiveis[];
  comparacoes: ComparacaoICA[];
  destaque: { resultado: NumeroICA; meta: NumeroICA | null; comparacao: ComparacaoICA | null } | null;
  tem_dados: boolean;
}
export interface RespostaICA {
  rede_id: number;
  rede_nome: string;
  codigo_ibge: string | null;
  indicador: { chave: string; nome: string; orgao: string; descricao: string };
  aviso_rede: string;
  pendencia: string | null;
  legenda_nivel: { nivel: number; rotulo: string; faixa: string }[];
  /** Pontos na escala do Saeb a partir dos quais o aluno conta como alfabetizado. */
  corte_alfabetizado?: number;
  territorios: TerritorioICA[];
  /** A UF SÓ nas redes municipais (microdados) — a comparação justa com o município. */
  uf_municipal?: TerritorioICA | null;
  fontes: FonteICA[];
  tem_dados: boolean;
}

export const MOTIVOS: Record<string, string> = {
  nao_divulgado: "não divulgado",
  participacao_baixa: "sem resultado (participação abaixo de 70%)",
  sem_meta: "sem meta definida",
};

/** "27,90" — sempre na precisão que a fonte publicou (sem inventar nem perder casas). */
export function numeroBR(valor: number, casas: number | null): string {
  const c = casas ?? 0;
  return valor.toLocaleString("pt-BR", { minimumFractionDigits: c, maximumFractionDigits: c });
}

export function percentual(n: { valor: number | null; casas_decimais: number | null; operador?: string | null }): string {
  if (n.valor == null) return "—";
  const prefixo = n.operador === ">" ? "acima de " : n.operador === ">=" ? "≥ " : "";
  return `${prefixo}${numeroBR(n.valor, n.casas_decimais)}%`;
}

/** "−2 p.p." com o sinal de menos tipográfico; "0 p.p." no empate. */
export function pontosPercentuais(dif: number, casas: number): string {
  const sinal = dif < 0 ? "−" : dif > 0 ? "+" : "";
  return `${sinal}${numeroBR(Math.abs(dif), casas)} p.p.`;
}

/** O nome com a rede: "São Paulo (rede pública)", "São Paulo (redes municipais)". */
export function nomeComRede(t: TerritorioICA): string {
  if (t.abrangencia === "municipio") return `${t.nome} (rede municipal)`;
  return `${t.nome} (${t.rede_ensino === "municipal" ? "redes municipais" : "rede pública"})`;
}
