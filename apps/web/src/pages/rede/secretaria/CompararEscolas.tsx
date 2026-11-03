/**
 * ESCOLAS — `/rede/escolas` (Secretaria e global; guarda `RotaRede`). DESENHO3 §3. (O arquivo
 * guarda o nome antigo, "Comparar escolas": a rota, os links e as importações seguem valendo.)
 *
 * TODAS as escolas da rede numa tabela só, em ordem alfabética (não é ranking), com o uso do
 * Elefante e do Matific no período e na série DESTA tela (padrão: ano letivo, do 1º ao 5º ano; a
 * escolha fica na URL, `?periodo=&serie=`):
 *  - o nome leva à FICHA da escola (`/rede/escolas/:id`), levando junto a consulta desta lista
 *    (o "‹ Escolas" da ficha volta ao mesmo recorte); a escola INATIVA no cadastro leva o selo
 *    "inativa no cadastro" (pelo painel da rede, `/redes/{id}/dashboard` — a mesma leitura, com
 *    cache curto, do Panorama e da ficha; sem o painel, nenhum selo inventado);
 *  - a coluna "Comparar" marca de 2 a 4 escolas (na URL, `?comparar=1,2,3`) para a comparação
 *    LADO A LADO, logo abaixo da tabela: uma coluna por escola com o Elefante e o Matific no
 *    período (a mesma leitura da tabela) e, separadas pela frase dos períodos diferentes, as
 *    avaliações externas (`/escolas/{id}/analise`: uma leitura por escola marcada, só quando há
 *    escolas marcadas). Plataformas e avaliações nunca na mesma tabela (medidas e períodos
 *    diferentes). Nas avaliações, NUNCA duas edições na mesma linha: a edição de cada linha é a
 *    mais recente com resultado entre as escolas marcadas (`edicaoDeReferencia`); a escola cujo
 *    último resultado é de edição anterior não mostra o número, a rede nem a meta — a célula diz,
 *    por extenso, de quando é o último oficial dela (que fica na ficha da escola).
 *
 * Se a leitura do uso (as plataformas) falhar, as escolas continuam listadas pelo cadastro (o
 * painel da rede), com o link para a ficha e "o uso no período não pôde ser carregado" — sem
 * comparação (ela depende do uso).
 *
 * A comparação de TODAS as escolas nas avaliações externas mora na tela Avaliações externas
 * (`/rede/avaliacoes-externas`); a pontuação do Constela, no Ranking da Rede — os dois a um link.
 */
import { ClipboardCheck, Columns3, ListOrdered, MonitorSmartphone, X } from "lucide-react";
import { useId, useRef, type ReactNode, type RefObject } from "react";
import { Link, useLocation, useSearchParams } from "react-router-dom";

import { TabelaRolavel } from "../../../components/TabelaRolavel";
import { Badge, Card, Carregando, IconePastel, Mensagem } from "../../../components/ui";
import { rotuloDasPlataformas, useModulos } from "../../../hooks/useModulos";
import type { ApiError } from "../../../lib/api";
import { OPCOES_ANALISE_DA_ESCOLA, urlAnaliseNoAnoLetivo } from "../../analise/AnaliseDaEscola";
import DetalhesEFontes, { Recolhivel, type ItemDetalhe } from "../../analise/DetalhesFonte";
import { TEXTO_SUPRESSAO_PADRAO } from "../../analise/Plataformas";
import {
  Coleta, SeloInativaNoCadastro, TabelaEscolasNoPeriodo, Valor, pct, porqueCaixaTravada, semDadoDo,
  type LinkDaEscola,
} from "../../analise/PlataformasRede";
import { CLASSE_LINK } from "../../analise/RelatoriosRede";
import {
  FiltrosAplicados, SeloNatureza, TD, TH, ValorOficial, useApiExata, usePlataformasDaRede,
} from "../../analise/comum";
import {
  ROTULO_SITUACAO, decimal, legendaSemRegistro, porNome, rotuloComponente, rotuloEtapa, rotuloSerie, valorComUnidade,
} from "../../analise/formato";
import type {
  EscolaPlataformas, MetricasElefante, MetricasMatific, PontoAnalise, RespostaAnaliseEscola, RespostaPlataformas,
} from "../../analise/tipos";
import type { DashboardRede } from "../comum";
import { conclusaoComparacaoPlataformas } from "./conclusoes";
import type { EstadoDaFicha } from "./FichaEscolaRede";
import { FRASE_PLATAFORMA, METRICAS_ELEFANTE, METRICAS_MATIFIC, textoSimples } from "./oQueMede";
import {
  AvisoOutraRede, CINZA, CabecalhoDaPagina, CampoPeriodo, CampoSerie, ComoLer, EstadoDaLeitura, FraseSeparacao,
  LinkVer, PaginaDaRede, TITULO_SECAO, type ContextoDaPagina,
} from "./pecas";
import {
  anoDaJanela, periodoParaUrl, useDashboardDaRede, useNomeDaRede, usePeriodoDaPagina, useSerieDaPagina,
} from "./useRedeDaPagina";

/** No máximo quantas escolas lado a lado (mais que isso não cabe numa leitura). */
export const LIMITE_COMPARAR = 4;

const PRESA = "presa-esquerda-celular"; // index.css: a 1ª coluna fica presa no celular

/** As escolas de `?comparar=1,2,3`: números inteiros, sem repetir, na ordem da URL. */
export function idsDaConsulta(valor: string | null): number[] {
  const ids: number[] = [];
  for (const parte of (valor ?? "").split(",")) {
    const t = parte.trim();
    if (!/^\d+$/.test(t)) continue;
    const n = Number(t);
    if (n > 0 && !ids.includes(n)) ids.push(n);
  }
  return ids;
}

