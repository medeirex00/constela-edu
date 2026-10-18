/**
 * Tipos e textos do IDEB e do SAEB oficiais por escola (etapa E8a) e da rede municipal
 * (etapa E8b) — o formato é o de `GET /redes/{id}/indicadores/ideb`. Comuns ao cartão
 * (`CartaoIDEB`), à aba (`AbaIDEB`) e à parte da rede (`RedeIDEB`).
 */
import type { FonteOficial } from "../../components/SeloFonte";
import { numeroBR } from "./ica";
import { MOTIVOS_SARESP } from "./saresp";

export type FonteIDEB = FonteOficial;

/** Um número da escola. `fonte_id` aponta para `fontes` (arquivo, edição e data). */
export interface NumeroIDEB {
  valor: number | null;
  casas_decimais: number | null;
  motivo_ausencia: string | null;
  /** "oficial" = da importação com prévia; "sem_registro" = gravado antes pelo 1 clique. */
  proveniencia: "oficial" | "sem_registro";
  fonte_id: number | null;
  /** Só nos números "sem_registro". */
  fonte_texto?: string | null;
  gravado_em?: string | null;
  difere_do_oficial?: boolean;
  recusado_na_importacao?: number | null;
}

export interface ComparacaoMeta {
  observado: number;
  meta: number;
  diferenca: number;
  casas_decimais: number;
  /** Ideb ≥ meta na precisão publicada = "atingiu" (o empate incluído, como lê o INEP). */
  situacao: "atingiu" | "nao_atingiu";
}

export type EtapaAprovacao = "anos_iniciais" | "1_ano" | "2_ano" | "3_ano" | "4_ano" | "5_ano";

export interface EdicaoIDEB {
  edicao: number;
  ideb: NumeroIDEB | null;
  saeb_lp: NumeroIDEB | null;
  saeb_mt: NumeroIDEB | null;
  nota_n: NumeroIDEB | null;
  rendimento_p: NumeroIDEB | null;
  aprovacao: Record<EtapaAprovacao, NumeroIDEB | null>;
  meta: NumeroIDEB | null;
  /** Por que não há meta: "depois_do_1o_ciclo" | "antes_das_metas" | "sem_arquivo_oficial". */
  sem_meta: string | null;
  comparacao_meta: ComparacaoMeta | null;
  variacao_ideb: { desde: number; diferenca: number; casas_decimais: number } | null;
  no_arquivo: boolean;
  tem_ideb: boolean;
  tem_saeb: boolean;
  /** Por que não há Ideb (chave de `MOTIVOS_IDEB`); nulo quando há. */
  motivo: string | null;
}

export interface EscolaIDEB {
  escola_id: number;
  nome: string;
  codigo_inep: string | null;
  status: string;
  pendencia: string | null;
  serie: EdicaoIDEB[];
  tem_sem_registro: boolean;
}

export interface EscolaRef {
  escola_id: number;
  nome: string;
  codigo_inep: string | null;
}

export interface CoberturaIDEB {
  edicao: number;
  total_escolas: number;
  com_ideb: number;
  com_saeb: number;
  sem_resultado: (EscolaRef & { motivo: string })[];
  sem_linha_no_arquivo: EscolaRef[];
  sem_inep: EscolaRef[];
  fora_do_cadastro: { codigo_inep: string | null; nome_no_arquivo: string | null }[];
  arquivo_importado: boolean;
  fonte_id: number | null;
}

// --- Rede municipal, UF e Brasil (E8b) ------------------------------------------

