/**
 * FICHA DA ESCOLA — `/rede/escolas/:escolaId` (Secretaria e global; guarda `RotaRede`). DESENHO3 §3.
 *
 * Uma escola da rede numa página só, de cima para baixo:
 *  1. "‹ Escolas" (volta à lista com a consulta que ela tinha: período, série, escolas marcadas),
 *     o nome, a situação do CADASTRO (ativa/inativa — não diz nada sobre uso), a cidade e os
 *     alunos, turmas e professores do ano letivo (o cartão do `/redes/{id}/dashboard`);
 *  2. a SITUAÇÃO DE USO no ano letivo — a mesma função do Panorama (`classificarEscola`);
 *  3. "Elefante e Matific" no período (padrão: ano letivo; a escolha fica na URL): os cartões da
 *     escola (`/redes/{id}/analise/plataformas`), com "O que mede" e o selo Plataforma;
 *  4. a evolução no ano letivo, por bimestre, SÓ da escola (`EvolucaoPlataformas` no modo
 *     `soEscola`);
 *  5. as avaliações externas DA escola, edição por edição (`/escolas/{id}/analise`, a parte
 *     oficial no modo simples) — sem resultado, o porquê —, separadas das plataformas pela frase
 *     dos períodos diferentes;
 *  6. "Ver as turmas da escola": a escola vai para o contexto e a Visão da Escola abre, com o
 *     "Voltar" para esta ficha — só quando a escola está na lista do contexto (`useApp().escolas`,
 *     o `GET /escolas`, que traz só as ATIVAS). A inativa no cadastro não entra no contexto (o
 *     cartão Contexto diria "Toda a Rede Municipal" com uma escola aberta): a ficha diz isso por
 *     extenso, sem o link.
 *
 * A escola tem de ser DESTA rede: a página confere na lista da rede (painel e plataformas) antes
 * de pedir qualquer leitura da escola — o endereço de uma escola de outra rede (ou que não existe)
 * mostra a mensagem, sem chamar a API dela (o backend também barra). Para a SECRETARIA, a lista da
 * sessão (`useApp().escolas`, o `GET /escolas`, que para ela traz só as escolas ATIVAS da rede dela)
 * já confirma: as leituras da escola saem junto com o painel e as plataformas, sem esperar por eles
 * (a escola inativa não está nessa lista e continua esperando a confirmação). Essa lista é do login:
 * quando o painel ou as plataformas chegam SEM a escola (movida ou excluída depois), ela deixa de
 * confirmar e a ficha diz que a escola não é desta rede. O admin global não
 * confirma pela sessão (a lista dele é de todas as redes e não diz a rede de cada escola) e leva o
 * `?rede=` em todos os links (`ctx.link`). Nenhum dado de aluno: tudo agregado e protegido.
 */
import { ChevronLeft, ClipboardCheck, Gauge, MonitorSmartphone, School } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Link, useLocation, useParams } from "react-router-dom";

import { periodoParaQuery, type Periodo } from "../../../components/SeletorPeriodo";
import { Badge, Card, IconePastel, PageHeader, Vazio } from "../../../components/ui";
import { useApp } from "../../../context/AppContext";
import type { ApiError } from "../../../lib/api";
import { rotuloDasPlataformas } from "../../../hooks/useModulos";
import { ConteudoAnaliseEscola, OPCOES_ANALISE_DA_ESCOLA, urlAnaliseNoAnoLetivo } from "../../analise/AnaliseDaEscola";
import { Recolhivel } from "../../analise/DetalhesFonte";
import EvolucaoPlataformas from "../../analise/EvolucaoPlataformas";
import { CartoesPlataformas } from "../../analise/Plataformas";
import { FiltrosAplicados, SeloNatureza, useApiExata, usePlataformasDaRede } from "../../analise/comum";
import { diaBR } from "../../analise/formato";
import type { RespostaAnaliseEscola, RespostaPlataformas } from "../../analise/tipos";
import type { EstadoDaVisaoEscola } from "../../VisaoEscola";
import type { EscolaCartao } from "../comum";
import { FRASE_PLATAFORMA, METRICAS_ELEFANTE, METRICAS_MATIFIC } from "./oQueMede";
import {
  CINZA, CLASSE_LINK_ACAO, CampoPeriodo, EstadoDaLeitura, FraseSeparacao, LinkVer, OQueMede, PaginaDaRede,
  TITULO_SECAO, type ContextoDaPagina,
} from "./pecas";
import {
  NOME_PLATAFORMA, ROTULO_ESTADO, ROTULO_PLATAFORMA, classificarEscola, complementoDoGeral, type EstadoUso,
  type Plataforma, type UsoDaPlataforma,
} from "./situacaoDeUso";
import {
  ANO_LETIVO, anoDaJanela, useDashboardDaRede, useNomeDaRede, usePeriodoDaPagina,
} from "./useRedeDaPagina";

