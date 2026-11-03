/**
 * Série histórica e escolas numa edição — a parte de baixo da aba "Avaliações externas"
 * (era a aba "Por indicador"; `?ver=indicador` continua abrindo aqui, com os mesmos
 * parâmetros). UM indicador oficial por vez. Primeiro o indicador (o indisponível
 * fica desabilitado e diz por quê); depois as dimensões: etapa, componente,
 * abrangência (rede ou a escola do filtro), intervalo de anos — ou a visão "escolas
 * numa edição".
 *
 * Série histórica: gráfico (a meta tracejada; referência só quando `comparavel`), UMA
 * tabela (ano, valor, meta, diferença, situação — a ausência por extenso, nunca 0), os
 * avisos de comparabilidade uma vez só e "Detalhes e fontes" recolhido (a fonte de
 * cada ponto mostrado). Escolas numa edição: em ORDEM DE NOME (nunca ranking), as
 * instáveis marcadas.
 *
 * Número SEM registro oficial (gravado antes, pelo 1 clique): marcado com "*" na tabela,
 * com a legenda embaixo, e FORA do gráfico (o gráfico é só de número oficial).
 *
 * Os filtros vivem na URL (`?indicador=&etapa=&componente=&abrangencia=&de=&ate=&visao=&edicao=`).
 *
 * Também é o DETALHE de cada indicador em `/rede/avaliacoes-externas` (a tela principal da
 * Secretaria): lá os cartões de cima escolhem o indicador (`semEscolha`) e a escola vem de um
 * campo dentro do próprio detalhe (`campoEscola`), porque a tela não tem filtros no topo. No
 * modo `simples` (esse fluxo principal), as duas tabelas rolam dentro do cartão com o aviso
 * "Deslize…" (`TabelaRolavel`) e a 1ª coluna (Ano, Escola) presa no celular; com `linkDaEscola`,
 * o nome da escola numa edição leva à ficha dela. A área avançada (sem `simples`) não muda.
 */
import { BarChart3, LineChart } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { GraficoLinha, type PontoSerie, type SerieLinha } from "../../components/Grafico";
import { TabelaRolavel } from "../../components/TabelaRolavel";
import { Badge, Card, Carregando, IconePastel, Mensagem } from "../../components/ui";
import { Aviso, Nota } from "../rede/IdebBlocos";
import { textoSimples } from "../rede/secretaria/oQueMede";
import DetalhesEFontes, { type ItemDetalhe } from "./DetalhesFonte";
import {
  EscolhaIndicador, FiltrosAplicados, SemPontoNaEdicao, Seletor, SituacaoDaMeta, TD, TH, TITULO_CARTAO, ValorOficial,
  formatoDaSerie, useApiExata,
} from "./comum";
import {
  MARCA_SEM_REGISTRO, casasDaDiferenca, diferencaComUnidade, ehSemRegistro, faixaDoEixo, legendaSemRegistro,
  numeroBR, porNome, rotuloComponente, rotuloEtapa, textoIndisponivel, valorComUnidade,
} from "./formato";
import type {
  EscolaDaRede, IndicadorAnalise, PontoAnalise, RespostaIndicador, RespostaIndicadoresRede, SerieAnalise,
} from "./tipos";

// Paleta de séries da v2 (a mesma das abas da rede): a principal no violeta da marca, a
// meta em ardósia TRACEJADA e as referências na ordem da paleta (teal, âmbar, vermelho,
// azul). Todas com >= 3:1 sobre o branco e sobre o fundo escuro (o traço é um elemento
// gráfico); a legenda e a tabela dizem o nome (a cor não é o único código).
const COR_PRINCIPAL = "#6C5CE7";
const COR_META = "#64748B";
const CINZA = "text-zinc-600 dark:text-zinc-400";
const CORES_REFERENCIA = ["#0D9488", "#D97706", "#DC2626", "#0284C7"];

