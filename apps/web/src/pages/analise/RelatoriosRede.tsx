/**
 * Os montadores das PLANILHAS (CSV) da rede e o cartão de cada arquivo:
 *
 *  - `tabelaCsvDiagnostico` (o Diagnóstico exploratório, na área avançada), `tabelaCsvAvaliacoes`
 *    (avaliações por escola), `tabelaCsvPlataformas` (Elefante e Matific por escola no período)
 *    e `tabelaCsvAcompanhamento` (os sinais das escolas em acompanhamento): gerados no navegador
 *    com `lib/csvRanking` (";", BOM, proteção contra fórmula), a partir das MESMAS respostas que
 *    as telas mostram — nenhum número calculado aqui; ausência e proteção saem escritas ("sem
 *    dado", "protegido"), nunca 0;
 *  - `CartaoRelatorio`: um arquivo ou destino, dizendo O QUE contém e DE QUANDO são os números
 *    (a tela Relatórios e exportações, `/rede/relatorios`, é feita deles).
 *
 * (Era a aba antiga "Relatórios e exportações" da análise, `?ver=relatorios`, que virou a tela
 * `/rede/relatorios`; o CSV do Diagnóstico ficou na aba Diagnóstico, na área avançada.)
 */
import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { IconePastel, Mensagem, type TomPastel } from "../../components/ui";
import { nomeArquivoCsv, type CelulaCsv, type TabelaCsv } from "../../lib/csvRanking";
import {
  ROTULO_CATEGORIA, ROTULO_COBERTURA, ROTULO_ESTADO, ROTULO_NIVEL, ROTULO_POSICAO, ROTULO_SITUACAO, ROTULO_TENDENCIA,
  avaliacaoPelaBaseGeral, coberturaDe, diaBR, estadoDoEixo, numeroBR, porNome, rotuloComponente, rotuloCobertura,
  rotuloEtapa, rotuloSerie, temPendencia, textoPendencia,
} from "./formato";
import type { MetricasElefante, MetricasMatific, RespostaIndicadoresRede, RespostaPlataformas } from "./tipos";
import type { LeituraComponente, NaturezaSinal, RespostaDiagnostico } from "./tiposDiagnostico";
import { textoSimples } from "../rede/secretaria/oQueMede";

const CINZA = "text-zinc-600 dark:text-zinc-400";

// --- Montadores das tabelas CSV ----------------------------------------------------------

const NATUREZA_CSV: Record<NaturezaSinal, string> = {
  oficial: "Oficial", calculado: "Calculado pelo Constela", plataforma: "Plataforma", dados: "Dados",
};

/** A natureza de um sinal na planilha. No eixo das plataformas o NÚMERO é da plataforma, mas
 *  o "abaixo da rede" é julgado pelo Constela (tolerância própria) — as duas coisas, como na
 *  tela de Escolas em acompanhamento. */
function naturezaDoSinal(s: { eixo: string; natureza: NaturezaSinal }): string {
  if (s.eixo === "plataforma") return `${NATUREZA_CSV.plataforma} + ${NATUREZA_CSV.calculado}`;
  return NATUREZA_CSV[s.natureza] ?? s.natureza;
}

/** As colunas de UMA leitura (LP ou MT). Os anos e a comparabilidade são POR COMPONENTE: a
 *  escola pode ter SARESP só de MT (LP sem avaliação) ou edições diferentes em cada um — uma
 *  coluna única, tirada da LP, diria "sem resultado oficial" para a MT que tem número. */
/** Ano como TEXTO na célula: número passa por `toLocaleString("pt-BR")` no CSV e 2025 sairia
 *  "2.025" (o decimal 2,025 numa planilha em inglês ou num script). */
const ano = (n: number | null | undefined): string | null => (n == null ? null : String(n));

const COLUNAS_LEITURA = [
  "avaliação", "base da avaliação", "plataforma", "categoria", "ano da avaliação usada", "ano letivo das plataformas",
  "comparabilidade",
];

