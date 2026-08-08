import {
  Activity,
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
  ChevronRight,
  ExternalLink,
  FileText,
  FlaskConical,
  Lightbulb,
  GitCompareArrows,
  GraduationCap,
  Landmark,
  LayoutDashboard,
  LifeBuoy,
  LogOut,
  Medal,
  Menu,
  MonitorPlay,
  Moon,
  PanelLeftClose,
  PanelLeftOpen,
  Radar,
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
import { api } from "../lib/api";
import { useHeartbeat } from "../hooks/useHeartbeat";
import { useOnboarding } from "../hooks/useOnboarding";
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
  /** Link externo (abre em nova aba) em vez de rota interna. */
  externo?: boolean;
  /** Operação de escola (importar, sincronizar, diagnosticar, onboarding):
   *  some para a Secretaria, que acompanha a rede mas não opera as escolas. */
  escolaOp?: boolean;
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
const COMECAR: ItemNav = { rotulo: "Comece aqui", caminho: "/comecar", icone: Rocket, gestao: true, escolaOp: true };
// "Secretaria": painel municipal (rede de escolas) + mapa — fica fora dos grupos,
// no topo, e só aparece para quem tem rede vinculada ou é admin global.
const SECRETARIA: ItemNav = { rotulo: "Secretaria", caminho: "/rede", icone: Landmark, exato: true };
// "Suporte": pasta no Google Drive com todos os guias de uso (Secretaria e Escola).
// Fica no rodapé do menu e aparece para TODOS os papéis — abre em nova aba.
const SUPORTE: ItemNav = {
  rotulo: "Suporte",
  caminho: "https://drive.google.com/drive/folders/1kbDGPRSsh7TOb6nk6smwXNyAJPkySk-i?hl=pt-br",
  icone: LifeBuoy,
  externo: true,
};

// ── Catálogo de itens de menu ────────────────────────────────────────────
// Cada item aponta para uma ROTA que já existe. As sidebars por perfil (logo
// abaixo) apenas ESCOLHEM e ORGANIZAM estes itens conforme a função de cada
// papel — nenhuma permissão nova nasce aqui. O backend continua sendo o portão
// real de cada rota (deps.py): reorganizar o menu não expõe nada, só arruma o
// que aquele perfil já podia abrir. Trocar de perfil troca a ESTRUTURA inteira
// (grupos, ordem, rótulos), não só a visibilidade de um botão.
const IT = {
  premiacoes: { rotulo: "Premiações", caminho: "/premiacoes", icone: Award },
  // Ranking Geral reúne Geral/Leitura/Matemática/Evolução num seletor interno.
  ranking: { rotulo: "Ranking Geral", caminho: "/ranking", icone: Trophy },
  rankingProf: { rotulo: "Ranking", caminho: "/ranking", icone: Trophy },
  comparador: { rotulo: "Comparador", caminho: "/comparador", icone: GitCompareArrows },
  insights: { rotulo: "Insights", caminho: "/insights", icone: Lightbulb },
  assistente: { rotulo: "Assistente", caminho: "/assistente", icone: Bot },
  simulador: { rotulo: "Simulador", caminho: "/simulador", icone: FlaskConical },
  visaoEscola: { rotulo: "Visão da Escola", caminho: "/escola", icone: Building2 },
  alunos: { rotulo: "Alunos", caminho: "/alunos", icone: GraduationCap },
  meusAlunos: { rotulo: "Meus Alunos", caminho: "/alunos", icone: GraduationCap },
  turmas: { rotulo: "Turmas", caminho: "/turmas", icone: Users },
  professores: { rotulo: "Professores", caminho: "/professores", icone: School },
  usuarios: { rotulo: "Usuários", caminho: "/usuarios", icone: UserCog },
  matific: { rotulo: "Matific", caminho: "/matific", icone: Calculator },
  elefante: { rotulo: "Elefante Letrado", caminho: "/elefante", icone: BookOpen },
  livros: { rotulo: "Catálogo de Livros", caminho: "/livros", icone: BookOpen },
  importacoes: { rotulo: "Importações", caminho: "/importacoes", icone: Upload },
  sincronizacao: { rotulo: "Sincronização automática", caminho: "/sincronizacao", icone: RefreshCw },
  diagnostico: { rotulo: "Diagnóstico Elefante", caminho: "/diagnostico-elefante", icone: Radar },
  conquistas: { rotulo: "Conquistas", caminho: "/conquistas", icone: Award, exato: true },
  bibliotecaConquistas: { rotulo: "Biblioteca de Conquistas", caminho: "/conquistas/biblioteca", icone: Medal },
  relatorios: { rotulo: "Relatórios", caminho: "/relatorios", icone: FileText },
  meusRelatorios: { rotulo: "Meus Relatórios", caminho: "/relatorios", icone: FileText },
  painelPublico: { rotulo: "Painel Público", caminho: "/painel-publico", icone: MonitorPlay },
  metricas: { rotulo: "Métricas", caminho: "/metricas", icone: SlidersHorizontal },
  configuracoes: { rotulo: "Configurações Gerais", caminho: "/configuracoes", icone: Settings },
  escolas: { rotulo: "Escolas", caminho: "/escolas", icone: Building2 },
  sessoes: { rotulo: "Sessões Ativas", caminho: "/sessoes", icone: Activity },
  redeGerenciar: { rotulo: "Gerenciar Rede", caminho: "/rede/gerenciar", icone: Blocks },
  avaliacoesRede: { rotulo: "Avaliações Externas", caminho: "/rede/avaliacoes", icone: FileText },
  // --- Itens da Secretaria (visão AGREGADA da rede, sem PII individual) ---
  // A Secretaria navega por DUAS telas apenas: o Panorama (visão geral) e o
  // Painel da Rede (centro de comando com mapa, metas, vitrine, avaliações e
  // boletim). As demais seções vivem DENTRO dessas duas telas — sem atalhos
  // duplicados na sidebar.
  panoramaRede: { rotulo: "Panorama da Rede", caminho: "/", icone: LayoutDashboard, exato: true },
  painelRede: { rotulo: "Painel da Rede", caminho: "/rede", icone: Landmark, exato: true },
} satisfies Record<string, ItemNav>;

/** Perfil resumido do usuário — decide QUAL sidebar montar. */
interface Perfil {
  /** Admin global (is_global): opera todo o ecossistema. */
  global: boolean;
  /** Secretaria (rede vinculada, não-global): visão agregada da rede. */
  secretaria: boolean;
  /** Gestão (admin/coordenador/global) — o professor é `false` aqui. */
  gestor: boolean;
}

/** Rótulo do Dashboard conforme o perfil — mesma rota "/", foco diferente. */
function rotuloDashboard(p: Perfil): string {
  if (p.global) return "Visão Global";
  if (p.secretaria) return "Panorama da Rede";
  if (p.gestor) return "Dashboard";
  return "Meu Dashboard";
}

/** Sidebar DEDICADA por perfil: a mesma lista de rotas que aquele papel já
 *  podia abrir, mas agrupada, ordenada e nomeada para o trabalho dele. Nenhum
 *  item aqui abre algo que o backend não autorize para o papel — as travas de
 *  rota (App.tsx) e o backend (deps.py) seguem intactos. */
function sidebarDoPerfil(p: Perfil): GrupoNav[] {
  // 👑 Admin Global — saúde do ecossistema + todas as ferramentas de escola.
  if (p.global) return [
    { chave: "estrutura", rotulo: "Estrutura", icone: Building2, itens: [IT.redeGerenciar, IT.escolas, IT.usuarios] },
    { chave: "monitoramento", rotulo: "Monitoramento", icone: Activity, itens: [IT.sessoes] },
    { chave: "desempenho", rotulo: "Desempenho", icone: Trophy, itens: [IT.premiacoes, IT.ranking, IT.comparador] },
    { chave: "inteligencia", rotulo: "Inteligência", icone: Sparkles, itens: [IT.insights, IT.assistente, IT.simulador] },
    { chave: "gestao", rotulo: "Gestão Escolar", icone: Users, itens: [IT.visaoEscola, IT.alunos, IT.turmas, IT.professores] },
    { chave: "plataformas", rotulo: "Plataformas", icone: Blocks, itens: [IT.matific, IT.elefante, IT.livros, IT.importacoes, IT.sincronizacao, IT.diagnostico] },
    { chave: "gamificacao", rotulo: "Gamificação", icone: Award, itens: [IT.conquistas, IT.bibliotecaConquistas] },
    { chave: "conteudo", rotulo: "Avaliações", icone: FileText, itens: [IT.avaliacoesRede] },
    { chave: "relatorios", rotulo: "Relatórios", icone: FileText, itens: [IT.relatorios, IT.painelPublico] },
    { chave: "sistema", rotulo: "Sistema", icone: Settings, itens: [IT.metricas, IT.configuracoes] },
  ];
  // 🏛️ Secretaria — navegação ENXUTA: o Painel da Rede é o centro de comando
  // (mapa, metas, vitrine, avaliações, boletim vivem lá dentro) e o Panorama é a
  // visão geral. Sem atalhos duplicados — tudo o que existia como item aqui já
  // está acessível dentro dessas duas telas (ver relatório). Permissões e
  // blindagem de PII inalteradas (backend: turmas_permitidas=[], etc.).
  if (p.secretaria) return [
    { chave: "principal", rotulo: "Principal", icone: LayoutDashboard, itens: [IT.panoramaRede] },
    { chave: "rede", rotulo: "Rede Municipal", icone: Landmark, itens: [IT.painelRede] },
  ];
  // 🏫 Coordenador — administra a própria escola de ponta a ponta.
  if (p.gestor) return [
    { chave: "desempenho", rotulo: "Desempenho", icone: Trophy, itens: [IT.premiacoes, IT.ranking, IT.comparador] },
    { chave: "inteligencia", rotulo: "Inteligência", icone: Sparkles, itens: [IT.insights, IT.assistente, IT.simulador] },
    { chave: "escola", rotulo: "Minha Escola", icone: School, itens: [IT.visaoEscola, IT.alunos, IT.turmas, IT.professores, IT.usuarios] },
    { chave: "plataformas", rotulo: "Plataformas", icone: Blocks, itens: [IT.matific, IT.elefante, IT.livros, IT.importacoes, IT.sincronizacao, IT.diagnostico] },
    { chave: "gamificacao", rotulo: "Gamificação", icone: Award, itens: [IT.conquistas, IT.bibliotecaConquistas] },
    { chave: "relatorios", rotulo: "Relatórios", icone: FileText, itens: [IT.relatorios, IT.painelPublico] },
    { chave: "config", rotulo: "Configurações", icone: Settings, itens: [IT.metricas, IT.configuracoes] },
  ];
  // 👩‍🏫 Professor — só as turmas dele (o backend filtra por turmas_permitidas).
  return [
    { chave: "turmas", rotulo: "Minhas Turmas", icone: GraduationCap, itens: [IT.meusAlunos] },
    { chave: "desempenho", rotulo: "Desempenho", icone: Trophy, itens: [IT.rankingProf, IT.premiacoes, IT.insights] },
    { chave: "reconhecimento", rotulo: "Reconhecimento", icone: Medal, itens: [IT.bibliotecaConquistas] },
    { chave: "relatorios", rotulo: "Relatórios", icone: FileText, itens: [IT.meusRelatorios] },
  ];
}

/** Todos os itens de menu que o usuário PODE abrir (Dashboard + sidebar do
 *  perfil), achatados — base da busca por páginas. */
function itensNavVisiveis(p: Perfil): ItemNav[] {
  const todos = [
    { ...DASHBOARD, rotulo: rotuloDashboard(p) },
    ...(p.global ? [SECRETARIA] : []),
    ...(p.gestor && !p.secretaria ? [COMECAR] : []),
    ...sidebarDoPerfil(p).flatMap((g) => g.itens),
  ];
  // Remove rotas repetidas (ex.: Panorama da Rede está no topo e no grupo).
  return todos.filter((it, i) => todos.findIndex((x) => x.caminho === it.caminho) === i);
}

const CHAVE_MENU = "constela_menu_abertos";

/** Grupo (da sidebar do perfil) que contém a rota atual — para destacar e
 *  abrir automaticamente o accordion certo. */
function grupoDaRota(grupos: GrupoNav[], pathname: string): string | null {
  for (const grupo of grupos) {
    const bate = grupo.itens.some((it) => {
      // Âncoras (#) nunca casam pelo pathname (que não tem hash) — o grupo abre
      // pelo item de rota irmão. `exato` casa só na igualdade (senão /rede
      // "engoliria" /rede/avaliacoes).
      const base = it.caminho.split("#")[0];
      if (!base) return false;
      if (it.exato) return pathname === base;
      return pathname === base || (base !== "/" && pathname.startsWith(base + "/"));
    });
    if (bate) return grupo.chave;
  }
  return null;
}

// Títulos de rotas que não estão (com esse nome) no catálogo de itens — usados
// na trilha/contexto do topo (PRD §11).
const TITULOS_ESPECIAIS: Record<string, string> = {
  "/": "Início",
  "/comecar": "Comece aqui",
  "/rede": "Painel da Rede",
  "/rede/gerenciar": "Gerenciar Rede",
  "/rede/avaliacoes": "Avaliações Externas",
  // Drill-down do Panorama (botão "Ver ranking completo"), não item de sidebar —
  // a navegação da Secretaria segue enxuta por decisão do dono.
  "/rede/ranking": "Ranking da Rede",
  "/usuarios": "Usuários e acessos",
};

/** Título legível da rota atual (para a trilha do topo). Casa primeiro o
 *  caminho EXATO — assim /conquistas/biblioteca não vira "Conquistas" — e só
 *  depois cai nos detalhes (perfil de aluno, turma) e no prefixo. */
function tituloDaRota(pathname: string): string {
  if (TITULOS_ESPECIAIS[pathname]) return TITULOS_ESPECIAIS[pathname];
  const exato = Object.values(IT).find((i) => i.caminho === pathname);
  if (exato) return exato.rotulo;
  if (pathname.startsWith("/alunos/")) return "Perfil do aluno";
  if (pathname.startsWith("/turmas/")) return "Detalhe da turma";
  const prefixo = Object.values(IT).find((i) => pathname.startsWith(i.caminho + "/"));
  return prefixo?.rotulo ?? "";
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
  // Secretaria = tem rede vinculada e NÃO é admin global: some das operações de escola.
  const secretaria = !global && usuario?.rede_id != null;

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
  const paginas: Opcao[] = consulta.length < 1 ? [] : itensNavVisiveis({ global, secretaria, gestor })
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
  tipo: string;
  severidade: string;
  titulo: string;
  rota: string | null;
  autor: string | null;
  data: string;
  lida: boolean;
}

/** Notificações acionáveis por perfil (Fase 2). O sino mostra um BADGE de
 *  não-lidas (buscado em segundo plano) e cada aviso LEVA à tela de ação. O
 *  feed é escolhido pelo perfil no servidor (professor: suas turmas; Secretaria:
 *  agregado da rede, sem PII) — o front só consome a rota que o backend mandou. */
function Notificacoes() {
  const navegar = useNavigate();
  const [aberto, setAberto] = useState(false);
  const [naoLidas, setNaoLidas] = useState(0);
  const [itens, setItens] = useState<Notificacao[]>([]);
  const [carregando, setCarregando] = useState(false);
  const caixa = useRef<HTMLDivElement | null>(null);

  // Badge: busca o contador em segundo plano (~60s), independente do popover
  // (mesma cadência leve do heartbeat; nunca bate com a aba oculta).
  useEffect(() => {
    let vivo = true;
    const buscar = () => {
      if (document.visibilityState === "hidden") return;
      api<{ nao_lidas: number }>("/notificacoes/contador")
        .then((r) => { if (vivo) setNaoLidas(r.nao_lidas); })
        .catch(() => {});
    };
    buscar();
    const timer = window.setInterval(buscar, 60_000);
    const aoVisivel = () => { if (document.visibilityState === "visible") buscar(); };
    document.addEventListener("visibilitychange", aoVisivel);
    return () => {
      vivo = false;
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", aoVisivel);
    };
  }, []);

  useEffect(() => {
    function fechar(evento: MouseEvent) {
      if (caixa.current && !caixa.current.contains(evento.target as Node)) setAberto(false);
    }
    document.addEventListener("mousedown", fechar);
    return () => document.removeEventListener("mousedown", fechar);
  }, []);

  async function alternar() {
    const abrindo = !aberto;
    setAberto(abrindo);
    if (!abrindo) return;
    setCarregando(true);
    try {
      const lista = await api<Notificacao[]>("/notificacoes");
      setItens(lista);
      if (lista.some((n) => !n.lida)) {
        await api("/notificacoes/marcar-lidas", { method: "POST" }).catch(() => {});
      }
      setNaoLidas(0); // abrir = visto tudo
    } catch {
      setItens([]);
    } finally {
      setCarregando(false);
    }
  }

  function irPara(item: Notificacao) {
    setAberto(false);
    if (item.rota) navegar(item.rota);
  }

  return (
    <div ref={caixa} className="relative">
      <button
        aria-label={naoLidas > 0 ? `Notificações (${naoLidas} não lidas)` : "Notificações"}
        className="relative rounded-lg p-2 text-zinc-600 hover:bg-zinc-100 dark:text-zinc-300 dark:hover:bg-zinc-800"
        onClick={alternar}
      >
        <Bell size={17} />
        {naoLidas > 0 && (
          <span className="absolute right-0.5 top-0.5 flex h-4 min-w-[16px] items-center justify-center rounded-full bg-rose-500 px-1 text-[10px] font-semibold leading-none text-white">
            {naoLidas > 9 ? "9+" : naoLidas}
          </span>
        )}
      </button>
      {aberto && (
        <div className="absolute right-0 top-full z-40 mt-1 w-80 overflow-hidden rounded-lg border border-zinc-200 bg-white shadow-lg dark:border-zinc-700 dark:bg-zinc-900">
          <p className="border-b border-zinc-200 px-3 py-2 text-xs font-semibold uppercase tracking-wide text-zinc-400 dark:border-zinc-800">
            Notificações
          </p>
          {carregando ? (
            <p className="px-3 py-3 text-sm text-zinc-400">Carregando…</p>
          ) : itens.length === 0 ? (
            <p className="px-3 py-3 text-sm text-zinc-400">Nenhuma novidade por enquanto.</p>
          ) : (
            <ul className="max-h-80 overflow-y-auto">
              {itens.map((item) => (
                <li key={item.id}>
                  <button
                    type="button"
                    onClick={() => irPara(item)}
                    disabled={!item.rota}
                    className={`flex w-full items-start gap-2.5 border-b border-zinc-100 px-3 py-2 text-left last:border-0 dark:border-zinc-800/60 ${
                      item.rota ? "hover:bg-zinc-50 dark:hover:bg-zinc-800/50" : "cursor-default"
                    }`}
                  >
                    <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${
                      item.severidade === "critico" ? "bg-red-500"
                        : item.severidade === "aviso" ? "bg-amber-500" : "bg-indigo-400"
                    }`} />
                    <span className="min-w-0 flex-1">
                      <span className={`block text-sm ${item.lida ? "" : "font-medium"}`}>{item.titulo}</span>
                      <span className="block text-xs text-zinc-400">
                        {item.autor ? `${item.autor} · ` : ""}{dataHora(item.data)}
                      </span>
                    </span>
                    {item.rota && (
                      <ChevronRight size={14} className="mt-0.5 shrink-0 text-zinc-300 dark:text-zinc-600" aria-hidden />
                    )}
                  </button>
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
  // Link externo (ex.: Suporte → Google Drive): abre em nova aba, nunca fica
  // "ativo" e não interfere no roteamento interno.
  if (item.externo) {
    return (
      <a
        href={item.caminho}
        target="_blank"
        rel="noopener noreferrer"
        onClick={aoNavegar}
        className="flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium text-zinc-600 transition-colors hover:bg-zinc-100/70 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-800/60 dark:hover:text-zinc-100"
      >
        <item.icone size={subitem ? 15 : 16} strokeWidth={2} className="shrink-0" />
        <span className="flex-1 truncate">{item.rotulo}</span>
        <ExternalLink size={13} strokeWidth={2} className="shrink-0 text-zinc-400" aria-hidden />
      </a>
    );
  }
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
  const rede = Boolean(usuario?.is_global) || usuario?.rede_id != null;
  // Secretaria = tem rede vinculada e NÃO é admin global.
  const secretaria = !usuario?.is_global && usuario?.rede_id != null;
  const perfil: Perfil = { global: Boolean(usuario?.is_global), secretaria, gestor };
  // "Comece aqui" só aparece enquanto a escola não foi configurada; depois da
  // config inicial ele some (novas importações passam a ser por "Importações").
  const { precisaConfigurar } = useOnboarding();
  const grupos = sidebarDoPerfil(perfil);
  const ativo = grupoDaRota(grupos, pathname);
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

  // PRIMEIRO ACESSO: enquanto a escola não foi configurada, o único caminho é o
  // "Comece aqui" — nada de Dashboard, Desempenho, Gestão, Plataformas etc. Não
  // faz sentido abrir as demais telas antes de conectar Lista Piloto/Elefante/
  // Matific. Depois que configura, `precisaConfigurar` vira falso e o menu
  // completo aparece. (Vale só para quem opera a escola: admin/coordenador; a
  // Secretaria e o professor entram numa escola já preparada.)
  if (gestor && !secretaria && precisaConfigurar) {
    return (
      <nav className="flex-1 space-y-1 overflow-y-auto px-3 py-4">
        <LinkMenu item={COMECAR} aoNavegar={aoNavegar} />
        <div className="mt-2 border-t border-zinc-200 pt-2 dark:border-zinc-800">
          <LinkMenu item={SUPORTE} aoNavegar={aoNavegar} />
        </div>
      </nav>
    );
  }

  return (
    <nav className="flex-1 space-y-1 overflow-y-auto px-3 py-4">
      {/* A Secretaria tem "Panorama da Rede" e "Painel da Rede" nos grupos
          (Principal / Rede Municipal); os demais perfis usam o item de topo. */}
      {!secretaria && <LinkMenu item={{ ...DASHBOARD, rotulo: rotuloDashboard(perfil) }} aoNavegar={aoNavegar} />}
      {rede && !secretaria && <LinkMenu item={SECRETARIA} aoNavegar={aoNavegar} />}

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

      {/* Suporte: fica destacado no rodapé, separado dos grupos, para todos os
          papéis (professor, coordenador, secretaria, admin). */}
      <div className="mt-2 border-t border-zinc-200 pt-2 dark:border-zinc-800">
        <LinkMenu item={SUPORTE} aoNavegar={aoNavegar} />
      </div>
    </nav>
  );
}

/** Um item na barra recolhida (só ícone, nome no tooltip). */
function IconeMenu({ item, atalho }: { item: ItemNav; atalho?: () => void }) {
  const classe = "flex justify-center rounded-lg p-2.5 transition-colors";
  const inativo = "text-zinc-500 hover:bg-zinc-100 hover:text-zinc-800 dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-zinc-100";
  if (item.externo) {
    return (
      <a
        href={item.caminho}
        target="_blank"
        rel="noopener noreferrer"
        title={item.rotulo}
        aria-label={item.rotulo}
        onClick={atalho}
        className={`${classe} ${inativo}`}
      >
        <item.icone size={18} strokeWidth={2} />
      </a>
    );
  }
  return (
    <NavLink
      to={item.caminho}
      end={item.exato}
      title={item.rotulo}
      aria-label={item.rotulo}
      onClick={atalho}
      className={({ isActive }) =>
        `${classe} ${isActive
          ? "bg-indigo-50 text-indigo-700 dark:bg-indigo-500/10 dark:text-indigo-300"
          : "text-zinc-500 hover:bg-zinc-100 hover:text-zinc-800 dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-zinc-100"}`
      }
    >
      <item.icone size={18} strokeWidth={2} />
    </NavLink>
  );
}

/** Navegação RECOLHIDA (só ícones, desktop) — PRD §14. Achata a sidebar do
 *  perfil numa lista de ícones: todos os destinos que o perfil já podia abrir
 *  seguem a um clique, com o nome no tooltip. Sem grupos/accordion (não cabem
 *  na barra estreita), mas nada some — é só a versão compacta do mesmo menu. */
function NavegacaoRail() {
  const { usuario } = useApp();
  const perfil: Perfil = {
    global: Boolean(usuario?.is_global),
    secretaria: !usuario?.is_global && usuario?.rede_id != null,
    gestor: Boolean(usuario?.is_global) || ["admin", "coordenador"].includes(usuario?.cargo ?? ""),
  };
  const bruto: ItemNav[] = [
    { ...DASHBOARD, rotulo: rotuloDashboard(perfil) },
    ...(perfil.global ? [SECRETARIA] : []),
    ...sidebarDoPerfil(perfil).flatMap((g) => g.itens),
  ];
  // Sem rotas repetidas (ex.: Panorama da Rede no topo e no grupo Principal).
  const itens = bruto.filter((it, i) => bruto.findIndex((x) => x.caminho === it.caminho) === i);
  return (
    <nav className="flex-1 space-y-1 overflow-y-auto px-2 py-3">
      {itens.map((item) => (
        <IconeMenu key={item.caminho} item={item} />
      ))}
      <div className="mt-2 border-t border-zinc-200 pt-2 dark:border-zinc-800">
        <IconeMenu item={SUPORTE} />
      </div>
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

/** Trilha/contexto no topo (PRD §11): "onde estou". Começa no Dashboard do
 *  perfil e mostra a página atual. Só no desktop — no celular o próprio título
 *  da página (dentro do conteúdo) já orienta, e o topo é curto. */
function Trilha() {
  const { pathname } = useLocation();
  const { usuario } = useApp();
  const perfil: Perfil = {
    global: Boolean(usuario?.is_global),
    secretaria: !usuario?.is_global && usuario?.rede_id != null,
    gestor: Boolean(usuario?.is_global) || ["admin", "coordenador"].includes(usuario?.cargo ?? ""),
  };
  const titulo = tituloDaRota(pathname);
  const naHome = pathname === "/";
  return (
    <nav aria-label="Trilha de navegação" className="hidden min-w-0 items-center gap-1.5 text-sm lg:flex">
      <NavLink
        to="/"
        className={({ isActive }) =>
          `shrink-0 ${isActive
            ? "font-medium text-zinc-800 dark:text-zinc-200"
            : "text-zinc-500 hover:text-zinc-800 dark:text-zinc-400 dark:hover:text-zinc-200"}`
        }
      >
        {rotuloDashboard(perfil)}
      </NavLink>
      {!naHome && titulo && (
        <>
          <ChevronRight size={14} className="shrink-0 text-zinc-300 dark:text-zinc-600" aria-hidden />
          <span className="truncate font-medium text-zinc-800 dark:text-zinc-200">{titulo}</span>
        </>
      )}
    </nav>
  );
}

/** Iniciais do nome (para o avatar): 1ª letra do primeiro e do último nome. */
function iniciais(nome?: string): string {
  const partes = (nome ?? "").trim().split(/\s+/).filter(Boolean);
  if (partes.length === 0) return "?";
  const primeira = partes[0][0] ?? "";
  const ultima = partes.length > 1 ? partes[partes.length - 1][0] ?? "" : "";
  return (primeira + ultima).toUpperCase();
}

/** Nome amigável do perfil (cabeçalho do menu do usuário). */
function rotuloPerfil(u: { is_global?: boolean; rede_id?: number | null; cargo?: string } | null | undefined): string {
  if (!u) return "";
  if (u.is_global) return "Admin Global";
  if (u.rede_id != null) return "Secretaria";
  if (u.cargo === "coordenador") return "Coordenação";
  if (u.cargo === "admin") return "Administração";
  return "Professor(a)";
}

/** Menu do usuário (avatar → conta + sair). Reúne identidade, atalho para a
 *  própria conta e logout num só lugar (PRD §11). O atalho aponta para
 *  /minha-conta (autoatendimento, reusa /auth/me) — funciona para QUALQUER
 *  perfil, inclusive a Secretaria, que não tem escola e não abre /usuarios. */
function MenuUsuario() {
  const { usuario, sair } = useApp();
  const [aberto, setAberto] = useState(false);
  const caixa = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    function fechar(evento: MouseEvent) {
      if (caixa.current && !caixa.current.contains(evento.target as Node)) setAberto(false);
    }
    document.addEventListener("mousedown", fechar);
    return () => document.removeEventListener("mousedown", fechar);
  }, []);

  return (
    <div className="relative" ref={caixa}>
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={aberto}
        aria-label="Menu do usuário"
        onClick={() => setAberto((a) => !a)}
        className="flex items-center gap-2 rounded-lg p-1 pr-2 text-sm text-zinc-600 hover:bg-zinc-100 dark:text-zinc-300 dark:hover:bg-zinc-800"
      >
        <span className="grid h-8 w-8 place-items-center rounded-full bg-indigo-100 text-xs font-semibold text-indigo-700 dark:bg-indigo-500/20 dark:text-indigo-300">
          {iniciais(usuario?.nome)}
        </span>
        <span className="hidden max-w-[140px] truncate sm:block">{usuario?.nome}</span>
        <ChevronDown
          size={14}
          className={`hidden shrink-0 text-zinc-400 transition-transform sm:block ${aberto ? "rotate-180" : ""}`}
          aria-hidden
        />
      </button>

      {aberto && (
        <div
          role="menu"
          className="absolute right-0 z-40 mt-2 w-60 overflow-hidden rounded-xl border border-zinc-200 bg-white shadow-lg dark:border-zinc-800 dark:bg-zinc-900"
        >
          <div className="border-b border-zinc-100 px-4 py-3 dark:border-zinc-800">
            <p className="truncate text-sm font-semibold text-zinc-900 dark:text-zinc-100">{usuario?.nome}</p>
            <p className="mt-0.5 truncate text-xs text-zinc-500 dark:text-zinc-400">{rotuloPerfil(usuario)}</p>
          </div>
          <div className="p-1">
            {/* Autoatendimento: SÓ a própria conta (/minha-conta, reusa /auth/me),
                para qualquer perfil — inclusive Secretaria. A GESTÃO de usuários
                (/usuarios) segue na sidebar, exclusiva de coordenador/admin. */}
            <NavLink
              to="/minha-conta"
              role="menuitem"
              onClick={() => setAberto(false)}
              className="flex items-center gap-3 rounded-lg px-3 py-2 text-sm text-zinc-700 hover:bg-zinc-100 dark:text-zinc-200 dark:hover:bg-zinc-800"
            >
              <UserCog size={16} className="shrink-0 text-zinc-400" />
              <span className="truncate">Minha conta</span>
            </NavLink>
            <button
              type="button"
              role="menuitem"
              onClick={() => { setAberto(false); sair(); }}
              className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm text-rose-600 hover:bg-rose-50 dark:text-rose-400 dark:hover:bg-rose-500/10"
            >
              <LogOut size={16} className="shrink-0" />
              <span>Sair</span>
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

const CHAVE_RECOLHIDO = "constela_menu_recolhido";

export default function Layout() {
  const { usuario, escolas, escolaId, selecionarEscola, tema, alternarTema } = useApp();
  // Secretaria (rede vinculada, não-global): o seletor do topo é o CONTEXTO da
  // visualização — "Toda a Rede Municipal" (padrão) ou uma escola específica.
  const secretaria = !usuario?.is_global && usuario?.rede_id != null;
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
  useHeartbeat();      // marca presença enquanto o app está aberto (Sessões Ativas)

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
      {/* Sidebar fixa (desktop) — recolhível para SÓ ÍCONES (PRD §14): a barra
          fica estreita mas todos os destinos continuam a um clique, com o nome
          no tooltip; não some a navegação, só encolhe. */}
      <aside
        className={`fixed inset-y-0 left-0 z-30 hidden flex-col border-r border-zinc-200 bg-white pl-safe transition-[width] duration-200 dark:border-zinc-800 dark:bg-zinc-900 lg:flex ${
          recolhido ? "w-16" : "w-60"
        }`}
      >
        {recolhido ? (
          <div className="flex justify-center py-3">
            <button
              aria-label="Expandir menu"
              title="Expandir menu"
              className="rounded-lg p-2 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-600 dark:hover:bg-zinc-800 dark:hover:text-zinc-300"
              onClick={alternarRecolhido}
            >
              <PanelLeftOpen size={18} />
            </button>
          </div>
        ) : (
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
        )}
        {recolhido ? <NavegacaoRail /> : <Navegacao />}
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

      <div className={recolhido ? "lg:pl-16" : "lg:pl-60"}>
        {/* Respiro no topo: base de 1.5rem + a área segura do notch (o antigo
            `pt-safe` zerava o topo em telas sem notch, colando a barra de
            pesquisa/header no topo). Só o topo muda; a base (pb) segue igual. */}
        <header
          style={{ paddingTop: "calc(env(safe-area-inset-top) + 1.5rem)" }}
          className="sticky top-0 z-20 flex items-center gap-3 border-b border-zinc-200 bg-white/80 px-4 pb-4 pr-safe backdrop-blur dark:border-zinc-800 dark:bg-zinc-950/80 lg:px-8"
        >
          <button
            aria-label="Abrir menu"
            className="rounded-lg p-2 text-zinc-600 hover:bg-zinc-100 dark:text-zinc-300 dark:hover:bg-zinc-800 lg:hidden"
            onClick={() => setMenuAberto(true)}
          >
            <Menu size={18} />
          </button>
          <Trilha />

          <PesquisaGlobal />

          {/* Seletor de CONTEXTO (todas as telas). Para a Secretaria é o switcher
              global: "Toda a Rede Municipal" (padrão) + as escolas da rede — o
              Dashboard inteiro acompanha o que estiver selecionado. Para os
              demais perfis é a troca rápida de escola de sempre. */}
          {(secretaria || escolas.length > 0) && (
            <label className="ml-auto flex items-center gap-2 text-sm">
              {secretaria
                ? <Landmark size={14} className="text-zinc-400" />
                : <ArrowLeftRight size={14} className="text-zinc-400" />}
              <select
                aria-label={secretaria ? "Contexto de visualização" : "Escola selecionada"}
                className="max-w-[180px] rounded-lg border border-zinc-300 bg-white px-2 py-1.5 text-sm dark:border-zinc-700 dark:bg-zinc-900 sm:max-w-none"
                value={escolaId ?? ""}
                onChange={(evento) => {
                  const v = evento.target.value;
                  selecionarEscola(v === "" ? null : Number(v));
                }}
              >
                {secretaria && <option value="">🏛️ Toda a Rede Municipal</option>}
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

          <MenuUsuario />
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
