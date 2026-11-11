/**
 * Formatação pt-BR da análise educacional — sempre na precisão que a API manda
 * (`casas`), sem inventar nem perder casas; ausência por extenso, nunca "0".
 */
import { MOTIVOS, numeroBR } from "../rede/ica";
import { MOTIVOS_IDEB } from "../rede/ideb";
import type { SituacaoMeta } from "./tipos";
import type {
  CategoriaLeitura, ContagemEscolas, EixoLeitura, EstadoEixo, LeituraComponente, NivelAcompanhamento,
  PendenciaDiagnostico, PosicaoRede, Tendencia,
} from "./tiposDiagnostico";

export { numeroBR };

/** Os motivos de um bloco SEM número que são PROTEÇÃO (poucos alunos), não falta de dado:
 *  `poucos_alunos_medidos` (menos de k alunos medidos), `series_suprimidas` (todas as séries da
 *  escola com poucos alunos) e `suprimido` (o recorte escondido junto com um pequeno). */
export const MOTIVOS_DE_PROTECAO: ReadonlySet<string> = new Set(["poucos_alunos_medidos", "series_suprimidas", "suprimido"]);

/**
 * O número que falta está PROTEGIDO (existe e não aparece, para proteger as crianças) — e não
 * "sem dado"? A regra ÚNICA das telas: o bloco inteiro sem número por um motivo de proteção
 * (`MOTIVOS_DE_PROTECAO`) ou, com `campo`, a métrica escondida em `metricas_protegidas`.
 */
export function numeroProtegido(
  bloco: { motivo_sem_dado?: string | null; metricas_protegidas?: string[] | null } | null | undefined,
  campo?: string,
): boolean {
  if (!bloco) return false;
  if (bloco.motivo_sem_dado && MOTIVOS_DE_PROTECAO.has(bloco.motivo_sem_dado)) return true;
  return campo != null && (bloco.metricas_protegidas ?? []).includes(campo);
}

export const ROTULO_ETAPA: Record<string, string> = {
  "2_ano": "2º ano",
  "5_ano": "5º ano",
  anos_iniciais: "Anos iniciais (1º ao 5º ano)",
};

export const ROTULO_COMPONENTE: Record<string, string> = {
  lp: "Língua Portuguesa",
  mt: "Matemática",
};

export const rotuloEtapa = (etapa: string | null | undefined): string =>
  etapa ? ROTULO_ETAPA[etapa] ?? etapa.replace(/_/g, " ") : "";

export const rotuloComponente = (componente: string | null | undefined): string =>
  componente ? ROTULO_COMPONENTE[componente] ?? componente : "";

/** "5º ano" — a série escolar (1–5) das plataformas. */
export const rotuloSerie = (serie: number): string => `${serie}º ano`;

/**
 * Motivos de ausência que a análise conhece (o texto da API, `texto_ausencia`, vem
 * primeiro; estes são o plano B para um motivo sem texto). Reúne os dos cartões
 * oficiais (ICA, SARESP, Ideb) — a MESMA linguagem da área de detalhes.
 */
export const MOTIVOS_ANALISE: Record<string, string> = {
  ...MOTIVOS,
  ...MOTIVOS_IDEB,
  nao_divulgado: "não divulgado no arquivo oficial",
  participacao_baixa: "sem resultado (participação baixa)",
  sem_codigo_inep: "a escola está sem código INEP no cadastro",
  sem_dado: "sem resultado nesta edição",
  sem_resultado: "sem resultado nesta edição",
};

/** A ausência por extenso: o texto da API, o motivo conhecido, ou "sem resultado". */
export function textoAusencia(
  p: { motivo_ausencia?: string | null; texto_ausencia?: string | null } | null | undefined,
): string {
  if (!p) return "sem resultado";
  if (p.texto_ausencia) return p.texto_ausencia;
  return MOTIVOS_ANALISE[p.motivo_ausencia ?? ""] ?? "sem resultado";
}

/** A edição que a série simplesmente não tem (nenhum ponto nela): a ausência por extenso. */
export const SEM_PONTO_NA_EDICAO = "sem resultado nesta edição";

/**
 * Por que um indicador do catálogo está indisponível — o plano B do `texto_indisponivel`
 * da API (os mesmos textos do backend). Nunca a chave técnica ("sem_importacao") na tela.
 */
