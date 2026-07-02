import { Navigate, Route, Routes } from "react-router-dom";

import Layout from "./components/Layout";
import { Carregando } from "./components/ui";
import { useApp } from "./context/AppContext";
import Alunos from "./pages/Alunos";
import Dashboard from "./pages/Dashboard";
import Elefante from "./pages/Elefante";
import EmBreve from "./pages/EmBreve";
import Importacoes from "./pages/Importacoes";
import { Professores, Turmas } from "./pages/ListasSimples";
import Livros from "./pages/Livros";
import Login from "./pages/Login";
import Matific from "./pages/Matific";
import PerfilAluno from "./pages/PerfilAluno";
import RankingGeral from "./pages/RankingGeral";
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
      <Route element={<AreaProtegida />}>
        <Route path="/" element={<Dashboard />} />
        <Route path="/ranking" element={<RankingGeral />} />
        <Route path="/alunos" element={<Alunos />} />
        <Route path="/alunos/:id" element={<PerfilAluno />} />
        <Route path="/turmas" element={<Turmas />} />
        <Route path="/professores" element={<Professores />} />
        <Route path="/metricas" element={<Metricas />} />
        <Route path="/configuracoes" element={<Configuracoes />} />
        <Route path="/matific" element={<Matific />} />
        <Route path="/elefante" element={<Elefante />} />
        <Route path="/livros" element={<Livros />} />
        <Route path="/importacoes" element={<Importacoes />} />
        <Route
          path="/relatorios"
          element={
            <EmBreve
              titulo="Relatórios"
              fase="Fase 4"
              descricao="Exportação em PDF, Excel e CSV com identidade visual da escola."
            />
          }
        />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
