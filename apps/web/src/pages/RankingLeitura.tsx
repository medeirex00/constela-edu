/**
 * Ranking de Leitura — três blocos, do oficial ao operacional:
 *  1. CLASSIFICAÇÃO OFICIAL (nota 0–100 do ano letivo, só alunos aferidos;
 *     `components/DesempenhoDimensao`) — respeita turma/série e o turno global;
 *  2. COMPETIÇÃO POR TURNO (a mesma nota, dividida por `Turma.turno`, rótulos do
 *     backend) — abre no turno global quando ele existe;
 *  3. LEITURA NO PERÍODO (pontos): livros, pontos de dificuldade e tempo somados
 *     apenas no intervalo escolhido (base do "melhor leitor da semana/mês").
 */
import { BookMarked } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { CompeticaoLeituraTurno } from "../components/CompeticaoLeituraTurno";
import { DesempenhoDimensao } from "../components/DesempenhoDimensao";
import { FiltroTurmaSerie, type AlvoRanking } from "../components/FiltroTurmaSerie";
import { SeletorPeriodo, periodoParaQuery } from "../components/SeletorPeriodo";
import { SeletorTurno } from "../components/SeletorTurno";
import { Botao, Card, Carregando, PageHeader, Vazio } from "../components/ui";
import { useApp } from "../context/AppContext";
import { useApi } from "../hooks/useApi";
import { useJanela } from "../hooks/useJanela";
import { numero, tempoLeitura } from "../lib/formato";
import { aplicarTurno, turnoEfetivo } from "../lib/turnos";
import type { RankingLeituraItem, Turma } from "../lib/types";

export default function RankingLeitura({ embutido = false }: { embutido?: boolean } = {}) {
  const { escolaId, periodo, definirPeriodo, turno, definirTurno } = useApp();
  // Período TEMPORAL e TURNO vêm do contexto global (seguem o usuário entre as
  // abas). O Elefante traz o TOTAL acumulado por aluno; recortes por semana/mês
  // só têm dados quando há relatório individual datado.
  const [alvo, setAlvo] = useState<AlvoRanking>({});

  const { dados: turmas } = useApi<Turma[]>(
    escolaId ? `/escolas/${escolaId}/turmas` : null, { cacheMs: 60_000 });
  const turnoAtivo = turnoEfetivo(turno, turmas);

  // Recalcula a URL quando período/turma/série/turno mudam; o hook rebusca sozinho.
  const q = new URLSearchParams(periodoParaQuery(periodo));
  if (alvo.turma_id) q.set("turma_id", alvo.turma_id);
  else if (alvo.ano_escolar) q.set("ano_escolar", alvo.ano_escolar);
  aplicarTurno(q, turnoAtivo);
  const {
    dados: itens,
    erro,
    carregando,
    recarregar,
  } = useApi<RankingLeituraItem[]>(
    escolaId ? `/escolas/${escolaId}/ranking/leitura?${q}` : null,
  );
  // Janelamento: em escolas grandes só as primeiras linhas entram no DOM.
  const { visiveis, restantes, mostrarMais } = useJanela(itens ?? []);

  return (
    <div>
      {!embutido && (
        <PageHeader
          titulo="Ranking de Leitura"
          descricao="Classificação oficial (nota 0–100), competição por turno e, abaixo, a leitura no período em pontos."
        />
      )}

      {/* Filtros que valem para a classificação oficial E para o período. */}
      <Card className="mb-4 flex flex-wrap items-center gap-3 p-4">
        <FiltroTurmaSerie turmas={turmas ?? []} valor={alvo} onChange={setAlvo} />
        <SeletorTurno turmas={turmas ?? []} valor={turno} onChange={definirTurno} />
      </Card>

      {/* 1. CLASSIFICAÇÃO OFICIAL: só aferidos, nota do ano, não aferidos ao lado. */}
      <div className="mb-6">
        <DesempenhoDimensao dimensao="leitura" filtros={{ ...alvo, turno: turnoAtivo }} />
      </div>

      {/* 2. COMPETIÇÃO POR TURNO: nota 0–100 por turno (régua única da escola). */}
      <h2 className="mb-1 text-sm font-semibold text-zinc-700 dark:text-zinc-300">
        Competição por turno
      </h2>
      <p className="mb-1 text-xs text-zinc-500 dark:text-zinc-400">
        A mesma nota oficial, com os alunos de cada turno competindo entre si
        (1º ao 5º ano juntos).
      </p>
      {/* A competição NÃO recebe o filtro de turma/série da tela (é sempre o
          turno inteiro); sem este aviso, parece que o filtro foi ignorado. */}
      <p className="mb-3 text-xs text-zinc-500 dark:text-zinc-400">
        Sempre todas as turmas de cada turno — o filtro de turma e série acima não se aplica aqui.
      </p>
      <div className="mb-6">
        <CompeticaoLeituraTurno />
      </div>

      {/* 3. LEITURA NO PERÍODO (temporal, pontos brutos) — preservado como estava. */}
      <h2 className="mb-1 text-sm font-semibold text-zinc-700 dark:text-zinc-300">
        Leitura no período (pontos)
      </h2>
      <p className="mb-3 text-xs text-zinc-500 dark:text-zinc-400">
        Melhor leitor da semana/mês/bimestre — soma de livros, pontos de dificuldade e
        tempo apenas no período escolhido. Não é a classificação oficial acima.
      </p>

      <Card className="mb-4 flex flex-wrap items-center gap-3 p-4">
        <SeletorPeriodo valor={periodo} onChange={definirPeriodo} />
      </Card>

      <Card>
        {carregando ? (
          <Carregando />
        ) : erro ? (
          <Vazio titulo="Não foi possível carregar" descricao={erro.message}
                 acao={<Botao variante="neutro" onClick={recarregar}>Tentar de novo</Botao>} />
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
