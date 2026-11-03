/**
 * Blocos do ENGAJAMENTO nas plataformas (Elefante Letrado e Matific) — agregados
 * por rede, escola e série escolar, no período escolhido. Nunca há dado de aluno:
 * a célula com poucos alunos chega SUPRIMIDA do backend (com o texto único da
 * supressão) e a tela diz isso; métrica sem dado é "sem dado no período" (ou o
 * motivo), nunca 0.
 *
 * O DENOMINADOR é o dos alunos que a plataforma conhece no período (`alunos_medidos`:
 * no Elefante, quem tem conta; no Matific, quem tem coleta no período) — o mesmo do
 * percentual. Quem fica fora (sem conta, escola sem coleta em dia, série suprimida)
 * é dito à parte e não conta como zero. Os blocos da rede (e os da escola com série
 * suprimida) somam só o que está à vista (`texto_blocos`, do backend).
 *
 * Os números vêm arredondados pelo backend (per capita em até 2 casas, percentuais
 * em 1): a tela mostra como recebe, sem inventar casas.
 */
import { BookOpen, Calculator } from "lucide-react";
import type { ReactNode } from "react";

import { TabelaRolavel } from "../../components/TabelaRolavel";
import { IconePastel } from "../../components/ui";
import { Recolhivel } from "./DetalhesFonte";
import { TD, TH } from "./comum";
import { decimal, diaBR, rotuloSerie } from "./formato";
import type {
  CoberturaDoBloco, CoberturaPlataformas as Cobertura, EscolaDaRede, EscolaPlataformas, MetricasElefante,
  MetricasMatific, SeriePlataforma,
} from "./tipos";

const SEM_DADO = "sem dado no período";
/** O texto único da supressão (o backend manda o dele; este é só o plano B). */
export const TEXTO_SUPRESSAO_PADRAO =
  "poucos alunos neste recorte (ou escondido junto com um recorte pequeno): os números não aparecem, "
  + "para proteger as crianças";

const CINZA = "text-zinc-600 dark:text-zinc-400";

/** Coluna da série presa à ESQUERDA no celular (< 640 px): ao deslizar a tabela, as
 *  colunas do Elefante e do Matific passam ao lado da série. Do sm para cima, célula comum. */
const PRESA_ESQUERDA_CELULAR = "presa-esquerda-celular"; // index.css (irmã da presa-celular)

/** Uma métrica = 3 linhas (rótulo, valor, detalhe) de uma SUBGRADE da lista: as duas
 *  métricas lado a lado dividem as mesmas linhas, então quando um rótulo quebra em
 *  duas linhas ("Livros novos por aluno") o valor do vizinho desce junto e os números
 *  ficam alinhados. */
function Metrica({ rotulo, valor, detalhe }: { rotulo: string; valor: string | null; detalhe?: string | null }) {
  return (
    <div className="row-span-3 grid min-w-0 grid-rows-subgrid gap-y-0">
      <dt className={`self-end text-xs font-medium ${CINZA}`}>{rotulo}</dt>
      <dd className={`break-words ${valor == null ? `text-xs ${CINZA}` : "text-xl font-bold tabular-nums tracking-tight text-zinc-900 dark:text-white"}`}>
        {valor ?? SEM_DADO}
      </dd>
      {detalhe && <dd className={`text-xs ${CINZA}`}>{detalhe}</dd>}
    </div>
  );
}

function Plataforma({ titulo, icone, children, testId, nivel }: {
  titulo: string; icone: ReactNode; children: ReactNode; testId: string; nivel: 3 | 4;
}) {
  const Titulo = nivel === 3 ? "h3" : "h4";
  return (
    <section className="min-w-0 rounded-2xl border border-zinc-200/70 bg-zinc-50/70 p-5 dark:border-zinc-800 dark:bg-zinc-800/40" aria-label={titulo}
             data-testid={testId}>
      <Titulo className="mb-4 flex items-center gap-2.5 text-[15px] font-semibold text-zinc-900 dark:text-white">{icone} {titulo}</Titulo>
      {children}
    </section>
  );
}

const pct = (v: number | null | undefined) => (v == null ? null : `${decimal(v, 1)}%`);
const inteiro = (n: number) => n.toLocaleString("pt-BR");

