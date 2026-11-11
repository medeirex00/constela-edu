import {
  Activity,
  Award,
  Bell,
  RefreshCw,
  Blocks,
  BookOpen,
  BookOpenCheck,
  Bot,
  Building,
  Building2,
  Cable,
  Calculator,
  ChartLine,
  ChevronDown,
  ChevronUp,
  ChevronRight,
  ChevronsUpDown,
  ClipboardCheck,
  ExternalLink,
  FileSearch,
  FileText,
  FlaskConical,
  Lightbulb,
  GitCompareArrows,
  GraduationCap,
  Landmark,
  LayoutDashboard,
  Library,
  LifeBuoy,
  ListOrdered,
  LogOut,
  Medal,
  Menu,
  Microscope,
  MonitorPlay,
  Moon,
  PanelLeftClose,
  PanelLeftOpen,
  Radar,
  Rocket,
  School,
  Search,
  Settings,
  ShieldCheck,
  SlidersHorizontal,
  SquarePen,
  Star,
  Sun,
  Trophy,
  Upload,
  UserCog,
  UserSearch,
  Users,
  X,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { Fragment, Suspense, useEffect, useId, useRef, useState } from "react";
import type { KeyboardEvent as ReactKeyboardEvent, MouseEvent as ReactMouseEvent, ReactNode } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate, useNavigationType } from "react-router-dom";

import { useApp } from "../context/AppContext";
import { useImportacaoLote } from "../context/ImportacaoLoteContext";
import { useApi } from "../hooks/useApi";
import { useBordasDaRolagem } from "../hooks/useBordasDaRolagem";
import { rotuloDasPlataformas, useModulos } from "../hooks/useModulos";
import { api } from "../lib/api";
import { useHeartbeat } from "../hooks/useHeartbeat";
import { useOnboarding } from "../hooks/useOnboarding";
import { usePerfil } from "../hooks/usePerfil";
import { useAtalhosGlobais } from "../lib/atalhos";
import { bimestreEmCurso, useCalendarioBimestres, type CalendarioDoAno } from "../lib/calendarioBimestres";
import { dataHora } from "../lib/formato";
import { normalizar } from "../lib/nomes";
import { podeAbrirRota } from "../lib/rotasGuardadas";
import { Logo, LogoHorizontal } from "./Logo";
import { Avatar, Botao, BotaoIcone, Carregando, IconePastel } from "./ui";

/** Seção da barra lateral (identidade v2): o rótulo em caixa alta sobre os grupos. Cada
 *  PERFIL tem as suas (`secoesDoPerfil`) — as fixas "Projeto"/"Gestão" não diziam nada à
 *  Secretaria nem à professora. */
interface SecaoNav {
  chave: string;
  rotulo: string;
}

interface ItemNav {
  rotulo: string;
  /** Rota interna. Pode trazer a ABA na consulta (`/rede/analise?ver=relacao`): o
   *  item fica ativo só naquela aba (`itemAtivo`). */
  caminho: string;
  icone: LucideIcon;
  /** Destaca só no match EXATO (rota pai que tem sub-rotas próprias). */
  exato?: boolean;
  /** Outras rotas (endereço exato, ou com parâmetro: `/rede/escolas/:escolaId`) que são
   *  "dentro" deste item sem estar no caminho dele: o item fica aceso nelas e a trilha as
   *  põe no grupo dele. Ex.: o Admin Global chega às telas da Secretaria (Escolas,
   *  Avaliações externas...) pelos links da "Visão da rede", sem item próprio no menu dele. */
  filhas?: string[];
  /** Link externo (abre em nova aba) em vez de rota interna. */
  externo?: boolean;
  /** Outros nomes pelos quais a pesquisa global também acha a página (o nome antigo de
   *  um item renomeado, a sigla, o que a pessoa digitaria). Não aparece em lugar nenhum. */
  busca?: string;
  /** A pesquisa também acha a página pelas plataformas CONTRATADAS (o nome e a matéria:
   *  "Elefante", "leitura", "Matific", "matemática"): `filtrarPorModulos` acrescenta só as da
   *  rede (nada da que ela não tem). */
  buscaComPlataformas?: boolean;
}

interface GrupoNav {
  chave: string;
  /** Nome do acordeão — e o nível do meio da trilha para os itens dele. */
  rotulo: string;
  icone: LucideIcon;
  itens: ItemNav[];
  /** Chave da seção (de `secoesDoPerfil`) em que o grupo aparece. */
  secao: string;
  /** Itens SOLTOS: aparecem direto na seção, sem o acordeão. O rótulo do grupo não
   *  aparece (a trilha usa o da seção). Grupo que fica com UM item também é desenhado
   *  solto (`ehSolto`). */
  solto?: boolean;
  /** Acordeão que nasce ABERTO enquanto o usuário não escolheu abrir ou fechar aquele
   *  grupo (o do trabalho diário do perfil). Escolhido, vale a escolha dele. */
  inicialAberto?: boolean;
}

// Página inicial ("/"): mora no 1º grupo solto da 1ª seção de cada perfil, com o nome que
// o perfil dá a ela (`rotuloDashboard`). Decisão D4 (referência aprovada pelo dono):
// "Dashboard"/"Meu Dashboard" passam a "Visão geral"; a rota "/" não muda e a pesquisa
// ainda acha pelos nomes antigos.
const DASHBOARD: ItemNav = {
  rotulo: "Visão geral", caminho: "/", icone: LayoutDashboard, exato: true, busca: "dashboard início painel visão geral resumo",
};
// "Comece aqui": assistente da configuração inicial da escola. No menu SÓ no primeiro
// acesso (é o único item, também na barra recolhida); depois, a pesquisa e a tela
// Integrações ainda levam a ele.
const COMECAR: ItemNav = {
  rotulo: "Comece aqui", caminho: "/comecar", icone: Rocket, busca: "configuração inicial primeiros passos onboarding",
};
// "Suporte": página interna (/suporte) com as dúvidas comuns do perfil, a
// explicação e o exemplo da pontuação, a orientação de sincronização e o link
// para a pasta dos guias em PDF no Google Drive. Fica no rodapé da barra e
// aparece para TODOS os papéis.
const SUPORTE: ItemNav = { rotulo: "Suporte", caminho: "/suporte", icone: LifeBuoy, busca: "ajuda dúvidas guias" };

// ── Catálogo de itens de menu ────────────────────────────────────────────
// Cada item aponta para uma ROTA que já existe. As sidebars por perfil (logo
// abaixo) apenas ESCOLHEM e ORGANIZAM estes itens conforme a função de cada
// papel — nenhuma permissão nova nasce aqui. O backend continua sendo o portão
// real de cada rota (deps.py): reorganizar o menu não expõe nada, só arruma o
// que aquele perfil já podia abrir. Trocar de perfil troca a ESTRUTURA inteira
// (grupos, ordem, rótulos), não só a visibilidade de um botão.
//
// Ícones: sem repetição DENTRO do menu de um perfil — a barra recolhida mostra só o
// ícone, e dois iguais lado a lado viravam adivinhação (Conquistas × Premiações,
// Elefante × Catálogo, Painel × Ranking da Rede, Usuários × Minha conta...).
const IT = {
  premiacoes: { rotulo: "Premiações", caminho: "/premiacoes", icone: Award, busca: "certificados pódio premiação bimestre" },
  // Ranking Geral reúne Geral/Leitura/Matemática/Evolução num seletor interno.
  ranking: { rotulo: "Ranking Geral", caminho: "/ranking", icone: Trophy, busca: "classificação leitura matemática evolução" },
  rankingProf: { rotulo: "Ranking", caminho: "/ranking", icone: Trophy, busca: "classificação leitura matemática evolução" },
  comparador: { rotulo: "Comparador", caminho: "/comparador", icone: GitCompareArrows, busca: "comparar alunos turmas" },
  insights: { rotulo: "Insights", caminho: "/insights", icone: Lightbulb, busca: "inteligência pedagógica alertas acompanhamento" },
  assistente: { rotulo: "Assistente", caminho: "/assistente", icone: Bot, busca: "assistente pedagógico ia perguntas" },
  simulador: { rotulo: "Simulador", caminho: "/simulador", icone: FlaskConical, busca: "simulação nota pesos" },
  visaoEscola: { rotulo: "Visão da Escola", caminho: "/escola", icone: Building2, busca: "resumo da escola análise da escola" },
  alunos: { rotulo: "Alunos", caminho: "/alunos", icone: GraduationCap, busca: "estudantes crianças fundir duplicatas transferido" },
  meusAlunos: { rotulo: "Meus Alunos", caminho: "/alunos", icone: GraduationCap, busca: "alunos estudantes crianças" },
  turmas: { rotulo: "Turmas", caminho: "/turmas", icone: Users, busca: "classes salas séries" },
  professores: { rotulo: "Professores", caminho: "/professores", icone: School, busca: "professoras docentes" },
  // ShieldCheck (contas e acessos): o UserCog fica só com "Minha conta", no menu do usuário.
  usuarios: { rotulo: "Usuários", caminho: "/usuarios", icone: ShieldCheck, busca: "acessos contas senha vincular turmas" },
  matific: { rotulo: "Matific", caminho: "/matific", icone: Calculator, busca: "matemática plataforma" },
  elefante: { rotulo: "Elefante Letrado", caminho: "/elefante", icone: BookOpen, busca: "leitura plataforma livros lidos" },
  livros: { rotulo: "Catálogo de Livros", caminho: "/livros", icone: Library, busca: "acervo livros nível dificuldade" },
  // "Importações" (upload manual) e "Diagnóstico Elefante" (sonda técnica da API)
  // são ferramentas AVANÇADAS: continuam existindo (rotas, permissões e backend
  // intactos) e ficam no menu do Admin Global; a escola chega nelas por links
  // dentro de "Integrações" — a tela de status que responde "os dados estão
  // atualizados?".
  importacoes: { rotulo: "Importações", caminho: "/importacoes", icone: Upload, busca: "importar dados upload planilha" },
  sincronizacao: { rotulo: "Integrações", caminho: "/sincronizacao", icone: RefreshCw, busca: "importar dados sincronização sincronizar" },
  // Fila de linhas de importação/sincronização cuja identidade o backend não
  // decidiu com segurança: o gestor escolhe o aluno (ou cria/descarta). É a
  // contraparte humana das "pendências" que Integrações anuncia — fica ao lado dela.
  revisoes: { rotulo: "Revisões de identidade", caminho: "/revisoes-identidade", icone: UserSearch, busca: "pendências contas vincular aluno" },
  diagnostico: { rotulo: "Diagnóstico Elefante", caminho: "/diagnostico-elefante", icone: Radar, busca: "diagnóstico da integração sonda api" },
  conquistas: { rotulo: "Conquistas", caminho: "/conquistas", icone: Star, exato: true, busca: "medalhas mural gamificação" },
  bibliotecaConquistas: { rotulo: "Biblioteca de Conquistas", caminho: "/conquistas/biblioteca", icone: Medal, busca: "medalhas gamificação" },
  // Editor das medalhas da escola. A coordenação grava as definições (o backend
  // libera admin e coordenador) mas não abre Configurações Gerais, onde ficava o
  // único caminho até aqui — ganha item próprio em "Regras de pontuação".
  editorConquistas: { rotulo: "Editar conquistas", caminho: "/configuracoes/conquistas", icone: SquarePen, busca: "medalhas gamificação" },
  // UMA entrada para toda a área. "Por período" é um TIPO de relatório e vive
  // numa aba dentro da página (ver `pages/RelatoriosArea.tsx`), não aqui ao
  // lado — quem procura um relatório não deve ter de adivinhar o módulo.
  // Sem `exato`: o item fica marcado também em /relatorios/periodo, que é a
  // mesma área.
  relatorios: { rotulo: "Relatórios", caminho: "/relatorios", icone: FileText, busca: "boletim certificados por período" },
  meusRelatorios: { rotulo: "Meus Relatórios", caminho: "/relatorios", icone: FileText, busca: "relatórios certificados por período" },
  painelPublico: { rotulo: "Painel Público", caminho: "/painel-publico", icone: MonitorPlay, busca: "telão tv vitrine" },
  // /metricas: decisão D4 — "Métricas" (Admin Global, com os editores da régua) e
  // "Pontuação" (escola, só leitura) passaram a "Critérios" no menu, como na referência
  // aprovada. Um item só (eram dois idênticos): a PROMESSA de cada perfil (editar ×
  // entender) está na própria página, e os nomes antigos seguem na pesquisa.
  criterios: { rotulo: "Critérios", caminho: "/metricas", icone: SlidersHorizontal, busca: "métricas pontuação pesos régua" },
  // Ranking de ESCOLAS (índice per capita da rede); o nome acompanha o cabeçalho da
  // página ("Ranking da Rede").
  rankingEscolas: { rotulo: "Ranking da Rede", caminho: "/rede/ranking", icone: ListOrdered, busca: "ranking das escolas índice" },
  configuracoes: { rotulo: "Configurações Gerais", caminho: "/configuracoes", icone: Settings, busca: "cor brasão logo backup assistente ia" },
  escolas: { rotulo: "Escolas", caminho: "/escolas", icone: Building, busca: "unidades cadastro de escolas" },
  sessoes: { rotulo: "Sessões Ativas", caminho: "/sessoes", icone: Activity, busca: "online presença monitoramento" },
  redeGerenciar: { rotulo: "Gerenciar Rede", caminho: "/rede/gerenciar", icone: Blocks, busca: "redes municípios secretarias cadastro" },
  // Painel da Rede (/rede): metas, vitrine pública, boletim e mapa. Mesmo nome que a
  // trilha e o h1 dão a /rede; a pesquisa ainda acha pelo nome antigo ("Secretaria").
  painelRede: { rotulo: "Painel da Rede", caminho: "/rede", icone: Landmark, exato: true, busca: "secretaria seduc metas vitrine pública mapa boletim" },
  // A área de rastreabilidade (/rede/avaliacoes: o detalhe e o arquivo de cada número; para
  // o global, também a importação). Para a Secretaria ela é o detalhe das Avaliações externas
  // (uma das `filhas` dela), com o h1 de sempre, "Fontes dos indicadores".
  importacoesFontes: { rotulo: "Importações e fontes", caminho: "/rede/avaliacoes", icone: FileSearch, busca: "importar indicadores oficiais fontes dos indicadores ideb saresp ica" },
  // --- Secretaria: TRÊS áreas (DESENHO3 §1) ---
  // O Panorama da Rede (a página inicial, `inicioDoPerfil`), as Escolas (todas, a comparação
  // e a ficha de cada uma) e as Avaliações externas. Tudo agregado por escola, sem dado
  // individual de criança (o backend é a trava). As outras telas da rede (Escolas em
  // acompanhamento, Relatórios, Painel da Rede, Análises avançadas) continuam existindo, com
  // as mesmas guardas, mas saíram do menu dela; as que ficam "dentro" de uma área (o detalhe
  // do uso, o Ranking da Rede, a Visão da Escola, os arquivos oficiais) são `filhas` dela.
  // A pesquisa acha cada área também pelos nomes antigos que levam a ela.
  escolasDaRede: {
    rotulo: "Escolas", caminho: "/rede/escolas", icone: School,
    // A ficha (/rede/escolas/:escolaId) acende pelo caminho (sub-rota); o Ranking da Rede e a
    // Visão da Escola (as turmas de uma escola) são abertos a partir daqui.
    filhas: ["/rede/ranking", "/escola"],
    busca: "escolas da rede todas as escolas comparar escolas comparação comparativo lado a lado ficha da escola "
      + "evolução ranking da rede índice análise da escola visão da escola turmas",
    buscaComPlataformas: true,
  },
  avaliacoesExternas: {
    rotulo: "Avaliações externas", caminho: "/rede/avaliacoes-externas", icone: ClipboardCheck,
    // Os arquivos oficiais de cada número (/rede/avaliacoes) são o detalhe desta área.
    filhas: ["/rede/avaliacoes"],
    busca: "ideb saeb saresp ica iee indicadores oficiais avaliações oficiais edições série histórica metas "
      + "resultados fontes dos indicadores arquivos oficiais",
  },
  // --- Admin Global (grupo "Redes e municípios") ---
  // A MESMA tela do Panorama da Secretaria, com o seletor de rede. As telas da Secretaria
  // abrem para o global pelos links dela (sem item próprio no menu dele): ficam "dentro" da
  // Visão da rede — o item acende nelas (a ficha de cada escola também) e a trilha diz
  // "Redes e municípios".
  visaoRede: {
    rotulo: "Visão da rede", caminho: "/rede/visao", icone: ChartLine,
    filhas: ["/rede/acompanhamento", "/rede/escolas", "/rede/escolas/:escolaId", "/rede/avaliacoes-externas",
      "/rede/plataformas", "/rede/relatorios"],
    busca: "panorama da rede resumo da rede escolas em acompanhamento comparar escolas avaliações externas plataformas relatórios",
  },
  // Microscope: no menu do global o FlaskConical já é o Simulador, e a barra recolhida
  // mostra só o ícone.
  analiseRede: {
    rotulo: "Análises avançadas", caminho: "/rede/analise", icone: Microscope,
    busca: "análise educacional inteligência pedagógica diagnóstico exploratório relação com as plataformas por escola",
  },
} satisfies Record<string, ItemNav>;

