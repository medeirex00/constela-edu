/**
 * PANORAMA DA REDE — a tela inicial da Secretaria (`/`, pelo Dashboard) e a "Visão da rede" do
 * admin global (`/rede/visao`, com o seletor de rede). DESENHO3 §2.
 *
 * Conclusão primeiro, de cima para baixo (cada número com "O que mede" e o selo de natureza):
 *
 *  1. Cabeçalho: o nome da rede e de quando são os dados (o selo de frescor);
 *  2. "A rede no Constela": escolas CADASTRADAS, ATIVAS no cadastro, COM USO no ano letivo e as
 *     demais por extenso (sem uso registrado · sem dado · protegidas) — não são sinônimos: a
 *     ativa é só a situação do cadastro;
 *  3. "Participação no ano letivo": por plataforma CONTRATADA, a participação da rede e um
 *     número de intensidade (livros novos / atividades por aluno), o período e a última coleta;
 *  4. "Todas as escolas da rede": TODAS (inclusive inativas, sem alunos e sem avaliação externa),
 *     em ordem alfabética — não é ranking —, com o cadastro, os alunos (todas as etapas), a
 *     situação de uso por plataforma e a geral, o filtro por situação e o link para a ficha; no
 *     celular, cartões. A lista sai do PAINEL: se a leitura do uso falhar, as escolas continuam
 *     (cadastro, alunos e a ficha), com "não foi possível carregar o uso" por extenso e sem filtro;
 *  5. "Escolas em destaque": o critério escrito (o mesmo da vitrine pública) e as escolas de cada
 *     plataforma contratada (`GET /redes/{id}/destaques`), com o link para a ficha e para o
 *     Ranking da Rede (que é OUTRA medida: a pontuação do Constela — a tela diz isso); logo
 *     abaixo, "Reconhecimento público" (a vitrine: ligar, copiar, abrir);
 *  6. "Metas da rede", recolhida: o progresso e o cadastro (os mesmos cartões do Painel da Rede),
 *     com a nota de cada métrica dizendo de quando ela é (nem toda meta segue o ano letivo);
 *  7. Rodapé: o link para as Avaliações externas e a frase de que avaliações e plataformas são de
 *     períodos diferentes. As avaliações externas NÃO são o elemento principal daqui. Só para o
 *     admin global, os atalhos dos Relatórios e exportações e das Escolas em acompanhamento da
 *     rede escolhida (ele não tem esses itens no menu; a Secretaria não os usa daqui).
 *
 * Escolas em anos letivos diferentes (`janela.anos_letivos` com mais de um ano, na virada do ano):
 * os rótulos não afirmam um ano só e a tela diz que o uso de cada escola é o do ano letivo dela.
 *
 * O uso NUNCA é inferido do painel (`alunos_com_dados`/`adocao` são contas e retratos sem
 * período): a situação de cada escola vem de `situacaoDeUso` (as coletas do ano letivo). Ausência
 * e proteção por extenso, nunca 0.
 *
 * Leituras: o painel da rede (o cadastro de todas as escolas), as plataformas no ano letivo, os
 * destaques, o nome da rede (a Secretaria: `/redes`; o global já tem a lista), o frescor (selo) e
 * a vitrine; as metas só ao abrir o bloco. Só agregados; nenhum dado de aluno. Para o admin global,
 * todo link leva o `?rede=` (`ctx.link`), e as metas e a vitrine são as da rede escolhida aqui.
 */