export const MOTIVOS_INDISPONIVEL: Record<string, string> = {
  sem_importacao: "nenhum arquivo oficial deste indicador foi importado para esta rede",
  so_estimativa: "só há a Estimativa Constela (calculada pelo Constela): ela não é o indicador oficial",
  so_sem_registro:
    "só há números gravados antes, sem o registro do arquivo oficial: importe o arquivo oficial desta edição",
  sem_codigo_ibge:
    "a rede não tem o código IBGE do município cadastrado: os números da rede não podem ser recortados",
};

export function textoIndisponivel(
  ind: { texto_indisponivel?: string | null; motivo_indisponivel?: string | null },
): string {
  return ind.texto_indisponivel
    ?? MOTIVOS_INDISPONIVEL[ind.motivo_indisponivel ?? ""]
    ?? "sem dado oficial importado";
}

/**
 * Número SEM registro oficial (gravado antes, pelo botão de 1 clique): aparece com esta
 * marca e a legenda — não é a Estimativa Constela e não entra nos destaques nem na relação.
 */
export const MARCA_SEM_REGISTRO = "*";
export const TEXTO_SEM_REGISTRO = "número gravado antes, sem o registro do arquivo oficial";

export const ehSemRegistro = (p: { proveniencia?: string | null; valor?: number | null } | null | undefined) =>
  Boolean(p && p.valor != null && p.proveniencia === "sem_registro");

/** A legenda da marca: o texto do backend (com "difere do arquivo oficial", se for o caso). */
export function legendaSemRegistro(
  pontos: { proveniencia?: string | null; valor?: number | null; difere_do_oficial?: boolean }[],
): string | null {
  const marcados = pontos.filter(ehSemRegistro);
  if (marcados.length === 0) return null;
  const difere = marcados.filter((p) => p.difere_do_oficial).length;
  return `${MARCA_SEM_REGISTRO} ${TEXTO_SEM_REGISTRO} (o botão de importação em 1 clique, sem prévia)${
    difere ? `; ${difere === 1 ? "um deles difere" : `${difere} deles diferem`} do arquivo oficial importado` : ""
  }. Não é a Estimativa Constela e não entra nos destaques nem na relação com as plataformas.`;
}

/** Sufixo da unidade junto do número: só o "%" (pontos e índices vão sem sufixo). */
export const sufixo = (unidade: string | null | undefined): string => (unidade === "%" ? "%" : "");

/** "acima de " / "≥ " quando a fonte publica o número com operador (ICA). */
export const prefixoOperador = (operador: string | null | undefined): string =>
  operador === ">" ? "acima de " : operador === ">=" ? "≥ " : "";

/** "56%", "230,1", "6,2" — na precisão recebida (com o operador da fonte, se houver). */
export function valorComUnidade(
  valor: number, casas: number | null | undefined, unidade?: string | null, operador?: string | null,
): string {
  return `${prefixoOperador(operador)}${numeroBR(valor, casas ?? 0)}${sufixo(unidade)}`;
}

/** "−5 p.p." (percentual) ou "+0,3" (pontos/índice), com o sinal de menos tipográfico. */
export function diferencaComUnidade(dif: number, casas: number | null | undefined, unidade?: string | null): string {
  const sinal = dif < 0 ? "−" : dif > 0 ? "+" : "";
  return `${sinal}${numeroBR(Math.abs(dif), casas ?? 0)}${unidade === "%" ? " p.p." : ""}`;
}

/** A diferença resultado × meta é escrita na MENOR precisão dos dois lados. */
export function casasDaDiferenca(casas: number | null | undefined, metaCasas: number | null | undefined): number {
  const a = casas ?? 0;
  return metaCasas == null ? a : Math.min(a, metaCasas);
}

export const ROTULO_SITUACAO: Record<SituacaoMeta, string> = {
  atingiu: "atingiu a meta",
  nao_atingiu: "não atingiu a meta",
  inconclusivo: "inconclusivo (empate na precisão divulgada)",
};

/** Número de plataforma (calculado pelo Constela): como a API manda (ela já arredonda),
 *  até `casas` casas, sem inventar zeros; null → null (a tela escreve a ausência). */
export function decimal(valor: number | null | undefined, casas = 2): string | null {
  if (valor == null) return null;
  return valor.toLocaleString("pt-BR", { maximumFractionDigits: casas });
}

/** "AAAA-MM-DD…" → "DD/MM/AAAA" (só o dia). */
export function diaBR(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const [a, m, d] = iso.slice(0, 10).split("-");
  return a && m && d ? `${d}/${m}/${a}` : null;
}