/** O estado que a lista (`/rede/escolas`) passa ao abrir a ficha: a consulta dela, para o
 *  "‹ Escolas" voltar ao mesmo recorte (período, série, escolas marcadas). */
export interface EstadoDaFicha {
  voltarLista?: string;
}

/** A volta da ficha: a lista com a consulta que ela tinha (só um caminho da própria lista); sem
 *  estado (link direto, recarga), a lista no padrão — com o `?rede=` do global. */
function voltaDaLista(estado: unknown, padrao: string): string {
  const v = (estado as EstadoDaFicha | null | undefined)?.voltarLista;
  return typeof v === "string" && /^\/rede\/escolas(\?|$)/.test(v) ? v : padrao;
}

/** A mesma URL de `usePlataformasDaRede` (sem série): o cache curto é dividido com a lista. */
function urlPlataformas(redeId: number, periodo: Periodo): string {
  const q = new URLSearchParams(periodoParaQuery(periodo));
  return `/redes/${redeId}/analise/plataformas?${q.toString()}`;
}

const TOM_ESTADO: Record<EstadoUso, "ok" | "alerta" | "neutro" | "info"> = {
  com_uso: "ok", sem_uso: "alerta", sem_dado: "neutro", protegido: "info",
};

/** A situação de uso por extenso (o texto, nunca só a cor). O rótulo padrão é o da ESCOLA
 *  (`ROTULO_ESTADO`); a linha de cada plataforma passa o rótulo curto dela (`ROTULO_PLATAFORMA`),
 *  o mesmo do Panorama — a mesma escola diz a mesma coisa nas duas telas. */
function SeloEstado({ estado, rotulo = ROTULO_ESTADO[estado] }: { estado: EstadoUso; rotulo?: string }) {
  return <Badge tom={TOM_ESTADO[estado]}>{rotulo}</Badge>;
}

function Voltar({ para }: { para: string }) {
  return (
    <Link to={para} data-testid="voltar-escolas"
          className="mb-4 inline-flex items-center gap-1 rounded-full border border-zinc-200 bg-white px-3 py-1.5 text-sm font-semibold text-indigo-600 shadow-cartao transition-colors hover:border-indigo-200 dark:border-zinc-700 dark:bg-zinc-900 dark:text-indigo-300">
      <ChevronLeft size={16} aria-hidden /> <span className="sr-only">Voltar para </span>Escolas
    </Link>
  );
}

const inteiro = (n: number) => n.toLocaleString("pt-BR");

/** O cadastro da escola: o que o painel da rede diz (ano letivo), sem nada de uso. Com o painel
 *  ainda a caminho (a ficha da Secretaria abre antes dele), "carregando" — nunca "sem o cadastro". */
function Cadastro({ cartao, carregando, erro, linkTurmas }: {
  cartao: EscolaCartao | null;
  carregando: boolean;
  erro: string | null;
  linkTurmas: ReactNode;
}) {
  const item = (rotulo: string, valor: ReactNode, detalhe?: string) => (
    <div className="min-w-0">
      <dt className={`text-xs font-medium ${CINZA}`}>{rotulo}</dt>
      <dd className="mt-0.5 break-words text-[15px] font-semibold text-zinc-900 dark:text-white">{valor}</dd>
      {detalhe && <dd className={`text-xs ${CINZA}`}>{detalhe}</dd>}
    </div>
  );
  return (
    <Card className="space-y-4 p-5 sm:p-6">
      <h2 className={TITULO_SECAO}>
        <IconePastel icone={School} tom="violeta" tamanho="sm" /> Cadastro da escola
      </h2>
      {cartao ? (
        <dl className="grid grid-cols-2 gap-x-4 gap-y-4 sm:grid-cols-3 lg:grid-cols-5" data-testid="ficha-cadastro">
          {item("Situação do cadastro",
            <Badge tom={cartao.status === "ativa" ? "ok" : "neutro"}>{cartao.status === "ativa" ? "Ativa" : "Inativa"}</Badge>,
            "situação do cadastro; não indica uso")}
          {item("Cidade", cartao.cidade || "não informada")}
          {item("Alunos no ano letivo", inteiro(cartao.total_alunos), "matriculados, todas as etapas")}
          {item("Turmas", inteiro(cartao.total_turmas))}
          {item("Professores", inteiro(cartao.total_professores))}
        </dl>
      ) : carregando ? (
        <p className={`text-sm ${CINZA}`} data-testid="ficha-cadastro-carregando">Carregando o cadastro da escola...</p>
      ) : (
        <p className={`text-sm ${CINZA}`} data-testid="ficha-sem-cadastro">
          Sem o cadastro da escola{erro ? `: não foi possível carregar o painel da rede (${erro})` : ""}.
        </p>
      )}
      {linkTurmas}
    </Card>
  );
}