/** Primeiro acesso do Admin Global: além do "Comece aqui", os cadastros que não dependem
 *  da escola selecionada estar configurada — é por eles que o primeiro usuário
 *  (coordenador) de uma escola recém-criada é cadastrado, ANTES de turmas, alunos e Lista
 *  Piloto. Lista EXPLÍCITA: antes o menu lia o grupo de chave "estrutura", e renomear o
 *  grupo escondia até a página Escolas, sem aviso. */
const PRIMEIRO_ACESSO_GLOBAL: ItemNav[] = [IT.redeGerenciar, IT.escolas, IT.usuarios];

/** Perfil resumido do usuário — decide QUAL sidebar montar. É o recorte de
 *  `usePerfil()` (fonte única da regra de papel) que o menu usa. */
interface Perfil {
  /** Admin global (is_global): opera todo o ecossistema. */
  global: boolean;
  /** Secretaria (rede vinculada, não-global): visão agregada da rede. */
  secretaria: boolean;
  /** Gestão (admin/coordenador/global) — o professor é `false` aqui. */
  gestor: boolean;
  /** Administrador (global ou cargo "admin") — `usePerfil().admin`. Separa,
   *  dentro da sidebar da escola, o admin da coordenação: Configurações Gerais
   *  é só dele. */
  admin: boolean;
}

/** Rótulo da página inicial conforme o perfil — mesma rota "/", foco diferente. */
function rotuloDashboard(p: Perfil): string {
  if (p.global) return "Visão Global";
  if (p.secretaria) return "Panorama da Rede";
  return "Visão geral";
}

/** Itens que só existem quando a rede CONTRATOU o módulo (SaaS). O que não está
 *  aqui vale para qualquer plano (ex.: Importações e Sincronização servem às
 *  duas plataformas). Módulo novo no futuro = mais uma entrada. */
const TODOS_MODULOS = ["leitura", "matematica"];

const MODULO_DO_ITEM: Record<string, string> = {
  "/matific": "matematica",
  "/elefante": "leitura",
  "/livros": "leitura",              // acervo do Elefante
  "/diagnostico-elefante": "leitura",
};

/** O que a pesquisa acha pelas plataformas que a rede TEM: o nome delas (o mesmo do h1 da
 *  tela delas, `rotuloDasPlataformas`) e a matéria de cada uma. */
function buscaDasPlataformas(modulos: string[]): string {
  const nenhum = !modulos.includes("leitura") && !modulos.includes("matematica");
  return [
    rotuloDasPlataformas(modulos),
    ...(nenhum || modulos.includes("leitura") ? ["leitura livros"] : []),
    ...(nenhum || modulos.includes("matematica") ? ["matemática atividades"] : []),
  ].join(" ");
}

/** Remove do menu o que a rede não contratou e descarta grupos que ficaram
 *  vazios — ponto de corte ÚNICO: o accordion, a barra só-ícones, a trilha e a
 *  busca global consomem daqui e herdam o filtro de graça. O grupo que fica com
 *  um item só é desenhado solto (`ehSolto`). */
function filtrarPorModulos(grupos: GrupoNav[], modulos: string[]): GrupoNav[] {
  return grupos
    .map((g) => ({
      ...g,
      itens: g.itens
        .filter((i) => {
          const exigido = MODULO_DO_ITEM[i.caminho];
          return !exigido || modulos.includes(exigido);
        })
        // A pesquisa acha só pelas plataformas que a rede TEM — numa rede só com o Matific,
        // "elefante" ou "leitura" não acham nada.
        .map((i) => (i.buscaComPlataformas
          ? { ...i, busca: `${i.busca ?? ""} ${buscaDasPlataformas(modulos)}` }
          : i)),
    }))
    .filter((g) => g.itens.length > 0);
}

/** Seções da barra por perfil — o rótulo diz o que a pessoa FAZ ali. */
function secoesDoPerfil(p: Perfil): SecaoNav[] {
  if (p.global) return [
    { chave: "administracao", rotulo: "Administração" },
    { chave: "escola", rotulo: "Escola selecionada" },
  ];
  // Secretaria: uma seção só, com as três áreas (DESENHO3 §1).
  if (p.secretaria) return [{ chave: "rede", rotulo: "Rede municipal" }];
  if (p.gestor) return [
    { chave: "escola", rotulo: "Escola" },
    { chave: "gestao", rotulo: "Gestão" },
  ];
  return [
    { chave: "turmas", rotulo: "Minhas turmas" },
    { chave: "reconhecimento", rotulo: "Reconhecimento" },
  ];
}

/** O que a pesquisa acha no Panorama da Rede da Secretaria, além dos nomes da página
 *  inicial: o assunto dele e os nomes das telas que saíram do menu e cujo conteúdo agora
 *  está ali (a vitrine e as metas do Painel da Rede, o uso das plataformas). Nada de
 *  "acompanhamento" nem "atenção": o Panorama (DESENHO3 §2) mostra a situação de uso de cada
 *  escola, não os sinais de atenção da antiga tela Escolas em acompanhamento — a pesquisa
 *  levaria a uma tela sem aquele conteúdo. */
const BUSCA_PANORAMA = "panorama da rede situação de uso participação plataformas escolas cadastradas ativas "
  + "destaques vitrine pública reconhecimento metas painel da rede";

/** A página inicial com o nome que o perfil dá a ela. A da Secretaria é o Panorama da Rede,
 *  uma das três áreas: o detalhe do uso das plataformas (/rede/plataformas), aberto pelo
 *  Panorama, fica "dentro" dela. */
const inicioDoPerfil = (p: Perfil): ItemNav => (p.secretaria
  ? {
    ...DASHBOARD, rotulo: rotuloDashboard(p), filhas: ["/rede/plataformas"],
    busca: `${DASHBOARD.busca} ${BUSCA_PANORAMA}`, buscaComPlataformas: true,
  }
  : { ...DASHBOARD, rotulo: rotuloDashboard(p) });

/** Sidebar DEDICADA por perfil: a mesma lista de rotas que aquele papel já
 *  podia abrir, mas agrupada, ordenada e nomeada para o trabalho dele. Nenhum
 *  item aqui abre algo que o backend não autorize para o papel — as travas de
 *  rota (App.tsx) e o backend (deps.py) seguem intactos (o teste
 *  NavegacaoPerfis confere cada item com `podeAbrirRota`).
 *
 *  Hierarquia: seção › [grupo ▸] › item. A página inicial abre o 1º grupo solto da 1ª
 *  seção; quem tem poucos itens (professora) não tem acordeão; a escola e o Admin Global
 *  têm acordeões por TAREFA, com o do dia a dia já aberto (`inicialAberto`); a Secretaria
 *  tem só as três áreas dela, soltas. */
