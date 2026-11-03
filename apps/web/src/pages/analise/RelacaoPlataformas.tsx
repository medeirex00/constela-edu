/**
 * Relação com as plataformas — um indicador OFICIAL por escola (etapa, componente,
 * edição) × uma métrica de plataforma no período. O backend decide se dá para
 * calcular (critérios documentados em docs/analise/METODOLOGIA.md: só oficial, a
 * mesma série, a janela da plataforma dentro do ano letivo da edição, escolas
 * suficientes com células de k alunos ou mais, variação nos dois lados).
 *
 *  - NÃO calculável: os motivos em linguagem simples + "lado a lado" (cada escola com
 *    o ano de cada lado), sem número de correlação nenhum;
 *  - calculável: a dispersão, o coeficiente (Spearman), o IC 95% e o n — e o mesmo
 *    "lado a lado";
 *  - SEMPRE: o aviso de que correlação não é causalidade e a metodologia recolhível.
 *
 * Abre com "O que dá para relacionar hoje" (o alerta de metodologia do catálogo: os anos das
 * avaliações × os das plataformas — morava na antiga Visão geral) e a regra, em uma frase.
 * (O quadro "Em quais séries há lacunas", também da antiga Visão geral, fica na tela Elefante
 * e Matific, em "Sobre os dados".)
 *
 * Filtros na URL: `?indicador=&etapa=&componente=&edicao=&metrica=`; o período é o da
 * página (vale para o lado da plataforma).
 */
import { AlertTriangle, ChartScatter } from "lucide-react";

import { periodoParaQuery } from "../../components/SeletorPeriodo";
import { Badge, Card, Carregando, IconePastel, Mensagem, SecaoRecolhivel } from "../../components/ui";
import { useApp } from "../../context/AppContext";
import {
  EscolhaIndicador, FiltrosAplicados, Seletor, TD, TH, TITULO_CARTAO, rotuloPeriodo, useApiExata,
} from "./comum";
import { decimal, numeroBR, porNome, rotuloComponente, rotuloEtapa } from "./formato";
import type {
  CriteriosRelacao, IndicadorAnalise, IntervaloConfianca, MetricaRelacao, ParRelacao, RespostaIndicadoresRede,
  RespostaRelacao,
} from "./tipos";

/** Métricas de plataforma que a relação aceita — as MESMAS chaves do backend
 *  (`services/analise/relacao.METRICAS`); a resposta traz a lista em
 *  `metricas_disponiveis`, que vale por cima desta (que é só o plano B antes de ela chegar). */
export const METRICAS_RELACAO: MetricaRelacao[] = [
  { chave: "livros_por_aluno", rotulo: "Livros novos por aluno com conta (Elefante)", plataforma: "elefante", componente: "lp" },
  { chave: "minutos_por_aluno", rotulo: "Minutos de leitura por aluno com conta (Elefante)", plataforma: "elefante", componente: "lp" },
  { chave: "participacao_elefante", rotulo: "Participação no Elefante (% dos alunos com conta que leram)", plataforma: "elefante", componente: "lp" },
  { chave: "taxa_acerto", rotulo: "Acerto nas questões do Elefante (%)", plataforma: "elefante", componente: "lp" },
  { chave: "nivel_medio", rotulo: "Nível médio dos livros lidos (Elefante; posição AA = 0 … Z = 29)", plataforma: "elefante", componente: "lp" },
  { chave: "atividades_por_aluno", rotulo: "Atividades por aluno com dado no período (Matific)", plataforma: "matific", componente: "mt" },
  { chave: "estrelas_por_aluno", rotulo: "Estrelas por aluno com dado no período (Matific)", plataforma: "matific", componente: "mt" },
  { chave: "desempenho_medio", rotulo: "Estrelas por atividade (Matific, 0 a 5)", plataforma: "matific", componente: "mt" },
  { chave: "participacao_matific", rotulo: "Participação no Matific (% dos alunos com dado no período que fizeram atividade)", plataforma: "matific", componente: "mt" },
];

const ROTULO_PLATAFORMA: Record<string, string> = { elefante: "Elefante Letrado", matific: "Matific" };
/** A área de cada plataforma (Elefante ↔ Língua Portuguesa; Matific ↔ Matemática). */
const COMPONENTE_DA_PLATAFORMA: Record<string, string> = { elefante: "lp", matific: "mt" };
const CINZA = "text-zinc-600 dark:text-zinc-400";

