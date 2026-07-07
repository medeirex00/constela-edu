/** Ranking de Evolução (PRD §72) — independente do Ranking Geral. */
import { TrendingUp } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { SeletorPeriodo, periodoParaQuery, type Periodo } from "../components/SeletorPeriodo";
import { Badge, Card, Carregando, PageHeader, Vazio, estiloInput } from "../components/ui";
import { useApp } from "../context/AppContext";
import { api } from "../lib/api";
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

export default function RankingEvolucao() {
  const { escolaId } = useApp();
  const [itens, setItens] = useState<ItemEvolucao[] | null>(null);
  const [turmas, setTurmas] = useState<Turma[]>([]);
  const [periodo, setPeriodo] = useState<Periodo>({ preset: "30dias" });
  const [turmaId, setTurmaId] = useState("");
  const [serie, setSerie] = useState("");

  useEffect(() => {
    if (!escolaId) return;
    api<Turma[]>(`/escolas/${escolaId}/turmas`).then(setTurmas).catch(() => setTurmas([]));
  }, [escolaId]);

  useEffect(() => {
    if (!escolaId) return;
    setItens(null);
    const parametros = new URLSearchParams(periodoParaQuery(periodo));
    if (turmaId) parametros.set("turma_id", turmaId);
    if (serie) parametros.set("ano_escolar", serie);
    api<ItemEvolucao[]>(`/escolas/${escolaId}/ranking-evolucao?${parametros}`)
      .then(setItens)
      .catch(() => setItens([]));
  }, [escolaId, periodo, turmaId, serie]);

  const series = useMemo(
    () => Array.from(new Set(turmas.map((turma) => turma.ano_escolar))).sort(),
    [turmas],
  );

  return (
    <div>
      <PageHeader
        titulo="Ranking de Evolução"
        descricao="Quem mais cresceu no período — independente da nota acumulada. Usa os mesmos pesos configuráveis aplicados aos ganhos."
      />

      <Card className="mb-4 flex flex-wrap items-center gap-2 p-4">
        <SeletorPeriodo valor={periodo} onChange={setPeriodo} />
        <select
          aria-label="Filtrar por turma"
          className={`${estiloInput} w-auto`}
          value={turmaId}
          onChange={(evento) => setTurmaId(evento.target.value)}
        >
          <option value="">Todas as turmas</option>
          {turmas.map((turma) => (
            <option key={turma.id} value={turma.id}>{turma.nome}</option>
          ))}
        </select>
        <select
          aria-label="Filtrar por série"
          className={`${estiloInput} w-auto`}
          value={serie}
          onChange={(evento) => setSerie(evento.target.value)}
        >
          <option value="">Todas as séries</option>
          {series.map((valor) => (
            <option key={valor} value={valor}>{valor}</option>
          ))}
        </select>
      </Card>

      <Card>
        {itens === null ? (
          <Carregando />
        ) : itens.length === 0 ? (
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
                {itens.map((item) => (
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
