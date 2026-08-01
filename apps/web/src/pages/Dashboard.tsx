import {
  AlertTriangle,
  ArrowRight,
  BookOpen,
  Calculator,
  CheckCircle2,
  Clock3,
  GraduationCap,
  Lightbulb,
  Rocket,
  School,
  Star,
  TrendingUp,
  Trophy,
  Users,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { lazy, Suspense, type ReactNode } from "react";
import { Link } from "react-router-dom";

import { Botao, Card, Carregando, Vazio } from "../components/ui";
import { useApp } from "../context/AppContext";
import { useApi } from "../hooks/useApi";
import { usePerfil } from "../hooks/usePerfil";
import { nota, numero, tempoLeitura } from "../lib/formato";
import type { Dashboard as DadosDashboard } from "../lib/types";

// Panorama da REDE (SEDUC) e o GLOBAL de todas as redes (Admin Global). Lazy:
// puxam o Leaflet do mapa — mantém o chunk do Dashboard leve para o professor/
// coordenador (que nunca os veem).
const PanoramaRede = lazy(() =>
  import("./rede/RedeDashboard").then((m) => ({ default: m.PanoramaRede })));
const PanoramaEscolaDaRede = lazy(() =>
  import("./rede/RedeDashboard").then((m) => ({ default: m.PanoramaEscolaDaRede })));
const PanoramaGlobal = lazy(() =>
  import("./rede/RedeDashboard").then((m) => ({ default: m.PanoramaGlobal })));

/* --- Inteligência (mesmos dados da aba Insights, reaproveitados) ----------- */
interface IndiceAluno {
  aluno_id: number;
  nome: string;
  turma: string;
  engajamento: number;
  evolucao: number;
  persistencia: number;
}
interface Alerta {
  tipo: string;
  gravidade: "alta" | "media" | "baixa";
  aluno_id: number;
  nome: string;
  turma: string;
  texto: string;
}
interface Insights {
  indices: IndiceAluno[];
  alertas: Alerta[];
}

function saudacao(): string {
  const h = new Date().getHours();
  if (h < 12) return "Bom dia";
  if (h < 18) return "Boa tarde";
  return "Boa noite";
}

/* -------------------------------------------------------------------------- */
/* Blocos de UI                                                               */
/* -------------------------------------------------------------------------- */

function TituloSecao({ children }: { children: ReactNode }) {
  return (
    <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-zinc-500 dark:text-zinc-400">
      {children}
    </h2>
  );
}

/** Bloco pulsante para carregamento (combina com o tema escuro). */
function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`animate-pulse rounded-xl bg-zinc-200/70 dark:bg-zinc-800/70 ${className}`} />;
}

/** Card de indicador secundário (engajamento) — visual mais discreto. */
function Indicador({ icone: Icone, rotulo, valor, detalhe }: {
  icone: LucideIcon; rotulo: string; valor: string; detalhe?: string;
}) {
  return (
    <Card className="p-4">
      <div className="flex items-center gap-2 text-zinc-500 dark:text-zinc-400">
        <Icone size={15} />
        <span className="text-xs font-medium uppercase tracking-wide">{rotulo}</span>
      </div>
      <p className="mt-2 text-2xl font-semibold tabular-nums tracking-tight">{valor}</p>
      {detalhe && <p className="mt-0.5 text-xs text-zinc-400 dark:text-zinc-500">{detalhe}</p>}
    </Card>
  );
}

