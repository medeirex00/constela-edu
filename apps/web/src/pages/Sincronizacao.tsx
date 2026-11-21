/**
 * Integrações (rota /sincronizacao).
 *
 * A tela da ESCOLA para conferir se os dados das plataformas (Matific e
 * Elefante Letrado) estão chegando e atualizados. Um card por plataforma diz,
 * em uma frase, a situação (Atualizado / Atualizado em parte / Verificado em
 * parte / Verificado: nada mudou / Sem atualização: correspondência pendente /
 * Sem dados na última coleta / Dados desatualizados / Falhou / Nova tentativa
 * pendente / Ainda não configurada / Sem dados ainda), quando foi o último DADO APLICADO, a última
 * VERIFICAÇÃO e a última TENTATIVA (são coisas diferentes), quando é a
 * próxima, quantos alunos têm dados e o que a última coleta fez (alunos
 * atualizados, linhas recebidas, em revisão, falhas). Recálculo pendente
 * aparece em vermelho no topo e no card. A configuração da conexão e a coleta
 * por período ficam recolhidas; histórico e logs viram "Detalhes técnicos"
 * (abertos por padrão só para o Admin Global).
 *
 * Nada muda de endpoint: usa GET /escolas/{id}/sync/status, /historico,
 * /alertas, /logs e os POST/PUT já existentes. Campos novos do status
 * (cobertura por aluno, contrato da etapa 2) são OPCIONAIS e só aparecem
 * quando o backend informa. Toda a UI usa o design system (ui.tsx + Tailwind).
 *
 * O card "Criação de alunos pela sincronização" mostra a política da escola
 * (GET/PUT /escolas/{id}/configuracoes/sincronizacao, já existentes): se a
 * plataforma pode criar ficha ("permitir") ou não matricula ninguém
 * ("bloquear"). A gestão da escola LÊ; só o Admin Global muda, com confirmação
 * (o PUT recusa os demais com 403). Professor não vê (o GET pede cargo).
 */