/** "Uso do Constela no ano letivo": a situação geral e a de cada plataforma CONTRATADA. */
function SituacaoDeUso({ cartao, plataformas, erro, escolaId }: {
  cartao: EscolaCartao | null;
  plataformas: RespostaPlataformas | null;
  erro: ApiError | null;
  escolaId: number;
}) {
  return (
    <Card className="space-y-3 p-5 sm:p-6" >
      <h2 className={TITULO_SECAO}>
        <IconePastel icone={Gauge} tom="verde" tamanho="sm" /> Uso do Constela no ano letivo
      </h2>
      {erro && !plataformas ? (
        <p className={`text-sm ${CINZA}`}>Não foi possível carregar o uso das plataformas: {erro.message}</p>
      ) : !plataformas ? (
        <p className={`text-sm ${CINZA}`}>Carregando o uso das plataformas...</p>
      ) : (() => {
        const s = classificarEscola(cartao ?? undefined,
          plataformas.escolas.find((e) => e.escola_id === escolaId), plataformas.modulos);
        const usos = Object.entries(s.plataformas) as [Plataforma, UsoDaPlataforma][];
        // "Sem uso registrado" com coleta parcial: a data vem junto (a mesma frase do Panorama).
        const complemento = complementoDoGeral(s);
        const acoes = [
          plataformas.modulos.elefante ? "leu um livro no Elefante" : null,
          plataformas.modulos.matific ? "fez uma atividade no Matific" : null,
        ].filter(Boolean).join(" ou ");
        return (
          <div className="space-y-3" data-testid="ficha-situacao-uso">
            <p className="flex flex-wrap items-center gap-2 text-sm text-zinc-800 dark:text-zinc-100">
              <span className="font-semibold">Situação:</span> <SeloEstado estado={s.geral} />
              {complemento && <>{" "}<span className="min-w-0 break-words" data-testid="ficha-situacao-complemento">{complemento}</span></>}
            </p>
            {usos.length === 0 ? (
              <p className={`text-sm ${CINZA}`}>A rede não tem Elefante nem Matific contratado.</p>
            ) : (
              <ul className="space-y-1.5">
                {usos.map(([p, u]) => (
                  <li key={p} className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-zinc-700 dark:text-zinc-200"
                      data-testid={`ficha-uso-${p}`}>
                    {/* Os espaços entre as partes: o leitor de tela lê a linha inteira, sem colar as palavras. */}
                    <span className="font-semibold">{NOME_PLATAFORMA[p]}:</span>{" "}
                    <SeloEstado estado={u.estado} rotulo={ROTULO_PLATAFORMA[u.estado]} />{" "}
                    <span className="min-w-0 break-words">{u.texto}</span>
                  </li>
                ))}
              </ul>
            )}
            {acoes && (
              <OQueMede texto={`“Com uso” quer dizer que pelo menos um aluno do 1º ao 5º ano ${acoes} no ano letivo, `
                + "pelas coletas. Sem coleta, sem conta ou com poucos alunos, a ficha diz isso — nunca conta como zero."} />
            )}
            <p className={`flex flex-wrap items-center gap-x-2 gap-y-1 text-xs ${CINZA}`}>
              <SeloNatureza natureza="plataforma" />
              <span className="min-w-0 break-words">{FRASE_PLATAFORMA}</span>
            </p>
          </div>
        );
      })()}
    </Card>
  );
}

