/**
 * Ranking de Leitura por PERÍODO: livros, pontos de dificuldade e tempo somados
 * apenas no intervalo escolhido (base do "melhor leitor da semana/mês").
 */
import { BookMarked } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { SeletorPeriodo, periodoParaQuery, type Periodo } from "../components/SeletorPeriodo";
import { Card, Carregando, PageHeader, Vazio, estiloInput } from "../components/ui";
import { useApp } from "../context/AppContext";
import { api } from "../lib/api";
import { numero, tempoLeitura } from "../lib/formato";
import type { RankingLeituraItem, Turma } from "../lib/types";

export default function RankingLeitura() {
  const { escolaId } = useApp();
  const [periodo, setPeriodo] = useState<Periodo>({ preset: "mes" });
  const [turmaId, setTurmaId] = useState("");
  const [turmas, setTurmas] = useState<Turma[]>([]);
  const [itens, setItens] = useState<RankingLeituraItem[] | null>(null);

  useEffect(() => {
    if (!escolaId) return;
    api<Turma[]>(`/escolas/${escolaId}/turmas`).then(setTurmas).catch(() => setTurmas([]));
  }, [escolaId]);

  const carregar = useCallback(() => {
    if (!escolaId) return;
    setItens(null);
    const q = periodoParaQuery(periodo);
    const filtro = turmaId ? `&turma_id=${turmaId}` : "";
    api<RankingLeituraItem[]>(`/escolas/${escolaId}/ranking/leitura?${q}${filtro}`)
      .then(setItens)
      .catch(() => setItens([]));
  }, [escolaId, periodo, turmaId]);

  useEffect(carregar, [carregar]);

  return (
    <div>
      <PageHeader
        titulo="Ranking de Leitura"
        descricao="Livros, pontos de dificuldade e tempo de leitura somados apenas no período escolhido."
      />

      <Card className="mb-4 flex flex-wrap items-center gap-3 p-4">
        <SeletorPeriodo valor={periodo} onChange={setPeriodo} />
        <select
          aria-label="Filtrar por turma"
          className={`${estiloInput} w-auto`}
          value={turmaId}
          onChange={(e) => setTurmaId(e.target.value)}
        >
          <option value="">Todas as turmas</option>
          {turmas.map((t) => <option key={t.id} value={t.id}>{t.nome}</option>)}
        </select>
      </Card>

      <Card>
        {itens === null ? (
          <Carregando />
        ) : itens.length === 0 ? (
          <Vazio titulo="Nenhuma leitura no período"
                 descricao="Ajuste o período ou importe os relatórios individuais do Elefante Letrado." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm tabular-nums">
              <thead>
                <tr className="border-b border-zinc-200 text-left text-xs uppercase tracking-wide text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
                  <th className="px-4 py-2 font-medium">#</th>
                  <th className="px-4 py-2 font-medium">Aluno</th>
                  <th className="hidden px-4 py-2 font-medium md:table-cell">Turma</th>
                  <th className="px-4 py-2 text-right font-medium">Livros</th>
                  <th className="px-4 py-2 text-right font-medium">Pontos</th>
                  <th className="px-4 py-2 text-right font-medium">Tempo</th>
                </tr>
              </thead>
              <tbody>
                {itens.map((item) => (
                  <tr key={item.aluno_id} className="border-b border-zinc-100 last:border-0 dark:border-zinc-800/60">
                    <td className="px-4 py-2.5">{item.posicao}º</td>
                    <td className="px-4 py-2.5">
                      <Link to={`/alunos/${item.aluno_id}`} className="inline-flex items-center gap-1.5 font-medium hover:text-indigo-600 dark:hover:text-indigo-400">
                        <BookMarked size={13} className="text-zinc-400" /> {item.nome}
                      </Link>
                    </td>
                    <td className="hidden px-4 py-2.5 text-zinc-500 dark:text-zinc-400 md:table-cell">{item.turma ?? "—"}</td>
                    <td className="px-4 py-2.5 text-right font-semibold">{numero(item.livros)}</td>
                    <td className="px-4 py-2.5 text-right">{numero(item.pontos)}</td>
                    <td className="px-4 py-2.5 text-right text-zinc-500 dark:text-zinc-400">{tempoLeitura(item.tempo_leitura_min)}</td>
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
