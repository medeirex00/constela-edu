/**
 * Aba "Evolução" da ficha do aluno: como o aluno evolui ao longo do tempo.
 *
 * Agrega as leituras (com data real, Fase 1) por semana, mês ou bimestre e
 * mostra em gráficos: livros lidos, pontos de dificuldade, tempo de leitura e
 * nível médio dos livros. Um link leva à evolução do Matific/ranking (que vem
 * dos snapshots).
 */
import { TrendingUp } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { GraficoLinha } from "./Grafico";
import { SeletorPeriodo, periodoParaQuery, type Periodo } from "./SeletorPeriodo";
import { Card, Carregando, Vazio } from "./ui";
import { api } from "../lib/api";

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

function CardGrafico({ titulo, series, campo }: {
  titulo: string;
  series: BaldeEvolucao[];
  campo: keyof BaldeEvolucao;
}) {
  const pontos = series.map((s) => ({ rotulo: s.rotulo, valor: Number(s[campo]) }));
  return (
    <Card className="p-4">
      <p className="mb-3 text-sm font-semibold">{titulo}</p>
      <GraficoLinha series={[{ nome: titulo, pontos }]} />
    </Card>
  );
}

export default function EvolucaoAlunoAba({ escolaId, alunoId }: {
  escolaId: number;
  alunoId: number | string;
}) {
  const [gran, setGran] = useState<string>("mes");
  const [periodo, setPeriodo] = useState<Periodo>({ preset: "tudo" });
  const [dados, setDados] = useState<EvolucaoLeitura | null>(null);
  const [carregando, setCarregando] = useState(true);

  const carregar = useCallback(() => {
    setCarregando(true);
    const q = periodoParaQuery(periodo);
    api<EvolucaoLeitura>(
      `/escolas/${escolaId}/alunos/${alunoId}/evolucao-leitura?granularidade=${gran}${q ? `&${q}` : ""}`,
    )
      .then(setDados)
      .catch(() => setDados(null))
      .finally(() => setCarregando(false));
  }, [escolaId, alunoId, gran, periodo]);

  useEffect(carregar, [carregar]);

  const series = dados?.series ?? [];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <div className="inline-flex rounded-xl border border-zinc-200 bg-white p-1 dark:border-zinc-800 dark:bg-zinc-900">
          {GRANULARIDADES.map((g) => (
            <button
              key={g.valor}
              type="button"
              onClick={() => setGran(g.valor)}
              className={`rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
                gran === g.valor
                  ? "bg-indigo-600 text-white shadow-sm"
                  : "text-zinc-600 hover:bg-zinc-100 dark:text-zinc-300 dark:hover:bg-zinc-800"
              }`}
            >
              {g.rotulo}
            </button>
          ))}
        </div>
        <SeletorPeriodo valor={periodo} onChange={setPeriodo} />
        <Link
          to={`/alunos/${alunoId}/evolucao`}
          className="ml-auto inline-flex items-center gap-1 text-sm font-medium text-indigo-600 hover:underline dark:text-indigo-400"
        >
          <TrendingUp size={14} /> Evolução do Matific e do ranking
        </Link>
      </div>

      {carregando ? (
        <Carregando />
      ) : series.length === 0 ? (
        <Card>
          <Vazio titulo="Sem leituras para montar a evolução"
                 descricao="Importe o relatório individual do Elefante Letrado (com as datas) para ver a evolução ao longo do tempo." />
        </Card>
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          <CardGrafico titulo="Livros lidos" series={series} campo="livros" />
          <CardGrafico titulo="Pontos de dificuldade" series={series} campo="pontos" />
          <CardGrafico titulo="Tempo de leitura (min)" series={series} campo="tempo_min" />
          <CardGrafico titulo="Nível médio dos livros" series={series} campo="nivel_medio" />
        </div>
      )}
    </div>
  );
}
