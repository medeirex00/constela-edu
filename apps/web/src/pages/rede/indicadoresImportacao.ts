/**
 * Tipos e rótulos da importação dos indicadores oficiais que NÃO são o ICA — o fluxo de
 * famílias do backend (`services/indicadores/pipeline_seduc`: `_saida`, `listar`):
 *
 *  - SARESP/IEE da SEDUC-SP → `/redes/{id}/indicadores/saresp/...`
 *  - Ideb do INEP (pacote do `preparar`) → `/redes/{id}/indicadores/ideb/...`
 *  - Saeb do INEP (pacote do `preparar`) → `/redes/{id}/indicadores/saeb/...`
 *
 * Cada família tem `previa`, `aplicar`, `importacoes` e `importacoes/{id}/desfazer`, só
 * do admin global. O ICA tem a sua tela e os seus tipos (`ImportarICA`).
 */
import { MOTIVOS_SARESP, ROTULO_ETAPA } from "./saresp";

export type FamiliaImportacao = "saresp" | "ideb" | "saeb";

/** Os contadores que a API devolve (`pipeline_seduc._contadores` + os da aplicação e do
 *  desfazer). Uma chave ausente não é zero: a tela só mostra o que veio. */
export interface ContadoresImportacao {
  lidas?: number;
  recortadas?: number;
  novas?: number;
  alteradas?: number;
  iguais?: number;
  mantidas?: number;
  substituicoes?: number;
  ausentes?: number;
  escolas_casadas?: number;
  fora_do_cadastro?: number;
  territorios?: number;
  /** Número por escola sem registro oficial IGUAL ao oficial (Ideb): fica como está. */
  iguais_sem_proveniencia?: number;
  /** Só depois de aplicar. */
  substituicoes_aplicadas?: number;
  substituicoes_mantidas?: number;
  /** Só depois de desfazer. */
  desfeitas?: number;
  [chave: string]: number | undefined;
}

/** Um número que muda (os iguais não vêm). `antes`/`depois` nulos = sem número. */
export interface MudancaImportacao {
  alvo: "escola" | "referencia";
  tipo: "nova" | "alterada" | "mantida" | "substituicao";
  avaliacao: string;
  onde: string | null;
  abrangencia: string;
  rede_ensino: string | null;
  codigo_inep: string | null;
  indicador: string;
  edicao: number;
  etapa: string | null;
  componente: string | null;
  localizacao: string | null;
  nivel: string | null;
  antes: number | null;
  antes_motivo: string | null;
  antes_fonte: string | null;
  depois: number | null;
  depois_motivo: string | null;
}

/** O ANTES (número por escola gravado sem registro oficial — no SARESP, a média
 *  calculada pelo Constela) × DEPOIS (o oficial) que a pergunta da D2 decide. */
export interface SubstituicaoD2 {
  escola_id: number;
  escola: string | null;
  codigo_inep: string | null;
  edicao: number;
  etapa: string | null;
  componente: string | null;
  antes: { valor: number | null; fonte: string | null; motivo_ausencia: string | null };
  depois: { valor: number | null; motivo_ausencia: string | null; fonte: string | null };
  diferenca: number | null;
}

export interface EscolaForaDoCadastro {
  codigo_inep: string;
  nome_no_arquivo?: string | null;
  cie?: string | null;
  municipio?: string | null;
}

export interface EscolaSemLinha {
  escola_id: number;
  escola: string | null;
  codigo_inep: string;
}

export interface ImportacaoOficial {
  id: number;
  status: "previa" | "aplicada" | "desfeita";
  parser: string;
  modo: string | null;
  arquivo_nome: string;
  arquivo_sha256?: string | null;
  edicao_arquivo: number;
  versao_rotulo?: string | null;
  url_origem?: string | null;
  last_modified_origem?: string | null;
  codigo_territorio_alvo?: string | null;
  fonte_nome?: string | null;
  citacao?: string | null;
  licenca?: string | null;
  contadores: ContadoresImportacao;
  avisos: string[];
  territorios?: Record<string, string>;
  escolas_casadas?: unknown[];
  fora_do_cadastro?: EscolaForaDoCadastro[];
  colunas_ignoradas?: string[];
  encoding?: string | null;
  pacote_sha256?: string | null;
  arquivo_data: string | null;
  created_at: string | null;
  aplicado_em: string | null;
  desfeito_em?: string | null;
  // Só de uma família (Ideb e Saeb): edições do arquivo, cobertura, escolas sem linha...
  edicoes?: number[];
  anos_meta?: number[];
  cobertura?: Record<string, { ideb: number; saeb: number }>;
  sem_linha_no_arquivo?: EscolaSemLinha[];
  // Só na prévia e na aplicação.
  mudancas?: MudancaImportacao[];
  substituicoes?: SubstituicaoD2[];
  // Só na lista.
  pode_desfazer?: boolean;
  /** Id da importação posterior que usa os mesmos números (desfazer antes ela). */
  bloqueada_por?: number | null;
}

/** Uma linha de `GET /redes` (o admin global vê todas as redes ativas). */
export interface RedeResumo {
  id: number;
  nome: string;
  uf?: string | null;
  codigo_ibge?: string | null;
  /** CODMUN da SEDUC-SP (SARESP por município) — NÃO é o código do IBGE. */
  codigo_municipio_estadual?: string | null;
}

