import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { Badge, Card, Carregando, PageHeader, Vazio } from "../components/ui";
import { useApp } from "../context/AppContext";
import { api } from "../lib/api";
import { nota } from "../lib/formato";
import type { RankingItem, Turma } from "../lib/types";

export default function RankingGeral() {
  const { escolaId } = useApp();
  const [itens, setItens] = useState<RankingItem[]>([]);
  const [turmas, setTurmas] = useState<Turma[]>([]);
  const [turmaId, setTurmaId] = useState("");
  const [serie, setSerie] = useState("");
  const [carregando, setCarregando] = useState(true);

  useEffect(() => {
    if (!escolaId) return;
    api<Turma[]>(`/escolas/${escolaId}/turmas`).then(setTurmas).catch(() => setTurmas([]));
  }, [escolaId]);

  useEffect(() => {
    if (!escolaId) return;
    setCarregando(true);
    const parametros = new URLSearchParams();
    if (turmaId) parametros.set("turma_id", turmaId);
    if (serie) parametros.set("ano_escolar", serie);
    api<RankingItem[]>(`/escolas/${escolaId}/ranking?${parametros}`)
      .then(setItens)
      .catch(() => setItens([]))
      .finally(() => setCarregando(false));
  }, [escolaId, turmaId, serie]);

  const series = useMemo(
    () => Array.from(new Set(turmas.map((turma) => turma.ano_escolar))).sort(),
    [turmas],
  );

  return (
    <div>
      <PageHeader
        titulo="Ranking Geral"
        descricao="Combinação das notas Matific e Elefante Letrado, com desempate configurável."
      />

      <div className="mb-4 flex flex-wrap gap-2">
        <select
          aria-label="Filtrar por turma"
          className="rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-900"
          value={turmaId}
          onChange={(evento) => setTurmaId(evento.target.value)}
        >
          <option value="">Todas as turmas</option>
          {turmas.map((turma) => (
            <option key={turma.id} value={turma.id}>
              {turma.nome}
            </option>
          ))}
        </select>
        <select
          aria-label="Filtrar por série"
          className="rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-900"
          value={serie}
          onChange={(evento) => setSerie(evento.target.value)}
        >
          <option value="">Todas as séries</option>
          {series.map((valor) => (
            <option key={valor} value={valor}>
              {valor}
            </option>
          ))}
        </select>
      </div>

      <Card>
        {carregando ? (
          <Carregando />
        ) : itens.length === 0 ? (
          <Vazio titulo="Nenhuma nota calculada ainda" descricao="Importe dados das plataformas para gerar o ranking." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm tabular-nums">
              <thead>
                <tr className="border-b border-zinc-200 text-left text-xs uppercase tracking-wide text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
                  <th className="px-4 py-2 font-medium">#</th>
                  <th className="px-4 py-2 font-medium">Aluno</th>
                  <th className="hidden px-4 py-2 font-medium md:table-cell">Turma</th>
                  <th className="px-4 py-2 text-right font-medium">Matific</th>
                  <th className="px-4 py-2 text-right font-medium">Leitura</th>
                  <th className="px-4 py-2 text-right font-medium">Geral</th>
                </tr>
              </thead>
              <tbody>
                {itens.map((item) => (
                  <tr key={item.aluno_id} className="border-b border-zinc-100 last:border-0 dark:border-zinc-800/60">
                    <td className="px-4 py-2.5">
                      {item.posicao <= 3 ? <Badge tom="destaque">{item.posicao}º</Badge> : `${item.posicao}º`}
                    </td>
                    <td className="px-4 py-2.5">
                      <Link to={`/alunos/${item.aluno_id}`} className="font-medium hover:text-indigo-600 dark:hover:text-indigo-400">
                        {item.nome}
                      </Link>
                    </td>
                    <td className="hidden px-4 py-2.5 text-zinc-500 dark:text-zinc-400 md:table-cell">{item.turma}</td>
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
