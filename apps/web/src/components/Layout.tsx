import {
  ArrowLeftRight,
  Award,
  Bell,
  RefreshCw,
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
  PanelLeftClose,
  PanelLeftOpen,
  Rocket,
  School,
  Search,
  Settings,
  SlidersHorizontal,
  Sparkles,
  Sun,
  Trophy,
  Upload,
  UserCog,
  Users,
  X,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { Suspense, useEffect, useRef, useState } from "react";
import type { KeyboardEvent as ReactKeyboardEvent } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";

import { useApp } from "../context/AppContext";
import { useImportacaoLote } from "../context/ImportacaoLoteContext";
import { useApi } from "../hooks/useApi";
import { useAtalhosGlobais } from "../lib/atalhos";
import { dataHora } from "../lib/formato";
import { normalizar } from "../lib/nomes";
import { LogoHorizontal } from "./Logo";
import { Carregando } from "./ui";

interface ItemNav {
  rotulo: string;
  caminho: string;
  icone: LucideIcon;
  /** Destaca só no match EXATO (rota pai que tem sub-rotas próprias). */
  exato?: boolean;
  /** Só para gestão (admin/coordenador) — professor não vê. */
  gestao?: boolean;
  /** Só para o administrador GLOBAL (gerencia todas as escolas). */
  global?: boolean;
}

interface GrupoNav {
  chave: string;
  rotulo: string;
  icone: LucideIcon;
  itens: ItemNav[];
}

// Dashboard fica fora dos grupos — é a página inicial, sempre à mão.
const DASHBOARD: ItemNav = { rotulo: "Dashboard", caminho: "/", icone: LayoutDashboard, exato: true };
// "Comece aqui": assistente de onboarding — fica fora dos grupos, logo abaixo
// do Dashboard, e só para gestão (admin/coordenador cria turmas e integrações).
const COMECAR: ItemNav = { rotulo: "Comece aqui", caminho: "/comecar", icone: Rocket, gestao: true };

// Menu agrupado (accordion): reduz o excesso de itens visíveis sem esconder
// nenhuma funcionalidade. Cada grupo abre/fecha; o da rota atual abre sozinho.
// Itens com `gestao: true` são exclusivos de admin/coordenador — o professor
// vê apenas o que toca as turmas dele (o backend também bloqueia tudo isto).
const GRUPOS: GrupoNav[] = [
  {
    chave: "desempenho", rotulo: "Desempenho", icone: Trophy, itens: [
      { rotulo: "Premiações", caminho: "/premiacoes", icone: Award },
      // Ranking Geral agora reúne Geral/Leitura/Matemática/Evolução num seletor
      // interno (a própria tela troca o conteúdo, sem abas separadas).
      { rotulo: "Ranking Geral", caminho: "/ranking", icone: Trophy },
      { rotulo: "Comparador", caminho: "/comparador", icone: GitCompareArrows, gestao: true },
    ],
  },
  {
    chave: "gestao", rotulo: "Gestão Escolar", icone: Users, itens: [
      { rotulo: "Visão da Escola", caminho: "/escola", icone: Building2, gestao: true },
      { rotulo: "Alunos", caminho: "/alunos", icone: GraduationCap },
      { rotulo: "Turmas", caminho: "/turmas", icone: Users, gestao: true },
      { rotulo: "Professores", caminho: "/professores", icone: School, gestao: true },
    ],
  },
  {
    chave: "plataformas", rotulo: "Plataformas", icone: Blocks, itens: [
      { rotulo: "Matific", caminho: "/matific", icone: Calculator, gestao: true },
      { rotulo: "Elefante Letrado", caminho: "/elefante", icone: BookOpen, gestao: true },
      { rotulo: "Catálogo de Livros", caminho: "/livros", icone: BookOpen, gestao: true },
      { rotulo: "Importações", caminho: "/importacoes", icone: Upload, gestao: true },
      { rotulo: "Sincronização automática", caminho: "/sincronizacao", icone: RefreshCw, gestao: true },
    ],
  },
  {
    chave: "gamificacao", rotulo: "Gamificação", icone: Award, itens: [
      { rotulo: "Conquistas", caminho: "/conquistas", icone: Award, exato: true, gestao: true },
      { rotulo: "Biblioteca de Conquistas", caminho: "/conquistas/biblioteca", icone: Medal },
    ],
  },
  {
    chave: "inteligencia", rotulo: "Inteligência", icone: Sparkles, itens: [
      { rotulo: "Insights", caminho: "/insights", icone: Lightbulb },
      { rotulo: "Assistente", caminho: "/assistente", icone: Bot, gestao: true },
      { rotulo: "Simulador", caminho: "/simulador", icone: FlaskConical, gestao: true },
    ],
  },
  {
    chave: "relatorios", rotulo: "Relatórios", icone: FileText, itens: [
      { rotulo: "Relatórios", caminho: "/relatorios", icone: FileText },
      { rotulo: "Painel Público", caminho: "/painel-publico", icone: MonitorPlay, gestao: true },
    ],
  },
  {
    chave: "config", rotulo: "Configurações", icone: Settings, itens: [
      { rotulo: "Métricas", caminho: "/metricas", icone: SlidersHorizontal, gestao: true },
      // Sem `gestao`: o professor também entra — vê SÓ a própria conta, para
      // gerar/ver a própria senha (matriz aplicada no backend).
      { rotulo: "Usuários", caminho: "/usuarios", icone: UserCog },
      { rotulo: "Escolas", caminho: "/escolas", icone: Building2, gestao: true, global: true },
      { rotulo: "Configurações Gerais", caminho: "/configuracoes", icone: Settings, gestao: true },
    ],
  },
];

/** Grupos visíveis para o papel do usuário (itens de gestão saem para o
 *  professor; itens globais só para o admin global; grupos vazios somem). */
function gruposVisiveis(gestor: boolean, global: boolean): GrupoNav[] {
  return GRUPOS
    .map((g) => ({
      ...g,
      itens: g.itens.filter((i) => (gestor || !i.gestao) && (global || !i.global)),
    }))
    .filter((g) => g.itens.length > 0);
}

/** Todos os itens de menu que o usuário PODE abrir (Dashboard + grupos
 *  visíveis), achatados — base da busca por páginas. */
function itensNavVisiveis(gestor: boolean, global: boolean): ItemNav[] {
  return [
    DASHBOARD,
    ...(gestor ? [COMECAR] : []),
    ...gruposVisiveis(gestor, global).flatMap((g) => g.itens),
  ];
}

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
  alunos: { id: number; nome: string; turma: string | null }[];
  turmas: { id: number; nome: string }[];
  professores: { id: number; nome: string }[];
  livros: { id: number; nome: string }[];
}

