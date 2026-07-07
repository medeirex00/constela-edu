import {
  ArrowLeftRight,
  Award,
  Bell,
  Blocks,
  BookOpen,
  Bot,
  Building2,
  Calculator,
  ChevronDown,
  FileText,
  FlaskConical,
  Lightbulb,
  GitCompareArrows,
  GraduationCap,
  LayoutDashboard,
  LogOut,
  Medal,
  Menu,
  MonitorPlay,
  Moon,
  School,
  Search,
  Settings,
  SlidersHorizontal,
  Sparkles,
  Sun,
  TrendingUp,
  Trophy,
  Upload,
  UserCog,
  Users,
  X,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";

import { useApp } from "../context/AppContext";
import { api } from "../lib/api";
import { useAtalhosGlobais } from "../lib/atalhos";
import { dataHora } from "../lib/formato";
import { LogoHorizontal } from "./Logo";

interface ItemNav {
  rotulo: string;
  caminho: string;
  icone: LucideIcon;
  /** Destaca só no match EXATO (rota pai que tem sub-rotas próprias). */
  exato?: boolean;
}

interface GrupoNav {
  chave: string;
  rotulo: string;
  icone: LucideIcon;
  itens: ItemNav[];
}

// Dashboard fica fora dos grupos — é a página inicial, sempre à mão.
const DASHBOARD: ItemNav = { rotulo: "Dashboard", caminho: "/", icone: LayoutDashboard, exato: true };

// Menu agrupado (accordion): reduz o excesso de itens visíveis sem esconder
// nenhuma funcionalidade. Cada grupo abre/fecha; o da rota atual abre sozinho.
const GRUPOS: GrupoNav[] = [
  {
    chave: "desempenho", rotulo: "Desempenho", icone: Trophy, itens: [
      { rotulo: "Premiações", caminho: "/premiacoes", icone: Award },
      { rotulo: "Ranking Geral", caminho: "/ranking", icone: Trophy },
      { rotulo: "Ranking de Leitura", caminho: "/ranking-leitura", icone: BookOpen },
      { rotulo: "Ranking de Evolução", caminho: "/evolucao", icone: TrendingUp },
      { rotulo: "Comparador", caminho: "/comparador", icone: GitCompareArrows },
    ],
  },
  {
    chave: "gestao", rotulo: "Gestão Escolar", icone: Users, itens: [
      { rotulo: "Visão da Escola", caminho: "/escola", icone: Building2 },
      { rotulo: "Alunos", caminho: "/alunos", icone: GraduationCap },
      { rotulo: "Turmas", caminho: "/turmas", icone: Users },
      { rotulo: "Professores", caminho: "/professores", icone: School },
    ],
  },
  {
    chave: "plataformas", rotulo: "Plataformas", icone: Blocks, itens: [
      { rotulo: "Matific", caminho: "/matific", icone: Calculator },
      { rotulo: "Elefante Letrado", caminho: "/elefante", icone: BookOpen },
      { rotulo: "Catálogo de Livros", caminho: "/livros", icone: BookOpen },
      { rotulo: "Importações", caminho: "/importacoes", icone: Upload },
    ],
  },
  {
    chave: "gamificacao", rotulo: "Gamificação", icone: Award, itens: [
      { rotulo: "Conquistas", caminho: "/conquistas", icone: Award, exato: true },
      { rotulo: "Biblioteca de Conquistas", caminho: "/conquistas/biblioteca", icone: Medal },
    ],
  },
  {
    chave: "inteligencia", rotulo: "Inteligência", icone: Sparkles, itens: [
      { rotulo: "Insights", caminho: "/insights", icone: Lightbulb },
      { rotulo: "Assistente", caminho: "/assistente", icone: Bot },
      { rotulo: "Simulador", caminho: "/simulador", icone: FlaskConical },
    ],
  },
  {
    chave: "relatorios", rotulo: "Relatórios", icone: FileText, itens: [
      { rotulo: "Relatórios", caminho: "/relatorios", icone: FileText },
      { rotulo: "Painel Público", caminho: "/painel-publico", icone: MonitorPlay },
    ],
  },
  {
    chave: "config", rotulo: "Configurações", icone: Settings, itens: [
      { rotulo: "Métricas", caminho: "/metricas", icone: SlidersHorizontal },
      { rotulo: "Usuários", caminho: "/usuarios", icone: UserCog },
      { rotulo: "Configurações Gerais", caminho: "/configuracoes", icone: Settings },
    ],
  },
];

const CHAVE_MENU = "constela_menu_abertos";

/** Grupo que contém a rota atual (para destacar e abrir automaticamente). */
function grupoDaRota(pathname: string): string | null {
  for (const grupo of GRUPOS) {
    const bate = grupo.itens.some(
      (it) => pathname === it.caminho || (it.caminho !== "/" && pathname.startsWith(it.caminho + "/")),
    );
    if (bate) return grupo.chave;
  }
  return null;
}

function carregarAbertos(): Set<string> {
  try {
    const bruto = localStorage.getItem(CHAVE_MENU);
    if (bruto) return new Set(JSON.parse(bruto) as string[]);
  } catch {
    /* localStorage indisponível: começa tudo fechado */
  }
  return new Set();
}

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
        id="pesquisa-global"
        aria-label="Pesquisar em todo o sistema (Ctrl+K)"
        className="w-full rounded-lg border border-zinc-300 bg-white py-1.5 pl-8 pr-3 text-sm dark:border-zinc-700 dark:bg-zinc-900"
        placeholder="Pesquisar...  (Ctrl+K)"
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

/** Um link do menu (item de topo ou subitem de um grupo). */
function LinkMenu({ item, aoNavegar, subitem }: {
  item: ItemNav;
  aoNavegar?: () => void;
  subitem?: boolean;
}) {
  return (
    <NavLink
      to={item.caminho}
      end={item.exato}
      onClick={aoNavegar}
      className={({ isActive }) =>
        `flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors ${
          isActive
            ? "bg-indigo-50 font-semibold text-indigo-700 dark:bg-indigo-500/10 dark:text-indigo-300"
            : "font-medium text-zinc-600 hover:bg-zinc-100/70 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-800/60 dark:hover:text-zinc-100"
        }`
      }
    >
      <item.icone size={subitem ? 15 : 16} strokeWidth={2} className="shrink-0" />
      <span className="truncate">{item.rotulo}</span>
    </NavLink>
  );
}

/** Navegação lateral agrupada em accordion (desktop e celular). */
function Navegacao({ aoNavegar }: { aoNavegar?: () => void }) {
  const { pathname } = useLocation();
  const ativo = grupoDaRota(pathname);
  const [abertos, setAbertos] = useState<Set<string>>(() => {
    const iniciais = carregarAbertos();
    if (ativo) iniciais.add(ativo); // o grupo da rota atual já nasce aberto
    return iniciais;
  });

  // Ao navegar para uma página dentro de um grupo fechado (busca, atalho,
  // link direto), abre esse grupo para o item ativo ficar visível.
  useEffect(() => {
    if (ativo) setAbertos((atuais) => (atuais.has(ativo) ? atuais : new Set(atuais).add(ativo)));
  }, [ativo]);

  function alternar(chave: string) {
    setAbertos((atuais) => {
      const proximos = new Set(atuais);
      if (proximos.has(chave)) proximos.delete(chave);
      else proximos.add(chave);
      try {
        localStorage.setItem(CHAVE_MENU, JSON.stringify([...proximos]));
      } catch {
        /* ignora se localStorage indisponível */
      }
      return proximos;
    });
  }

  return (
    <nav className="flex-1 space-y-1 overflow-y-auto px-3 py-4">
      <LinkMenu item={DASHBOARD} aoNavegar={aoNavegar} />

      {GRUPOS.map((grupo) => {
        const aberto = abertos.has(grupo.chave);
        const temAtivo = ativo === grupo.chave;
        return (
          <div key={grupo.chave}>
            <button
              type="button"
              aria-expanded={aberto}
              onClick={() => alternar(grupo.chave)}
              className={`flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                temAtivo
                  ? "text-indigo-700 dark:text-indigo-300"
                  : "text-zinc-600 hover:bg-zinc-100/70 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-800/60 dark:hover:text-zinc-100"
              }`}
            >
              <grupo.icone
                size={16}
                strokeWidth={2}
                className={`shrink-0 ${temAtivo ? "text-indigo-600 dark:text-indigo-400" : ""}`}
              />
              <span className="flex-1 text-left">{grupo.rotulo}</span>
              {temAtivo && !aberto && (
                <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-indigo-500" aria-hidden />
              )}
              <ChevronDown
                size={15}
                className={`shrink-0 text-zinc-400 transition-transform duration-200 ${aberto ? "rotate-180" : ""}`}
              />
            </button>

            {/* Animação suave de altura via grid 0fr→1fr (respeita reduce-motion). */}
            <div
              className={`grid transition-[grid-template-rows] duration-300 ease-out motion-reduce:transition-none ${
                aberto ? "grid-rows-[1fr]" : "grid-rows-[0fr]"
              }`}
            >
              <div className="overflow-hidden">
                <div className="ml-4 mt-0.5 space-y-0.5 border-l border-zinc-200 pl-3 dark:border-zinc-800">
                  {grupo.itens.map((item) => (
                    <LinkMenu key={item.caminho} item={item} aoNavegar={aoNavegar} subitem />
                  ))}
                </div>
              </div>
            </div>
          </div>
        );
      })}
    </nav>
  );
}

function Marca() {
  return (
    <div className="flex items-center gap-2.5 border-b border-zinc-200 px-5 py-4 dark:border-zinc-800">
      <LogoHorizontal altura={38} />
    </div>
  );
}

export default function Layout() {
  const { usuario, escolas, escolaId, selecionarEscola, tema, alternarTema, sair } = useApp();
  const [menuAberto, setMenuAberto] = useState(false);
  useAtalhosGlobais(); // Ctrl+K pesquisa, Alt+1..0 navegação (web e desktop)

  // Menu aberto no celular: trava o scroll do fundo e fecha no Esc (evita o
  // "scroll fantasma" atrás do drawer no Safari do iPhone).
  useEffect(() => {
    if (!menuAberto) return;
    const anterior = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const aoTeclar = (evento: KeyboardEvent) => {
      if (evento.key === "Escape") setMenuAberto(false);
    };
    document.addEventListener("keydown", aoTeclar);
    return () => {
      document.body.style.overflow = anterior;
      document.removeEventListener("keydown", aoTeclar);
    };
  }, [menuAberto]);

  return (
    <div className="min-h-screen">
      {/* Sidebar fixa (desktop) */}
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-60 flex-col border-r border-zinc-200 bg-white pl-safe dark:border-zinc-800 dark:bg-zinc-900 lg:flex">
        <Marca />
        <Navegacao />
      </aside>

      {/* Sidebar deslizante (celular/tablet) — botões reais, resposta imediata ao toque (PRD §9) */}
      {menuAberto && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <button
            aria-label="Fechar menu"
            className="absolute inset-0 bg-zinc-950/40"
            onClick={() => setMenuAberto(false)}
          />
          <aside className="absolute inset-y-0 left-0 flex w-64 flex-col border-r border-zinc-200 bg-white pl-safe pt-safe dark:border-zinc-800 dark:bg-zinc-900">
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
            <Navegacao aoNavegar={() => setMenuAberto(false)} />
          </aside>
        </div>
      )}

      <div className="lg:pl-60">
        <header className="sticky top-0 z-20 flex items-center gap-3 border-b border-zinc-200 bg-white/80 px-4 py-3 pr-safe pt-safe backdrop-blur dark:border-zinc-800 dark:bg-zinc-950/80">
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
