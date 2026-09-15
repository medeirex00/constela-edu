/**
 * Premiações da escola por PERÍODO.
 *
 * Categorias (Melhor Leitor, Melhor Matemática, Mais Livros, Mais Tempo) com o
 * pódio calculado EXCLUSIVAMENTE no intervalo escolhido. "Melhor Matemática" usa
 * a nota_matific OFICIAL (0–100) do período — NÃO a quantidade de atividades
 * (decisão do dono 2026-09-01). Abaixo, "Melhor Evolução" (Leitura e Matemática)
 * premia quem mais CRESCEU no período (motor de evolução, leitura read-only).
 *
 * Duas dimensões independentes e GLOBAIS (seguem o usuário pelos rankings): o
 * PERÍODO temporal (seletor de datas) e o TURNO escolar (seletor de turno; as
 * opções vêm de `Turma.turno` da escola, nunca hardcoded). Os pódios por turno
 * vêm do backend (`?turnos=true`): vencedores calculados só com os alunos do
 * turno; a régua da Matemática é a da escola inteira (decisão registrada).
 * Com UMA TURMA selecionada, a turma vence (o turno fica desabilitado, com o
 * motivo em texto visível ligado ao seletor por `aria-describedby`).
 *
 * O backend agrupa por turno TODOS os alunos ativos matriculados no ano letivo
 * (com ou sem dado no período): um turno sem grupo significa "ninguém
 * matriculado nesse turno", não "ninguém com dados".
 *
 * Dados DO RECORTE ATUAL: `useApi` mantém a resposta anterior enquanto a nova
 * URL carrega (e há um render com `carregando=false` antes do efeito). O aviso
 * de turno sem grupo e os cartões de Melhor Evolução só usam uma resposta
 * carregada PARA a URL atual — senão o pódio de uma turma decidiria o turno da
 * evolução por um instante (e dispararia consulta com o recorte errado).
 */
import { Award, TrendingUp, Trophy } from "lucide-react";
import { useId, useState } from "react";
import { Link } from "react-router-dom";

import { SeletorPeriodo, periodoParaQuery } from "../components/SeletorPeriodo";
import { SeletorTurno } from "../components/SeletorTurno";
import { Card, Carregando, PageHeader, Vazio, estiloInput } from "../components/ui";
import { useApp } from "../context/AppContext";
import { useApi } from "../hooks/useApi";
import { nota as fmtNota, numero, tempoLeitura } from "../lib/formato";
import { TURNO_TODOS, chaveTurno, rotuloTurno, turnoEfetivo, turnoParaQuery } from "../lib/turnos";
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