/** "Elefante e Matific" no período da página: os cartões da escola, o que mede cada número. */
function PlataformasNoPeriodo({ escolaId, periodo, aoMudar, leitura, nomePlataformas }: {
  escolaId: number;
  periodo: Periodo;
  aoMudar: (p: Periodo) => void;
  leitura: { dados: RespostaPlataformas | null; erro: ApiError | null };
  nomePlataformas: string;
}) {
  return (
    <Card className="space-y-4 p-5 sm:p-6">
      <h2 className={TITULO_SECAO}>
        <IconePastel icone={MonitorSmartphone} tom="azul" tamanho="sm" /> {nomePlataformas} no período
      </h2>
      <CampoPeriodo periodo={periodo} aoMudar={aoMudar} />
      <EstadoDaLeitura dados={leitura.dados} erro={leitura.erro} oQue="o uso das plataformas da escola">
        {(p) => {
          const e = p.escolas.find((x) => x.escola_id === escolaId);
          const coletas = e && !e.suprimido ? [
            p.modulos.elefante && e.ultima_coleta?.elefante ? `Elefante ${diaBR(e.ultima_coleta.elefante)}` : null,
            p.modulos.matific && e.ultima_coleta?.matific ? `Matific ${diaBR(e.ultima_coleta.matific)}` : null,
          ].filter(Boolean) : [];
          return (
            <div className="space-y-3" data-testid="ficha-plataformas">
              <FiltrosAplicados testId="ficha-recorte-plataformas">
                Vale aqui: período ({p.janela.rotulo}) e série (1º ao 5º ano).
              </FiltrosAplicados>
              <p className={`flex flex-wrap items-center gap-x-2 gap-y-1 text-xs ${CINZA}`}>
                <SeloNatureza natureza="plataforma" />
                <span className="min-w-0 break-words">{FRASE_PLATAFORMA}</span>
              </p>
              {e ? (
                <CartoesPlataformas alunos={e.alunos} elefante={e.elefante} matific={e.matific} modulos={p.modulos}
                                    suprimido={e.suprimido} textoSupressao={e.texto_supressao}
                                    textoBlocos={e.texto_blocos} nivelTitulo={3} />
              ) : (
                <p className={`text-sm ${CINZA}`}>Sem dado das plataformas para esta escola no período.</p>
              )}
              {coletas.length > 0 && (
                <p className={`text-xs ${CINZA}`} data-testid="ficha-ultima-coleta">Última coleta: {coletas.join(" · ")}.</p>
              )}
              <Recolhivel titulo="O que mede cada número" testId="ficha-o-que-mede">
                <dl className="space-y-2">
                  {[...(p.modulos.elefante ? METRICAS_ELEFANTE.map((m) => ({ ...m, rotulo: `Elefante — ${m.rotulo}` })) : []),
                    ...(p.modulos.matific ? METRICAS_MATIFIC.map((m) => ({ ...m, rotulo: `Matific — ${m.rotulo}` })) : [])]
                    .map((m) => (
                      <div key={m.rotulo}>
                        <dt className="font-semibold text-zinc-800 dark:text-zinc-100">{m.rotulo}</dt>
                        <dd>{m.oQueMede}</dd>
                      </div>
                    ))}
                  <div>
                    <dt className="font-semibold text-zinc-800 dark:text-zinc-100">Sem dado e protegido</dt>
                    <dd>
                      “Sem dado” não é zero: a escola sem coleta ou sem conta na plataforma fica sem número. Com poucos
                      alunos, os números não aparecem, para proteger as crianças.
                    </dd>
                  </div>
                </dl>
              </Recolhivel>
            </div>
          );
        }}
      </EstadoDaLeitura>
    </Card>
  );
}

/** A última edição com número oficial DA escola (para a frase dos períodos diferentes). */
function ultimaEdicaoDaEscola(d: RespostaAnaliseEscola | null): number | null {
  const edicoes = (d?.indicadores ?? []).flatMap((ind) => ind.series
    .filter((s) => s.papel === "principal")
    .flatMap((s) => s.pontos.filter((p) => p.valor != null).map((p) => p.edicao)));
  return edicoes.length ? Math.max(...edicoes) : null;
}