/** Motivo de recusa → linguagem simples (o texto da API, `textos`, vem primeiro). */
export const MOTIVOS_RELACAO: Record<string, string> = {
  indicador_so_da_rede: "Este indicador só existe para a rede: a relação é feita escola a escola.",
  so_estimativa:
    "Só há a Estimativa Constela (calculada pelo Constela): estimativa não entra em associação estatística.",
  so_sem_registro:
    "Nesta edição só há números gravados antes, sem o registro do arquivo oficial: a relação usa só números oficiais.",
  sem_dado_oficial: "Nenhuma escola da rede tem resultado oficial nesta edição.",
  serie_incompativel: "A série da plataforma não é a série avaliada.",
  componente_incompativel: "A métrica é de outra área (Elefante ↔ Língua Portuguesa; Matific ↔ Matemática).",
  modulo_nao_contratado: "A rede não contratou a plataforma desta métrica.",
  periodo_sem_sobreposicao:
    "O período da plataforma não cai no ano letivo da edição escolhida: os dois números são de anos diferentes.",
  n_insuficiente: "Poucas escolas têm os dois números: não dá para calcular com segurança.",
  sem_variancia: "Um dos lados não varia entre as escolas: não há o que relacionar.",
};

/** O aviso de causalidade é fixo na tela; os outros avisos da API aparecem no resultado. */
const ehAvisoCausalidade = (t: string) => /causalidade/i.test(t);

/**
 * A interpretação sem o parágrafo de causalidade: a caixa fixa da tela já o diz (sem
 * isso o aviso aparecia DUAS vezes, com redações diferentes).
 */
function semCausalidade(texto: string, avisos: string[]): string {
  let t = texto;
  for (const a of avisos.filter(ehAvisoCausalidade)) t = t.split(a).join("");
  return t.replace(/\s*Correlação não é causalidade[\s\S]*$/i, "").trim();
}

/** "Ano letivo 2026 (ano letivo 2026)" → "Ano letivo 2026": o ano não se repete. */
const semAnoRepetido = (t: string) => t.replace(/(ano letivo (\d{4}))\s*\(ano letivo \2\)/gi, "$1");

const METODOLOGIA_PADRAO =
  "A relação usa o coeficiente de Spearman (por postos, empates pelo posto médio), com intervalo de confiança "
  + "de 95% aproximado. Cada ponto é uma escola. Só entra número oficial (com o registro do arquivo), da mesma "
  + "série avaliada, com a janela da plataforma dentro do ano letivo da edição, e só escolas com alunos medidos "
  + "suficientes na série e a coleta em dia no período.";

function intervalo(ic: IntervaloConfianca | null): [number, number] | null {
  if (!ic) return null;
  if (Array.isArray(ic)) return ic.length === 2 ? [ic[0], ic[1]] : null;
  return [ic.inferior, ic.superior];
}

const coef = (v: number) => `${v < 0 ? "−" : ""}${numeroBR(Math.abs(v), 2)}`;

/** Casas do número oficial: as que a API manda; sem elas, a precisão publicada da escala. */
const CASAS_DA_ESCALA: Record<string, number> = {
  escala_saresp: 1, escala_saeb: 2, indice_ideb: 1, indice_iee: 2, percentual: 0,
};

function valorOficial(par: ParRelacao, indicador: IndicadorAnalise | null): string | null {
  if (par.valor_oficial == null) return null;
  const casas = par.casas_oficial ?? CASAS_DA_ESCALA[indicador?.escala ?? ""] ?? 1;
  return `${numeroBR(par.valor_oficial, casas)}${indicador?.unidade === "%" ? "%" : ""}`;
}

const MAX_EIXO = 44;
const encurtar = (s: string) => (s.length > MAX_EIXO ? `${s.slice(0, MAX_EIXO - 1).trimEnd()}…` : s);

