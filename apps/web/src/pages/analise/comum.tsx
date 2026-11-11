/**
 * Peças comuns das telas da análise educacional: abas, "filtros que valem aqui",
 * situação da meta, número oficial com a ausência por extenso, minitendência, a
 * escolha de UM indicador (com o motivo de cada indisponível), o selo único de
 * NATUREZA (oficial, plataforma, calculado pelo Constela, exploratório, estimativa, dados),
 * a faixa fixa da hipótese exploratória e a posição contra a rede (▲/=/▼ com o texto).
 */
import { FlaskConical, SlidersHorizontal } from "lucide-react";
import { useId, useState, type ReactNode } from "react";

import { PRESETS_PERIODO, periodoParaQuery, type Periodo } from "../../components/SeletorPeriodo";
import { Badge, estiloInput } from "../../components/ui";
import { useApp } from "../../context/AppContext";
import { useApi, type OpcoesUseApi } from "../../hooks/useApi";
import { usePerfil } from "../../hooks/usePerfil";
import {
  MARCA_SEM_REGISTRO, ROTULO_POSICAO, ROTULO_SITUACAO, SEM_PONTO_NA_EDICAO, SIMBOLO_POSICAO, TEXTO_SEM_REGISTRO,
  casasDaDiferenca, diaBR, diferencaComUnidade, ehSemRegistro, numeroBR, textoAusencia, textoIndisponivel,
  valorComUnidade,
} from "./formato";
import type { IndicadorAnalise, RespostaPlataformas, SituacaoMeta } from "./tipos";
import type { PosicaoRede, RespostaDiagnostico } from "./tiposDiagnostico";

/** A resposta → as URLs que a devolveram (só nas leituras com cache; ver `useApiExata`). */
const URLS_DA_RESPOSTA = new WeakMap<object, Set<string>>();

/**
 * `useApi` que só entrega os dados QUANDO são da URL pedida agora. O `useApi` guarda a
 * resposta anterior até a nova chegar (ou falhar): ao trocar de indicador, de filtro ou
 * de escola, a tela mostraria os números do recorte anterior sob o título novo. Aqui,
 * enquanto a resposta da URL atual não chega, `dados` é null (carregando ou erro).
 *
 * As `opcoes` vão para o `useApi` (tempo limite, novas tentativas, cache). Com `cacheMs`, o
 * `useApi` entrega a resposta guardada SEM chamar `aoSucesso` (e já no 1º render): por isso
 * a origem de cada resposta fica no WeakMap, e não no estado deste hook — a resposta guardada
 * de outra URL, que o `useApi` mostra enquanto a nova carrega, nunca passa por esta.
 */
export function useApiExata<T>(url: string | null, opcoes: Omit<OpcoesUseApi<T>, "aoSucesso"> = {}) {
  const [origem, setOrigem] = useState<string | null>(null);
  const comCache = (opcoes.cacheMs ?? 0) > 0;
  const r = useApi<T>(url, {
    ...opcoes,
    aoSucesso: (dados) => {
      if (comCache && url != null && typeof dados === "object" && dados !== null) {
        const urls = URLS_DA_RESPOSTA.get(dados) ?? new Set<string>();
        URLS_DA_RESPOSTA.set(dados, urls.add(url));
      }
      setOrigem(url);
    },
  });
  const daUrl = url != null && (comCache && typeof r.dados === "object" && r.dados !== null
    ? URLS_DA_RESPOSTA.get(r.dados)?.has(url) === true
    : origem === url);
  return { ...r, dados: daUrl ? r.dados : null };
}

/**
 * Leituras PESADAS da análise (o diagnóstico mede as plataformas de toda a rede; a evolução,
 * uma vez por bimestre já começado): o servidor pode levar mais que os 15 s padrão com dados
 * reais. Tempo limite de 60 s e SEM nova tentativa automática — o servidor não cancela o
 * cálculo quando a tela desiste, e repetir só somaria outro cálculo inteiro ao primeiro; o
 * erro aparece e quem quiser recarrega. O cache curto evita refazer a medição a cada troca
 * de aba (Visão geral, Avaliações, Diagnóstico e Relatórios pedem o MESMO diagnóstico).
 */
export const OPCOES_LEITURA_PESADA = { timeoutMs: 60_000, tentativas: 0, cacheMs: 60_000 } as const;

/**
 * Os períodos que a SECRETARIA pede nas análises da rede: o ano letivo ou um bimestre inteiro
 * (`services/analise/plataformas.PRESETS_DA_REDE`; o servidor recusa os outros com 422). Com
 * dois períodos que se sobrepõem, a diferença entre eles mostraria os números de uma criança
 * que um deles esconde. O admin global e a coordenação da escola continuam com todos.
 */