/** Barra 0–100 (reaproveita a leitura da aba Insights). */
function Barra({ valor }: { valor: number }) {
  const cor = valor >= 66 ? "bg-emerald-500" : valor >= 33 ? "bg-amber-500" : "bg-red-400";
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-zinc-200 dark:bg-zinc-800">
      <div className={`h-full rounded-full ${cor}`} style={{ width: `${Math.max(4, Math.min(100, valor))}%` }} />
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Seções                                                                     */
/* -------------------------------------------------------------------------- */

/** Cabeçalho: saudação contextual + seletor de escola compacto (só aparece se
 *  houver mais de uma escola — a troca principal já vive no topo do sistema). */
function Cabecalho({ nome, subtitulo, escolas, escolaId, selecionar }: {
  nome: string; subtitulo: string;
  escolas: { id: number; nome: string }[];
  escolaId: number | null;
  selecionar: (id: number) => void;
}) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">
          {saudacao()}, {nome} <span aria-hidden>👋</span>
        </h1>
        <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">{subtitulo}</p>
      </div>
      {escolas.length > 1 && (
        <label className="flex items-center gap-2 text-sm">
          <School size={15} className="text-zinc-400" />
          <select
            aria-label="Escola selecionada"
            className="max-w-[220px] rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm font-medium dark:border-zinc-700 dark:bg-zinc-900"
            value={escolaId ?? ""}
            onChange={(e) => selecionar(Number(e.target.value))}
          >
            {escolas.map((escola) => (
              <option key={escola.id} value={escola.id}>{escola.nome}</option>
            ))}
          </select>
        </label>
      )}
    </div>
  );
}

/** Indicadores com hierarquia: Média Geral em destaque + alunos/turmas/prof;
 *  depois a linha de engajamento (leitura/Matific). */
function Indicadores({ dados }: { dados: DadosDashboard }) {
  return (
    <section>
      <TituloSecao>Indicadores principais</TituloSecao>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {/* Média geral — o indicador-âncora, com destaque e barra 0–100. */}
        <Card className="relative overflow-hidden p-5 ring-1 ring-indigo-500/20 sm:col-span-2 lg:col-span-1 lg:row-span-1">
          <div className="flex items-center gap-2 text-indigo-600 dark:text-indigo-300">
            <Star size={16} />
            <span className="text-xs font-semibold uppercase tracking-wide">Média geral</span>
          </div>
          <p className="mt-2 text-4xl font-bold tabular-nums tracking-tight text-indigo-700 dark:text-indigo-200">
            {nota(dados.media_geral)}
          </p>
          <p className="mb-3 mt-0.5 text-xs text-zinc-400 dark:text-zinc-500">escala 0–100</p>
          <Barra valor={dados.media_geral} />
        </Card>
        <Indicador icone={GraduationCap} rotulo="Alunos" valor={numero(dados.total_alunos)} />
        <Indicador icone={Users} rotulo="Turmas" valor={numero(dados.total_turmas)} />
        <Indicador icone={School} rotulo="Professores" valor={numero(dados.total_professores)} />
      </div>

      <h3 className="mb-3 mt-6 text-xs font-semibold uppercase tracking-wider text-zinc-500 dark:text-zinc-400">
        Engajamento
      </h3>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-3">
        <Indicador icone={BookOpen} rotulo="Livros lidos" valor={numero(dados.total_livros)} detalhe="títulos únicos" />
        <Indicador icone={Clock3} rotulo="Tempo de leitura" valor={tempoLeitura(dados.tempo_leitura_min)} />
        <Indicador icone={Calculator} rotulo="Atividades Matific" valor={numero(dados.total_atividades)} />
      </div>
    </section>
  );
}

/** Inteligência: destaques (maior engajamento) + situações de atenção
 *  (alertas). Tudo derivado dos MESMOS dados reais da aba Insights. */
