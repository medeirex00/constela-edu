import { Suspense, lazy } from "react";
import { Navigate, Route, Routes } from "react-router-dom";

import Layout from "./components/Layout";
import { Botao, Carregando } from "./components/ui";
import { useApp } from "./context/AppContext";
import { ImportacaoLoteProvider } from "./context/ImportacaoLoteContext";
import { usePerfil } from "./hooks/usePerfil";

// Code-splitting por rota: cada página vira um chunk próprio, carregado sob
// demanda. Assim as rotas públicas (/p/:token) e o /login não baixam o app
// administrativo inteiro, e cada navegação traz só o chunk da página.
// Layout, AppContext e lib ficam no chunk principal (o "shell").
const Alunos = lazy(() => import("./pages/Alunos"));
const Assistente = lazy(() => import("./pages/Assistente"));
const BibliotecaConquistas = lazy(() => import("./pages/BibliotecaConquistas"));
const Comecar = lazy(() => import("./pages/Comecar"));
const Comparador = lazy(() => import("./pages/Comparador"));
const Insights = lazy(() => import("./pages/Insights"));
const Conquistas = lazy(() => import("./pages/Conquistas"));
const Dashboard = lazy(() => import("./pages/Dashboard"));
const Elefante = lazy(() => import("./pages/Elefante"));
const EvolucaoAluno = lazy(() => import("./pages/EvolucaoAluno"));
const Importacoes = lazy(() => import("./pages/Importacoes"));
// Export nomeado -> adapta para o default que o lazy() espera.
const Professores = lazy(() =>
  import("./pages/ListasSimples").then((m) => ({ default: m.Professores })));
const Livros = lazy(() => import("./pages/Livros"));
const Login = lazy(() => import("./pages/Login"));
const Matific = lazy(() => import("./pages/Matific"));
const PainelPublicoConfig = lazy(() => import("./pages/PainelPublicoConfig"));
const PerfilAluno = lazy(() => import("./pages/PerfilAluno"));
const Premiacoes = lazy(() => import("./pages/Premiacoes"));
const RedefinirSenha = lazy(() => import("./pages/RedefinirSenha"));
const PainelPublico = lazy(() => import("./pages/publico/PainelPublico"));
const PainelPublicoRede = lazy(() => import("./pages/publico/PainelPublicoRede"));
const PerfilPublico = lazy(() => import("./pages/publico/PerfilPublico"));
const Rankings = lazy(() => import("./pages/Rankings"));
const RedeDashboard = lazy(() => import("./pages/rede/RedeDashboard"));
const RedeGestao = lazy(() => import("./pages/rede/RedeGestao"));
const RedeAvaliacoes = lazy(() => import("./pages/rede/RedeAvaliacoes"));
const Relatorios = lazy(() => import("./pages/Relatorios"));
const Escolas = lazy(() => import("./pages/Escolas"));
const SessoesAtivas = lazy(() => import("./pages/SessoesAtivas"));
const Simulador = lazy(() => import("./pages/Simulador"));
const Sincronizacao = lazy(() => import("./pages/Sincronizacao"));
const DiagnosticoElefante = lazy(() => import("./pages/DiagnosticoElefante"));
const TurmaDetalhe = lazy(() => import("./pages/TurmaDetalhe"));
const Turmas = lazy(() => import("./pages/Turmas"));
const Usuarios = lazy(() => import("./pages/Usuarios"));
const VisaoEscola = lazy(() => import("./pages/VisaoEscola"));
const ConfigConquistas = lazy(() => import("./pages/configuracoes/ConfigConquistas"));
const Configuracoes = lazy(() => import("./pages/configuracoes/Configuracoes"));
const Metricas = lazy(() => import("./pages/configuracoes/Metricas"));

function ReconectarSessao({ aoTentar }: { aoTentar: () => void }) {
  // Falha transitória ao abrir a sessão: o token continua válido, então
  // oferecemos reconectar em vez de mandar a pessoa refazer o login.
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-4 p-6 text-center">
      <p className="text-lg font-medium">Não consegui conectar ao servidor.</p>
      <p className="max-w-sm text-sm text-zinc-500 dark:text-zinc-400">
        Sua sessão continua válida — pode ter sido uma queda momentânea de rede
        ou o servidor iniciando. Tente novamente.
      </p>
      <Botao onClick={aoTentar}>Tentar de novo</Botao>
    </div>
  );
}

