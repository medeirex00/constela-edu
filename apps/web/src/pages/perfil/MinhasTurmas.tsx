/**
 * Home do PROFESSOR — "Minhas Turmas".
 *
 * Compõe dados JÁ escopados pelo backend (o professor só recebe as turmas dele):
 * o dashboard conta apenas as turmas dele, e /turmas devolve só as designadas.
 * Nenhum dado de outra turma chega aqui — a segurança é do servidor.
 */
import { BookOpen, Calculator, GraduationCap, LineChart, Trophy, Users } from "lucide-react";
import { Link } from "react-router-dom";

import { Card, Carregando, PageHeader, StatCard, Vazio } from "../../components/ui";
import { useApp } from "../../context/AppContext";
import { useApi } from "../../hooks/useApi";
import { nota, numero } from "../../lib/formato";

interface Turma {
  id: number;
  nome: string;
  ano_escolar: string;
  total_alunos: number;
}
interface Dashboard {
  total_alunos: number;
  total_turmas: number;
  media_geral: number;
  top10: { posicao: number; aluno_id: number; nome: string; turma: string | null; nota_geral: number }[];
}

const ATALHOS = [
  { rotulo: "Ranking", caminho: "/ranking", icone: Trophy },
  { rotulo: "Evolução", caminho: "/ranking?ver=evolucao", icone: LineChart },
  { rotulo: "Matific", caminho: "/matific", icone: Calculator },
  { rotulo: "Elefante Letrado", caminho: "/elefante", icone: BookOpen },
];

export default function MinhasTurmas() {
  const { escolaId, usuario } = useApp();
  const base = escolaId ? `/escolas/${escolaId}` : null;
  const { dados: dash, erro, carregando } = useApi<Dashboard>(base ? `${base}/dashboard` : null);
  const { dados: turmas } = useApi<Turma[]>(base ? `${base}/turmas` : null);

  if (carregando && !dash) return <Carregando texto="Carregando suas turmas..." />;
  if (erro && !dash)
    return <Vazio titulo="Não foi possível carregar suas turmas" descricao={erro.message} />;

  return (
    <div className="space-y-6">
      <PageHeader
        titulo={`Olá, ${usuario?.nome?.split(" ")[0] ?? "professor(a)"}`}
        descricao="Suas turmas e o desempenho dos seus alunos."
      />

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <StatCard icone={<Users size={16} />} rotulo="Minhas turmas" valor={numero(dash?.total_turmas ?? 0)} />
        <StatCard icone={<GraduationCap size={16} />} rotulo="Meus alunos" valor={numero(dash?.total_alunos ?? 0)} />
        <StatCard icone={<Trophy size={16} />} rotulo="Média geral" valor={nota(dash?.media_geral ?? 0)} />
      </div>

      <div>
        <h2 className="mb-2 text-sm font-semibold">Turmas</h2>
        {!turmas?.length ? (
          <Vazio titulo="Nenhuma turma designada"
                 descricao="Quando uma turma for vinculada a você, ela aparece aqui." />
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {turmas.map((t) => (
              <Link key={t.id} to={`/turmas/${t.id}`}
                    className="card p-4 transition-colors hover:border-indigo-300 dark:hover:border-indigo-700">
                <p className="font-semibold">{t.nome}</p>
                <p className="text-sm text-zinc-500 dark:text-zinc-400">{t.ano_escolar}</p>
                <p className="mt-2 flex items-center gap-1.5 text-sm text-zinc-600 dark:text-zinc-300">
                  <Users size={14} /> {t.total_alunos} alunos
                </p>
              </Link>
            ))}
          </div>
        )}
      </div>

      {!!dash?.top10?.length && (
        <Card className="p-4">
          <h2 className="mb-2 flex items-center gap-2 text-sm font-semibold">
            <Trophy size={16} className="text-amber-500" /> Destaques das suas turmas
          </h2>
          <ol className="space-y-1">
            {dash.top10.slice(0, 5).map((a) => (
              <li key={a.aluno_id}>
                <Link to={`/alunos/${a.aluno_id}`}
                      className="flex items-center gap-3 rounded-lg px-2 py-1.5 hover:bg-zinc-50 dark:hover:bg-zinc-800/60">
                  <span className="w-6 text-center text-sm font-bold tabular-nums text-zinc-400">{a.posicao}</span>
                  <span className="flex-1 truncate text-sm font-medium">{a.nome}</span>
                  <span className="hidden text-xs text-zinc-500 sm:block">{a.turma}</span>
                  <span className="text-sm font-bold tabular-nums">{nota(a.nota_geral)}</span>
                </Link>
              </li>
            ))}
          </ol>
        </Card>
      )}

      <div className="flex flex-wrap gap-2">
        {ATALHOS.map((a) => (
          <Link key={a.caminho} to={a.caminho}
                className="inline-flex items-center gap-2 rounded-lg border border-zinc-300 bg-white px-3.5 py-2 text-sm font-medium hover:bg-zinc-50 dark:border-zinc-700 dark:bg-zinc-900 dark:hover:bg-zinc-800">
            <a.icone size={15} /> {a.rotulo}
          </Link>
        ))}
      </div>
    </div>
  );
}
