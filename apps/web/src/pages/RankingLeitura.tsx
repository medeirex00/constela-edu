/**
 * Ranking de Leitura por PERÍODO: livros, pontos de dificuldade e tempo somados
 * apenas no intervalo escolhido (base do "melhor leitor da semana/mês").
 */
import { BookMarked } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { CompeticaoLeituraTurno } from "../components/CompeticaoLeituraTurno";
import { FiltroTurmaSerie, type AlvoRanking } from "../components/FiltroTurmaSerie";
import { SeletorPeriodo, periodoParaQuery, type Periodo } from "../components/SeletorPeriodo";
import { Card, Carregando, PageHeader, Vazio } from "../components/ui";
import { useApp } from "../context/AppContext";
import { useApi } from "../hooks/useApi";
import { useJanela } from "../hooks/useJanela";
import { numero, tempoLeitura } from "../lib/formato";
import type { RankingLeituraItem, Turma } from "../lib/types";

export default function RankingLeitura({ embutido = false }: { embutido?: boolean } = {}) {
  const { escolaId } = useApp();
  // "Todo o histórico" por padrão: a sincronização do Elefante Letrado traz o
  // TOTAL acumulado por aluno (livros/tempo), sem uma linha por livro com data —
  // então os recortes por semana/mês só têm dados quando há relatório individual.
  const [periodo, setPeriodo] = useState<Periodo>({ preset: "ano_letivo" });
  const [alvo, setAlvo] = useState<AlvoRanking>({});

  const { dados: turmas } = useApi<Turma[]>(
    escolaId ? `/escolas/${escolaId}/turmas` : null, { cacheMs: 60_000 });

  // Recalcula a URL quando período/turma/série mudam; o hook rebusca sozinho.
  const q = periodoParaQuery(periodo);
  const filtro = alvo.turma_id
    ? `&turma_id=${alvo.turma_id}`
    : alvo.ano_escolar
      ? `&ano_escolar=${encodeURIComponent(alvo.ano_escolar)}`
      : "";
  const {
    dados: itens,
    erro,
    carregando,
  } = useApi<RankingLeituraItem[]>(
    escolaId ? `/escolas/${escolaId}/ranking/leitura?${q}${filtro}` : null,
  );
  // Janelamento: em escolas grandes só as primeiras linhas entram no DOM.
  const { visiveis, restantes, mostrarMais } = useJanela(itens ?? []);

  return (
    <div>
      {!embutido && (
        <PageHeader
          titulo="Ranking de Leitura"
          descricao="A competição escolar oficial (nota 0–100) é dividida por turno; abaixo, o ranking por período (pontos)."
        />
      )}

      {/* COMPETIÇÃO OFICIAL: nota 0–100 por turno (régua única da escola). */}
      <div className="mb-6">
        <CompeticaoLeituraTurno />
      </div>

      {/* RANKING POR PERÍODO (temporal, pontos brutos) — preservado como estava. */}
      <h2 className="mb-2 mt-2 text-sm font-semibold text-zinc-700 dark:text-zinc-300">
        Ranking por período (pontos)
      </h2>
      <p className="mb-3 text-xs text-zinc-500 dark:text-zinc-400">
        Melhor leitor da semana/mês/bimestre — soma de livros, pontos de dificuldade e
        tempo apenas no período escolhido. Não é a competição escolar oficial acima.
      </p>

      <Card className="mb-4 flex flex-wrap items-center gap-3 p-4">
        <SeletorPeriodo valor={periodo} onChange={setPeriodo} />
        <FiltroTurmaSerie turmas={turmas ?? []} valor={alvo} onChange={setAlvo} />
      </Card>

      <Card>
        {carregando ? (
          <Carregando />
        ) : erro ? (
          <Vazio titulo="Não foi possível carregar" descricao={erro.message} />
        ) : (itens ?? []).length === 0 ? (
          <Vazio titulo="Nenhuma leitura no período"
                 descricao="Sincronize o Elefante Letrado (ou importe o relatório) e use “Todo o histórico” para ver o total acumulado por aluno." />
        ) : (
          <>
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
                {visiveis.map((item) => (
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
          {restantes > 0 && (
            <div className="border-t border-zinc-100 p-3 text-center dark:border-zinc-800/60">
              <button
                onClick={mostrarMais}
                className="text-sm font-medium text-indigo-600 hover:underline dark:text-indigo-400"
              >
                Mostrar mais {numero(restantes)} aluno(s)
              </button>
            </div>
          )}
          </>
        )}
      </Card>
    </div>
  );
}