// --- A legenda da tabela ----------------------------------------------------------------------

/** Com uma série escolhida (`?serie=`), a coluna "Alunos" traz só os alunos dessa série. */
function LegendaColunasPlataformas({ p, serie }: { p: RespostaPlataformas; serie: number | null }) {
  const linha = (rotulo: string, texto: string) => (
    <div key={rotulo}>
      <dt className="font-semibold text-zinc-800 dark:text-zinc-100">{rotulo}</dt>
      <dd>{texto}</dd>
    </div>
  );
  const coleta = "Se a coleta da plataforma cobre o período inteiro (“coleta em dia”) ou parou antes (“coleta "
    + "parcial”, com a data até onde os números valem).";
  return (
    <Recolhivel titulo="O que significa cada coluna" testId="legenda-colunas-plataformas">
      <dl className="space-y-2">
        {linha("Escola", "O nome leva à ficha da escola: cadastro, uso do Constela, evolução no ano letivo e "
          + "avaliações externas. “Inativa no cadastro”: a situação do cadastro da escola — não diz nada sobre uso.")}
        {linha("Comparar", `Marque de 2 a ${LIMITE_COMPARAR} escolas para vê-las lado a lado, abaixo da tabela.`)}
        {linha("Alunos", serie != null
          ? `Alunos matriculados no ${rotuloSerie(serie)} na escola.`
          : "Alunos matriculados do 1º ao 5º ano na escola.")}
        {p.modulos.elefante && <>
          {linha("Elefante — Participação", METRICAS_ELEFANTE[0].oQueMede)}
          {linha("Elefante — Livros novos/aluno", METRICAS_ELEFANTE[1].oQueMede)}
          {linha("Elefante — Min/aluno", METRICAS_ELEFANTE[2].oQueMede)}
          {linha("Elefante — Acerto", METRICAS_ELEFANTE[3].oQueMede)}
          {linha("Elefante — Coleta", coleta)}
        </>}
        {p.modulos.matific && <>
          {linha("Matific — Participação", METRICAS_MATIFIC[0].oQueMede)}
          {linha("Matific — Atividades/aluno", METRICAS_MATIFIC[1].oQueMede)}
          {linha("Matific — Desempenho (0–5)", METRICAS_MATIFIC[3].oQueMede)}
          {linha("Matific — Coleta", coleta)}
        </>}
      </dl>
    </Recolhivel>
  );
}

// --- Lado a lado: Elefante e Matific ------------------------------------------------------------

type Plat = "elefante" | "matific";
type Bloco = MetricasElefante | MetricasMatific;

/** Uma linha de métrica da comparação: o rótulo, o campo (o "protegido" em complemento) e o valor. */
interface LinhaMetrica {
  rotulo: string;
  campo: string;
  valor: (b: Bloco) => string | null;
}

const LINHAS_ELEFANTE: LinhaMetrica[] = [
  { rotulo: "Participação", campo: "participacao_pct", valor: (b) => pct(b.participacao_pct) },
  { rotulo: "Livros novos por aluno", campo: "livros_por_aluno",
    valor: (b) => decimal((b as MetricasElefante).livros_por_aluno) },
  { rotulo: "Minutos de leitura por aluno", campo: "minutos_por_aluno",
    valor: (b) => decimal((b as MetricasElefante).minutos_por_aluno, 1) },
];
const LINHAS_MATIFIC: LinhaMetrica[] = [
  { rotulo: "Participação", campo: "participacao_pct", valor: (b) => pct(b.participacao_pct) },
  { rotulo: "Atividades por aluno", campo: "atividades_por_aluno",
    valor: (b) => decimal((b as MetricasMatific).atividades_por_aluno) },
  { rotulo: "Desempenho (0 a 5)", campo: "desempenho_medio", valor: (b) => decimal((b as MetricasMatific).desempenho_medio) },
];

/** Uma célula de plataforma: protegido e sem dado por extenso (o porquê na 1ª linha), nunca 0. */
function CelulaPlataforma({ e, p, linha, primeira }: { e: EscolaPlataformas; p: Plat; linha: LinhaMetrica; primeira: boolean }) {
  const discreto = `text-[11px] ${CINZA}`;
  if (e.suprimido) {
    return <span className={discreto}>{primeira ? `Protegido: ${e.texto_supressao ?? TEXTO_SUPRESSAO_PADRAO}.` : "protegido"}</span>;
  }
  const sem = semDadoDo(e[p], e.cobertura?.[p]);
  if (sem || !e[p]) return <span className={discreto}>{primeira ? `Sem dado: ${sem ?? "sem dado no período"}.` : "sem dado"}</span>;
  const bloco = e[p]!;
  return <Valor texto={linha.valor(bloco)} campo={linha.campo} bloco={bloco} />;
}

function GrupoPlataforma({ titulo, p, linhas, escolas }: {
  titulo: string; p: Plat; linhas: LinhaMetrica[]; escolas: EscolaPlataformas[];
}) {
  return (
    <tbody>
      <tr className="bg-zinc-50 dark:bg-zinc-800/40">
        <th scope="rowgroup" colSpan={escolas.length + 1} className={`${TD} text-left font-semibold`}>{titulo}</th>
      </tr>
      {linhas.map((l, i) => (
        <tr key={l.rotulo} className="border-b border-zinc-100 align-top dark:border-zinc-800/60">
          <th scope="row" className={`${TD} ${PRESA} min-w-[9rem] text-left font-medium`}>{l.rotulo}</th>
          {escolas.map((e) => (
            <td key={e.escola_id} className={TD}><CelulaPlataforma e={e} p={p} linha={l} primeira={i === 0} /></td>
          ))}
        </tr>
      ))}
      <tr className="border-b border-zinc-100 align-top dark:border-zinc-800/60">
        <th scope="row" className={`${TD} ${PRESA} min-w-[9rem] text-left font-medium`}>Coleta</th>
        {escolas.map((e) => (
          <td key={e.escola_id} className={TD}>
            {e.suprimido ? <span className={`text-[11px] ${CINZA}`}>protegido</span> : <Coleta e={e} p={p} />}
          </td>
        ))}
      </tr>
    </tbody>
  );
}