function colunasLeitura(l: LeituraComponente | undefined): CelulaCsv[] {
  if (!l) return COLUNAS_LEITURA.map(() => "sem leitura");
  // A base só existe quando alguma avaliação entrou (sem sinal nenhum, o backend manda null).
  const base = l.base ?? (typeof l.avaliacao === "object" && l.avaliacao ? l.avaliacao.base : null);
  return [
    ROTULO_ESTADO[estadoDoEixo(l.avaliacao)],
    avaliacaoPelaBaseGeral(l) ? "indicadores gerais (IEE/Ideb)"
      : base === "componente" || (base == null && estadoDoEixo(l.avaliacao) !== "sem_dado") ? "do componente"
        : "nenhuma avaliação entrou",
    ROTULO_ESTADO[estadoDoEixo(l.plataforma)],
    ROTULO_CATEGORIA[l.categoria] ?? l.categoria,
    ano(l.anos?.avaliacao) ?? "nenhuma avaliação entrou",
    ano(l.anos?.plataforma) ?? "nenhuma plataforma entrou",
    l.comparabilidade === "mesmo_ano" ? "mesmo ano (associação, nunca causa)"
      : l.comparabilidade === "exploratoria" ? "exploratória (anos e coortes diferentes)"
        // Sem rótulo: falta um dos lados OU nenhum sinal com direção decide a leitura — o
        // texto do backend diz qual dos dois.
        : l.texto_comparabilidade ?? "sem comparação (falta a avaliação ou a plataforma)",
  ];
}

/** Uma linha por escola (ordem alfabética): nível, motivos, as duas leituras e TODOS os sinais. */
export function tabelaCsvDiagnostico(d: RespostaDiagnostico, hoje?: Date): TabelaCsv {
  return {
    nomeArquivo: nomeArquivoCsv("diagnostico-pedagogico-exploratorio", hoje),
    cabecalho: [
      "Escola", "Código INEP", "Acompanhamento (hipótese exploratória)", "Motivos",
      ...COLUNAS_LEITURA.map((c) => `Leitura (LP) — ${c}`),
      ...COLUNAS_LEITURA.map((c) => `Matemática (MT) — ${c}`),
      "Sinais (natureza: texto [referência])", "Pendências",
    ],
    linhas: porNome(d.escolas).map((e) => [
      e.nome, e.codigo_inep ?? "sem código INEP",
      ROTULO_NIVEL[e.acompanhamento.nivel] ?? e.acompanhamento.nivel,
      e.acompanhamento.motivos.join(" | "),
      ...colunasLeitura(e.leituras?.lp), ...colunasLeitura(e.leituras?.mt),
      e.sinais.map((s) => `${naturezaDoSinal(s)}: ${s.texto} [${s.referencia}]`).join(" | "),
      e.pendencias.map(textoPendencia).join(" | "),
    ]),
  };
}

/** Uma linha por escola × série oficial (a última edição com número oficial); a escola sem
 *  número oficial nenhum ganha uma linha que diz isso. */
export function tabelaCsvAvaliacoes(d: RespostaDiagnostico, base: RespostaIndicadoresRede, hoje?: Date): TabelaCsv {
  const nome = (chave: string) => base.indicadores.find((i) => i.chave === chave)?.nome ?? chave.toUpperCase();
  const linhas: CelulaCsv[][] = [];
  for (const e of porNome(d.escolas)) {
    if (e.oficiais.length === 0) {
      const motivo = temPendencia(e.pendencias, "sem_codigo_inep") || !e.codigo_inep
        ? "sem código INEP no cadastro" : "sem resultado oficial importado";
      linhas.push([e.nome, e.codigo_inep ?? "sem código INEP", "", "", "", "", motivo]);
      continue;
    }
    for (const o of e.oficiais) {
      linhas.push([
        e.nome, e.codigo_inep ?? "sem código INEP", nome(o.indicador), rotuloEtapa(o.etapa), rotuloComponente(o.componente),
        ano(o.edicao), numeroBR(o.valor, o.casas ?? 0),
        o.meta == null ? "" : numeroBR(o.meta, o.meta_casas ?? o.casas ?? 0),
        o.situacao_meta ? ROTULO_SITUACAO[o.situacao_meta] : "",
        o.valor_rede == null ? "" : numeroBR(o.valor_rede, o.casas_rede ?? o.casas ?? 0),
        o.diferenca_rede,
        o.posicao_rede ? ROTULO_POSICAO[o.posicao_rede] : "",
        // Os motivos do servidor na língua simples da tela (a planilha sai do fluxo principal).
        o.posicao_rede ? "" : textoSimples(o.motivo_sem_comparacao),
        ano(o.anterior?.edicao) ?? "", o.anterior ? numeroBR(o.anterior.valor, o.anterior.casas ?? o.casas ?? 0) : "",
        o.tendencia ? ROTULO_TENDENCIA[o.tendencia] : textoSimples(o.motivo_sem_tendencia),
        // O IEE calculado com médias de TPS = 0 NÃO é instável (regra do backend: o número
        // oficial vale), mas a tela o marca ("calculado com médias instáveis") — o "não" seco a
        // contradiria.
        o.instavel ? "sim" : o.tps_zero ? "não (IEE calculado com médias instáveis)" : "não",
      ]);
    }
  }
  return {
    nomeArquivo: nomeArquivoCsv("avaliacoes-por-escola", hoje),
    cabecalho: [
      "Escola", "Código INEP", "Indicador", "Etapa", "Componente", "Edição", "Resultado (oficial)", "Meta (oficial)",
      "Situação da meta (oficial)", "Rede municipal na mesma edição", "Diferença escola − rede (calculado pelo Constela)",
      "Posição contra a rede (calculado pelo Constela)", "Por que não há posição", "Edição anterior",
      "Resultado anterior", "Tendência (calculado pelo Constela)", "Média instável (poucos alunos fizeram a prova)",
    ],
    linhas,
  };
}

