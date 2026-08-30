/**
 * Competição escolar OFICIAL de leitura, dividida por TURNO (`Turma.turno`).
 *
 * Dentro de cada turno competem TODOS os alunos do 1º ao 5º ano juntos, pela
 * MESMA `nota_elefante` (régua única da escola). Os turnos e seus rótulos vêm do
 * backend (`/ranking/leitura/turnos`) — nada de "Manhã"/"Tarde" hardcoded aqui.
 * A série aparece só como informação ao lado do aluno, nunca na pontuação.
 *
 * NÃO confundir com o "Ranking de Leitura" por período (pontos brutos), que é
 * outra tela: este é a competição 0–100 oficial.
 */
import { Trophy } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { useApp } from "../context/AppContext";
import { useApi } from "../hooks/useApi";
import { nota as fmtNota } from "../lib/formato";
import type { RankingTurno } from "../lib/types";
import { Card, Carregando, Vazio } from "./ui";

export function CompeticaoLeituraTurno() {
  const { escolaId } = useApp();
  const { dados, erro, carregando } = useApi<RankingTurno[]>(
    escolaId ? `/escolas/${escolaId}/ranking/leitura/turnos` : null,
  );
  // Turno selecionado. `null` = o usuário ainda NÃO escolheu → mostra o primeiro
  // grupo. NÃO dá para usar o próprio valor do turno como "não escolhido",
  // porque `turno` pode ser `null` de verdade (turma sem turno) — usar `null`
  // como sentinela selecionaria o grupo "Sem turno" por engano.
  const [sel, setSel] = useState<{ turno: string | null } | null>(null);

  if (carregando) return <Carregando />;
  if (erro) return <Vazio titulo="Não foi possível carregar" descricao={erro.message} />;

  const grupos = dados ?? [];
  if (grupos.length === 0) {
    return (
      <Vazio
        titulo="Competição de leitura ainda vazia"
        descricao="Assim que os alunos tiverem leituras aferidas no Elefante Letrado, o ranking por turno aparece aqui."
      />
    );
  }

  const chave = (t: string | null) => t ?? "";
  const atual =
    (sel && grupos.find((g) => chave(g.turno) === chave(sel.turno))) ?? grupos[0];

  return (
    <div>
      {grupos.length > 1 && (
        <div
          role="tablist"
          aria-label="Turno"
          className="mb-3 inline-flex flex-wrap gap-1 rounded-lg border border-zinc-200 bg-zinc-100 p-1 dark:border-zinc-800 dark:bg-zinc-900/60"
        >
          {grupos.map((g) => (
            <button
              key={chave(g.turno) || "_sem"}
              type="button"
              role="tab"
              aria-selected={chave(atual.turno) === chave(g.turno)}
              onClick={() => setSel({ turno: g.turno })}
              className={`rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
                chave(atual.turno) === chave(g.turno)
                  ? "bg-white text-indigo-700 shadow-sm dark:bg-zinc-800 dark:text-indigo-300"
                  : "text-zinc-600 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100"
              }`}
            >
              {g.turno_rotulo}
              <span className="ml-1.5 text-xs text-zinc-400">({g.total})</span>
            </button>
          ))}
        </div>
      )}

      <Card>
        <div className="flex items-center gap-2 border-b border-zinc-200 px-4 py-3 dark:border-zinc-800">
          <Trophy size={16} className="text-amber-500" />
          <h3 className="text-sm font-semibold">
            Ranking de Leitura — {atual.turno_rotulo}
          </h3>
          <span className="ml-auto text-xs text-zinc-400">
            {atual.total} aluno(s) · 1º ao 5º ano juntos
          </span>
        </div>

        {atual.alunos.length === 0 ? (
          <Vazio titulo="Sem alunos aferidos neste turno" descricao="" />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm tabular-nums">
              <thead>
                <tr className="border-b border-zinc-200 text-left text-xs uppercase tracking-wide text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
                  <th className="px-4 py-2 font-medium">#</th>
                  <th className="px-4 py-2 font-medium">Aluno</th>
                  <th className="px-4 py-2 font-medium">Série</th>
                  <th className="hidden px-4 py-2 font-medium md:table-cell">Turma</th>
                  <th className="px-4 py-2 text-right font-medium">Nota de Leitura</th>
                </tr>
              </thead>
              <tbody>
                {atual.alunos.map((item) => (
                  <tr
                    key={item.aluno_id}
                    className="border-b border-zinc-100 last:border-0 dark:border-zinc-800/60"
                  >
                    <td className="px-4 py-2.5 font-semibold text-zinc-500 dark:text-zinc-400">
                      {item.posicao}º
                    </td>
                    <td className="px-4 py-2.5">
                      <Link
                        to={`/alunos/${item.aluno_id}`}
                        className="font-medium hover:text-indigo-600 dark:hover:text-indigo-400"
                      >
                        {item.nome}
                      </Link>
                    </td>
                    <td className="px-4 py-2.5 text-zinc-500 dark:text-zinc-400">
                      {item.ano_escolar ?? "—"}
                    </td>
                    <td className="hidden px-4 py-2.5 text-zinc-500 dark:text-zinc-400 md:table-cell">
                      {item.turma ?? "—"}
                    </td>
                    <td className="px-4 py-2.5 text-right font-semibold">
                      {fmtNota(item.nota_elefante)}
                    </td>
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
