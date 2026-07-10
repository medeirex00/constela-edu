/**
 * Premiações da escola por PERÍODO.
 *
 * Cada categoria (melhor leitor, mais livros, mais tempo, destaque no Matific)
 * mostra o pódio calculado EXCLUSIVAMENTE com os dados do intervalo escolhido —
 * a base para premiar semanal, mensal, bimestral ou em datas personalizadas.
 */
import { Award, Trophy } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { SeletorPeriodo, periodoParaQuery, type Periodo } from "../components/SeletorPeriodo";
import { Card, Carregando, PageHeader, Vazio, estiloInput } from "../components/ui";
import { useApp } from "../context/AppContext";
import { useApi } from "../hooks/useApi";
import { numero, tempoLeitura } from "../lib/formato";
import type { CategoriaPremiacao, Premiacoes as PremiacoesT, Turma } from "../lib/types";

const MEDALHAS = ["🥇", "🥈", "🥉"];

function formatarValor(valor: number, unidade: string): string {
  if (unidade === "min") return tempoLeitura(valor);
  return `${numero(valor)} ${unidade}`;
}

function CartaoCategoria({ categoria }: { categoria: CategoriaPremiacao }) {
  const [campeao, ...resto] = categoria.podio;
  return (
    <Card className="flex flex-col p-5">
      <div className="mb-3 flex items-start gap-3">
        <span className="text-2xl leading-none">{categoria.icone}</span>
        <div>
          <h3 className="text-sm font-semibold">{categoria.titulo}</h3>
          <p className="text-xs text-zinc-500 dark:text-zinc-400">{categoria.descricao}</p>
        </div>
      </div>

      {!campeao ? (
        <p className="py-6 text-center text-sm text-zinc-400">Sem dados no período.</p>
      ) : (
        <>
          {/* Campeão em destaque */}
          <Link
            to={`/alunos/${campeao.aluno_id}`}
            className="flex items-center gap-3 rounded-xl border border-amber-200 bg-amber-50/70 p-3 transition-colors hover:bg-amber-50 dark:border-amber-500/20 dark:bg-amber-500/10"
          >
            <span className="text-2xl">🥇</span>
            <div className="min-w-0 flex-1">
              <p className="truncate font-semibold">{campeao.nome}</p>
              {campeao.turma && <p className="text-xs text-zinc-500 dark:text-zinc-400">{campeao.turma}</p>}
            </div>
            <span className="shrink-0 text-right text-sm font-bold tabular-nums text-amber-700 dark:text-amber-300">
              {formatarValor(campeao.valor, categoria.unidade)}
            </span>
          </Link>

          {/* Demais colocados */}
          {resto.length > 0 && (
            <ul className="mt-2 space-y-0.5">
              {resto.map((item) => (
                <li key={item.aluno_id}>
                  <Link
                    to={`/alunos/${item.aluno_id}`}
                    className="flex items-center gap-2.5 rounded-lg px-2 py-1.5 text-sm transition-colors hover:bg-zinc-50 dark:hover:bg-zinc-800/60"
                  >
                    <span className="w-5 shrink-0 text-center">
                      {MEDALHAS[item.posicao - 1] ?? <span className="text-xs text-zinc-400">{item.posicao}º</span>}
                    </span>
                    <span className="min-w-0 flex-1 truncate">{item.nome}</span>
                    {item.turma && <span className="hidden shrink-0 text-xs text-zinc-400 sm:block">{item.turma}</span>}
                    <span className="shrink-0 tabular-nums text-zinc-500 dark:text-zinc-400">
                      {formatarValor(item.valor, categoria.unidade)}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </Card>
  );
}

export default function Premiacoes() {
  const { escolaId } = useApp();
  const [periodo, setPeriodo] = useState<Periodo>({ preset: "mes" });
  const [turmaId, setTurmaId] = useState("");

  const { dados: turmas } = useApi<Turma[]>(escolaId ? `/escolas/${escolaId}/turmas` : null);

  const q = periodoParaQuery(periodo);
  const filtroTurma = turmaId ? `&turma_id=${turmaId}` : "";
  const { dados, erro, carregando } = useApi<PremiacoesT>(
    escolaId ? `/escolas/${escolaId}/premiacoes?${q}${filtroTurma}` : null,
  );

  return (
    <div>
      <PageHeader
        titulo="Premiações"
        descricao="Vencedores calculados apenas com os dados do período escolhido — para premiar por semana, mês, bimestre ou datas personalizadas."
      />

      <Card className="mb-6 flex flex-wrap items-center gap-3 p-4">
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
        {dados && (
          <span className="ml-auto inline-flex items-center gap-1.5 text-sm font-medium text-indigo-700 dark:text-indigo-300">
            <Trophy size={15} /> {dados.periodo.rotulo}
          </span>
        )}
      </Card>

      {carregando ? (
        <Carregando />
      ) : erro ? (
        <Vazio titulo="Não foi possível carregar as premiações" descricao={erro.message} />
      ) : !dados ? (
        <Vazio titulo="Não foi possível carregar as premiações" />
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {dados.categorias.map((categoria) => (
            <CartaoCategoria key={categoria.chave} categoria={categoria} />
          ))}
        </div>
      )}

      <p className="mt-6 flex items-center gap-1.5 text-xs text-zinc-400">
        <Award size={13} /> As premiações consideram somente as leituras e atividades registradas dentro do período.
      </p>
    </div>
  );
}