function gruposDoPerfil(p: Perfil): GrupoNav[] {
  const inicio = inicioDoPerfil(p);
  // 👑 Admin Global — administra as redes e o sistema e opera qualquer escola (a
  // selecionada no cartão do rodapé). Uma porta por assunto: tudo de rede num grupo só
  // (antes em quatro lugares) e as três importações separadas pelo que importam
  // (indicadores oficiais em "Redes"; plataformas e planilhas em "Integrações e dados").
  // "Visão da rede" é o Panorama da Secretaria com o seletor de rede; as demais telas da
  // Secretaria abrem pelos links dela (`filhas`).
  if (p.global) return [
    { chave: "inicio", secao: "administracao", solto: true, rotulo: "Início", icone: LayoutDashboard, itens: [inicio] },
    { chave: "redes", secao: "administracao", rotulo: "Redes e municípios", icone: Landmark, inicialAberto: true,
      itens: [IT.painelRede, IT.visaoRede, IT.rankingEscolas, IT.analiseRede, IT.importacoesFontes, IT.redeGerenciar] },
    { chave: "cadastros", secao: "administracao", solto: true, rotulo: "Cadastros", icone: Building, itens: [IT.escolas, IT.usuarios] },
    { chave: "integracoes", secao: "administracao", rotulo: "Integrações e dados", icone: Cable,
      itens: [IT.sincronizacao, IT.importacoes, IT.revisoes, IT.diagnostico] },
    { chave: "configuracoes", secao: "administracao", rotulo: "Configurações", icone: Settings,
      itens: [IT.criterios, IT.simulador, IT.configuracoes] },
    // Um item só: desenhado solto (`ehSolto`); o grupo fica para a trilha e para quando
    // o monitoramento ganhar outra tela.
    { chave: "monitoramento", secao: "administracao", rotulo: "Monitoramento", icone: Activity, itens: [IT.sessoes] },
    { chave: "gestao-escolar", secao: "escola", rotulo: "Gestão escolar", icone: School,
      itens: [IT.visaoEscola, IT.turmas, IT.alunos, IT.professores, IT.relatorios] },
    { chave: "acompanhamento", secao: "escola", rotulo: "Acompanhamento", icone: BookOpenCheck,
      itens: [IT.elefante, IT.livros, IT.matific, IT.insights, IT.comparador, IT.assistente] },
    { chave: "reconhecimento", secao: "escola", rotulo: "Reconhecimento", icone: Trophy,
      itens: [IT.ranking, IT.premiacoes, IT.conquistas, IT.bibliotecaConquistas, IT.painelPublico] },
  ];
  // 🏛️ Secretaria — lê a rede inteira, só agregado (backend: turmas_permitidas=[],
  // supressão k; importar e desfazer é do admin global — D4). TRÊS áreas soltas, sem
  // acordeão (DESENHO3 §1): o Panorama da Rede (a página inicial: todas as escolas e a
  // situação de uso, os destaques e a vitrine, as metas), as Escolas (todas, a comparação e
  // a ficha de cada uma) e as Avaliações externas. Relatórios, premiações, usuários,
  // configurações e as análises técnicas saíram do menu dela (as rotas e as guardas ficam).
  // Nenhuma tela de escola (Turmas, Professores, Alunos…) entra aqui — o backend já protege.
  if (p.secretaria) return [
    { chave: "rede", secao: "rede", solto: true, rotulo: "Rede municipal", icone: Landmark,
      itens: [inicio, IT.escolasDaRede, IT.avaliacoesExternas] },
  ];
  // 🏫 Coordenação e administração da escola — administram a própria escola. "Minha
  // Escola" reúne as pessoas, as turmas e as CONTAS de acesso (Usuários, como antes da v2)
  // e nasce aberta. Fora do menu, como desde setembro: Importações (upload manual) e
  // Diagnóstico Elefante (sonda técnica da API) — rotas e permissões intactas, a escola
  // chega nelas por "Integrações". Configurações Gerais (cor, brasão, backup, IA) é do
  // administrador (RotaAdmin) e fica solta em Gestão: a coordenação edita as medalhas por
  // "Editar conquistas"; o admin, pelo cartão de Configurações Gerais.
  if (p.gestor) return [
    { chave: "inicio", secao: "escola", solto: true, rotulo: "Início", icone: LayoutDashboard, itens: [inicio] },
    { chave: "minha-escola", secao: "escola", rotulo: "Minha Escola", icone: School, inicialAberto: true,
      itens: [IT.visaoEscola, IT.turmas, IT.alunos, IT.professores, IT.usuarios, IT.relatorios] },
    { chave: "acompanhamento", secao: "escola", rotulo: "Acompanhamento", icone: BookOpenCheck,
      itens: [IT.elefante, IT.livros, IT.matific, IT.insights, IT.comparador, IT.assistente] },
    { chave: "reconhecimento", secao: "escola", rotulo: "Reconhecimento", icone: Trophy,
      itens: [IT.ranking, IT.premiacoes, IT.conquistas, IT.bibliotecaConquistas, IT.painelPublico] },
    // "Integrações" responde "os dados estão atualizados?"; a fila de revisão de
    // identidade fica ao lado dela.
    { chave: "dados", secao: "gestao", rotulo: "Dados e integrações", icone: Cable, itens: [IT.sincronizacao, IT.revisoes] },
    // "Critérios" = a mesma página /metricas em modo explicativo (só leitura).
    { chave: "pontuacao", secao: "gestao", rotulo: "Regras de pontuação", icone: SlidersHorizontal,
      itens: [IT.criterios, IT.simulador, ...(p.admin ? [] : [IT.editorConquistas])] },
    ...(p.admin
      ? [{ chave: "configuracoes", secao: "gestao", solto: true, rotulo: "Configurações", icone: Settings,
           itens: [IT.configuracoes] }]
      : []),
  ];
  // 👩‍🏫 Professora — só as turmas dela (o backend filtra por turmas_permitidas). Poucos
  // itens: duas seções sem acordeão. Turmas, Elefante e Matific continuam fora (telas de
  // gestão; as guardas RotaGestao/RotaEscolaOp não mudam).
  return [
    { chave: "turmas", secao: "turmas", solto: true, rotulo: "Minhas turmas", icone: GraduationCap,
      itens: [inicio, IT.meusAlunos, IT.insights, IT.meusRelatorios] },
    { chave: "reconhecimento", secao: "reconhecimento", solto: true, rotulo: "Reconhecimento", icone: Trophy,
      itens: [IT.rankingProf, IT.premiacoes, IT.bibliotecaConquistas] },
  ];
}

/** Sidebar do perfil JÁ FILTRADA pelos módulos contratados da rede. Sem
 *  `modulos` (chamada legada/teste) assume tudo ligado — o comportamento
 *  pré-SaaS. */
function sidebarDoPerfil(p: Perfil, modulos: string[] = TODOS_MODULOS): GrupoNav[] {
  return filtrarPorModulos(gruposDoPerfil(p), modulos);
}

/** Grupo desenhado SEM acordeão: marcado solto ou com um item só (acordeão de um item é
 *  um clique a mais por nada — ex.: Sessões Ativas do global, ou um grupo que o filtro de
 *  módulos deixou com um item). */
const ehSolto = (grupo: GrupoNav): boolean => Boolean(grupo.solto) || grupo.itens.length === 1;

/** Todos os itens de menu que o usuário PODE abrir (sidebar do perfil, "Comece aqui"
 *  para quem opera a escola e o Suporte), achatados — base da busca por páginas. */
function itensNavVisiveis(p: Perfil, modulos: string[] = TODOS_MODULOS): ItemNav[] {
  const [inicio, ...resto] = sidebarDoPerfil(p, modulos).flatMap((g) => g.itens);
  const todos = [
    ...(inicio ? [inicio] : []),
    ...(p.gestor && !p.secretaria ? [COMECAR] : []),
    ...resto,
    SUPORTE,
  ];
  // Sem endereços repetidos (vale o primeiro).
  return todos.filter((it, i) => todos.findIndex((x) => x.caminho === it.caminho) === i);
}

/** Escolhas de abrir/fechar grupos — chave nova: as antigas (`constela_menu_abertos`)
 *  guardavam chaves de outra arrumação e não valem mais. */
const CHAVE_MENU = "constela_menu_abertos_v3";

/** Rota e aba (`?ver=`) de um caminho do menu. */
function partesDoCaminho(caminho: string): { base: string; ver: string | null } {
  const [base, consulta = ""] = caminho.split("?");
  return { base, ver: new URLSearchParams(consulta).get("ver") };
}

/** A rota casa com a base do item? `exato` casa só na igualdade (senão /rede "engoliria"
 *  /rede/avaliacoes); os demais também nas sub-rotas (/alunos/12 acende Alunos). */
function casaRota(base: string, exato: boolean | undefined, pathname: string): boolean {
  if (exato) return pathname === base;
  return pathname === base || (base !== "/" && pathname.startsWith(base + "/"));
}

/** O endereço casa com o padrão? Segmento a segmento; `:parametro` casa com qualquer valor
 *  (`/rede/escolas/:escolaId` casa com `/rede/escolas/3`, não com `/rede/escolas`). Sem
 *  parâmetro, é a igualdade. */
function casaPadrao(padrao: string, pathname: string): boolean {
  const a = padrao.split("/").filter(Boolean);
  const b = pathname.split("/").filter(Boolean);
  return a.length === b.length && a.every((s, i) => s.startsWith(":") || s === b[i]);
}

/** Com que rota o item casa no endereço atual: a base dele (com as sub-rotas, salvo
 *  `exato`) ou uma das `filhas` (endereço exato ou padrão com parâmetro); `null` = não casa.
 *  O comprimento da rota casada mede o quanto o item é específico para este endereço. */
function rotaCasada(item: ItemNav, pathname: string): string | null {
  const { base } = partesDoCaminho(item.caminho);
  if (casaRota(base, item.exato, pathname)) return base;
  return item.filhas?.some((filha) => casaPadrao(filha, pathname)) ? pathname : null;
}

/** Abas que SAÍRAM de /rede/analise e viraram telas próprias (DESENHO2 §2.4): a página
 *  redireciona o link antigo (visão geral → Panorama; avaliações/indicador → Avaliações
 *  externas; plataformas → Elefante e Matific; relatórios → Relatórios e exportações).
 *  Nesse instante nenhum item acende — senão as Análises avançadas (a página que redireciona)
 *  acenderiam por um instante e o grupo delas abriria pela rota e ficaria aberto depois do
 *  redirecionamento. */
const ABAS_QUE_SAIRAM = new Set(["visao", "avaliacoes", "indicador", "plataformas", "relatorios"]);
/** A página das abas das Análises avançadas (AnaliseEducacional). */
const ROTA_ANALISE = "/rede/analise";

/** REGRA ÚNICA de item ativo: o destaque do menu e da barra recolhida, o grupo que abre
 *  sozinho e a trilha usam esta função (o NavLink ignora a consulta da URL e acenderia
 *  todas as abas da análise ao mesmo tempo).
 *  - item com aba (`?ver=X`): a rota casa E a aba da URL é X;
 *  - item sem aba: a rota casa (a base ou uma das `filhas`) e NENHUM outro item do menu é
 *    mais específico — um irmão com a aba da URL (/rede/analise × ?ver=relacao) ou uma
 *    rota mais longa (/configuracoes × /configuracoes/conquistas). Sem aba, ou com uma aba
 *    que nenhum item tem (`ver=diagnostico`, a aba padrão), acende o item sem aba — é a
 *    aba que a página abre;
 *  - /rede/analise com uma aba que saiu (`ABAS_QUE_SAIRAM`): nenhum.
 *  Assim um único item fica marcado por vez. */
function itemAtivo(item: ItemNav, pathname: string, search: string, todos: ItemNav[]): boolean {
  if (item.externo) return false;
  const { base, ver } = partesDoCaminho(item.caminho);
  const casada = rotaCasada(item, pathname);
  if (casada == null) return false;
  const verAtual = new URLSearchParams(search).get("ver");
  if (casada === ROTA_ANALISE && verAtual != null && ABAS_QUE_SAIRAM.has(verAtual)) return false;
  if (ver) return casada === base && ver === verAtual;
  return !todos.some((outro) => {
    if (outro === item || outro.externo) return false;
    const o = rotaCasada(outro, pathname);
    if (o == null) return false;
    const verOutro = partesDoCaminho(outro.caminho).ver;
    return o.length > casada.length || (o === casada && verOutro != null && verOutro === verAtual);
  });
}

/** Filtros que as abas da análise COMPARTILHAM na URL: série e escola (e a rede escolhida
 *  pelo admin global). Os parâmetros próprios de uma aba (indicador, etapa, componente,
 *  visao, edicao, de, ate, metrica...) não passam para a outra. */
const FILTROS_DA_ANALISE = ["serie", "escola", "rede"] as const;

/** Páginas que leem a rede escolhida pelo admin global em `?rede=`: as telas da Secretaria
 *  (`useRedeDaPagina`, que também a põe nos links de dentro delas; a ficha de cada escola
 *  também) e as Análises avançadas. O Painel da Rede e as Importações e fontes escolhem a
 *  rede de outro jeito — fora daqui. Endereço exato ou padrão com parâmetro (`casaPadrao`). */
const PAGINAS_COM_REDE = [
  ROTA_ANALISE, "/rede/visao", "/rede/acompanhamento", "/rede/escolas", "/rede/escolas/:escolaId",
  "/rede/avaliacoes-externas", "/rede/plataformas", "/rede/relatorios",
];
const leARede = (pathname: string): boolean => PAGINAS_COM_REDE.some((p) => casaPadrao(p, pathname));

/** Para onde o link de um item do menu leva — FUNÇÃO ÚNICA do menu aberto (`LinkMenu`) e
 *  da barra recolhida (`IconeMenu`). Os itens da análise têm caminho fixo
 *  (`/rede/analise?ver=X`) e o Link troca a consulta inteira: já dentro da análise, o item
 *  do menu zerava a Série (e a rede do global) sem aviso, enquanto a aba da própria página
 *  (`trocarAba`) mantém os filtros — o mesmo destino dava resultados diferentes conforme o
 *  caminho. Estando JÁ em /rede/analise, o item leva os filtros compartilhados da URL atual
 *  e troca só a aba (Diagnóstico exploratório, a aba padrão = sem `ver`). Entre as páginas
 *  que leem `?rede=` (`PAGINAS_COM_REDE`), o item leva só a rede: o admin global que escolheu
 *  a rede 2 na Visão da rede (e seguiu pelos links dela, que a levam) voltava, pelo menu, à
 *  primeira rede sem perceber. Fora disso, é o caminho do item. O destaque não muda:
 *  `itemAtivo` olha só a rota e o `ver`. */
function destinoDoItem(item: ItemNav, pathname: string, search: string): string {
  const [base, consulta = ""] = item.caminho.split("?");
  if (item.externo) return item.caminho;
  const chaves: readonly string[] = base === ROTA_ANALISE && pathname === ROTA_ANALISE ? FILTROS_DA_ANALISE
    : leARede(base) && leARede(pathname) ? ["rede"]
      : [];
  if (chaves.length === 0) return item.caminho;
  const atual = new URLSearchParams(search);
  const destino = new URLSearchParams(consulta);
  for (const chave of chaves) {
    const valor = atual.get(chave);
    if (valor && !destino.has(chave)) destino.set(chave, valor);
  }
  const texto = destino.toString();
  return texto ? `${base}?${texto}` : base;
}

/** O item do menu da rota atual e o grupo dele. Rotas de detalhe (/alunos/12,
 *  /turmas/3, /relatorios/periodo) herdam o item pai. */
function contextoDaRota(
  grupos: GrupoNav[], pathname: string, search: string,
): { item: ItemNav; grupo: GrupoNav } | null {
  const todos = grupos.flatMap((g) => g.itens);
  for (const grupo of grupos) {
    const item = grupo.itens.find((it) => itemAtivo(it, pathname, search, todos));
    if (item) return { item, grupo };
  }
  return null;
}