/** "5 de 7 alunos com conta leram no período" — o MESMO denominador do percentual. */
function participacaoElefante(m: MetricasElefante): string | null {
  if (m.alunos_com_leitura == null || m.alunos_medidos == null) return null;
  return `${inteiro(m.alunos_com_leitura)} de ${inteiro(m.alunos_medidos)} alunos com conta leram no período`;
}

/** O Matific não manda quem fez atividade (o total refaria a célula): só o denominador. */
function participacaoMatific(m: MetricasMatific): string | null {
  if (m.alunos_medidos == null) return null;
  return `sobre ${inteiro(m.alunos_medidos)} alunos com dado no período`;
}

/** Quem do recorte NÃO entra na conta da plataforma — dito à parte, nunca como zero. */
function foraDaConta(alunos: number | null, medidos: number | null | undefined, plataforma: "elefante" | "matific") {
  if (alunos == null || medidos == null || medidos >= alunos) return null;
  const porque = plataforma === "elefante" ? "sem conta no Elefante" : "sem dado do Matific no período";
  return `${inteiro(alunos - medidos)} de ${inteiro(alunos)} alunos do recorte não entram na conta: ${porque}, `
    + "de escola sem coleta em dia ou de série com poucos alunos (não contam como zero).";
}

/** A coleta parou antes do fim do período: os números valem só até `coberto_ate`. */
function ColetaParcial({ bloco, testId }: { bloco: CoberturaDoBloco; testId: string }) {
  if (!bloco.coleta_parcial) {
    // Bloco da rede: escolas com a coleta parada, mas cobrindo quase todo o período, entram
    // na soma — a data até onde valem vem junto.
    if (!bloco.texto_parcial_na_soma) return null;
    return (
      <p className="mt-2 text-xs text-amber-800 dark:text-amber-300" data-testid={`${testId}-na-soma`}>
        <span className="font-semibold">Coleta parcial:</span> {bloco.texto_parcial_na_soma}
      </p>
    );
  }
  return (
    <p className="mt-2 text-xs text-amber-800 dark:text-amber-300" data-testid={testId}>
      <span className="font-semibold">Coleta parcial:</span>{" "}
      {bloco.texto_cobertura ?? `os números valem só até ${diaBR(bloco.coberto_ate) ?? "a última coleta"}`}
    </p>
  );
}

/** Uma nota curta do backend sob as métricas (o texto vem pronto; sem texto, nada). */
function Nota({ rotulo, texto, testId }: { rotulo: string; texto?: string | null; testId: string }) {
  if (!texto) return null;
  return (
    <p className={`mt-2 text-xs ${CINZA}`} data-testid={testId}>
      <span className="font-semibold">{rotulo}:</span> {texto}.
    </p>
  );
}

/** Sem dado nenhum da plataforma no recorte: diz o porquê, uma vez (não 5 "sem dado"). */
function semDado(m: { texto_sem_dado?: string | null; motivo_sem_dado?: string | null } | null): string | null {
  if (!m) return null;
  return m.texto_sem_dado ?? (m.motivo_sem_dado ? SEM_DADO : null);
}

