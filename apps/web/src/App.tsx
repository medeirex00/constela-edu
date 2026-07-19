import { Suspense, lazy } from "react";
import { Navigate, Route, Routes } from "react-router-dom";

import Layout from "./components/Layout";
import { Botao, Carregando } from "./components/ui";
import { useApp } from "./context/AppContext";
import { ImportacaoLoteProvider } from "./context/ImportacaoLoteContext";

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
const PerfilPublico = lazy(() => import("./pages/publico/PerfilPublico"));
const Rankings = lazy(() => import("./pages/Rankings"));
const Relatorios = lazy(() => import("./pages/Relatorios"));
const Escolas = lazy(() => import("./pages/Escolas"));
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
        <Route element={<AreaProtegida />}>
          <Route path="/" element={<Dashboard />} />
          <Route path="/ranking" element={<Rankings />} />
          {/* Tela única de Ranking Geral com seletor; rotas antigas viram
              deep-links para a aba correspondente (atalhos/bookmarks seguem). */}
          <Route path="/evolucao" element={<Navigate to="/ranking?ver=evolucao" replace />} />
          <Route path="/ranking-leitura" element={<Navigate to="/ranking?ver=leitura" replace />} />
          <Route path="/ranking-matematica" element={<Navigate to="/ranking?ver=matematica" replace />} />
          <Route path="/comparador" element={<Comparador />} />
          <Route path="/premiacoes" element={<Premiacoes />} />
          <Route path="/escola" element={<VisaoEscola />} />
          <Route path="/alunos" element={<Alunos />} />
          <Route path="/alunos/:id" element={<PerfilAluno />} />
          <Route path="/alunos/:id/evolucao" element={<EvolucaoAluno />} />
          <Route path="/turmas" element={<Turmas />} />
          <Route path="/turmas/:id" element={<TurmaDetalhe />} />
          <Route path="/professores" element={<Professores />} />
          <Route path="/metricas" element={<Metricas />} />
          <Route path="/configuracoes" element={<Configuracoes />} />
          <Route path="/configuracoes/conquistas" element={<ConfigConquistas />} />
          <Route path="/matific" element={<Matific />} />
          <Route path="/elefante" element={<Elefante />} />
          <Route path="/livros" element={<Livros />} />
          <Route path="/comecar" element={<Comecar />} />
          <Route path="/importacoes" element={<Importacoes />} />
          <Route path="/sincronizacao" element={<Sincronizacao />} />
          <Route path="/diagnostico-elefante" element={<DiagnosticoElefante />} />
          <Route path="/conquistas" element={<Conquistas />} />
          <Route path="/conquistas/biblioteca" element={<BibliotecaConquistas />} />
          <Route path="/insights" element={<Insights />} />
          <Route path="/assistente" element={<Assistente />} />
          <Route path="/painel-publico" element={<PainelPublicoConfig />} />
          <Route path="/relatorios" element={<Relatorios />} />
          <Route path="/simulador" element={<Simulador />} />
          <Route path="/usuarios" element={<Usuarios />} />
          <Route path="/escolas" element={<Escolas />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </Suspense>
  );
}