const FONTE_DO_EIXO: Record<string, string> = {
  avaliacao: "Avaliações externas", plataforma: "Elefante e Matific", dados: "Dados incompletos",
};
/** O módulo que a rede não contratou é escolha do contrato, não dado faltando na escola: fica
 *  na planilha com o rótulo próprio (a tela de Escolas em acompanhamento não o lista). */
const ONDE_DO_SINAL: Record<string, string> = { modulo_nao_contratado: "Módulo não contratado pela rede" };
const TIPO_DO_SINAL: Record<string, string> = { atencao: "atenção", favoravel: "favorável", informativo: "informativo" };

/**
 * Escolas em acompanhamento (CSV): uma linha por SINAL (ordem alfabética das escolas), com a
 * fonte (avaliações externas × Elefante e Matific × dados incompletos), o tipo (atenção,
 * favorável, informativo), a natureza e a referência — os mesmos sinais da tela, mais os
 * favoráveis, que a tela não lista. A escola sem sinal nenhum ganha uma linha que diz isso. Sem
 * nível nem categoria (são exploratórios: ficam no CSV do Diagnóstico, na área avançada).
 */
export function tabelaCsvAcompanhamento(d: RespostaDiagnostico, hoje?: Date): TabelaCsv {
  const linhas: CelulaCsv[][] = [];
  for (const e of porNome(d.escolas)) {
    const inep = e.codigo_inep ?? "sem código INEP";
    if (e.sinais.length === 0) {
      linhas.push([e.nome, inep, "", "sem sinal", "", "nenhum sinal nesta leitura", ""]);
      continue;
    }
    for (const s of e.sinais) {
      linhas.push([
        // O texto do sinal como a tela de Escolas em acompanhamento o mostra (língua simples).
        e.nome, inep, ONDE_DO_SINAL[s.codigo] ?? FONTE_DO_EIXO[s.eixo] ?? s.eixo, TIPO_DO_SINAL[s.direcao] ?? s.direcao,
        naturezaDoSinal(s), textoSimples(s.texto), s.referencia,
      ]);
    }
  }
  return {
    nomeArquivo: nomeArquivoCsv("escolas-em-acompanhamento", hoje),
    cabecalho: ["Escola", "Código INEP", "Onde", "Tipo de sinal", "Natureza", "Sinal", "Referência"],
    linhas,
  };
}

/** Métrica de plataforma para o CSV: o número, ou "protegido"/"sem dado" escritos. */
function metrica(v: number | null | undefined, campo: string, bloco: MetricasElefante | MetricasMatific | null): CelulaCsv {
  if (v != null) return v;
  return (bloco?.metricas_protegidas ?? []).includes(campo) ? "protegido" : "sem dado";
}

/** Uma linha por escola (ordem alfabética), as colunas só dos módulos contratados. Com uma
 *  série (a leitura foi pedida com `?serie=`), o nome do arquivo diz a série — o arquivo não
 *  se confunde com o da rede inteira (1º ao 5º ano). */
