/** Ranking de Evolução (PRD §72) — independente do Ranking Geral. */
import { TrendingUp } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { FiltroTurmaSerie, type AlvoRanking } from "../components/FiltroTurmaSerie";
import { SeletorPeriodo, periodoParaQuery, type Periodo } from "../components/SeletorPeriodo";
import { Badge, Card, Carregando, PageHeader, Vazio } from "../components/ui";
import { useApp } from "../context/AppContext";
import { useApi } from "../hooks/useApi";
import { nota, numero } from "../lib/formato";
import type { Turma } from "../lib/types";

interface ItemEvolucao {
  posicao: number;
  aluno_id: number;
  nome: string;
  turma: string;
  ano_escolar: string;
  nota_evolucao: number;
  ganhos: {
    atividades: number;
    estrelas: number;
    livros: number;
    tempo_leitura_min: number;
    acertos: number;
  };
}

export default function RankingEvolucao({ embutido = false }: { embutido?: boolean } = {}) {
  const { escolaId } = useApp();
  const [periodo, setPeriodo] = useState<Periodo>({ preset: "mes" });
  const [alvo, setAlvo] = useState<AlvoRanking>({});

  // Turmas alimentam apenas os filtros; na falha caímos para lista vazia.
  const { dados: turmasDados } = useApi<Turma[]>(
    escolaId ? `/escolas/${escolaId}/turmas` : null, { cacheMs: 60_000 });
  const turmas = turmasDados ?? [];

  const parametros = new URLSearchParams(periodoParaQuery(periodo));
  if (alvo.turma_id) parametros.set("turma_id", alvo.turma_id);
  if (alvo.ano_escolar) parametros.set("ano_escolar", alvo.ano_escolar);
  const { dados: itens, erro, carregando } = useApi<ItemEvolucao[]>(
    escolaId ? `/escolas/${escolaId}/ranking-evolucao?${parametros}` : null,
  );

  return (
    <div>
      {!embutido && (
        <PageHeader
          titulo="Ranking de Evolução"
          descricao="Quem mais cresceu no período — independente da nota acumulada. Usa os mesmos pesos configuráveis aplicados aos ganhos."
        />
      )}

      <Card className="mb-4 flex flex-wrap items-center gap-2 p-4">
        <SeletorPeriodo valor={periodo} onChange={setPeriodo} />
        <FiltroTurmaSerie turmas={turmas} valor={alvo} onChange={setAlvo} />
      </Card>

      <Card>
        {carregando ? (
          <Carregando />
        ) : erro ? (
          <Vazio titulo="Não foi possível carregar" descricao={erro.message} />
        ) : (itens ?? []).length === 0 ? (
          <Vazio titulo="Sem dados no período" descricao="Importe novos relatórios para medir a evolução." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm tabular-nums">
              <thead>
                <tr className="border-b border-zinc-200 text-left text-xs uppercase tracking-wide text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
                  <th className="px-4 py-2 font-medium">#</th>
                  <th className="px-4 py-2 font-medium">Aluno</th>
                  <th className="hidden px-4 py-2 font-medium md:table-cell">Turma</th>
                  <th className="px-4 py-2 font-medium">Ganhos no período</th>
                  <th className="px-4 py-2 text-right font-medium">
                    <span className="inline-flex items-center gap-1"><TrendingUp size={13} /> Evolução</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {(itens ?? []).map((item) => (
                  <tr key={item.aluno_id} className="border-b border-zinc-100 last:border-0 dark:border-zinc-800/60">
                    <td className="px-4 py-2.5">
                      {item.posicao <= 3 ? <Badge tom="ok">{item.posicao}º</Badge> : `${item.posicao}º`}
                    </td>
                    <td className="px-4 py-2.5">
                      <Link to={`/alunos/${item.aluno_id}/evolucao`} className="font-medium hover:text-indigo-600 dark:hover:text-indigo-400">
                        {item.nome}
                      </Link>
                    </td>
                    <td className="hidden px-4 py-2.5 text-zinc-500 dark:text-zinc-400 md:table-cell">{item.turma}</td>
                    <td className="px-4 py-2.5 text-xs text-zinc-600 dark:text-zinc-300">
                      {[
                        item.ganhos.atividades > 0 && `+${numero(item.ganhos.atividades)} atividades`,
                        item.ganhos.livros > 0 && `+${numero(item.ganhos.livros)} livros`,
                        item.ganhos.estrelas > 0 && `+${numero(item.ganhos.estrelas)} estrelas`,
                        item.ganhos.acertos > 0 && `+${numero(item.ganhos.acertos)} acertos`,
                      ]
                        .filter(Boolean)
                        .join(" · ") || "sem ganhos"}
                    </td>
                    <td className="px-4 py-2.5 text-right font-semibold">{nota(item.nota_evolucao)}</td>
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
