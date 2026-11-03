/**
 * Selo de FONTE de um número (ou de um bloco de números) de indicador oficial —
 * plano dos indicadores, 5.4. Diz quem publicou, qual arquivo e de quando (datas e
 * arquivos dos exemplos: SINTÉTICOS):
 *
 *  - planilha de resultados: "INEP — Indicador Criança Alfabetizada, arquivo de
 *    15/07/2026 (resultados_e_metas_municipios_2025_3.xlsx)";
 *  - microdados agregados (TS_MUNICIPIO/TS_ESTADO): "INEP — Microdados da avaliação
 *    da alfabetização, microdados de 10/03/2026 (microdados_sintetico_2025.zip)" — e,
 *    nas casas decimais que vêm deles como DETALHE de um número de capa, "detalhe dos
 *    microdados de 10/03/2026".
 *  - CSV da SEDUC (SARESP/IEE): "SEDUC-SP — Proficiência do SARESP por município,
 *    SARESP 2025, arquivo de 12/01/2026 (….csv)" — o CSV não tem data interna; a API
 *    manda em `data_arquivo` o dia do Last-Modified informado na importação.
 *  - pacote do Ideb por escola (e do município, da UF e do Brasil): "INEP — Ideb por
 *    escola, anos iniciais (…), divulgação 2023, arquivo de 02/06/2031 (ideb.zip)" — a
 *    divulgação diz de que arquivo vem a série inteira; a data é a interna da planilha
 *    no zip do INEP;
 *  - pacote da planilha do Saeb: "INEP — Saeb: resultados de Brasil, estados e
 *    municípios (planilha), Saeb 2025, arquivo de 02/06/2031 (….xlsx)".
 *
 * A data é a gravada no arquivo (o INEP a põe lá); sem ela, a do Last-Modified do
 * servidor; sem nenhuma, o selo não inventa data. Reutilizável pelas próximas abas
 * (SAEB, SARESP): só depende do formato da fonte que a API devolve.
 */
import { FileSearch } from "lucide-react";

import { dataHora } from "../lib/formato";

export interface FonteOficial {
  importacao_id: number;
  fonte_nome: string;
  arquivo_nome: string;
  arquivo_data: string | null;
  last_modified_origem: string | null;
  url_origem: string | null;
  edicao_arquivo: number;
  versao_rotulo: string | null;
  importado_em: string | null;
  coletado_em: string | null;
  citacao: string | null;
  licenca: string | null;
  /** inep_ica_* (planilha de resultados) | inep_aeeb_agregados (microdados agregados). */
  parser?: string;
  modo?: string;
  /** Observações do próprio arquivo oficial (rodapé), como publicadas. */
  notas?: string[];
  /** Dia do arquivo já resolvido pela API (AAAA-MM-DD) — nos CSVs da SEDUC, o do
   *  Last-Modified informado na importação. Ausente nas fontes do ICA. */
  data_arquivo?: string | null;
  data_arquivo_origem?: "interna" | "last_modified" | null;
}

export const PARSER_MICRODADOS = "inep_aeeb_agregados";
/** Ideb por escola (pacote do zip do INEP): a data é a interna da planilha no zip. */
export const PARSER_IDEB_ESCOLAS = "inep_ideb_escolas";
/** Os arquivos do Ideb (por escola, por município e de UF/Brasil): a divulgação no selo. */
export const PARSERS_IDEB = [PARSER_IDEB_ESCOLAS, "inep_ideb_municipios", "inep_ideb_uf_brasil"];
/** A planilha de resultados do Saeb (Brasil, estados e municípios), uma por edição. */
export const PARSER_PLANILHA_SAEB = "inep_saeb_planilha";

export function ehMicrodados(f: Pick<FonteOficial, "parser"> | null | undefined): boolean {
  return f?.parser === PARSER_MICRODADOS;
}

/** CSV aberto da SEDUC-SP (IEE, SARESP por município ou por instância). */
export function ehSeduc(f: Pick<FonteOficial, "parser"> | null | undefined): boolean {
  return Boolean(f?.parser?.startsWith("seduc_"));
}

/** "AAAA-MM-DD…" → "DD/MM/AAAA" (só o dia, como publicado). */
export function diaDoArquivo(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const [a, m, d] = iso.slice(0, 10).split("-");
  return a && m && d ? `${d}/${m}/${a}` : null;
}

/** "Tue, 10 Mar 2026 13:00:00 GMT" → "10/03/2026" (o dia em UTC); ilegível → null. */
export function diaDoLastModified(texto: string | null | undefined): string | null {
  if (!texto) return null;
  const quando = new Date(texto);
  if (Number.isNaN(quando.getTime())) return null;
  return diaDoArquivo(quando.toISOString());
}

/**
 * O dia do arquivo: a data interna. Só nos microdados, sem ela, o Last-Modified (que
 * ali vem do servidor do INEP, pelo manifesto do pacote); na planilha o Last-Modified
 * é digitado na importação e não vira "arquivo de". Sem nenhum, null.
 */
