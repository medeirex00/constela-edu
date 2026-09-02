/**
 * Premiações da escola por PERÍODO.
 *
 * Categorias (Melhor Leitor, Melhor Matemática, Mais Livros, Mais Tempo) com o
 * pódio calculado EXCLUSIVAMENTE no intervalo escolhido. "Melhor Matemática" usa
 * a nota_matific OFICIAL (0–100) do período — NÃO a quantidade de atividades
 * (decisão do dono 2026-09-01). Abaixo, "Melhor Evolução" (Leitura e Matemática)
 * premia quem mais CRESCEU no período (motor de evolução, leitura read-only).
 *
 * Duas dimensões independentes: o PERÍODO temporal (o seletor de datas global) e
 * o TURNO escolar (abas "Todas as turmas" → Manhã/Tarde/…, derivadas de
 * Turma.turno pelo backend, nunca hardcoded).
 */
import { Award, TrendingUp, Trophy } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { SeletorPeriodo, periodoParaQuery } from "../components/SeletorPeriodo";
import { Card, Carregando, PageHeader, Vazio, estiloInput } from "../components/ui";
import { useApp } from "../context/AppContext";
import { useApi } from "../hooks/useApi";
import { nota as fmtNota, numero, tempoLeitura } from "../lib/formato";
import type { CategoriaPremiacao, Premiacoes as PremiacoesT, Turma } from "../lib/types";

const MEDALHAS = ["🥇", "🥈", "🥉"];

function formatarValor(valor: number, unidade: string): string {
  if (unidade === "min") return tempoLeitura(valor);
  if (unidade === "nota") return fmtNota(valor); // 0–100
  return `${numero(valor)} ${unidade}`;
}