/** Uma edição do Ideb do território (arquivo do Ideb por município ou de UF/Brasil). */
export interface EdicaoIdebRede {
  edicao: number;
  ideb: NumeroIDEB | null;
  meta: NumeroIDEB | null;
  sem_meta: string | null;
  comparacao_meta: ComparacaoMeta | null;
  /** A nota do Saeb que entra no Ideb — universo do INEP (escolas urbanas). Nunca é a
   *  média da planilha do Saeb. */
  nota_saeb: { lp: NumeroIDEB | null; mt: NumeroIDEB | null };
  nota_n: NumeroIDEB | null;
  rendimento_p: NumeroIDEB | null;
  /** Aprovação do 1º ao 5º ano. */
  aprovacao: NumeroIDEB | null;
}

export interface TerritorioIdeb {
  chave: "rede_municipal" | "uf_redes_municipais" | "uf_rede_publica" | "brasil_redes_municipais";
  abrangencia: "municipio" | "uf" | "brasil";
  codigo_territorio: string;
  rede_ensino: string;
  /** Mesma rede da comparação (municipal)? A UF na rede pública é OUTRA rede: contexto. */
  mesma_rede: boolean;
  contexto: boolean;
  posicao: number;
  nome: string;
  rotulo: string;
  rotulo_contexto: string | null;
  motivo_contexto: string | null;
  universo_saeb: { chave: string; rotulo: string; indicadores: string[] };
  serie: EdicaoIdebRede[];
  anos_meta: number[];
  tem_dados: boolean;
}

export interface NivelSaeb extends NumeroIDEB {
  nivel: number;
  /** Faixa na escala do Saeb do 5º ano (`null` = aberta). */
  inicio: number | null;
  fim: number | null;
}

export interface DistribuicaoSaeb {
  niveis: NivelSaeb[];
  /** Soma dos percentuais só quando todos os níveis têm número (ausência ≠ 0). */
  soma: number | null;
}

export interface EdicaoSaebRede {
  edicao: number;
  media: { lp: NumeroIDEB | null; mt: NumeroIDEB | null };
  niveis: { lp: DistribuicaoSaeb; mt: DistribuicaoSaeb };
}

export interface TerritorioSaeb {
  chave: "rede_municipal" | "uf_redes_municipais" | "brasil_redes_municipais";
  abrangencia: "municipio" | "uf" | "brasil";
  codigo_territorio: string;
  rede_ensino: string;
  localizacao: string;
  mesma_rede: boolean;
  posicao: number;
  nome: string;
  rotulo: string;
  edicoes: EdicaoSaebRede[];
  tem_dados: boolean;
}

export interface FaixaNivel { nivel: number; inicio: number | null; fim: number | null }

export interface ReguaSaeb {
  lp: FaixaNivel[];
  mt: FaixaNivel[];
  /** De onde vêm os cortes (o Dicionário da planilha do Saeb 2025). */
  fonte: string;
  edicoes_com_cortes_no_arquivo: number[];
  texto_outras_edicoes: string;
  unidade: string;
}

export interface RedeMunicipalIDEB {
  ideb: {
    territorios: TerritorioIdeb[];
    edicoes: number[];
    anos_meta: number[];
    uf_sem_rede_municipal: boolean;
    texto_uf_sem_rede_municipal: string | null;
    tem_dados: boolean;
  };
  saeb: {
    territorios: TerritorioSaeb[];
    edicoes: number[];
    localizacao: string;
    rotulo_localizacao: string;
    regua: ReguaSaeb;
    /** As edições da planilha do 5º ano importadas para ESTA rede (a UF e o Brasil podem ter
     *  vindo da planilha de outra rede — são referência pública, pelo código). */
    edicoes_importadas_rede: number[];
    tem_dados: boolean;
  };
  avisos: Record<string, string>;
  /** Há número DA REDE MUNICIPAL (o Ideb ou o Saeb do município). A UF e o Brasil sozinhos não
   *  contam — esses estão no `tem_dados` do Ideb e do Saeb. */
  tem_dados: boolean;
}

export interface EdicaoAmostral {
  edicao: number;
  media: { lp: NumeroIDEB | null; mt: NumeroIDEB | null };
  /** Taxa de alfabetização do Saeb (2021) — NÃO é o ICA. */
  tx_alfabetizado: NumeroIDEB | null;
}

