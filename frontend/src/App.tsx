import { Navigate, Route, Routes } from "react-router-dom";

import Layout from "./components/Layout";
import { Carregando } from "./components/ui";
import { useApp } from "./context/AppContext";
import Alunos from "./pages/Alunos";
import Dashboard from "./pages/Dashboard";
import EmBreve from "./pages/EmBreve";
import { Professores, Turmas } from "./pages/ListasSimples";
import Login from "./pages/Login";
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
        <Route
          path="/matific"
          element={
            <EmBreve
              titulo="Matific"
              fase="Fase 2"
              descricao="Tela do módulo com importação de relatórios (PDF ou texto colado), edição manual auditada e histórico por aluno."
            />
          }
        />
        <Route
          path="/elefante"
          element={
            <EmBreve
              titulo="Elefante Letrado"
              fase="Fase 2"
              descricao="Tela do módulo com importação de relatórios, livros por nível, questões e tempo de leitura por aluno."
            />
          }
        />
        <Route
          path="/livros"
          element={
            <EmBreve
              titulo="Catálogo de Livros"
              fase="Fase 2"
              descricao="Consulta rápida de títulos, autores, níveis e pontuação atual de cada livro."
            />
          }
        />
        <Route
          path="/importacoes"
          element={
            <EmBreve
              titulo="Importações"
              fase="Fase 2"
              descricao="Envio de PDF ou texto, prévia com validação, confirmação e histórico completo de cada importação."
            />
          }
        />
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