export const ROTULO_PARSER: Record<string, string> = {
  seduc_iee: "IEE (SEDUC-SP)",
  seduc_saresp_municipio: "SARESP por município (SEDUC-SP)",
  seduc_saresp_instancia: "SARESP por instância (SEDUC-SP)",
  inep_ideb_escolas: "Ideb por escola (INEP)",
  inep_ideb_municipios: "Ideb do município (INEP)",
  inep_ideb_uf_brasil: "Ideb da UF e do Brasil (INEP)",
  inep_saeb_planilha: "Saeb — planilha de resultados (INEP)",
};

export const ROTULO_STATUS: Record<string, string> = {
  previa: "prévia (nada gravado)",
  aplicada: "aplicada",
  desfeita: "desfeita",
};

export const ROTULO_TIPO: Record<string, string> = {
  nova: "novo",
  alterada: "alterado",
  mantida: "mantido (já vale um arquivo mais novo)",
  substituicao: "troca de número sem registro oficial",
};

const ROTULO_INDICADOR: Record<string, string> = {
  proficiencia: "proficiência",
  participacao: "participação",
  tps: "critério de participação (TPS)",
  iee: "nota do IEE",
  meta: "meta",
  icm: "cumprimento da meta (ICM)",
  ideb: "Ideb",
  nota_n: "nota padronizada (N)",
  rendimento_p: "rendimento (P)",
  aprovacao: "aprovação",
  nota_saeb: "nota do Saeb",
  pct_nivel: "% no nível",
  tx_alfabetizado: "taxa de alfabetização do Saeb (não é o ICA)",
};
const ROTULO_COMPONENTE: Record<string, string> = { lp: "LP", portugues: "LP", mt: "MT", matematica: "MT" };
/** As etapas que as prévias trazem — inclusive a aprovação por série do Ideb (1º ao 4º ano). */
const ROTULO_ETAPA_IMPORTACAO: Record<string, string> = {
  ...ROTULO_ETAPA, "1_ano": "1º ano", "3_ano": "3º ano", "4_ano": "4º ano", anos_iniciais: "anos iniciais",
};
/** `rede_ensino` da API (Ideb e Saeb gravam também a pública e o total). */
const ROTULO_REDE_IMPORTACAO: Record<string, string> = {
  municipal: "rede municipal", estadual: "rede estadual", publica: "rede pública",
  total: "todas as redes (públicas e privadas)",
};
/** `localizacao` da API: o Saeb grava total, urbana e rural SEPARADAS. */
const ROTULO_LOCALIZACAO: Record<string, string> = {
  total: "área total (urbana e rural)", urbana: "só área urbana", rural: "só área rural",
};

/** A prévia traz números separados por localização (o Saeb: total, urbana e rural)?
 *  Então cada rótulo precisa dizer qual é — sem isso, as três linhas sairiam iguais. */
export function separaLocalizacao(mudancas: readonly Pick<MudancaImportacao, "localizacao">[]): boolean {
  return mudancas.some((m) => m.localizacao != null && m.localizacao !== "total");
}

/** Motivo de um número ausente — nunca zero. */
export const MOTIVOS_IMPORTACAO: Record<string, string> = {
  ...MOTIVOS_SARESP,
  sem_meta: "sem meta definida",
  sem_resultado: "sem resultado nesta edição",
};

/** "proficiência 5º ano LP 2025" — o nome legível de um número da prévia. Com
 *  `localizacao` (a prévia separa por localização: `separaLocalizacao`), diz também
 *  se é a área total, a urbana ou a rural. */
export function rotuloNumero(m: Pick<MudancaImportacao, "indicador" | "etapa" | "componente" | "nivel" | "edicao">
  & Partial<Pick<MudancaImportacao, "rede_ensino" | "localizacao">>,
  opcoes: { localizacao?: boolean } = {}): string {
  const partes = [ROTULO_INDICADOR[m.indicador] ?? m.indicador];
  if (m.nivel) partes.push(m.nivel);
  if (m.etapa) partes.push(ROTULO_ETAPA_IMPORTACAO[m.etapa] ?? m.etapa);
  if (m.componente) partes.push(ROTULO_COMPONENTE[m.componente] ?? m.componente);
  if (m.rede_ensino) partes.push(ROTULO_REDE_IMPORTACAO[m.rede_ensino] ?? `rede ${m.rede_ensino}`);
  if (opcoes.localizacao && m.localizacao) partes.push(ROTULO_LOCALIZACAO[m.localizacao] ?? m.localizacao);
  partes.push(String(m.edicao));
  return partes.join(" ");
}

/** Um número da prévia: o valor em pt-BR ou "sem resultado (motivo)" — ausência não é 0. */
export function valorImportacao(valor: number | null, motivo: string | null): string {
  if (valor == null) return motivo ? `sem resultado (${MOTIVOS_IMPORTACAO[motivo] ?? motivo})` : "—";
  return valor.toLocaleString("pt-BR", { maximumFractionDigits: 4 });
}

/** "09/03/2031" — o dia da data interna do arquivo, quando ele traz. */
export function diaDoArquivoInterno(iso: string | null | undefined): string | null {
  const [a, m, d] = (iso ?? "").slice(0, 10).split("-");
  return a && m && d ? `${d}/${m}/${a}` : null;
}