/** Ordem ALFABÉTICA (sem acento nem caixa) — listas de escolas nunca são ranking. */
export function porNome<T extends { nome: string }>(lista: T[]): T[] {
  return [...lista].sort((a, b) => a.nome.localeCompare(b.nome, "pt-BR", { sensitivity: "base" }));
}

/**
 * Faixa do eixo Y com limites inteiros e amplitude PAR: o `GraficoLinha` rotula a
 * linha do meio arredondando para inteiro — com amplitude ímpar ela mentiria (a
 * mesma regra de `faixaIdeb`). Percentual nunca passa de 0–100.
 */
export function faixaDoEixo(valores: number[], unidade?: string | null): { minimo: number; maximo: number } {
  const teto = unidade === "%" ? 100 : Number.POSITIVE_INFINITY;
  if (valores.length === 0) return { minimo: 0, maximo: unidade === "%" ? 100 : 10 };
  const menor = Math.min(...valores);
  const maior = Math.max(...valores);
  const folga = Math.max((maior - menor) * 0.25, maior <= 10 ? 0.5 : 2);
  let minimo = Math.max(0, Math.floor(menor - folga));
  let maximo = Math.min(teto, Math.ceil(maior + folga));
  if (maximo <= minimo) maximo = minimo + 2;
  if ((maximo - minimo) % 2 !== 0) {
    if (maximo + 1 <= teto) maximo += 1;
    else minimo = Math.max(0, minimo - 1);
  }
  return { minimo, maximo };
}

// --- Diagnóstico pedagógico (exploratório) e evolução por bimestre ----------------------
// Os rótulos dizem o estado POR EXTENSO (a cor nunca é o único código) e nenhum soa como
// nota ou ranking: "Prioritário" é a ordem de conversa com a escola, não uma classificação.

export const ORDEM_NIVEIS: NivelAcompanhamento[] = [
  "prioritario", "acompanhar", "oportunidade", "dados_insuficientes", "sem_sinal",
];

export const ROTULO_NIVEL: Record<NivelAcompanhamento, string> = {
  prioritario: "Prioritário",
  acompanhar: "Acompanhar",
  oportunidade: "Oportunidade",
  dados_insuficientes: "Dados insuficientes",
  sem_sinal: "Sem sinal",
};

/** A regra de cada nível em uma linha (a mesma do backend, para a legenda dos chips). */
export const EXPLICA_NIVEL: Record<NivelAcompanhamento, string> = {
  prioritario: "avaliação e plataforma em atenção no mesmo componente",
  acompanhar: "avaliação em atenção com uso alto da plataforma, ou meta oficial (IEE/Ideb) não atingida",
  oportunidade: "avaliação favorável com uso baixo da plataforma",
  dados_insuficientes: "sem número oficial e sem plataforma medida",
  sem_sinal: "nenhum dos sinais acima",
};

export const ROTULO_ESTADO: Record<EstadoEixo, string> = {
  favoravel: "Favorável",
  atencao: "Atenção",
  misto: "Misto",
  // O backend usa `sem_dado` também para "números na média / estáveis": não há sinal com
  // direção — não necessariamente falta número (o motivo, nos sinais, diz qual dos dois).
  sem_dado: "Sem sinal",
};

export const ROTULO_CATEGORIA: Record<CategoriaLeitura, string> = {
  convergente_favoravel: "Convergente favorável",
  convergente_atencao: "Convergente em atenção",
  divergente_uso_alto: "Divergente: uso alto, avaliação em atenção",
  divergente_uso_baixo: "Divergente: avaliação favorável, uso baixo",
  inconclusiva: "Inconclusiva",
};

export const ROTULO_POSICAO: Record<PosicaoRede, string> = {
  acima: "acima da rede",
  abaixo: "abaixo da rede",
  na_media: "na média da rede",
};

/** ▲ / = / ▼ — sempre ACOMPANHADO do texto (o símbolo sozinho não basta). */
export const SIMBOLO_POSICAO: Record<PosicaoRede, string> = { acima: "▲", abaixo: "▼", na_media: "=" };

export const ROTULO_TENDENCIA: Record<Tendencia, string> = { subiu: "subiu", caiu: "caiu", estavel: "estável" };

