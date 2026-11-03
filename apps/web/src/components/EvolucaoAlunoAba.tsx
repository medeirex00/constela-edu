/**
 * Aba "Evolução" da ficha do aluno: como o aluno evolui ao longo do tempo.
 *
 * Agrega as leituras (com data real, Fase 1) por semana, mês ou bimestre e
 * mostra em gráficos: livros lidos, pontos de dificuldade, tempo de leitura e
 * nível médio dos livros. Um link leva à evolução do Matific/ranking (que vem
 * dos snapshots).
 */
import { BookMarked, Clock, Gauge, LineChart, Sparkles, TrendingUp } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { GraficoLinha } from "./Grafico";
import { SeletorPeriodo, periodoParaQuery, type Periodo } from "./SeletorPeriodo";
import { Card, ESTILOS_BOTAO, Erro, IconePastel, Skeleton, TAMANHOS_BOTAO, Vazio } from "./ui";
import type { TomPastel } from "./ui";
import { useApi } from "../hooks/useApi";

interface BaldeEvolucao {
  rotulo: string;
  livros: number;
  pontos: number;
  tempo_min: number;
  nivel_medio: number;
}
interface EvolucaoLeitura {
  granularidade: string;
  series: BaldeEvolucao[];
}

const GRANULARIDADES = [
  { valor: "semana", rotulo: "Semana" },
  { valor: "mes", rotulo: "Mês" },
  { valor: "bimestre", rotulo: "Bimestre" },
] as const;

/** Leitura = Elefante Letrado: a série vai em violeta (identidade v2). */
const COR_LEITURA = "#6C5CE7";

function CardGrafico({ titulo, series, campo, icone, tom }: {
  titulo: string;
  series: BaldeEvolucao[];
  campo: keyof BaldeEvolucao;
  icone: LucideIcon;
  tom: TomPastel;
}) {
  const pontos = series.map((s) => ({ rotulo: s.rotulo, valor: Number(s[campo]) }));
  return (
    <Card className="p-5">
      <div className="mb-3 flex items-center gap-3">
        <IconePastel icone={icone} tom={tom} tamanho="sm" />
        <p className="text-sm font-semibold">{titulo}</p>
      </div>
      <GraficoLinha series={[{ nome: titulo, pontos, cor: COR_LEITURA }]} rotulo={`${titulo} ao longo do tempo`} />
    </Card>
  );
}

export default function EvolucaoAlunoAba({ escolaId, alunoId }: {
  escolaId: number;
  alunoId: number | string;
}) {
  const [gran, setGran] = useState<string>("mes");
  const [periodo, setPeriodo] = useState<Periodo>({ preset: "tudo" });

  // A URL muda com granularidade/período; o useApi refaz a busca sozinho.
  const q = periodoParaQuery(periodo);
  const { dados, erro, carregando, recarregar } = useApi<EvolucaoLeitura>(
    `/escolas/${escolaId}/alunos/${alunoId}/evolucao-leitura?granularidade=${gran}${q ? `&${q}` : ""}`,
  );

  const series = dados?.series ?? [];

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-3">
        {/* Agrupamento: botões alternáveis (aria-pressed), na pílula segmentada da v2. */}
        <div
          role="group"
          aria-label="Agrupar por"
          className="inline-flex gap-1 rounded-2xl border border-zinc-200/80 bg-white p-1 shadow-cartao dark:border-zinc-800 dark:bg-zinc-900"
        >
          {GRANULARIDADES.map((g) => (
            <button
              key={g.valor}
              type="button"
              aria-pressed={gran === g.valor}
              onClick={() => setGran(g.valor)}
              className={`rounded-xl px-3.5 py-2 text-sm font-semibold transition-colors ${
                gran === g.valor
                  ? "bg-indigo-600 text-white shadow-pilula"
                  : "text-zinc-600 hover:bg-zinc-100 hover:text-zinc-900 dark:text-zinc-300 dark:hover:bg-zinc-800 dark:hover:text-white"
              }`}
            >
              {g.rotulo}
            </button>
          ))}
        </div>
        <SeletorPeriodo valor={periodo} onChange={setPeriodo} />
        <Link
          to={`/alunos/${alunoId}/evolucao`}
          className={`ml-auto inline-flex items-center justify-center font-semibold transition-colors ${TAMANHOS_BOTAO.md} ${ESTILOS_BOTAO.secundario}`}
        >
          <TrendingUp size={16} aria-hidden /> Evolução do Matific e do ranking
        </Link>
      </div>

      {carregando ? (
        <div role="status" className="grid grid-cols-1 gap-5 lg:grid-cols-2">
          <span className="sr-only">Carregando...</span>
          {[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-60 rounded-cartao" />)}
        </div>
      ) : erro ? (
        <Card>
          <Erro descricao={erro.message} aoTentar={recarregar} />
        </Card>
      ) : series.length === 0 ? (
        <Card>
          <Vazio icone={LineChart} titulo="Sem leituras para montar a evolução"
                 descricao="Importe o relatório individual do Elefante Letrado (com as datas) para ver a evolução ao longo do tempo." />
        </Card>
      ) : (
        <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
          <CardGrafico titulo="Livros lidos" series={series} campo="livros" icone={BookMarked} tom="violeta" />
          <CardGrafico titulo="Pontos de dificuldade" series={series} campo="pontos" icone={Sparkles} tom="ambar" />
          <CardGrafico titulo="Tempo de leitura (min)" series={series} campo="tempo_min" icone={Clock} tom="azul" />
          <CardGrafico titulo="Nível médio dos livros" series={series} campo="nivel_medio" icone={Gauge} tom="verde" />
        </div>
      )}
    </div>
  );
}