const numeroOuNull = (v: string | null): number | null => {
  if (v == null || v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
};

/** O valor com mais casas (outro arquivo), só para conferência em "Detalhes". */
function textoDetalhado(p: PontoAnalise, unidade: string): string | null {
  if (p.valor_detalhado == null || p.valor == null || p.valor_detalhado === p.valor) return null;
  const texto = p.casas_detalhe != null
    ? numeroBR(p.valor_detalhado, p.casas_detalhe)
    : p.valor_detalhado.toLocaleString("pt-BR", { maximumFractionDigits: 4 });
  return `com mais casas no arquivo, ${texto}${unidade === "%" ? "%" : ""}`;
}

/** A diferença resultado × meta na precisão que o backend diz (ou a menor dos dois lados). */
function diferenca(p: { diferenca_meta: number | null; diferenca_casas?: number | null; casas: number | null;
                        meta_casas?: number | null }, unidade: string): string {
  if (p.diferenca_meta == null) return "—";
  return diferencaComUnidade(p.diferenca_meta, p.diferenca_casas ?? casasDaDiferenca(p.casas, p.meta_casas), unidade);
}

/**
 * Os pontos do gráfico com a QUEBRA de escala: antes da edição que abre a escala nova
 * entra um ponto sem valor e fora do eixo — a lacuna do `GraficoLinha` (a linha não
 * liga os dois lados). Ausência é lacuna também: valor nulo nunca vira 0. O número sem
 * registro oficial também fica fora (o gráfico é só de número oficial; ele está na tabela).
 */
function pontosDoGrafico(
  pontos: PontoAnalise[], quebras: RespostaIndicador["quebras"], campo: "valor" | "meta",
): PontoSerie[] {
  const saida: PontoSerie[] = [];
  for (const p of [...pontos].sort((a, b) => a.edicao - b.edicao)) {
    const q = quebras.find((x) => x.entre[1] === p.edicao);
    if (q && saida.length > 0) saida.push({ rotulo: `quebra ${q.entre[0]}-${q.entre[1]}`, valor: null });
    const valor = campo === "valor" ? (ehSemRegistro(p) ? null : p.valor) : p.meta;
    saida.push({ rotulo: String(p.edicao), valor });
  }
  return saida;
}

function escolherPrincipal(series: SerieAnalise[], escolaId: number | null): SerieAnalise | null {
  const principais = series.filter((s) => s.papel === "principal");
  return principais.find((s) => escolaId != null && s.escola_id === escolaId) ?? principais[0] ?? null;
}

/** As marcas da média instável e os textos do servidor nas células e na legenda: com a sigla
 *  técnica (a área avançada) ou na língua simples do fluxo principal da Secretaria
 *  (`/rede/avaliacoes-externas`, prop `simples`) — `texto` reescreve o motivo da falta, a origem
 *  do número, a legenda do "*", o porquê de uma série ficar fora da comparação e o do indicador
 *  indisponível (sem "1 clique", "decisão D2", "reimporte", "coorte"…). */
interface Marcas { instavel: string; tpsZero: string; texto: (t: string) => string }
const MARCAS_TECNICAS: Marcas = {
  instavel: "média instável (TPS = 0)", tpsZero: "calculado com médias de TPS = 0", texto: (t) => t,
};
const MARCAS_SIMPLES: Marcas = {
  instavel: "média instável (poucos alunos fizeram a prova)", tpsZero: "calculado com médias instáveis",
  texto: textoSimples,
};

/** No fluxo principal (celular), a tabela larga rola dentro do cartão, com o aviso "Deslize…"
 *  (a mesma moldura da ficha da escola); na área avançada, a moldura de sempre. */
function Moldura({ simples, rotulo, children }: { simples: boolean; rotulo: string; children: ReactNode }) {
  return simples
    ? <TabelaRolavel rotulo={rotulo}>{children}</TabelaRolavel>
    : <div className="relative overflow-x-auto">{children}</div>;
}

/** A 1ª coluna (Ano, Escola) presa à esquerda no celular — só no fluxo principal. */
const presa = (simples: boolean) => (simples ? " presa-esquerda-celular" : "");

// --- Série histórica ---------------------------------------------------------------------

function SerieHistorica({ resp, indicador, escolaId, marcas, simples }: {
  resp: RespostaIndicador; indicador: IndicadorAnalise; escolaId: number | null; marcas: Marcas; simples: boolean;
}) {
  const principal = escolherPrincipal(resp.series, escolaId);
  if (!principal) {
    const soEscola = !indicador.abrangencias.includes("rede");
    return (
      <p className={`text-sm ${CINZA}`} data-testid="indicador-sem-serie">
        {soEscola
          ? `O ${indicador.nome} é por escola: escolha uma escola no filtro Escola ou use a visão “Escolas numa edição”.`
          : "Sem série oficial para este recorte."}
      </p>
    );
  }
  // Referência no gráfico SÓ quando comparável (mesma rede, mesma escala); o resto é contexto.
  const referencias = resp.series.filter((s) => s !== principal && s.comparavel && s.papel !== "contexto");
  const foraDaComparacao = resp.series.filter((s) => s !== principal && !referencias.includes(s));
  const unidade = indicador.unidade;
  const casas = principal.pontos.find((p) => p.casas != null)?.casas ?? null;
  const formato = formatoDaSerie(casas, unidade);
  const edicoes = [...new Set([principal, ...referencias].flatMap((s) => s.pontos.map((p) => p.edicao)))]
    .sort((a, b) => a - b);
  const eixoX = edicoes.map(String);
  const temMeta = indicador.tem_meta && principal.pontos.some((p) => p.meta != null);
  const series: SerieLinha[] = [
    { nome: principal.rotulo, cor: COR_PRINCIPAL, pontos: pontosDoGrafico(principal.pontos, resp.quebras, "valor") },
    ...(temMeta
      ? [{ nome: `Meta — ${principal.rotulo}`, cor: COR_META, tracejada: true,
           pontos: pontosDoGrafico(principal.pontos, resp.quebras, "meta") }]
      : []),
    ...referencias.map((s, i) => ({
      nome: s.rotulo, cor: CORES_REFERENCIA[i % CORES_REFERENCIA.length],
      pontos: pontosDoGrafico(s.pontos, resp.quebras, "valor"),
    })),
  ];
  const valores = series.flatMap((s) => s.pontos.flatMap((p) => (p.valor == null ? [] : [p.valor])));
  const { minimo, maximo } = faixaDoEixo(valores, unidade);
  const quebrasNoEixo = resp.quebras.filter((q) => edicoes.includes(q.entre[0]) && edicoes.includes(q.entre[1]));
  const recorte = [rotuloEtapa(resp.filtros.etapa), rotuloComponente(resp.filtros.componente)].filter(Boolean).join(" · ");
  const titulo = `${indicador.nome}${recorte ? ` — ${recorte}` : ""}`;
  const porEdicao = (s: SerieAnalise, e: number) => s.pontos.find((p) => p.edicao === e) ?? null;
  const linhas = [...edicoes].sort((a, b) => b - a);
  const legenda = legendaSemRegistro([principal, ...referencias].flatMap((s) => s.pontos));

  const itens: ItemDetalhe[] = [principal, ...referencias].flatMap((s) => s.pontos.map((p) => ({
    rotulo: `${p.edicao} — ${s.rotulo}`, fonte_id: p.fonte_id, detalhe: textoDetalhado(p, unidade),
  })));

  return (
    <div className="space-y-4">
      <figure className="space-y-1" data-testid="indicador-grafico">
        <figcaption className="text-sm font-semibold text-zinc-800 dark:text-zinc-100">{titulo}</figcaption>
        {/* No celular o gráfico ocupa a largura que há (sem largura mínima: o ano mais
            recente nunca fica escondido fora da vista); do sm para cima, largura mínima
            legível e teto no desktop para não virar um painel gigante. */}
        <div className="relative overflow-x-auto">
          <div className="max-w-2xl sm:min-w-[24rem]">
            <GraficoLinha
              series={series} eixoX={eixoX} minimo={minimo} maximo={maximo} altura={200} formato={formato}
              rotulo={`${titulo}: ${series.map((s) => s.nome).join(", ")} por edição${
                quebrasNoEixo.map((q) => `. Sem linha de ${q.entre[0]} para ${q.entre[1]} (quebra de escala)`).join("")}${
                legenda ? `. Os números marcados com ${MARCA_SEM_REGISTRO} (sem registro oficial) ficam fora do gráfico` : ""}`}
            />
          </div>
        </div>
        {legenda && (
          <p className={`text-xs ${CINZA}`} data-testid="grafico-sem-registro">
            Os números marcados com {MARCA_SEM_REGISTRO} (sem registro oficial) ficam fora do gráfico: estão só na tabela.
          </p>
        )}
      </figure>

      <Moldura simples={simples} rotulo={`${titulo}: tabela completa`}>
        <table className="w-full text-xs" data-testid="indicador-tabela">
          <caption className="sr-only">{titulo}: valor, meta, diferença e situação por edição</caption>
          <thead>
            <tr className={`border-b border-zinc-200 dark:border-zinc-800 ${CINZA}`}>
              <th className={`${TH}${presa(simples)}`} scope="col">Ano</th>
              <th className={TH} scope="col">{principal.rotulo}</th>
              {indicador.tem_meta && <>
                <th className={TH} scope="col">Meta</th>
                <th className={TH} scope="col">Diferença</th>
                <th className={TH} scope="col">Situação</th>
              </>}
              {referencias.map((s) => <th key={s.id} className={TH} scope="col">{s.rotulo}</th>)}
            </tr>
          </thead>
          <tbody>
            {linhas.map((e) => {
              const p = porEdicao(principal, e);
              return (
                <tr key={e} className="border-b border-zinc-100 last:border-0 dark:border-zinc-800/60">
                  <th scope="row" className={`${TD}${presa(simples)} text-left font-medium`}>{e}</th>
                  <td className={TD}>
                    {p ? <ValorOficial {...p} unidade={unidade} traduzir={marcas.texto} /> : <SemPontoNaEdicao />}
                    {p?.instavel && <span className="ml-1"><Badge tom="alerta">média instável</Badge></span>}
                    {p?.tps_zero && <span className="ml-1"><Badge tom="alerta">{marcas.tpsZero}</Badge></span>}
                  </td>
                  {indicador.tem_meta && <>
                    <td className={TD}>
                      {p?.meta != null
                        ? valorComUnidade(p.meta, p.meta_casas ?? p.casas, unidade, p.operador_meta)
                        : <span className={`text-xs ${CINZA}`}>{p?.texto_sem_meta ?? "sem meta nesta edição"}</span>}
                    </td>
                    <td className={TD}>{p ? diferenca(p, unidade) : "—"}</td>
                    <td className={TD}>
                      {p?.situacao_meta
                        ? <SituacaoDaMeta situacao={p.situacao_meta} diferenca={null} casas={p.casas} unidade={unidade} />
                        : "—"}
                    </td>
                  </>}
                  {referencias.map((s) => {
                    const r = porEdicao(s, e);
                    return (
                      <td key={s.id} className={TD}>
                        {r ? <ValorOficial {...r} unidade={unidade} traduzir={marcas.texto} /> : <SemPontoNaEdicao />}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </Moldura>
      {legenda && <p className={`text-xs ${CINZA}`} data-testid="legenda-sem-registro">{marcas.texto(legenda)}</p>}

      {foraDaComparacao.length > 0 && (
        <div className="text-xs text-zinc-600 dark:text-zinc-300" data-testid="fora-da-comparacao">
          <p className="font-medium">Fora da comparação (não está no gráfico):</p>
          <ul className="mt-1 list-disc space-y-0.5 pl-4">
            {foraDaComparacao.map((s) => (
              <li key={s.id}>{s.rotulo} — {marcas.texto(s.motivo_nao_comparavel ?? "outra rede ou outra escala")}</li>
            ))}
          </ul>
        </div>
      )}

      <DetalhesEFontes itens={itens} fontes={resp.fontes} testId="detalhes-fontes-indicador" />
    </div>
  );
}

// --- Escolas numa edição ------------------------------------------------------------------

function EscolasNaEdicao({ resp, indicador, escolasDaRede, marcas, simples, linkDaEscola }: {
  resp: RespostaIndicador; indicador: IndicadorAnalise; escolasDaRede: EscolaDaRede[]; marcas: Marcas; simples: boolean;
  linkDaEscola?: (escolaId: number) => string;
}) {
  const edicao = resp.filtros.edicao;
  const linhas = porNome(resp.escolas);
  const unidade = indicador.unidade;
  if (linhas.length === 0) {
    return <p className={`text-sm ${CINZA}`}>Nenhuma escola da rede tem linha nesta edição.</p>;
  }
  const legenda = legendaSemRegistro(linhas);
  const semInep = (e: (typeof linhas)[number]) =>
    (e.pendencia ?? escolasDaRede.find((x) => x.id === e.escola_id)?.pendencia) === "sem_codigo_inep";
  // Como comparar, alinhado ao Comparar escolas: a meta só quando o indicador tem meta; a rede
  // municipal só quando ela tem número (o IEE só existe por escola).
  const comQue = [
    ...(indicador.tem_meta ? ["com a sua meta"] : []),
    "com ela mesma nas outras edições (série histórica)",
    ...(indicador.abrangencias.includes("rede") ? ["com a rede municipal na mesma edição"] : []),
  ];
  const comparar = comQue.length > 1 ? `${comQue.slice(0, -1).join(", ")} e ${comQue[comQue.length - 1]}` : comQue[0];
  return (
    <div className="space-y-3">
      <Nota testId="escolas-sem-ranking">
        Escolas em ordem alfabética — não é ranking.{" "}
        {indicador.tem_meta ? "Compare" : "Este indicador não tem meta: compare"} cada escola {comparar}.
      </Nota>
      <Moldura simples={simples} rotulo={`${indicador.nome}${edicao ? ` ${edicao}` : ""} por escola: tabela completa`}>
        <table className="w-full text-xs" data-testid="indicador-escolas">
          <caption className="sr-only">{indicador.nome} {edicao ?? ""}: escolas da rede em ordem alfabética</caption>
          <thead>
            <tr className={`border-b border-zinc-200 dark:border-zinc-800 ${CINZA}`}>
              <th className={`${TH}${presa(simples)}`} scope="col">Escola</th>
              <th className={TH} scope="col">Resultado{edicao ? ` (${edicao})` : ""}</th>
              {indicador.tem_meta && <>
                <th className={TH} scope="col">Meta</th>
                <th className={TH} scope="col">Diferença</th>
              </>}
              <th className={TH} scope="col">Observação</th>
            </tr>
          </thead>
          <tbody>
            {linhas.map((e) => (
              <tr key={e.escola_id} className="border-b border-zinc-100 last:border-0 dark:border-zinc-800/60">
                <th scope="row" className={`${TD}${presa(simples)} min-w-[10rem] text-left font-normal`}>
                  {linkDaEscola ? (
                    <Link to={linkDaEscola(e.escola_id)}
                          className="break-words font-medium text-indigo-700 underline-offset-2 hover:underline dark:text-indigo-300">
                      {e.nome}
                    </Link>
                  ) : <span className="break-words">{e.nome}</span>}
                  {semInep(e) && <span className="ml-1"><Badge tom="alerta">sem código INEP</Badge></span>}
                </th>
                <td className={TD}><ValorOficial {...e} unidade={unidade} traduzir={marcas.texto} /></td>
                {indicador.tem_meta && <>
                  <td className={TD}>
                    {e.meta != null
                      ? valorComUnidade(e.meta, e.meta_casas ?? e.casas, unidade)
                      : <span className={`text-xs ${CINZA}`}>{e.texto_sem_meta ?? "sem meta nesta edição"}</span>}
                  </td>
                  <td className={TD}>{diferenca(e, unidade)}</td>
                </>}
                <td className={TD}>
                  <span className="flex flex-wrap gap-1">
                    {e.instavel && <Badge tom="alerta">{marcas.instavel}</Badge>}
                    {e.tps_zero && <Badge tom="alerta">{marcas.tpsZero}</Badge>}
                    {e.situacao_meta && <SituacaoDaMeta situacao={e.situacao_meta} diferenca={null} casas={e.casas} />}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Moldura>
      {legenda && <p className={`text-xs ${CINZA}`} data-testid="legenda-sem-registro">{marcas.texto(legenda)}</p>}
      <DetalhesEFontes
        itens={linhas.map((e) => ({ rotulo: `${e.nome}${edicao ? ` (${edicao})` : ""}`, fonte_id: e.fonte_id }))}
        fontes={resp.fontes} testId="detalhes-fontes-escolas" />
    </div>
  );
}

// --- Tela -------------------------------------------------------------------------------

export default function PorIndicador({
  redeId, base, params, atualizar, escolaId, titulo, semEscolha, campoEscola, simples, linkDaEscola,
}: {
  redeId: number;
  base: RespostaIndicadoresRede;
  params: URLSearchParams;
  atualizar: (mudancas: Record<string, string | null>) => void;
  escolaId: number | null;
  /** O título da parte quando ela vive DENTRO de outra aba (Avaliações externas). */
  titulo?: string;
  /** A página já escolheu o indicador (os cartões de `/rede/avaliacoes-externas`): sem a
   *  escolha repetida aqui — o indicador vem só do `?indicador=`. */
  semEscolha?: boolean;
  /** O campo Escola DENTRO do detalhe, para a página que não tem o filtro Escola no topo
   *  (`/rede/avaliacoes-externas`). Sem ele, vale o filtro Escola da página (a análise). */
  campoEscola?: { aoMudar: (escolaId: number | null) => void };
  /** A língua simples do fluxo principal: as marcas da média instável sem a sigla técnica e os
   *  textos do servidor reescritos (`textoSimples`: avisos, motivos de falta e de "fora da
   *  comparação", indicador indisponível). Sem ela, os textos técnicos de sempre. Com ela, as
   *  tabelas rolam com o aviso "Deslize…" e a 1ª coluna presa no celular. */
  simples?: boolean;
  /** O caminho da ficha de cada escola (com o `?rede=` do global): o nome da escola numa edição
   *  vira link. Sem ele, o nome é só texto. */
  linkDaEscola?: (escolaId: number) => string;
}) {
  const marcas = simples ? MARCAS_SIMPLES : MARCAS_TECNICAS;
  const disponiveis = base.indicadores.filter((i) => i.disponivel);
  const indicador = base.indicadores.find((i) => i.chave === params.get("indicador")) ?? disponiveis[0] ?? null;
  const porEscola = Boolean(indicador?.por_escola && indicador.abrangencias.includes("escola"));
  // Indicador SÓ por escola (o IEE): não há número da rede — sem escola escolhida, a
  // visão padrão é a das escolas numa edição; com escola, a série dela.
  const soEscola = Boolean(indicador && porEscola && !indicador.abrangencias.includes("rede"));
  const visaoUrl = params.get("visao");
  const visao = porEscola && (visaoUrl === "escolas" || (soEscola && escolaId == null && visaoUrl !== "serie"))
    ? "escolas" : "serie";
  const abrangencia = porEscola && escolaId != null && (params.get("abrangencia") === "escola" || soEscola)
    ? "escola" : "rede";
  const escola = escolaId != null ? base.escolas.find((e) => e.id === escolaId) ?? null : null;
  const edicaoEscolas = numeroOuNull(params.get("edicao")) ?? indicador?.edicao_mais_recente ?? null;
  // De > Até (um link antigo, digitado à mão): os dois trocam de lugar — a API recusaria.
  const deUrl = numeroOuNull(params.get("de"));
  const ateUrl = numeroOuNull(params.get("ate"));
  const [de, ate] = deUrl != null && ateUrl != null && deUrl > ateUrl ? [ateUrl, deUrl] : [deUrl, ateUrl];

  const q = new URLSearchParams();
  for (const k of ["etapa", "componente"]) {
    const v = params.get(k);
    if (v) q.set(k, v);
  }
  if (de != null) q.set("de", String(de));
  if (ate != null) q.set("ate", String(ate));
  if (visao === "serie" && abrangencia === "escola" && escolaId != null) q.set("escola_id", String(escolaId));
  q.set("visao", visao);
  if (visao === "escolas" && edicaoEscolas != null) q.set("edicao", String(edicaoEscolas));
  const url = indicador && indicador.disponivel
    ? `/redes/${redeId}/analise/indicadores/${encodeURIComponent(indicador.chave)}?${q.toString()}`
    : null;
  const { dados, carregando, erro } = useApiExata<RespostaIndicador>(url);

  function escolher(chave: string) {
    // Outro indicador: as dimensões do anterior não valem para ele.
    atualizar({ indicador: chave, etapa: null, componente: null, de: null, ate: null, edicao: null,
                visao: null, abrangencia: null });
  }

  const cabecalho = titulo && (
    <h2 className={TITULO_CARTAO}>
      <IconePastel icone={LineChart} tom="violeta" tamanho="sm" /> {titulo}
    </h2>
  );

  if (base.indicadores.length === 0) {
    return (
      <Card className="space-y-4 p-6">
        {cabecalho}
        <p className={`text-sm ${CINZA}`}>Nenhum indicador oficial no catálogo da rede.</p>
      </Card>
    );
  }

  const opcoes = dados?.opcoes;
  const etapas = opcoes?.etapas ?? indicador?.etapas ?? [];
  const componentes = opcoes?.componentes ?? indicador?.componentes ?? [];
  const edicoes = [...(opcoes?.edicoes ?? indicador?.edicoes ?? [])].sort((a, b) => a - b);
  const valor = (k: string, eco: string | number | null | undefined) => params.get(k) ?? (eco == null ? "" : String(eco));
  const motivoSemEscola = !indicador ? null
    : !porEscola ? (indicador.chave === "ica"
      ? "O ICA é da rede: não existe por escola."
      : `O ${indicador.nome} não é divulgado por escola.`)
      : escolaId == null
        ? campoEscola ? "Escolha uma escola no campo Escola." : "Escolha uma escola no filtro Escola, acima."
        : null;
  const temDadoNaEscola = escolaId != null ? opcoes?.escolas.find((e) => e.id === escolaId)?.tem_dado : undefined;
  const avisos = [...new Set([...(indicador?.avisos ?? []), ...(dados?.avisos ?? []),
                              ...(dados?.quebras ?? []).map((x) => `Entre ${x.entre[0]} e ${x.entre[1]}: ${x.texto}`)]
    .map((a) => (simples ? textoSimples(a) : a)))];

  return (
    <div className="space-y-5">
      <Card className="space-y-5 p-6">
        {cabecalho}
        {!semEscolha && (
          <EscolhaIndicador legenda="Indicador oficial (um por vez)" indicadores={base.indicadores}
                            selecionado={indicador?.chave ?? null} aoEscolher={escolher} />
        )}
        {indicador && indicador.disponivel && (
          <div className="flex flex-wrap items-end gap-3" data-testid="dimensoes-indicador">
            {campoEscola && porEscola && (
              <Seletor rotulo="Escola" valor={escolaId == null ? "" : String(escolaId)}
                       aoMudar={(v) => campoEscola.aoMudar(numeroOuNull(v))}>
                <option value="">Nenhuma (rede municipal)</option>
                {porNome(base.escolas).map((e) => (
                  <option key={e.id} value={e.id}>
                    {e.nome}{e.pendencia === "sem_codigo_inep" ? " (sem código INEP)" : ""}
                  </option>
                ))}
              </Seletor>
            )}
            {etapas.length > 0 && (
              <Seletor rotulo="Etapa" valor={valor("etapa", dados?.filtros.etapa)}
                       aoMudar={(v) => atualizar({ etapa: v || null })}>
                {etapas.map((e) => <option key={e} value={e}>{rotuloEtapa(e)}</option>)}
              </Seletor>
            )}
            {componentes.length > 0 && (
              <Seletor rotulo="Componente" valor={valor("componente", dados?.filtros.componente)}
                       aoMudar={(v) => atualizar({ componente: v || null })}>
                {componentes.map((c) => <option key={c} value={c}>{rotuloComponente(c)}</option>)}
              </Seletor>
            )}
            <fieldset className="min-w-0 text-xs text-zinc-600 dark:text-zinc-300">
              <legend className="mb-1 font-medium">Visão</legend>
              <div className="flex flex-wrap gap-x-3 gap-y-1">
                <label className="inline-flex items-center gap-1.5">
                  <input type="radio" name="visao-indicador" checked={visao === "serie"}
                         onChange={() => atualizar({ visao: soEscola ? "serie" : null, edicao: null })} />
                  Série histórica
                </label>
                <label className={`inline-flex items-center gap-1.5 ${porEscola ? "" : "text-zinc-500 dark:text-zinc-400"}`}>
                  <input type="radio" name="visao-indicador" checked={visao === "escolas"} disabled={!porEscola}
                         onChange={() => atualizar({ visao: "escolas" })} />
                  Escolas numa edição
                </label>
              </div>
            </fieldset>
            {visao === "serie" ? (
              <>
                <fieldset className="min-w-0 text-xs text-zinc-600 dark:text-zinc-300">
                  <legend className="mb-1 font-medium">Abrangência</legend>
                  <div className="flex flex-wrap gap-x-3 gap-y-1">
                    <label className={`inline-flex items-center gap-1.5 ${soEscola ? "text-zinc-500 dark:text-zinc-400" : ""}`}>
                      <input type="radio" name="abrangencia-indicador" checked={abrangencia === "rede"}
                             disabled={soEscola} onChange={() => atualizar({ abrangencia: null })} />
                      Rede municipal
                    </label>
                    <label className={`inline-flex min-w-0 items-center gap-1.5 ${motivoSemEscola ? "text-zinc-500 dark:text-zinc-400" : ""}`}>
                      <input type="radio" name="abrangencia-indicador" checked={abrangencia === "escola"}
                             disabled={motivoSemEscola != null} onChange={() => atualizar({ abrangencia: "escola" })} />
                      <span className="break-words">
                        {campoEscola ? "Escola escolhida" : "Escola do filtro"}{escola ? `: ${escola.nome}` : ""}
                      </span>
                    </label>
                  </div>
                  {soEscola && (
                    <p className="mt-1 text-xs text-amber-700 dark:text-amber-400" data-testid="motivo-so-escola">
                      O {indicador.nome} é por escola: não existe número da rede.
                    </p>
                  )}
                  {motivoSemEscola && (
                    <p className="mt-1 text-xs text-amber-700 dark:text-amber-400" data-testid="motivo-sem-escola">
                      {motivoSemEscola}
                    </p>
                  )}
                </fieldset>
                {edicoes.length > 1 && (
                  <>
                    {/* De depois de Até nunca vai para a API: o outro lado acompanha. */}
                    <Seletor rotulo="De" valor={String(de ?? dados?.filtros.de ?? edicoes[0])}
                             aoMudar={(v) => {
                               const n = numeroOuNull(v);
                               const fim = ate ?? edicoes[edicoes.length - 1];
                               atualizar(n != null && n > fim ? { de: v, ate: v } : { de: v || null });
                             }}>
                      {edicoes.map((e) => <option key={e} value={e}>{e}</option>)}
                    </Seletor>
                    <Seletor rotulo="Até" valor={String(ate ?? dados?.filtros.ate ?? edicoes[edicoes.length - 1])}
                             aoMudar={(v) => {
                               const n = numeroOuNull(v);
                               const inicio = de ?? edicoes[0];
                               atualizar(n != null && n < inicio ? { ate: v, de: v } : { ate: v || null });
                             }}>
                      {edicoes.map((e) => <option key={e} value={e}>{e}</option>)}
                    </Seletor>
                  </>
                )}
              </>
            ) : (
              <Seletor rotulo="Edição" valor={edicaoEscolas == null ? "" : String(edicaoEscolas)}
                       aoMudar={(v) => atualizar({ edicao: v || null })}>
                {[...edicoes].reverse().map((e) => <option key={e} value={e}>{e}</option>)}
              </Seletor>
            )}
          </div>
        )}
        <FiltrosAplicados testId="filtros-indicador">
          {campoEscola ? (
            <>
              A avaliação oficial tem edição própria (o período das plataformas não se aplica).
              {porEscola
                ? " O campo Escola vale para a abrangência “Escola”."
                : " Este indicador não existe por escola."}
            </>
          ) : (
            <>
              O período e a série do topo não se aplicam: a avaliação oficial tem edição própria.
              {porEscola
                ? " O filtro Escola vale para a abrangência “Escola”."
                : " O filtro Escola não se aplica a este indicador."}
            </>
          )}
        </FiltrosAplicados>
      </Card>

      {indicador && !indicador.disponivel ? (
        <Card className="p-6">
          <p className="text-sm text-zinc-600 dark:text-zinc-300" data-testid="indicador-indisponivel">
            {indicador.nome}: {marcas.texto(textoIndisponivel(indicador))}.
          </p>
        </Card>
      ) : indicador && (
        <Card className="space-y-5 p-6" >
          <h2 className={`${TITULO_CARTAO} flex-wrap`}>
            <IconePastel icone={BarChart3} tom="violeta" tamanho="sm" />
            {indicador.nome}
            <span className={`text-sm font-normal ${CINZA}`}>· {indicador.orgao}</span>
          </h2>
          {avisos.length > 0 && (
            <Aviso testId="avisos-comparabilidade">
              <p className="font-medium">Antes de comparar</p>
              <ul className="list-disc space-y-0.5 pl-4">{avisos.map((a) => <li key={a}>{a}</li>)}</ul>
            </Aviso>
          )}
          {abrangencia === "escola" && temDadoNaEscola === false && (
            <Nota>Esta escola não tem número deste indicador no recorte — cada ano diz o motivo.</Nota>
          )}
          {erro && !dados ? (
            <Mensagem tipo="erro">Não foi possível carregar o indicador: {erro.message}</Mensagem>
          ) : !dados ? (
            carregando || url ? <Carregando texto="Carregando o indicador..." /> : null
          ) : visao === "escolas" ? (
            <EscolasNaEdicao resp={dados} indicador={dados.indicador} escolasDaRede={base.escolas} marcas={marcas}
                             simples={Boolean(simples)} linkDaEscola={linkDaEscola} />
          ) : (
            <SerieHistorica resp={dados} indicador={dados.indicador} marcas={marcas} simples={Boolean(simples)}
                            escolaId={abrangencia === "escola" ? escolaId : null} />
          )}
        </Card>
      )}
    </div>
  );
}