export const PRESETS_DA_REDE: ReadonlySet<string> = new Set([
  "ano_letivo", "bimestre", "bimestre_anterior", "bimestre_1", "bimestre_2", "bimestre_3", "bimestre_4",
]);
export const TEXTO_PERIODO_DA_REDE = "Para a Secretaria, o período é o ano letivo ou um bimestre inteiro: "
  + "a diferença entre dois períodos que se sobrepõem mostraria os números de uma criança.";

/** As opções do seletor de período para quem lê (a Secretaria: só as de `PRESETS_DA_REDE`). */
export function presetsDoPeriodo(secretaria: boolean) {
  return secretaria ? PRESETS_PERIODO.filter((p) => PRESETS_DA_REDE.has(p.valor)) : PRESETS_PERIODO;
}

/** O período como a análise da rede o pede: para a Secretaria, um que não vale vira o ano letivo
 *  (o período global, guardado de outra tela, ou um link antigo com `?periodo=mes`). */
export function periodoDaRede(p: Periodo, secretaria: boolean): Periodo {
  return !secretaria || PRESETS_DA_REDE.has(p.preset) ? p : { preset: "ano_letivo" };
}

/** O período GLOBAL como as análises da rede o pedem para quem está logado (`periodoDaRede`). */
export function usePeriodoDaAnalise(): Periodo {
  const { periodo } = useApp();
  const { secretaria } = usePerfil();
  return periodoDaRede(periodo, secretaria);
}

/** As opções de período de quem está logado, para dentro de um `<select>` / `Seletor`. */
export function OpcoesDePeriodo() {
  const { secretaria } = usePerfil();
  return <>{presetsDoPeriodo(secretaria).map((p) => <option key={p.valor} value={p.valor}>{p.rotulo}</option>)}</>;
}

/**
 * O diagnóstico da rede numa janela (só a parte das plataformas depende dela; os números
 * oficiais são a última edição de cada escola). Sem `periodoFixo`, a do período global (a área
 * avançada); as telas principais da Secretaria (Panorama, Escolas em acompanhamento, Comparar
 * escolas, Relatórios) passam o ANO LETIVO — "no ano letivo" na tela não pode virar "este mês"
 * por uma escolha feita na área avançada. Telas que pedem a MESMA URL dividem a leitura (cache
 * curto de `OPCOES_LEITURA_PESADA`).
 */
export function useDiagnostico(redeId: number, periodoFixo?: Periodo) {
  const periodo = usePeriodoDaAnalise();
  return useApiExata<RespostaDiagnostico>(
    `/redes/${redeId}/analise/diagnostico?${periodoParaQuery(periodoFixo ?? periodo)}`, OPCOES_LEITURA_PESADA);
}

/**
 * As plataformas de TODAS as escolas no período (sem `escola_id`: com ele a API devolveria só
 * a escola, e a tabela "Escolas no período" precisa de todas; a escola do filtro é achada na
 * lista). A série vale (é um recorte das plataformas). Sem `periodoFixo`, o período global; as
 * telas principais passam o da própria tela (padrão: o ano letivo).
 *
 * Cache curto (60 s): o Panorama, a tela Elefante e Matific, o Comparar escolas e os
 * Relatórios pedem a MESMA leitura (com dados reais ela leva segundos) — trocar de tela não a
 * refaz. A resposta de outro recorte nunca aparece sob o atual (`useApiExata`).
 */
export function usePlataformasDaRede(redeId: number, serie: number | null, periodoFixo?: Periodo) {
  const periodo = usePeriodoDaAnalise();
  const q = new URLSearchParams(periodoParaQuery(periodoFixo ?? periodo));
  if (serie != null) q.set("serie", String(serie));
  return useApiExata<RespostaPlataformas>(`/redes/${redeId}/analise/plataformas?${q.toString()}`,
                                          { cacheMs: 60_000 });
}

/** O nome do período escolhido (o rótulo do preset, ou as datas do personalizado). */
export function rotuloPeriodo(p: Periodo): string {
  if (p.preset === "personalizado") {
    const de = diaBR(p.inicio), ate = diaBR(p.fim);
    return de && ate ? `de ${de} a ${ate}` : "período personalizado";
  }
  if (p.preset === "dia") return diaBR(p.inicio) ?? "um dia";
  return PRESETS_PERIODO.find((x) => x.valor === p.preset)?.rotulo.toLowerCase() ?? p.preset;
}