function AreaProtegida() {
  const { usuario, carregando, falhaSessao, tentarReconectar } = useApp();
  if (carregando) return <Carregando texto="Abrindo o sistema..." />;
  if (falhaSessao && !usuario) return <ReconectarSessao aoTentar={tentarReconectar} />;
  if (!usuario) return <Navigate to="/login" replace />;
  // Provider acima do Layout/rotas: a importação em lote segue rodando
  // enquanto o usuário navega (indicador flutuante no Layout).
  return (
    <ImportacaoLoteProvider>
      <Layout />
    </ImportacaoLoteProvider>
  );
}

/** Trava de ROTA por cargo (defesa em profundidade além do menu e do backend):
 *  o professor que digitar a URL — ou chegar por um link — de uma tela de GESTÃO
 *  é mandado de volta ao Dashboard, em vez de abrir a tela com botões de admin
 *  (ex.: importar Lista Piloto). O backend continua sendo a trava real dos dados. */
function RotaGestao({ children }: { children: React.ReactNode }) {
  const { gestor } = usePerfil();
  return gestor ? <>{children}</> : <Navigate to="/" replace />;
}

/** Só administrador GLOBAL (gestão de todas as escolas). */
function RotaGlobal({ children }: { children: React.ReactNode }) {
  const { global } = usePerfil();
  return global ? <>{children}</> : <Navigate to="/" replace />;
}

/** Só a Secretaria (usuário com rede vinculada) ou o admin global entra em
 *  /rede — o painel municipal com o mapa. Professor/escola cai no Dashboard. */
function RotaRede({ children }: { children: React.ReactNode }) {
  const { rede } = usePerfil();
  return rede ? <>{children}</> : <Navigate to="/" replace />;
}

/** Operações de ESCOLA (importar, sincronizar, diagnóstico, onboarding): a
 *  Secretaria (rede vinculada, não-global) acompanha os resultados da rede mas
 *  NÃO opera as escolas — é mandada ao Dashboard. Coordenador de escola (sem
 *  rede) e admin global entram. O backend também barra (deps.negar_secretaria). */
function RotaEscolaOp({ children }: { children: React.ReactNode }) {
  const { gestor, secretaria } = usePerfil();
  return gestor && !secretaria ? <>{children}</> : <Navigate to="/" replace />;
}

/** Tela inicial ADAPTÁVEL ao perfil (rota "/"): a SEDUC/Secretaria e o Admin
 *  Global entram na visão consolidada da REDE (/rede); professor/coordenador/
 *  admin de escola veem o Dashboard da escola. Reutiliza os painéis existentes
 *  — não duplica nenhuma tela. */
function RoteadorInicial() {
  const { rede } = usePerfil();
  return rede ? <Navigate to="/rede" replace /> : <Dashboard />;
}