export interface TerritorioAmostral {
  chave: string;
  abrangencia: "uf" | "brasil";
  codigo_territorio: string;
  rede_ensino: string;
  localizacao: string;
  desenho: "amostral";
  posicao: number;
  nome: string;
  rotulo: string;
  edicoes: EdicaoAmostral[];
  tem_dados: boolean;
}

export interface ContextoAmostral {
  territorios: TerritorioAmostral[];
  edicoes: number[];
  desenho: "amostral";
  etapa: string;
  unidade_media: string;
  aviso: string;
  nao_e_ica: string;
  tem_dados: boolean;
}

/** O que ainda falta: o que a base não importou (pelo nome do arquivo) ou está adiado. */
export interface PendenteIDEB {
  chave: string;
  edicao: number | null;
  situacao: "sem_importacao" | "adiado";
  arquivo: string;
  texto: string;
}

export interface RespostaIDEB {
  rede_id: number;
  rede_nome: string;
  codigo_ibge: string | null;
  municipio: string | null;
  indicadores: Record<string, { chave: string; nome: string; orgao: string; descricao: string }>;
  pendencias: string[];
  avisos: Record<string, string>;
  campos: Record<string, { rotulo: string; unidade: string; casas_publicadas?: number }>;
  edicoes: number[];
  anos_meta: number[];
  escolas: EscolaIDEB[];
  cobertura: CoberturaIDEB[];
  sem_registro_oficial: { total: number; por_edicao: Record<string, number>; difere_do_oficial: number };
  participacao: { disponivel: boolean; decisao: string; texto: string };
  rede_municipal: RedeMunicipalIDEB;
  contexto_amostral: ContextoAmostral;
  pendentes: PendenteIDEB[];
  fontes: FonteIDEB[];
  /** Há número de alguma escola (a parte "Por escola"). */
  tem_dados_escolas: boolean;
  tem_dados: boolean;
}

/** Motivos de "sem resultado" (nunca 0): os do SARESP, com o "não divulgado" do INEP. */
export const MOTIVOS_IDEB: Record<string, string> = {
  ...MOTIVOS_SARESP,
  nao_divulgado: "não divulgado",
  fora_do_arquivo: "a escola não tem linha no arquivo oficial importado",
  sem_importacao: "nenhum arquivo oficial do Ideb foi importado",
  sem_resultado: "sem resultado nesta edição",
};

/** Por que a edição não tem meta para comparar. */
export function textoSemMeta(edicao: number, motivo: string | null, anosMeta: number[]): string | null {
  if (motivo === "depois_do_1o_ciclo") return `o INEP não definiu meta do Ideb para ${edicao}`;
  if (motivo === "antes_das_metas") {
    return `sem meta em ${edicao} (as metas começam em ${anosMeta.length ? Math.min(...anosMeta) : 2007})`;
  }
  if (motivo === "sem_arquivo_oficial") return "metas só com o arquivo oficial importado";
  if (motivo === "sem_meta_no_arquivo") return "o arquivo do INEP não traz meta do Ideb para esta rede";
  return null;
}

/** "2019–2023"; com uma edição só, só o ano ("2023", não "2023–2023"). */
export function periodoIDEB(edicoes: (number | string)[]): string {
  if (edicoes.length === 0) return "";
  return edicoes.length === 1 ? String(edicoes[0]) : `${edicoes[0]}–${edicoes[edicoes.length - 1]}`;
}

/** O número na precisão publicada ("1,5"; "131,47"); sem número, "—". */
export function valorIDEB(n: Pick<NumeroIDEB, "valor" | "casas_decimais"> | null | undefined, casas = 1): string {
  if (!n || n.valor == null) return "—";
  return numeroBR(n.valor, n.casas_decimais ?? casas);
}

