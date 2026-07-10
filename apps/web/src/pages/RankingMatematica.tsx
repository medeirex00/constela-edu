/**
 * Ranking de Matemática por PERÍODO: estrelas e atividades do Matific
 * conquistadas apenas no intervalo escolhido — o espelho do Ranking de
 * Leitura para os melhores da matemática.
 */
import { Calculator } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { SeletorPeriodo, periodoParaQuery, type Periodo } from "../components/SeletorPeriodo";
import { Card, Carregando, PageHeader, Vazio, estiloInput } from "../components/ui";
import { useApp } from "../context/AppContext";
import { useApi } from "../hooks/useApi";
import { numero } from "../lib/formato";
import type { RankingMatematicaItem, Turma } from "../lib/types";

export default function RankingMatematica() {
  const { escolaId } = useApp();
  const [periodo, setPeriodo] = useState<Periodo>({ preset: "mes" });
  const [turmaId, setTurmaId] = useState("");

  // Turmas para o filtro (ocioso enquanto não houver escola).
  const { dados: turmas } = useApi<Turma[]>(escolaId ? `/escolas/${escolaId}/turmas` : null);

  // Ranking do período: a URL muda com período/turma, então o hook rebusca sozinho.
  const q = periodoParaQuery(periodo);
  const filtro = turmaId ? `&turma_id=${turmaId}` : "";
  const { dados: itens, erro, carregando } = useApi<RankingMatematicaItem[]>(
    escolaId ? `/escolas/${escolaId}/ranking/matematica?${q}${filtro}` : null,
  );

  return (
    <div>
      <PageHeader
        titulo="Ranking de Matemática"
        descricao="Estrelas e atividades do Matific conquistadas apenas no período escolhido."
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
          {(turmas ?? []).map((t) => <option key={t.id} value={t.id}>{t.nome}</option>)}
        </select>
      </Card>

      <Card>
        {carregando ? (
          <Carregando />
        ) : erro ? (
          <Vazio titulo="Não foi possível carregar" descricao={erro.message} />
        ) : (itens ?? []).length === 0 ? (
          <Vazio titulo="Nenhuma atividade de matemática no período"
                 descricao="Ajuste o período ou importe o relatório do Matific com o intervalo de datas." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm tabular-nums">
              <thead>
                <tr className="border-b border-zinc-200 text-left text-xs uppercase tracking-wide text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
                  <th className="px-4 py-2 font-medium">#</th>
                  <th className="px-4 py-2 font-medium">Aluno</th>
                  <th className="hidden px-4 py-2 font-medium md:table-cell">Turma</th>
                  <th className="px-4 py-2 text-right font-medium">Estrelas</th>
                  <th className="px-4 py-2 text-right font-medium">Atividades</th>
                  <th className="hidden px-4 py-2 text-right font-medium sm:table-cell">Pontuação média (no período)</th>
                </tr>
              </thead>
              <tbody>
                {(itens ?? []).map((item) => (
                  <tr key={item.aluno_id} className="border-b border-zinc-100 last:border-0 dark:border-zinc-800/60">
                    <td className="px-4 py-2.5">{item.posicao}º</td>
                    <td className="px-4 py-2.5">
                      <Link to={`/alunos/${item.aluno_id}`} className="inline-flex items-center gap-1.5 font-medium hover:text-indigo-600 dark:hover:text-indigo-400">
                        <Calculator size={13} className="text-zinc-400" /> {item.nome}
                      </Link>
                    </td>
                    <td className="hidden px-4 py-2.5 text-zinc-500 dark:text-zinc-400 md:table-cell">{item.turma ?? "—"}</td>
                    <td className="px-4 py-2.5 text-right font-semibold">⭐ {numero(item.estrelas)}</td>
                    <td className="px-4 py-2.5 text-right">{numero(item.atividades)}</td>
                    <td className="hidden px-4 py-2.5 text-right text-zinc-500 dark:text-zinc-400 sm:table-cell">{item.pontuacao_media.toFixed(2)}</td>
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