export default function App() {
  return (
    // Um único limite de Suspense cobre o carregamento dos chunks de rota.
    // O Layout tem o seu próprio Suspense em volta do <Outlet/>, então a
    // troca de página autenticada mantém o shell (menu) na tela.
    <Suspense fallback={<Carregando texto="Carregando..." />}>
      <Routes>
        <Route path="/login" element={<Login />} />
        {/* Redefinição de senha por link: acessível sem login */}
        <Route path="/redefinir-senha" element={<RedefinirSenha />} />
        {/* Painel Público: acessível sem login (PRD §104) */}
        <Route path="/p/:token" element={<PainelPublico />} />
        <Route path="/p/:token/alunos/:id" element={<PerfilPublico />} />
        {/* Vitrine pública da Secretaria (top 5 escolas), também sem login */}
        <Route path="/rede/p/:token" element={<PainelPublicoRede />} />
        <Route element={<AreaProtegida />}>
          {/* --- Abertas ao professor (dados já filtrados pelas turmas dele) --- */}
          {/* "/" adapta ao perfil: SEDUC/Admin Global → visão da rede; escola → Dashboard. */}
          <Route path="/" element={<RoteadorInicial />} />
          <Route path="/ranking" element={<Rankings />} />
          {/* Tela única de Ranking Geral com seletor; rotas antigas viram
              deep-links para a aba correspondente (atalhos/bookmarks seguem). */}
          <Route path="/evolucao" element={<Navigate to="/ranking?ver=evolucao" replace />} />
          <Route path="/ranking-leitura" element={<Navigate to="/ranking?ver=leitura" replace />} />
          <Route path="/ranking-matematica" element={<Navigate to="/ranking?ver=matematica" replace />} />
          <Route path="/premiacoes" element={<Premiacoes />} />
          <Route path="/alunos" element={<Alunos />} />
          <Route path="/alunos/:id" element={<PerfilAluno />} />
          <Route path="/conquistas/biblioteca" element={<BibliotecaConquistas />} />
          <Route path="/insights" element={<Insights />} />
          {/* Relatórios: professor exporta o ranking e a lista das turmas dele
              (o backend filtra por turmas_permitidas). */}
          <Route path="/relatorios" element={<Relatorios />} />
          {/* Usuários: professor entra mas o backend só devolve a própria conta. */}
          <Route path="/usuarios" element={<Usuarios />} />

          {/* --- Secretaria (rede) ou admin global: painel municipal + mapa --- */}
          <Route path="/rede" element={<RotaRede><RedeDashboard /></RotaRede>} />
          {/* Provisionar redes (criar, vincular escolas + coords, designar Secretaria)
              é ação de admin GLOBAL — uma rede cruza várias escolas. */}
          <Route path="/rede/gerenciar" element={<RotaGlobal><RedeGestao /></RotaGlobal>} />
          {/* Avaliações externas (SAEB/IDEB/...) × engajamento — Secretaria ou global. */}
          <Route path="/rede/avaliacoes" element={<RotaRede><RedeAvaliacoes /></RotaRede>} />

          {/* --- Só GESTÃO (admin/coordenador) — professor é redirecionado --- */}
          <Route path="/comparador" element={<RotaGestao><Comparador /></RotaGestao>} />
          <Route path="/escola" element={<RotaGestao><VisaoEscola /></RotaGestao>} />
          <Route path="/alunos/:id/evolucao" element={<RotaGestao><EvolucaoAluno /></RotaGestao>} />
          <Route path="/turmas" element={<RotaGestao><Turmas /></RotaGestao>} />
          <Route path="/turmas/:id" element={<RotaGestao><TurmaDetalhe /></RotaGestao>} />
          <Route path="/professores" element={<RotaGestao><Professores /></RotaGestao>} />
          <Route path="/metricas" element={<RotaGestao><Metricas /></RotaGestao>} />
          <Route path="/configuracoes" element={<RotaGestao><Configuracoes /></RotaGestao>} />
          <Route path="/configuracoes/conquistas" element={<RotaGestao><ConfigConquistas /></RotaGestao>} />
          <Route path="/matific" element={<RotaGestao><Matific /></RotaGestao>} />
          <Route path="/elefante" element={<RotaGestao><Elefante /></RotaGestao>} />
          <Route path="/livros" element={<RotaGestao><Livros /></RotaGestao>} />
          <Route path="/comecar" element={<RotaEscolaOp><Comecar /></RotaEscolaOp>} />
          <Route path="/importacoes" element={<RotaEscolaOp><Importacoes /></RotaEscolaOp>} />
          <Route path="/sincronizacao" element={<RotaEscolaOp><Sincronizacao /></RotaEscolaOp>} />
          <Route path="/diagnostico-elefante" element={<RotaEscolaOp><DiagnosticoElefante /></RotaEscolaOp>} />
          <Route path="/conquistas" element={<RotaGestao><Conquistas /></RotaGestao>} />
          <Route path="/assistente" element={<RotaGestao><Assistente /></RotaGestao>} />
          <Route path="/painel-publico" element={<RotaGestao><PainelPublicoConfig /></RotaGestao>} />
          <Route path="/simulador" element={<RotaGestao><Simulador /></RotaGestao>} />

          {/* --- Só administrador GLOBAL --- */}
          <Route path="/escolas" element={<RotaGlobal><Escolas /></RotaGlobal>} />
          <Route path="/sessoes" element={<RotaGlobal><SessoesAtivas /></RotaGlobal>} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </Suspense>
  );
}