/** O cabeçalho de cada coluna: o nome (leva à ficha), o selo da inativa no cadastro e "Tirar"
 *  (sai da comparação). */
function CabecalhoEscolas({ escolas, linkDaEscola, aoTirar, primeira, inativas }: {
  escolas: { escola_id: number; nome: string }[];
  linkDaEscola: (id: number) => LinkDaEscola;
  aoTirar: (id: number) => void;
  primeira: string;
  inativas: ReadonlySet<number>;
}) {
  return (
    <thead>
      <tr className={`border-b border-zinc-200 align-bottom dark:border-zinc-800 ${CINZA}`}>
        <th className={`${TH} ${PRESA}`} scope="col">{primeira}</th>
        {escolas.map((e) => {
          const link = linkDaEscola(e.escola_id);
          return (
            <th key={e.escola_id} className={`${TH} min-w-[9rem]`} scope="col">
              <span className="flex items-start justify-between gap-1">
                <span className="min-w-0">
                  <Link to={link.para} state={link.estado}
                        className="break-words text-indigo-700 underline-offset-2 hover:underline dark:text-indigo-300">
                    {e.nome}
                  </Link>
                  {inativas.has(e.escola_id) && <span className="mt-0.5 block font-normal"><SeloInativaNoCadastro /></span>}
                </span>
                <button type="button" onClick={() => aoTirar(e.escola_id)}
                        className="-mr-1 -mt-1 grid h-8 w-8 shrink-0 place-items-center rounded-lg text-zinc-500 hover:bg-zinc-100 hover:text-zinc-800 dark:hover:bg-zinc-800 dark:hover:text-zinc-100"
                        aria-label={`Tirar ${e.nome} da comparação`} title="Tirar da comparação">
                  <X size={14} aria-hidden />
                </button>
              </span>
            </th>
          );
        })}
      </tr>
    </thead>
  );
}

// --- Lado a lado: avaliações externas -----------------------------------------------------------

const ORDEM_INDICADOR = ["iee", "ideb", "saresp", "saeb"];
const ORDEM_ETAPA = ["anos_iniciais", "5_ano", "2_ano"];
const ORDEM_COMPONENTE = ["lp", "mt"];
/** O nome CURTO (o da análise pode ser longo: "Índice de Excelência…"). */
const NOME_CURTO: Record<string, string> = { iee: "IEE", ideb: "Ideb", saresp: "SARESP", saeb: "Saeb" };
const posicaoEm = (lista: string[], v: string | null) => {
  const i = v == null ? -1 : lista.indexOf(v);
  return i < 0 ? lista.length : i;
};

/** Uma linha das avaliações: um indicador num recorte (etapa × componente). */
interface LinhaOficial {
  chave: string;
  indicador: string;
  etapa: string | null;
  componente: string | null;
  rotulo: string;
}

/** O último resultado oficial DA escola numa linha, com a rede municipal na mesma edição. */
interface ResultadoOficial {
  ponto: PontoAnalise;
  unidade: string | null;
  rede: PontoAnalise | null;
}

/** Os resultados de uma escola, por linha (a chave da linha). */
type ResultadosDaEscola = Map<string, { linha: LinhaOficial; r: ResultadoOficial }>;

/**
 * O último resultado oficial de cada indicador da escola (a série DELA, a edição mais nova com
 * número), com a rede municipal na MESMA edição como referência. O indicador que não existe por
 * escola (o ICA) não tem série da escola: não entra.
 */
export function ultimosOficiais(d: RespostaAnaliseEscola): ResultadosDaEscola {
  const mapa: ResultadosDaEscola = new Map();
  for (const ind of d.indicadores) {
    const unidade = ind.unidade ?? (ind.chave === "ica" ? "%" : null);
    for (const s of ind.series.filter((x) => x.papel === "principal")) {
      const ponto = [...s.pontos].filter((p) => p.valor != null).sort((a, b) => b.edicao - a.edicao)[0];
      if (!ponto) continue;
      const etapa = s.etapa ?? null;
      const componente = s.componente ?? null;
      const chave = `${ind.chave}|${etapa ?? ""}|${componente ?? ""}`;
      const ref = ind.series.find((r) => r.papel === "referencia" && r.abrangencia === "rede"
        && (r.etapa ?? null) === etapa && (r.componente ?? null) === componente);
      const rede = ref?.pontos.find((p) => p.edicao === ponto.edicao && p.valor != null) ?? null;
      const rotulo = `${NOME_CURTO[ind.chave] ?? ind.nome}${etapa && etapa !== "anos_iniciais" ? ` ${rotuloEtapa(etapa)}` : ""}`
        + `${componente ? ` · ${rotuloComponente(componente)}` : ""}`;
      mapa.set(chave, { linha: { chave, indicador: ind.chave, etapa, componente, rotulo }, r: { ponto, unidade, rede } });
    }
  }
  return mapa;
}

