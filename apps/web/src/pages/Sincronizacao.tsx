/**
 * Integrações (rota /sincronizacao).
 *
 * A tela da ESCOLA para conferir se os dados das plataformas (Matific e
 * Elefante Letrado) estão chegando e atualizados. Um card por plataforma diz,
 * em uma frase, a situação (Funcionando / Dados desatualizados / Falhou /
 * Ainda não configurada / Sem dados ainda), quando foi a última sincronização,
 * quando é a próxima e quantos alunos têm dados. A configuração da conexão e
 * a coleta por período ficam recolhidas; histórico e logs viram "Detalhes
 * técnicos" (abertos por padrão só para o Admin Global).
 *
 * Nada muda de endpoint: usa GET /escolas/{id}/sync/status, /historico,
 * /alertas, /logs e os POST/PUT já existentes. Campos novos do status
 * (cobertura por aluno) são OPCIONAIS e só aparecem quando o backend informa.
 * Toda a UI usa o design system (ui.tsx + Tailwind).
 */
import {
  AlertTriangle,
  CalendarClock,
  CheckCircle2,
  ChevronDown,
  Clock,
  FileUp,
  History,
  Plug,
  Radar,
  RefreshCw,
  Users,
  Wrench,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import type { MouseEvent, ReactNode } from "react";
import { Link } from "react-router-dom";

import { CredenciaisForm } from "../components/CredenciaisForm";
import {
  NOME_PLATAFORMA as NOME,
  StatusIntegracaoBadge,
  precisaVerificacao,
  rotuloAlerta,
  situacaoIntegracao,
} from "../components/StatusIntegracao";
import type { EscolaStatus, Execucao, PlataformaStatus } from "../components/StatusIntegracao";
import ImportacaoMatriculas from "./ImportacaoMatriculas";
import {
  Badge,
  Botao,
  Card,
  Carregando,
  Drawer,
  Mensagem,
  PageHeader,
  StatCard,
  Vazio,
  estiloInput,
} from "../components/ui";
import { useApp } from "../context/AppContext";
import { useApi } from "../hooks/useApi";
import { useMutation } from "../hooks/useMutation";
import { api } from "../lib/api";
import { dataHora } from "../lib/formato";

// --- Tipos locais (espelham app/sync/schemas.py) ----------------------------
interface LogLinha {
  id: number; execucao_id: number; etapa: string; nivel: string;
  mensagem: string; created_at: string;
}
interface Alerta {
  id: number; plataforma: string | null; tipo: string; severidade: string;
  mensagem: string; resolvido: boolean; created_at: string;
}
interface Dashboard {
  escolas_total: number; escolas_configuradas: number; escolas_sincronizadas: number;
  escolas_com_erro: number; escolas_desatualizadas: number;
  em_andamento: number; fila: number; workers_ativos: number;
  scheduler_ligado: boolean; ultima_sincronizacao: string | null;
  duracao_ultima_ms: number | null; tempo_medio_ms: number | null; alertas_abertos: number;
}

const DIAS = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"];

// Usa o formatador compartilhado (trata UTC naive + horário de Brasília).
const fmtData = (s: string | null | undefined) => dataHora(s ?? null);
const fmtDur = (ms: number | null) => (ms ? `${(ms / 1000).toFixed(1)}s` : "—");

// Rótulos dos tipos de alerta: mapa único em components/StatusIntegracao
// (o badge "Falhou: <motivo>" usa o mesmo).

// Status de uma execução (histórico) → rótulo humano + cor theme-aware.
const ESTADO: Record<string, { rotulo: string; classe: string }> = {
  concluida: { rotulo: "concluída", classe: "bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300" },
  erro: { rotulo: "erro", classe: "bg-red-50 text-red-700 dark:bg-red-500/10 dark:text-red-300" },
  executando: { rotulo: "executando", classe: "bg-indigo-50 text-indigo-700 dark:bg-indigo-500/10 dark:text-indigo-300" },
  fila: { rotulo: "na fila", classe: "bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300" },
  cancelada: { rotulo: "cancelada", classe: "bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300" },
  sem_dados: { rotulo: "sem dados novos", classe: "bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300" },
};

function EstadoBadge({ status }: { status: string }) {
  const e = ESTADO[status] ?? { rotulo: status.replace(/_/g, " "), classe: ESTADO.cancelada.classe };
  return (
    <span className={`inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium ${e.classe}`}>
      {e.rotulo}
    </span>
  );
}

/** Bloco recolhível leve (sem Card próprio) — para seções dentro de um card. */
function BlocoRecolhivel({
  titulo, icone, inicialAberto = false, descricao, children,
}: {
  titulo: string; icone?: ReactNode; inicialAberto?: boolean;
  descricao?: string; children: ReactNode;
}) {
  const [aberto, setAberto] = useState(inicialAberto);
  return (
    <div className="mt-4 border-t border-zinc-100 pt-3 dark:border-zinc-800">
      <button
        type="button"
        onClick={() => setAberto((a) => !a)}
        aria-expanded={aberto}
        className="flex w-full items-center gap-2 text-left text-sm font-semibold text-zinc-800 hover:text-indigo-600 dark:text-zinc-100 dark:hover:text-indigo-400"
      >
        {icone}
        {titulo}
        <ChevronDown
          size={16}
          aria-hidden
          className={`ml-auto shrink-0 text-zinc-400 transition-transform ${aberto ? "rotate-180" : ""}`}
        />
      </button>
      {descricao && !aberto && (
        <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">{descricao}</p>
      )}
      {aberto && <div className="mt-3">{children}</div>}
    </div>
  );
}

export default function Sincronizacao() {
  const { escolaId, usuario } = useApp();
  const base = escolaId ? `/escolas/${escolaId}/sync` : null;
  const global = Boolean(usuario?.is_global);
  const gestor = global || ["admin", "coordenador"].includes(usuario?.cargo ?? "");

  // TODOS os hooks vêm antes de qualquer return (ordem de hooks estável).
  const status = useApi<EscolaStatus>(base ? `${base}/status` : null);
  const historico = useApi<Execucao[]>(base ? `${base}/historico?limite=30` : null);
  const alertas = useApi<Alerta[]>(base ? `${base}/alertas?resolvido=false` : null);
  const dashboard = useApi<Dashboard>(global ? "/sync/dashboard" : null);

  const [execLog, setExecLog] = useState<number | null>(null);
  const [verMatriculas, setVerMatriculas] = useState(false);
  const logs = useApi<LogLinha[]>(
    base && execLog ? `${base}/logs?execucao_id=${execLog}&limite=200` : null);

  const recarregar = useCallback(() => {
    status.recarregar(); historico.recarregar(); alertas.recarregar();
    if (global) dashboard.recarregar();
  }, [status, historico, alertas, dashboard, global]);

  // Auto-atualiza enquanto houver execução em andamento (polling leve).
  const emAndamento = (historico.dados ?? []).some(
    (e) => e.status === "executando" || e.status === "fila");
  useEffect(() => {
    if (!emAndamento) return;
    const t = setInterval(recarregar, 4000);
    return () => clearInterval(t);
  }, [emAndamento, recarregar]);

  const sincronizar = useMutation(
    async (opts?: { plataforma?: string; inicio?: string; fim?: string }) => {
      const q = new URLSearchParams();
      if (opts?.plataforma) q.set("plataforma", opts.plataforma);
      if (opts?.inicio && opts?.fim) { q.set("inicio", opts.inicio); q.set("fim", opts.fim); }
      const qs = q.toString();
      await api(`${base}/agora${qs ? `?${qs}` : ""}`, { method: "POST" });
    }, { aoSucesso: recarregar });

  const resolver = useMutation(async (id: number) => {
    await api(`${base}/alertas/${id}/resolver`, { method: "POST" });
  }, { aoSucesso: recarregar });

  if (!escolaId) {
    return <Vazio titulo="Selecione uma escola" descricao="Escolha uma escola para conferir as integrações." />;
  }

  const dados = status.dados;
  const listaAlertas = alertas.dados ?? [];
  const verificacao = dados
    ? precisaVerificacao(dados, alertas.dados ? listaAlertas.length : null)
    : null;
  const temProblema = Boolean(verificacao && (
    verificacao.alertas > 0 || verificacao.pendencias > 0 || verificacao.desatualizadas.length > 0));

  // Alertas por plataforma (o card mostra os seus); os sem plataforma ficam
  // num bloco geral abaixo dos cards.
  const plataformasConhecidas = new Set((dados?.plataformas ?? []).map((p) => p.plataforma));
  const alertasDe = (plat: string) => listaAlertas.filter((a) => a.plataforma === plat);
  const alertasGerais = listaAlertas.filter(
    (a) => !a.plataforma || !plataformasConhecidas.has(a.plataforma));
  const primeiraComAlerta = (dados?.plataformas ?? []).find((p) => alertasDe(p.plataforma).length > 0);
  const alvoAlertas = primeiraComAlerta ? `alertas-${primeiraComAlerta.plataforma}` : "alertas-gerais";
  // Texto cru do erro da execução aberta no painel de logs (histórico ou a
  // última execução de uma plataforma; na última, cai no erro da credencial).
  const platDoLog = (dados?.plataformas ?? []).find(
    (p) => execLog !== null && p.ultima_execucao?.id === execLog);
  const execDoLog = execLog === null
    ? null
    : (historico.dados ?? []).find((e) => e.id === execLog) ?? platDoLog?.ultima_execucao ?? null;
  const detalheExecLog =
    execDoLog?.erro_resumo ||
    (platDoLog && situacaoIntegracao(platDoLog).chave === "falhou" ? platDoLog.ultimo_erro : null) ||
    null;

  const irPara = (id: string) => (e: MouseEvent<HTMLAnchorElement>) => {
    const el = document.getElementById(id);
    if (el && typeof el.scrollIntoView === "function") {
      e.preventDefault();
      el.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  };

  return (
    <div className="space-y-6">
      <PageHeader
        titulo="Integrações"
        descricao="Os dados das plataformas chegam sozinhos. Aqui você confere se estão atualizados."
        acoes={
          <div className="flex flex-wrap items-center gap-2">
            {dados && (
              dados.integracao_configurada
                ? <Badge tom="ok">✓ Integração configurada</Badge>
                : <Badge tom="alerta">Integração pendente</Badge>
            )}
            <Botao variante="neutro" onClick={recarregar}>
              <RefreshCw size={15} /> Atualizar
            </Botao>
            {/* Matrícula (Lista Piloto) NÃO vem da sincronização — ela coleta
                desempenho, não o cadastro. Por isso o roster é atualizado aqui. */}
            <Botao variante="neutro" onClick={() => setVerMatriculas(true)}>
              <Users size={15} /> {dados?.lista_piloto_importada ? "Atualizar Lista Piloto" : "Importar Lista Piloto"}
            </Botao>
            <Botao disabled={sincronizar.enviando || !dados?.integracao_configurada}
              onClick={() => sincronizar.executar(undefined)}>
              {sincronizar.enviando ? "Sincronizando…" : "Sincronizar agora"}
            </Botao>
          </div>
        }
      />

      {sincronizar.erro && <Mensagem tipo="erro">{sincronizar.erro.message}</Mensagem>}

      {/* Estados de carregamento / erro do status principal */}
      {status.carregando && !dados && <Carregando texto="Carregando integrações…" />}
      {status.erro && !dados && (
        <Vazio titulo="Não foi possível carregar as integrações"
          descricao={status.erro.message}
          acao={<Botao variante="neutro" onClick={() => status.recarregar()}>Tentar de novo</Botao>} />
      )}

      {/* Banner: há algo que a escola precisa olhar */}
      {dados && verificacao && temProblema && (
        <div
          role="status"
          className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-100"
        >
          <div className="flex items-start gap-2">
            <AlertTriangle size={17} className="mt-0.5 shrink-0 text-amber-500" />
            <div className="min-w-0 space-y-1">
              <p className="font-semibold">Atenção: há dados que precisam de verificação.</p>
              <ul className="list-inside list-disc text-xs">
                {verificacao.alertas > 0 && (
                  <li>{verificacao.alertas} alerta(s) em aberto nas plataformas.</li>
                )}
                {verificacao.pendencias > 0 && (
                  <li>
                    Nos últimos 30 dias, {verificacao.pendencias} linha(s) de relatório ficaram sem
                    aluno correspondente. As que ainda aguardam decisão estão em Revisões de
                    identidade, onde você escolhe o aluno certo.
                  </li>
                )}
                {verificacao.desatualizadas.length > 0 && (
                  <li>Dados desatualizados: {verificacao.desatualizadas.join(" e ")}.</li>
                )}
              </ul>
              <div className="flex flex-wrap gap-x-4 gap-y-1 pt-1 text-xs font-medium">
                {verificacao.alertas > 0 && (
                  <a href={`#${alvoAlertas}`} onClick={irPara(alvoAlertas)} className="underline">
                    Ver alertas
                  </a>
                )}
                {verificacao.pendencias > 0 && (
                  <Link to="/revisoes-identidade" className="underline">Ver revisões de identidade</Link>
                )}
                <Link to="/importacoes" className="underline">Ver importações (avançado)</Link>
              </div>
            </div>
          </div>
        </div>
      )}

      {dados && !dados.lista_piloto_importada && (
        <Mensagem tipo="erro">
          Nenhuma turma cadastrada ainda. Comece pela <Link className="font-semibold underline" to="/comecar">
          configuração inicial da escola</Link> (Lista Piloto) para criar turmas e alunos.
        </Mensagem>
      )}

      {/* Visão geral — só usuário com acesso total */}
      {global && (
        <section className="space-y-3">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
            Visão geral (todas as escolas)
          </h2>
          {dashboard.erro && !dashboard.dados && (
            <Mensagem tipo="erro">
              Não foi possível carregar a visão geral: {dashboard.erro.message}
            </Mensagem>
          )}
          {dashboard.carregando && !dashboard.dados && <Carregando texto="Carregando visão geral…" />}
          {dashboard.dados && (<>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-7">
            <StatCard icone={<CheckCircle2 size={15} />} rotulo="Configuradas" valor={String(dashboard.dados.escolas_configuradas)} detalhe={`de ${dashboard.dados.escolas_total}`} />
            <StatCard icone={<RefreshCw size={15} />} rotulo="Sincronizadas" valor={String(dashboard.dados.escolas_sincronizadas)} />
            <StatCard icone={<AlertTriangle size={15} />} rotulo="Com erro" valor={String(dashboard.dados.escolas_com_erro)} />
            <StatCard icone={<Clock size={15} />} rotulo="Desatualizadas" valor={String(dashboard.dados.escolas_desatualizadas)} detalhe="dados envelhecendo" />
            <StatCard icone={<Clock size={15} />} rotulo="Em andamento" valor={String(dashboard.dados.em_andamento)} detalhe={`${dashboard.dados.fila} na fila`} />
            <StatCard icone={<Clock size={15} />} rotulo="Tempo médio" valor={fmtDur(dashboard.dados.tempo_medio_ms)} />
            <StatCard icone={<History size={15} />} rotulo="Última" valor={fmtData(dashboard.dados.ultima_sincronizacao)} />
          </div>
          {!dashboard.dados.scheduler_ligado && (
            <Mensagem tipo="erro">
              O agendador automático está <strong>desligado</strong> no servidor
              (SYNC_SCHEDULER_ENABLED). As sincronizações manuais funcionam; para a
              automática, ligue-o no servidor.
            </Mensagem>
          )}
          </>)}
        </section>
      )}

      {alertas.erro && !alertas.dados && (
        <Mensagem tipo="erro">
          Não foi possível carregar os alertas: {alertas.erro.message}
        </Mensagem>
      )}

      {/* Um card por plataforma */}
      {dados?.plataformas.map((p) => (
        <PlataformaCard
          key={p.plataforma}
          base={base!}
          p={p}
          gestor={gestor}
          alertas={alertasDe(p.plataforma)}
          onResolver={(id) => resolver.executar(id)}
          resolvendo={resolver.enviando}
          erroResolver={resolver.erro?.message ?? null}
          onMudou={recarregar}
          onSincronizar={() => sincronizar.executar({ plataforma: p.plataforma })}
          onSincronizarPeriodo={(inicio, fim) =>
            sincronizar.executar({ plataforma: p.plataforma, inicio, fim })}
          sincronizando={sincronizar.enviando}
          onVerLogs={(execId) => setExecLog(execId)}
        />
      ))}

      {/* Alertas sem plataforma (raros): ficam num bloco próprio */}
      {alertasGerais.length > 0 && (
        <Card className="p-5">
          <div id="alertas-gerais" className="scroll-mt-4">
            <h2 className="flex items-center gap-2 text-base font-semibold tracking-tight">
              <AlertTriangle size={17} className="text-amber-500" />
              Outros alertas ({alertasGerais.length})
            </h2>
            <ListaAlertas alertas={alertasGerais} onResolver={(id) => resolver.executar(id)}
              resolvendo={resolver.enviando} erro={resolver.erro?.message ?? null} />
          </div>
        </Card>
      )}

      {/* Detalhes técnicos: histórico + logs (aberto por padrão só para o global) */}
      {dados && (
        <Card className="p-5">
          <BlocoRecolhivel
            key={global ? "global" : "escola"}
            titulo="Detalhes técnicos"
            icone={<Wrench size={16} className="text-zinc-400" />}
            inicialAberto={global}
            descricao="Histórico das sincronizações e registro de cada execução. Útil para o suporte; não é necessário no dia a dia."
          >
            <p className="mb-3 text-xs text-zinc-500 dark:text-zinc-400">
              “Registros” são as linhas processadas em cada execução (um aluno pode
              contar duas vezes: resumo e leituras). “Linhas c/ erro” são as linhas
              que não puderam ser vinculadas a um aluno.
            </p>
            {historico.carregando && !historico.dados ? (
              <Carregando texto="Carregando histórico…" />
            ) : (historico.dados?.length ?? 0) === 0 ? (
              <Vazio titulo="Nenhuma sincronização ainda"
                descricao="Assim que uma plataforma for conectada e sincronizar, o histórico aparece aqui." />
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-zinc-200 text-left text-xs uppercase tracking-wide text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
                      <th className="px-3 py-2 font-medium">Quando</th>
                      <th className="px-3 py-2 font-medium">Plataforma</th>
                      <th className="hidden px-3 py-2 font-medium sm:table-cell">Origem</th>
                      <th className="px-3 py-2 font-medium">Status</th>
                      <th className="px-3 py-2 text-right font-medium">Registros</th>
                      <th className="hidden px-3 py-2 text-right font-medium md:table-cell">Linhas c/ erro</th>
                      <th className="hidden px-3 py-2 text-right font-medium sm:table-cell">Duração</th>
                      <th className="px-3 py-2 font-medium">Logs</th>
                    </tr>
                  </thead>
                  <tbody>
                    {historico.dados!.map((e) => (
                      <tr key={e.id} className="border-b border-zinc-100 last:border-0 dark:border-zinc-800/60">
                        <td className="px-3 py-2 whitespace-nowrap">{fmtData(e.iniciada_em ?? e.created_at ?? null)}</td>
                        <td className="px-3 py-2">{NOME[e.plataforma] ?? e.plataforma}</td>
                        <td className="hidden px-3 py-2 text-zinc-500 dark:text-zinc-400 sm:table-cell">
                          {e.origem === "scheduler" ? "Automático" : "Manual"}
                        </td>
                        <td className="px-3 py-2"><EstadoBadge status={e.status} /></td>
                        <td className="px-3 py-2 text-right tabular-nums">{e.qtd_alunos}</td>
                        <td className="hidden px-3 py-2 text-right tabular-nums md:table-cell">{e.qtd_erros}</td>
                        <td className="hidden px-3 py-2 text-right tabular-nums sm:table-cell">{fmtDur(e.duracao_ms)}</td>
                        <td className="px-3 py-2">
                          <button className="text-indigo-600 hover:underline dark:text-indigo-400"
                            onClick={() => setExecLog(e.id)}>ver</button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </BlocoRecolhivel>
        </Card>
      )}

      {/* Logs da execução — painel lateral */}
      <Drawer titulo={execLog ? `Logs da execução #${execLog}` : "Logs"}
        aberto={execLog !== null} aoFechar={() => setExecLog(null)}>
        {detalheExecLog && (
          <p className="mb-3 break-words rounded-lg border border-red-200 bg-red-50 px-3 py-2 font-mono text-xs text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300">
            Detalhe técnico: {detalheExecLog}
          </p>
        )}
        {logs.carregando && !logs.dados ? (
          <Carregando texto="Carregando logs…" />
        ) : (logs.dados?.length ?? 0) === 0 ? (
          <Vazio titulo="Sem logs" descricao="Esta execução não registrou etapas." />
        ) : (
          <div className="space-y-1 font-mono text-xs">
            {logs.dados!.slice().reverse().map((l) => (
              <div key={l.id} className={
                l.nivel === "error" ? "text-red-600 dark:text-red-400"
                  : l.nivel === "warn" ? "text-amber-600 dark:text-amber-400"
                    : "text-zinc-600 dark:text-zinc-300"}>
                <span className="text-zinc-400">{fmtData(l.created_at)}</span>{" "}
                <span className="font-semibold">[{l.etapa}]</span> {l.mensagem}
              </div>
            ))}
          </div>
        )}
      </Drawer>

      {/* Atualizar/Importar a Lista Piloto (matrículas) — reusa o mesmo
          componente e endpoint idempotente (casa por RA/nome, atualiza os
          existentes e marca quem saiu como "fora da lista", sem apagar). */}
      <Drawer titulo="Atualizar Lista Piloto" aberto={verMatriculas} aoFechar={() => setVerMatriculas(false)}>
        {escolaId ? (
          <ImportacaoMatriculas
            escolaId={escolaId}
            aoConcluir={recarregar}
            aoAvancar={() => setVerMatriculas(false)}
          />
        ) : null}
      </Drawer>
    </div>
  );
}

// --- Lista de alertas (com Resolver) ------------------------------------------
function ListaAlertas({ alertas, onResolver, resolvendo, erro }: {
  alertas: Alerta[]; onResolver: (id: number) => void; resolvendo: boolean; erro: string | null;
}) {
  return (
    <>
      <ul className="mt-2 space-y-2">
        {alertas.map((a) => (
          <li key={a.id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-zinc-200 px-3 py-2 dark:border-zinc-800">
            <span className="text-sm">
              <span className={a.severidade === "critico"
                ? "font-semibold text-red-600 dark:text-red-400"
                : "font-semibold text-amber-600 dark:text-amber-400"}>
                {rotuloAlerta(a.tipo)}
              </span>
              {" — "}{a.mensagem}
              <span className="ml-1 text-xs text-zinc-400">({fmtData(a.created_at)})</span>
            </span>
            <Botao variante="neutro" disabled={resolvendo} onClick={() => onResolver(a.id)}>Resolver</Botao>
          </li>
        ))}
      </ul>
      {erro && <div className="mt-2"><Mensagem tipo="erro">{erro}</Mensagem></div>}
    </>
  );
}

// --- "Dados recebidos" de uma plataforma ------------------------------------
// Só mostra o que o backend informou: cobertura por aluno quando existir;
// senão, os contadores da última execução (registros processados / linhas
// não vinculadas). Nunca inventa número. ``null`` na cobertura = o backend não
// conseguiu contar → cai nos contadores / "Nenhum dado recebido ainda".
// 0 com e 0 sem = não há aluno ativo no ano letivo (nunca "0 de 0").
function DadosRecebidos({ p }: { p: PlataformaStatus }) {
  const exec = p.ultima_execucao;
  const com = typeof p.alunos_com_dados === "number" ? p.alunos_com_dados : null;
  const sem = typeof p.alunos_sem_dados === "number" ? p.alunos_sem_dados : null;
  if (com === 0 && sem === 0) {
    return (
      <dd className="mt-0.5 text-zinc-500 dark:text-zinc-400">
        Nenhum aluno ativo matriculado no ano letivo
      </dd>
    );
  }
  if (com !== null) {
    const total = sem !== null ? com + sem : null;
    return (
      <>
        <dd className="mt-0.5 font-medium">
          {total !== null ? `${com} de ${total} alunos com dados` : `${com} alunos com dados`}
        </dd>
        {p.plataforma === "elefante" && p.alunos_com_zero_registros != null && (
          <dd className="text-xs text-zinc-500 dark:text-zinc-400">
            {`${p.alunos_com_zero_registros} com zero livros (zero real, não falta de dado)`}
          </dd>
        )}
        {p.dado_mais_recente_em && (
          <dd className="text-xs text-zinc-500 dark:text-zinc-400">
            dado mais recente: {fmtData(p.dado_mais_recente_em)}
          </dd>
        )}
      </>
    );
  }
  if (exec) {
    return (
      <>
        <dd className="mt-0.5">
          {`registros processados na última sincronização: ${exec.qtd_alunos}`}
        </dd>
        <dd className="text-xs text-zinc-500 dark:text-zinc-400">
          {`linhas não vinculadas: ${exec.qtd_erros}`}
        </dd>
      </>
    );
  }
  return <dd className="mt-0.5 text-zinc-500 dark:text-zinc-400">Nenhum dado recebido ainda.</dd>;
}

function descreverAgenda(p: PlataformaStatus): string | null {
  if (!p.agendada) return null;
  const hora = p.hora_local ? ` às ${p.hora_local}` : "";
  if (p.cadencia === "diaria") return `todos os dias${hora}`;
  if (p.cadencia === "semanal") {
    const dia = p.dia_semana != null ? DIAS[p.dia_semana] : null;
    return dia ? `toda ${dia}${hora}` : `uma vez por semana${hora}`;
  }
  return null;
}

// --- Card de uma plataforma -------------------------------------------------
function PlataformaCard({
  base, p, gestor, alertas, onResolver, resolvendo, erroResolver,
  onMudou, onSincronizar, onSincronizarPeriodo, sincronizando, onVerLogs,
}: {
  base: string;
  p: PlataformaStatus;
  gestor: boolean;
  alertas: Alerta[];
  onResolver: (id: number) => void;
  resolvendo: boolean;
  erroResolver: string | null;
  onMudou: () => void;
  onSincronizar: () => void;
  onSincronizarPeriodo: (inicio: string, fim: string) => void;
  sincronizando: boolean;
  onVerLogs: (id: number) => void;
}) {
  const nome = NOME[p.plataforma] ?? p.plataforma;
  const [pInicio, setPInicio] = useState("");
  const [pFim, setPFim] = useState("");
  const sit = situacaoIntegracao(p, nome, alertas);
  const exec = p.ultima_execucao;
  const agenda = descreverAgenda(p);
  const manualEmDestaque = !p.conectada || p.desatualizada || sit.chave === "falhou";

  return (
    <Card className="p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-base font-semibold tracking-tight">{nome}</h2>
        <StatusIntegracaoBadge situacao={sit} />
      </div>
      <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-300">{sit.frase}</p>
      {/* Texto cru do erro: recolhido e pequeno — útil para o suporte, fora do badge. */}
      {sit.detalheTecnico && (
        <details className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
          <summary className="cursor-pointer select-none hover:text-zinc-700 dark:hover:text-zinc-200">
            Ver detalhe técnico
          </summary>
          <p className="mt-1 break-words font-mono">Detalhe técnico: {sit.detalheTecnico}</p>
        </details>
      )}

      <dl className="mt-4 grid gap-4 text-sm sm:grid-cols-3">
        <div>
          <dt className="text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
            Última sincronização
          </dt>
          <dd className="mt-0.5 font-medium">{fmtData(exec?.finalizada_em ?? exec?.iniciada_em)}</dd>
          <dd className="text-xs text-zinc-500 dark:text-zinc-400">
            último sucesso: {fmtData(p.ultimo_sucesso_em)}
          </dd>
        </div>
        <div>
          <dt className="text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
            Próxima
          </dt>
          <dd className="mt-0.5 font-medium">{p.agendada ? fmtData(p.proxima_execucao) : "manual"}</dd>
          <dd className="text-xs text-zinc-500 dark:text-zinc-400">
            {agenda ?? "só quando você pedir"}
          </dd>
        </div>
        <div>
          <dt className="text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
            Dados recebidos
          </dt>
          <DadosRecebidos p={p} />
        </div>
      </dl>

      {/* Erros: alertas abertos DESTA plataforma */}
      {alertas.length > 0 && (
        <div id={`alertas-${p.plataforma}`} className="mt-4 scroll-mt-4">
          <h3 className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-red-700 dark:text-red-300">
            <AlertTriangle size={13} /> Erros ({alertas.length})
          </h3>
          <ListaAlertas alertas={alertas} onResolver={onResolver} resolvendo={resolvendo} erro={erroResolver} />
        </div>
      )}

      {/* Ações */}
      <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-zinc-100 pt-4 dark:border-zinc-800">
        <Botao disabled={!p.conectada || sincronizando} onClick={onSincronizar}>
          <RefreshCw size={15} /> Sincronizar {nome}
        </Botao>
        {sit.chave === "falhou" && exec && (
          <Botao variante="neutro" onClick={() => onVerLogs(exec.id)}>
            Ver o registro da falha
          </Botao>
        )}
        {p.plataforma === "elefante" && gestor && (
          <Link
            to="/diagnostico-elefante"
            className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-300 bg-white px-3.5 py-2 text-sm font-medium text-zinc-700 hover:bg-zinc-50 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-200 dark:hover:bg-zinc-800"
          >
            <Radar size={15} /> Ver diagnóstico
          </Link>
        )}
        {!p.conectada && (
          <span className="text-xs text-zinc-500 dark:text-zinc-400">
            Configure e valide a conexão para habilitar a sincronização.
          </span>
        )}
        <Link
          to="/importacoes"
          className={manualEmDestaque
            ? "ml-auto inline-flex items-center gap-1.5 rounded-lg border border-amber-300 bg-amber-50 px-3 py-1.5 text-xs font-medium text-amber-800 hover:bg-amber-100 dark:border-amber-500/40 dark:bg-amber-500/10 dark:text-amber-200"
            : "ml-auto inline-flex items-center gap-1.5 text-xs text-zinc-500 underline-offset-2 hover:underline dark:text-zinc-400"}
        >
          <FileUp size={13} /> Enviar relatório manualmente (avançado)
        </Link>
      </div>

      {/* Configurar conexão: aberta por padrão enquanto não houver credencial válida */}
      <BlocoRecolhivel
        titulo="Configurar conexão"
        icone={<Plug size={16} className="text-zinc-400" />}
        inicialAberto={p.credencial_status !== "valida"}
        descricao={`Acesso ao ${nome} e horário da atualização automática.`}
      >
        <div className="grid gap-6 lg:grid-cols-2">
          <div>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
              Acesso à plataforma
            </h3>
            <CredenciaisForm base={base} plataforma={p.plataforma} nome={nome}
              status={p.credencial_status} aoMudar={onMudou} />
            <p className="mt-2 text-xs text-zinc-500 dark:text-zinc-400">
              Validada em: {fmtData(p.validada_em)}
            </p>
          </div>
          <div>
            <h3 className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
              <CalendarClock size={13} /> Atualização automática
            </h3>
            <AgendaForm base={base} p={p} aoMudar={onMudou} />
          </div>
        </div>
      </BlocoRecolhivel>

      {/* Coleta POR PERÍODO — só Matific (o Elefante já tem leituras datadas). */}
      {p.plataforma === "matific" && p.conectada && (
        <BlocoRecolhivel
          titulo="Avançado: coletar um período específico"
          icone={<CalendarClock size={16} className="text-zinc-400" />}
          inicialAberto={false}
          descricao="Para premiar uma semana ou um mês: busca no Matific só o que foi feito naquelas datas."
        >
          <p className="mb-2 text-xs text-zinc-500 dark:text-zinc-400">
            Colete o Matific de um intervalo específico (semana, mês…). O ranking
            de matemática desse período mostra o que foi feito só naquelas datas.
          </p>
          <div className="flex flex-wrap items-end gap-2">
            <label className="text-xs text-zinc-500 dark:text-zinc-400">
              De
              <input type="date" className={`${estiloInput} mt-1 w-auto`} value={pInicio}
                     onChange={(e) => setPInicio(e.target.value)} />
            </label>
            <label className="text-xs text-zinc-500 dark:text-zinc-400">
              Até
              <input type="date" className={`${estiloInput} mt-1 w-auto`} value={pFim}
                     onChange={(e) => setPFim(e.target.value)} />
            </label>
            <Botao variante="neutro"
                   disabled={sincronizando || !pInicio || !pFim || pFim < pInicio}
                   onClick={() => onSincronizarPeriodo(pInicio, pFim)}>
              <CalendarClock size={15} /> Coletar do Matific este período
            </Botao>
          </div>
        </BlocoRecolhivel>
      )}
    </Card>
  );
}

// --- Sub-form: agendamento --------------------------------------------------
function AgendaForm({ base, p, aoMudar }: {
  base: string; p: PlataformaStatus; aoMudar: () => void;
}) {
  const [cadencia, setCadencia] = useState(p.cadencia || "manual");
  const [hora, setHora] = useState(p.hora_local || "03:00");
  const [dia, setDia] = useState(p.dia_semana ?? 0);

  const salvar = useMutation(async () => {
    await api(`${base}/config/${p.plataforma}`, {
      method: "PUT",
      body: JSON.stringify({
        ativo: cadencia !== "manual",
        cadencia,
        hora_local: hora,
        dia_semana: cadencia === "semanal" ? dia : null,
      }),
    });
  }, { aoSucesso: aoMudar });

  return (
    <div className="grid gap-3 sm:max-w-sm">
      <label className="block text-sm">
        <span className="mb-1 block font-medium text-zinc-700 dark:text-zinc-300">Frequência</span>
        <select className={estiloInput} value={cadencia}
          onChange={(e) => setCadencia(e.target.value)}>
          <option value="manual">Só quando eu pedir (manual)</option>
          <option value="diaria">Todos os dias</option>
          <option value="semanal">Uma vez por semana</option>
        </select>
      </label>

      {cadencia !== "manual" && (
        <div className="grid grid-cols-2 gap-3">
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-zinc-700 dark:text-zinc-300">Horário</span>
            <input type="time" className={estiloInput} value={hora}
              onChange={(e) => setHora(e.target.value)} />
          </label>
          {cadencia === "semanal" && (
            <label className="block text-sm">
              <span className="mb-1 block font-medium text-zinc-700 dark:text-zinc-300">Dia da semana</span>
              <select className={estiloInput} value={dia}
                onChange={(e) => setDia(Number(e.target.value))}>
                {DIAS.map((d, i) => <option key={i} value={i}>{d}</option>)}
              </select>
            </label>
          )}
        </div>
      )}

      <div className="flex items-center gap-2">
        <Botao variante="neutro" disabled={salvar.enviando} onClick={() => salvar.executar()}>
          {salvar.enviando ? "Salvando…" : "Salvar agendamento"}
        </Botao>
        {p.agendada && (
          <span className="text-xs text-emerald-600 dark:text-emerald-400">
            Ativo · próxima {fmtData(p.proxima_execucao)}
          </span>
        )}
      </div>
      {salvar.erro && <Mensagem tipo="erro">{salvar.erro.message}</Mensagem>}
      <p className="text-xs text-zinc-500 dark:text-zinc-400">
        A automática roda no horário definido (fuso do servidor) e só quando houver
        credencial válida. Requer o agendador ligado no servidor.
      </p>
    </div>
  );
}