/** Os dois cartões (Elefante e Matific) de um recorte: rede inteira, escola ou série. */
export function CartoesPlataformas({
  alunos, elefante, matific, modulos, suprimido, textoSupressao, textoBlocos, nivelTitulo = 4,
}: {
  alunos: number | null;
  elefante: MetricasElefante | null;
  matific: MetricasMatific | null;
  modulos?: { elefante: boolean; matific: boolean };
  suprimido?: boolean;
  textoSupressao?: string | null;
  /** "Os números … somam só as escolas/séries mostradas" (o backend diz quando vale). */
  textoBlocos?: string | null;
  /** O nível do título de cada plataforma (3 sob um h2; 4 sob um h3). */
  nivelTitulo?: 3 | 4;
}) {
  if (suprimido) {
    return (
      <p className={`text-sm ${CINZA}`} data-testid="plataformas-suprimidas">
        Números ocultos: {textoSupressao ?? TEXTO_SUPRESSAO_PADRAO}.
      </p>
    );
  }
  const comElefante = modulos?.elefante ?? true;
  const comMatific = modulos?.matific ?? true;
  if (!comElefante && !comMatific) {
    return <p className={`text-sm ${CINZA}`}>A rede não tem módulo de plataforma contratado.</p>;
  }
  const semElefante = semDado(elefante);
  const semMatific = semDado(matific);
  const foraElefante = elefante && !semElefante ? foraDaConta(alunos, elefante.alunos_medidos, "elefante") : null;
  const foraMatific = matific && !semMatific ? foraDaConta(alunos, matific.alunos_medidos, "matific") : null;
  return (
    <div className="space-y-2">
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {comElefante && (
          <Plataforma titulo="Elefante Letrado (leitura)" testId="plataforma-elefante" nivel={nivelTitulo}
                      icone={<IconePastel icone={BookOpen} tom="violeta" tamanho="sm" />}>
            {elefante && !semElefante ? (
              <>
                <dl className="grid grid-cols-2 gap-x-4 gap-y-3">
                  <Metrica rotulo="Participação" valor={pct(elefante.participacao_pct)}
                           detalhe={participacaoElefante(elefante)} />
                  <Metrica rotulo="Livros novos por aluno" valor={decimal(elefante.livros_por_aluno)} />
                  <Metrica rotulo="Minutos por aluno"
                           valor={elefante.minutos_por_aluno == null ? null : `${decimal(elefante.minutos_por_aluno, 1)} min`} />
                  <Metrica rotulo="Nível médio dos livros" valor={elefante.nivel_medio} />
                  <Metrica rotulo="Acerto nas questões" valor={pct(elefante.taxa_acerto_pct)}
                           detalhe={elefante.janela_questoes?.inicio && elefante.janela_questoes.fim
                             ? `medido de ${diaBR(elefante.janela_questoes.inicio)} a ${diaBR(elefante.janela_questoes.fim)} (coletas)`
                             : null} />
                </dl>
                {foraElefante && (
                  <p className={`mt-2 text-xs ${CINZA}`} data-testid="fora-da-conta-elefante">{foraElefante}</p>
                )}
                <Nota rotulo="Questões" texto={elefante.texto_contador_regrediu} testId="contador-regrediu-elefante" />
                <Nota rotulo="Médias ocultas" texto={elefante.texto_metricas_protegidas}
                      testId="metricas-protegidas-elefante" />
                <ColetaParcial bloco={elefante} testId="coleta-parcial-elefante" />
              </>
            ) : (
              <p className={`text-xs ${CINZA}`}>Sem dado do Elefante: {semElefante ?? SEM_DADO}.</p>
            )}
          </Plataforma>
        )}
        {comMatific && (
          <Plataforma titulo="Matific (matemática)" testId="plataforma-matific" nivel={nivelTitulo}
                      icone={<IconePastel icone={Calculator} tom="teal" tamanho="sm" />}>
            {matific && !semMatific ? (
              <>
                <dl className="grid grid-cols-2 gap-x-4 gap-y-3">
                  <Metrica rotulo="Participação" valor={pct(matific.participacao_pct)}
                           detalhe={participacaoMatific(matific)} />
                  <Metrica rotulo="Atividades por aluno" valor={decimal(matific.atividades_por_aluno)} />
                  <Metrica rotulo="Estrelas por aluno" valor={decimal(matific.estrelas_por_aluno)} />
                  <Metrica rotulo="Desempenho médio" valor={matific.desempenho_medio == null ? null
                           : `${decimal(matific.desempenho_medio)} de 5`}
                           detalhe="estrelas por atividade" />
                </dl>
                {foraMatific && (
                  <p className={`mt-2 text-xs ${CINZA}`} data-testid="fora-da-conta-matific">{foraMatific}</p>
                )}
                <Nota rotulo="Médias ocultas" texto={matific.texto_metricas_protegidas}
                      testId="metricas-protegidas-matific" />
                <ColetaParcial bloco={matific} testId="coleta-parcial-matific" />
              </>
            ) : (
              <p className={`text-xs ${CINZA}`}>Sem dado do Matific: {semMatific ?? SEM_DADO}.</p>
            )}
          </Plataforma>
        )}
      </div>
      {textoBlocos && (
        <p className={`text-xs ${CINZA}`} data-testid="texto-blocos">{textoBlocos}</p>
      )}
    </div>
  );
}