/**
 * A edição de REFERÊNCIA de uma linha (indicador × etapa × componente): a MAIS RECENTE com
 * resultado entre as escolas mostradas — a regra de não misturar edições, a mesma da tabela de
 * todas as escolas das Avaliações externas. Sem resultado em escola nenhuma, null.
 */
export function edicaoDeReferencia(resultados: ResultadosDaEscola[], chave: string): number | null {
  const edicoes = resultados.flatMap((m) => {
    const v = m.get(chave);
    return v ? [v.r.ponto.edicao] : [];
  });
  return edicoes.length ? Math.max(...edicoes) : null;
}

/** A escola cujo último resultado é de edição ANTERIOR à da linha: nem o número, nem a rede, nem a
 *  meta (seriam dois períodos lado a lado) — por extenso, de quando é o último oficial dela, que
 *  fica na ficha da escola. */
function CelulaEdicaoAnterior({ referencia, edicao, link }: { referencia: number; edicao: number; link: LinkDaEscola }) {
  return (
    <p className={`min-w-[8rem] text-[11px] leading-snug ${CINZA}`} data-edicao-anterior>
      sem resultado em {referencia} — o último oficial desta escola é de {edicao} (
      <Link to={link.para} state={link.estado}
            className="text-indigo-700 underline underline-offset-2 dark:text-indigo-300">na ficha da escola</Link>)
    </p>
  );
}

function CelulaOficial({ r }: { r: ResultadoOficial }) {
  const { ponto: p, unidade, rede } = r;
  return (
    <div className="min-w-[8rem] space-y-1">
      <p className="flex flex-wrap items-center gap-1.5">
        <span className="text-sm font-semibold tabular-nums text-zinc-900 dark:text-white">
          <ValorOficial {...p} unidade={unidade} traduzir={textoSimples} />
        </span>
        <span className="rounded-md bg-zinc-100 px-1.5 py-0.5 text-[11px] font-semibold text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">
          {p.edicao}
        </span>
        {p.instavel
          ? <Badge tom="alerta">média instável</Badge>
          : p.tps_zero && <Badge tom="alerta">calculado com médias instáveis</Badge>}
      </p>
      {rede?.valor != null && (
        <p className={`text-[11px] ${CINZA}`}>
          rede municipal: {valorComUnidade(rede.valor, rede.casas, unidade, rede.operador)}
        </p>
      )}
      {p.meta != null && (
        <p className={`text-[11px] ${CINZA}`}>
          meta {valorComUnidade(p.meta, p.meta_casas ?? p.casas, unidade, p.operador_meta)}
          {p.situacao_meta ? ` · ${ROTULO_SITUACAO[p.situacao_meta]}` : ""}
        </p>
      )}
    </div>
  );
}

/** Uma leitura da análise de uma escola (o `useApiExata`): carregando, erro ou os dados. */
interface LeituraDaEscola {
  dados: RespostaAnaliseEscola | null;
  erro: ApiError | null;
}

/** A célula sem resultado: carregando, erro, ou a ausência por extenso (nunca 0). */
function CelulaSemResultado({ leitura, semInep }: { leitura: LeituraDaEscola; semInep: boolean }) {
  if (!leitura.dados) {
    return (
      <span className={`text-[11px] ${CINZA}`}>
        {leitura.erro ? `não foi possível carregar: ${leitura.erro.message}` : "carregando…"}
      </span>
    );
  }
  return <ValorOficial valor={null} casas={null}
                       texto_ausencia={semInep ? "sem código INEP no cadastro" : "sem resultado oficial"} />;
}

/** As 4 leituras possíveis (uma por escola marcada, nas mesmas posições a cada render). */
function useAnalisesDasEscolas(ids: number[]): LeituraDaEscola[] {
  const r0 = useApiExata<RespostaAnaliseEscola>(urlAnaliseNoAnoLetivo(ids[0]), OPCOES_ANALISE_DA_ESCOLA);
  const r1 = useApiExata<RespostaAnaliseEscola>(urlAnaliseNoAnoLetivo(ids[1]), OPCOES_ANALISE_DA_ESCOLA);
  const r2 = useApiExata<RespostaAnaliseEscola>(urlAnaliseNoAnoLetivo(ids[2]), OPCOES_ANALISE_DA_ESCOLA);
  const r3 = useApiExata<RespostaAnaliseEscola>(urlAnaliseNoAnoLetivo(ids[3]), OPCOES_ANALISE_DA_ESCOLA);
  return [r0, r1, r2, r3].slice(0, ids.length).map((r, i) => ({
    // Só a resposta DESTA escola (a leitura de outra posição nunca aparece na coluna errada).
    dados: r.dados && r.dados.escola.id === ids[i] ? r.dados : null,
    erro: r.erro,
  }));
}