/** "+0,3" / "−0,8" / "0,0" (sinal de menos tipográfico). */
export function diferencaIDEB(dif: number, casas: number): string {
  const sinal = dif < 0 ? "−" : dif > 0 ? "+" : "";
  return `${sinal}${numeroBR(Math.abs(dif), casas)}`;
}

/** O texto da ausência de UM número: o motivo da fonte ("não divulgado"), nunca 0. */
export function textoAusenciaIDEB(n: NumeroIDEB | null | undefined, padrao = "sem resultado"): string {
  if (!n) return padrao;
  return MOTIVOS_IDEB[n.motivo_ausencia ?? ""] ?? padrao;
}

export function fonteDe(dados: RespostaIDEB, id: number | null | undefined): FonteIDEB | null {
  if (id == null) return null;
  return dados.fontes.find((f) => f.importacao_id === id) ?? null;
}

/** As fontes (sem repetição) dos números dados. */
export function fontesDosNumeros(dados: RespostaIDEB, numeros: (NumeroIDEB | null | undefined)[]): FonteIDEB[] {
  const ids = new Set(numeros.flatMap((n) => (n?.fonte_id != null ? [n.fonte_id] : [])));
  return dados.fontes.filter((f) => ids.has(f.importacao_id));
}

/** Todos os números de uma edição de uma escola (para o selo da tabela). */
export function numerosDaEdicao(ed: EdicaoIDEB | undefined): (NumeroIDEB | null)[] {
  if (!ed) return [];
  return [ed.ideb, ed.saeb_lp, ed.saeb_mt, ed.nota_n, ed.rendimento_p, ed.meta, ...Object.values(ed.aprovacao)];
}

export function edicaoDe(escola: EscolaIDEB, edicao: number): EdicaoIDEB | undefined {
  return escola.serie.find((e) => e.edicao === edicao);
}

/** Faixa do eixo Y do Ideb (0–10) com amplitude PAR: o `GraficoLinha` rotula a linha do
 *  meio arredondando para inteiro — com amplitude ímpar ela cairia num "x,5" rotulado
 *  "x+1" (faixa 4–7: a linha de 5,5 dizia "6"). */
export function faixaIdeb(valores: number[]): { minimo: number; maximo: number } {
  if (valores.length === 0) return { minimo: 0, maximo: 10 };
  let minimo = Math.max(0, Math.floor(Math.min(...valores) - 0.5));
  let maximo = Math.min(10, Math.ceil(Math.max(...valores) + 0.5));
  if ((maximo - minimo) % 2 !== 0) {
    if (maximo < 10) maximo += 1;
    else minimo -= 1;                       // máximo 10 e amplitude ímpar: mínimo ≥ 1
  }
  return { minimo, maximo };
}

/** Todos os números de um território do Ideb (para o selo do bloco). */
export function numerosDoTerritorio(t: TerritorioIdeb): (NumeroIDEB | null)[] {
  return t.serie.flatMap((e) => [e.ideb, e.meta, e.nota_saeb.lp, e.nota_saeb.mt, e.nota_n, e.rendimento_p,
                                 e.aprovacao]);
}

/** "125 a 150"; "abaixo de 125"; "325 ou mais" — a faixa do nível na escala do Saeb. */
export function textoFaixa(f: Pick<FaixaNivel, "inicio" | "fim">): string {
  if (f.inicio == null && f.fim != null) return `abaixo de ${f.fim}`;
  if (f.inicio != null && f.fim == null) return `${f.inicio} ou mais`;
  if (f.inicio != null && f.fim != null) return `${f.inicio} a menos de ${f.fim}`;
  return "—";
}

/** Ordem por NOME (sem acento e sem caixa) — sem ranking. A tela não depende da API. */
export function porNome<T extends { nome: string }>(lista: T[]): T[] {
  return [...lista].sort((a, b) => a.nome.localeCompare(b.nome, "pt-BR", { sensitivity: "base" }));
}
