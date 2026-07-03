/** Página da turma (PRD §76–§77): médias, totais e ranking interno. */
import { ArrowLeft, BookOpen, Calculator, Clock, Users } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { Badge, Card, Carregando, StatCard, Vazio } from "../components/ui";
import { useApp } from "../context/AppContext";
import { api } from "../lib/api";
import { nota, numero, tempoLeitura } from "../lib/formato";
import type { RankingItem } from "../lib/types";

interface ResumoTurma {
  turma: { id: number; nome: string; ano_escolar: string };
  total_alunos: number;
  media_geral: number;
  media_matific: number;
  media_elefante: number;
  indicadores: Record<string, number>;
}

export default function TurmaDetalhe() {
  const { id } = useParams();
  const { escolaId } = useApp();
  const [resumo, setResumo] = useState<ResumoTurma | null>(null);
  const [ranking, setRanking] = useState<RankingItem[]>([]);
  const [carregando, setCarregando] = useState(true);

  useEffect(() => {
    if (!escolaId || !id) return;
    setCarregando(true);
    Promise.all([
      api<ResumoTurma>(`/escolas/${escolaId}/turmas/${id}/resumo`),
      api<RankingItem[]>(`/escolas/${escolaId}/ranking?turma_id=${id}`),
    ])
      .then(([resumoTurma, itens]) => {
        setResumo(resumoTurma);
        setRanking(itens);
      })
      .catch(() => setResumo(null))
      .finally(() => setCarregando(false));
  }, [escolaId, id]);

  if (carregando) return <Carregando />;
  if (!resumo) return <Vazio titulo="Turma não encontrada" />;

  return (
    <div className="space-y-6">
      <div>
        <Link to="/turmas" className="mb-3 inline-flex items-center gap-1.5 text-sm text-zinc-500 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100">
          <ArrowLeft size={15} /> Turmas
        </Link>
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-xl font-semibold tracking-tight">{resumo.turma.nome}</h1>
          <Badge tom="destaque">{resumo.turma.ano_escolar}</Badge>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatCard icone={<Users size={15} />} rotulo="Alunos" valor={numero(resumo.total_alunos)} />
        <StatCard icone={<Calculator size={15} />} rotulo="Média geral" valor={nota(resumo.media_geral)}
                  detalhe={`Matific ${nota(resumo.media_matific)} · Leitura ${nota(resumo.media_elefante)}`} />
        <StatCard icone={<BookOpen size={15} />} rotulo="Livros lidos" valor={numero(resumo.indicadores.livros_unicos ?? 0)} />
        <StatCard icone={<Clock size={15} />} rotulo="Tempo de leitura" valor={tempoLeitura(resumo.indicadores.tempo_leitura_min ?? 0)} />
      </div>

      <Card>
        <div className="border-b border-zinc-200 px-4 py-3 dark:border-zinc-800">
          <h3 className="text-sm font-semibold">Ranking da turma</h3>
        </div>
        {ranking.length === 0 ? (
          <Vazio titulo="Sem notas calculadas" descricao="Importe dados das plataformas para gerar o ranking." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm tabular-nums">
              <thead>
                <tr className="border-b border-zinc-200 text-left text-xs uppercase tracking-wide text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
                  <th className="px-4 py-2 font-medium">#</th>
                  <th className="px-4 py-2 font-medium">Aluno</th>
                  <th className="px-4 py-2 text-right font-medium">Matific</th>
                  <th className="px-4 py-2 text-right font-medium">Leitura</th>
                  <th className="px-4 py-2 text-right font-medium">Geral</th>
                </tr>
              </thead>
              <tbody>
                {ranking.map((item, indice) => (
                  <tr key={item.aluno_id} className="border-b border-zinc-100 last:border-0 dark:border-zinc-800/60">
                    <td className="px-4 py-2.5">{indice + 1}º <span className="text-xs text-zinc-400">({item.posicao}º geral)</span></td>
                    <td className="px-4 py-2.5">
                      <Link to={`/alunos/${item.aluno_id}`} className="font-medium hover:text-indigo-600 dark:hover:text-indigo-400">
                        {item.nome}
                      </Link>
                    </td>
                    <td className="px-4 py-2.5 text-right">{nota(item.nota_matific)}</td>
                    <td className="px-4 py-2.5 text-right">{nota(item.nota_elefante)}</td>
                    <td className="px-4 py-2.5 text-right font-semibold">{nota(item.nota_geral)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