export default function Premiacoes() {
  const { escolaId, periodo, definirPeriodo, turno, definirTurno } = useApp();
  const [turmaId, setTurmaId] = useState("");
  const idMotivoTurno = useId();

  const { dados: turmas } = useApi<Turma[]>(
    escolaId ? `/escolas/${escolaId}/turmas` : null, { cacheMs: 60_000 });

  const q = periodoParaQuery(periodo);
  const filtroTurma = turmaId ? `&turma_id=${turmaId}` : "";
  // Só pede a quebra por turno na visão "todas as turmas".
  const pedirTurnos = turmaId ? "" : "&turnos=true";
  const urlPremiacoes = escolaId
    ? `/escolas/${escolaId}/premiacoes?${q}${filtroTurma}${pedirTurnos}` : null;
  // URL da última resposta que CHEGOU (ver "Dados DO RECORTE ATUAL" no topo).
  const [urlCarregada, setUrlCarregada] = useState<string | null>(null);
  const { dados: ultimaResposta, erro, carregando } = useApi<PremiacoesT>(urlPremiacoes, {
    aoSucesso: () => setUrlCarregada(urlPremiacoes),
  });
  const respostaAtual = urlCarregada === urlPremiacoes;
  const dados = !carregando && respostaAtual ? ultimaResposta : null;
  // Resposta antiga na mão e a nova ainda não chegou: é carregamento, não vazio.
  const aguardando = carregando || (!erro && ultimaResposta != null && !respostaAtual);

  // TURNO global: com uma turma selecionada, a turma vence (o turno não se
  // aplica). Um turno persistido que não existe nesta escola conta como "todos"
  // — sem sobrescrever a escolha guardada.
  const turnoAtivo = turmaId ? TURNO_TODOS : turnoEfetivo(turno, turmas);
  const turnos = (!turmaId && dados?.turnos) || [];
  // Escopo de categorias exibido: o grupo do turno escolhido ou "Todos".
  const grupoTurno = turnoAtivo !== TURNO_TODOS
    ? turnos.find((g) => chaveTurno(g.turno) === turnoAtivo) : undefined;
  // Turno escolhido, mas sem nenhum aluno matriculado nele neste ano letivo:
  // mostra "Todos" e AVISA (não finge que o pódio é do turno), sem mexer no que
  // está guardado. `dados` já é só a resposta do recorte atual.
  const turnoSemRecorte = turnoAtivo !== TURNO_TODOS && !!dados && !grupoTurno;
  const categorias = grupoTurno?.categorias ?? dados?.categorias ?? [];

  // Evolução respeita EXATAMENTE os mesmos filtros lockados: período + turma +
  // turno (vazio = "Sem turno"). Sem isto, a evolução ignoraria período/turno e
  // a tela mostraria recortes divergentes. Quando o turno não existe no recorte
  // (pódios caíram em "Todos"), a evolução também vai sem turno.
  const filtroTurno = turnoAtivo !== TURNO_TODOS && !turnoSemRecorte
    ? `&${turnoParaQuery(turnoAtivo)}` : "";
  const paramsEvol = `&${q}${filtroTurma}${filtroTurno}`;

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
          onChange={(e) => setTurmaId(e.target.value)}
        >
          <option value="">Todas as turmas</option>
          {(turmas ?? []).map((t) => <option key={t.id} value={t.id}>{t.nome}</option>)}
        </select>
        <SeletorTurno
          turmas={turmas ?? []}
          valor={turmaId ? TURNO_TODOS : turno}
          onChange={definirTurno}
          disabled={Boolean(turmaId)}
          descricaoId={turmaId ? idMotivoTurno : undefined}
        />
        {/* Motivo do seletor desabilitado em TEXTO visível (title não chega a
            leitor de tela nem a toque). */}
        {turmaId && (
          <span id={idMotivoTurno} className="text-xs text-zinc-500 dark:text-zinc-400">
            Com uma turma escolhida, o turno não se aplica.
          </span>
        )}
        {dados && (
          <span className="ml-auto inline-flex items-center gap-1.5 text-sm font-medium text-indigo-700 dark:text-indigo-300">
            <Trophy size={15} /> {dados.periodo.rotulo}
            {grupoTurno && <> · {grupoTurno.turno_rotulo} ({grupoTurno.total})</>}
          </span>
        )}
      </Card>

      {turnoSemRecorte && (
        <p role="status" className="mb-4 text-sm text-amber-700 dark:text-amber-300">
          Nenhum aluno matriculado no turno {rotuloTurno(turnoAtivo)} neste ano letivo; mostrando todos os turnos.
        </p>
      )}

      {aguardando ? (
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

          {/* MELHOR EVOLUÇÃO — quem mais cresceu no período (mesmo período +
              turma + turno dos pódios acima). */}
          <h2 className="mb-3 mt-8 text-sm font-semibold text-zinc-700 dark:text-zinc-300">
            Melhor Evolução no período
          </h2>
          {escolaId && (
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
          )}
        </>
      )}

      <p className="mt-6 flex items-center gap-1.5 text-xs text-zinc-400">
        <Award size={13} /> Melhor Matemática usa a nota oficial (0–100) do período. Evolução mede o crescimento dentro do intervalo, não o acumulado.
      </p>
      {grupoTurno && (
        <p className="mt-1 text-xs text-zinc-400">
          Vencedores calculados só com os alunos do turno selecionado; a régua da Matemática é a da escola inteira.
        </p>
      )}
    </div>
  );
}