// As abas da análise usam o controle segmentado comum (components/AbasLigadas).

/** Células das tabelas da análise (cabeçalho em negrito, linhas mais arejadas). */
export const TH = "px-2.5 py-2 text-left font-semibold";
export const TD = "px-2.5 py-2 tabular-nums";

/** Título de cartão da análise: ícone em quadrado pastel + texto (identidade v2). */
export const TITULO_CARTAO = "flex items-center gap-3 text-[17px] font-semibold tracking-tight text-zinc-900 dark:text-white";

/** A linha que diz QUAIS filtros valem para o bloco (e quais não). */
export function FiltrosAplicados({ children, testId }: { children: ReactNode; testId?: string }) {
  return (
    <p className="flex items-start gap-1.5 text-xs text-zinc-500 dark:text-zinc-400" data-testid={testId}>
      <SlidersHorizontal size={13} className="mt-0.5 shrink-0" aria-hidden />
      <span className="min-w-0 break-words">{children}</span>
    </p>
  );
}

/** "atingiu a meta (+2 p.p.)" — o texto diz a situação; a cor não é o único código. */
export function SituacaoDaMeta({ situacao, diferenca, casas, metaCasas, casasDiferenca, unidade }: {
  situacao: SituacaoMeta | null | undefined;
  diferenca: number | null | undefined;
  casas: number | null | undefined;
  metaCasas?: number | null;
  /** A precisão da diferença dita pelo backend (senão, a menor dos dois lados). */
  casasDiferenca?: number | null;
  unidade?: string | null;
}) {
  if (!situacao) return null;
  const dif = diferenca == null
    ? ""
    : ` (${diferencaComUnidade(diferenca, casasDiferenca ?? casasDaDiferenca(casas, metaCasas), unidade)})`;
  const tom = situacao === "atingiu" ? "ok" : situacao === "nao_atingiu" ? "alerta" : "neutro";
  return <Badge tom={tom}>{ROTULO_SITUACAO[situacao]}{dif}</Badge>;
}

/**
 * O número oficial na precisão publicada; sem número, "—" e o MOTIVO por extenso.
 * O número SEM registro oficial (gravado antes, pelo 1 clique) leva a marca "*" — a
 * legenda fica embaixo da tabela (`legendaSemRegistro`) e o leitor de tela ouve o porquê.
 */
export function ValorOficial({
  valor, casas, unidade, operador, motivo_ausencia, texto_ausencia, proveniencia, texto_proveniencia, traduzir,
}: {
  /** Reescreve os textos do servidor (o motivo da falta, a origem) — a língua simples do fluxo
   *  principal da Secretaria (`textoSimples`); sem ele, o texto de sempre. */
  traduzir?: (t: string) => string;
  valor: number | null;
  casas: number | null;
  unidade?: string | null;
  operador?: string | null;
  motivo_ausencia?: string | null;
  texto_ausencia?: string | null;
  proveniencia?: string | null;
  texto_proveniencia?: string | null;
}) {
  if (valor != null) {
    const texto = valorComUnidade(valor, casas, unidade, operador);
    if (!ehSemRegistro({ valor, proveniencia })) return <>{texto}</>;
    const porque = (traduzir ?? String)(texto_proveniencia ?? TEXTO_SEM_REGISTRO);
    return (
      <span title={porque} data-proveniencia="sem_registro">
        {texto}
        <span aria-hidden className="font-semibold text-amber-700 dark:text-amber-400">{MARCA_SEM_REGISTRO}</span>
        <span className="sr-only"> (sem registro oficial: {porque})</span>
      </span>
    );
  }
  return (
    <span className="text-zinc-600 dark:text-zinc-400">
      <span aria-hidden>— </span>
      <span className="text-[11px] leading-tight">{(traduzir ?? String)(textoAusencia({ motivo_ausencia, texto_ausencia }))}</span>
    </span>
  );
}

/** A edição que a série não tem (nenhum ponto nela): ausência por extenso, nunca "—" mudo. */
export function SemPontoNaEdicao() {
  return <ValorOficial valor={null} casas={null} texto_ausencia={SEM_PONTO_NA_EDICAO} />;
}

/**
 * Minitendência (SVG pequeno): a linha QUEBRA no ano sem resultado — nunca liga os
 * vizinhos nem desce a 0. O texto alternativo lê a série inteira.
 */
