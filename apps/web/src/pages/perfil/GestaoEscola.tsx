/**
 * Home do COORDENADOR / GESTOR — "Gestão da Escola".
 *
 * Cockpit da escola: KPIs, desempenho consolidado POR PROFESSOR (a lacuna que
 * faltava) e atalhos para comparar turmas / ver a escola. Tudo escopado à
 * escola pelo backend; um coordenador nunca vê outra escola.
 */
import { BarChart3, Building2, GitCompareArrows, GraduationCap, Sparkles, TrendingUp, Trophy, Users } from "lucide-react";
import { Link } from "react-router-dom";

import { Card, Carregando, PageHeader, StatCard, Vazio } from "../../components/ui";
import { useApp } from "../../context/AppContext";
import { useApi } from "../../hooks/useApi";
import { corPorMedia } from "../../lib/cores";
import { nota, numero } from "../../lib/formato";

interface Dashboard {
  total_alunos: number;
  total_turmas: number;
  total_professores: number;
  media_geral: number;
}
interface Professor {
  professor_id: number | null;
  professor_nome: string;
  total_turmas: number;
  total_alunos: number;
  alunos_com_dados: number;
  participacao: number;
  media_geral: number;
  turmas: { turma_id: number; nome: string; total_alunos: number; media_geral: number }[];
}

export default function GestaoEscola() {
  const { escolaId, escolaAtual } = useApp();
  const base = escolaId ? `/escolas/${escolaId}` : null;
  const { dados: dash, erro, carregando } = useApi<Dashboard>(base ? `${base}/dashboard` : null);
  const { dados: professores } = useApi<Professor[]>(base ? `${base}/consolidado-professores` : null);

  if (carregando && !dash) return <Carregando texto="Carregando a escola..." />;
  if (erro && !dash)
    return <Vazio titulo="Não foi possível carregar a escola" descricao={erro.message} />;

  return (
    <div className="space-y-6">
      <PageHeader
        titulo="Gestão da Escola"
        descricao={escolaAtual?.nome ?? "Visão consolidada da sua escola."}
      />

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatCard icone={<Users size={16} />} rotulo="Turmas" valor={numero(dash?.total_turmas ?? 0)} />
        <StatCard icone={<GraduationCap size={16} />} rotulo="Alunos" valor={numero(dash?.total_alunos ?? 0)} />
        <StatCard icone={<Building2 size={16} />} rotulo="Professores" valor={numero(dash?.total_professores ?? 0)} />
        <StatCard icone={<TrendingUp size={16} />} rotulo="Média geral" valor={nota(dash?.media_geral ?? 0)} />
      </div>

      <Card className="p-4">
        <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold">
          <BarChart3 size={16} className="text-indigo-600" /> Desempenho por professor
        </h2>
        {!professores?.length ? (
          <Vazio titulo="Sem dados por professor ainda"
                 descricao="Vincule professores às turmas e importe dados para ver o consolidado." />
        ) : (
          <div className="space-y-2">
            {professores.map((p) => (
              <div key={p.professor_id ?? "sem"} className="rounded-lg border border-zinc-200 p-3 dark:border-zinc-800">
                <div className="flex items-center gap-3">
                  <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: corPorMedia(p.media_geral) }} />
                  <span className="flex-1 truncate text-sm font-semibold">{p.professor_nome}</span>
                  <span className="text-xs text-zinc-500">{p.total_turmas} turma(s) · {p.total_alunos} al.</span>
                  <span className="hidden text-xs text-zinc-500 sm:block">part. {nota(p.participacao)}%</span>
                  <span className="w-14 text-right text-sm font-bold tabular-nums">{nota(p.media_geral)}</span>
                </div>
                <div className="mt-2 flex flex-wrap gap-1.5 pl-6">
                  {p.turmas.map((t) => (
                    <Link key={t.turma_id} to={`/turmas/${t.turma_id}`}
                          className="inline-flex items-center gap-1 rounded-full bg-zinc-100 px-2 py-0.5 text-xs hover:bg-zinc-200 dark:bg-zinc-800 dark:hover:bg-zinc-700">
                      {t.nome} <b className="tabular-nums">{nota(t.media_geral)}</b>
                    </Link>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>

      <div className="flex flex-wrap gap-2">
        {[
          { rotulo: "Visão da Escola", caminho: "/escola", icone: Building2 },
          { rotulo: "Comparar turmas", caminho: "/comparador", icone: GitCompareArrows },
          { rotulo: "Ranking", caminho: "/ranking", icone: Trophy },
          { rotulo: "Alunos em atenção", caminho: "/insights", icone: Sparkles },
        ].map((a) => (
          <Link key={a.caminho} to={a.caminho}
                className="inline-flex items-center gap-2 rounded-lg border border-zinc-300 bg-white px-3.5 py-2 text-sm font-medium hover:bg-zinc-50 dark:border-zinc-700 dark:bg-zinc-900 dark:hover:bg-zinc-800">
            <a.icone size={15} /> {a.rotulo}
          </Link>
        ))}
      </div>
    </div>
  );
}