export function tabelaCsvPlataformas(d: RespostaPlataformas, hoje?: Date, serie: number | null = null): TabelaCsv {
  const comE = d.modulos.elefante, comM = d.modulos.matific;
  const cabecalho = [
    "Escola", "Alunos",
    ...(comE ? ["Elefante — participação (%)", "Elefante — livros novos por aluno", "Elefante — minutos por aluno",
      "Elefante — acerto nas questões (%)", "Elefante — coleta"] : []),
    ...(comM ? ["Matific — participação (%)", "Matific — atividades por aluno", "Matific — desempenho (0–5)",
      "Matific — coleta"] : []),
  ];
  const linhas = porNome(d.escolas).map((e): CelulaCsv[] => {
    const n = cabecalho.length - 1;
    if (e.suprimido) return [e.nome, ...Array.from({ length: n }, () => "protegido")];
    const coleta = (p: "elefante" | "matific") => {
      const s = coberturaDe(e.cobertura, p);
      const ate = s === "coleta_parcial" ? diaBR(e.coberto_ate?.[p] ?? null) : null;
      return s ? `${ROTULO_COBERTURA[s] ?? rotuloCobertura(s)}${ate ? ` (até ${ate})` : ""}` : "";
    };
    const el = e.elefante, ma = e.matific;
    return [
      e.nome, e.alunos ?? "sem dado",
      ...(comE ? [metrica(el?.participacao_pct, "participacao_pct", el), metrica(el?.livros_por_aluno, "livros_por_aluno", el),
        metrica(el?.minutos_por_aluno, "minutos_por_aluno", el), metrica(el?.taxa_acerto_pct, "taxa_acerto_pct", el),
        coleta("elefante")] : []),
      ...(comM ? [metrica(ma?.participacao_pct, "participacao_pct", ma), metrica(ma?.atividades_por_aluno, "atividades_por_aluno", ma),
        metrica(ma?.desempenho_medio, "desempenho_medio", ma), coleta("matific")] : []),
    ];
  });
  const base = serie != null ? `plataformas-por-escola-${rotuloSerie(serie)}` : "plataformas-por-escola";
  return { nomeArquivo: nomeArquivoCsv(base, hoje), cabecalho, linhas };
}

// --- A tela ------------------------------------------------------------------------------

/** Um arquivo ou destino: o que contém, de quando são os números e a ação (também na tela
 *  Relatórios e exportações, `/rede/relatorios`). */
export function CartaoRelatorio({ icone, tom, titulo, contem, quando, acao, erro, testId }: {
  icone: LucideIcon; tom: TomPastel; titulo: string; contem: ReactNode; quando: ReactNode; acao: ReactNode;
  erro?: string | null; testId: string;
}) {
  return (
    <section className="flex min-w-0 flex-col gap-3 rounded-2xl border border-zinc-200/70 bg-zinc-50/70 p-5 dark:border-zinc-800 dark:bg-zinc-800/40"
             aria-labelledby={`${testId}-titulo`} data-testid={testId}>
      <h3 id={`${testId}-titulo`} className="flex items-center gap-2.5 text-[15px] font-semibold text-zinc-900 dark:text-white">
        <IconePastel icone={icone} tom={tom} tamanho="sm" /> {titulo}
      </h3>
      <p className="text-xs text-zinc-700 dark:text-zinc-200">{contem}</p>
      <p className={`text-xs ${CINZA}`} data-testid={`${testId}-quando`}>
        <span className="font-semibold">De quando: </span>{quando}
      </p>
      {erro && <Mensagem tipo="erro">{erro}</Mensagem>}
      <div className="mt-auto flex flex-wrap gap-2 pt-1">{acao}</div>
    </section>
  );
}

/** O link com cara de botão secundário (o destino é outra tela, não um arquivo). */
export const CLASSE_LINK = "inline-flex items-center gap-2 rounded-xl border border-zinc-200 bg-white px-3.5 py-2 text-sm "
  + "font-semibold text-zinc-800 transition-colors hover:border-indigo-300 hover:text-indigo-700 dark:border-zinc-700 "
  + "dark:bg-zinc-900 dark:text-zinc-100 dark:hover:border-indigo-500/50 dark:hover:text-indigo-300";