function CartaoCategoria({ categoria, vazioTexto }: {
  categoria: CategoriaPremiacao; vazioTexto?: string;
}) {
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
        <p className="py-6 text-center text-sm text-zinc-400">
          {vazioTexto ?? "Sem dados no período."}
        </p>
      ) : (
        <>
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

// --- Melhor Evolução (Leitura / Matemática) ---------------------------------
// Reusa o endpoint de evolução por DIMENSÃO (crescimento DENTRO da janela, motor
// oficial read-only). O critério (evolução, não desempenho absoluto) fica claro
// no rótulo. Matemática pode vir vazia por baixa densidade de snapshots (L1).
interface EvolucaoItem {
  aluno_id: number; nome: string; turma: string;
  posicao: number; nota: number | null; n_aferidos: number | null;
}

function CartaoEvolucao({ escolaId, dimensao, titulo, icone, params, vazio }: {
  escolaId: number; dimensao: "leitura" | "matematica";
  titulo: string; icone: string; params: string; vazio: string;
}) {
  // `params` traz o MESMO período e turno das premiações (o filtro é lockado).
  const { dados, erro, carregando } = useApi<EvolucaoItem[]>(
    `/escolas/${escolaId}/ranking-evolucao?dimensao=${dimensao}${params}`,
  );
  const podio = (dados ?? []).slice(0, 5);
  const [campeao, ...resto] = podio;
  return (
    <Card className="flex flex-col p-5">
      <div className="mb-3 flex items-start gap-3">
        <span className="text-2xl leading-none">{icone}</span>
        <div>
          <h3 className="text-sm font-semibold">{titulo}</h3>
          <p className="text-xs text-zinc-500 dark:text-zinc-400">
            Quem mais CRESCEU no período (não o maior acumulado)
          </p>
        </div>
      </div>
      {carregando ? (
        <div className="py-6"><Carregando /></div>
      ) : erro ? (
        <p className="py-6 text-center text-sm text-zinc-400">Não foi possível carregar.</p>
      ) : !campeao ? (
        <p className="py-6 text-center text-sm text-zinc-400">{vazio}</p>
      ) : (
        <>
          <Link
            to={`/alunos/${campeao.aluno_id}/evolucao`}
            className="flex items-center gap-3 rounded-xl border border-emerald-200 bg-emerald-50/70 p-3 transition-colors hover:bg-emerald-50 dark:border-emerald-500/20 dark:bg-emerald-500/10"
          >
            <span className="text-2xl">🥇</span>
            <div className="min-w-0 flex-1">
              <p className="truncate font-semibold">{campeao.nome}</p>
              {campeao.turma && <p className="text-xs text-zinc-500 dark:text-zinc-400">{campeao.turma}</p>}
            </div>
            <span className="shrink-0 inline-flex items-center gap-1 text-sm font-bold tabular-nums text-emerald-700 dark:text-emerald-300">
              <TrendingUp size={13} /> {fmtNota(campeao.nota ?? 0)}
            </span>
          </Link>
          {resto.length > 0 && (
            <ul className="mt-2 space-y-0.5">
              {resto.map((item) => (
                <li key={item.aluno_id}>
                  <Link to={`/alunos/${item.aluno_id}/evolucao`}
                        className="flex items-center gap-2.5 rounded-lg px-2 py-1.5 text-sm transition-colors hover:bg-zinc-50 dark:hover:bg-zinc-800/60">
                    <span className="w-5 shrink-0 text-center">
                      {MEDALHAS[item.posicao - 1] ?? <span className="text-xs text-zinc-400">{item.posicao}º</span>}
                    </span>
                    <span className="min-w-0 flex-1 truncate">{item.nome}</span>
                    <span className="shrink-0 tabular-nums text-zinc-500 dark:text-zinc-400">{fmtNota(item.nota ?? 0)}</span>
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

// Chave estável para o turno (null "Sem turno" não pode virar sentinela de "não
// escolhido" — o mesmo cuidado da Competição de leitura por turno).
const chaveTurno = (t: string | null) => t ?? "";

export default function Premiacoes() {
  const { escolaId, periodo, definirPeriodo } = useApp();
  const [turmaId, setTurmaId] = useState("");
  // Turno selecionado: null = "Todas as turmas" (não escolheu um turno).
  const [turnoSel, setTurnoSel] = useState<{ turno: string | null } | null>(null);

  const { dados: turmas } = useApi<Turma[]>(
    escolaId ? `/escolas/${escolaId}/turmas` : null, { cacheMs: 60_000 });

  const q = periodoParaQuery(periodo);
  const filtroTurma = turmaId ? `&turma_id=${turmaId}` : "";
  // Só pede a quebra por turno na visão "todas as turmas".
  const pedirTurnos = turmaId ? "" : "&turnos=true";
  // Evolução respeita EXATAMENTE os mesmos filtros lockados: período + turma +
  // turno (o turno selecionado nas abas; vazio = "Sem turno"). Sem isto, a
  // evolução ignoraria período/turno e a tela mostraria recortes divergentes.
  const { dados, erro, carregando } = useApi<PremiacoesT>(
    escolaId ? `/escolas/${escolaId}/premiacoes?${q}${filtroTurma}${pedirTurnos}` : null,
  );

  const turnos = (!turmaId && dados?.turnos) || [];
  // Escopo de categorias exibido: um turno escolhido (e existente) ou "Todas".
  const grupoTurno = turnoSel
    ? turnos.find((g) => chaveTurno(g.turno) === chaveTurno(turnoSel.turno))
    : null;
  const categorias = grupoTurno?.categorias ?? dados?.categorias ?? [];

  // Turno órfão: se o usuário tinha um turno selecionado e, ao trocar o período,
  // esse turno deixa de existir no recorte, volta para "Todas". Sem isto os
  // pódios cairiam no fallback (todos os turnos) sem destacar aba nenhuma e a
  // Melhor Evolução ainda filtraria por um turno inexistente (retornando vazio).
  useEffect(() => {
    if (turnoSel && turnos.length > 0
        && !turnos.some((g) => chaveTurno(g.turno) === chaveTurno(turnoSel.turno))) {
      setTurnoSel(null);
    }
  }, [turnoSel, turnos]);

  return (
    <div>
      <PageHeader
        titulo="Premiações"
        descricao="Vencedores calculados apenas com os dados do período escolhido — por semana, mês, bimestre ou datas personalizadas."
      />

      <Card className="mb-6 flex flex-wrap items-center gap-3 p-4">
        <SeletorPeriodo valor={periodo} onChange={definirPeriodo} />
        <select
          aria-label="Filtrar por turma"
          className={`${estiloInput} w-auto`}
          value={turmaId}
          onChange={(e) => { setTurmaId(e.target.value); setTurnoSel(null); }}
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

      {/* Abas de TURNO (só na visão "todas as turmas" e quando há mais de um). */}
      {turnos.length > 1 && (
        <div role="tablist" aria-label="Turno"
             className="mb-4 inline-flex flex-wrap gap-1 rounded-lg border border-zinc-200 bg-zinc-100 p-1 dark:border-zinc-800 dark:bg-zinc-900/60">
          <button type="button" role="tab" aria-selected={!turnoSel}
                  onClick={() => setTurnoSel(null)}
                  className={`rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
                    !turnoSel ? "bg-white text-indigo-700 shadow-sm dark:bg-zinc-800 dark:text-indigo-300"
                              : "text-zinc-600 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100"}`}>
            Todas
          </button>
          {turnos.map((g) => (
            <button key={chaveTurno(g.turno) || "_sem"} type="button" role="tab"
                    aria-selected={chaveTurno(grupoTurno?.turno ?? null) === chaveTurno(g.turno) && !!turnoSel}
                    onClick={() => setTurnoSel({ turno: g.turno })}
                    className={`rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
                      turnoSel && chaveTurno(grupoTurno?.turno ?? null) === chaveTurno(g.turno)
                        ? "bg-white text-indigo-700 shadow-sm dark:bg-zinc-800 dark:text-indigo-300"
                        : "text-zinc-600 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100"}`}>
              {g.turno_rotulo}<span className="ml-1.5 text-xs text-zinc-400">({g.total})</span>
            </button>
          ))}
        </div>
      )}

      {carregando ? (
        <Carregando />
      ) : erro ? (
        <Vazio titulo="Não foi possível carregar as premiações" descricao={erro.message} />
      ) : !dados ? (
        <Vazio titulo="Não foi possível carregar as premiações" />
      ) : (
        <>
          <div className="grid gap-4 md:grid-cols-2">
            {categorias.map((categoria) => (
              <CartaoCategoria
                key={categoria.chave} categoria={categoria}
                vazioTexto={categoria.chave === "melhor_matematica"
                  ? "Sem snapshots do Matific no período (importe/sincronize para premiar por nota)."
                  : undefined}
              />
            ))}
          </div>

          {/* MELHOR EVOLUÇÃO — quem mais cresceu no período (toda a escola ou a
              turma filtrada; o motor de evolução ainda não separa por turno). */}
          <h2 className="mb-3 mt-8 text-sm font-semibold text-zinc-700 dark:text-zinc-300">
            Melhor Evolução no período
          </h2>
          {escolaId && (() => {
            // Mesmo período + turma + TURNO selecionado que os pódios acima.
            const filtroTurno = turnoSel
              ? `&turno=${encodeURIComponent(chaveTurno(turnoSel.turno))}` : "";
            const paramsEvol = `&${q}${filtroTurma}${filtroTurno}`;
            return (
              <div className="grid gap-4 md:grid-cols-2">
                <CartaoEvolucao
                  escolaId={escolaId} dimensao="leitura" params={paramsEvol}
                  titulo="Melhor Evolução — Leitura" icone="📚"
                  vazio="Sem dados suficientes para medir evolução de leitura no período." />
                <CartaoEvolucao
                  escolaId={escolaId} dimensao="matematica" params={paramsEvol}
                  titulo="Melhor Evolução — Matemática" icone="🧮"
                  vazio="Sem dados suficientes no período para medir evolução de Matemática." />
              </div>
            );
          })()}
        </>
      )}

      <p className="mt-6 flex items-center gap-1.5 text-xs text-zinc-400">
        <Award size={13} /> Melhor Matemática usa a nota oficial (0–100) do período. Evolução mede o crescimento dentro do intervalo, não o acumulado.
      </p>
    </div>
  );
}