import {
  Activity,
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
  ShieldCheck,
  Timer,
  Users,
  Wrench,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import type { MouseEvent, ReactNode } from "react";
import { Link } from "react-router-dom";

import { CaixaAviso } from "../components/CaixaAviso";
import { CredenciaisForm } from "../components/CredenciaisForm";
import { IconePlataforma, identidadeDe } from "../components/identidadePlataforma";
import {
  ExecucaoBadge,
  NOME_PLATAFORMA as NOME,
  StatusIntegracaoBadge,
  descreverExecucao,
  idadeHumana,
  precisaVerificacao,
  recalculoPendente,
  rotuloAlerta,
  situacaoIntegracao,
  temContagemPorAluno,
  ultimaTentativa,
} from "../components/StatusIntegracao";
import type { EscolaStatus, Execucao, PlataformaStatus } from "../components/StatusIntegracao";
import ImportacaoMatriculas from "./ImportacaoMatriculas";
import {
  Badge,
  Botao,
  Card,
  Carregando,
  Drawer,
  ESTILOS_BOTAO,
  Erro,
  IconePastel,
  Mensagem,
  Modal,
  PageHeader,
  StatCard,
  TAMANHOS_BOTAO,
  Vazio,
  classesTabela,
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
/** Pré-requisitos para religar o agendador (backend: app/sync/prerequisitos.py). */
interface VerificacaoAgendador { id: string; ok: boolean; critico: boolean; motivo: string }
interface PrerequisitosAgendador {
  habilitado: boolean; forcar: boolean; pode_iniciar: boolean;
  decisao_no_boot?: string | null; criticos_falhos: string[];
  verificacoes: VerificacaoAgendador[];
}
interface Dashboard {
  /** Escolas com ao menos uma coleta que APLICOU dado (concluída ou parcial). */
  escolas_total: number; escolas_configuradas: number; escolas_sincronizadas: number;
  escolas_com_erro: number; escolas_desatualizadas: number;
  em_andamento: number; fila: number; workers_ativos: number;
  /** Fim da última coleta que aplicou dado (concluída ou parcial). */
  scheduler_ligado: boolean; ultima_sincronizacao: string | null;
  duracao_ultima_ms: number | null; tempo_medio_ms: number | null; alertas_abertos: number;
  /** Só o admin global recebe; ``null`` = a verificação não pôde rodar. Opcional. */
  prerequisitos_agendador?: PrerequisitosAgendador | null;
}

const DECISAO_BOOT: Record<string, string> = {
  desligado: "desligado (SYNC_SCHEDULER_ENABLED não está ligado)",
  recusado: "recusado (pré-requisito crítico falhou no boot)",
  iniciado: "iniciado",
  forcado: "iniciado à força (SYNC_SCHEDULER_FORCAR)",
};

/** Bloco do painel global: o agendador pode ser religado? (frente E). */
function PrerequisitosAgendadorBloco({ p }: { p: PrerequisitosAgendador }) {
  const falhos = p.verificacoes.filter((v) => v.critico && !v.ok);
  const avisos = p.verificacoes.filter((v) => !v.critico && !v.ok);
  return (
    <section className="card p-5" aria-label="Pré-requisitos do agendador">
      <h3 className="flex items-center gap-2.5 text-[15px] font-semibold text-zinc-900 dark:text-white">
        <IconePastel icone={ShieldCheck} tom={p.pode_iniciar ? "verde" : "rosa"} tamanho="sm" />
        Pré-requisitos para religar o agendador
      </h3>
      <p className="mt-2 text-sm text-zinc-600 dark:text-zinc-300">
        {p.pode_iniciar
          ? "Nenhum pré-requisito crítico falhando. Religar continua sendo decisão do dono, pela checklist de docs/sync/REATIVAR-AGENDADOR.md."
          : `${falhos.length} pré-requisito(s) crítico(s) falhando: mesmo com SYNC_SCHEDULER_ENABLED=true o agendador recusa subir.`}
        {p.decisao_no_boot ? ` Neste servidor, no boot: ${DECISAO_BOOT[p.decisao_no_boot] ?? p.decisao_no_boot}.` : ""}
      </p>
      {(falhos.length > 0 || avisos.length > 0) && (
        <ul className="mt-3 space-y-1.5 text-xs" aria-label="Pré-requisitos que falharam">
          {[...falhos, ...avisos].map((v) => (
            <li key={v.id} className={`rounded-xl px-3 py-2 ${v.critico
              ? "bg-rose-50 text-rose-700 dark:bg-rose-500/10 dark:text-rose-300"
              : "bg-ouro-50 text-ouro-700 dark:bg-ouro-400/10 dark:text-ouro-300"}`}>
              <span className="font-mono">{v.id}</span>{v.critico ? " (crítico)" : " (aviso)"}: {v.motivo}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

const DIAS = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"];

// Usa o formatador compartilhado (trata UTC naive + horário de Brasília).
const fmtData = (s: string | null | undefined) => dataHora(s ?? null);
const fmtDur = (ms: number | null) => (ms ? `${(ms / 1000).toFixed(1)}s` : "—");

// Rótulos dos tipos de alerta e dos status de execução: mapa único em
// components/StatusIntegracao (o badge do card e o histórico usam o mesmo).

/** "01/10/2026" a partir de "2026-10-01" (sem fuso: é uma data de calendário). */
function fmtDia(iso: string | null | undefined): string | null {
  const m = iso ? /^(\d{4})-(\d{2})-(\d{2})/.exec(iso) : null;
  return m ? `${m[3]}/${m[2]}/${m[1]}` : null;
}

/** "período 01/10/2026 a 15/10/2026" quando a execução pediu um período. */
function textoPeriodo(e: Execucao | null | undefined): string | null {
  const inicio = fmtDia(e?.periodo?.inicio);
  const fim = fmtDia(e?.periodo?.fim);
  if (!inicio && !fim) return null;
  if (inicio && fim) return inicio === fim ? `período ${inicio}` : `período ${inicio} a ${fim}`;
  return `período ${inicio ?? fim}`;
}

/** Bloco recolhível leve (sem Card próprio) — para seções dentro de um card. */
function BlocoRecolhivel({
  titulo, icone, inicialAberto = false, descricao, children, semBorda = false,
}: {
  titulo: string; icone?: ReactNode; inicialAberto?: boolean;
  descricao?: string; children: ReactNode;
  /** Sem a linha de cima (quando o bloco é o único conteúdo do cartão). */
  semBorda?: boolean;
}) {
  const [aberto, setAberto] = useState(inicialAberto);
  return (
    <div className={semBorda ? "pt-4" : "mt-5 border-t border-zinc-100 pt-4 dark:border-zinc-800"}>
      <button
        type="button"
        onClick={() => setAberto((a) => !a)}
        aria-expanded={aberto}
        className="-m-1 flex w-[calc(100%+0.5rem)] items-center gap-2.5 rounded-xl p-1 text-left text-sm font-semibold text-zinc-800 transition-colors hover:text-indigo-600 dark:text-zinc-100 dark:hover:text-indigo-400"
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
        <p className="mt-1 pl-[2.625rem] text-xs text-zinc-500 dark:text-zinc-400">{descricao}</p>
      )}
      {aberto && <div className="mt-4">{children}</div>}
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

  // Recarga SEM cancelar o que está em voo. O `recarregar` do useApi aborta a
  // busca em andamento e recomeça (o proxy registra 499): com o /status mais
  // lento que o intervalo do polling, nenhum chegava ao fim e o card não
  // atualizava. Aqui um recurso ainda carregando NÃO é abortado: o tick do
  // polling o pula; uma recarga pedida (Atualizar, sucesso de uma ação) fica
  // pendente e sai assim que ele termina. Os `recarregar` do useApi são
  // estáveis, então o intervalo não recomeça a cada render.
  const recursos = { status, historico, alertas, dashboard };
  const refRecursos = useRef(recursos);
  refRecursos.current = recursos;
  const pendentes = useRef(new Set<keyof typeof recursos>());

  const recarregarSemCancelar = useCallback((repetirAoTerminar: boolean) => {
    const nomes = (["status", "historico", "alertas", "dashboard"] as const)
      .filter((nome) => nome !== "dashboard" || global);
    for (const nome of nomes) {
      const recurso = refRecursos.current[nome];
      if (!recurso.carregando) recurso.recarregar();
      else if (repetirAoTerminar) pendentes.current.add(nome);
    }
  }, [global]);
  const recarregar = useCallback(() => recarregarSemCancelar(true), [recarregarSemCancelar]);

  useEffect(() => {
    for (const nome of Array.from(pendentes.current)) {
      const recurso = refRecursos.current[nome];
      if (!recurso.carregando) {
        pendentes.current.delete(nome);
        recurso.recarregar();
      }
    }
  }, [status.carregando, historico.carregando, alertas.carregando, dashboard.carregando]);

  // Auto-atualiza enquanto houver execução em andamento (polling leve). Uma
  // NOVA TENTATIVA na fila (tentativa > 1) espera o atraso do agendador: é
  // consultada devagar; fila parada (agendador desligado) não é consultada.
  const filasParadas = new Set((status.dados?.plataformas ?? [])
    .filter((p) => p.fila_parada && p.ultima_execucao)
    .map((p) => p.ultima_execucao!.id));
  const vivas = [
    ...(historico.dados ?? []),
    ...(status.dados?.plataformas ?? []).flatMap((p) => (p.ultima_execucao ? [p.ultima_execucao] : [])),
  ].filter((e) => !filasParadas.has(e.id));
  const intervalo = vivas.some((e) => e.status === "executando"
    || (e.status === "fila" && (e.tentativa ?? 1) <= 1))
    ? 4000
    : vivas.some((e) => e.status === "fila") ? 30000 : null;
  useEffect(() => {
    if (!intervalo) return;
    const t = setInterval(() => recarregarSemCancelar(false), intervalo);
    return () => clearInterval(t);
  }, [intervalo, recarregarSemCancelar]);

  // De onde veio o último "Sincronizar": o erro aparece perto do botão clicado
  // (no card da plataforma) e não só no topo da página.
  const [origemSync, setOrigemSync] = useState<string | null>(null);
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

  // Recálculo pendente: o mesmo POST /importacoes/recalcular da tela de
  // Importações. Um recálculo que dá certo fecha a pendência no backend (alerta
  // e marca das execuções) — o /status recarregado tira o aviso.
  const recalcular = useMutation(async () => {
    await api(`/escolas/${escolaId}/importacoes/recalcular`, { method: "POST" });
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
    verificacao.alertas > 0 || verificacao.pendencias > 0 || verificacao.desatualizadas.length > 0
    || verificacao.parciais.length > 0 || verificacao.correspondenciaPendente.length > 0
    || verificacao.tudoEmRevisao.length > 0 || verificacao.recadastrar.length > 0));
  // "Chegam sozinhos" só quando o servidor diz que o agendador está ligado.
  const descricaoTela = dados?.agendador_ativo === true
    ? "Os dados das plataformas chegam sozinhos. Aqui você confere se estão atualizados."
    : dados?.agendador_ativo === false
      ? "A atualização automática está desligada neste servidor: os dados só chegam quando alguém clica em “Sincronizar”. Aqui você confere se estão atualizados."
      : "Aqui você confere se os dados das plataformas estão chegando e atualizados.";

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
    (platDoLog && ["falhou", "indisponivel", "nova_tentativa"].includes(situacaoIntegracao(platDoLog).chave)
      ? platDoLog.ultimo_erro : null) ||
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
        descricao={descricaoTela}
        acoes={
          <div className="flex flex-wrap items-center gap-2.5">
            {dados && (
              dados.integracao_configurada
                ? <Badge tom="ok">✓ Integração configurada</Badge>
                : <Badge tom="alerta">Integração pendente</Badge>
            )}
            <Botao variante="secundario" onClick={recarregar}>
              <RefreshCw size={15} aria-hidden /> Atualizar
            </Botao>
            {/* Matrícula (Lista Piloto) NÃO vem da sincronização — ela coleta
                desempenho, não o cadastro. Por isso o roster é atualizado aqui. */}
            <Botao variante="secundario" onClick={() => setVerMatriculas(true)}>
              <Users size={15} aria-hidden /> {dados?.lista_piloto_importada ? "Atualizar Lista Piloto" : "Importar Lista Piloto"}
            </Botao>
            <Botao disabled={sincronizar.enviando || !dados?.integracao_configurada}
              onClick={() => { setOrigemSync(null); void sincronizar.executar(undefined); }}>
              <RefreshCw size={15} aria-hidden
                className={sincronizar.enviando ? "animate-spin motion-reduce:animate-none" : ""} />
              {sincronizar.enviando ? "Sincronizando…" : "Sincronizar agora"}
            </Botao>
          </div>
        }
      />

      {sincronizar.erro && origemSync === null && <Mensagem tipo="erro">{sincronizar.erro.message}</Mensagem>}

      {/* Estados de carregamento / erro do status principal */}
      {status.carregando && !dados && <Carregando texto="Carregando integrações…" />}
      {status.erro && !dados && (
        <Card className="p-2">
          <Erro titulo="Não foi possível carregar as integrações"
            descricao={status.erro.message}
            aoTentar={() => status.recarregar()} />
        </Card>
      )}

      {/* Recálculo pendente: o dado entrou, mas as notas/rankings não — em
          vermelho, acima de tudo (é o que faz o ranking mostrar valor antigo). */}
      {dados && verificacao && verificacao.recalculoPendente.length > 0 && (
        <CaixaAviso
          tom="erro"
          role="alert"
          icone={AlertTriangle}
          titulo={`Recálculo pendente: ${verificacao.recalculoPendente.join(" e ")}.`}
        >
          <div className="min-w-0 space-y-1">
            <p className="text-xs">
              Os dados da última coleta foram gravados, mas as notas e os rankings ainda
              não foram recalculados: eles podem estar mostrando valores antigos.{" "}
              {gestor
                ? "Use “Recalcular agora” (ou sincronize de novo); se a falha se repetir, avise o suporte."
                : "Peça à coordenação da escola para usar “Recalcular agora” nesta tela."}
            </p>
            {gestor && (
              <div className="pt-2">
                <Botao variante="secundario" tamanho="sm" disabled={recalcular.enviando}
                  onClick={() => { void recalcular.executar(); }}>
                  <RefreshCw size={14} aria-hidden
                    className={recalcular.enviando ? "animate-spin motion-reduce:animate-none" : ""} />
                  {recalcular.enviando ? "Recalculando…" : "Recalcular agora"}
                </Botao>
              </div>
            )}
            {recalcular.erro && <Mensagem tipo="erro">{recalcular.erro.message}</Mensagem>}
          </div>
        </CaixaAviso>
      )}

      {/* Banner: há algo que a escola precisa olhar */}
      {dados && verificacao && temProblema && (
        <CaixaAviso tom="alerta" role="status" titulo="Atenção: há dados que precisam de verificação.">
          <div className="min-w-0 space-y-1">
            <ul className="list-inside list-disc space-y-0.5 text-xs">
              {verificacao.recadastrar.length > 0 && (
                <li>
                  Recadastre o acesso: {verificacao.recadastrar.join(" e ")} (a senha salva não
                  pode mais ser lida pelo servidor; informe usuário e senha de novo em
                  “Configurar conexão”).
                </li>
              )}
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
              {verificacao.parciais.length > 0 && (
                <li>
                  Coleta parcial: {verificacao.parciais.join(" e ")} (parte da última coleta
                  falhou; o que chegou foi aplicado ou conferido).
                </li>
              )}
              {verificacao.correspondenciaPendente.length > 0 && (
                <li>
                  Sem atualização por correspondência pendente: {verificacao.correspondenciaPendente.join(" e ")} (a
                  coleta trouxe dados, mas nenhum aluno foi atualizado até alguém escolher o aluno certo).
                </li>
              )}
              {verificacao.tudoEmRevisao.length > 0 && (
                <li>
                  Nenhuma conta da escola reconhecida na última coleta: {verificacao.tudoEmRevisao.join(" e ")} (tudo
                  ficou em revisão, e isso não conta como dado em dia; confira se o acesso cadastrado é o desta escola).
                </li>
              )}
            </ul>
            <div className="flex flex-wrap gap-x-4 gap-y-1 pt-2 text-xs font-semibold text-indigo-700 dark:text-indigo-300">
              {verificacao.alertas > 0 && (
                <a href={`#${alvoAlertas}`} onClick={irPara(alvoAlertas)} className="underline underline-offset-2">
                  Ver alertas
                </a>
              )}
              {(verificacao.pendencias > 0 || verificacao.correspondenciaPendente.length > 0
                || verificacao.tudoEmRevisao.length > 0) && (
                <Link to="/revisoes-identidade" className="underline underline-offset-2">Ver revisões de identidade</Link>
              )}
              <Link to="/importacoes" className="underline underline-offset-2">Ver importações (avançado)</Link>
            </div>
          </div>
        </CaixaAviso>
      )}

      {dados && !dados.lista_piloto_importada && (
        // Aviso, não erro: nada falhou — falta o primeiro passo da escola.
        <CaixaAviso tom="alerta" role="status" icone={Users}>
          <p>
            Nenhuma turma cadastrada ainda. Comece pela <Link className="font-semibold text-indigo-700 underline dark:text-indigo-300" to="/comecar">
            configuração inicial da escola</Link> (Lista Piloto) para criar turmas e alunos.
          </p>
        </CaixaAviso>
      )}

      {/* Visão geral — só usuário com acesso total */}
      {global && (
        <section className="space-y-4">
          <h2 className="text-[11px] font-semibold uppercase tracking-[0.08em] text-zinc-500 dark:text-zinc-400">
            Visão geral (todas as escolas)
          </h2>
          {dashboard.erro && !dashboard.dados && (
            <Mensagem tipo="erro">
              Não foi possível carregar a visão geral: {dashboard.erro.message}
            </Mensagem>
          )}
          {dashboard.carregando && !dashboard.dados && <Carregando texto="Carregando visão geral…" />}
          {dashboard.dados && (<>
          {/* Contadores numa grade que cabe de 820 a 1440 px; tempo e data (textos
              longos) ficam numa linha própria, mais larga. */}
          <div className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-5">
            <StatCard tom="verde" icone={<CheckCircle2 size={20} />} rotulo="Configuradas" valor={String(dashboard.dados.escolas_configuradas)} detalhe={`de ${dashboard.dados.escolas_total}`} />
            <StatCard tom="violeta" icone={<RefreshCw size={20} />} rotulo="Já sincronizaram" valor={String(dashboard.dados.escolas_sincronizadas)} detalhe="com dado aplicado alguma vez" />
            <StatCard tom="rosa" icone={<AlertTriangle size={20} />} rotulo="Com erro" valor={String(dashboard.dados.escolas_com_erro)} />
            <StatCard tom="ambar" icone={<Clock size={20} />} rotulo="Desatualizadas" valor={String(dashboard.dados.escolas_desatualizadas)} detalhe="dados envelhecendo" />
            <StatCard tom="azul" icone={<Activity size={20} />} rotulo="Em andamento" valor={String(dashboard.dados.em_andamento)} detalhe={`${dashboard.dados.fila} na fila`} />
          </div>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <StatCard tom="neutro" icone={<Timer size={20} />} rotulo="Tempo médio" valor={fmtDur(dashboard.dados.tempo_medio_ms)} />
            <StatCard tom="violeta" icone={<History size={20} />} rotulo="Último dado aplicado" valor={fmtData(dashboard.dados.ultima_sincronizacao)} />
          </div>
          {!dashboard.dados.scheduler_ligado && (
            // Estado do servidor, não erro desta tela: aviso âmbar.
            <CaixaAviso tom="alerta" role="status" icone={Clock}>
              <p>
                O agendador automático está <strong>desligado</strong> no servidor
                (SYNC_SCHEDULER_ENABLED). As sincronizações manuais funcionam; a automática
                só volta pela checklist de reativação, com os pré-requisitos abaixo.
              </p>
            </CaixaAviso>
          )}
          {dashboard.dados.prerequisitos_agendador && (
            <PrerequisitosAgendadorBloco p={dashboard.dados.prerequisitos_agendador} />
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
          onSincronizar={() => {
            setOrigemSync(p.plataforma);
            void sincronizar.executar({ plataforma: p.plataforma });
          }}
          onSincronizarPeriodo={(inicio, fim) => {
            setOrigemSync(p.plataforma);
            void sincronizar.executar({ plataforma: p.plataforma, inicio, fim });
          }}
          sincronizando={sincronizar.enviando}
          erroSincronizar={origemSync === p.plataforma ? sincronizar.erro?.message ?? null : null}
          onVerLogs={(execId) => setExecLog(execId)}
          agendadorAtivo={dados.agendador_ativo}
        />
      ))}

      {/* Alertas sem plataforma (raros): ficam num bloco próprio */}
      {alertasGerais.length > 0 && (
        <Card className="p-6">
          <div id="alertas-gerais" className="scroll-mt-4">
            <h2 className="flex items-center gap-3 text-[17px] font-semibold tracking-tight text-zinc-900 dark:text-white">
              <IconePastel icone={AlertTriangle} tom="ambar" />
              Outros alertas ({alertasGerais.length})
            </h2>
            <ListaAlertas alertas={alertasGerais} onResolver={(id) => resolver.executar(id)}
              resolvendo={resolver.enviando} erro={resolver.erro?.message ?? null} />
          </div>
        </Card>
      )}

      {/* Política de criação de aluno: a gestão lê, só o Admin Global muda. O
          professor não vê (o GET da política pede cargo de gestão). */}
      {gestor && <PoliticaCriacaoAluno key={escolaId} escolaId={escolaId} global={global} />}

      {/* Detalhes técnicos: histórico + logs (aberto por padrão só para o global) */}
      {dados && (
        <Card className="px-6 pb-5 pt-1">
          <BlocoRecolhivel
            key={global ? "global" : "escola"}
            semBorda
            titulo="Detalhes técnicos"
            icone={<IconePastel icone={Wrench} tom="neutro" tamanho="sm" />}
            inicialAberto={global}
            descricao="Histórico das sincronizações e registro de cada execução. Útil para o suporte; não é necessário no dia a dia."
          >
            {historico.carregando && !historico.dados ? (
              <Carregando texto="Carregando histórico…" />
            ) : (historico.dados?.length ?? 0) === 0 ? (
              <Vazio titulo="Nenhuma sincronização ainda"
                descricao="Assim que uma plataforma for conectada e sincronizar, o histórico aparece aqui." />
            ) : (
              <TabelaHistorico execucoes={historico.dados!} onVerLogs={(id) => setExecLog(id)} />
            )}
          </BlocoRecolhivel>
        </Card>
      )}

      {/* Logs da execução — painel lateral */}
      <Drawer titulo={execLog ? `Logs da execução #${execLog}` : "Logs"}
        aberto={execLog !== null} aoFechar={() => setExecLog(null)}>
        {detalheExecLog && (
          <p className="mb-3 break-words rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 font-mono text-xs text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-300">
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
                l.nivel === "error" ? "text-rose-700 dark:text-rose-300"
                  : l.nivel === "warn" ? "text-ouro-700 dark:text-ouro-300"
                    : "text-zinc-600 dark:text-zinc-300"}>
                <span className="text-zinc-500 dark:text-zinc-400">{fmtData(l.created_at)}</span>{" "}
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

// --- Política de criação de aluno (quem é a fonte da matrícula) --------------
// Espelha app/services/politica_sync.py. "bloquear" = a plataforma não matricula:
// na sincronização e no relatório de plataforma enviado à mão, a linha que não
// casa com segurança vira pendência de identidade em vez de ficha nova. A Lista
// Piloto e o cadastro pela tela continuam criando. Trocar não mexe em nada já
// gravado nem recalcula: vale da próxima coleta em diante.
type ModoCriacao = "permitir" | "bloquear";
interface PoliticaSincronizacao { criar_aluno: string }

const MODO_CRIACAO: Record<ModoCriacao, {
  rotulo: string; tom: "neutro" | "destaque"; frase: string;
  pergunta: string; botao: string; confirmar: string; salvo: string; efeito: string[];
}> = {
  bloquear: {
    rotulo: "Bloqueada",
    tom: "destaque",
    frase: "A plataforma não matricula ninguém nesta escola: na sincronização e no relatório "
      + "de plataforma enviado à mão, o aluno que não for reconhecido com segurança vai para "
      + "Revisões de identidade, em vez de virar ficha nova. A matrícula vem da Lista Piloto.",
    pergunta: "Bloquear a criação de alunos pela plataforma?",
    botao: "Bloquear a criação pela plataforma",
    confirmar: "Confirmar: bloquear",
    salvo: "Política salva: a plataforma não cria mais alunos nesta escola.",
    efeito: [
      "Da próxima sincronização (ou relatório enviado à mão) em diante, a plataforma não "
        + "matricula ninguém: quem não for reconhecido com segurança vai para Revisões de "
        + "identidade, com o nome recebido, a turma do relatório e os candidatos.",
      "A Lista Piloto e o cadastro pela tela de Alunos continuam criando normalmente.",
      "Nada já gravado muda e nada é recalculado.",
    ],
  },
  permitir: {
    rotulo: "Permitida",
    tom: "neutro",
    frase: "A sincronização e o relatório de plataforma enviado à mão podem criar a ficha de "
      + "um aluno sem nenhuma ficha parecida (ativa, sem RA e sem nascimento). É o padrão da "
      + "escola que nunca configurou.",
    pergunta: "Permitir que a plataforma crie alunos?",
    botao: "Permitir a criação pela plataforma",
    confirmar: "Confirmar: permitir",
    salvo: "Política salva: a plataforma volta a poder criar alunos nesta escola.",
    // A regra do motor (identidade_aluno.decidir): só o aluno SEM nenhum candidato
    // vira ficha; havendo ficha parecida, o vínculo seguro (nome do meio omitido,
    // abreviação) é feito sozinho, e o não seguro (nome parecido, mais de um candidato,
    // nome de outra turma) vai para a Revisão — como diz o Suporte. A lista das
    // outras exceções não é fechada: conta de outra escola, a mesma conta em duas
    // linhas e turma que não dá para decidir também esperam na fila.
    efeito: [
      "Da próxima sincronização (ou relatório enviado à mão) em diante, o aluno sem nenhuma "
        + "ficha parecida vira ficha nova, ativa, sem RA e sem nascimento, e já conta no "
        + "ranking; quando há ficha parecida, a linha é vinculada a ela se o vínculo for "
        + "seguro (como o nome do meio omitido) e, se não for, vai para Revisões de "
        + "identidade. Também "
        + "não viram ficha o nome abreviado (como “ZEFA Q”), duas contas com o mesmo nome no "
        + "mesmo relatório e outros casos de dúvida, como a conta de um aluno de outra escola: "
        + "essas linhas esperam em Revisões de identidade. Ficha criada assim não se desfaz "
        + "sozinha.",
      "Só faz sentido se a matrícula desta escola não vem da Lista Piloto.",
      "Nada já gravado muda e nada é recalculado.",
    ],
  },
};

function PoliticaCriacaoAluno({ escolaId, global }: { escolaId: number; global: boolean }) {
  const url = `/escolas/${escolaId}/configuracoes/sincronizacao`;
  const politica = useApi<PoliticaSincronizacao>(url);
  const [alvo, setAlvo] = useState<ModoCriacao | null>(null);
  const [motivo, setMotivo] = useState("");
  const [salvo, setSalvo] = useState<ModoCriacao | null>(null);

  const salvar = useMutation(async (modo: ModoCriacao) => {
    await api(url, {
      method: "PUT",
      body: JSON.stringify({ criar_aluno: modo, motivo: motivo.trim() || null }),
    });
  }, {
    aoSucesso: (_r, modo) => {
      setSalvo(modo); setAlvo(null); setMotivo(""); politica.recarregar();
    },
  });

  // O backend já normaliza (valor ilegível = "permitir", o padrão).
  const modo: ModoCriacao | null = politica.dados
    ? (politica.dados.criar_aluno === "bloquear" ? "bloquear" : "permitir")
    : null;
  const outro: ModoCriacao | null = modo ? (modo === "bloquear" ? "permitir" : "bloquear") : null;
  const fechar = () => { setAlvo(null); setMotivo(""); salvar.limparErro(); };

  return (
    <Card className="p-6">
      <section aria-label="Criação de alunos pela sincronização">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="flex items-center gap-3 text-[17px] font-semibold tracking-tight text-zinc-900 dark:text-white">
            <IconePastel icone={ShieldCheck} tom="verde" />
            Criação de alunos pela sincronização
          </h2>
          {modo && <Badge tom={MODO_CRIACAO[modo].tom}>{MODO_CRIACAO[modo].rotulo}</Badge>}
        </div>
        {politica.carregando && !politica.dados && (
          <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">Carregando a política…</p>
        )}
        {politica.erro && !politica.dados && (
          <div className="mt-2">
            <Mensagem tipo="erro">
              Não foi possível ler a política desta escola: {politica.erro.message}
            </Mensagem>
          </div>
        )}
        {modo && (
          <p className="mt-3 text-sm text-zinc-600 dark:text-zinc-300">{MODO_CRIACAO[modo].frase}</p>
        )}
        {modo && outro && (global ? (
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <Botao variante="secundario" onClick={() => { setSalvo(null); setAlvo(outro); }}>
              {MODO_CRIACAO[outro].botao}
            </Botao>
            <span className="text-xs text-zinc-500 dark:text-zinc-400">
              Vale da próxima coleta em diante; nada já gravado muda.
            </span>
          </div>
        ) : (
          <p className="mt-2 text-xs text-zinc-500 dark:text-zinc-400">
            Só a Administração Global altera esta política.
          </p>
        ))}
        {salvo && (
          <div className="mt-3"><Mensagem tipo="ok">{MODO_CRIACAO[salvo].salvo}</Mensagem></div>
        )}
      </section>

      <Modal titulo={alvo ? MODO_CRIACAO[alvo].pergunta : ""} aberto={global && alvo !== null}
        aoFechar={fechar}>
        {alvo && (
          <div className="space-y-3 text-sm">
            <ul className="list-inside list-disc space-y-1 text-zinc-700 dark:text-zinc-200">
              {MODO_CRIACAO[alvo].efeito.map((t) => <li key={t}>{t}</li>)}
            </ul>
            <label className="block">
              <span className="mb-1 block font-medium text-zinc-700 dark:text-zinc-300">
                Motivo (opcional, fica no registro de auditoria)
              </span>
              <input className={estiloInput} value={motivo} maxLength={300}
                onChange={(e) => setMotivo(e.target.value)} />
            </label>
            {salvar.erro && <Mensagem tipo="erro">{salvar.erro.message}</Mensagem>}
            <div className="flex flex-wrap justify-end gap-2">
              <Botao variante="neutro" disabled={salvar.enviando} onClick={fechar}>Cancelar</Botao>
              <Botao disabled={salvar.enviando} onClick={() => { void salvar.executar(alvo); }}>
                {salvar.enviando ? "Salvando…" : MODO_CRIACAO[alvo].confirmar}
              </Botao>
            </div>
          </div>
        )}
      </Modal>
    </Card>
  );
}

// --- Lista de alertas (com Resolver) ------------------------------------------
function ListaAlertas({ alertas, onResolver, resolvendo, erro }: {
  alertas: Alerta[]; onResolver: (id: number) => void; resolvendo: boolean; erro: string | null;
}) {
  return (
    <>
      <ul className="mt-3 space-y-2">
        {alertas.map((a) => (
          <li key={a.id} className="flex flex-wrap items-center gap-3 rounded-2xl border border-zinc-200/80 bg-white px-3.5 py-3 dark:border-zinc-800 dark:bg-zinc-900">
            <IconePastel icone={AlertTriangle} tom={a.severidade === "critico" ? "rosa" : "ambar"} tamanho="sm" />
            <span className="min-w-0 flex-1 text-sm text-zinc-700 dark:text-zinc-200">
              <span className={a.severidade === "critico"
                ? "font-semibold text-rose-700 dark:text-rose-300"
                : "font-semibold text-ouro-700 dark:text-ouro-300"}>
                {rotuloAlerta(a.tipo)}
              </span>
              {" — "}{a.mensagem}
              <span className="ml-1 text-xs text-zinc-500 dark:text-zinc-400">({fmtData(a.created_at)})</span>
            </span>
            <Botao variante="secundario" tamanho="sm" disabled={resolvendo} onClick={() => onResolver(a.id)}>Resolver</Botao>
          </li>
        ))}
      </ul>
      {erro && <div className="mt-2"><Mensagem tipo="erro">{erro}</Mensagem></div>}
    </>
  );
}

// --- Histórico das execuções ------------------------------------------------
// Com as contagens novas (qtd_linhas presente), cada número diz uma coisa:
// alunos DISTINTOS atualizados, linhas recebidas, em revisão e falhas. Uma
// execução antiga (sem qtd_linhas) não ganha número inventado: o contador dela
// é marcado com * e explicado (registros por arquivo).
function TabelaHistorico({ execucoes, onVerLogs }: {
  execucoes: Execucao[]; onVerLogs: (id: number) => void;
}) {
  const contagemNova = execucoes.some(temContagemPorAluno);
  const temAntiga = contagemNova && execucoes.some((e) => !temContagemPorAluno(e));
  const num = (v: number | null | undefined) => (typeof v === "number" ? String(v) : "—");
  return (
    <>
      {contagemNova ? (
        <p className="mb-3 text-xs text-zinc-500 dark:text-zinc-400">
          “Alunos atualizados” conta cada aluno uma vez, só quando um dado novo ou
          alterado foi gravado. “Linhas recebidas” é o que a plataforma entregou;
          “Em revisão”, as linhas que aguardam a escolha do aluno certo; “Falhas”,
          as turmas, lotes ou alunos que não puderam ser coletados.
          {temAntiga && (
            <> Execuções marcadas com * são anteriores a essa contagem: o número é de
              registros processados (um aluno pode contar duas vezes).</>
          )}
        </p>
      ) : (
        <p className="mb-3 text-xs text-zinc-500 dark:text-zinc-400">
          “Registros” são as linhas processadas em cada execução (um aluno pode
          contar duas vezes: resumo e leituras). “Linhas c/ erro” são as linhas
          que não puderam ser vinculadas a um aluno.
        </p>
      )}
      <div className={`${classesTabela.moldura} -mx-6`}>
        <table className={classesTabela.tabela}>
          <thead>
            <tr>
              <th className={classesTabela.th}>Quando</th>
              <th className={classesTabela.th}>Plataforma</th>
              <th className={`hidden sm:table-cell ${classesTabela.th}`}>Origem</th>
              <th className={classesTabela.th}>Status</th>
              {contagemNova ? (<>
                <th className={`${classesTabela.th} text-right`}>Alunos atualizados</th>
                <th className={`hidden md:table-cell ${classesTabela.th} text-right`}>Linhas recebidas</th>
                <th className={`hidden md:table-cell ${classesTabela.th} text-right`}>Em revisão</th>
                <th className={`hidden sm:table-cell ${classesTabela.th} text-right`}>Falhas</th>
              </>) : (<>
                <th className={`${classesTabela.th} text-right`}>Registros</th>
                <th className={`hidden md:table-cell ${classesTabela.th} text-right`}>Linhas c/ erro</th>
              </>)}
              <th className={`hidden sm:table-cell ${classesTabela.th} text-right`}>Duração</th>
              <th className={classesTabela.th}>Logs</th>
            </tr>
          </thead>
          <tbody>
            {execucoes.map((e) => {
              const nova = temContagemPorAluno(e);
              const periodo = textoPeriodo(e);
              return (
                <tr key={e.id} className={classesTabela.tr}>
                  <td className={`${classesTabela.td} whitespace-nowrap`}>{fmtData(e.iniciada_em ?? e.created_at ?? null)}</td>
                  <td className={`${classesTabela.td} whitespace-nowrap`}>
                    <span className="inline-flex items-center gap-2">
                      <span aria-hidden className={`h-2 w-2 rounded-full ${identidadeDe(e.plataforma)?.ponto ?? "bg-zinc-400"}`} />
                      {NOME[e.plataforma] ?? e.plataforma}
                    </span>
                  </td>
                  <td className={`hidden sm:table-cell ${classesTabela.td} text-zinc-500 dark:text-zinc-400`}>
                    {e.origem === "scheduler" ? "Automático" : "Manual"}
                  </td>
                  <td className={classesTabela.td}>
                    <div className="flex flex-wrap items-center gap-1">
                      <ExecucaoBadge execucao={e} />
                      {e.recalculo_pendente && (
                        <Badge tom="erro">recálculo pendente</Badge>
                      )}
                    </div>
                    {periodo && (
                      <div className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">{periodo}</div>
                    )}
                  </td>
                  {contagemNova ? (<>
                    <td className={`${classesTabela.td} text-right tabular-nums`}>
                      {nova ? e.qtd_alunos : `${e.qtd_alunos}*`}
                    </td>
                    <td className={`hidden md:table-cell ${classesTabela.td} text-right tabular-nums`}>{num(e.qtd_linhas)}</td>
                    <td className={`hidden md:table-cell ${classesTabela.td} text-right tabular-nums`}>{num(e.qtd_em_revisao)}</td>
                    <td className={`hidden sm:table-cell ${classesTabela.td} text-right tabular-nums`}>{num(e.qtd_falhas)}</td>
                  </>) : (<>
                    <td className={`${classesTabela.td} text-right tabular-nums`}>{e.qtd_alunos}</td>
                    <td className={`hidden md:table-cell ${classesTabela.td} text-right tabular-nums`}>{e.qtd_erros}</td>
                  </>)}
                  <td className={`hidden sm:table-cell ${classesTabela.td} text-right tabular-nums`}>{fmtDur(e.duracao_ms)}</td>
                  <td className={classesTabela.td}>
                    <button type="button" className="rounded-lg px-1.5 py-0.5 font-semibold text-indigo-700 hover:bg-indigo-50 hover:underline dark:text-indigo-300 dark:hover:bg-indigo-500/10"
                      aria-label={`Ver os logs da execução #${e.id}`}
                      onClick={() => onVerLogs(e.id)}>ver</button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );
}

// --- O que a ÚLTIMA COLETA fez (contrato da etapa 2) ------------------------
// Só aparece quando a execução traz as contagens novas. Nunca soma nem estima.
function ResumoUltimaColeta({ e }: { e: Execucao }) {
  const itens: { texto: string; destaque?: "erro" | "alerta" }[] = [
    { texto: `${e.qtd_alunos} aluno${e.qtd_alunos === 1 ? "" : "s"} atualizado${e.qtd_alunos === 1 ? "" : "s"}` },
  ];
  if (typeof e.qtd_linhas === "number") {
    itens.push({ texto: `${e.qtd_linhas} linha${e.qtd_linhas === 1 ? "" : "s"} recebida${e.qtd_linhas === 1 ? "" : "s"}` });
  }
  if (typeof e.qtd_em_revisao === "number") {
    itens.push({ texto: `${e.qtd_em_revisao} em revisão`, destaque: e.qtd_em_revisao > 0 ? "alerta" : undefined });
  }
  if (typeof e.qtd_falhas === "number") {
    itens.push({
      texto: `${e.qtd_falhas} falha${e.qtd_falhas === 1 ? "" : "s"}`,
      destaque: e.qtd_falhas > 0 ? "erro" : undefined,
    });
  }
  const periodo = textoPeriodo(e);
  return (
    <div className="mt-4 rounded-2xl border border-zinc-200/80 px-4 py-3 text-sm dark:border-zinc-800">
      <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-zinc-500 dark:text-zinc-400">
        Na última coleta{periodo ? ` (${periodo})` : ""}
      </p>
      <ul className="mt-2 flex flex-wrap gap-2" aria-label="Resumo da última coleta">
        {itens.map((i) => (
          <li key={i.texto} className={`rounded-full px-3 py-1 text-xs font-semibold ${
            i.destaque === "erro" ? "bg-rose-50 text-rose-700 dark:bg-rose-500/15 dark:text-rose-300"
              : i.destaque === "alerta" ? "bg-ouro-50 text-ouro-700 dark:bg-ouro-400/15 dark:text-ouro-300"
                : "bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-200"}`}>
            {i.texto}
          </li>
        ))}
      </ul>
      {(e.qtd_em_revisao ?? 0) > 0 && (
        <Link to="/revisoes-identidade" className="mt-2 inline-block text-xs font-semibold text-indigo-700 underline dark:text-indigo-300">
          Escolher o aluno certo em Revisões de identidade
        </Link>
      )}
    </div>
  );
}

// --- "Dados recebidos" de uma plataforma ------------------------------------
// Só mostra o que o backend informou: cobertura por aluno quando existir;
// senão, os contadores da última execução (registros processados / linhas
// não vinculadas). Nunca inventa número. ``null`` na cobertura = o backend não
// conseguiu contar → cai nos contadores / "Nenhum dado recebido ainda".
// 0 com e 0 sem = não há aluno ativo no ano letivo (nunca "0 de 0").
function DadosRecebidos({ p }: { p: PlataformaStatus }) {
  // A última tentativa que TERMINOU (uma execução na fila não tem contagem).
  const exec = ultimaTentativa(p) ?? p.ultima_execucao;
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
        <dd className="mt-1 text-[15px] font-semibold text-zinc-900 dark:text-white">
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
  if (exec && temContagemPorAluno(exec)) {
    // Contagem nova: alunos DISTINTOS com dado aplicado (o resumo da coleta,
    // abaixo do card, traz linhas, revisão e falhas).
    return (
      <dd className="mt-0.5">
        {`alunos atualizados na última sincronização: ${exec.qtd_alunos}`}
      </dd>
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
  onMudou, onSincronizar, onSincronizarPeriodo, sincronizando, onVerLogs, agendadorAtivo,
  erroSincronizar = null,
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
  agendadorAtivo?: boolean;
  /** Erro do último "Sincronizar" clicado NESTE card (aparece perto do botão). */
  erroSincronizar?: string | null;
}) {
  const nome = NOME[p.plataforma] ?? p.plataforma;
  const identidade = identidadeDe(p.plataforma);
  const [pInicio, setPInicio] = useState("");
  const [pFim, setPFim] = useState("");
  const sit = situacaoIntegracao(p, nome, alertas, agendadorAtivo);
  // A última TENTATIVA que terminou (o backend novo informa; no antigo, a última
  // execução quando já terminou) — diferente do último DADO APLICADO.
  const tentativa = ultimaTentativa(p);
  const agenda = descreverAgenda(p);
  const pausada = p.agendada && agendadorAtivo === false;
  const idadeSucesso = idadeHumana(p.idade_horas);
  const recalculo = recalculoPendente(p);
  const manualEmDestaque = !p.conectada
    || ["falhou", "indisponivel", "nova_tentativa", "desatualizada", "sem_dados_coleta", "parcial"]
      .includes(sit.chave);
  // Coleta do Matific de UM dia (início = fim): só quando o servidor confirmou
  // a semântica do fim de período (MATIFIC_END_DATE). Sem o campo, não aceita.
  const umDiaPermitido = p.periodo_um_dia_permitido === true;
  const umDia = Boolean(pInicio && pFim && pInicio === pFim);

  return (
    <Card className="p-6">
      {/* Cabeçalho: ícone da plataforma na cor dela (Elefante violeta, Matific
          verde-azulado), o nome (h2 — os testes procuram o card por ele) e a pílula
          da situação. */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 items-center gap-3.5">
          <IconePlataforma plataforma={p.plataforma} tamanho="lg" />
          <div className="min-w-0">
            <h2 className="text-lg font-bold tracking-tight text-zinc-900 dark:text-white">{nome}</h2>
            {identidade && <p className="text-xs text-zinc-500 dark:text-zinc-400">{identidade.area}</p>}
          </div>
        </div>
        <StatusIntegracaoBadge situacao={sit} />
      </div>
      <p className="mt-4 text-sm text-zinc-700 dark:text-zinc-300">{sit.frase}</p>
      {sit.link && (
        <Link to={sit.link.para} className="mt-1 inline-block text-sm font-semibold text-indigo-700 underline underline-offset-2 dark:text-indigo-300">
          {sit.link.texto}
        </Link>
      )}
      {/* Recálculo pendente: bem visível, no topo do card. */}
      {recalculo && (
        <div role="alert" className="mt-4 flex items-start gap-2.5 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-200">
          <AlertTriangle size={16} aria-hidden className="mt-0.5 shrink-0 text-rose-500" />
          <span>
            <strong>Recálculo pendente.</strong> Os dados desta coleta foram gravados, mas as
            notas e os rankings ainda não foram recalculados.
          </span>
        </div>
      )}
      {/* Texto cru do erro: recolhido e pequeno — útil para o suporte, fora do badge. */}
      {sit.detalheTecnico && (
        <details className="mt-2 text-xs text-zinc-500 dark:text-zinc-400">
          <summary className="cursor-pointer select-none hover:text-zinc-700 dark:hover:text-zinc-200">
            Ver detalhe técnico
          </summary>
          <p className="mt-1 break-words rounded-xl bg-zinc-50 px-3 py-2 font-mono dark:bg-zinc-800/50">Detalhe técnico: {sit.detalheTecnico}</p>
        </details>
      )}

      {/* Três blocos lado a lado: último dado, próxima coleta, dados recebidos. */}
      <dl className="mt-5 grid grid-cols-1 gap-3 text-sm md:grid-cols-3">
        <div className="rounded-2xl bg-zinc-50 p-4 dark:bg-zinc-800/50">
          <dt className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.08em] text-zinc-500 dark:text-zinc-400">
            <History size={13} aria-hidden className="shrink-0" />
            Último dado aplicado
          </dt>
          <dd className="mt-1 text-[15px] font-semibold text-zinc-900 dark:text-white">
            {p.ultimo_sucesso_em ? fmtData(p.ultimo_sucesso_em) : "nenhum ainda"}
          </dd>
          {idadeSucesso && (
            <dd className="text-xs text-zinc-500 dark:text-zinc-400">{idadeSucesso}</dd>
          )}
          {/* Verificação ≠ dado aplicado: "nada mudou" e "sem dados" verificam
              sem aplicar nada. Só aparece quando o backend informa. */}
          {p.ultima_verificacao_em !== undefined && (
            <dd className="text-xs text-zinc-500 dark:text-zinc-400">
              última verificação: {p.ultima_verificacao_em ? fmtData(p.ultima_verificacao_em) : "nenhuma"}
            </dd>
          )}
          <dd className="text-xs text-zinc-500 dark:text-zinc-400">
            última tentativa: {tentativa
              ? `${fmtData(tentativa.finalizada_em ?? tentativa.iniciada_em)} (${descreverExecucao(tentativa).rotulo})`
              : "nenhuma"}
          </dd>
        </div>
        <div className="rounded-2xl bg-zinc-50 p-4 dark:bg-zinc-800/50">
          <dt className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.08em] text-zinc-500 dark:text-zinc-400">
            <CalendarClock size={13} aria-hidden className="shrink-0" />
            Próxima
          </dt>
          <dd className="mt-1 text-[15px] font-semibold text-zinc-900 dark:text-white">
            {!p.agendada ? "manual" : pausada ? "pausada no servidor" : fmtData(p.proxima_execucao)}
          </dd>
          <dd className="text-xs text-zinc-500 dark:text-zinc-400">
            {pausada
              ? "a atualização automática está desligada no servidor: sincronize manualmente"
              : (agenda ?? "só quando você pedir")}
          </dd>
        </div>
        <div className="rounded-2xl bg-zinc-50 p-4 dark:bg-zinc-800/50">
          <dt className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.08em] text-zinc-500 dark:text-zinc-400">
            <Users size={13} aria-hidden className="shrink-0" />
            Dados recebidos
          </dt>
          <DadosRecebidos p={p} />
        </div>
      </dl>

      {tentativa && temContagemPorAluno(tentativa) && <ResumoUltimaColeta e={tentativa} />}

      {/* Erros: alertas abertos DESTA plataforma */}
      {alertas.length > 0 && (
        <div id={`alertas-${p.plataforma}`} className="mt-5 scroll-mt-4">
          <h3 className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.08em] text-rose-700 dark:text-rose-300">
            <AlertTriangle size={13} aria-hidden /> Erros ({alertas.length})
          </h3>
          <ListaAlertas alertas={alertas} onResolver={onResolver} resolvendo={resolvendo} erro={erroResolver} />
        </div>
      )}

      {/* Ações */}
      <div className="mt-5 flex flex-wrap items-center gap-2.5 border-t border-zinc-100 pt-5 dark:border-zinc-800">
        <Botao disabled={!p.conectada || sincronizando} onClick={onSincronizar}>
          <RefreshCw size={15} aria-hidden /> Sincronizar {nome}
        </Botao>
        {["falhou", "indisponivel", "nova_tentativa"].includes(sit.chave) && tentativa && (
          <Botao variante="secundario" onClick={() => onVerLogs(tentativa.id)}>
            Ver o registro da falha
          </Botao>
        )}
        {sit.chave === "parcial" && tentativa && (
          <Botao variante="secundario" onClick={() => onVerLogs(tentativa.id)}>
            Ver o registro da coleta
          </Botao>
        )}
        {p.plataforma === "elefante" && gestor && (
          <Link
            to="/diagnostico-elefante"
            className={`inline-flex items-center justify-center font-semibold transition-colors ${TAMANHOS_BOTAO.md} ${ESTILOS_BOTAO.secundario}`}
          >
            <Radar size={15} aria-hidden /> Ver diagnóstico
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
            ? "ml-auto inline-flex items-center gap-1.5 rounded-full border border-ouro-200 bg-ouro-50 px-3.5 py-1.5 text-xs font-semibold text-marinho-800 hover:bg-ouro-100 dark:border-ouro-400/30 dark:bg-ouro-400/10 dark:text-ouro-300"
            : "ml-auto inline-flex items-center gap-1.5 text-xs text-zinc-500 underline-offset-2 hover:text-indigo-700 hover:underline dark:text-zinc-400 dark:hover:text-indigo-300"}
        >
          <FileUp size={13} aria-hidden /> Enviar relatório manualmente (avançado)
        </Link>
      </div>
      {erroSincronizar && <div className="mt-3"><Mensagem tipo="erro">{erroSincronizar}</Mensagem></div>}

      {/* Configurar conexão: aberta por padrão enquanto não houver credencial válida */}
      <BlocoRecolhivel
        titulo="Configurar conexão"
        icone={<IconePastel icone={Plug} tom={identidade?.tom ?? "neutro"} tamanho="sm" />}
        inicialAberto={p.credencial_status !== "valida"}
        descricao={`Acesso ao ${nome} e horário da atualização automática.`}
      >
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <div>
            <h3 className="mb-3 text-[11px] font-semibold uppercase tracking-[0.08em] text-zinc-500 dark:text-zinc-400">
              Acesso à plataforma
            </h3>
            <CredenciaisForm base={base} plataforma={p.plataforma} nome={nome}
              status={p.credencial_status} aoMudar={onMudou} />
            <p className="mt-2 text-xs text-zinc-500 dark:text-zinc-400">
              Validada em: {fmtData(p.validada_em)}
            </p>
          </div>
          <div>
            <h3 className="mb-3 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.08em] text-zinc-500 dark:text-zinc-400">
              <CalendarClock size={13} aria-hidden /> Atualização automática
            </h3>
            <AgendaForm base={base} p={p} aoMudar={onMudou} agendadorAtivo={agendadorAtivo} />
          </div>
        </div>
      </BlocoRecolhivel>

      {/* Coleta POR PERÍODO — só Matific (o Elefante já tem leituras datadas). */}
      {p.plataforma === "matific" && p.conectada && (
        <BlocoRecolhivel
          titulo="Avançado: coletar um período específico"
          icone={<IconePastel icone={CalendarClock} tom="teal" tamanho="sm" />}
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
            <Botao variante="secundario"
                   disabled={sincronizando || !pInicio || !pFim || pFim < pInicio
                     || (umDia && !umDiaPermitido)}
                   onClick={() => onSincronizarPeriodo(pInicio, pFim)}>
              <CalendarClock size={15} aria-hidden /> Coletar do Matific este período
            </Botao>
          </div>
          {!umDiaPermitido && (
            <p className={umDia
              ? "mt-2 text-xs font-medium text-ouro-700 dark:text-ouro-300"
              : "mt-2 text-xs text-zinc-500 dark:text-zinc-400"}>
              {umDia ? "Período de um dia só não é aceito: " : "O período precisa ter pelo menos 2 dias: "}
              a semântica do fim de período do Matific ainda não foi confirmada (não se
              sabe se o dia final entra na coleta). Escolha pelo menos 2 dias.
            </p>
          )}
        </BlocoRecolhivel>
      )}
    </Card>
  );
}

// --- Sub-form: agendamento --------------------------------------------------
function AgendaForm({ base, p, aoMudar, agendadorAtivo }: {
  base: string; p: PlataformaStatus; aoMudar: () => void; agendadorAtivo?: boolean;
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

      <div className="flex flex-wrap items-center gap-2">
        <Botao variante="secundario" disabled={salvar.enviando} onClick={() => salvar.executar()}>
          {salvar.enviando ? "Salvando…" : "Salvar agendamento"}
        </Botao>
        {p.agendada && agendadorAtivo === false && (
          <span className="text-xs text-ouro-700 dark:text-ouro-300">
            Salvo, mas pausado: o agendador está desligado no servidor
          </span>
        )}
        {p.agendada && agendadorAtivo !== false && (
          <span className="text-xs font-medium text-emerald-700 dark:text-emerald-400">
            Ativo · próxima {fmtData(p.proxima_execucao)}
          </span>
        )}
      </div>
      {salvar.erro && <Mensagem tipo="erro">{salvar.erro.message}</Mensagem>}
      <p className="text-xs text-zinc-500 dark:text-zinc-400">
        A automática roda no horário definido (horário de Brasília) e só quando houver
        credencial válida. Requer o agendador ligado no servidor.
      </p>
    </div>
  );
}