export function MiniTendencia({ serie, rotulo, casas, unidade }: {
  serie: { edicao: number; valor: number | null }[];
  rotulo: string;
  casas: number | null;
  unidade?: string | null;
}) {
  const pontos = [...serie].sort((a, b) => a.edicao - b.edicao);
  const valores = pontos.flatMap((p) => (p.valor == null ? [] : [p.valor]));
  if (pontos.length < 2 || valores.length === 0) return null;
  const L = 112, A = 28, m = 3;
  const menor = Math.min(...valores), maior = Math.max(...valores);
  const x = (i: number) => m + (i / (pontos.length - 1)) * (L - 2 * m);
  const y = (v: number) => (maior === menor ? A / 2 : m + (1 - (v - menor) / (maior - menor)) * (A - 2 * m));
  const trechos: string[][] = [[]];
  pontos.forEach((p, i) => {
    if (p.valor == null) {
      if (trechos[trechos.length - 1].length) trechos.push([]);
      return;
    }
    trechos[trechos.length - 1].push(`${x(i)},${y(p.valor)}`);
  });
  const descricao = pontos
    .map((p) => `${p.edicao}: ${p.valor == null ? "sem resultado" : valorComUnidade(p.valor, casas, unidade)}`)
    .join("; ");
  return (
    <svg viewBox={`0 0 ${L} ${A}`} className="h-7 w-28" role="img" aria-label={`Tendência — ${rotulo}: ${descricao}`}>
      {trechos.filter((t) => t.length > 1).map((t, i) => (
        <polyline key={i} points={t.join(" ")} fill="none" stroke="#6C5CE7" strokeWidth={1.5} />
      ))}
      {pontos.map((p, i) => (p.valor == null ? null : (
        <circle key={p.edicao} cx={x(i)} cy={y(p.valor)} r={2} fill="#6C5CE7" />
      )))}
    </svg>
  );
}

/** Formata um número de série com a precisão do primeiro ponto com valor. */
export function formatoDaSerie(casas: number | null | undefined, unidade?: string | null) {
  return (v: number) => `${numeroBR(v, casas ?? 0)}${unidade === "%" ? "%" : ""}`;
}

/**
 * Escolha de UM indicador (botões de opção): o indisponível fica desabilitado e diz
 * POR QUÊ, à vista (não só no `title`, que não existe no celular).
 */