import {
  Award, BookOpen, Calculator, ChevronDown, ListChecks, Megaphone, MonitorSmartphone, School, Target,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useId, useMemo, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";

import { SeloFrescorDaRede } from "../../../components/SeloFrescor";
import { Badge, Card, IconePastel, type TomPastel } from "../../../components/ui";
import { useModulos } from "../../../hooks/useModulos";
import { usePerfil } from "../../../hooks/usePerfil";
import type { ApiError } from "../../../lib/api";
import { numero } from "../../../lib/formato";
import { SeloNatureza, usePlataformasDaRede, type NaturezaSelo } from "../../analise/comum";
import { decimal, diaBR, numeroProtegido } from "../../analise/formato";
import type { MetricasElefante, MetricasMatific, RespostaPlataformas } from "../../analise/tipos";
import { MetasDaRede, VitrinePublica, type DashboardRede, type DestaquesRede, type ListaDeDestaques } from "../comum";
import {
  conclusaoPlataformas, conclusaoRedeNoConstela, textoDemaisSituacoes, textoDestaquesVazio, textoForaPorProtecao,
  textoReconhecimentoPublico,
} from "./conclusoes";
import {
  FRASE_PLATAFORMA, METRICAS_ELEFANTE, METRICAS_MATIFIC, NOTA_DAS_METAS_NO_PANORAMA, O_QUE_MEDE_REDE,
  ROTULO_LINK_RANKING, criterioDosDestaques, fraseAnosMistos, fraseRankingOutraMedida, textoEscolasNaSoma,
  type ModulosDaRede,
} from "./oQueMede";
import {
  AvisoOutraRede, CINZA, CabecalhoDaPagina, ComoLer, EstadoDaLeitura, FraseSeparacao, LinkVer, OQueMede,
  PaginaDaRede, TITULO_SECAO, type ContextoDaPagina,
} from "./pecas";
import {
  NOME_PLATAFORMA, ROTULO_ESTADO, ROTULO_PLATAFORMA, classificarRede, complementoDoGeral, contarSituacoes,
  datasDoSemUsoParcial, escolasDoCadastro, type EscolaDoCadastro, type EstadoUso, type Plataforma,
  type SituacaoEscola,
} from "./situacaoDeUso";
import {
  ANO_LETIVO, anoDaJanela, useDashboardDaRede, useDestaques, useNomeDaRede,
} from "./useRedeDaPagina";

const PLATAFORMAS: Plataforma[] = ["elefante", "matific"];
const pct = (v: number | null | undefined) => (v == null ? null : `${decimal(v, 1)}%`);
const CLASSE_LINK = "font-semibold text-indigo-700 underline-offset-2 hover:underline dark:text-indigo-300";

/** A frase dos anos letivos misturados (escolas medidas cada uma no ano letivo dela). */
function AnosMistos({ anos, testId }: { anos: number[]; testId: string }) {
  return <p className={`text-xs ${CINZA}`} data-testid={testId}>{fraseAnosMistos(anos)}</p>;
}

/** A resposta sem o ano de referência na janela (com anos letivos misturados): a conclusão diz
 *  "No ano letivo", sem afirmar o ano mais comum como se fosse o de todas as escolas. */
const semAnoNaJanela = (dados: RespostaPlataformas): RespostaPlataformas =>
  ({ ...dados, janela: { ...dados.janela, ano_letivo: null, inicio: null, fim: null } });

/** A cor da pílula de cada situação (o texto sempre diz a situação: a cor nunca é o único código). */
const TOM_ESTADO: Record<EstadoUso, "ok" | "alerta" | "neutro" | "info"> = {
  com_uso: "ok",
  sem_uso: "alerta",
  sem_dado: "neutro",
  protegido: "info",
};

function PilulaEstado({ estado, rotulo }: { estado: EstadoUso; rotulo: string }) {
  return (
    <span className="inline-flex max-w-full" data-estado={estado}>
      <Badge tom={TOM_ESTADO[estado]}>{rotulo}</Badge>
    </span>
  );
}

// --- Seção -----------------------------------------------------------------------------------

function Secao({ titulo, icone, tom, natureza, descricao, testId, children }: {
  titulo: string;
  icone: LucideIcon;
  tom: TomPastel;
  natureza?: NaturezaSelo;
  descricao?: ReactNode;
  testId: string;
  children: ReactNode;
}) {
  const id = useId();
  return (
    <section className="min-w-0 space-y-4" aria-labelledby={id} data-testid={testId}>
      <div className="space-y-1.5">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
          <h2 id={id} className={TITULO_SECAO}>
            <IconePastel icone={icone} tom={tom} tamanho="sm" />
            <span className="min-w-0 break-words">{titulo}</span>
          </h2>
          {natureza && <SeloNatureza natureza={natureza} />}
        </div>
        {descricao && <p className={`max-w-3xl text-sm ${CINZA}`}>{descricao}</p>}
      </div>
      {children}
    </section>
  );
}

/** A frase-conclusão de uma seção (o que os números dizem), antes do detalhe. */
function Conclusao({ testId, children }: { testId: string; children: ReactNode }) {
  return (
    <p className="text-base font-semibold leading-snug text-zinc-900 dark:text-white" data-testid={testId}>{children}</p>
  );
}

// --- 2. A rede no Constela -------------------------------------------------------------------

function NumeroDaRede({ testId, rotulo, valor, detalhe, oQueMede }: {
  testId: string; rotulo: string; valor: ReactNode; detalhe?: ReactNode; oQueMede: string;
}) {
  return (
    <Card className="flex min-w-0 flex-col p-4">
      <div className="flex min-w-0 flex-1 flex-col gap-1.5 break-words" data-testid={testId}>
        <p className={`text-xs font-semibold ${CINZA}`}>{rotulo}</p>
        <p className="text-2xl font-bold tabular-nums tracking-tight text-zinc-900 dark:text-white">{valor}</p>
        {detalhe && <p className="text-xs text-zinc-700 dark:text-zinc-200">{detalhe}</p>}
        <OQueMede texto={oQueMede} className="mt-auto pt-1" />
        <p className="pt-0.5"><SeloNatureza natureza="calculado" /></p>
      </div>
    </Card>
  );
}

/** O valor de um número que depende de uma leitura: carregando e falha por extenso (nunca 0). */
function ValorDaLeitura({ pronto, erro, children }: { pronto: boolean; erro: boolean; children: ReactNode }) {
  if (pronto) return <>{children}</>;
  return (
    <span className={`text-sm font-medium ${CINZA}`}>{erro ? "não foi possível carregar" : "carregando..."}</span>
  );
}

function RedeNoConstela({ painel, situacoes, erroUso, modulos, ano, anosMistos }: {
  painel: { dados: DashboardRede | null; erro: ApiError | null };
  situacoes: SituacaoEscola[] | null;
  erroUso: boolean;
  modulos: ModulosDaRede;
  /** O ano letivo das plataformas (null com anos misturados: nenhum rótulo afirma um ano só). */
  ano: number | null;
  /** Os anos letivos das escolas, só quando são mais de um. */
  anosMistos: number[] | null;
}) {
  const t = painel.dados?.totais ?? null;
  const conta = situacoes ? contarSituacoes(situacoes) : null;
  const demais = conta ? conta.sem_uso + conta.sem_dado + conta.protegido : null;
  // As "sem uso registrado" com coleta parcial aparecem por extenso com a data.
  const semUsoParcial = situacoes ? datasDoSemUsoParcial(situacoes) : [];
  return (
    <>
      {t && (
        <Conclusao testId="conclusao-rede">
          {conclusaoRedeNoConstela(t.escolas, t.escolas_ativas, conta ? conta.com_uso : null, ano)}
        </Conclusao>
      )}
      {anosMistos && <AnosMistos anos={anosMistos} testId="anos-letivos-mistos" />}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4" data-testid="numeros-da-rede">
        <NumeroDaRede testId="numero-cadastradas" rotulo="Escolas cadastradas" oQueMede={O_QUE_MEDE_REDE.cadastradas}
                      valor={<ValorDaLeitura pronto={t != null} erro={Boolean(painel.erro)}>{numero(t?.escolas)}</ValorDaLeitura>} />
        <NumeroDaRede testId="numero-ativas" rotulo="Ativas no cadastro" oQueMede={O_QUE_MEDE_REDE.ativas}
                      valor={<ValorDaLeitura pronto={t != null} erro={Boolean(painel.erro)}>{numero(t?.escolas_ativas)}</ValorDaLeitura>} />
        <NumeroDaRede testId="numero-com-uso" rotulo="Com uso no ano letivo" oQueMede={O_QUE_MEDE_REDE.comUso(modulos)}
                      valor={<ValorDaLeitura pronto={conta != null} erro={erroUso}>{conta?.com_uso === 0 ? "nenhuma" : numero(conta?.com_uso)}</ValorDaLeitura>}
                      detalhe={anosMistos ? `ano letivo de cada escola (${anosMistos.join(", ")}), pelas coletas`
                        : ano != null ? `ano letivo de ${ano}, pelas coletas` : "pelas coletas"} />
        <NumeroDaRede testId="numero-demais" rotulo="Sem uso registrado, sem dado ou protegidas" oQueMede={O_QUE_MEDE_REDE.demais}
                      valor={<ValorDaLeitura pronto={demais != null} erro={erroUso}>{demais === 0 ? "nenhuma" : numero(demais)}</ValorDaLeitura>}
                      detalhe={conta && demais ? textoDemaisSituacoes(conta, semUsoParcial) : undefined} />
      </div>
    </>
  );
}

// --- 3. Participação no ano letivo -----------------------------------------------------------

/** Um número da rede numa plataforma: sem ele, "protegido" (escondido para proteger um grupo
 *  pequeno — o bloco inteiro ou só a métrica: `numeroProtegido`) ou "sem dado" — escritos,
 *  nunca 0. */
function MetricaDaRede({ rotulo, valor, campo, bloco, oQueMede, testId }: {
  rotulo: string;
  valor: string | null;
  campo: string;
  bloco: MetricasElefante | MetricasMatific | null;
  oQueMede: string;
  testId: string;
}) {
  const protegido = numeroProtegido(bloco, campo);
  return (
    <div className="rounded-xl bg-zinc-50 px-3 py-2 dark:bg-zinc-800/50" data-testid={testId}>
      <p className="flex flex-wrap items-baseline gap-x-2">
        <span className="text-sm font-medium text-zinc-700 dark:text-zinc-200">{rotulo}</span>
        {valor != null
          ? <span className="text-lg font-bold tabular-nums text-zinc-900 dark:text-white">{valor}</span>
          : <span className={`text-xs ${CINZA}`}>{protegido ? "protegido (poucos alunos)" : "sem dado no período"}</span>}
      </p>
      <OQueMede texto={oQueMede} className="mt-0.5" />
    </div>
  );
}

function CartaoParticipacao({ p, dados, anosMistos }: {
  p: Plataforma; dados: RespostaPlataformas; anosMistos: number[] | null;
}) {
  const id = useId();
  const elefante = p === "elefante";
  const bloco = dados.rede[p];
  const metricas = elefante ? METRICAS_ELEFANTE : METRICAS_MATIFIC;
  const participacao = metricas.find((m) => m.chave === "participacao_pct")!;
  const intensidade = metricas.find((m) => m.chave === (elefante ? "livros_por_aluno" : "atividades_por_aluno"))!;
  const valorIntensidade = elefante
    ? decimal((bloco as MetricasElefante | null)?.livros_por_aluno)
    : decimal((bloco as MetricasMatific | null)?.atividades_por_aluno);
  const j = dados.janela;
  const datas = j.inicio && j.fim ? ` (${diaBR(j.inicio)} a ${diaBR(j.fim)})` : "";
  const ultima = diaBR(dados.cobertura.ultima_coleta[p]);
  // Com anos letivos misturados, o rótulo da janela (o do ano mais comum) não vale para todas.
  const periodo = anosMistos ? `Ano letivo de cada escola (${anosMistos.join(", ")})` : `${j.rotulo}${datas}`;
  // Quantas escolas entraram no número da rede (só as com a coleta em dia somam). O bloco
  // protegido inteiro (poucos alunos medidos) não mostra soma nenhuma: não se diz de quais
  // escolas é um número que não aparece.
  const naSoma = numeroProtegido(bloco) ? null
    : textoEscolasNaSoma(dados.rede.escolas_com_dado?.[p], dados.escolas.length);
  return (
    <Card className="flex min-w-0 flex-col p-5">
      <article className="flex min-w-0 flex-1 flex-col gap-3" aria-labelledby={id} data-testid={`participacao-${p}`}>
        <h3 id={id} className="flex items-center gap-2.5 text-[15px] font-semibold text-zinc-900 dark:text-white">
          <IconePastel icone={elefante ? BookOpen : Calculator} tom={elefante ? "violeta" : "teal"} tamanho="sm" />
          <span className="min-w-0 break-words">{elefante ? "Elefante Letrado (leitura)" : "Matific (matemática)"}</span>
        </h3>
        <MetricaDaRede testId={`participacao-${p}-pct`} rotulo={participacao.rotulo} campo="participacao_pct"
                       valor={pct(bloco?.participacao_pct)} bloco={bloco} oQueMede={participacao.oQueMede} />
        <MetricaDaRede testId={`participacao-${p}-intensidade`} rotulo={intensidade.rotulo} campo={intensidade.chave}
                       valor={valorIntensidade} bloco={bloco} oQueMede={intensidade.oQueMede} />
        {naSoma && <p className={`text-xs ${CINZA}`} data-testid={`participacao-${p}-escolas`}>{naSoma}</p>}
        {bloco?.texto_parcial_na_soma && <p className={`text-xs ${CINZA}`}>{bloco.texto_parcial_na_soma}</p>}
        <p className={`mt-auto flex flex-wrap items-center gap-x-2 gap-y-1 text-xs ${CINZA}`} data-testid={`participacao-${p}-quando`}>
          <SeloNatureza natureza="plataforma" />
          <span className="min-w-0 break-words">
            {periodo}. Última coleta: {ultima ?? "nenhuma registrada"}.
          </span>
        </p>
      </article>
    </Card>
  );
}

function Participacao({ dados, ctx, anosMistos }: {
  dados: RespostaPlataformas; ctx: ContextoDaPagina; anosMistos: number[] | null;
}) {
  const contratadas = PLATAFORMAS.filter((p) => dados.modulos[p]);
  const comCartoes = !dados.rede.suprimido && contratadas.length > 0;
  return (
    <>
      <Conclusao testId="conclusao-plataformas">
        {conclusaoPlataformas(anosMistos ? semAnoNaJanela(dados) : dados)}
      </Conclusao>
      {anosMistos && <AnosMistos anos={anosMistos} testId="anos-letivos-mistos-participacao" />}
      <p className={`text-xs ${CINZA}`}>{FRASE_PLATAFORMA}</p>
      {/* O escopo dos números da rede: só as escolas com a coleta em dia entram na soma. */}
      {comCartoes && dados.rede.texto_blocos && (
        <p className={`text-xs ${CINZA}`} data-testid="participacao-escopo">{dados.rede.texto_blocos}</p>
      )}
      {comCartoes && (
        <div className={`grid grid-cols-1 gap-4 ${contratadas.length > 1 ? "lg:grid-cols-2" : ""}`}>
          {contratadas.map((p) => <CartaoParticipacao key={p} p={p} dados={dados} anosMistos={anosMistos} />)}
        </div>
      )}
      <LinkVer para={ctx.link("/rede/plataformas")}>Ver o uso em detalhe</LinkVer>
    </>
  );
}

// --- 4. Todas as escolas da rede -------------------------------------------------------------

/** A lista do Panorama: com a situação de uso de cada escola ou, quando a leitura do uso falhou,
 *  só o cadastro do painel (com o erro, dito por extenso). */
type ListaDasEscolas = { situacoes: SituacaoEscola[] } | { cadastro: EscolaDoCadastro[]; erroUso: ApiError };

type Filtro = "todas" | "com_uso" | "sem_uso" | "sem_dado";

const FILTROS: { valor: Filtro; rotulo: string }[] = [
  { valor: "todas", rotulo: "Todas" },
  { valor: "com_uso", rotulo: "Com uso" },
  { valor: "sem_uso", rotulo: "Sem uso registrado" },
  { valor: "sem_dado", rotulo: "Sem dado ou protegidas" },
];

const passaNoFiltro = (f: Filtro, s: SituacaoEscola) =>
  f === "todas" || (f === "sem_dado" ? s.geral === "sem_dado" || s.geral === "protegido" : s.geral === f);

/** O rótulo dos alunos da lista: o `total_alunos` do painel conta TODAS as etapas (a tela Escolas
 *  e o uso contam só do 1º ao 5º ano) — o rótulo diz isso, como a ficha. */
const ROTULO_ALUNOS = "Alunos no ano letivo (todas as etapas)";

/** O uso não carregou (a leitura das plataformas falhou): por extenso em cada escola. */
const USO_INDISPONIVEL = "não foi possível carregar o uso";

/** A grade das linhas no desktop (classes estáticas para o Tailwind): escola, cadastro, alunos,
 *  uma coluna por plataforma contratada e a situação geral (sem o uso: só a coluna "Situação de
 *  uso", na grade de 0 plataformas). Abaixo do `xl`, cartões. */
const GRADE_LINHA: Record<number, string> = {
  0: "xl:grid-cols-[minmax(0,2fr)_minmax(0,0.8fr)_minmax(0,0.8fr)_minmax(0,1.2fr)]",
  1: "xl:grid-cols-[minmax(0,1.8fr)_minmax(0,0.7fr)_minmax(0,0.7fr)_minmax(0,2.4fr)_minmax(0,1.2fr)]",
  2: "xl:grid-cols-[minmax(0,1.5fr)_minmax(0,0.7fr)_minmax(0,0.7fr)_minmax(0,1.8fr)_minmax(0,1.8fr)_minmax(0,1.1fr)]",
};
/** Os campos (cadastro, alunos, plataformas, geral) ocupam o resto da linha, na mesma grade. */
const SPAN_CAMPOS: Record<number, string> = { 0: "xl:col-span-3", 1: "xl:col-span-4", 2: "xl:col-span-5" };

function Campo({ rotulo, largo = false, children }: { rotulo: string; largo?: boolean; children: ReactNode }) {
  return (
    <div className={`min-w-0 ${largo ? "max-xl:col-span-2" : ""}`}>
      <dt className={`text-xs font-semibold ${CINZA} xl:sr-only`}>{rotulo}</dt>
      <dd className="mt-0.5 min-w-0 break-words xl:mt-0">{children}</dd>
    </div>
  );
}

/** Uma escola da lista. `s` (a situação de uso) é null quando o uso não carregou: a linha mostra
 *  o cadastro, os alunos e o link para a ficha, e o uso por extenso ("não foi possível
 *  carregar o uso") — nunca "sem uso" nem "sem dado", que seriam afirmações sobre a escola. */
function LinhaEscola({ e, s, plataformas, ctx }: {
  e: EscolaDoCadastro; s: SituacaoEscola | null; plataformas: Plataforma[]; ctx: ContextoDaPagina;
}) {
  const n = s ? plataformas.length : 0;
  // "Sem uso registrado" com coleta parcial: a data vem junto ("até 15/03/2026 (coleta parcial)").
  const complemento = s ? complementoDoGeral(s) : null;
  return (
    <li className={`card min-w-0 p-4 xl:grid ${GRADE_LINHA[n]} xl:items-start xl:gap-4 xl:rounded-none xl:border-0 xl:bg-transparent xl:px-1 xl:py-3 xl:shadow-none`}
        data-testid={`escola-${e.escolaId}`} data-situacao={s ? s.geral : "uso_indisponivel"}>
      <p className="min-w-0 break-words text-sm">
        <Link to={ctx.link(`/rede/escolas/${e.escolaId}`)} className={CLASSE_LINK}>{e.nome}</Link>
      </p>
      <dl className={`mt-3 grid grid-cols-2 gap-x-4 gap-y-3 text-sm xl:mt-0 xl:grid-cols-subgrid xl:gap-y-0 ${SPAN_CAMPOS[n]}`}>
        <Campo rotulo="Cadastro">
          {e.ativa == null
            ? <span className={CINZA}>sem cadastro no painel</span>
            : <span data-testid="cadastro">{e.ativa ? "Ativa" : "Inativa"}</span>}
        </Campo>
        <Campo rotulo={ROTULO_ALUNOS}>
          {e.alunos == null
            ? <span className={CINZA}>sem dado</span>
            : <span className="tabular-nums">{e.alunos === 0 ? "nenhum" : numero(e.alunos)}</span>}
        </Campo>
        {s ? (
          <>
            {plataformas.map((p) => {
              const u = s.plataformas[p];
              return (
                <Campo key={p} rotulo={NOME_PLATAFORMA[p]} largo>
                  {u ? (
                    <span className="flex flex-col items-start gap-1" data-testid={`uso-${p}`}>
                      <PilulaEstado estado={u.estado} rotulo={ROTULO_PLATAFORMA[u.estado]} />
                      <span className={`text-xs ${CINZA}`}>{u.texto}</span>
                    </span>
                  ) : <span className={CINZA}>sem dado</span>}
                </Campo>
              );
            })}
            <Campo rotulo="Situação geral" largo>
              <span className="flex flex-col items-start gap-1" data-testid="situacao-geral">
                <PilulaEstado estado={s.geral} rotulo={ROTULO_ESTADO[s.geral]} />
                {complemento && <>{" "}<span className={`text-xs ${CINZA}`}>{complemento}</span></>}
              </span>
            </Campo>
          </>
        ) : (
          <Campo rotulo="Situação de uso" largo>
            <span className={CINZA} data-testid="uso-indisponivel">{USO_INDISPONIVEL}</span>
          </Campo>
        )}
      </dl>
    </li>
  );
}

/** O cabeçalho das colunas, só no desktop (no leitor de tela, os rótulos vêm do <dt> de cada escola). */
function CabecalhoDaLista({ plataformas, comUso }: { plataformas: Plataforma[]; comUso: boolean }) {
  return (
    <div aria-hidden className={`hidden ${GRADE_LINHA[comUso ? plataformas.length : 0]} gap-4 border-b border-zinc-200/70 px-1 py-2.5 text-[11px] font-semibold uppercase tracking-[0.08em] text-zinc-500 dark:border-zinc-800 dark:text-zinc-400 xl:grid`}>
      <span>Escola</span>
      <span>Cadastro</span>
      <span>Alunos (todas as etapas)</span>
      {comUso && plataformas.map((p) => <span key={p}>{NOME_PLATAFORMA[p]}</span>)}
      <span>{comUso ? "Situação geral" : "Situação de uso"}</span>
    </div>
  );
}

const CLASSE_LISTA = "grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-1 xl:gap-0 xl:divide-y xl:divide-zinc-100 xl:dark:divide-zinc-800/60";

/**
 * A lista quando o USO não carregou (a leitura das plataformas falhou) mas o painel chegou: as
 * escolas continuam todas, em ordem alfabética, com o cadastro, os alunos e o link para a ficha;
 * o uso fica por extenso, sem filtro por situação (não há situação para filtrar).
 */
function TodasAsEscolasSemUso({ escolas, erro, ctx }: {
  escolas: EscolaDoCadastro[]; erro: ApiError; ctx: ContextoDaPagina;
}) {
  if (escolas.length === 0) return <p className={`text-sm ${CINZA}`}>Nenhuma escola cadastrada na rede ainda.</p>;
  return (
    <>
      <p className="text-sm text-zinc-700 dark:text-zinc-200" data-testid="lista-sem-uso">
        Não foi possível carregar o uso das plataformas ({erro.message}): a lista mostra o cadastro e os alunos de
        cada escola, sem a situação de uso. A ficha de cada escola continua aberta pelo nome.
      </p>
      <div className="min-w-0 xl:card xl:px-5 xl:py-2">
        <CabecalhoDaLista plataformas={[]} comUso={false} />
        <ul className={CLASSE_LISTA} data-testid="lista-escolas" aria-label="Escolas da rede, em ordem alfabética">
          {escolas.map((e) => <LinhaEscola key={e.escolaId} e={e} s={null} plataformas={[]} ctx={ctx} />)}
        </ul>
      </div>
      <LinkVer para={ctx.link("/rede/escolas")}>Comparar escolas lado a lado</LinkVer>
    </>
  );
}

function TodasAsEscolas({ situacoes, modulos, ctx }: {
  situacoes: SituacaoEscola[]; modulos: ModulosDaRede; ctx: ContextoDaPagina;
}) {
  const [filtro, setFiltro] = useState<Filtro>("todas");
  const conta = contarSituacoes(situacoes);
  const quantas: Record<Filtro, number> = {
    todas: situacoes.length, com_uso: conta.com_uso, sem_uso: conta.sem_uso, sem_dado: conta.sem_dado + conta.protegido,
  };
  const plataformas = PLATAFORMAS.filter((p) => modulos[p]);
  const visiveis = situacoes.filter((s) => passaNoFiltro(filtro, s));
  if (situacoes.length === 0) return <p className={`text-sm ${CINZA}`}>Nenhuma escola cadastrada na rede ainda.</p>;
  return (
    <>
      <div className="flex flex-wrap gap-1.5 max-sm:gap-2" role="group" aria-label="Filtrar as escolas pela situação de uso"
           data-testid="filtro-situacao">
        {FILTROS.map((f) => (
          <button key={f.valor} type="button" aria-pressed={filtro === f.valor} onClick={() => setFiltro(f.valor)}
                  className={`rounded-full px-3 py-1.5 text-xs font-semibold transition-colors max-sm:min-h-10 ${
                    filtro === f.valor
                      ? "bg-indigo-600 text-white shadow-pilula"
                      : "bg-zinc-100 text-zinc-700 hover:bg-zinc-200 dark:bg-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-700"}`}>
            {f.rotulo} ({quantas[f.valor]})
          </button>
        ))}
      </div>
      {visiveis.length === 0 ? (
        <p className={`text-sm ${CINZA}`} data-testid="lista-escolas-vazia">Nenhuma escola nesta situação.</p>
      ) : (
        // No celular e no tablet, um cartão por escola; no desktop, linhas alinhadas num cartão só
        // (o mesmo DOM: sem render duplo).
        <div className="min-w-0 xl:card xl:px-5 xl:py-2">
          <CabecalhoDaLista plataformas={plataformas} comUso />
          <ul className={CLASSE_LISTA} data-testid="lista-escolas" aria-label="Escolas da rede, em ordem alfabética">
            {visiveis.map((s) => <LinhaEscola key={s.escolaId} e={s} s={s} plataformas={plataformas} ctx={ctx} />)}
          </ul>
        </div>
      )}
      <LinkVer para={ctx.link("/rede/escolas")}>Comparar escolas lado a lado</LinkVer>
    </>
  );
}

// --- 5. Escolas em destaque e a vitrine ------------------------------------------------------

function ListaDestaques({ testId, titulo, icone, tom, unidade, lista, ctx }: {
  testId: string; titulo: string; icone: LucideIcon; tom: TomPastel; unidade: string;
  lista: ListaDeDestaques; ctx: ContextoDaPagina;
}) {
  const id = useId();
  const vazia = lista.escolas.length === 0;
  // A lista vazia diz tudo numa frase só (inclusive as que ficaram fora por proteção); a frase de
  // quem ficou fora, à parte, só abaixo de uma lista com escolas.
  const fora = vazia ? null : textoForaPorProtecao(lista.fora_por_protecao);
  return (
    <Card className="flex min-w-0 flex-col p-5">
      <article className="flex min-w-0 flex-1 flex-col gap-3" aria-labelledby={id} data-testid={testId}>
        <h3 id={id} className="flex items-center gap-2.5 text-[15px] font-semibold text-zinc-900 dark:text-white">
          <IconePastel icone={icone} tom={tom} tamanho="sm" />
          <span className="min-w-0 break-words">{titulo}</span>
        </h3>
        {vazia ? (
          <p className={`text-sm ${CINZA}`} data-testid={`${testId}-vazio`}>
            {textoDestaquesVazio(lista.fora_por_protecao)}
          </p>
        ) : (
          <ol className="space-y-2">
            {lista.escolas.map((e, i) => (
              // Com quebra: se o nome não cabe ao lado do valor (no celular, um nome longo), o
              // valor desce para a linha de baixo em vez de espremer o nome em várias linhas.
              <li key={e.escola_id} className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5 rounded-xl bg-zinc-50 px-3 py-2 dark:bg-zinc-800/50">
                <span className="min-w-0 break-words text-sm">
                  <span className={`mr-1.5 text-xs tabular-nums ${CINZA}`}>{i + 1}.</span>
                  <Link to={ctx.link(`/rede/escolas/${e.escola_id}`)} className={CLASSE_LINK}>{e.nome}</Link>
                </span>
                <span className="shrink-0 text-sm font-semibold tabular-nums text-zinc-900 dark:text-white sm:text-right">
                  {decimal(e.valor, 1)} <span className={`text-xs font-normal ${CINZA}`}>{unidade}</span>
                </span>
              </li>
            ))}
          </ol>
        )}
        {fora && <p className={`text-xs ${CINZA}`} data-testid={`${testId}-fora`}>{fora}</p>}
      </article>
    </Card>
  );
}

function EscolasEmDestaque({ dados, ctx }: { dados: DestaquesRede; ctx: ContextoDaPagina }) {
  const mods: ModulosDaRede = { elefante: dados.leitura != null, matific: dados.matematica != null };
  const duas = mods.elefante && mods.matific;
  return (
    <>
      <ComoLer titulo="Critério (o mesmo da vitrine pública)" testId="criterio-destaques">
        <ul className="list-disc space-y-1 pl-5 text-sm">
          {criterioDosDestaques(mods, dados.k_minimo, dados.limite).map((l) => <li key={l}>{l}</li>)}
        </ul>
      </ComoLer>
      {(mods.elefante || mods.matific) ? (
        <div className={`grid grid-cols-1 gap-4 ${duas ? "lg:grid-cols-2" : ""}`}>
          {dados.leitura && (
            <ListaDestaques testId="destaques-leitura" titulo="Leitura — Elefante" icone={BookOpen} tom="violeta"
                            unidade="livros por aluno" lista={dados.leitura} ctx={ctx} />
          )}
          {dados.matematica && (
            <ListaDestaques testId="destaques-matematica" titulo="Matemática — Matific" icone={Calculator} tom="teal"
                            unidade="estrelas por aluno" lista={dados.matematica} ctx={ctx} />
          )}
        </div>
      ) : (
        <p className={`text-sm ${CINZA}`}>A rede não tem Elefante nem Matific contratado.</p>
      )}
      {/* O Ranking da Rede é OUTRA medida (a pontuação do Constela), não a continuação destes
          destaques: o nome do link e a frase dizem isso. */}
      <div className="space-y-1">
        <p className={`text-xs ${CINZA}`} data-testid="ranking-outra-medida">{fraseRankingOutraMedida(mods)}</p>
        <LinkVer para={ctx.link("/rede/ranking")}>{ROTULO_LINK_RANKING}</LinkVer>
        <AvisoOutraRede ctx={ctx} tela="O Ranking da Rede" />
      </div>
    </>
  );
}

// --- 6. Metas da rede (recolhida) ------------------------------------------------------------

function MetasRecolhidas({ redeId, modulos }: { redeId: number; modulos: string[] }) {
  const [aberto, setAberto] = useState(false);
  const id = useId();
  const idConteudo = useId();
  return (
    <section className="min-w-0 space-y-3" aria-labelledby={id} data-testid="metas-da-rede">
      <h2 id={id} className={TITULO_SECAO}>
        <button type="button" aria-expanded={aberto} aria-controls={aberto ? idConteudo : undefined}
                onClick={() => setAberto((a) => !a)}
                className="-m-1 flex min-h-[2.75rem] min-w-0 flex-1 items-center gap-3 rounded-xl p-1 text-left transition-colors hover:text-indigo-700 dark:hover:text-indigo-300">
          <IconePastel icone={Target} tom="ambar" tamanho="sm" />
          <span className="min-w-0 break-words">Metas da rede</span>
          <ChevronDown size={16} aria-hidden
                       className={`ml-auto shrink-0 text-zinc-400 transition-transform duration-200 ${aberto ? "rotate-180" : ""}`} />
        </button>
      </h2>
      <p className={`max-w-3xl text-sm ${CINZA}`}>
        O progresso das metas da rede, calculado com o dado real, e o cadastro dos alvos. As metas não seguem
        todas o ano letivo: cada uma diz o que o número mede e, quando se sabe, de quando é. O uso no ano letivo está em “Participação no ano
        letivo”, acima.
      </p>
      {aberto && (
        <div id={idConteudo}>
          <MetasDaRede redeId={redeId} nivel={3} tituloCadastro="Cadastro das metas" modulos={modulos}
                       notaDaMetrica={NOTA_DAS_METAS_NO_PANORAMA} />
        </div>
      )}
    </section>
  );
}

// --- A tela ----------------------------------------------------------------------------------

function Panorama({ ctx, titulo }: { ctx: ContextoDaPagina; titulo: string }) {
  const { redeId } = ctx;
  const painel = useDashboardDaRede(redeId);
  const plataformas = usePlataformasDaRede(redeId, null, ANO_LETIVO);
  const destaques = useDestaques(redeId);
  const nomeRede = useNomeDaRede(redeId, ctx.nomeRede);
  const { leitura, matematica } = useModulos();
  const plat = plataformas.dados;
  const modsDoPainel = painel.dados?.modulos;
  // Os módulos CONTRATADOS pela rede mostrada (o global pode ver outra rede que não a dele): os
  // da análise; antes dela, os do painel; antes dos dois, os da conta.
  const mods: ModulosDaRede = plat?.modulos
    ?? (modsDoPainel
      ? { elefante: modsDoPainel.includes("leitura"), matific: modsDoPainel.includes("matematica") }
      : { elefante: leitura, matific: matematica });
  const listaMods = [...(mods.elefante ? ["leitura"] : []), ...(mods.matific ? ["matematica"] : [])];
  // Escolas em anos letivos diferentes (a análise mede cada uma no ano dela): nenhum rótulo afirma
  // o ano mais comum como se fosse o de todas, e a tela diz isso por extenso.
  const anosLetivos = plat?.janela.anos_letivos ?? [];
  const anosMistos = anosLetivos.length > 1 ? anosLetivos : null;
  const ano = anosMistos ? null : anoDaJanela(plat?.janela);
  // TODAS as escolas (a base é o painel, com inativas e sem alunos) e a situação de uso de cada
  // uma — com as duas leituras (o uso nunca sai do painel).
  const situacoes = useMemo(
    () => (painel.dados && plat ? classificarRede(painel.dados.escolas, plat) : null),
    [painel.dados, plat],
  );
  // A leitura do uso FALHOU (não só demorou) com o painel na mão: a lista continua, do painel, só
  // com o cadastro — o uso por extenso ("não foi possível carregar"). Enquanto o uso carrega, a
  // seção espera (sem uma lista sem filtro que muda logo depois).
  const erroUso = (!plat && plataformas.erro) || null;
  const cadastro = useMemo(
    () => (painel.dados && erroUso ? escolasDoCadastro(painel.dados.escolas) : null),
    [painel.dados, erroUso],
  );
  const lista: ListaDasEscolas | null = situacoes ? { situacoes }
    : cadastro && erroUso ? { cadastro, erroUso } : null;
  // A lista só falha com o painel (o cadastro de todas as escolas); os números de uso, com qualquer um.
  const erroLista = (!painel.dados && painel.erro) || null;
  const erroNumerosDeUso = Boolean(erroLista || erroUso);
  // As escolas que ficaram fora dos destaques para proteger as crianças (só a Secretaria): a
  // vitrine pública, com o mesmo critério, tem essas escolas — a descrição dela diz isso.
  const foraDosDestaques = (destaques.dados?.leitura?.fora_por_protecao ?? 0)
    + (destaques.dados?.matematica?.fora_por_protecao ?? 0);

  return (
    <div className="min-w-0 space-y-8">
      <CabecalhoDaPagina
        titulo={titulo}
        descricao="Todas as escolas da rede e o uso do Constela no ano letivo, as que se destacam e o caminho para a ficha de cada uma."
        nomeRede={nomeRede}
        ctx={ctx}
        depois={(
          <SeloFrescorDaRede redeId={redeId}
                             dimensoes={[...(mods.elefante ? ["leitura" as const] : []),
                                         ...(mods.matific ? ["matematica" as const] : [])]} />
        )}
      />

      <Secao testId="rede-no-constela" titulo="A rede no Constela" icone={School} tom="violeta"
             descricao="Cadastrada, ativa e com uso não são a mesma coisa: “ativa” é a situação do cadastro; o uso vem das coletas das plataformas.">
        <RedeNoConstela painel={painel} situacoes={situacoes} erroUso={erroNumerosDeUso} modulos={mods} ano={ano}
                        anosMistos={anosMistos} />
      </Secao>

      <Secao testId="participacao-ano-letivo" titulo="Participação no ano letivo" icone={MonitorSmartphone} tom="azul"
             natureza="plataforma">
        <EstadoDaLeitura dados={plat} erro={plataformas.erro} oQue="o uso das plataformas">
          {(p) => <Participacao dados={p} ctx={ctx} anosMistos={anosMistos} />}
        </EstadoDaLeitura>
      </Secao>

      <Secao testId="todas-as-escolas" titulo="Todas as escolas da rede" icone={ListChecks} tom="teal" natureza="calculado"
             descricao="Em ordem alfabética — não é ranking. A situação de uso é a do ano letivo, pelas coletas, medida do 1º ao 5º ano; os alunos contam todas as etapas. A ficha de cada escola tem o detalhe.">
        <EstadoDaLeitura dados={lista} erro={erroLista} oQue="as escolas da rede">
          {(l) => ("situacoes" in l
            ? <TodasAsEscolas situacoes={l.situacoes} modulos={mods} ctx={ctx} />
            : <TodasAsEscolasSemUso escolas={l.cadastro} erro={l.erroUso} ctx={ctx} />)}
        </EstadoDaLeitura>
      </Secao>

      <Secao testId="escolas-em-destaque" titulo="Escolas em destaque" icone={Award} tom="ambar" natureza="calculado">
        <EstadoDaLeitura dados={destaques.dados} erro={destaques.erro} oQue="as escolas em destaque">
          {(d) => <EscolasEmDestaque dados={d} ctx={ctx} />}
        </EstadoDaLeitura>
      </Secao>

      <Secao testId="reconhecimento-publico" titulo="Reconhecimento público" icone={Megaphone} tom="rosa"
             descricao={textoReconhecimentoPublico(foraDosDestaques)}>
        <VitrinePublica redeId={redeId} nivel={3} modulos={listaMods} />
      </Secao>

      <MetasRecolhidas redeId={redeId} modulos={listaMods} />

      {/* Rodapé discreto: as avaliações externas têm a área própria (não são o principal aqui). */}
      <div className="space-y-2 border-t border-zinc-200/70 pt-4 dark:border-zinc-800" data-testid="rodape-panorama">
        <p className="text-sm text-zinc-700 dark:text-zinc-200">
          Resultados das avaliações externas (Ideb, Saeb, SARESP, ICA e IEE):{" "}
          <Link to={ctx.link("/rede/avaliacoes-externas")} className={CLASSE_LINK}>Avaliações externas</Link>.
        </p>
        {/* Só o admin global: ele não tem estes itens no menu e chegava a eles por aqui (a "Visão da
            rede" dele) — com o `?rede=` da rede escolhida. A Secretaria não vê esta linha. */}
        {ctx.global && (
          <p className="text-sm text-zinc-700 dark:text-zinc-200" data-testid="atalhos-do-global">
            Para a rede escolhida:{" "}
            <Link to={ctx.link("/rede/relatorios")} className={CLASSE_LINK}>Relatórios e exportações</Link>
            {" · "}
            <Link to={ctx.link("/rede/acompanhamento")} className={CLASSE_LINK}>Escolas em acompanhamento</Link>.
          </p>
        )}
        <FraseSeparacao anoAvaliacao={null} anoPlataforma={ano} />
      </div>
    </div>
  );
}

export default function PanoramaSecretaria() {
  const { global } = usePerfil();
  // O mesmo nome do item do menu de cada perfil: a Secretaria abre o "Panorama da Rede" (/);
  // o admin global, a "Visão da rede" (/rede/visao).
  const titulo = global ? "Visão da rede" : "Panorama da Rede";
  return (
    <PaginaDaRede titulo={titulo}>
      {(ctx) => <Panorama key={ctx.redeId} ctx={ctx} titulo={titulo} />}
    </PaginaDaRede>
  );
}