/** Uma opção do resultado: página do menu ou registro (aluno/turma/...). */
interface Opcao {
  chave: string;
  rotulo: string;
  sub?: string;
  Icone?: LucideIcon;
  caminho: string;
}

/** Pesquisa global (PRD §21): abre PÁGINAS do menu (como clicar na barra
 *  lateral) e encontra alunos, turmas, professores e livros — sempre dentro
 *  do que o cargo pode acessar (o menu já é filtrado por papel; o backend
 *  filtra os alunos pelas turmas do professor). Navegável pelo teclado. */
function PesquisaGlobal() {
  const { escolaId, usuario } = useApp();
  const navegar = useNavigate();
  const [termo, setTermo] = useState("");
  const [aberto, setAberto] = useState(false);
  const [ativo, setAtivo] = useState(0);
  const caixa = useRef<HTMLDivElement | null>(null);

  const gestor = Boolean(usuario?.is_global) ||
    ["admin", "coordenador"].includes(usuario?.cargo ?? "");
  const global = Boolean(usuario?.is_global);

  const consulta = termo.trim();

  // Atrasa (debounce) a busca para não consultar a API a cada tecla.
  const [consultaAtrasada, setConsultaAtrasada] = useState("");
  useEffect(() => {
    const t = window.setTimeout(() => setConsultaAtrasada(consulta), 200);
    return () => window.clearTimeout(t);
  }, [consulta]);
  const { dados: resultado } = useApi<ResultadoPesquisa>(
    escolaId && consultaAtrasada.length >= 2
      ? `/escolas/${escolaId}/pesquisa?q=${encodeURIComponent(consultaAtrasada)}`
      : null);

  useEffect(() => {
    function fechar(evento: MouseEvent) {
      if (caixa.current && !caixa.current.contains(evento.target as Node)) setAberto(false);
    }
    document.addEventListener("mousedown", fechar);
    return () => document.removeEventListener("mousedown", fechar);
  }, []);

  // Páginas do menu que casam com o texto (só as que o cargo pode abrir).
  const alvo = normalizar(consulta);
  const paginas: Opcao[] = consulta.length < 1 ? [] : itensNavVisiveis(gestor, global)
    .filter((item) => normalizar(item.rotulo).includes(alvo))
    .slice(0, 6)
    .map((item) => ({
      chave: `pag:${item.caminho}`, rotulo: item.rotulo,
      sub: "Página", Icone: item.icone, caminho: item.caminho,
    }));

  const registros: { titulo: string; itens: Opcao[] }[] = resultado
    ? ([
        {
          titulo: "Alunos",
          itens: resultado.alunos.map((a) => ({
            chave: `alu:${a.id}`, rotulo: a.nome,
            sub: a.turma ?? "Aluno", Icone: GraduationCap,
            caminho: `/alunos/${a.id}`,
          })),
        },
        {
          titulo: "Turmas",
          itens: resultado.turmas.map((t) => ({
            chave: `tur:${t.id}`, rotulo: t.nome, sub: "Turma",
            Icone: Users, caminho: `/turmas/${t.id}`,
          })),
        },
        {
          titulo: "Professores",
          itens: resultado.professores.map((p) => ({
            chave: `prof:${p.id}`, rotulo: p.nome, sub: "Professor",
            Icone: School, caminho: "/professores",
          })),
        },
        {
          titulo: "Livros",
          itens: resultado.livros.map((l) => ({
            chave: `liv:${l.id}`, rotulo: l.nome, sub: "Livro",
            Icone: BookOpen, caminho: "/livros",
          })),
        },
      ].filter((s) => s.itens.length > 0))
    : [];

  const secoes = [
    ...(paginas.length ? [{ titulo: "Páginas", itens: paginas }] : []),
    ...registros,
  ];
  const planas = secoes.flatMap((s) => s.itens); // ordem para o teclado
  const mostrar = aberto && consulta.length >= 2;

  useEffect(() => { setAtivo(0); }, [consulta, resultado]);

  function abrir(caminho: string) {
    setTermo("");
    setAberto(false);
    navegar(caminho);
  }

  function aoTeclar(evento: ReactKeyboardEvent<HTMLInputElement>) {
    if (evento.key === "Escape") { setAberto(false); return; }
    if (!planas.length) return;
    if (evento.key === "ArrowDown") {
      evento.preventDefault();
      setAtivo((i) => (i + 1) % planas.length);
    } else if (evento.key === "ArrowUp") {
      evento.preventDefault();
      setAtivo((i) => (i - 1 + planas.length) % planas.length);
    } else if (evento.key === "Enter") {
      evento.preventDefault();
      const alvo = planas[ativo] ?? planas[0];
      if (alvo) abrir(alvo.caminho);
    }
  }

  return (
    <div ref={caixa} className="relative hidden min-w-0 flex-1 items-center sm:flex sm:max-w-xs">
      <Search size={14} className="pointer-events-none absolute left-3 text-zinc-400" />
      <input
        id="pesquisa-global"
        aria-label="Pesquisar páginas, alunos, turmas... (Ctrl+K)"
        autoComplete="off"
        className="w-full rounded-lg border border-zinc-300 bg-white py-1.5 pl-8 pr-3 text-sm dark:border-zinc-700 dark:bg-zinc-900"
        placeholder="Pesquisar...  (Ctrl+K)"
        value={termo}
        onChange={(evento) => { setTermo(evento.target.value); setAberto(true); }}
        onFocus={() => setAberto(true)}
        onKeyDown={aoTeclar}
      />
      {mostrar && (
        <div className="absolute left-0 top-full z-40 mt-1 max-h-[70vh] w-full overflow-y-auto rounded-lg border border-zinc-200 bg-white shadow-lg dark:border-zinc-700 dark:bg-zinc-900">
          {secoes.length === 0 ? (
            <p className="px-3 py-2 text-sm text-zinc-400">Nada encontrado.</p>
          ) : (
            secoes.map((secao) => (
              <div key={secao.titulo}>
                <p className="bg-zinc-50 px-3 py-1 text-[11px] font-semibold uppercase tracking-wide text-zinc-400 dark:bg-zinc-800/60">
                  {secao.titulo}
                </p>
                {secao.itens.map((item) => {
                  const indice = planas.findIndex((o) => o.chave === item.chave);
                  const realcado = indice === ativo;
                  return (
                    <button
                      key={item.chave}
                      onMouseEnter={() => setAtivo(indice)}
                      className={`flex w-full items-center gap-2.5 px-3 py-2 text-left text-sm ${
                        realcado ? "bg-indigo-50 dark:bg-indigo-500/10" : "hover:bg-zinc-100 dark:hover:bg-zinc-800"
                      }`}
                      onClick={() => abrir(item.caminho)}
                    >
                      {item.Icone && <item.Icone size={15} className="shrink-0 text-zinc-400" />}
                      <span className="min-w-0 flex-1 truncate">{item.rotulo}</span>
                      {item.sub && (
                        <span className="shrink-0 text-xs text-zinc-400">{item.sub}</span>
                      )}
                    </button>
                  );
                })}
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
  const { dados } = useApi<Notificacao[]>(
    aberto && escolaId ? `/escolas/${escolaId}/notificacoes` : null);
  const itens = dados ?? [];
  const caixa = useRef<HTMLDivElement | null>(null);

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
  const { usuario } = useApp();
  const gestor = Boolean(usuario?.is_global) ||
    ["admin", "coordenador"].includes(usuario?.cargo ?? "");
  const grupos = gruposVisiveis(gestor, Boolean(usuario?.is_global));
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
      {gestor && <LinkMenu item={COMECAR} aoNavegar={aoNavegar} />}

      {grupos.map((grupo) => {
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

function Marca({ aoNavegar }: { aoNavegar?: () => void }) {
  return (
    <div className="border-b border-zinc-200 dark:border-zinc-800">
      {/* Clicar na marca volta para o Dashboard */}
      <NavLink
        to="/"
        onClick={aoNavegar}
        aria-label="Ir para o Dashboard"
        className="flex items-center gap-2.5 px-5 py-4 transition-opacity hover:opacity-80"
      >
        <LogoHorizontal altura={38} />
      </NavLink>
    </div>
  );
}

/** Indicador flutuante da importação em lote: mostra o progresso em qualquer
 *  tela e leva de volta a Importações — o processamento roda no contexto. */
function IndicadorImportacao() {
  const { fase, progresso, emAndamento } = useImportacaoLote();
  const { pathname } = useLocation();
  if (pathname === "/importacoes") return null;
  if (!emAndamento && fase !== "conferencia") return null;

  const rotulo = emAndamento
    ? `${fase === "analisando" ? "Analisando" : "Importando"} ${progresso.atual} de ${progresso.total}...`
    : "Importação aguardando conferência";

  return (
    <NavLink
      to="/importacoes"
      className="fixed bottom-4 right-4 z-20 flex items-center gap-2.5 rounded-full border border-indigo-200 bg-white px-4 py-2.5 text-sm font-medium text-indigo-700 shadow-lg transition-colors hover:bg-indigo-50 dark:border-indigo-500/30 dark:bg-zinc-900 dark:text-indigo-300 dark:hover:bg-zinc-800"
    >
      {emAndamento ? (
        <span className="h-3.5 w-3.5 shrink-0 animate-spin rounded-full border-2 border-indigo-300 border-t-indigo-600" />
      ) : (
        <Upload size={14} className="shrink-0" />
      )}
      {rotulo}
    </NavLink>
  );
}

const CHAVE_RECOLHIDO = "constela_menu_recolhido";

export default function Layout() {
  const { usuario, escolas, escolaId, selecionarEscola, tema, alternarTema, sair } = useApp();
  const [menuAberto, setMenuAberto] = useState(false);
  // Barra lateral recolhida (desktop): o conteúdo ocupa a tela toda. A escolha
  // fica salva no navegador para valer nas próximas visitas.
  const [recolhido, setRecolhido] = useState(() => {
    try {
      return localStorage.getItem(CHAVE_RECOLHIDO) === "1";
    } catch {
      return false;
    }
  });
  function alternarRecolhido() {
    setRecolhido((atual) => {
      try {
        localStorage.setItem(CHAVE_RECOLHIDO, atual ? "0" : "1");
      } catch {
        /* localStorage indisponível: só não persiste */
      }
      return !atual;
    });
  }
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
      {/* Sidebar fixa (desktop) — recolhível para dar a tela toda ao conteúdo */}
      <aside
        className={`fixed inset-y-0 left-0 z-30 hidden w-60 flex-col border-r border-zinc-200 bg-white pl-safe dark:border-zinc-800 dark:bg-zinc-900 ${
          recolhido ? "" : "lg:flex"
        }`}
      >
        <div className="flex items-center justify-between pr-2">
          <Marca />
          <button
            aria-label="Recolher menu"
            title="Recolher menu"
            className="rounded-lg p-2 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-600 dark:hover:bg-zinc-800 dark:hover:text-zinc-300"
            onClick={alternarRecolhido}
          >
            <PanelLeftClose size={17} />
          </button>
        </div>
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
              <Marca aoNavegar={() => setMenuAberto(false)} />
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

      <div className={recolhido ? "" : "lg:pl-60"}>
        <header className="sticky top-0 z-20 flex items-center gap-3 border-b border-zinc-200 bg-white/80 px-4 py-3 pr-safe pt-safe backdrop-blur dark:border-zinc-800 dark:bg-zinc-950/80">
          <button
            aria-label="Abrir menu"
            className="rounded-lg p-2 text-zinc-600 hover:bg-zinc-100 dark:text-zinc-300 dark:hover:bg-zinc-800 lg:hidden"
            onClick={() => setMenuAberto(true)}
          >
            <Menu size={18} />
          </button>
          {recolhido && (
            <button
              aria-label="Mostrar menu"
              title="Mostrar menu"
              className="hidden rounded-lg p-2 text-zinc-600 hover:bg-zinc-100 dark:text-zinc-300 dark:hover:bg-zinc-800 lg:block"
              onClick={alternarRecolhido}
            >
              <PanelLeftOpen size={18} />
            </button>
          )}

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
          {/* Suspense em volta do Outlet: ao navegar para uma página ainda não
              baixada (code-splitting), o menu/shell permanece e só o conteúdo
              mostra o fallback. */}
          <Suspense fallback={<Carregando texto="Abrindo..." />}>
            <Outlet />
          </Suspense>
        </main>
      </div>

      <IndicadorImportacao />
    </div>
  );
}