/** Uma linha por série escolar (1º–5º ano). Célula pequena: números ocultos, com o porquê. */
export function TabelaSeriesPlataformas({ series, modulos, serieFiltro, legenda }: {
  series: SeriePlataforma[];
  modulos?: { elefante: boolean; matific: boolean };
  serieFiltro?: number | null;
  legenda: string;
}) {
  const comElefante = modulos?.elefante ?? true;
  const comMatific = modulos?.matific ?? true;
  const linhas = [...series]
    .filter((s) => serieFiltro == null || s.serie === serieFiltro)
    .sort((a, b) => a.serie - b.serie);
  if (linhas.length === 0) {
    return <p className={`text-xs ${CINZA}`}>Nenhuma série do 1º ao 5º ano com alunos neste recorte.</p>;
  }
  const colunas = 2 + (comElefante ? 3 : 0) + (comMatific ? 3 : 0);
  const v = (x: string | null) => x ?? <span className={`text-xs ${CINZA}`}>{SEM_DADO}</span>;
  return (
    <div className="space-y-1">
      {/* No celular a tabela rola de lado, com o aviso "Deslize..." em cima e a série presa
          à esquerda: a comparação por série (Elefante e Matific) continua alcançável. */}
      <TabelaRolavel rotulo={`${legenda}: tabela completa`}>
        <table className="w-full text-xs" data-testid="tabela-series-plataformas">
          <caption className="sr-only">{legenda}</caption>
          <thead>
            <tr className={`border-b border-zinc-200 dark:border-zinc-800 ${CINZA}`}>
              <th className={`${TH} ${PRESA_ESQUERDA_CELULAR}`} scope="col">Série</th>
              <th className={TH} scope="col">Alunos</th>
              {comElefante && <>
                <th className={TH} scope="col">Elefante: participação</th>
                <th className={TH} scope="col">Livros/aluno</th>
                <th className={TH} scope="col">Min/aluno</th>
              </>}
              {comMatific && <>
                <th className={TH} scope="col">Matific: participação</th>
                <th className={TH} scope="col">Atividades/aluno</th>
                <th className={TH} scope="col">Desempenho (0–5)</th>
              </>}
            </tr>
          </thead>
          <tbody>
            {linhas.map((s) => (
              <tr key={s.serie} className="border-b border-zinc-100 last:border-0 dark:border-zinc-800/60">
                <th scope="row" className={`${TD} whitespace-nowrap text-left font-medium ${PRESA_ESQUERDA_CELULAR}`}>
                  {rotuloSerie(s.serie)}
                </th>
                {s.suprimido ? (
                  <td colSpan={colunas - 1} className={`${TD} ${CINZA}`}>
                    {s.texto_supressao ?? TEXTO_SUPRESSAO_PADRAO}
                  </td>
                ) : (
                  <>
                    <td className={TD}>{s.alunos == null ? "—" : inteiro(s.alunos)}</td>
                    {comElefante && <>
                      <td className={TD}>{v(pct(s.elefante?.participacao_pct))}</td>
                      <td className={TD}>{v(decimal(s.elefante?.livros_por_aluno))}</td>
                      <td className={TD}>{v(decimal(s.elefante?.minutos_por_aluno, 1))}</td>
                    </>}
                    {comMatific && <>
                      <td className={TD}>{v(pct(s.matific?.participacao_pct))}</td>
                      <td className={TD}>{v(decimal(s.matific?.atividades_por_aluno))}</td>
                      <td className={TD}>{v(decimal(s.matific?.desempenho_medio))}</td>
                    </>}
                  </>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </TabelaRolavel>
      <p className={`text-xs ${CINZA}`} data-testid="legenda-denominador">
        Participação e médias por aluno: sobre os alunos que a plataforma conhece no período (Elefante: com conta;
        Matific: com dado no período). Quem fica fora não conta como zero.
      </p>
    </div>
  );
}

const ROTULO_PLATAFORMA: Record<string, string> = { elefante: "Elefante", matific: "Matific" };

/**
 * Até onde as coletas cobrem: última coleta, escolas sem coleta, coleta parcial e o 1º
 * evento do Elefante. Só as escolas VISÍVEIS: a escola suprimida (poucos alunos) não
 * aparece aqui — nem a cobertura nem as datas dela.
 */
export function CoberturaDasColetas({ cobertura, escolas, escolasPlataformas }: {
  cobertura: Cobertura;
  escolas: EscolaDaRede[];
  /** As escolas da resposta das plataformas (a data até onde cada coleta parcial vale). */
  escolasPlataformas?: EscolaPlataformas[];
}) {
  const { ultima_coleta: u, dias_desde_ultima_coleta: dias } = cobertura;
  const nome = (id: number) => escolas.find((e) => e.id === id)?.nome ?? `escola ${id}`;
  // Quem não tem coleta NENHUMA já aparece na linha própria: aqui, só a falta no período.
  const semNoPeriodo = Object.entries(cobertura.escolas_sem_coleta_no_periodo ?? {})
    .map(([p, ids]) => [p, ids.filter((id) => !cobertura.escolas_sem_coleta.includes(id))] as const)
    .filter(([, ids]) => ids.length > 0);
  const parciais = Object.entries(cobertura.escolas_coleta_parcial ?? {}).filter(([, ids]) => ids.length > 0);
  const ate = (id: number, p: string) => {
    const e = escolasPlataformas?.find((x) => x.escola_id === id);
    const d = diaBR(e?.coberto_ate?.[p as "elefante" | "matific"] ?? null);
    return d ? `${nome(id)} (até ${d})` : nome(id);
  };
  const semNenhuma = cobertura.escolas_sem_coleta.map(nome);
  const partes = [
    u.elefante ? `Elefante ${diaBR(u.elefante)}` : null,
    u.matific ? `Matific ${diaBR(u.matific)}` : null,
  ].filter(Boolean);
  const temSuprimida = (escolasPlataformas ?? []).some((e) => e.suprimido);
  return (
    <div className={`space-y-0.5 text-xs ${CINZA}`} data-testid="cobertura-coletas">
      <p>
        Última coleta: {partes.length ? partes.join(" · ") : "nenhuma coleta registrada"}
        {/* "(há 0 dias)" soava como erro: a coleta do dia é "(hoje)", como no selo do Ranking. */}
        {dias == null ? "" : dias === 0 ? " (hoje)" : ` (há ${dias} dia${dias === 1 ? "" : "s"})`}.
        {cobertura.primeiro_evento_elefante
          && ` O histórico do Elefante começa em ${diaBR(cobertura.primeiro_evento_elefante)}.`}
      </p>
      {semNenhuma.length > 0 && (
        <p className="text-amber-800 dark:text-amber-300">
          Sem nenhuma coleta: {semNenhuma.join(", ")} — essas escolas ficam sem número (não contam como zero).
        </p>
      )}
      {semNoPeriodo.map(([plataforma, ids]) => (
        <p key={plataforma} className="text-amber-800 dark:text-amber-300">
          {ROTULO_PLATAFORMA[plataforma] ?? plataforma} sem coleta que cubra o período: {ids.map(nome).join(", ")}
          {" "}(sem número, não zero).
        </p>
      ))}
      {parciais.map(([plataforma, ids]) => (
        <p key={`parcial-${plataforma}`} className="text-amber-800 dark:text-amber-300"
           data-testid={`coleta-parcial-rede-${plataforma}`}>
          {ROTULO_PLATAFORMA[plataforma] ?? plataforma} com a coleta parada antes do fim do período:{" "}
          {ids.map((id) => ate(id, plataforma)).join(", ")} — os números delas valem só até essa data; entram na
          soma da rede só se a coleta cobre ao menos 90% do período.
        </p>
      ))}
      {temSuprimida && (
        <p>As escolas com poucos alunos não aparecem nestas listas nem na soma da rede, para proteger as crianças.</p>
      )}
    </div>
  );
}

/** As limitações dos dados das plataformas, recolhidas ("como ler estes números"). */
export function LimitacoesPlataformas({ limitacoes }: { limitacoes: string[] | undefined }) {
  if (!limitacoes || limitacoes.length === 0) return null;
  return (
    <Recolhivel titulo="Como ler estes números (limitações)" testId="limitacoes-plataformas">
      <ul className="list-disc space-y-1 pl-4">
        {limitacoes.map((t) => <li key={t}>{t}</li>)}
      </ul>
    </Recolhivel>
  );
}