export function diaDaFonte(f: FonteOficial | null | undefined): string | null {
  if (!f) return null;
  const interna = diaDoArquivo(f.arquivo_data);
  return interna
    ?? (ehMicrodados(f) ? diaDoLastModified(f.last_modified_origem) : null)
    ?? diaDoArquivo(f.data_arquivo);
}

/** O texto do selo de UMA fonte (sem o "Fonte:" e sem a data de importação). */
export function textoFonte(f: FonteOficial): string {
  if (ehMicrodados(f)) {
    const dia = diaDaFonte(f);
    return `${f.fonte_nome}, ${dia ? `microdados de ${dia}` : "microdados sem data"} (${f.arquivo_nome})`;
  }
  if (ehSeduc(f)) {
    // O IEE "2025-2026" é calculado com o SARESP 2025: a edição evita a confusão.
    const dia = diaDaFonte(f);
    return `${f.fonte_nome}, SARESP ${f.edicao_arquivo}, `
      + `${dia ? `arquivo de ${dia}` : "data do arquivo não informada"} (${f.arquivo_nome})`;
  }
  if (f.parser && PARSERS_IDEB.includes(f.parser)) {
    // Um arquivo do Ideb traz a série inteira (2005–AAAA): a DIVULGAÇÃO diz de qual é.
    const dia = diaDoArquivo(f.arquivo_data);
    return `${f.fonte_nome}, divulgação ${f.edicao_arquivo}, `
      + `${dia ? `arquivo de ${dia}` : "data do arquivo não informada"} (${f.arquivo_nome})`;
  }
  if (f.parser === PARSER_PLANILHA_SAEB) {
    // Uma planilha do Saeb por edição: a edição vem no selo (o nome do arquivo varia).
    const dia = diaDoArquivo(f.arquivo_data);
    return `${f.fonte_nome}, Saeb ${f.edicao_arquivo}, `
      + `${dia ? `arquivo de ${dia}` : "data do arquivo não informada"} (${f.arquivo_nome})`;
  }
  const dia = diaDoArquivo(f.arquivo_data);
  return `${f.fonte_nome}, arquivo ${dia ? `de ${dia} ` : ""}(${f.arquivo_nome})`;
}

/** Como dizer de onde vêm as casas decimais de um DETALHE. */
export function textoDetalhe(f: FonteOficial | null | undefined): string {
  const dia = diaDaFonte(f);
  if (ehMicrodados(f)) return dia ? `detalhe dos microdados de ${dia}` : "detalhe dos microdados";
  return dia ? `no arquivo de ${dia}` : "";
}

/** Fontes sem repetição, na ordem em que aparecem. */
export function fontesUnicas(fontes: (FonteOficial | null | undefined)[]): FonteOficial[] {
  const vistas = new Map<number, FonteOficial>();
  for (const f of fontes) if (f && !vistas.has(f.importacao_id)) vistas.set(f.importacao_id, f);
  return [...vistas.values()];
}

/**
 * O selo de um BLOCO: uma linha por arquivo de onde vêm os números do bloco, com a
 * data de importação e a licença. Sem fonte nenhuma, não aparece (nada importado).
 */
export default function SeloFonte({ fontes, testId, titulo }: {
  fontes: (FonteOficial | null | undefined)[];
  testId?: string;
  titulo?: string;
}) {
  const unicas = fontesUnicas(fontes);
  if (unicas.length === 0) return null;
  return (
    <div className="flex items-start gap-2.5 break-words rounded-2xl border border-zinc-200/80 bg-zinc-50 px-3.5 py-3 text-xs text-zinc-600 dark:border-zinc-800 dark:bg-zinc-800/50 dark:text-zinc-400"
         data-testid={testId}>
      <FileSearch size={14} aria-hidden className="mt-0.5 shrink-0 text-zinc-500 dark:text-zinc-400" />
      <div className="min-w-0 space-y-1">
        {titulo && <p className="font-semibold text-zinc-700 dark:text-zinc-300">{titulo}</p>}
        {unicas.map((f) => (
          <p key={f.importacao_id}>
            Fonte: {textoFonte(f)}
            {f.importado_em ? ` · importado em ${dataHora(f.importado_em)}` : ""}
          </p>
        ))}
        {unicas[0]?.licenca && <p className="text-zinc-500 dark:text-zinc-400">{unicas[0].licenca}</p>}
      </div>
    </div>
  );
}

/**
 * O selo de UM número: a fonte curta ao lado do valor ("microdados de 10/03/2026",
 * "arquivo de 15/07/2026"), com o texto completo no título e para leitor de tela.
 */
export function SeloNumero({ fonte, detalhe = false }: { fonte: FonteOficial | null | undefined; detalhe?: boolean }) {
  if (!fonte) return null;
  const dia = diaDaFonte(fonte);
  const curto = detalhe
    ? textoDetalhe(fonte)
    : ehMicrodados(fonte) ? (dia ? `microdados de ${dia}` : "microdados") : (dia ? `arquivo de ${dia}` : fonte.arquivo_nome);
  return (
    <span className="block text-[11px] text-zinc-500 dark:text-zinc-400" title={`Fonte: ${textoFonte(fonte)}`}>
      {curto}
      <span className="sr-only"> — fonte: {textoFonte(fonte)}</span>
    </span>
  );
}
