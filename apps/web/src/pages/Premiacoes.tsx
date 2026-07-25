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

type PlacarItem = {
  nome: string;
  turma: string | null;
  estrelas: number;
  atividades: number;
  aluno_id: number | null;
};
type PlacarAoVivo = { periodo: string; atualizado_em: string; total: number; itens: PlacarItem[] };

/**
 * "Destaque no Matific" AO VIVO. Consulta o Placar do Matific pelo período (o
 * mesmo mecanismo do Ranking de Matemática): ano letivo vem do banco local
 * (sincronização diária) e sub-períodos vêm do Matific em tempo real. Assim
 * premia o período ATUAL de qualquer escola — inclusive uma que entrou no meio
 * do bimestre — SEM precisar importar relatório (não depende de snapshots
 * datados como o card de leitura). Se as credenciais não estiverem prontas,
 * explica em vez de sumir.
 */
function CartaoMatificAoVivo({ escolaId, periodo, turmaNome }: {
  escolaId: number; periodo: Periodo; turmaNome?: string;
}) {
  // Professor não acessa Sincronização — para ele o erro não oferece o link,
  // aponta para o coordenador. (O placar já vem filtrado nos alunos dele.)
  const { usuario } = useApp();
  const gestor = Boolean(usuario?.is_global)
    || ["admin", "coordenador"].includes(usuario?.cargo ?? "");
  const isAno = periodo.preset === "ano_letivo";
  // Personalizado só busca com as duas datas — não dispara login pela metade.
  const periodoCompleto = periodo.preset !== "personalizado" || Boolean(periodo.inicio && periodo.fim);
  const q = periodoParaQuery(periodo);
  const local = useApi<PlacarItem[]>(
    escolaId && isAno ? `/escolas/${escolaId}/ranking/matematica?periodo=ano_letivo` : null,
  );
  const live = useApi<PlacarAoVivo>(
    escolaId && !isAno && periodoCompleto
      ? `/escolas/${escolaId}/sync/matific/placar-ao-vivo?${q}` : null,
    { timeoutMs: 180_000, tentativas: 0 },
  );
  const carregando = isAno ? local.carregando : live.carregando;
  const erro = isAno ? local.erro : live.erro;
  const brutos: PlacarItem[] = isAno ? (local.dados ?? []) : (live.dados?.itens ?? []);

  // Filtra por turma só se o Placar trouxer turma (o Matific nem sempre traz).
  const temTurma = brutos.some((i) => i.turma);
  const podio = brutos
    .filter((i) => (turmaNome && temTurma ? i.turma === turmaNome : true))
    .filter((i) => i.atividades > 0)
    .slice()
    .sort((a, b) => b.atividades - a.atividades)
    .slice(0, 5);
  const [campeao, ...resto] = podio;

  const classeCampeao =
    "flex items-center gap-3 rounded-xl border border-amber-200 bg-amber-50/70 p-3 dark:border-amber-500/20 dark:bg-amber-500/10";
  const conteudoCampeao = campeao && (
    <>
      <span className="text-2xl">🥇</span>
      <div className="min-w-0 flex-1">
        <p className="truncate font-semibold">{campeao.nome}</p>
        {campeao.turma && <p className="text-xs text-zinc-500 dark:text-zinc-400">{campeao.turma}</p>}
      </div>
      <span className="shrink-0 text-right text-sm font-bold tabular-nums text-amber-700 dark:text-amber-300">
        {numero(campeao.atividades)} atividades
      </span>
    </>
  );

  return (
    <Card className="flex flex-col p-5">
      <div className="mb-3 flex items-start gap-3">
        <span className="text-2xl leading-none">🧮</span>
        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-semibold">Destaque no Matific</h3>
          <p className="text-xs text-zinc-500 dark:text-zinc-400">
            Mais atividades no Matific no período {isAno ? "(banco local)" : "· ao vivo"}
          </p>
        </div>
      </div>

      {carregando ? (
        <div className="py-6"><Carregando texto="Consultando o Matific…" /></div>
      ) : erro ? (
        <p className="py-6 text-center text-sm text-zinc-400">
          Não foi possível consultar o Matific agora.{" "}
          {gestor ? (
            <>
              Verifique as credenciais em{" "}
              <Link to="/sincronizacao" className="font-medium underline">Sincronização</Link> e tente de novo.
            </>
          ) : (
            "Peça ao coordenador para verificar a conexão com o Matific."
          )}
        </p>
      ) : !campeao ? (
        <p className="py-6 text-center text-sm text-zinc-400">Sem atividades do Matific neste período.</p>
      ) : (
        <>
          {campeao.aluno_id ? (
            <Link to={`/alunos/${campeao.aluno_id}`} className={`${classeCampeao} transition-colors hover:bg-amber-50`}>
              {conteudoCampeao}
            </Link>
          ) : (
            <div className={classeCampeao}>{conteudoCampeao}</div>
          )}
          {resto.length > 0 && (
            <ul className="mt-2 space-y-0.5">
              {resto.map((item, i) => (
                <li key={item.aluno_id ?? item.nome}
                    className="flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm">
                  <span className="w-6 shrink-0 text-center">{MEDALHAS[i + 1] ?? `${i + 2}º`}</span>
                  <span className="min-w-0 flex-1 truncate">{item.nome}</span>
                  <span className="shrink-0 tabular-nums text-zinc-500 dark:text-zinc-400">
                    {numero(item.atividades)}
                  </span>
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

  const { dados: turmas } = useApi<Turma[]>(
    escolaId ? `/escolas/${escolaId}/turmas` : null, { cacheMs: 60_000 });

  const q = periodoParaQuery(periodo);
  const filtroTurma = turmaId ? `&turma_id=${turmaId}` : "";
  const turmaNome = (turmas ?? []).find((t) => String(t.id) === turmaId)?.nome;
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
          {dados.categorias
            .filter((categoria) => categoria.chave !== "destaque_matific")
            .map((categoria) => (
              <CartaoCategoria key={categoria.chave} categoria={categoria} />
            ))}
          {/* O Matific vem AO VIVO do Placar pelo período (não de snapshot
              datado) — funciona mesmo para escolas que entraram no meio do
              bimestre, sem importar nada. */}
          {escolaId && (
            <CartaoMatificAoVivo escolaId={escolaId} periodo={periodo} turmaNome={turmaNome} />
          )}
        </div>
      )}

      <p className="mt-6 flex items-center gap-1.5 text-xs text-zinc-400">
        <Award size={13} /> Leitura: pelo que foi registrado no período. Matific: consultado ao vivo pelo período (ano letivo vem do banco local).
      </p>
    </div>
  );
}
