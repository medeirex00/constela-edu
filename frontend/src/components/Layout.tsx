import {
  ArrowLeftRight,
  BookOpen,
  Calculator,
  FileText,
  GraduationCap,
  LayoutDashboard,
  LogOut,
  Menu,
  Moon,
  School,
  Settings,
  SlidersHorizontal,
  Sun,
  Trophy,
  Upload,
  Users,
  X,
} from "lucide-react";
import { useState } from "react";
import { NavLink, Outlet } from "react-router-dom";

import { useApp } from "../context/AppContext";

const MENU = [
  { rotulo: "Dashboard", caminho: "/", icone: LayoutDashboard },
  { rotulo: "Ranking Geral", caminho: "/ranking", icone: Trophy },
  { rotulo: "Alunos", caminho: "/alunos", icone: GraduationCap },
  { rotulo: "Turmas", caminho: "/turmas", icone: Users },
  { rotulo: "Professores", caminho: "/professores", icone: School },
  { rotulo: "Matific", caminho: "/matific", icone: Calculator },
  { rotulo: "Elefante Letrado", caminho: "/elefante", icone: BookOpen },
  { rotulo: "Catálogo de Livros", caminho: "/livros", icone: BookOpen },
  { rotulo: "Importações", caminho: "/importacoes", icone: Upload },
  { rotulo: "Relatórios", caminho: "/relatorios", icone: FileText },
  { rotulo: "Métricas", caminho: "/metricas", icone: SlidersHorizontal },
  { rotulo: "Configurações", caminho: "/configuracoes", icone: Settings },
];

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