export function EscolhaIndicador({ indicadores, selecionado, aoEscolher, bloqueio, legenda }: {
  indicadores: IndicadorAnalise[];
  selecionado: string | null;
  aoEscolher: (chave: string) => void;
  /** Motivo extra de bloqueio (ex.: na relação, o ICA só existe para a rede). */
  bloqueio?: (indicador: IndicadorAnalise) => string | null;
  legenda: string;
}) {
  const nome = useId();
  return (
    <fieldset className="min-w-0">
      <legend className="mb-2 text-xs font-semibold text-zinc-600 dark:text-zinc-300">{legenda}</legend>
      <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2 lg:grid-cols-3">
        {indicadores.map((ind) => {
          const motivo = !ind.disponivel ? textoIndisponivel(ind) : bloqueio?.(ind) ?? null;
          const ativo = selecionado === ind.chave;
          const idMotivo = `${nome}-${ind.chave}-motivo`;
          return (
            <label
              key={ind.chave}
              className={`flex min-w-0 cursor-pointer items-start gap-2.5 rounded-2xl border p-3 text-sm transition-colors ${
                motivo
                  ? "cursor-not-allowed border-dashed border-zinc-200 text-zinc-500 dark:border-zinc-800 dark:text-zinc-400"
                  : ativo
                    ? "border-indigo-400 bg-indigo-50/70 ring-1 ring-indigo-400 dark:border-indigo-500/50 dark:bg-indigo-500/10"
                    : "border-zinc-200 bg-white hover:border-indigo-300 dark:border-zinc-800 dark:bg-zinc-900 dark:hover:border-indigo-500/40"
              }`}
            >
              <input
                type="radio"
                name={nome}
                value={ind.chave}
                checked={ativo}
                disabled={motivo != null}
                aria-describedby={motivo ? idMotivo : undefined}
                onChange={() => aoEscolher(ind.chave)}
                className="mt-1 shrink-0 accent-indigo-600"
              />
              <span className="min-w-0 break-words">
                <span className="block font-semibold text-zinc-800 dark:text-zinc-100">{ind.nome}</span>
                <span className="block text-xs text-zinc-500 dark:text-zinc-400">{ind.orgao}</span>
                {motivo && <span id={idMotivo} className="mt-0.5 block text-xs text-amber-700 dark:text-amber-400">{motivo}</span>}
              </span>
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}

// --- Natureza do número: o selo ÚNICO -------------------------------------------------

/** De onde vem o que está na tela. Os sinais do diagnóstico usam oficial/calculado/
 *  plataforma/dados; "hipotese" marca a leitura exploratória (o selo diz "Exploratório" — as
 *  quatro naturezas do desenho: Oficial · Plataforma · Calculado pelo Constela · Exploratório)
 *  e "estimativa" a Estimativa Constela (que nunca é o indicador oficial). */
export type NaturezaSelo = "oficial" | "plataforma" | "calculado" | "hipotese" | "estimativa" | "dados";

/** Tons do `Badge` da v2 (contraste AA nos dois temas, já conferido no ui.tsx). A natureza é
 *  NEUTRA quanto ao resultado: o verde e o vermelho ficam para "favorável"/"atenção" — um
 *  selo "Oficial" verde pareceria dizer que o resultado é bom. */
const SELOS: Record<NaturezaSelo, { texto: string; tom: "neutro" | "destaque" | "alerta" | "info" }> = {
  oficial: { texto: "Oficial", tom: "destaque" },
  plataforma: { texto: "Plataforma", tom: "info" },
  calculado: { texto: "Calculado pelo Constela", tom: "neutro" },
  hipotese: { texto: "Exploratório", tom: "alerta" },
  estimativa: { texto: "Estimativa Constela", tom: "neutro" },
  dados: { texto: "Dados", tom: "neutro" },
};

/** O selo de natureza (texto por extenso; a cor nunca é o único código). */
export function SeloNatureza({ natureza }: { natureza: NaturezaSelo | string }) {
  const selo = SELOS[natureza as NaturezaSelo] ?? { texto: natureza, tom: "neutro" as const };
  return (
    <span className="inline-flex shrink-0" data-natureza={natureza}>
      <Badge tom={selo.tom}>{selo.texto}</Badge>
    </span>
  );
}

/**
 * A faixa FIXA de toda leitura que cruza avaliação oficial com plataforma: é hipótese
 * calculada pelo Constela, não causa e efeito. `children` diz a comparabilidade (anos).
 */
export function FaixaHipotese({ children, testId = "faixa-hipotese" }: { children?: ReactNode; testId?: string }) {
  return (
    <div className="flex items-start gap-2.5 rounded-2xl border border-ouro-200 bg-ouro-50 px-4 py-3 text-xs text-zinc-800 dark:border-ouro-400/25 dark:bg-ouro-400/10 dark:text-zinc-100"
         data-testid={testId}>
      <FlaskConical size={16} aria-hidden className="mt-0.5 shrink-0 text-ouro-700 dark:text-ouro-300" />
      <div className="min-w-0 space-y-1 break-words">
        <p className="text-sm font-semibold">Hipótese exploratória — calculada pelo Constela; não é causa e efeito.</p>
        {children}
      </div>
    </div>
  );
}

/** "▲ acima da rede" — o símbolo é decorativo; o texto diz a posição (calculada pelo Constela). */
export function PosicaoNaRede({ posicao, detalhe }: { posicao: PosicaoRede; detalhe?: string | null }) {
  const cor = posicao === "acima"
    ? "text-emerald-700 dark:text-emerald-300"
    : posicao === "abaixo" ? "text-amber-800 dark:text-amber-300" : "text-zinc-600 dark:text-zinc-300";
  return (
    <span className={`inline-flex flex-wrap items-baseline gap-x-1 font-medium ${cor}`} data-posicao={posicao}>
      <span aria-hidden>{SIMBOLO_POSICAO[posicao]}</span>
      <span>{ROTULO_POSICAO[posicao]}</span>
      {detalhe && <span className="font-normal text-zinc-600 dark:text-zinc-400">{detalhe}</span>}
    </span>
  );
}

/** Seletor rotulado (rótulo visível ligado ao campo), largura total no celular. */
export function Seletor({ rotulo, valor, aoMudar, children, desabilitado }: {
  rotulo: string;
  valor: string;
  aoMudar: (v: string) => void;
  children: ReactNode;
  desabilitado?: boolean;
}) {
  const id = useId();
  return (
    <div className="flex min-w-0 flex-col gap-1.5 text-xs text-zinc-600 dark:text-zinc-300">
      <label htmlFor={id} className="font-semibold">{rotulo}</label>
      {/* O mesmo campo do resto do app (estiloInput), mais baixo: cabe na linha de filtros. */}
      <select
        id={id}
        value={valor}
        disabled={desabilitado}
        onChange={(e) => aoMudar(e.target.value)}
        className={`${estiloInput} min-w-0 max-w-full py-2 disabled:opacity-60 sm:w-auto`}
      >
        {children}
      </select>
    </div>
  );
}