function NaoEncontrada({ volta }: { volta: string }) {
  return (
    <div className="min-w-0 space-y-4" data-testid="ficha-nao-encontrada">
      <Voltar para={volta} />
      <PageHeader titulo="Escola não encontrada" />
      <Card>
        <Vazio icone={School} titulo="Esta escola não está nesta rede"
               descricao="O endereço aponta para uma escola que não existe ou que não faz parte da rede municipal aberta aqui. Volte à lista para escolher uma escola."
               acao={<Link to={volta} className={CLASSE_LINK_ACAO}>Ver todas as escolas</Link>} />
      </Card>
    </div>
  );
}

function Ficha({ ctx, escolaId }: { ctx: ContextoDaPagina; escolaId: number | null }) {
  const { state, pathname, search } = useLocation();
  const { selecionarEscola, escolas } = useApp();
  const [periodo, definirPeriodo] = usePeriodoDaPagina();
  // A volta é lida UMA vez, na chegada: trocar o período aqui grava a URL com `replace`, e essa
  // navegação não leva o estado — sem guardar, o "‹ Escolas" perderia a consulta da lista. (A
  // ficha remonta ao trocar de escola ou de rede: a `key` é rede + escola.)
  const [volta] = useState(() => voltaDaLista(state, ctx.link("/rede/escolas")));

  // As listas da REDE (nunca da escola): o cadastro de todas e as plataformas no ano letivo (a
  // mesma leitura da lista e do Panorama, com cache curto). Elas dizem se a escola é desta rede.
  const painel = useDashboardDaRede(ctx.redeId);
  const anoLetivo = usePlataformasDaRede(ctx.redeId, null, ANO_LETIVO);
  const nomeRede = useNomeDaRede(ctx.redeId, ctx.nomeRede);
  const ehAnoLetivo = periodo.preset === "ano_letivo";
  const doPeriodo = useApiExata<RespostaPlataformas>(ehAnoLetivo ? null : urlPlataformas(ctx.redeId, periodo),
                                                     { cacheMs: 60_000 });
  const cartao = escolaId != null ? painel.dados?.escolas.find((e) => e.escola_id === escolaId) ?? null : null;
  const daAnalise = escolaId != null ? anoLetivo.dados?.escolas.find((e) => e.escola_id === escolaId) ?? null : null;
  // A Secretaria: a lista da sessão só tem escolas da rede dela (o global não usa este atalho).
  const daSessao = !ctx.global && escolaId != null ? escolas.find((e) => e.id === escolaId) ?? null : null;
  // A lista da sessão é do LOGIN: a escola movida para outra rede (ou excluída) depois dele continua
  // nela. Ela só confirma enquanto nenhuma lista da rede chegou SEM a escola — o painel traz todas as
  // escolas da rede (inativas inclusive); chegando sem ela, a escola não é mais desta rede.
  const desmentida = (painel.dados != null && cartao == null) || (anoLetivo.dados != null && daAnalise == null);
  const confirmada = escolaId != null && (cartao != null || daAnalise != null || (daSessao != null && !desmentida));
  // As leituras DA escola só depois de confirmada (escola de outra rede: nenhuma chamada).
  const analise = useApiExata<RespostaAnaliseEscola>(confirmada ? urlAnaliseNoAnoLetivo(escolaId) : null,
                                                     OPCOES_ANALISE_DA_ESCOLA);

  if (escolaId == null) return <NaoEncontrada volta={volta} />;
  if (!confirmada) {
    const prontas = (painel.dados != null || painel.erro != null) && (anoLetivo.dados != null || anoLetivo.erro != null);
    if (!prontas) {
      return (
        <div className="min-w-0 space-y-4">
          <Voltar para={volta} />
          <EstadoDaLeitura dados={null} erro={null} oQue="a escola">{() => null}</EstadoDaLeitura>
        </div>
      );
    }
    if (painel.dados == null && anoLetivo.dados == null) {
      return (
        <div className="min-w-0 space-y-4">
          <Voltar para={volta} />
          <PageHeader titulo="Ficha da escola" />
          <EstadoDaLeitura dados={null} erro={painel.erro ?? anoLetivo.erro} oQue="a escola">{() => null}</EstadoDaLeitura>
        </div>
      );
    }
    return <NaoEncontrada volta={volta} />;
  }

  const nome = cartao?.nome ?? daAnalise?.nome ?? daSessao?.nome ?? "Escola";
  const modulos = anoLetivo.dados?.modulos;
  const nomePlataformas = rotuloDasPlataformas(modulos
    ? [...(modulos.elefante ? ["leitura"] : []), ...(modulos.matific ? ["matematica"] : [])]
    : ["leitura", "matematica"]);
  // "Ver as turmas": a escola vai para o contexto (a Visão da Escola lê dele) e a volta é ESTA ficha.
  // Só com a escola na lista do contexto (as ativas): fora dela, o cartão Contexto não a mostraria e
  // a Visão da Escola abriria sem dizer de qual escola é — a ficha diz por quê, por extenso.
  const estadoTurmas: EstadoDaVisaoEscola = {
    voltar: { caminho: `${pathname}${search}`, texto: "Voltar para a ficha da escola" },
  };
  const noContexto = escolas.some((e) => e.id === escolaId);
  const linkTurmas = noContexto ? (
    <Link to="/escola" state={estadoTurmas} onClick={() => selecionarEscola(escolaId)} className={CLASSE_LINK_ACAO}
          data-testid="ver-turmas">
      Ver as turmas da escola <span aria-hidden>→</span>
    </Link>
  ) : (
    <p className={`text-sm ${CINZA}`} data-testid="ver-turmas-indisponivel">
      {cartao && cartao.status !== "ativa"
        ? "Escola inativa no cadastro: as turmas dela não ficam disponíveis na Visão da Escola."
        : "As turmas desta escola não estão disponíveis na Visão da Escola para a sua conta."}
    </p>
  );

  return (
    <div className="min-w-0 space-y-5">
      <div>
        <Voltar para={volta} />
        <PageHeader titulo={nome}
                    descricao={`A escola numa página: cadastro, uso do Constela, ${nomePlataformas}, evolução no ano letivo e avaliações externas.`} />
        {nomeRede && (
          <p className={`-mt-4 text-sm font-medium ${CINZA}`} data-testid="secretaria-rede-nome">{nomeRede}</p>
        )}
      </div>

      <Cadastro cartao={cartao} carregando={painel.dados == null && painel.erro == null}
                erro={painel.erro?.message ?? null} linkTurmas={linkTurmas} />
      <SituacaoDeUso cartao={cartao} plataformas={anoLetivo.dados} erro={anoLetivo.erro} escolaId={escolaId} />
      <PlataformasNoPeriodo escolaId={escolaId} periodo={periodo} aoMudar={definirPeriodo}
                            leitura={ehAnoLetivo ? anoLetivo : doPeriodo} nomePlataformas={nomePlataformas} />
      <EvolucaoPlataformas redeId={ctx.redeId} serie={null} escolaId={escolaId} soEscola nomeEscola={nome}
                           modulos={modulos} />

      <FraseSeparacao anoAvaliacao={ultimaEdicaoDaEscola(analise.dados)} anoPlataforma={anoDaJanela(anoLetivo.dados?.janela)} />

      <Card className="space-y-4 p-5 sm:p-6">
        <h2 className={TITULO_SECAO}>
          <IconePastel icone={ClipboardCheck} tom="violeta" tamanho="sm" /> Avaliações externas da escola
        </h2>
        <p className={`flex flex-wrap items-center gap-x-2 gap-y-1 text-xs ${CINZA}`}>
          <SeloNatureza natureza="oficial" />
          <span className="min-w-0 break-words">
            resultados e metas oficiais, edição por edição; a rede municipal aparece como referência. Cada avaliação
            tem escala própria: compare a escola com ela mesma e com a rede, não uma avaliação com outra.
          </span>
        </p>
        <EstadoDaLeitura dados={analise.dados} erro={analise.erro} oQue="as avaliações externas da escola">
          {(d) => <ConteudoAnaliseEscola dados={d} simples soAvaliacoes />}
        </EstadoDaLeitura>
        <LinkVer para={ctx.link("/rede/avaliacoes-externas")}>Ver as avaliações externas de toda a rede</LinkVer>
      </Card>
    </div>
  );
}

/** O id do endereço (só número inteiro positivo; o resto é "escola não encontrada"). */
function idDoEndereco(v: string | undefined): number | null {
  if (!v || !/^\d+$/.test(v)) return null;
  const n = Number(v);
  return n > 0 ? n : null;
}

export default function FichaEscolaRede() {
  const { escolaId } = useParams();
  const id = idDoEndereco(escolaId);
  return (
    <PaginaDaRede titulo="Ficha da escola">
      {(ctx) => <Ficha key={`${ctx.redeId}-${id ?? "x"}`} ctx={ctx} escolaId={id} />}
    </PaginaDaRede>
  );
}