function Dispersao({ pares, rotuloX, rotuloY }: { pares: ParRelacao[]; rotuloX: string; rotuloY: string }) {
  const pontos = pares.filter((p) => p.incluido && p.valor_oficial != null && p.valor_plataforma != null);
  if (pontos.length === 0) return null;
  const W = 460, H = 280, m = { l: 48, r: 16, t: 12, b: 40 };
  const xs = pontos.map((p) => p.valor_plataforma as number), ys = pontos.map((p) => p.valor_oficial as number);
  const [minX, maxX, minY, maxY] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  const px = (x: number) => m.l + (maxX === minX ? 0.5 : (x - minX) / (maxX - minX)) * (W - m.l - m.r);
  const py = (y: number) => H - m.b - (maxY === minY ? 0.5 : (y - minY) / (maxY - minY)) * (H - m.t - m.b);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full max-w-xl" role="img"
         aria-label={`Dispersão por escola: ${rotuloX} (horizontal) × ${rotuloY} (vertical), ${pontos.length} escolas`}
         data-testid="relacao-dispersao">
      <line x1={m.l} y1={H - m.b} x2={W - m.r} y2={H - m.b} className="stroke-zinc-300 dark:stroke-zinc-700" />
      <line x1={m.l} y1={m.t} x2={m.l} y2={H - m.b} className="stroke-zinc-300 dark:stroke-zinc-700" />
      {pontos.map((p) => (
        <circle key={p.escola_id} cx={px(p.valor_plataforma as number)} cy={py(p.valor_oficial as number)} r={5}
                className="fill-indigo-500/80">
          <title>{p.nome}</title>
        </circle>
      ))}
      <text x={W / 2} y={H - 6} textAnchor="middle" className="fill-zinc-600 text-xs dark:fill-zinc-400">
        {encurtar(rotuloX)} →<title>{rotuloX}</title>
      </text>
      <text x={12} y={H / 2} textAnchor="middle" transform={`rotate(-90 12 ${H / 2})`} className="fill-zinc-600 text-xs dark:fill-zinc-400">
        {encurtar(rotuloY)} →<title>{rotuloY}</title>
      </text>
    </svg>
  );
}