/** A situação da coleta de uma escola numa plataforma (a do serviço das plataformas). */
export const ROTULO_COBERTURA: Record<string, string> = {
  ok: "coleta em dia",
  coleta_parcial: "coleta parcial",
  sem_coleta: "sem coleta",
  sem_coleta_no_periodo: "sem coleta no período",
  modulo_nao_contratado: "módulo não contratado",
  sem_alunos_no_recorte: "sem alunos no recorte",
};

/** "coleta parcial" — nunca a chave técnica; desconhecida vira texto legível. */
export const rotuloCobertura = (situacao: string | null | undefined): string | null =>
  situacao ? ROTULO_COBERTURA[situacao] ?? situacao.replace(/_/g, " ") : null;

/** O eixo como estado (o desenho aceita "favoravel" ou {estado: "favoravel", base}). */
export function estadoDoEixo(eixo: EixoLeitura | null | undefined): EstadoEixo {
  if (!eixo) return "sem_dado";
  return typeof eixo === "string" ? eixo : eixo.estado ?? "sem_dado";
}

/** A leitura da avaliação usou os indicadores GERAIS (IEE/Ideb) por falta do componente? */
export function avaliacaoPelaBaseGeral(l: LeituraComponente | null | undefined): boolean {
  if (!l) return false;
  const doEixo = typeof l.avaliacao === "object" && l.avaliacao ? l.avaliacao.base : null;
  return (l.base ?? doEixo) === "geral";
}

/** Uma situação de cobertura de UMA plataforma (o campo vem por plataforma ou já único). */
export function coberturaDe(
  valor: Partial<Record<"elefante" | "matific", string | null>> | string | null | undefined,
  plataforma: "elefante" | "matific",
): string | null {
  if (valor == null) return null;
  return typeof valor === "string" ? valor : valor[plataforma] ?? null;
}

const PENDENCIAS: Record<string, string> = {
  sem_codigo_inep: "sem código INEP no cadastro (os arquivos oficiais não casam)",
};

/** A pendência por extenso (o texto do backend, o código conhecido ou o código legível). */
export function textoPendencia(p: PendenciaDiagnostico): string {
  if (typeof p !== "string") return p.texto ?? (p.codigo ? PENDENCIAS[p.codigo] ?? p.codigo.replace(/_/g, " ") : "");
  if (PENDENCIAS[p]) return PENDENCIAS[p];
  return /^[a-z0-9_]+$/.test(p) ? p.replace(/_/g, " ") : p;
}

export const temPendencia = (lista: PendenciaDiagnostico[] | null | undefined, codigo: string): boolean =>
  (lista ?? []).some((p) => (typeof p === "string" ? p === codigo : p.codigo === codigo));

/** "5" ou "Elefante 5 · Matific 4" — a contagem de escolas como o backend manda. */
export function textoContagem(c: ContagemEscolas | undefined): string | null {
  if (c == null) return null;
  if (typeof c === "number") return c.toLocaleString("pt-BR");
  const partes = [
    c.elefante != null ? `Elefante ${c.elefante.toLocaleString("pt-BR")}` : null,
    c.matific != null ? `Matific ${c.matific.toLocaleString("pt-BR")}` : null,
  ].filter(Boolean);
  return partes.length ? partes.join(" · ") : null;
}

/** As tolerâncias do critério ("Ideb 0,2; SARESP 5 pontos…"): as chaves conhecidas por
 *  extenso; uma chave nova aparece legível, nunca some. */
const ROTULO_TOLERANCIA: Record<string, (v: string) => string> = {
  participacao: (v) => `participação ${v} p.p.`,
  participacao_pp: (v) => `participação ${v} p.p.`,
  intensidade: (v) => `intensidade ${v}% do valor da rede`,
  intensidade_pct: (v) => `intensidade ${v}% do valor da rede`,
  intensidade_pct_da_rede: (v) => `intensidade ${v}% do valor da rede`,
  ideb: (v) => `Ideb ${v}`,
  iee: (v) => `IEE ${v} (só tendência)`,
  saresp: (v) => `SARESP ${v} pontos`,
  saeb: (v) => `Saeb ${v} pontos`,
};

export function textoTolerancias(t: Record<string, number | string> | null | undefined): string[] {
  return Object.entries(t ?? {}).map(([chave, valor]) => {
    const v = typeof valor === "number" ? valor.toLocaleString("pt-BR") : String(valor);
    return ROTULO_TOLERANCIA[chave]?.(v) ?? `${chave.replace(/_/g, " ")}: ${v}`;
  });
}