// Títulos das rotas que podem abrir SEM item no menu do perfil (atalho de teclado, link
// de outra tela, rota órfã) ou numa das `filhas` de um item; com item, a trilha usa o nome
// do item (`tituloDaRota`).
const TITULOS_ESPECIAIS: Record<string, string> = {
  "/comecar": "Comece aqui",
  "/rede": "Painel da Rede",
  "/rede/gerenciar": "Gerenciar Rede",
  "/rede/avaliacoes": "Fontes dos indicadores",
  "/rede/analise": "Análises avançadas",
  "/rede/ranking": "Ranking da Rede",
  // Telas da Secretaria que o Admin Global abre pelos links da "Visão da rede" (filhas do
  // item dele) e que a Secretaria abre pelos links das três áreas dela: a trilha diz o nome
  // da tela, não o do item pai. (/rede/plataformas não entra aqui: o nome dela segue os
  // módulos contratados, `ROTA_PLATAFORMAS` em `tituloDaRota`.)
  "/rede/visao": "Visão da rede",
  "/rede/acompanhamento": "Escolas em acompanhamento",
  "/rede/escolas": "Escolas",
  "/rede/avaliacoes-externas": "Avaliações externas",
  "/rede/relatorios": "Relatórios e exportações",
  // D4: o mesmo nome do menu para os dois perfis (era "Métricas" no global e
  // "Pontuação" na escola).
  "/metricas": "Critérios",
  "/usuarios": "Usuários e acessos",
  "/suporte": "Suporte",
  "/minha-conta": "Minha conta",
  "/sincronizacao": "Integrações",
  "/importacoes": "Importações (avançado)",
  "/diagnostico-elefante": "Diagnóstico da integração (avançado)",
};

/** Títulos das rotas com parâmetro (`casaPadrao`) que não têm item próprio no menu. */
const TITULOS_POR_PADRAO: [string, string][] = [
  ["/rede/escolas/:escolaId", "Ficha da escola"],
];

/** A tela do uso das plataformas da rede (/rede/plataformas): o nome é o das plataformas que
 *  a rede contratou, o mesmo do h1 dela (`rotuloDasPlataformas`). */
const ROTA_PLATAFORMAS = "/rede/plataformas";

/** Título legível da rota atual (o último nível da trilha). O nome do item do menu do
 *  perfil vence — é o que a pessoa clicou, com a aba ("Relação com as plataformas") e o nome
 *  do perfil ("Meus Alunos", "Importações e fontes"). Fora do menu (ou numa das `filhas` de
 *  um item): os títulos especiais, o catálogo pelo caminho EXATO (assim
 *  /conquistas/biblioteca não vira "Conquistas"), os detalhes (perfil de aluno, turma) e,
 *  por fim, o item pai ou o prefixo. */
function tituloDaRota(pathname: string, ativo: ItemNav | null, modulos: string[] = TODOS_MODULOS): string {
  if (ativo && partesDoCaminho(ativo.caminho).base === pathname) return ativo.rotulo;
  if (pathname === ROTA_PLATAFORMAS) return rotuloDasPlataformas(modulos);
  if (TITULOS_ESPECIAIS[pathname]) return TITULOS_ESPECIAIS[pathname];
  const comParametro = TITULOS_POR_PADRAO.find(([padrao]) => casaPadrao(padrao, pathname));
  if (comParametro) return comParametro[1];
  const catalogo: ItemNav[] = Object.values(IT);
  const exato = catalogo.find((i) => i.caminho === pathname);
  if (exato) return exato.rotulo;
  if (pathname.startsWith("/alunos/")) return "Perfil do aluno";
  if (pathname.startsWith("/turmas/")) return "Detalhe da turma";
  if (ativo) return ativo.rotulo;
  const prefixo = catalogo.find((i) => pathname.startsWith(i.caminho + "/"));
  return prefixo?.rotulo ?? "";
}

/** O que o USUÁRIO escolheu abrir ou fechar, por grupo (`{chave: aberto}`). Grupo sem
 *  escolha segue o `inicialAberto`; valor estragado = ninguém escolheu nada ainda. */
function carregarEscolhas(): Record<string, boolean> {
  try {
    const bruto = localStorage.getItem(CHAVE_MENU);
    const lido: unknown = bruto ? JSON.parse(bruto) : null;
    if (lido && typeof lido === "object" && !Array.isArray(lido)) {
      return Object.fromEntries(
        Object.entries(lido as Record<string, unknown>).filter(([, v]) => typeof v === "boolean"),
      ) as Record<string, boolean>;
    }
  } catch {
    /* localStorage indisponível ou JSON inválido */
  }
  return {};
}

/** Grava UMA escolha sem apagar as dos grupos de outro perfil no mesmo navegador. */
function salvarEscolha(chave: string, aberto: boolean) {
  try {
    localStorage.setItem(CHAVE_MENU, JSON.stringify({ ...carregarEscolhas(), [chave]: aberto }));
  } catch {
    /* localStorage indisponível: só não persiste */
  }
}

/** Primeiro acesso: a escola selecionada ainda não foi configurada (sem Lista Piloto) e
 *  quem entra a opera (admin/coordenação; a Secretaria e a professora entram numa escola
 *  já preparada). Regra ÚNICA do menu aberto e da barra recolhida. */
function usePrimeiroAcesso(): boolean {
  const { gestor, secretaria } = usePerfil();
  const { precisaConfigurar } = useOnboarding();
  return gestor && !secretaria && precisaConfigurar;
}

/** Selo do item "Premiações": dias até o FIM do bimestre em curso, pelo calendário
 *  oficial (o do backend, via useCalendarioBimestres). Não existe data de
 *  premiação no sistema — o selo nunca diz "dias para a premiação". Fora do
 *  calendário (férias, ano sem calendário) não há selo. */
interface SeloMenu {
  /** O que aparece na pílula (decorativo, aria-hidden). */
  curto: string;
  /** O texto completo: descrição acessível do link e dica do mouse. */
  completo: string;
}

function seloDoBimestre(hoje: Date, calendario: CalendarioDoAno | null): SeloMenu | null {
  const bimestre = bimestreEmCurso(hoje, calendario);
  if (!bimestre) return null;
  const dias = bimestre.diasParaOFim;
  if (dias === 0) return { curto: "hoje", completo: `O ${bimestre.numero}º bimestre termina hoje` };
  return {
    curto: `${dias}d`,
    completo: `Fim do ${bimestre.numero}º bimestre em ${dias} ${dias === 1 ? "dia" : "dias"}`,
  };
}

const seloDoItem = (item: ItemNav, selo: SeloMenu | null): SeloMenu | null =>
  item.caminho === "/premiacoes" ? selo : null;

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
  pagina?: boolean;
}

/** Pesquisa global (PRD §21): abre PÁGINAS do menu (como clicar na barra
 *  lateral) e encontra alunos, turmas, professores e livros — sempre dentro
 *  do que o cargo pode acessar (o menu já é filtrado por papel; o backend
 *  filtra os alunos pelas turmas do professor). Navegável pelo teclado. */
