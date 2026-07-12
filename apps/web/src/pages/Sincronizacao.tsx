/**
 * Painel de Sincronização Automática de Plataformas.
 *
 * Conecta Matific e Elefante Letrado, agenda a atualização automática e dispara
 * sincronizações sob demanda, mostrando status, histórico, logs e alertas — tudo
 * por escola, respeitando o isolamento multi-tenant do AppContext (escolaId).
 * Toda a UI usa o design system (ui.tsx + Tailwind) — nada de classes soltas.
 */
import {
  AlertTriangle,
  CalendarClock,
  CheckCircle2,
  ChevronDown,
  Clock,
  History,
  RefreshCw,
  ScrollText,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { CredenciaisForm } from "../components/CredenciaisForm";
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

// --- Tipos (espelham app/sync/schemas.py) ----------------------------------
interface Execucao {
  id: number; plataforma: string; origem: string; status: string;
  iniciada_em: string | null; finalizada_em: string | null; duracao_ms: number;
  qtd_alunos: number; qtd_turmas: number; qtd_arquivos: number; qtd_erros: number;
  tentativa: number; erro_resumo: string | null; conector_versao: string | null;
  parser_versao: string | null; created_at: string;
}
interface PlataformaStatus {
  plataforma: string; estrategia: string; conectada: boolean;
  credencial_status: string; validada_em: string | null; ultimo_erro: string | null;
  agendada: boolean; cadencia: string; hora_local: string; dia_semana: number | null;
  proxima_execucao: string | null; ultima_execucao: Execucao | null;
}
interface EscolaStatus {
  escola_id: number; escola_nome: string; qtd_alunos: number; qtd_turmas: number;
  plataformas: PlataformaStatus[]; alertas_abertos: number;
  lista_piloto_importada: boolean; integracao_configurada: boolean;
}
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
  escolas_com_erro: number; em_andamento: number; fila: number; workers_ativos: number;
  scheduler_ligado: boolean; ultima_sincronizacao: string | null;
  duracao_ultima_ms: number | null; tempo_medio_ms: number | null; alertas_abertos: number;
}

const NOME: Record<string, string> = { matific: "Matific", elefante: "Elefante Letrado" };
const DIAS = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"];

// Usa o formatador compartilhado (trata UTC naive + horário de Brasília).
const fmtData = (s: string | null) => dataHora(s);
const fmtDur = (ms: number | null) => (ms ? `${(ms / 1000).toFixed(1)}s` : "—");

// Estados possíveis (credencial + execução) → rótulo humano + cor theme-aware.
const ESTADO: Record<string, { rotulo: string; classe: string }> = {
  valida: { rotulo: "conectada", classe: "bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300" },
  concluida: { rotulo: "concluída", classe: "bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300" },
  invalida: { rotulo: "credencial inválida", classe: "bg-red-50 text-red-700 dark:bg-red-500/10 dark:text-red-300" },
  expirada: { rotulo: "credencial expirada", classe: "bg-red-50 text-red-700 dark:bg-red-500/10 dark:text-red-300" },
  erro: { rotulo: "erro", classe: "bg-red-50 text-red-700 dark:bg-red-500/10 dark:text-red-300" },
  executando: { rotulo: "executando", classe: "bg-indigo-50 text-indigo-700 dark:bg-indigo-500/10 dark:text-indigo-300" },
  fila: { rotulo: "na fila", classe: "bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300" },
  nao_validada: { rotulo: "não validada", classe: "bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300" },
  cancelada: { rotulo: "cancelada", classe: "bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300" },
  sem_dados: { rotulo: "sem dados novos", classe: "bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300" },
  nao_configurada: { rotulo: "não configurada", classe: "bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300" },
};

function EstadoBadge({ status }: { status: string }) {
  const e = ESTADO[status] ?? { rotulo: status.replace(/_/g, " "), classe: ESTADO.nao_configurada.classe };
  return (
    <span className={`inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium ${e.classe}`}>
      {e.rotulo}
    </span>
  );
}