function Inteligencia({ intel, carregando }: { intel: Insights | null; carregando: boolean }) {
  const destaques = (intel?.indices ?? [])
    .filter((i) => i.engajamento > 0)
    .slice(0, 4);
  const alertas = (intel?.alertas ?? []).slice(0, 4);

  return (
    <section className="grid gap-4 lg:grid-cols-2">
      {/* Destaques */}
      <Card className="flex flex-col p-5">
        <div className="mb-4 flex items-center justify-between">
          <span className="inline-flex items-center gap-2 text-sm font-semibold">
            <Lightbulb size={16} className="text-amber-500" /> Destaques da escola
          </span>
          <Link to="/insights" className="text-xs font-medium text-indigo-600 hover:underline dark:text-indigo-400">
            Ver insights
          </Link>
        </div>
        {carregando ? (
          <div className="space-y-3">
            {[0, 1, 2].map((i) => <Skeleton key={i} className="h-9" />)}
          </div>
        ) : destaques.length === 0 ? (
          <p className="flex-1 text-sm text-zinc-400 dark:text-zinc-500">
            Ainda não há dados suficientes para gerar destaques.
          </p>
        ) : (
          <ul className="space-y-3">
            {destaques.map((a) => (
              <li key={a.aluno_id} className="flex items-center gap-3">
                <TrendingUp size={15} className="shrink-0 text-emerald-500" />
                <div className="min-w-0 flex-1">
                  <div className="flex items-baseline justify-between gap-2">
                    <Link to={`/alunos/${a.aluno_id}`} className="truncate text-sm font-medium hover:text-indigo-600 dark:hover:text-indigo-400">
                      {a.nome}
                    </Link>
                    <span className="shrink-0 text-xs text-zinc-400">{a.turma}</span>
                  </div>
                  <div className="mt-1"><Barra valor={a.engajamento} /></div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>

      {/* Precisa de atenção */}
      <Card className="flex flex-col p-5">
        <span className="mb-4 inline-flex items-center gap-2 text-sm font-semibold">
          <AlertTriangle size={16} className="text-amber-500" /> Precisa de atenção
        </span>
        {carregando ? (
          <div className="space-y-3">
            {[0, 1, 2].map((i) => <Skeleton key={i} className="h-9" />)}
          </div>
        ) : alertas.length === 0 ? (
          <p className="flex flex-1 items-center gap-2 text-sm text-emerald-600 dark:text-emerald-400">
            <CheckCircle2 size={16} /> Nenhuma situação crítica identificada no momento.
          </p>
        ) : (
          <ul className="space-y-2.5">
            {alertas.map((a, i) => (
              <li key={`${a.aluno_id}-${i}`} className="flex items-start gap-2.5 text-sm">
                <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${
                  a.gravidade === "alta" ? "bg-red-500" : a.gravidade === "media" ? "bg-amber-500" : "bg-zinc-400"
                }`} />
                <span className="text-zinc-600 dark:text-zinc-300">{a.texto}</span>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </section>
  );
}

/** Leitura (Elefante) e Matemática (Matific) — os dois pilares da plataforma. */
function LeituraMatematica({ dados }: { dados: DadosDashboard }) {
  return (
    <section>
      <TituloSecao>Desempenho por plataforma</TituloSecao>
      <div className="grid gap-4 sm:grid-cols-2">
        <Card className="p-5">
          <div className="flex items-center justify-between">
            <span className="inline-flex items-center gap-2 text-sm font-semibold">
              <BookOpen size={16} className="text-emerald-500" /> Leitura
            </span>
            <Link to="/elefante" className="inline-flex items-center gap-1 text-xs font-medium text-indigo-600 hover:underline dark:text-indigo-400">
              Elefante Letrado <ArrowRight size={13} />
            </Link>
          </div>
          <div className="mt-4 grid grid-cols-2 gap-4">
            <div>
              <p className="text-2xl font-semibold tabular-nums">{numero(dados.total_livros)}</p>
              <p className="text-xs text-zinc-400 dark:text-zinc-500">livros lidos</p>
            </div>
            <div>
              <p className="text-2xl font-semibold tabular-nums">{tempoLeitura(dados.tempo_leitura_min)}</p>
              <p className="text-xs text-zinc-400 dark:text-zinc-500">tempo de leitura</p>
            </div>
          </div>
        </Card>

        <Card className="p-5">
          <div className="flex items-center justify-between">
            <span className="inline-flex items-center gap-2 text-sm font-semibold">
              <Calculator size={16} className="text-sky-500" /> Matemática
            </span>
            <Link to="/matific" className="inline-flex items-center gap-1 text-xs font-medium text-indigo-600 hover:underline dark:text-indigo-400">
              Matific <ArrowRight size={13} />
            </Link>
          </div>
          <div className="mt-4 grid grid-cols-2 gap-4">
            <div>
              <p className="text-2xl font-semibold tabular-nums">{numero(dados.total_atividades)}</p>
              <p className="text-xs text-zinc-400 dark:text-zinc-500">atividades concluídas</p>
            </div>
            <div>
              <p className="text-2xl font-semibold tabular-nums">{nota(dados.media_geral)}</p>
              <p className="text-xs text-zinc-400 dark:text-zinc-500">média geral da escola</p>
            </div>
          </div>
        </Card>
      </div>
    </section>
  );
}

/** Top 5 do ranking geral (compacto) — o completo fica na página de ranking. */
function TopRanking({ top }: { top: DadosDashboard["top10"] }) {
  const top5 = top.slice(0, 5);
  return (
    <section>
      <Card>
        <div className="flex items-center justify-between border-b border-zinc-200 px-4 py-3 dark:border-zinc-800">
          <h2 className="inline-flex items-center gap-2 text-sm font-semibold">
            <Trophy size={16} className="text-amber-500" /> Top 5 — Ranking Geral
          </h2>
          <Link to="/ranking" className="inline-flex items-center gap-1 text-sm font-medium text-indigo-600 hover:underline dark:text-indigo-400">
            Ver ranking completo <ArrowRight size={14} />
          </Link>
        </div>
        {top5.length === 0 ? (
          <Vazio
            titulo="Ainda não há notas calculadas"
            descricao="Importe dados das plataformas ou cadastre alunos para começar."
          />
        ) : (
          <ul className="divide-y divide-zinc-100 dark:divide-zinc-800/60">
            {top5.map((item) => (
              <li key={item.aluno_id} className="flex items-center gap-3 px-4 py-3">
                <span className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-bold tabular-nums ${
                  item.posicao <= 3
                    ? "bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300"
                    : "bg-zinc-100 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400"
                }`}>
                  {item.posicao}º
                </span>
                <Link to={`/alunos/${item.aluno_id}`} className="min-w-0 flex-1 truncate text-sm font-medium hover:text-indigo-600 dark:hover:text-indigo-400">
                  {item.nome}
                </Link>
                <span className="hidden shrink-0 text-xs text-zinc-400 sm:inline">{item.turma}</span>
                <span className="shrink-0 text-sm font-semibold tabular-nums">{nota(item.nota_geral)}</span>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </section>
  );
}

/* -------------------------------------------------------------------------- */
/* Página                                                                     */
/* -------------------------------------------------------------------------- */

/**
 * Dashboard = aba ÚNICA para todos os perfis; o CONTEÚDO muda pelo perfil:
 *   - SEDUC/Secretaria e Admin Global → panorama consolidado da REDE inteira;
 *   - professor/coordenador/admin de escola → Dashboard da ESCOLA (abaixo,
 *     INALTERADO). A aba Secretaria (/rede) fica só com o administrativo.
 */
export default function Dashboard() {
  const { global, secretaria } = usePerfil();
  const { escolaId } = useApp();
  // Admin Global → consolidação de TODAS as redes; SEDUC/Secretaria → sua rede;
  // professor/coordenador/admin de escola → Dashboard da escola (abaixo, inalterado).
  if (global) {
    return (
      <Suspense fallback={<Carregando texto="Carregando o panorama global..." />}>
        <PanoramaGlobal />
      </Suspense>
    );
  }
  if (secretaria) {
    // O seletor de contexto do topo controla o Dashboard: "Toda a Rede Municipal"
    // (escolaId nulo) → consolidado da rede; uma escola → panorama daquela escola.
    return (
      <Suspense fallback={<Carregando texto="Carregando o panorama..." />}>
        {escolaId == null
          ? <PanoramaRede />
          : <PanoramaEscolaDaRede escolaId={escolaId} />}
      </Suspense>
    );
  }
  return <DashboardEscola />;
}

function DashboardEscola() {
  const { escolaId, escolas, selecionarEscola, usuario } = useApp();
  const { dados, erro, carregando } = useApi<DadosDashboard>(
    escolaId ? `/escolas/${escolaId}/dashboard` : null);
  // /insights é mais pesado: carrega em paralelo e independente (a página não
  // trava esperando por ele; cada seção mostra seu próprio estado).
  const { dados: intel, carregando: carregandoIntel } = useApi<Insights>(
    escolaId ? `/escolas/${escolaId}/insights` : null, { timeoutMs: 45000 });

  // Quem opera a escola (admin/coordenador, não Secretaria) e ainda não tem
  // NADA cadastrado vê só o "Comece aqui" (o estado vive na escola).
  const podeConfigurar = (Boolean(usuario?.is_global) ||
    ["admin", "coordenador"].includes(usuario?.cargo ?? "")) &&
    !(!usuario?.is_global && usuario?.rede_id != null);
  const precisaConfigurar = podeConfigurar && dados != null &&
    dados.total_turmas === 0 && dados.total_alunos === 0;

  if (!carregando && precisaConfigurar) {
    return (
      <div className="mx-auto flex min-h-[62vh] max-w-lg flex-col items-center justify-center gap-6 text-center">
        {escolas.length > 1 && (
          <select
            aria-label="Selecionar escola"
            className="w-full max-w-xs rounded-lg border border-zinc-300 bg-white px-3 py-2 text-center text-sm font-semibold dark:border-zinc-700 dark:bg-zinc-950"
            value={escolaId ?? ""}
            onChange={(evento) => selecionarEscola(Number(evento.target.value))}
          >
            {escolas.map((escola) => (
              <option key={escola.id} value={escola.id}>{escola.nome}</option>
            ))}
          </select>
        )}
        <Rocket size={44} className="text-indigo-600 dark:text-indigo-400" />
        <div className="space-y-2">
          <h1 className="text-2xl font-semibold tracking-tight">Bem-vindo(a) ao Constela Edu</h1>
          <p className="text-zinc-500 dark:text-zinc-400">
            Vamos deixar sua escola pronta em poucos minutos: turmas, alunos e as plataformas
            conectadas. É só clicar para começar.
          </p>
        </div>
        <Link to="/comecar">
          <Botao>
            Comece aqui <ArrowRight size={16} />
          </Botao>
        </Link>
      </div>
    );
  }

  const subtitulo = dados
    ? `Panorama da sua escola · Ano letivo ${dados.escola.ano_letivo_ativo}`
    : "Aqui está o panorama da sua escola.";

  return (
    <div className="space-y-8">
      <Cabecalho
        nome={usuario?.nome ?? ""}
        subtitulo={subtitulo}
        escolas={escolas}
        escolaId={escolaId}
        selecionar={selecionarEscola}
      />

      {!carregando && erro && (
        <Vazio titulo="Não foi possível carregar os indicadores" descricao={erro.message} />
      )}

      {carregando && (
        <div className="space-y-8">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-28" />)}
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            <Skeleton className="h-48" />
            <Skeleton className="h-48" />
          </div>
          <Skeleton className="h-64" />
        </div>
      )}

      {!carregando && dados && (
        <>
          <Indicadores dados={dados} />
          <Inteligencia intel={intel ?? null} carregando={carregandoIntel && !intel} />
          <LeituraMatematica dados={dados} />
          <TopRanking top={dados.top10} />
        </>
      )}
    </div>
  );
}