function LadoALado({ resp, rotuloIndicador, rotuloMetrica }: {
  resp: RespostaRelacao; rotuloIndicador: string; rotuloMetrica: string;
}) {
  const pares = porNome(resp.pares);
  if (pares.length === 0) return <p className={`text-sm ${CINZA}`}>Nenhuma escola da rede com um dos dois números.</p>;
  return (
    <div className="space-y-1.5">
      <h3 className="text-[15px] font-semibold text-zinc-900 dark:text-white">Lado a lado, escola por escola</h3>
      <p className={`text-xs ${CINZA}`}>
        Em ordem alfabética — não é ranking. Cada lado mostra o ano a que se refere, e cada escola que fica de fora
        diz o motivo dela.
      </p>
      <div className="relative overflow-x-auto">
        <table className="w-full text-xs" data-testid="relacao-lado-a-lado">
          <caption className="sr-only">Lado a lado: {rotuloIndicador} e {rotuloMetrica} por escola</caption>
          <thead>
            <tr className={`border-b border-zinc-200 dark:border-zinc-800 ${CINZA}`}>
              <th className={TH} scope="col">Escola</th>
              <th className={TH} scope="col">{rotuloIndicador}</th>
              <th className={TH} scope="col">Ano da avaliação</th>
              <th className={TH} scope="col">{rotuloMetrica}</th>
              <th className={TH} scope="col">Período da plataforma</th>
              <th className={TH} scope="col">Entra no cálculo?</th>
            </tr>
          </thead>
          <tbody>
            {pares.map((p) => (
              <tr key={p.escola_id} className="border-b border-zinc-100 last:border-0 dark:border-zinc-800/60">
                <th scope="row" className={`${TD} min-w-[10rem] text-left font-normal`}><span className="break-words">{p.nome}</span></th>
                <td className={TD}>
                  {valorOficial(p, resp.indicador)
                    ?? <span className={`text-xs ${CINZA}`}>{p.texto_ausencia_oficial ?? "sem resultado oficial"}</span>}
                  {p.instavel && <span className="ml-1"><Badge tom="alerta">média instável</Badge></span>}
                </td>
                <td className={TD}>{p.edicao ?? "—"}</td>
                <td className={TD}>{decimal(p.valor_plataforma) ?? <span className={`text-xs ${CINZA}`}>sem dado no período</span>}</td>
                <td className={TD}>{p.janela ?? "—"}</td>
                <td className={TD}>
                  {p.incluido ? "sim" : (
                    <span className={`text-xs ${CINZA}`}>
                      {/* O motivo PRÓPRIO da escola (mesmo quando há um motivo geral, que está acima). */}
                      não{(p.motivo_escola ?? p.motivo_exclusao) ? `: ${semAnoRepetido(p.motivo_escola ?? p.motivo_exclusao ?? "")}` : ""}
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Criterios({ c }: { c: CriteriosRelacao }) {
  const sim = (b: boolean) => (b ? "sim" : "não");
  return (
    <ul className="list-disc space-y-0.5 pl-4 text-xs text-zinc-600 dark:text-zinc-300" data-testid="relacao-criterios">
      <li>Método: {c.metodo}</li>
      <li>Mínimo de escolas com os dois números: {c.n_minimo}</li>
      <li>Mínimo de alunos da série em cada escola: {c.k_minimo_alunos}</li>
      <li>Mesmo ano letivo dos dois lados: {sim(c.exige_mesmo_ano_letivo)}</li>
      <li>Mesma série avaliada: {sim(c.exige_mesma_serie)}</li>
      <li>Só número oficial: {sim(c.so_oficial)}</li>
      <li>Mesma escala: {sim(c.mesma_escala)}</li>
      {c.exige_coleta_em_dia != null && <li>Coleta da plataforma em dia no período: {sim(c.exige_coleta_em_dia)}</li>}
      {c.exclui_instavel != null && <li>Médias instáveis (TPS = 0) ficam de fora: {sim(c.exclui_instavel)}</li>}
    </ul>
  );
}

const numeroOuNull = (v: string | null): number | null => {
  if (v == null || v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
};

/** A regra, em uma frase (vale sempre, com ou sem o alerta do catálogo). */
const REGRA_DA_RELACAO = "A relação só é calculada com números oficiais e de plataforma do MESMO ano letivo, em ao "
  + "menos 8 escolas; abaixo, a cada escolha, a tela diz se dá para calcular ou por que não.";

/**
 * "O que dá para relacionar hoje": o alerta de METODOLOGIA do catálogo (já lido pela página:
 * nenhuma leitura a mais) — hoje, os anos das avaliações por escola e os das plataformas — e a
 * regra. O diagnóstico pesado não é pedido só para isso.
 */
function OQueDaParaRelacionar({ base }: { base: RespostaIndicadoresRede }) {
  const alerta = base.alertas.find((a) => a.tipo === "metodologia");
  return (
    <p className="text-sm text-zinc-800 dark:text-zinc-100" data-testid="situacao-relacao">
      {alerta?.texto ? `${alerta.texto} ` : ""}{REGRA_DA_RELACAO}
    </p>
  );
}

export default function RelacaoPlataformas({ redeId, base, params, atualizar }: {
  redeId: number;
  base: RespostaIndicadoresRede;
  params: URLSearchParams;
  atualizar: (mudancas: Record<string, string | null>) => void;
}) {
  const { periodo } = useApp();
  // A relação é ESCOLA a ESCOLA: indicador só da rede (o ICA) ou não oficial fica de fora.
  const bloqueio = (i: IndicadorAnalise): string | null => {
    if (!i.oficial) return "não é oficial: fica fora da relação";
    if (!i.por_escola || !i.abrangencias.includes("escola")) {
      return i.chave === "ica"
        ? "o ICA é da rede: não existe por escola, e a relação é feita escola a escola"
        : "só existe para a rede: a relação é feita escola a escola";
    }
    return null;
  };
  const elegiveis = base.indicadores.filter((i) => i.disponivel && bloqueio(i) == null);
  const indicador = elegiveis.find((i) => i.chave === params.get("indicador")) ?? elegiveis[0] ?? null;
  const etapa = (indicador && params.get("etapa") && indicador.etapas.includes(params.get("etapa")!))
    ? params.get("etapa")! : indicador?.etapas[0] ?? null;
  const componente = (indicador && params.get("componente") && indicador.componentes.includes(params.get("componente")!))
    ? params.get("componente")! : indicador?.componentes[0] ?? null;
  const edicaoUrl = numeroOuNull(params.get("edicao"));
  const edicao = indicador && edicaoUrl != null && indicador.edicoes.includes(edicaoUrl)
    ? edicaoUrl : indicador?.edicao_mais_recente ?? null;
  // Métrica padrão: a do componente (LP ↔ Elefante; MT ↔ Matific) — a mesma do backend.
  const metricaPadrao = componente === "mt" ? "estrelas_por_aluno" : "livros_por_aluno";
  const metricaUrl = params.get("metrica");
  const metrica = metricaUrl && /^[a-z_]+$/.test(metricaUrl) ? metricaUrl : metricaPadrao;

  const q = new URLSearchParams(periodoParaQuery(periodo));
  if (indicador) q.set("indicador", indicador.chave);
  if (etapa) q.set("etapa", etapa);
  if (componente) q.set("componente", componente);
  if (edicao != null) q.set("edicao", String(edicao));
  q.set("metrica", metrica);
  const url = indicador && edicao != null ? `/redes/${redeId}/analise/relacao?${q.toString()}` : null;
  const { dados, carregando, erro } = useApiExata<RespostaRelacao>(url);

  const metricas = dados?.metricas_disponiveis?.length ? dados.metricas_disponiveis : METRICAS_RELACAO;
  const rotuloMetrica = dados?.metrica?.rotulo ?? metricas.find((m) => m.chave === metrica)?.rotulo ?? metrica;
  const avisosResultado = (dados?.avisos ?? []).filter((t) => !ehAvisoCausalidade(t));
  const rotuloIndicador = [indicador?.nome, rotuloEtapa(etapa), rotuloComponente(componente)].filter(Boolean).join(" · ");
  const ic = intervalo(dados?.ic95 ?? null);
  const textos = (dados
    ? (dados.textos.length > 0 ? dados.textos : dados.motivos.map((m) => MOTIVOS_RELACAO[m] ?? m))
    : []).map(semAnoRepetido);
  const interpretacao = dados?.interpretacao ? semCausalidade(dados.interpretacao, dados.avisos ?? []) : null;

  return (
    <div className="space-y-5">
      <Card className="space-y-5 p-6">
        <div className="space-y-1.5">
          <h2 className={TITULO_CARTAO}>
            <IconePastel icone={ChartScatter} tom="teal" tamanho="sm" /> O que dá para relacionar hoje
          </h2>
          <OQueDaParaRelacionar base={base} />
        </div>
        <EscolhaIndicador legenda="Indicador oficial (por escola)" indicadores={base.indicadores}
                          selecionado={indicador?.chave ?? null} bloqueio={bloqueio}
                          aoEscolher={(c) => atualizar({ indicador: c, etapa: null, componente: null, edicao: null,
                                                         metrica: null })} />
        {indicador && (
          <div className="flex flex-wrap items-end gap-3" data-testid="dimensoes-relacao">
            {indicador.etapas.length > 0 && (
              <Seletor rotulo="Etapa" valor={etapa ?? ""} aoMudar={(v) => atualizar({ etapa: v || null })}>
                {indicador.etapas.map((e) => <option key={e} value={e}>{rotuloEtapa(e)}</option>)}
              </Seletor>
            )}
            {indicador.componentes.length > 0 && (
              // Outra área: a métrica escolhida antes (de outra plataforma) não vale — volta à do componente.
              <Seletor rotulo="Componente" valor={componente ?? ""}
                       aoMudar={(v) => atualizar({ componente: v || null, metrica: null })}>
                {indicador.componentes.map((c) => <option key={c} value={c}>{rotuloComponente(c)}</option>)}
              </Seletor>
            )}
            <Seletor rotulo="Edição" valor={edicao == null ? "" : String(edicao)}
                     aoMudar={(v) => atualizar({ edicao: v || null })}>
              {[...indicador.edicoes].sort((a, b) => b - a).map((e) => <option key={e} value={e}>{e}</option>)}
            </Seletor>
            <Seletor rotulo="Métrica da plataforma" valor={metrica} aoMudar={(v) => atualizar({ metrica: v })}>
              {(["elefante", "matific"] as const).map((pl) => (
                <optgroup key={pl} label={componente && COMPONENTE_DA_PLATAFORMA[pl] !== componente
                  ? `${ROTULO_PLATAFORMA[pl]} — outra área (${rotuloComponente(COMPONENTE_DA_PLATAFORMA[pl])})`
                  : ROTULO_PLATAFORMA[pl]}>
                  {metricas.filter((m) => m.plataforma === pl).map((m) => (
                    <option key={m.chave} value={m.chave}>{m.rotulo}</option>
                  ))}
                </optgroup>
              ))}
            </Seletor>
          </div>
        )}
        <FiltrosAplicados testId="filtros-relacao">
          Vale aqui: o período ({rotuloPeriodo(periodo)}) para o lado da plataforma — ele precisa caber no ano letivo
          da edição. A série vem da etapa (2º ano ↔ 2º ano; 5º ano ↔ 5º ano; anos iniciais ↔ 1º ao 5º ano). O filtro
          Escola não se aplica: a relação compara as escolas da rede.
        </FiltrosAplicados>
      </Card>

      <p className="flex items-start gap-3 rounded-2xl border border-ouro-200 bg-ouro-50 px-4 py-3.5 text-xs text-zinc-800 dark:border-ouro-400/25 dark:bg-ouro-400/10 dark:text-zinc-100"
         data-testid="aviso-causalidade">
        <span aria-hidden className="grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-white text-ouro-700 shadow-sm dark:bg-zinc-900/70 dark:text-ouro-300">
          <AlertTriangle size={14} />
        </span>
        <span>
          <b>Correlação não é causalidade.</b> Mesmo quando os dois números andam juntos entre as escolas, isso não
          mostra que o uso da plataforma causou o resultado oficial (nem o contrário): a avaliação mede outras crianças
          ou outro momento, e muitas coisas da escola pesam nos dois lados.
        </span>
      </p>

      {!indicador ? (
        <Card className="p-6">
          <p className={`text-sm ${CINZA}`}>Nenhum indicador oficial por escola disponível para relacionar.</p>
        </Card>
      ) : (
        <Card className="space-y-5 p-6" >
          <h2 className={`${TITULO_CARTAO} flex-wrap`}>
            <IconePastel icone={ChartScatter} tom="violeta" tamanho="sm" />
            {rotuloIndicador}{edicao != null ? ` (${edicao})` : ""} × {rotuloMetrica}
          </h2>
          {erro && !dados ? (
            <Mensagem tipo="erro">Não foi possível carregar a relação: {erro.message}</Mensagem>
          ) : !dados ? (
            carregando || url ? <Carregando texto="Conferindo se dá para calcular..." /> : null
          ) : (
            <>
              {dados.calculavel ? (
                <div className="space-y-3" data-testid="relacao-calculavel">
                  <Badge tom="ok">Dá para calcular</Badge>
                  <Dispersao pares={dados.pares} rotuloX={rotuloMetrica} rotuloY={rotuloIndicador} />
                  {dados.coeficiente != null && (
                    <p className="text-sm" data-testid="relacao-coeficiente">
                      Coeficiente de Spearman: <b className="tabular-nums">{coef(dados.coeficiente)}</b>
                      {ic && <> · IC 95%: <span className="tabular-nums">{coef(ic[0])} a {coef(ic[1])}</span></>}
                      {" "}· n = {dados.n} escola{dados.n === 1 ? "" : "s"}
                    </p>
                  )}
                  {dados.coeficiente != null && (interpretacao || ic) && (
                    <p className="text-xs text-zinc-600 dark:text-zinc-300" data-testid="relacao-interpretacao">
                      {interpretacao
                        || (ic && ic[0] <= 0 && ic[1] >= 0
                          ? "O intervalo de 95% inclui o zero: com estas escolas, não dá para afirmar que os dois números andam juntos."
                          : `Nestas escolas, quem tem “${rotuloMetrica}” mais alto tende a ter o resultado oficial ${
                            dados.coeficiente > 0 ? "mais alto" : "mais baixo"} — uma associação, não uma causa.`)}
                    </p>
                  )}
                </div>
              ) : (
                <div className="space-y-2" data-testid="relacao-nao-calculavel">
                  <Badge tom="alerta">Não dá para calcular a relação</Badge>
                  <ul className="list-disc space-y-0.5 pl-4 text-sm text-zinc-700 dark:text-zinc-200">
                    {textos.map((t) => <li key={t}>{t}</li>)}
                  </ul>
                  <p className={`text-xs ${CINZA}`}>
                    Nenhum coeficiente é mostrado. Abaixo, os dois números de cada escola, cada um com o seu ano.
                  </p>
                </div>
              )}
              {avisosResultado.length > 0 && (
                <ul className="list-disc space-y-0.5 pl-4 text-xs text-zinc-600 dark:text-zinc-300">
                  {avisosResultado.map((t) => <li key={t}>{t}</li>)}
                </ul>
              )}
              <LadoALado resp={dados} rotuloIndicador={rotuloIndicador} rotuloMetrica={rotuloMetrica} />
            </>
          )}
        </Card>
      )}

      <SecaoRecolhivel titulo="Metodologia da relação" inicialAberto={false}>
        <div className="space-y-2 text-xs text-zinc-600 dark:text-zinc-300" data-testid="relacao-metodologia">
          <p>{dados?.metodologia || METODOLOGIA_PADRAO}</p>
          {dados?.criterios && <Criterios c={dados.criterios} />}
        </div>
      </SecaoRecolhivel>
    </div>
  );
}