function PesquisaGlobal() {
  const { escolaId } = useApp();
  const perfil = usePerfil();
  const { modulos: modulosBusca } = useModulos();
  const navegar = useNavigate();
  const [termo, setTermo] = useState("");
  const [aberto, setAberto] = useState(false);
  const [ativo, setAtivo] = useState(0);
  const caixa = useRef<HTMLDivElement | null>(null);

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

  // Páginas do menu que casam com o texto (só as que o cargo pode abrir). Casa
  // também pelos outros nomes da página (ex.: "dashboard", "pontuação").
  const alvo = normalizar(consulta);
  const paginas: Opcao[] = consulta.length < 1 ? [] : itensNavVisiveis(perfil, modulosBusca)
    .filter((item) => normalizar(`${item.rotulo} ${item.busca ?? ""}`).includes(alvo))
    .slice(0, 6)
    .map((item) => ({
      chave: `pag:${item.caminho}`, rotulo: item.rotulo,
      sub: "Página", Icone: item.icone, caminho: item.caminho, pagina: true,
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

  // Visível em TODAS as larguras (antes sumia abaixo de 640 px, sem botão de busca).
  // Com a trilha ao lado (lg+), a caixa tem 20rem e encolhe até 13rem antes de a
  // trilha cortar o nome da página atual.
  return (
    <div ref={caixa} className="relative flex min-w-0 flex-1 items-center lg:min-w-[13rem] lg:[flex:0_1_20rem]">
      <Search size={16} aria-hidden className="pointer-events-none absolute left-3.5 text-zinc-400" />
      <input
        id="pesquisa-global"
        aria-label="Pesquisar páginas, alunos, turmas... (Ctrl+K)"
        autoComplete="off"
        className="h-10 w-full rounded-full border border-zinc-200/80 bg-white pl-10 pr-4 text-sm text-zinc-900 shadow-cartao transition-colors placeholder:text-zinc-500 hover:border-zinc-300 focus:border-indigo-400 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100 dark:placeholder:text-zinc-400 lg:pr-16"
        placeholder="Pesquisar…"
        value={termo}
        onChange={(evento) => { setTermo(evento.target.value); setAberto(true); }}
        onFocus={() => setAberto(true)}
        onKeyDown={aoTeclar}
      />
      <kbd
        aria-hidden
        className="pointer-events-none absolute right-3 hidden rounded-md border border-zinc-200 bg-zinc-50 px-1.5 py-0.5 font-sans text-[10px] font-semibold text-zinc-500 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-400 lg:block"
      >
        Ctrl K
      </kbd>
      {mostrar && (
        <div className="absolute right-0 top-full z-40 mt-2 max-h-[70vh] w-full min-w-[min(20rem,calc(100vw-2rem))] overflow-y-auto overscroll-contain rounded-2xl border border-zinc-200/80 bg-white p-1.5 shadow-flutuante dark:border-zinc-700 dark:bg-zinc-900">
          {secoes.length === 0 ? (
            <p className="px-3 py-2.5 text-sm text-zinc-500 dark:text-zinc-400">Nada encontrado.</p>
          ) : (
            secoes.map((secao) => (
              <div key={secao.titulo} className="py-1">
                <p className="px-3 pb-1 pt-1.5 text-[11px] font-semibold uppercase tracking-[0.08em] text-zinc-500 dark:text-zinc-400">
                  {secao.titulo}
                </p>
                {secao.itens.map((item) => {
                  const indice = planas.findIndex((o) => o.chave === item.chave);
                  const realcado = indice === ativo;
                  return (
                    <button
                      key={item.chave}
                      type="button"
                      onMouseEnter={() => setAtivo(indice)}
                      className={`flex w-full items-center gap-3 rounded-xl px-2.5 py-2 text-left text-sm transition-colors ${
                        realcado ? "bg-indigo-50 dark:bg-indigo-500/10" : "hover:bg-zinc-50 dark:hover:bg-zinc-800"
                      }`}
                      onClick={() => abrir(item.caminho)}
                    >
                      {item.Icone && (
                        <IconePastel icone={item.Icone} tom={item.pagina ? "violeta" : "neutro"} tamanho="sm" />
                      )}
                      <span className="min-w-0 flex-1 truncate font-medium text-zinc-800 dark:text-zinc-100" title={item.rotulo}>{item.rotulo}</span>
                      {item.sub && (
                        <span className="shrink-0 text-xs text-zinc-500 dark:text-zinc-400">{item.sub}</span>
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
  // Falha ao LISTAR não é "nenhuma novidade": o contador pode estar dizendo que há
  // avisos (inclusive os críticos de coleta) e o popover não pode negar isso.
  const [falhou, setFalhou] = useState(false);
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

  async function carregar() {
    setCarregando(true);
    setFalhou(false);
    try {
      const lista = await api<Notificacao[]>("/notificacoes");
      setItens(lista);
      if (lista.some((n) => !n.lida)) {
        // Abrir = visto tudo, mas só quando o servidor GRAVOU a leitura: com o
        // marcar-lidas falhando, o contador continua (a próxima busca dele, em
        // segundo plano, segue dizendo a verdade).
        await api("/notificacoes/marcar-lidas", { method: "POST" })
          .then(() => setNaoLidas(0), () => undefined);
      } else {
        setNaoLidas(0);
      }
    } catch {
      setItens([]);
      setFalhou(true);
    } finally {
      setCarregando(false);
    }
  }

  function alternar() {
    const abrindo = !aberto;
    setAberto(abrindo);
    if (abrindo) void carregar();
  }

  // Aviso que aponta para uma tela que o perfil não abre (ex.: backup →
  // Configurações Gerais, só do administrador; importação → Importações, que o
  // professor não opera) fica sem link — antes levava a um redirecionamento
  // mudo para o Dashboard. As guardas são as mesmas de App.tsx.
  const perfil = usePerfil();
  const { tem } = useModulos();
  const rotaDe = (item: Notificacao) =>
    item.rota && podeAbrirRota(item.rota, perfil, tem) ? item.rota : null;

  function irPara(item: Notificacao) {
    setAberto(false);
    const rota = rotaDe(item);
    if (rota) navegar(rota);
  }

  return (
    <div ref={caixa} className="relative">
      <BotaoIcone
        rotulo={naoLidas > 0 ? `Notificações (${naoLidas} não lidas)` : "Notificações"}
        aria-expanded={aberto}
        onClick={alternar}
      >
        <Bell size={18} aria-hidden />
        {naoLidas > 0 && (
          <span
            aria-hidden
            className="absolute -right-1 -top-1 flex h-[18px] min-w-[18px] items-center justify-center rounded-full bg-rose-600 px-1 text-[10px] font-bold leading-none text-white ring-2 ring-zinc-50 dark:ring-zinc-950"
          >
            {naoLidas > 9 ? "9+" : naoLidas}
          </span>
        )}
      </BotaoIcone>
      {aberto && (
        <div className="absolute right-0 top-full z-40 mt-2 w-[min(22rem,calc(100vw-2rem))] overflow-hidden rounded-2xl border border-zinc-200/80 bg-white shadow-flutuante dark:border-zinc-700 dark:bg-zinc-900">
          <p className="border-b border-zinc-100 px-4 py-3 text-[11px] font-semibold uppercase tracking-[0.08em] text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
            Notificações
          </p>
          {carregando ? (
            <p className="px-4 py-4 text-sm text-zinc-500 dark:text-zinc-400">Carregando…</p>
          ) : falhou ? (
            <div role="alert" className="flex flex-col items-center px-4 py-6 text-center">
              <p className="text-sm text-zinc-600 dark:text-zinc-300">Não foi possível carregar as notificações.</p>
              <Botao variante="secundario" tamanho="sm" className="mt-3" onClick={() => void carregar()}>
                Tentar de novo
              </Botao>
            </div>
          ) : itens.length === 0 ? (
            <div className="flex flex-col items-center px-4 py-7 text-center">
              <IconePastel icone={Bell} tom="violeta" />
              <p className="mt-3 text-sm text-zinc-500 dark:text-zinc-400">Nenhuma novidade por enquanto.</p>
            </div>
          ) : (
            <ul className="max-h-80 overflow-y-auto overscroll-contain p-1.5">
              {itens.map((item) => (
                <li key={item.id}>
                  <button
                    type="button"
                    onClick={() => irPara(item)}
                    disabled={!rotaDe(item)}
                    className={`flex w-full items-start gap-3 rounded-xl px-2.5 py-2.5 text-left transition-colors ${
                      rotaDe(item) ? "hover:bg-zinc-50 dark:hover:bg-zinc-800/60" : "cursor-default"
                    }`}
                  >
                    <span aria-hidden className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${
                      item.severidade === "critico" ? "bg-red-500"
                        : item.severidade === "aviso" ? "bg-amber-500" : "bg-indigo-400"
                    }`} />
                    <span className="min-w-0 flex-1">
                      {/* A gravidade também em texto (não só na cor da bolinha). */}
                      {item.severidade === "critico" && <span className="sr-only">Crítico: </span>}
                      {item.severidade === "aviso" && <span className="sr-only">Aviso: </span>}
                      <span className={`block text-sm text-zinc-800 dark:text-zinc-100 ${item.lida ? "" : "font-semibold"}`}>{item.titulo}</span>
                      <span className="mt-0.5 block text-xs text-zinc-500 dark:text-zinc-400">
                        {item.autor ? `${item.autor} · ` : ""}{dataHora(item.data)}
                      </span>
                    </span>
                    {rotaDe(item) && (
                      <ChevronRight size={15} className="mt-0.5 shrink-0 text-zinc-400" aria-hidden />
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

// ── Barra lateral marinho (identidade v2) ─────────────────────────────────
// Texto #C9CBE3 sobre #17193B (10,6:1); rótulos de seção #8B8FB5 (5,4:1); item ativo
// em pílula violeta com sombra; hover suave em branco translúcido.
const ITEM_BASE = "flex items-center gap-3 rounded-xl px-3 transition-colors";
const ITEM_INATIVO = "font-medium text-marinho-200 hover:bg-white/[0.07] hover:text-white";
const ITEM_ATIVO = "bg-indigo-600 font-semibold text-white shadow-pilula";

/** Pílula âmbar do selo (ex.: "61d" em Premiações). Decorativa: o texto completo é a
 *  descrição acessível do link e o title. */
function PilulaSelo({ selo }: { selo: SeloMenu }) {
  return (
    <span
      aria-hidden
      title={selo.completo}
      className="ml-auto shrink-0 rounded-full bg-ouro-400 px-2 py-0.5 text-[11px] font-bold leading-4 text-marinho-900 tabular-nums"
    >
      {selo.curto}
    </span>
  );
}

/** Um link do menu (item solto ou subitem de um grupo). `ativo` vem de `itemAtivo` (a
 *  regra única, que entende a aba `?ver=`) — por isso é um Link com `aria-current` à mão,
 *  e não um NavLink. */
function LinkMenu({ item, ativo, aoNavegar, subitem, selo }: {
  item: ItemNav;
  ativo: boolean;
  aoNavegar?: () => void;
  subitem?: boolean;
  selo?: SeloMenu | null;
}) {
  // O selo NÃO entra no nome acessível do link ("Premiações" continua sendo o nome):
  // vai como descrição (aria-describedby), lida depois do nome.
  const idSelo = useId();
  const { pathname, search } = useLocation();
  // Altura MÍNIMA (não fixa): o rótulo que não cabe numa linha quebra em até duas (D24,
  // D54) em vez de cortar o nome com reticências — na barra de 256 px, os rótulos longos
  // ficavam pela metade. O de uma linha fica com a altura de sempre (36/40 px).
  const altura = subitem ? "min-h-9 py-1.5 text-[13px]" : "min-h-10 py-2 text-sm";
  const classeRotulo = "min-w-0 line-clamp-2 break-words leading-snug";
  // Link externo (ex.: Suporte → Google Drive): abre em nova aba, nunca fica
  // "ativo" e não interfere no roteamento interno.
  if (item.externo) {
    return (
      <a
        href={item.caminho}
        target="_blank"
        rel="noopener noreferrer"
        onClick={aoNavegar}
        className={`${ITEM_BASE} ${altura} ${ITEM_INATIVO}`}
      >
        <item.icone size={subitem ? 16 : 18} strokeWidth={2} className="shrink-0" aria-hidden />
        <span className={`${classeRotulo} flex-1`} title={item.rotulo}>{item.rotulo}</span>
        <ExternalLink size={13} strokeWidth={2} className="shrink-0 opacity-70" aria-hidden />
      </a>
    );
  }
  return (
    <>
      <Link
        to={destinoDoItem(item, pathname, search)}
        onClick={aoNavegar}
        aria-current={ativo ? "page" : undefined}
        aria-describedby={selo ? idSelo : undefined}
        className={`${ITEM_BASE} ${altura} ${ativo ? ITEM_ATIVO : ITEM_INATIVO}`}
      >
        <item.icone size={subitem ? 16 : 18} strokeWidth={2} className="shrink-0" aria-hidden />
        {/* title: se nem duas linhas bastarem, o nome inteiro continua à mão. */}
        <span className={classeRotulo} title={item.rotulo}>{item.rotulo}</span>
        {selo && <PilulaSelo selo={selo} />}
      </Link>
      {selo && <span id={idSelo} hidden>{selo.completo}</span>}
    </>
  );
}

/** Um grupo recolhível (acordeão) dentro de uma seção. */
function GrupoMenu({ grupo, aberto, temAtivo, idPainel, aoAlternar, aoNavegar, selo, ativoDe }: {
  grupo: GrupoNav;
  aberto: boolean;
  temAtivo: boolean;
  idPainel: string;
  aoAlternar: () => void;
  aoNavegar?: () => void;
  selo: SeloMenu | null;
  ativoDe: (item: ItemNav) => boolean;
}) {
  return (
    <div>
      <button
        type="button"
        aria-expanded={aberto}
        aria-controls={idPainel}
        onClick={aoAlternar}
        className={`${ITEM_BASE} h-10 w-full text-sm ${
          temAtivo ? "font-semibold text-white hover:bg-white/[0.07]" : ITEM_INATIVO
        }`}
      >
        <grupo.icone
          size={18}
          strokeWidth={2}
          aria-hidden
          className={`shrink-0 ${temAtivo ? "text-indigo-300" : ""}`}
        />
        <span className="min-w-0 flex-1 truncate text-left" title={grupo.rotulo}>{grupo.rotulo}</span>
        {temAtivo && !aberto && (
          <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-indigo-400" aria-hidden />
        )}
        <ChevronDown
          size={16}
          aria-hidden
          className={`shrink-0 text-marinho-400 transition-transform duration-200 motion-reduce:transition-none ${aberto ? "rotate-180" : ""}`}
        />
      </button>

      {/* Animação suave de altura via grid 0fr→1fr (respeita reduce-motion).
          Fechado = `invisible` (visibility: hidden): com altura 0 os links
          continuavam no Tab — o foco sumia dentro de um grupo fechado — e o
          leitor de tela lia o grupo inteiro. A visibilidade entra na transição
          para o grupo só sumir no FIM da animação de fechar. */}
      <div
        id={idPainel}
        className={`grid transition-[grid-template-rows,visibility] duration-300 ease-out motion-reduce:transition-none ${
          aberto ? "grid-rows-[1fr]" : "invisible grid-rows-[0fr]"
        }`}
      >
        <div className="overflow-hidden">
          <div className="ml-[1.3rem] mt-1 space-y-1 border-l border-white/10 pl-3">
            {grupo.itens.map((item) => (
              <LinkMenu key={item.caminho} item={item} ativo={ativoDe(item)} aoNavegar={aoNavegar} subitem
                        selo={seloDoItem(item, selo)} />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

/** Rótulo de seção da barra (caixa alta só por CSS). */
function TituloSecao({ id, children }: { id: string; children: string }) {
  return (
    <p id={id} className="px-3 pb-2 text-[11px] font-semibold uppercase tracking-[0.1em] text-marinho-400">
      {children}
    </p>
  );
}

// scroll-pt-10/scroll-pb-12: o item ativo levado à vista fica FORA dos esmaecidos
// do topo e do pé (cada um com 32 px).
const CLASSE_NAV = "min-h-0 flex-1 overflow-y-auto overscroll-contain scroll-pb-12 scroll-pt-10 px-3 pb-4 pt-2 [scrollbar-color:rgba(255,255,255,0.18)_transparent] [scrollbar-width:thin]";

/** Navegação lateral: as seções do perfil, com itens soltos e grupos em acordeão
 *  (barra fixa do desktop e gaveta do celular). */
function Navegacao({ aoNavegar }: { aoNavegar?: () => void }) {
  const { pathname, search } = useLocation();
  // Fonte única da regra de papel (antes reescrita aqui com a mesma conta).
  const perfil = usePerfil();
  // "Comece aqui" só aparece enquanto a escola não foi configurada; depois da
  // config inicial ele some (novas cargas passam a ser por "Integrações", que também
  // leva às Importações manuais).
  const primeiroAcesso = usePrimeiroAcesso();
  const { modulos } = useModulos();
  const grupos = sidebarDoPerfil(perfil, modulos);
  const todos = grupos.flatMap((g) => g.itens);
  const ativo = contextoDaRota(grupos, pathname, search)?.grupo.chave ?? null;
  const ativoDe = (item: ItemNav) => itemAtivo(item, pathname, search, todos);
  const { escolaId } = useApp();
  const calendario = useCalendarioBimestres(escolaId);
  const selo = seloDoBimestre(new Date(), calendario);
  // A Navegacao existe duas vezes (barra fixa e gaveta do celular): ids próprios.
  const idBase = useId();
  const refNav = useRef<HTMLElement | null>(null);
  // O menu de primeiro acesso (só "Comece aqui") é curto e não tem os esmaecidos.
  const { inicio: acima, fim: abaixo } = useBordasDaRolagem(refNav, "y", !primeiroAcesso);
  // O que o usuário escolheu abrir/fechar (persistido) e os grupos que a ROTA abriu
  // (só na memória: abrir sozinho não é escolha dele). O `inicialAberto` vale enquanto
  // não há escolha — calculado a cada render, porque o perfil chega depois do 1º render
  // (até o /auth/me responder, o menu é o de quem não é gestor).
  const [escolhas, setEscolhas] = useState<Record<string, boolean>>(carregarEscolhas);
  const [abertosPelaRota, setAbertosPelaRota] = useState<Set<string>>(() => new Set(ativo ? [ativo] : []));
  const estaAberto = (grupo: GrupoNav) =>
    abertosPelaRota.has(grupo.chave) || (escolhas[grupo.chave] ?? Boolean(grupo.inicialAberto));

  // Ao navegar para uma página dentro de um grupo fechado (busca, atalho,
  // link direto), abre esse grupo para o item ativo ficar visível.
  useEffect(() => {
    if (ativo) setAbertosPelaRota((atuais) => (atuais.has(ativo) ? atuais : new Set(atuais).add(ativo)));
  }, [ativo]);

  // Em telas baixas (notebook de 720 px) a última seção do perfil (Gestão, Escola
  // selecionada...) fica abaixo da dobra: ao entrar numa página de lá — ou trocar de aba
  // da análise pelo menu —, rola SÓ o menu até o item ativo (o resto não se move).
  // A rolagem é feita no scrollTop da lista, NÃO com scrollIntoView: no Chromium o
  // scrollIntoView move o ponto de partida da navegação por teclado para o item, e o 1º Tab
  // da página pulava o "Pular para o conteúdo" (WCAG 2.4.1) e caía no item seguinte do menu.
  // As folgas são as do CLASSE_NAV (scroll-pt-10 = 40 px; scroll-pb-12 = 48 px): o item
  // fica fora dos esmaecidos do topo e do pé.
  useEffect(() => {
    const lista = refNav.current;
    const atual = lista?.querySelector<HTMLElement>('[aria-current="page"]');
    if (!lista || !atual) return;
    const caixa = lista.getBoundingClientRect();
    const item = atual.getBoundingClientRect();
    if (item.top < caixa.top + 40) lista.scrollTop -= caixa.top + 40 - item.top;
    else if (item.bottom > caixa.bottom - 48) lista.scrollTop += item.bottom - (caixa.bottom - 48);
  }, [pathname, search]);

  function alternar(grupo: GrupoNav) {
    const abrir = !estaAberto(grupo);
    setAbertosPelaRota((atuais) => {
      if (!atuais.has(grupo.chave)) return atuais;
      const proximos = new Set(atuais);
      proximos.delete(grupo.chave);
      return proximos;
    });
    setEscolhas((atuais) => ({ ...atuais, [grupo.chave]: abrir }));
    salvarEscolha(grupo.chave, abrir);
  }

  // PRIMEIRO ACESSO: enquanto a escola não foi configurada, o único caminho é o
  // "Comece aqui" — nada de Visão geral, Minha Escola, Gestão etc. Não faz sentido
  // abrir as demais telas antes de conectar Lista Piloto/Elefante/Matific. Depois que
  // configura, `precisaConfigurar` vira falso e o menu completo aparece. O Suporte fica
  // no rodapé da barra, como no menu completo.
  //
  // EXCEÇÃO — Admin Global: Gerenciar Rede, Escolas e Usuários não dependem da escola
  // selecionada estar configurada (PRIMEIRO_ACESSO_GLOBAL). Sem isto, selecionar a
  // escola nova escondia até a página Escolas.
  if (primeiroAcesso) {
    return (
      <nav aria-label="Menu principal" className={CLASSE_NAV}>
        <TituloSecao id={`${idBase}-secao-inicio`}>Primeiros passos</TituloSecao>
        <LinkMenu item={COMECAR} ativo={itemAtivo(COMECAR, pathname, search, [])} aoNavegar={aoNavegar} />
        {perfil.global && (
          <div className="mt-5">
            <TituloSecao id={`${idBase}-secao-administracao`}>Administração</TituloSecao>
            <div className="space-y-1">
              {PRIMEIRO_ACESSO_GLOBAL.map((item) => (
                <LinkMenu key={item.caminho} item={item} ativo={itemAtivo(item, pathname, search, PRIMEIRO_ACESSO_GLOBAL)}
                          aoNavegar={aoNavegar} />
              ))}
            </div>
          </div>
        )}
      </nav>
    );
  }

  return (
    <ListaComSetas acima={acima} abaixo={abaixo}>
      <nav ref={refNav} aria-label="Menu principal" className={CLASSE_NAV}>
        <DegradeRolagem lado="topo" visivel={acima} />
        <div>
          {secoesDoPerfil(perfil).map((secao) => {
            const daSecao = grupos.filter((g) => g.secao === secao.chave);
            // Seção vazia não aparece (ex.: tudo dela fora dos módulos contratados).
            if (daSecao.length === 0) return null;
            const idTitulo = `${idBase}-secao-${secao.chave}`;
            return (
              <div key={secao.chave} role="group" aria-labelledby={idTitulo} className="mt-6 first:mt-0">
                <TituloSecao id={idTitulo}>{secao.rotulo}</TituloSecao>
                <div className="space-y-1">
                  {daSecao.map((grupo) =>
                    ehSolto(grupo) ? (
                      grupo.itens.map((item) => (
                        <LinkMenu key={item.caminho} item={item} ativo={ativoDe(item)} aoNavegar={aoNavegar}
                                  selo={seloDoItem(item, selo)} />
                      ))
                    ) : (
                      <GrupoMenu
                        key={grupo.chave}
                        grupo={grupo}
                        aberto={estaAberto(grupo)}
                        temAtivo={ativo === grupo.chave}
                        idPainel={`${idBase}-${grupo.chave}`}
                        aoAlternar={() => alternar(grupo)}
                        aoNavegar={aoNavegar}
                        selo={selo}
                        ativoDe={ativoDe}
                      />
                    ),
                  )}
                </div>
              </div>
            );
          })}
        </div>
        <DegradeRolagem lado="base" visivel={abaixo} />
      </nav>
    </ListaComSetas>
  );
}

/** Esmaecido no topo ou no pé da lista do menu: aparece SÓ quando há itens
 *  escondidos naquele lado (a lista rola por dentro em telas baixas), para nenhum
 *  item cortado ficar sem aviso. Decorativo. Fica dentro da área que rola, preso à
 *  borda (sticky); o do topo não ocupa espaço (margens negativas) e o do pé deixa
 *  uma folga para o último item subir acima dele. `recuo` anula o padding lateral
 *  da lista (px-3 no menu, px-2 na barra só de ícones). A SETA não mora aqui: ver
 *  `SetaRolagem`. */
function DegradeRolagem({ lado, visivel, recuo = "-mx-3" }: {
  lado: "topo" | "base";
  visivel: boolean;
  recuo?: string;
}) {
  const posicao = lado === "topo"
    ? "-top-2 -mt-2 -mb-6 bg-gradient-to-b"
    : "-bottom-4 -mb-4 mt-2 bg-gradient-to-t";
  return (
    <div
      aria-hidden
      data-degrade={lado}
      data-visivel={visivel ? "sim" : "nao"}
      className={`pointer-events-none sticky z-10 ${recuo} block h-8 from-marinho-900 to-transparent transition-opacity duration-200 motion-reduce:transition-none dark:from-marinho-950 ${posicao} ${
        visivel ? "opacity-100" : "opacity-0"}`}
    />
  );
}

/** Seta que avisa que há itens escondidos naquele lado da lista do menu (com a janela
 *  baixa um item pode ficar todo escondido, e o esmaecido sozinho quase não se nota).
 *  Fica FORA da área que rola, numa faixa de 8 px na folga entre a lista e o cabeçalho
 *  (topo) ou o rodapé (base) — onde não há texto. Dentro da lista, presa à borda, ela
 *  caía em cima do rótulo que passava ali ("Regras de⌄pontuação" numa janela de 768 px
 *  com todos os grupos abertos). Decorativa. */
function SetaRolagem({ lado, visivel }: { lado: "topo" | "base"; visivel: boolean }) {
  return (
    <div
      aria-hidden
      data-seta={lado}
      data-visivel={visivel ? "sim" : "nao"}
      className={`pointer-events-none absolute inset-x-0 z-10 flex h-2 items-center justify-center transition-opacity duration-200 motion-reduce:transition-none ${
        lado === "topo" ? "top-0 -translate-y-full" : "bottom-0 translate-y-full"
      } ${visivel ? "opacity-100" : "opacity-0"}`}
    >
      {lado === "topo"
        ? <ChevronUp size={16} className="shrink-0 text-marinho-300" />
        : <ChevronDown size={16} className="shrink-0 text-marinho-300" />}
    </div>
  );
}

/** A lista do menu com as setas de rolagem por fora dela (ver `SetaRolagem`). */
function ListaComSetas({ acima, abaixo, children }: { acima: boolean; abaixo: boolean; children: ReactNode }) {
  return (
    <div className="relative flex min-h-0 flex-1 flex-col">
      <SetaRolagem lado="topo" visivel={acima} />
      {children}
      <SetaRolagem lado="base" visivel={abaixo} />
    </div>
  );
}

/** Um item na barra recolhida (só ícone, nome no tooltip). `ativo`: a mesma regra do
 *  menu aberto (`itemAtivo`). */
function IconeMenu({ item, ativo, atalho, selo }: {
  item: ItemNav;
  ativo: boolean;
  atalho?: () => void;
  selo?: SeloMenu | null;
}) {
  const idSelo = useId();
  const { pathname, search } = useLocation();
  const classe = "relative mx-auto flex h-11 w-11 items-center justify-center rounded-xl transition-colors";
  const inativo = "text-marinho-200 hover:bg-white/[0.07] hover:text-white";
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
        <item.icone size={19} strokeWidth={2} aria-hidden />
      </a>
    );
  }
  return (
    <>
      <Link
        to={destinoDoItem(item, pathname, search)}
        title={selo ? `${item.rotulo} · ${selo.completo}` : item.rotulo}
        aria-label={item.rotulo}
        aria-current={ativo ? "page" : undefined}
        aria-describedby={selo ? idSelo : undefined}
        onClick={atalho}
        className={`${classe} ${ativo ? "bg-indigo-600 text-white shadow-pilula" : inativo}`}
      >
        <item.icone size={19} strokeWidth={2} aria-hidden />
        {selo && (
          <span aria-hidden className="absolute right-1 top-1 h-2.5 w-2.5 rounded-full bg-ouro-400 ring-2 ring-marinho-900" />
        )}
      </Link>
      {selo && <span id={idSelo} hidden>{selo.completo}</span>}
    </>
  );
}

/** Navegação RECOLHIDA (só ícones, desktop) — PRD §14. Achata a sidebar do
 *  perfil numa lista de ícones: todos os destinos que o perfil já podia abrir
 *  seguem a um clique, com o nome no tooltip. Sem grupos/accordion (não cabem
 *  na barra estreita), mas nada some — é só a versão compacta do mesmo menu.
 *  Um fio separa as seções do perfil (a barra estreita não tem os títulos). */
function NavegacaoRail() {
  const perfil = usePerfil();
  const primeiroAcesso = usePrimeiroAcesso();
  const { modulos: modulosRail } = useModulos();
  const { pathname, search } = useLocation();
  const grupos = sidebarDoPerfil(perfil, modulosRail);
  const { escolaId } = useApp();
  const calendario = useCalendarioBimestres(escolaId);
  const selo = seloDoBimestre(new Date(), calendario);
  // Primeiro acesso: o MESMO recorte do menu aberto — só "Comece aqui" (e, para o Admin
  // Global, os cadastros que não dependem da escola). Antes a barra recolhida ignorava o
  // primeiro acesso e mostrava o menu inteiro de uma escola ainda vazia.
  const blocos: ItemNav[][] = primeiroAcesso
    ? [[COMECAR], ...(perfil.global ? [PRIMEIRO_ACESSO_GLOBAL] : [])]
    : secoesDoPerfil(perfil)
      .map((secao) => grupos.filter((g) => g.secao === secao.chave).flatMap((g) => g.itens))
      .filter((itens) => itens.length > 0);
  const todos = blocos.flat();
  const refNav = useRef<HTMLElement | null>(null);
  const { inicio: acima, fim: abaixo } = useBordasDaRolagem(refNav, "y");
  return (
    <ListaComSetas acima={acima} abaixo={abaixo}>
      <nav ref={refNav} aria-label="Menu principal" className={`${CLASSE_NAV} !px-2`}>
        <DegradeRolagem lado="topo" visivel={acima} recuo="-mx-2" />
        <div className="space-y-1">
          {blocos.map((itens, i) => (
            <Fragment key={itens[0]?.caminho ?? i}>
              {i > 0 && <div aria-hidden data-divisoria="secao" className="mx-3 my-3 border-t border-white/10" />}
              {itens.map((item) => (
                <IconeMenu key={item.caminho} item={item} ativo={itemAtivo(item, pathname, search, todos)}
                           selo={seloDoItem(item, selo)} />
              ))}
            </Fragment>
          ))}
        </div>
        <DegradeRolagem lado="base" visivel={abaixo} recuo="-mx-2" />
      </nav>
    </ListaComSetas>
  );
}

const ROTULO_MARCA = "Ir para a página inicial";

function Marca({ aoNavegar }: { aoNavegar?: () => void }) {
  return (
    // Clicar na marca volta para a página inicial do perfil.
    <NavLink
      to="/"
      onClick={aoNavegar}
      aria-label={ROTULO_MARCA}
      className="flex min-w-0 items-center rounded-xl px-1.5 py-1 transition-opacity hover:opacity-90"
    >
      <LogoHorizontal altura={36} sobreEscuro />
    </NavLink>
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
      className="fixed bottom-4 right-4 z-20 flex items-center gap-2.5 rounded-full border border-indigo-100 bg-white px-4 py-2.5 text-sm font-semibold text-indigo-700 shadow-flutuante transition-colors hover:bg-indigo-50 dark:border-indigo-500/30 dark:bg-zinc-900 dark:text-indigo-300 dark:hover:bg-zinc-800"
    >
      {emAndamento ? (
        <span className="h-3.5 w-3.5 shrink-0 animate-spin rounded-full border-2 border-indigo-200 border-t-indigo-600 motion-reduce:animate-none" />
      ) : (
        <Upload size={14} className="shrink-0" aria-hidden />
      )}
      {rotulo}
    </NavLink>
  );
}

/** Trilha/contexto no topo (PRD §11): "onde estou", em três níveis — Início › Contexto ›
 *  Página. O contexto é o GRUPO (acordeão) do item ativo ou, se o item é solto, a SEÇÃO:
 *  o mesmo caminho que a pessoa faz no menu. Some quando repetiria a página. Só a partir
 *  de 1024 px — no celular o próprio título da página já orienta, e o topo é curto. */
function Trilha() {
  const { pathname, search } = useLocation();
  const perfil = usePerfil();
  const { modulos } = useModulos();
  // O nome da página é o do item do menu de CADA perfil: /metricas é "Critérios" para os
  // dois (D4); /rede/avaliacoes é "Importações e fontes" para o global (que importa ali)
  // e "Fontes dos indicadores" para a Secretaria (o detalhe das Avaliações externas, sem
  // item próprio); a tela das plataformas, o nome das que a rede contratou.
  const contexto = contextoDaRota(sidebarDoPerfil(perfil, modulos), pathname, search);
  const titulo = tituloDaRota(pathname, contexto?.item ?? null, modulos);
  const meio = !contexto ? ""
    : ehSolto(contexto.grupo)
      ? secoesDoPerfil(perfil).find((s) => s.chave === contexto.grupo.secao)?.rotulo ?? ""
      : contexto.grupo.rotulo;
  const naHome = pathname === "/";
  const inicio = rotuloDashboard(perfil);
  // Largura: a trilha ocupa o tamanho do próprio texto (flex-initial) e quem cede
  // espaço primeiro é a pesquisa (de 20rem até 13rem). Só depois a trilha corta, e
  // corta antes o primeiro nível (encolhe 4×), depois o contexto (2×) e por último o
  // nome da página atual. Os três têm o texto inteiro no title.
  return (
    <nav aria-label="Trilha de navegação" className="hidden min-w-0 flex-initial items-center gap-1.5 text-sm lg:flex">
      <NavLink
        to="/"
        title={inicio}
        className={({ isActive }) =>
          `min-w-0 shrink-[4] truncate rounded-md ${isActive
            ? "font-semibold text-zinc-900 dark:text-white"
            : "font-medium text-zinc-500 transition-colors hover:text-indigo-700 dark:text-zinc-400 dark:hover:text-indigo-300"}`
        }
      >
        {inicio}
      </NavLink>
      {!naHome && titulo && (
        <>
          {meio && meio !== titulo && (
            <>
              <ChevronRight size={15} className="shrink-0 text-zinc-400" aria-hidden />
              <span data-trilha="contexto" className="min-w-0 shrink-[2] truncate font-medium text-zinc-500 dark:text-zinc-400"
                    title={meio}>{meio}</span>
            </>
          )}
          <ChevronRight size={15} className="shrink-0 text-zinc-400" aria-hidden />
          <span data-trilha="pagina" className="min-w-0 truncate font-semibold text-zinc-900 dark:text-white"
                title={titulo}>{titulo}</span>
        </>
      )}
    </nav>
  );
}

/** Nome amigável do perfil (cartão e menu do usuário). */
function rotuloPerfil(u: { is_global?: boolean; rede_id?: number | null; cargo?: string } | null | undefined): string {
  if (!u) return "";
  if (u.is_global) return "Admin Global";
  if (u.rede_id != null) return "Secretaria";
  if (u.cargo === "coordenador") return "Coordenação";
  if (u.cargo === "admin") return "Administração";
  return "Professor(a)";
}

/** Menu do usuário (cartão com avatar → conta + sair), no rodapé da barra. Reúne
 *  identidade, atalho para a própria conta e logout num só lugar (PRD §11). O
 *  atalho aponta para /minha-conta (autoatendimento, reusa /auth/me) — funciona
 *  para QUALQUER perfil, inclusive a Secretaria, que não tem escola e não abre
 *  /usuarios. Na barra recolhida vira só o avatar (o menu abre ao lado). */
function MenuUsuario({ compacto = false }: { compacto?: boolean }) {
  const { usuario, sair } = useApp();
  const [aberto, setAberto] = useState(false);
  const caixa = useRef<HTMLDivElement | null>(null);
  const botao = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    function fechar(evento: MouseEvent) {
      if (caixa.current && !caixa.current.contains(evento.target as Node)) setAberto(false);
    }
    document.addEventListener("mousedown", fechar);
    return () => document.removeEventListener("mousedown", fechar);
  }, []);

  // Esc fecha e devolve o foco ao botão (padrão de menu). Em CAPTURA e com
  // preventDefault: dentro da gaveta do celular, o ouvinte dela (bolha, no
  // document) vê o Esc já tratado e não fecha a gaveta inteira junto.
  useEffect(() => {
    if (!aberto) return;
    const aoTeclar = (evento: KeyboardEvent) => {
      if (evento.key !== "Escape") return;
      evento.preventDefault();
      setAberto(false);
      botao.current?.focus();
    };
    document.addEventListener("keydown", aoTeclar, true);
    return () => document.removeEventListener("keydown", aoTeclar, true);
  }, [aberto]);

  const papel = rotuloPerfil(usuario);

  return (
    <div className="relative" ref={caixa}>
      <button
        ref={botao}
        type="button"
        aria-haspopup="menu"
        aria-expanded={aberto}
        aria-label="Menu do usuário"
        title={compacto ? usuario?.nome : undefined}
        onClick={() => setAberto((a) => !a)}
        className={compacto
          ? "mx-auto grid h-11 w-11 place-items-center rounded-xl transition-colors hover:bg-white/[0.07]"
          : "flex w-full items-center gap-3 rounded-2xl p-2 text-left transition-colors hover:bg-white/[0.07]"}
      >
        <Avatar nome={usuario?.nome} chave={usuario?.id ?? usuario?.nome ?? "?"} className="!ring-marinho-800" />
        {!compacto && (
          <>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-sm font-semibold text-white" title={usuario?.nome}>{usuario?.nome}</span>
              {papel && <span className="block truncate text-xs text-marinho-300" title={papel}>{papel}</span>}
            </span>
            <ChevronsUpDown size={16} aria-hidden className="shrink-0 text-marinho-400" />
          </>
        )}
      </button>

      {aberto && (
        <div
          role="menu"
          className={`absolute z-50 w-64 overflow-hidden rounded-2xl border border-zinc-200/80 bg-white shadow-flutuante dark:border-zinc-700 dark:bg-zinc-900 ${
            compacto ? "bottom-0 left-full ml-3" : "bottom-full left-0 mb-2"
          }`}
        >
          <div className="flex items-center gap-3 border-b border-zinc-100 px-4 py-3 dark:border-zinc-800">
            <Avatar nome={usuario?.nome} chave={usuario?.id ?? usuario?.nome ?? "?"} tamanho="sm" />
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold text-zinc-900 dark:text-zinc-100" title={usuario?.nome}>{usuario?.nome}</p>
              <p className="mt-0.5 truncate text-xs text-zinc-500 dark:text-zinc-400" title={papel}>{papel}</p>
            </div>
          </div>
          <div className="p-1.5">
            {/* Autoatendimento: SÓ a própria conta (/minha-conta, reusa /auth/me),
                para qualquer perfil — inclusive Secretaria. A GESTÃO de usuários
                (/usuarios) segue na sidebar, exclusiva de coordenador/admin. */}
            <NavLink
              to="/minha-conta"
              role="menuitem"
              onClick={() => setAberto(false)}
              className="flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium text-zinc-700 transition-colors hover:bg-zinc-50 dark:text-zinc-200 dark:hover:bg-zinc-800"
            >
              <UserCog size={17} className="shrink-0 text-zinc-500 dark:text-zinc-400" aria-hidden />
              <span className="truncate">Minha conta</span>
            </NavLink>
            <button
              type="button"
              role="menuitem"
              onClick={() => { setAberto(false); sair(); }}
              className="flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium text-rose-600 transition-colors hover:bg-rose-50 dark:text-rose-400 dark:hover:bg-rose-500/10"
            >
              <LogOut size={17} className="shrink-0" aria-hidden />
              <span>Sair</span>
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

/** Símbolo da escola no cartão: o brasão cadastrado (logotipo_url) ou um ícone. Se a
 *  imagem não carregar, volta ao ícone (nada de imagem quebrada). */
function SimboloEscola({ url, rede }: { url: string | null | undefined; rede: boolean }) {
  const [falhou, setFalhou] = useState<string | null>(null);
  if (url && falhou !== url) {
    return (
      <img
        src={url}
        alt=""
        onError={() => setFalhou(url)}
        className="h-10 w-10 shrink-0 rounded-xl bg-white object-contain p-1"
      />
    );
  }
  const Icone = rede ? Landmark : School;
  return (
    <span aria-hidden className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-indigo-500/20 text-indigo-200">
      <Icone size={19} strokeWidth={2} />
    </span>
  );
}

/** Telas que dependem da escola escolhida (com as sub-rotas): a Secretaria que volta a
 *  "Toda a Rede Municipal" numa delas é levada ao Panorama da Rede. Só as que ela ABRE
 *  (RotaGestao): Turmas, Professores, Simulador e o Catálogo de Livros são RotaEscolaOp, e
 *  o App a manda ao Dashboard antes de o Layout montar. */
const TELAS_DA_ESCOLA = ["/escola", "/metricas"];
const ehTelaDaEscola = (pathname: string): boolean =>
  TELAS_DA_ESCOLA.some((r) => pathname === r || pathname.startsWith(`${r}/`));

/** Telas da Secretaria que LEEM o contexto no lugar: escolher uma escola nelas só grava o
 *  contexto, sem ir para a ficha — o Suporte mostra ali a regra da nota da escola escolhida. */
const LEEM_O_CONTEXTO_NO_LUGAR = ["/suporte"];

/** Cartão ESCOLA do rodapé da barra: o seletor de CONTEXTO de todas as telas (antes
 *  no cabeçalho). Para a Secretaria: "Toda a Rede Municipal" (padrão) + as escolas da
 *  rede; escolher uma escola leva à FICHA dela (/rede/escolas/{id}) — menos nas telas que
 *  leem o contexto no lugar (`LEEM_O_CONTEXTO_NO_LUGAR`: o Suporte), onde só grava — e "Toda
 *  a Rede Municipal", numa tela de escola (`TELAS_DA_ESCOLA`), leva ao Panorama da Rede — fora
 *  delas, fica onde está (DESENHO3 §1). O contexto continua gravado como antes: a Visão da
 *  Escola e as telas de escola leem dele. Para os demais perfis é a troca rápida de escola
 *  de sempre. Uma escola no contexto que NÃO está na lista (ex.: inativa, fora do `/escolas`)
 *  vira uma opção própria ("Escola nº 9 (fora da lista)"): o cartão nunca diz "Toda a Rede
 *  Municipal" com uma escola escolhida, e voltar à rede dispara a troca. O <select> continua
 *  NATIVO, com os mesmos aria-label e opções, mas transparente e esticado sobre o cartão inteiro (o clique em qualquer ponto abre a
 *  lista): o que se VÊ é o nome em até duas linhas (um <select> não quebra linha e cortava
 *  quase todo nome de escola), com o texto inteiro no title. O foco do teclado aparece no
 *  contorno do cartão. Na barra recolhida vira um botão que expande o menu. */
function CartaoEscola({ compacto = false, aoExpandir }: { compacto?: boolean; aoExpandir?: () => void }) {
  const { escolas, escolaId, selecionarEscola } = useApp();
  const { secretaria } = usePerfil();
  const navegar = useNavigate();
  const { pathname } = useLocation();
  if (!secretaria && escolas.length === 0) return null;
  const atual = escolas.find((e) => e.id === escolaId) ?? null;
  // Escola no contexto que não está na lista: nome próprio (nunca "Toda a Rede Municipal").
  const foraDaLista = escolaId != null && !atual ? `Escola nº ${escolaId} (fora da lista)` : null;
  const rotulo = secretaria ? "Contexto" : "Escola";
  const nomeAtual = atual?.nome ?? foraDaLista ?? (secretaria ? "Toda a Rede Municipal" : "");
  // O ícone da rede só com a rede mesmo (sem escola nenhuma no contexto).
  const naRede = secretaria && escolaId == null;

  if (compacto) {
    return (
      <button
        type="button"
        onClick={aoExpandir}
        aria-label={`${rotulo}: ${nomeAtual}. Expandir o menu para trocar`}
        title={`${rotulo}: ${nomeAtual}`}
        className="mx-auto grid h-11 w-11 place-items-center rounded-xl text-marinho-200 transition-colors hover:bg-white/[0.07] hover:text-white"
      >
        {naRede ? <Landmark size={19} aria-hidden /> : <School size={19} aria-hidden />}
      </button>
    );
  }

  return (
    <div className="relative flex items-center gap-3 rounded-2xl bg-white/[0.06] p-3 ring-1 ring-inset ring-white/10 transition-colors hover:bg-white/[0.09]">
      <SimboloEscola url={atual?.logotipo_url} rede={naRede} />
      {/* Só visual: o leitor de tela ouve o rótulo e o valor do <select> abaixo. */}
      <div aria-hidden className="min-w-0 flex-1 pr-5">
        <p className="text-[11px] font-semibold uppercase tracking-[0.1em] text-marinho-300">{rotulo}</p>
        <p data-testid="cartao-escola-nome" className="line-clamp-2 break-words text-sm font-semibold leading-snug text-white">
          {nomeAtual}
        </p>
      </div>
      <ChevronDown
        size={15}
        aria-hidden
        className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-marinho-300"
      />
      <select
        aria-label={secretaria ? "Contexto de visualização" : "Escola selecionada"}
        title={nomeAtual}
        className="peer absolute inset-0 h-full w-full cursor-pointer appearance-none rounded-2xl opacity-0 [&>option]:bg-white [&>option]:text-zinc-900 dark:[&>option]:bg-zinc-900 dark:[&>option]:text-zinc-100"
        value={escolaId ?? ""}
        onChange={(evento) => {
          const v = evento.target.value;
          const id = v === "" ? null : Number(v);
          selecionarEscola(id);
          if (!secretaria) return;
          if (id != null) {
            if (!LEEM_O_CONTEXTO_NO_LUGAR.includes(pathname)) navegar(`/rede/escolas/${id}`);
          } else if (ehTelaDaEscola(pathname)) navegar("/");
        }}
      >
        {/* Sem emoji no texto: o ícone do cartão já diz que é a rede, e o nome cabe. */}
        {secretaria && <option value="">Toda a Rede Municipal</option>}
        {foraDaLista && <option value={escolaId ?? ""}>{foraDaLista}</option>}
        {escolas.map((escola) => (
          <option key={escola.id} value={escola.id}>
            {escola.nome}
          </option>
        ))}
      </select>
      {/* Foco do teclado: o <select> é transparente (opacity-0), então o contorno vem
          deste irmão (peer), que funciona em qualquer navegador (sem :has()). */}
      <span
        aria-hidden
        className="pointer-events-none absolute inset-0 rounded-2xl peer-focus-visible:outline peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-indigo-400"
      />
    </div>
  );
}

/** Rodapé da barra (fixo, fora da rolagem do menu): Suporte, cartão ESCOLA e o
 *  cartão do usuário. */
function RodapeBarra({ compacto = false, aoExpandir, aoNavegar }: {
  compacto?: boolean;
  aoExpandir?: () => void;
  aoNavegar?: () => void;
}) {
  const { pathname, search } = useLocation();
  const suporteAtivo = itemAtivo(SUPORTE, pathname, search, []);
  return (
    <div className={`space-y-2 border-t border-white/10 pb-safe ${compacto ? "px-2 py-3" : "px-3 py-3"}`}>
      {/* Suporte: para TODOS os papéis (professor, coordenador, secretaria, admin). */}
      {compacto
        ? <IconeMenu item={SUPORTE} ativo={suporteAtivo} />
        : <LinkMenu item={SUPORTE} ativo={suporteAtivo} aoNavegar={aoNavegar} />}
      <CartaoEscola compacto={compacto} aoExpandir={aoExpandir} />
      <MenuUsuario compacto={compacto} />
    </div>
  );
}

const CHAVE_RECOLHIDO = "constela_menu_recolhido";
/** A partir daqui (o `xl` do Tailwind) a barra lateral fixa aparece e a gaveta some (`xl:hidden`).
 *  Entre 1024 e 1279 px (tablet deitado, notebook pequeno) a navegação fica na gaveta e o
 *  conteúdo ganha a largura toda (~960 px, o mesmo do notebook de 1280 px com a barra). */
const MEDIA_DESKTOP = "(min-width: 1280px)";

/** Chama `aoMudar` quando a tela passa a ter (ou deixa de ter) a largura do desktop. */
function assinarLarguraDesktop(aoMudar: (desktop: boolean) => void): () => void {
  const consulta = window.matchMedia?.(MEDIA_DESKTOP);
  if (!consulta) return () => undefined;
  const ouvinte = () => aoMudar(consulta.matches);
  ouvinte();
  if (consulta.addEventListener) {
    consulta.addEventListener("change", ouvinte);
    return () => consulta.removeEventListener("change", ouvinte);
  }
  // Safari < 14 (tablets antigos das escolas) só tem addListener.
  consulta.addListener(ouvinte);
  return () => consulta.removeListener(ouvinte);
}

/** Botão pequeno da barra marinho (recolher/expandir/fechar). */
const BOTAO_BARRA =
  "grid h-9 w-9 shrink-0 place-items-center rounded-xl text-marinho-300 transition-colors hover:bg-white/[0.08] hover:text-white";

export default function Layout() {
  const { tema, alternarTema } = useApp();
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
  const botaoAbrirMenu = useRef<HTMLButtonElement | null>(null);
  const gaveta = useRef<HTMLElement | null>(null);
  const conteudo = useRef<HTMLElement | null>(null);
  const { pathname, search } = useLocation();

  // A ROTA mudou (endereço ou consulta) com a gaveta aberta: fecha. Antes só os links do
  // menu fechavam (`aoNavegar`); "Minha conta" no menu do usuário, um atalho Alt+1..0 ou a
  // pesquisa global trocavam a página com o diálogo modal ainda por cima — rolagem do fundo
  // travada e Tab preso nele até um "Fechar menu" ou Esc. Fechar por aqui passa pela mesma
  // limpeza do efeito abaixo (solta a rolagem e o Tab, devolve o foco ao "Abrir menu"); o
  // Esc não muda a rota, então continua fechando só pelo ouvinte dele. Navegação REPLACE é a
  // própria página reescrevendo a consulta (a análise grava `?escola=` quando os dados
  // chegam), não a pessoa indo a outro lugar: não fecha a gaveta que ela acabou de abrir.
  const tipoNavegacao = useNavigationType();
  useEffect(() => {
    if (tipoNavegacao !== "REPLACE") setMenuAberto(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- só a troca de rota dispara; o tipo é o dela
  }, [pathname, search]);

  // Menu aberto no celular: trava o scroll do fundo e fecha no Esc (evita o
  // "scroll fantasma" atrás do drawer no Safari do iPhone). Gaveta = diálogo modal
  // para o teclado: o foco entra nela ao abrir, o Tab fica preso dentro dela (sem
  // isso ele seguia pelos controles do topo, ESCONDIDOS atrás do véu) e volta ao
  // botão "Abrir menu" ao fechar.
  useEffect(() => {
    if (!menuAberto) return;
    const anterior = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const focaveis = () => [...(gaveta.current?.querySelectorAll<HTMLElement>(
      "a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex='-1'])",
    ) ?? [])].filter((el) => getComputedStyle(el).visibility !== "hidden");
    focaveis()[0]?.focus();
    const aoTeclar = (evento: KeyboardEvent) => {
      // Esc já tratado (menu do usuário aberto dentro da gaveta): fecha só o menu.
      if (evento.key === "Escape" && !evento.defaultPrevented) setMenuAberto(false);
      if (evento.key !== "Tab") return;
      const lista = focaveis();
      if (lista.length === 0) return;
      const primeiro = lista[0];
      const ultimo = lista[lista.length - 1];
      const atual = document.activeElement;
      const fora = !gaveta.current?.contains(atual);
      if (evento.shiftKey && (atual === primeiro || fora)) {
        evento.preventDefault();
        ultimo.focus();
      } else if (!evento.shiftKey && (atual === ultimo || fora)) {
        evento.preventDefault();
        primeiro.focus();
      }
    };
    document.addEventListener("keydown", aoTeclar);
    // A gaveta só existe abaixo de 1280 px. Girar o tablet ou alargar a janela com
    // ela aberta a escondia (display:none) sem fechar: a trava do Tab seguia
    // mandando o foco para links invisíveis — nenhum Tab andava na página até um
    // Esc — e a rolagem do fundo continuava travada. Na largura do desktop, fecha.
    const pararDeOuvirLargura = assinarLarguraDesktop((desktop) => {
      if (desktop) setMenuAberto(false);
    });
    const abridor = botaoAbrirMenu.current;
    return () => {
      document.body.style.overflow = anterior;
      document.removeEventListener("keydown", aoTeclar);
      pararDeOuvirLargura();
      abridor?.focus();
    };
  }, [menuAberto]);

  /** "Pular para o conteúdo": leva o foco ao <main> sem mexer no endereço (um
   *  #conteudo na URL entraria no histórico do roteador). */
  function pularParaConteudo(evento: ReactMouseEvent<HTMLAnchorElement>) {
    evento.preventDefault();
    conteudo.current?.focus();
    conteudo.current?.scrollIntoView({ block: "start" });
  }

  const fecharGaveta = () => setMenuAberto(false);

  return (
    <div className="min-h-screen">
      {/* 1º Tab da página: pula o menu inteiro (dezenas de links) direto para o
          conteúdo — WCAG 2.4.1. Invisível até receber o foco. */}
      <a
        href="#conteudo"
        onClick={pularParaConteudo}
        className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-50 focus:rounded-xl focus:bg-white focus:px-4 focus:py-2 focus:text-sm focus:font-semibold focus:text-indigo-700 focus:shadow-flutuante dark:focus:bg-zinc-900 dark:focus:text-indigo-300"
      >
        Pular para o conteúdo
      </a>
      {/* Sidebar fixa (desktop), marinho — recolhível para SÓ ÍCONES (PRD §14): a
          barra fica estreita mas todos os destinos continuam a um clique, com o
          nome no tooltip; não some a navegação, só encolhe. */}
      <aside
        className={`fixed inset-y-0 left-0 z-30 hidden flex-col bg-marinho-900 pl-safe transition-[width] duration-200 motion-reduce:transition-none dark:border-r dark:border-white/5 dark:bg-marinho-950 xl:flex ${
          recolhido ? "w-[76px]" : "w-64"
        }`}
      >
        {recolhido ? (
          <div className="flex flex-col items-center gap-2 px-2 pb-2 pt-5">
            <NavLink to="/" aria-label={ROTULO_MARCA} className="grid h-11 w-11 place-items-center rounded-xl hover:bg-white/[0.07]">
              <Logo tamanho={30} sobreEscuro alt="" />
            </NavLink>
            <button aria-label="Expandir menu" title="Expandir menu" className={BOTAO_BARRA} onClick={alternarRecolhido}>
              <PanelLeftOpen size={18} aria-hidden />
            </button>
          </div>
        ) : (
          <div className="flex items-center justify-between gap-2 px-4 pb-4 pt-5">
            <Marca />
            <button aria-label="Recolher menu" title="Recolher menu" className={BOTAO_BARRA} onClick={alternarRecolhido}>
              <PanelLeftClose size={18} aria-hidden />
            </button>
          </div>
        )}
        {recolhido ? <NavegacaoRail /> : <Navegacao />}
        <RodapeBarra compacto={recolhido} aoExpandir={alternarRecolhido} />
      </aside>

      {/* Sidebar deslizante (celular/tablet), no mesmo estilo marinho — botões
          reais, resposta imediata ao toque (PRD §9) */}
      {menuAberto && (
        <div className="fixed inset-0 z-40 xl:hidden">
          {/* Véu: só para o toque/clique fora. Fora do Tab e do leitor de tela — o
              "Fechar menu" acessível é o botão dentro da gaveta (eram dois iguais). */}
          <button
            type="button"
            tabIndex={-1}
            aria-hidden="true"
            className="absolute inset-0 bg-marinho-950/50 backdrop-blur-[2px]"
            onClick={fecharGaveta}
          />
          <aside
            ref={gaveta}
            role="dialog"
            aria-modal="true"
            aria-label="Menu de navegação"
            className="absolute inset-y-0 left-0 flex w-72 max-w-[85vw] flex-col bg-marinho-900 pl-safe pt-safe shadow-flutuante dark:bg-marinho-950"
          >
            <div className="flex items-center justify-between gap-2 px-4 pb-4 pt-5">
              <Marca aoNavegar={fecharGaveta} />
              <button aria-label="Fechar menu" className={BOTAO_BARRA} onClick={fecharGaveta}>
                <X size={18} aria-hidden />
              </button>
            </div>
            <Navegacao aoNavegar={fecharGaveta} />
            <RodapeBarra aoNavegar={fecharGaveta} />
          </aside>
        </div>
      )}

      <div className={`transition-[padding] duration-200 motion-reduce:transition-none ${recolhido ? "xl:pl-[76px]" : "xl:pl-64"}`}>
        {/* Cabeçalho TRANSPARENTE sobre a lavanda (sem borda): só um véu translúcido
            com desfoque para o conteúdo que rola por baixo não brigar com os botões.
            Respiro no topo: base + a área segura do notch. */}
        <header
          style={{ paddingTop: "calc(env(safe-area-inset-top) + 1.25rem)" }}
          className="sticky top-0 z-20 bg-zinc-50/85 pb-3 pr-safe backdrop-blur-md dark:bg-zinc-950/80"
        >
          <div className="mx-auto flex max-w-7xl items-center gap-3 px-4 sm:px-6 lg:px-8">
            <button
              ref={botaoAbrirMenu}
              aria-label="Abrir menu"
              aria-expanded={menuAberto}
              aria-haspopup="dialog"
              className="grid h-10 w-10 shrink-0 place-items-center rounded-full border border-zinc-200/80 bg-white text-zinc-600 shadow-cartao transition-colors hover:text-indigo-600 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300 dark:hover:text-indigo-300 xl:hidden"
              onClick={() => setMenuAberto(true)}
            >
              <Menu size={18} aria-hidden />
            </button>
            <Trilha />

            <div className="flex min-w-0 flex-1 items-center justify-end gap-2.5 lg:min-w-min">
              <PesquisaGlobal />
              <Notificacoes />
              <BotaoIcone
                rotulo={tema === "claro" ? "Ativar modo escuro" : "Ativar modo claro"}
                onClick={alternarTema}
              >
                {tema === "claro" ? <Moon size={18} aria-hidden /> : <Sun size={18} aria-hidden />}
              </BotaoIcone>
            </div>
          </div>
        </header>

        {/* tabIndex -1: alvo do "Pular para o conteúdo" (recebe foco por script,
            não entra no Tab). Sem contorno: o foco aqui é só um ponto de partida. */}
        <main id="conteudo" ref={conteudo} tabIndex={-1}
          className="mx-auto max-w-7xl px-4 py-8 focus:outline-none focus-visible:ring-0 sm:px-6 lg:px-8">
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
