import { Navigate, Route, Routes } from "react-router-dom";

import Layout from "./components/Layout";
import { Carregando } from "./components/ui";
import { useApp } from "./context/AppContext";
import Alunos from "./pages/Alunos";
import Assistente from "./pages/Assistente";
import BibliotecaConquistas from "./pages/BibliotecaConquistas";
import Comparador from "./pages/Comparador";
import Insights from "./pages/Insights";
import Conquistas from "./pages/Conquistas";
import Dashboard from "./pages/Dashboard";
import Elefante from "./pages/Elefante";
import EvolucaoAluno from "./pages/EvolucaoAluno";
import Importacoes from "./pages/Importacoes";
import { Professores } from "./pages/ListasSimples";
import Livros from "./pages/Livros";
import Login from "./pages/Login";
import Matific from "./pages/Matific";
import PainelPublicoConfig from "./pages/PainelPublicoConfig";
import PerfilAluno from "./pages/PerfilAluno";
import Premiacoes from "./pages/Premiacoes";
import RankingEvolucao from "./pages/RankingEvolucao";
import PainelPublico from "./pages/publico/PainelPublico";
import PerfilPublico from "./pages/publico/PerfilPublico";
import RankingGeral from "./pages/RankingGeral";
import RankingLeitura from "./pages/RankingLeitura";
import Relatorios from "./pages/Relatorios";
import Simulador from "./pages/Simulador";
import TurmaDetalhe from "./pages/TurmaDetalhe";
import Turmas from "./pages/Turmas";
import Usuarios from "./pages/Usuarios";
import VisaoEscola from "./pages/VisaoEscola";
import ConfigConquistas from "./pages/configuracoes/ConfigConquistas";
import Configuracoes from "./pages/configuracoes/Configuracoes";
import Metricas from "./pages/configuracoes/Metricas";

function AreaProtegida() {
  const { usuario, carregando } = useApp();
  if (carregando) return <Carregando texto="Abrindo o sistema..." />;
  if (!usuario) return <Navigate to="/login" replace />;
  return <Layout />;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      {/* Painel Público: acessível sem login (PRD §104) */}
      <Route path="/p/:token" element={<PainelPublico />} />
      <Route path="/p/:token/alunos/:id" element={<PerfilPublico />} />
      <Route element={<AreaProtegida />}>
        <Route path="/" element={<Dashboard />} />
        <Route path="/ranking" element={<RankingGeral />} />
        <Route path="/evolucao" element={<RankingEvolucao />} />
        <Route path="/ranking-leitura" element={<RankingLeitura />} />
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
        <Route path="/importacoes" element={<Importacoes />} />
        <Route path="/conquistas" element={<Conquistas />} />
        <Route path="/conquistas/biblioteca" element={<BibliotecaConquistas />} />
        <Route path="/insights" element={<Insights />} />
        <Route path="/assistente" element={<Assistente />} />
        <Route path="/painel-publico" element={<PainelPublicoConfig />} />
        <Route path="/relatorios" element={<Relatorios />} />
        <Route path="/simulador" element={<Simulador />} />
        <Route path="/usuarios" element={<Usuarios />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
