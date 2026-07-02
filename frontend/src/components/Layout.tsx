import {
  ArrowLeftRight,
  Award,
  Bell,
  BookOpen,
  Building2,
  Calculator,
  FileText,
  FlaskConical,
  GitCompareArrows,
  GraduationCap,
  LayoutDashboard,
  LogOut,
  Menu,
  MonitorPlay,
  Moon,
  School,
  Search,
  Settings,
  SlidersHorizontal,
  Sun,
  TrendingUp,
  Trophy,
  Upload,
  UserCog,
  Users,
  X,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";

import { useApp } from "../context/AppContext";
import { api } from "../lib/api";
import { dataHora } from "../lib/formato";

const MENU = [
  { rotulo: "Dashboard", caminho: "/", icone: LayoutDashboard },
  { rotulo: "Ranking Geral", caminho: "/ranking", icone: Trophy },
  { rotulo: "Ranking de Evolução", caminho: "/evolucao", icone: TrendingUp },
  { rotulo: "Comparador", caminho: "/comparador", icone: GitCompareArrows },
  { rotulo: "Visão da Escola", caminho: "/escola", icone: Building2 },
  { rotulo: "Alunos", caminho: "/alunos", icone: GraduationCap },
  { rotulo: "Turmas", caminho: "/turmas", icone: Users },
  { rotulo: "Professores", caminho: "/professores", icone: School },
  { rotulo: "Matific", caminho: "/matific", icone: Calculator },
  { rotulo: "Elefante Letrado", caminho: "/elefante", icone: BookOpen },
  { rotulo: "Catálogo de Livros", caminho: "/livros", icone: BookOpen },
  { rotulo: "Importações", caminho: "/importacoes", icone: Upload },
  { rotulo: "Conquistas", caminho: "/conquistas", icone: Award },
  { rotulo: "Painel Público", caminho: "/painel-publico", icone: MonitorPlay },
  { rotulo: "Relatórios", caminho: "/relatorios", icone: FileText },
  { rotulo: "Simulador", caminho: "/simulador", icone: FlaskConical },
  { rotulo: "Métricas", caminho: "/metricas", icone: SlidersHorizontal },
  { rotulo: "Usuários", caminho: "/usuarios", icone: UserCog },
  { rotulo: "Configurações", caminho: "/configuracoes", icone: Settings },
];

interface ResultadoPesquisa {
  alunos: { id: number; nome: string }[];
  turmas: { id: number; nome: string }[];
  professores: { id: number; nome: string }[];
  livros: { id: number; nome: string }[];
}

/** Pesquisa global (PRD §21): encontra alunos, turmas, professores e livros. */
function PesquisaGlobal() {
  const { escolaId } = useApp();
  const navegar = useNavigate();
  const [termo, setTermo] = useState("");
  const [resultado, setResultado] = useState<ResultadoPesquisa | null>(null);
  const caixa = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!escolaId || termo.trim().length < 2) {
      setResultado(null);
      return;
    }
    const timer = window.setTimeout(() => {
      api<ResultadoPesquisa>(`/escolas/${escolaId}/pesquisa?q=${encodeURIComponent(termo.trim())}`)
        .then(setResultado)
        .catch(() => setResultado(null));
    }, 250);
    return () => window.clearTimeout(timer);
  }, [escolaId, termo]);

  useEffect(() => {
    function fechar(evento: MouseEvent) {
      if (caixa.current && !caixa.current.contains(evento.target as Node)) setResultado(null);
    }
    document.addEventListener("mousedown", fechar);
    return () => document.removeEventListener("mousedown", fechar);
  }, []);

  function abrir(caminho: string) {
    setTermo("");
    setResultado(null);
    navegar(caminho);
  }

  const grupos = resultado
    ? ([
        { titulo: "Alunos", itens: resultado.alunos, caminho: (id: number) => `/alunos/${id}` },
        { titulo: "Turmas", itens: resultado.turmas, caminho: (id: number) => `/turmas/${id}` },
        { titulo: "Professores", itens: resultado.professores, caminho: () => "/professores" },
        { titulo: "Livros", itens: resultado.livros, caminho: () => "/livros" },
      ].filter((grupo) => grupo.itens.length > 0))
    : [];

  return (
    <div ref={caixa} className="relative hidden min-w-0 flex-1 items-center sm:flex sm:max-w-xs">
      <Search size={14} className="pointer-events-none absolute left-3 text-zinc-400" />
      <input
        aria-label="Pesquisar em todo o sistema"
        className="w-full rounded-lg border border-zinc-300 bg-white py-1.5 pl-8 pr-3 text-sm dark:border-zinc-700 dark:bg-zinc-900"
        placeholder="Pesquisar..."
        value={termo}
        onChange={(evento) => setTermo(evento.target.value)}
      />
      {resultado && (
        <div className="absolute left-0 top-full z-40 mt-1 w-full overflow-hidden rounded-lg border border-zinc-200 bg-white shadow-lg dark:border-zinc-700 dark:bg-zinc-900">
          {grupos.length === 0 ? (
            <p className="px-3 py-2 text-sm text-zinc-400">Nada encontrado.</p>
          ) : (
            grupos.map((grupo) => (
              <div key={grupo.titulo}>
                <p className="bg-zinc-50 px-3 py-1 text-[11px] font-semibold uppercase tracking-wide text-zinc-400 dark:bg-zinc-800/60">
                  {grupo.titulo}
                </p>
                {grupo.itens.map((item) => (
                  <button
                    key={item.id}
                    className="block w-full px-3 py-1.5 text-left text-sm hover:bg-zinc-100 dark:hover:bg-zinc-800"
                    onClick={() => abrir(grupo.caminho(item.id))}
                  >
                    {item.nome}
                  </button>
                ))}
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}

interface Notificacao {
  id: number;
  texto: string;
  autor: string | null;
  data: string;
}

/** Notificações (PRD §22): últimos acontecimentos relevantes da escola. */
function Notificacoes() {
  const { escolaId } = useApp();
  const [aberto, setAberto] = useState(false);
  const [itens, setItens] = useState<Notificacao[]>([]);
  const caixa = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!aberto || !escolaId) return;
    api<Notificacao[]>(`/escolas/${escolaId}/notificacoes`).then(setItens).catch(() => setItens([]));
  }, [aberto, escolaId]);

  useEffect(() => {
    function fechar(evento: MouseEvent) {
      if (caixa.current && !caixa.current.contains(evento.target as Node)) setAberto(false);
    }
    document.addEventListener("mousedown", fechar);
    return () => document.removeEventListener("mousedown", fechar);
  }, []);

  return (
    <div ref={caixa} className="relative">
      <button
        aria-label="Notificações"
        className="rounded-lg p-2 text-zinc-600 hover:bg-zinc-100 dark:text-zinc-300 dark:hover:bg-zinc-800"
        onClick={() => setAberto((atual) => !atual)}
      >
        <Bell size={17} />
      </button>
      {aberto && (
        <div className="absolute right-0 top-full z-40 mt-1 w-80 overflow-hidden rounded-lg border border-zinc-200 bg-white shadow-lg dark:border-zinc-700 dark:bg-zinc-900">
          <p className="border-b border-zinc-200 px-3 py-2 text-xs font-semibold uppercase tracking-wide text-zinc-400 dark:border-zinc-800">
            Notificações
          </p>
          {itens.length === 0 ? (
            <p className="px-3 py-3 text-sm text-zinc-400">Nenhuma novidade por enquanto.</p>
          ) : (
            <ul className="max-h-80 overflow-y-auto">
              {itens.map((item) => (
                <li key={item.id} className="border-b border-zinc-100 px-3 py-2 last:border-0 dark:border-zinc-800/60">
                  <p className="text-sm">{item.texto}</p>
                  <p className="text-xs text-zinc-400">
                    {item.autor ? `${item.autor} · ` : ""}{dataHora(item.data)}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

function ItensMenu({ aoNavegar }: { aoNavegar?: () => void }) {
  return (
    <nav className="flex-1 space-y-0.5 overflow-y-auto px-3 py-4">
      {MENU.map(({ rotulo, caminho, icone: Icone }) => (
        <NavLink
          key={caminho}
          to={caminho}
          end={caminho === "/"}
          onClick={aoNavegar}
          className={({ isActive }) =>
            `flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
              isActive
                ? "bg-zinc-100 text-zinc-900 dark:bg-zinc-800 dark:text-zinc-50"
                : "text-zinc-600 hover:bg-zinc-100/70 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-800/60 dark:hover:text-zinc-100"
            }`
          }
        >
          <Icone size={16} strokeWidth={2} />
          {rotulo}
        </NavLink>
      ))}
    </nav>
  );
}

function Marca() {
  return (
    <div className="flex items-center gap-2.5 border-b border-zinc-200 px-5 py-4 dark:border-zinc-800">
      <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-indigo-600 text-sm font-bold text-white">
        S
      </span>
      <div className="leading-tight">
        <p className="text-sm font-semibold tracking-tight">SGPE</p>
        <p className="text-[11px] text-zinc-500 dark:text-zinc-400">Gestão e Premiação Escolar</p>
      </div>
    </div>
  );
}

export default function Layout() {
  const { usuario, escolas, escolaId, selecionarEscola, tema, alternarTema, sair } = useApp();
  const [menuAberto, setMenuAberto] = useState(false);

  return (
    <div className="min-h-screen">
      {/* Sidebar fixa (desktop) */}
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-60 flex-col border-r border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900 lg:flex">
        <Marca />
        <ItensMenu />
      </aside>

      {/* Sidebar deslizante (celular/tablet) — botões reais, resposta imediata ao toque (PRD §9) */}
      {menuAberto && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <button
            aria-label="Fechar menu"
            className="absolute inset-0 bg-zinc-950/40"
            onClick={() => setMenuAberto(false)}
          />
          <aside className="absolute inset-y-0 left-0 flex w-64 flex-col border-r border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
            <div className="flex items-center justify-between pr-2">
              <Marca />
              <button
                aria-label="Fechar menu"
                className="rounded-lg p-2 text-zinc-500 hover:bg-zinc-100 dark:hover:bg-zinc-800"
                onClick={() => setMenuAberto(false)}
              >
                <X size={18} />
              </button>
            </div>
            <ItensMenu aoNavegar={() => setMenuAberto(false)} />
          </aside>
        </div>
      )}

      <div className="lg:pl-60">
        <header className="sticky top-0 z-20 flex items-center gap-3 border-b border-zinc-200 bg-white/80 px-4 py-3 backdrop-blur dark:border-zinc-800 dark:bg-zinc-950/80">
          <button
            aria-label="Abrir menu"
            className="rounded-lg p-2 text-zinc-600 hover:bg-zinc-100 dark:text-zinc-300 dark:hover:bg-zinc-800 lg:hidden"
            onClick={() => setMenuAberto(true)}
          >
            <Menu size={18} />
          </button>

          <PesquisaGlobal />

          {/* Troca rápida de escola disponível em todas as telas */}
          {escolas.length > 0 && (
            <label className="ml-auto flex items-center gap-2 text-sm">
              <ArrowLeftRight size={14} className="text-zinc-400" />
              <select
                aria-label="Escola selecionada"
                className="max-w-[180px] rounded-lg border border-zinc-300 bg-white px-2 py-1.5 text-sm dark:border-zinc-700 dark:bg-zinc-900 sm:max-w-none"
                value={escolaId ?? ""}
                onChange={(evento) => selecionarEscola(Number(evento.target.value))}
              >
                {escolas.map((escola) => (
                  <option key={escola.id} value={escola.id}>
                    {escola.nome}
                  </option>
                ))}
              </select>
            </label>
          )}

          <Notificacoes />

          <button
            aria-label={tema === "claro" ? "Ativar modo escuro" : "Ativar modo claro"}
            className="rounded-lg p-2 text-zinc-600 hover:bg-zinc-100 dark:text-zinc-300 dark:hover:bg-zinc-800"
            onClick={alternarTema}
          >
            {tema === "claro" ? <Moon size={17} /> : <Sun size={17} />}
          </button>

          <div className="hidden items-center gap-2 sm:flex">
            <span className="text-sm text-zinc-500 dark:text-zinc-400">{usuario?.nome}</span>
          </div>
          <button
            aria-label="Sair do sistema"
            title="Sair"
            className="rounded-lg p-2 text-zinc-600 hover:bg-zinc-100 dark:text-zinc-300 dark:hover:bg-zinc-800"
            onClick={sair}
          >
            <LogOut size={17} />
          </button>
        </header>

        <main className="mx-auto max-w-6xl px-4 py-6 lg:px-8 lg:py-8">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