export default function Sincronizacao() {
  const { escolaId, usuario } = useApp();
  const base = escolaId ? `/escolas/${escolaId}/sync` : null;

  const status = useApi<EscolaStatus>(base ? `${base}/status` : null);
  const historico = useApi<Execucao[]>(base ? `${base}/historico?limite=30` : null);
  const alertas = useApi<Alerta[]>(base ? `${base}/alertas?resolvido=false` : null);
  const dashboard = useApi<Dashboard>(usuario?.is_global ? "/sync/dashboard" : null);

  const [execLog, setExecLog] = useState<number | null>(null);
  // Alertas e Histórico ficam recolhíveis (clique no cabeçalho abre/fecha) —
  // fechados por padrão para a tela ficar limpa.
  const [verAlertas, setVerAlertas] = useState(false);
  const [verHistorico, setVerHistorico] = useState(false);
  const logs = useApi<LogLinha[]>(
    base && execLog ? `${base}/logs?execucao_id=${execLog}&limite=200` : null);

  const recarregar = useCallback(() => {
    status.recarregar(); historico.recarregar(); alertas.recarregar();
    if (usuario?.is_global) dashboard.recarregar();
  }, [status, historico, alertas, dashboard, usuario]);

  // Auto-atualiza enquanto houver execução em andamento (polling leve).
  const emAndamento = (historico.dados ?? []).some(
    (e) => e.status === "executando" || e.status === "fila");
  useEffect(() => {
    if (!emAndamento) return;
    const t = setInterval(recarregar, 4000);
    return () => clearInterval(t);
  }, [emAndamento, recarregar]);

  const sincronizar = useMutation(async (plataforma?: string) => {
    const q = plataforma ? `?plataforma=${plataforma}` : "";
    await api(`${base}/agora${q}`, { method: "POST" });
  }, { aoSucesso: recarregar });

  const resolver = useMutation(async (id: number) => {
    await api(`${base}/alertas/${id}/resolver`, { method: "POST" });
  }, { aoSucesso: recarregar });

  if (!escolaId) {
    return <Vazio titulo="Selecione uma escola" descricao="Escolha uma escola para configurar a sincronização." />;
  }

  const dados = status.dados;

  return (
    <div className="space-y-6">
      <PageHeader
        titulo="Sincronização automática"
        descricao="Conecte Matific e Elefante Letrado e mantenha os dados atualizados sem upload manual. O upload manual continua disponível como alternativa."
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

      {dados && !dados.lista_piloto_importada && (
        <Mensagem tipo="erro">
          Nenhuma turma cadastrada ainda. Comece pela <Link className="font-semibold underline" to="/comecar">
          configuração inicial da escola</Link> (Lista Piloto) para criar turmas e alunos.
        </Mensagem>
      )}

      {/* Dashboard global — só usuário com acesso total */}
      {usuario?.is_global && (
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
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
            <StatCard icone={<CheckCircle2 size={15} />} rotulo="Configuradas" valor={String(dashboard.dados.escolas_configuradas)} detalhe={`de ${dashboard.dados.escolas_total}`} />
            <StatCard icone={<RefreshCw size={15} />} rotulo="Sincronizadas" valor={String(dashboard.dados.escolas_sincronizadas)} />
            <StatCard icone={<AlertTriangle size={15} />} rotulo="Com erro" valor={String(dashboard.dados.escolas_com_erro)} />
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

      {/* Cards por plataforma */}
      {dados?.plataformas.map((p) => (
        <PlataformaCard
          key={p.plataforma}
          base={base!}
          p={p}
          onMudou={recarregar}
          onSincronizar={() => sincronizar.executar(p.plataforma)}
          sincronizando={sincronizar.enviando}
          onVerLogs={(execId) => setExecLog(execId)}
        />
      ))}

      {/* Alertas abertos */}
      {alertas.erro && !alertas.dados && (
        <Mensagem tipo="erro">
          Não foi possível carregar os alertas: {alertas.erro.message}
        </Mensagem>
      )}
      {(alertas.dados?.length ?? 0) > 0 && (
        <Card className="p-5">
          <button
            type="button"
            onClick={() => setVerAlertas((v) => !v)}
            aria-expanded={verAlertas}
            className="flex w-full items-center gap-2 text-base font-semibold tracking-tight"
          >
            <AlertTriangle size={17} className="text-amber-500" />
            Alertas ({alertas.dados!.length})
            <ChevronDown
              size={17}
              className={`ml-auto text-zinc-400 transition-transform ${verAlertas ? "rotate-180" : ""}`}
            />
          </button>
          {verAlertas && (
          <ul className="mt-3 space-y-2">
            {alertas.dados!.map((a) => (
              <li key={a.id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-zinc-200 px-3 py-2 dark:border-zinc-800">
                <span className="text-sm">
                  <span className={a.severidade === "critico"
                    ? "font-semibold text-red-600 dark:text-red-400"
                    : "font-semibold text-amber-600 dark:text-amber-400"}>
                    {a.tipo.replace(/_/g, " ")}
                  </span>
                  {" — "}{a.mensagem}
                  <span className="ml-1 text-xs text-zinc-400">({fmtData(a.created_at)})</span>
                </span>
                <Botao variante="neutro" disabled={resolver.enviando}
                  onClick={() => resolver.executar(a.id)}>Resolver</Botao>
              </li>
            ))}
          </ul>
          )}
          {verAlertas && resolver.erro && <div className="mt-2"><Mensagem tipo="erro">{resolver.erro.message}</Mensagem></div>}
        </Card>
      )}

      {/* Histórico */}
      <Card className="p-5">
        <button
          type="button"
          onClick={() => setVerHistorico((v) => !v)}
          aria-expanded={verHistorico}
          className="flex w-full items-center gap-2 text-base font-semibold tracking-tight"
        >
          <History size={17} className="text-zinc-400" /> Histórico de sincronizações
          <ChevronDown
            size={17}
            className={`ml-auto text-zinc-400 transition-transform ${verHistorico ? "rotate-180" : ""}`}
          />
        </button>
        {verHistorico && (historico.carregando && !historico.dados ? (
          <Carregando texto="Carregando histórico…" />
        ) : (historico.dados?.length ?? 0) === 0 ? (
          <Vazio titulo="Nenhuma sincronização ainda"
            descricao="Assim que você conectar uma plataforma e sincronizar, o histórico aparece aqui." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-zinc-200 text-left text-xs uppercase tracking-wide text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
                  <th className="px-3 py-2 font-medium">Quando</th>
                  <th className="px-3 py-2 font-medium">Plataforma</th>
                  <th className="hidden px-3 py-2 font-medium sm:table-cell">Origem</th>
                  <th className="px-3 py-2 font-medium">Status</th>
                  <th className="px-3 py-2 text-right font-medium">Alunos</th>
                  <th className="hidden px-3 py-2 text-right font-medium md:table-cell">Erros</th>
                  <th className="hidden px-3 py-2 text-right font-medium sm:table-cell">Duração</th>
                  <th className="px-3 py-2 font-medium">Logs</th>
                </tr>
              </thead>
              <tbody>
                {historico.dados!.map((e) => (
                  <tr key={e.id} className="border-b border-zinc-100 last:border-0 dark:border-zinc-800/60">
                    <td className="px-3 py-2 whitespace-nowrap">{fmtData(e.iniciada_em ?? e.created_at)}</td>
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
        ))}
      </Card>

      {/* Logs da execução — painel lateral */}
      <Drawer titulo={execLog ? `Logs da execução #${execLog}` : "Logs"}
        aberto={execLog !== null} aoFechar={() => setExecLog(null)}>
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
    </div>
  );
}

// --- Card de uma plataforma -------------------------------------------------
function PlataformaCard({
  base, p, onMudou, onSincronizar, sincronizando, onVerLogs,
}: {
  base: string;
  p: PlataformaStatus;
  onMudou: () => void;
  onSincronizar: () => void;
  sincronizando: boolean;
  onVerLogs: (id: number) => void;
}) {
  const nome = NOME[p.plataforma] ?? p.plataforma;
  return (
    <Card className="p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-base font-semibold tracking-tight">{nome}</h2>
        <EstadoBadge status={p.credencial_status} />
      </div>
      <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
        Estratégia: {p.estrategia === "navegador" ? "automação de navegador" : p.estrategia}
        {" · "}Validada: {fmtData(p.validada_em)}
        {" · "}Última sincronização: {fmtData(p.ultima_execucao?.iniciada_em ?? null)}
        {" · "}Próxima: {p.agendada ? fmtData(p.proxima_execucao) : "manual"}
      </p>
      {p.ultimo_erro && (
        <div className="mt-3"><Mensagem tipo="erro">Último erro: {p.ultimo_erro}</Mensagem></div>
      )}

      <div className="mt-4 grid gap-6 lg:grid-cols-2">
        <div>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
            Credenciais
          </h3>
          <CredenciaisForm base={base} plataforma={p.plataforma} nome={nome}
            status={p.credencial_status} aoMudar={onMudou} />
        </div>
        <div>
          <h3 className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
            <CalendarClock size={13} /> Agendamento
          </h3>
          <AgendaForm base={base} p={p} aoMudar={onMudou} />
        </div>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-zinc-100 pt-4 dark:border-zinc-800">
        <Botao disabled={!p.conectada || sincronizando} onClick={onSincronizar}>
          <RefreshCw size={15} /> Sincronizar {nome}
        </Botao>
        {p.ultima_execucao && (
          <Botao variante="neutro" onClick={() => onVerLogs(p.ultima_execucao!.id)}>
            <ScrollText size={15} /> Ver logs da última
          </Botao>
        )}
        {!p.conectada && (
          <span className="text-xs text-zinc-500 dark:text-zinc-400">
            Configure e valide as credenciais para habilitar a sincronização.
          </span>
        )}
      </div>
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