function AvaliacoesLadoALado({ escolas, leituras, resultados, linkDaEscola, aoTirar, inativas }: {
  escolas: EscolaPlataformas[];
  leituras: LeituraDaEscola[];
  resultados: ResultadosDaEscola[];
  linkDaEscola: (id: number) => LinkDaEscola;
  aoTirar: (id: number) => void;
  inativas: ReadonlySet<number>;
}) {
  const linhas = [...new Map(resultados.flatMap((m) => [...m.values()].map((v) => [v.linha.chave, v.linha]))).values()]
    .sort((a, b) => posicaoEm(ORDEM_INDICADOR, a.indicador) - posicaoEm(ORDEM_INDICADOR, b.indicador)
      || posicaoEm(ORDEM_ETAPA, a.etapa) - posicaoEm(ORDEM_ETAPA, b.etapa)
      || posicaoEm(ORDEM_COMPONENTE, a.componente) - posicaoEm(ORDEM_COMPONENTE, b.componente)
      || a.chave.localeCompare(b.chave));
  const semInep = leituras.map((l) => l.dados?.escola.pendencia === "sem_codigo_inep");
  // Uma edição por linha: só os resultados NA edição de referência aparecem (e entram na legenda e
  // nas fontes); o de edição anterior vira a frase por extenso.
  const referencia = new Map(linhas.map((l) => [l.chave, edicaoDeReferencia(resultados, l.chave)]));
  const naReferencia = (v: { linha: LinhaOficial; r: ResultadoOficial }) => v.r.ponto.edicao === referencia.get(v.linha.chave);
  const pontos = resultados.flatMap((m) => [...m.values()].filter(naReferencia).map((v) => v.r.ponto));
  const comAnterior = resultados.some((m) => [...m.values()].some((v) => !naReferencia(v)));
  const semRegistro = legendaSemRegistro(pontos);
  const comInstavel = pontos.some((p) => p.instavel || p.tps_zero);
  const itensFonte: ItemDetalhe[] = escolas.flatMap((e, i) => [...resultados[i].values()].filter(naReferencia).map((v) => ({
    rotulo: `${e.nome} — ${v.linha.rotulo} (${v.r.ponto.edicao})`, fonte_id: v.r.ponto.fonte_id,
  })));
  const fontes = Object.assign({}, ...leituras.map((l) => l.dados?.fontes ?? {}));
  return (
    <div className="space-y-2" data-testid="comparacao-avaliacoes-bloco">
      <TabelaRolavel rotulo="Avaliações externas lado a lado: tabela completa">
        <table className="w-full text-xs" data-testid="comparacao-avaliacoes">
          <caption className="sr-only">
            Resultado oficial de cada avaliação externa, uma coluna por escola; em cada linha, a edição mais recente
            entre as escolas comparadas
          </caption>
          <CabecalhoEscolas escolas={escolas} linkDaEscola={linkDaEscola} aoTirar={aoTirar} primeira="Avaliação"
                            inativas={inativas} />
          <tbody>
            {linhas.length === 0 ? (
              <tr className="align-top">
                <th scope="row" className={`${TD} ${PRESA} min-w-[9rem] text-left font-medium`}>Resultado oficial</th>
                {escolas.map((e, i) => (
                  <td key={e.escola_id} className={TD}><CelulaSemResultado leitura={leituras[i]} semInep={semInep[i]} /></td>
                ))}
              </tr>
            ) : linhas.map((l) => {
              const ref = referencia.get(l.chave) ?? null;
              return (
                <tr key={l.chave} className="border-b border-zinc-100 align-top last:border-0 dark:border-zinc-800/60"
                    data-testid={`linha-oficial-${l.chave}`}>
                  <th scope="row" className={`${TD} ${PRESA} min-w-[9rem] text-left font-medium`}>
                    {l.rotulo}
                    {ref != null && <span className={`block text-[11px] font-normal ${CINZA}`}>edição {ref}</span>}
                  </th>
                  {escolas.map((e, i) => {
                    const v = resultados[i].get(l.chave);
                    return (
                      <td key={e.escola_id} className={TD}>
                        {!v ? <CelulaSemResultado leitura={leituras[i]} semInep={semInep[i]} />
                          : ref != null && v.r.ponto.edicao < ref
                            ? <CelulaEdicaoAnterior referencia={ref} edicao={v.r.ponto.edicao} link={linkDaEscola(e.escola_id)} />
                            : <CelulaOficial r={v.r} />}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </TabelaRolavel>
      <div className={`space-y-1 text-xs ${CINZA}`} data-testid="legenda-comparacao-avaliacoes">
        <p>
          Cada linha usa uma edição só: a mais recente com resultado entre as escolas comparadas (o ano aparece abaixo
          do nome da avaliação e em cada número). Junto, a rede municipal na mesma edição e a meta oficial, quando
          existe. Sem número, a célula diz por quê — nunca 0.
        </p>
        {comAnterior && (
          <p data-testid="legenda-edicao-anterior">
            A escola sem resultado na edição da linha não mostra o número de uma edição anterior (seriam períodos
            diferentes lado a lado): a célula diz de quando é o último resultado oficial dela, que fica na ficha da escola.
          </p>
        )}
        {comInstavel && <p>Média instável: poucos alunos fizeram a prova — o número vale, mas compare com cuidado.</p>}
        {semRegistro && <p>{textoSimples(semRegistro)}</p>}
      </div>
      {itensFonte.length > 0 && <DetalhesEFontes itens={itensFonte} fontes={fontes} testId="detalhes-fontes-comparacao" />}
    </div>
  );
}

// --- Lado a lado: o bloco ------------------------------------------------------------------------

function ComparacaoLadoALado({ p, ids, serie, nomePlataformas, linkDaEscola, aoTirar, idTitulo, refTitulo, inativas }: {
  p: RespostaPlataformas;
  ids: number[];
  serie: number | null;
  nomePlataformas: string;
  linkDaEscola: (id: number) => LinkDaEscola;
  aoTirar: (id: number) => void;
  idTitulo: string;
  refTitulo: RefObject<HTMLHeadingElement>;
  inativas: ReadonlySet<number>;
}) {
  // Ordem alfabética também aqui (não é ranking).
  const escolas = porNome(ids.map((id) => p.escolas.find((e) => e.escola_id === id))
    .filter((e): e is EscolaPlataformas => Boolean(e)));
  const leituras = useAnalisesDasEscolas(escolas.map((e) => e.escola_id));
  const resultados = leituras.map((l) => (l.dados ? ultimosOficiais(l.dados) : new Map() as ResultadosDaEscola));
  // A edição mais nova entre os resultados mostrados: a frase dos períodos diz "até {ano}".
  const edicoes = resultados.flatMap((m) => [...m.values()].map((v) => v.r.ponto.edicao));
  const ultimaEdicao = edicoes.length ? Math.max(...edicoes) : null;
  const recorte = `${p.janela.rotulo}${serie != null ? `, ${rotuloSerie(serie)}` : ", do 1º ao 5º ano"}`;
  const alunos = (e: EscolaPlataformas): ReactNode => (e.suprimido
    ? <span className={`text-[11px] ${CINZA}`}>protegido</span>
    : e.alunos == null ? <span className={`text-[11px] ${CINZA}`}>sem dado</span> : e.alunos.toLocaleString("pt-BR"));
  return (
    <section aria-labelledby={idTitulo} data-testid="comparacao-lado-a-lado">
      <Card className="space-y-4 p-5 sm:p-6">
        <h2 id={idTitulo} ref={refTitulo} tabIndex={-1} className={`${TITULO_SECAO} outline-none`}>
          <IconePastel icone={Columns3} tom="violeta" tamanho="sm" /> Escolas lado a lado
        </h2>
        <p className={`text-sm ${CINZA}`}>
          Uma coluna por escola, em ordem alfabética — não é ranking. O nome abre a ficha da escola.
        </p>

        <h3 className="flex items-center gap-2 text-[15px] font-semibold text-zinc-900 dark:text-white">
          <MonitorSmartphone size={16} aria-hidden className="shrink-0 text-sky-600 dark:text-sky-300" /> {nomePlataformas} no período
        </h3>
        <FiltrosAplicados testId="recorte-lado-a-lado">Vale aqui: {recorte} — o mesmo recorte da tabela.</FiltrosAplicados>
        <p className={`flex flex-wrap items-center gap-x-2 gap-y-1 text-xs ${CINZA}`}>
          <SeloNatureza natureza="plataforma" />
          <span className="min-w-0 break-words">{FRASE_PLATAFORMA}</span>
        </p>
        <TabelaRolavel rotulo="Plataformas lado a lado: tabela completa">
          <table className="w-full text-xs" data-testid="comparacao-plataformas">
            <caption className="sr-only">
              Uso do {nomePlataformas} no período, uma coluna por escola (ordem alfabética)
            </caption>
            <CabecalhoEscolas escolas={escolas} linkDaEscola={linkDaEscola} aoTirar={aoTirar} primeira="No período"
                              inativas={inativas} />
            <tbody>
              <tr className="border-b border-zinc-100 align-top dark:border-zinc-800/60">
                <th scope="row" className={`${TD} ${PRESA} min-w-[9rem] text-left font-medium`}>
                  Alunos ({serie != null ? rotuloSerie(serie) : "1º ao 5º ano"})
                </th>
                {escolas.map((e) => <td key={e.escola_id} className={TD}>{alunos(e)}</td>)}
              </tr>
            </tbody>
            {p.modulos.elefante && (
              <GrupoPlataforma titulo="Elefante Letrado (leitura)" p="elefante" linhas={LINHAS_ELEFANTE} escolas={escolas} />
            )}
            {p.modulos.matific && (
              <GrupoPlataforma titulo="Matific (matemática)" p="matific" linhas={LINHAS_MATIFIC} escolas={escolas} />
            )}
          </table>
        </TabelaRolavel>
        <p className={`text-xs ${CINZA}`}>
          Participação e médias por aluno: sobre os alunos que a plataforma conhece no período. “Protegido”: poucos
          alunos — os números não aparecem, para proteger as crianças. “Sem dado” não é zero.
        </p>

        <FraseSeparacao anoAvaliacao={ultimaEdicao} anoPlataforma={anoDaJanela(p.janela)} />

        <h3 className="flex items-center gap-2 text-[15px] font-semibold text-zinc-900 dark:text-white">
          <ClipboardCheck size={16} aria-hidden className="shrink-0 text-indigo-600 dark:text-indigo-300" /> Avaliações
          externas — a edição mais recente entre as escolas comparadas
        </h3>
        <p className={`flex flex-wrap items-center gap-x-2 gap-y-1 text-xs ${CINZA}`}>
          <SeloNatureza natureza="oficial" />
          <span className="min-w-0 break-words">
            resultados e metas oficiais. Não usam o período nem a série da tabela: cada avaliação tem a sua edição e a
            sua escala — compare cada escola com a rede e com ela mesma, não uma avaliação com outra.
          </span>
        </p>
        <AvaliacoesLadoALado escolas={escolas} leituras={leituras} resultados={resultados}
                             linkDaEscola={linkDaEscola} aoTirar={aoTirar} inativas={inativas} />
      </Card>
    </section>
  );
}

// --- A tela --------------------------------------------------------------------------------------

/** O resumo das marcadas, ACIMA da tabela (a comparação fica embaixo): quantas, quais e o atalho.
 *  Com o limite cheio, o porquê das caixas travadas fica ESCRITO aqui (`idPorqueTravada`): cada
 *  caixa travada aponta para este texto, e quem toca no celular o vê sem depender do `title`. */
function ResumoComparar({ marcadas, nomes, aoVer, aoLimpar, idPorqueTravada }: {
  marcadas: number[];
  nomes: string[];
  aoVer: () => void;
  aoLimpar: () => void;
  idPorqueTravada: string;
}) {
  const lista = nomes.length > 1 ? `${nomes.slice(0, -1).join(", ")} e ${nomes[nomes.length - 1]}` : nomes[0] ?? "";
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2 text-sm text-zinc-700 dark:text-zinc-200"
         data-testid="resumo-comparar">
      {/* Só a frase é anunciada (marcar uma caixa diz quantas e quais), não os botões. */}
      <span className="min-w-0 break-words" aria-live="polite">
        {marcadas.length === 0
          ? `Para comparar lado a lado, marque de 2 a ${LIMITE_COMPARAR} escolas na coluna “Comparar”.`
          : marcadas.length === 1
            ? `1 escola marcada (${lista}). Marque mais uma (até ${LIMITE_COMPARAR}) para comparar lado a lado.`
            : `${marcadas.length} escolas marcadas para comparar: ${lista}.`}
        {marcadas.length >= LIMITE_COMPARAR && (
          <>{" "}<span id={idPorqueTravada} data-testid="porque-caixa-travada">{porqueCaixaTravada(LIMITE_COMPARAR)}</span></>
        )}
      </span>
      {marcadas.length >= 2 && (
        <button type="button" onClick={aoVer} className={CLASSE_LINK}>Ver lado a lado</button>
      )}
      {marcadas.length > 0 && (
        <button type="button" onClick={aoLimpar} className={CLASSE_LINK}>Desmarcar todas</button>
      )}
    </div>
  );
}

/**
 * A leitura do USO (as plataformas) falhou: as escolas continuam listadas pelo CADASTRO (o painel
 * da rede), em ordem alfabética, com o link para a ficha e o uso por extenso — nunca "sem uso" nem
 * 0. Sem comparação lado a lado (ela depende do uso).
 */
function EscolasSemUso({ erro, painel, linkDaEscola, inativas }: {
  erro: ApiError;
  painel: { dados: DashboardRede | null; erro: ApiError | null };
  linkDaEscola: (id: number) => LinkDaEscola;
  inativas: ReadonlySet<number>;
}) {
  const escolas = painel.dados ? porNome(painel.dados.escolas) : [];
  return (
    <div className="space-y-3" data-testid="escolas-sem-uso">
      <Mensagem tipo="erro">Não foi possível carregar o uso das escolas no período: {erro.message}</Mensagem>
      {!painel.dados ? (
        painel.erro
          ? <p className={`text-sm ${CINZA}`}>A lista das escolas também não pôde ser carregada: {painel.erro.message}</p>
          : <Carregando texto="Carregando as escolas da rede..." />
      ) : escolas.length === 0 ? (
        <p className={`text-sm ${CINZA}`}>Nenhuma escola cadastrada na rede.</p>
      ) : (
        <>
          <p className={`text-sm ${CINZA}`}>
            As escolas da rede, pelo cadastro, em ordem alfabética — não é ranking. Sem o uso no período, não há
            comparação lado a lado; o nome abre a ficha da escola.
          </p>
          <ul className="divide-y divide-zinc-100 dark:divide-zinc-800/60">
            {escolas.map((c) => {
              const link = linkDaEscola(c.escola_id);
              return (
                <li key={c.escola_id} data-testid={`escola-sem-uso-${c.escola_id}`}
                    className="flex flex-wrap items-center gap-x-2 gap-y-1 py-2 text-sm">
                  <Link to={link.para} state={link.estado}
                        className="break-words font-medium text-indigo-700 underline-offset-2 hover:underline dark:text-indigo-300">
                    {c.nome}
                  </Link>
                  {inativas.has(c.escola_id) && <SeloInativaNoCadastro />}
                  <span className={`min-w-0 break-words text-xs ${CINZA}`}>o uso no período não pôde ser carregado</span>
                </li>
              );
            })}
          </ul>
        </>
      )}
    </div>
  );
}

function Escolas({ ctx }: { ctx: ContextoDaPagina }) {
  const [params, setParams] = useSearchParams();
  const { pathname, search } = useLocation();
  const [periodo, definirPeriodo] = usePeriodoDaPagina();
  const [serie, definirSerie] = useSerieDaPagina();
  const nomeRede = useNomeDaRede(ctx.redeId, ctx.nomeRede);
  const plataformas = usePlataformasDaRede(ctx.redeId, serie, periodo);
  // O cadastro de todas as escolas (a mesma leitura do Panorama e da ficha, com cache curto): o selo
  // da inativa e a lista quando o uso não pôde ser carregado.
  const painel = useDashboardDaRede(ctx.redeId);
  const inativas: ReadonlySet<number> = new Set((painel.dados?.escolas ?? [])
    .filter((c) => c.status !== "ativa").map((c) => c.escola_id));
  const { modulos } = useModulos();
  const p = plataformas.dados;
  const nomePlataformas = rotuloDasPlataformas(p
    ? [...(p.modulos.elefante ? ["leitura"] : []), ...(p.modulos.matific ? ["matematica"] : [])]
    : modulos);
  const idTitulo = useId();
  const idPorqueTravada = useId();
  const refTitulo = useRef<HTMLHeadingElement>(null);

  // As marcadas: as da URL que são escolas DESTA rede (nada de leitura de escola de outra rede).
  const marcadas = p
    ? idsDaConsulta(params.get("comparar")).filter((id) => p.escolas.some((e) => e.escola_id === id)).slice(0, LIMITE_COMPARAR)
    : [];
  function gravar(ids: number[]) {
    const prox = new URLSearchParams(params);
    if (ids.length) prox.set("comparar", ids.join(","));
    else prox.delete("comparar");
    setParams(prox, { replace: true });
  }
  function alternar(id: number) {
    if (marcadas.includes(id)) gravar(marcadas.filter((x) => x !== id));
    else if (marcadas.length < LIMITE_COMPARAR) gravar([...marcadas, id]);
  }
  function verLadoALado() {
    const titulo = refTitulo.current;
    titulo?.scrollIntoView?.({ behavior: "smooth", block: "start" });
    titulo?.focus({ preventScroll: true });
  }
  // A ficha leva o período desta lista e, no estado, a consulta inteira (o "‹ Escolas" volta a ela).
  const estadoFicha: EstadoDaFicha = { voltarLista: `${pathname}${search}` };
  const linkDaEscola = (id: number): LinkDaEscola => ({
    para: ctx.link(`/rede/escolas/${id}`, periodoParaUrl(periodo)),
    estado: estadoFicha,
  });
  const nomesMarcadas = p ? porNome(p.escolas.filter((e) => marcadas.includes(e.escola_id))).map((e) => e.nome) : [];

  return (
    <div className="min-w-0 space-y-5">
      <CabecalhoDaPagina
        titulo="Escolas"
        descricao={`Todas as escolas da rede, com o uso do ${nomePlataformas} no período. Abra a ficha de uma escola ou marque de 2 a ${LIMITE_COMPARAR} para comparar lado a lado.`}
        nomeRede={nomeRede}
        ctx={ctx}
      />
      <ComoLer titulo="Como ler" testId="como-comparar">
        <p>
          As escolas aparecem em ordem alfabética — não é ranking. O nome abre a ficha da escola (cadastro, uso do
          Constela, evolução no ano letivo e avaliações externas). Para comparar, marque de 2 a {LIMITE_COMPARAR} escolas
          na coluna “Comparar”: elas aparecem lado a lado logo abaixo da tabela.
        </p>
      </ComoLer>

      <Card className="space-y-4 p-5 sm:p-6">
        <h2 className={TITULO_SECAO}>
          <IconePastel icone={MonitorSmartphone} tom="azul" tamanho="sm" /> Todas as escolas — {nomePlataformas} no período
        </h2>
        <div className="flex flex-wrap items-end gap-3">
          <CampoPeriodo periodo={periodo} aoMudar={definirPeriodo} />
          <CampoSerie serie={serie} aoMudar={definirSerie} />
        </div>
        {!p && plataformas.erro ? (
          <EscolasSemUso erro={plataformas.erro} painel={painel} linkDaEscola={linkDaEscola} inativas={inativas} />
        ) : (
          <EstadoDaLeitura dados={p} erro={plataformas.erro} oQue="as escolas da rede">
            {(d) => (
              <>
                <p className="text-base font-semibold text-zinc-900 dark:text-white" data-testid="conclusao-escolas">
                  {conclusaoComparacaoPlataformas(d, serie)}
                </p>
                <FiltrosAplicados testId="recorte-escolas">
                  Vale aqui: período ({d.janela.rotulo}) e série ({serie != null ? rotuloSerie(serie) : "1º ao 5º ano"}).
                </FiltrosAplicados>
                <p className={`flex flex-wrap items-center gap-x-2 gap-y-1 text-xs ${CINZA}`} data-testid="natureza-plataformas">
                  <SeloNatureza natureza="plataforma" />
                  <span className="min-w-0 break-words">{FRASE_PLATAFORMA}</span>
                </p>
                <ResumoComparar marcadas={marcadas} nomes={nomesMarcadas} aoVer={verLadoALado} aoLimpar={() => gravar([])}
                                idPorqueTravada={idPorqueTravada} />
                <TabelaEscolasNoPeriodo dados={d} linkDaEscola={linkDaEscola} inativas={inativas}
                                        comparar={{ marcadas, limite: LIMITE_COMPARAR, aoAlternar: alternar, idPorqueTravada }} />
                <LegendaColunasPlataformas p={d} serie={serie} />
                <LinkVer para={ctx.link("/rede/plataformas", { ...periodoParaUrl(periodo), serie: serie == null ? null : String(serie) })}>
                  Ver o uso da rede no período
                </LinkVer>
              </>
            )}
          </EstadoDaLeitura>
        )}
      </Card>

      {p && marcadas.length >= 2 && (
        <ComparacaoLadoALado p={p} ids={marcadas} serie={serie} nomePlataformas={nomePlataformas}
                             linkDaEscola={linkDaEscola} aoTirar={alternar} idTitulo={idTitulo} refTitulo={refTitulo}
                             inativas={inativas} />
      )}

      <div className={`space-y-2 text-sm ${CINZA}`}>
        <p className="flex flex-wrap items-center gap-x-3 gap-y-2" data-testid="link-avaliacoes">
          <span className="min-w-0 break-words">
            Todas as escolas, na edição mais recente de cada avaliação, ficam em Avaliações externas.
          </span>
          <Link to={ctx.link("/rede/avaliacoes-externas")} className={CLASSE_LINK}>
            <ClipboardCheck size={15} aria-hidden /> Abrir as Avaliações externas
          </Link>
        </p>
        <p className="flex flex-wrap items-center gap-x-3 gap-y-2" data-testid="link-ranking">
          <span className="min-w-0 break-words">
            A pontuação do Constela (o índice das plataformas) e a ordem das escolas ficam no Ranking da Rede — é outra
            medida.
          </span>
          <Link to="/rede/ranking" className={CLASSE_LINK}>
            <ListOrdered size={15} aria-hidden /> Ranking da Rede (pontuação do Constela)
          </Link>
          <AvisoOutraRede ctx={ctx} tela="O Ranking da Rede" />
        </p>
      </div>
    </div>
  );
}

export default function CompararEscolas() {
  return (
    <PaginaDaRede titulo="Escolas">
      {(ctx) => <Escolas key={ctx.redeId} ctx={ctx} />}
    </PaginaDaRede>
  );
}
