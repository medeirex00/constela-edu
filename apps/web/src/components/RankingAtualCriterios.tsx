/**
 * "Ranking atual com esta régua" — os 5 primeiros de CADA matéria AGORA, pela
 * nota oficial (0 a 100) do ano letivo, na escola inteira. É o lugar da "prévia
 * ao vivo" da referência visual, com dado REAL: não existe cálculo de prévia no
 * backend e uma segunda fórmula no front é proibida, então aqui só aparece a
 * ordem que o servidor já calculou (GET /escolas/{id}/ranking?dimensao=...),
 * fatiada nos 5 primeiros para caber no cartão.
 *
 * Quem pode ver: a gestão da escola e o Admin Global (a tela é RotaGestao). A
 * Secretaria NÃO recebe nome de criança — a página nem monta este cartão para ela.
 * Matéria fora do plano da rede (useModulos) não aparece.
 */
import { BarChart3, BookOpen, Calculator } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useEffect, useId } from "react";
import { Link } from "react-router-dom";

import { useApp } from "../context/AppContext";
import { useApi } from "../hooks/useApi";
import { useModulos } from "../hooks/useModulos";
import type { RankingItem } from "../lib/types";
import { CabecalhoCartao } from "./CriteriosVisuais";
import { Avatar, Chip, Erro, IconePastel, PosicaoBolinha, Skeleton, Vazio, type TomPastel } from "./ui";

const TOPO = 5;

/** Nota com DUAS casas sempre ("87,50", não "87,5"): a coluna alinhada à direita
 *  fica com os números alinhados. Só a apresentação muda; o valor é o da API. */
const formatoNota = new Intl.NumberFormat("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

const MATERIAS: Record<"leitura" | "matematica", { rotulo: string; plataforma: string; icone: LucideIcon; tom: TomPastel }> = {
  leitura: { rotulo: "Leitura", plataforma: "Elefante Letrado", icone: BookOpen, tom: "violeta" },
  matematica: { rotulo: "Matemática", plataforma: "Matific", icone: Calculator, tom: "teal" },
};

function TopoDaMateria({ dimensao, versao }: { dimensao: "leitura" | "matematica"; versao: number }) {
  const { escolaId } = useApp();
  const materia = MATERIAS[dimensao];
  const idTitulo = useId();
  const { dados, erro, carregando, recarregar } = useApi<RankingItem[]>(
    escolaId ? `/escolas/${escolaId}/ranking?dimensao=${dimensao}` : null,
  );

  // Depois de "Salvar pesos" (Admin Global) as notas são recalculadas: a página
  // sobe `versao` e a lista é buscada de novo, com a ordem nova do servidor.
  useEffect(() => {
    if (versao > 0) recarregar();
  }, [versao]); // eslint-disable-line react-hooks/exhaustive-deps

  const itens = (dados ?? []).slice(0, TOPO);
  const total = dados?.[0]?.n_aferidos ?? dados?.length ?? 0;

  return (
    <div className="flex min-w-0 flex-col rounded-2xl border border-zinc-200/80 p-4 dark:border-zinc-800">
      <div className="flex items-center gap-3">
        <IconePastel icone={materia.icone} tom={materia.tom} tamanho="sm" />
        <div className="min-w-0 flex-1">
          <h3 id={idTitulo} className="text-[15px] font-semibold text-zinc-900 dark:text-white">
            {materia.rotulo} <span className="font-medium text-zinc-500 dark:text-zinc-400">· {materia.plataforma}</span>
          </h3>
          {!carregando && !erro && itens.length > 0 && (
            <p className="text-xs text-zinc-500 dark:text-zinc-400">
              {total === 1 ? "1 aluno aferido" : `${total.toLocaleString("pt-BR")} alunos aferidos`}
            </p>
          )}
        </div>
      </div>

      {carregando ? (
        <div className="mt-4 space-y-3" aria-hidden>
          {Array.from({ length: TOPO }, (_, i) => (
            <Skeleton key={i} className="h-9" />
          ))}
        </div>
      ) : erro ? (
        <Erro titulo="Não foi possível carregar o ranking" descricao={erro.message} aoTentar={recarregar} />
      ) : itens.length === 0 ? (
        <Vazio
          icone={BarChart3}
          titulo={`Nenhum aluno aferido em ${materia.rotulo} ainda`}
          descricao="O ranking aparece quando a plataforma enviar os primeiros dados."
        />
      ) : (
        <ol aria-labelledby={idTitulo} className="mt-4 space-y-1.5">
          {itens.map((item) => (
            <li
              key={item.aluno_id}
              className="flex items-center gap-3 rounded-xl px-2 py-1.5 transition-colors hover:bg-zinc-50 dark:hover:bg-zinc-800/50"
            >
              <PosicaoBolinha posicao={item.posicao} />
              <Avatar nome={item.nome} chave={item.aluno_id} tamanho="sm" />
              <div className="min-w-0 flex-1">
                <p className="line-clamp-2 break-words text-sm font-semibold text-zinc-900 dark:text-zinc-50" title={item.nome}>{item.nome}</p>
                {item.turma && <Chip className="mt-0.5 px-1.5 py-0.5 text-[11px]">{item.turma}</Chip>}
              </div>
              <span className="shrink-0 text-right">
                <span className="block text-[15px] font-bold tabular-nums text-zinc-900 dark:text-white">
                  {typeof item.nota === "number" ? formatoNota.format(item.nota) : "—"}
                </span>
                <span className="block text-[11px] text-zinc-500 dark:text-zinc-400">nota</span>
              </span>
            </li>
          ))}
        </ol>
      )}

      <Link
        to={`/ranking?ver=${dimensao}`}
        className="mt-auto pt-4 text-sm font-semibold text-indigo-600 hover:text-indigo-700 hover:underline dark:text-indigo-300"
      >
        Ver ranking completo de {materia.rotulo}
      </Link>
    </div>
  );
}

export default function RankingAtualCriterios({
  versao = 0,
  subtitulo = "Os 5 primeiros de cada matéria agora, pela nota oficial (0 a 100) do ano letivo, na escola inteira.",
}: {
  /** Sobe a cada "Salvar pesos": a lista é buscada de novo. */
  versao?: number;
  subtitulo?: string;
}) {
  const modulos = useModulos();
  const idTitulo = useId();
  const materias = (["leitura", "matematica"] as const).filter((m) => modulos.tem(m));
  if (materias.length === 0) return null;
  return (
    <section aria-labelledby={idTitulo} className="card p-5 sm:p-6">
      <CabecalhoCartao id={idTitulo} icone={BarChart3} tom="azul" titulo="Ranking atual com esta régua" subtitulo={subtitulo} />
      <div className={`mt-5 grid gap-4 ${materias.length > 1 ? "md:grid-cols-2" : ""}`}>
        {materias.map((m) => (
          <TopoDaMateria key={m} dimensao={m} versao={versao} />
        ))}
      </div>
    </section>
  );
}
