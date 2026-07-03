/** Inteligência Pedagógica (PRD §129–§153): índices e alertas automáticos. */
import { AlertTriangle, Lightbulb } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { Badge, Card, Carregando, PageHeader, Vazio } from "../components/ui";
import { useApp } from "../context/AppContext";
import { api } from "../lib/api";
import { nota } from "../lib/formato";

interface IndiceAluno {
  aluno_id: number;
  nome: string;
  turma: string;
  engajamento: number;
  evolucao: number;
  persistencia: number;
}

interface Alerta {
  tipo: string;
  gravidade: "alta" | "media" | "baixa";
  aluno_id: number;
  nome: string;
  turma: string;
  texto: string;
}

interface InsightsResposta {
  indices: IndiceAluno[];
  alertas: Alerta[];
}

function BarraIndice({ valor }: { valor: number }) {
  const cor = valor >= 66 ? "bg-emerald-500" : valor >= 33 ? "bg-amber-500" : "bg-red-400";
  return (
    <div className="flex items-center gap-2">
      <div className="h-2 w-16 overflow-hidden rounded bg-zinc-100 dark:bg-zinc-800">
        <div className={`h-full rounded ${cor}`} style={{ width: `${Math.min(100, valor)}%` }} />
      </div>
      <span className="w-10 text-right tabular-nums">{nota(valor)}</span>
    </div>
  );
}

export default function Insights() {
  const { escolaId } = useApp();
  const [dadosInsights, setDadosInsights] = useState<InsightsResposta | null>(null);

  useEffect(() => {
    if (!escolaId) return;
    setDadosInsights(null);
    api<InsightsResposta>(`/escolas/${escolaId}/insights`)
      .then(setDadosInsights)
      .catch(() => setDadosInsights({ indices: [], alertas: [] }));
  }, [escolaId]);

  if (!dadosInsights) return <Carregando />;

  return (
    <div className="space-y-6">
      <PageHeader
        titulo="Inteligência Pedagógica"
        descricao="Índices e alertas calculados por regras transparentes sobre os dados reais — sem caixa-preta."
      />

      <Card>
        <div className="flex items-center gap-2 border-b border-zinc-200 px-4 py-3 dark:border-zinc-800">
          <AlertTriangle size={15} className="text-amber-500" />
          <h3 className="text-sm font-semibold">Alertas ({dadosInsights.alertas.length})</h3>
        </div>
        {dadosInsights.alertas.length === 0 ? (
          <Vazio titulo="Nenhum alerta" descricao="Todos os alunos estão com dados recentes e desempenho estável." />
        ) : (
          <ul className="divide-y divide-zinc-100 dark:divide-zinc-800/60">
            {dadosInsights.alertas.map((alerta, indice) => (
              <li key={indice} className="flex items-start gap-3 px-4 py-3">
                <Badge tom={alerta.gravidade === "alta" ? "alerta" : "neutro"}>
                  {alerta.gravidade}
                </Badge>
                <div>
                  <p className="text-sm">{alerta.texto}</p>
                  <Link
                    to={`/alunos/${alerta.aluno_id}`}
                    className="text-xs text-indigo-600 hover:underline dark:text-indigo-400"
                  >
                    ver perfil de {alerta.nome}
                  </Link>
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card>
        <div className="flex items-center gap-2 border-b border-zinc-200 px-4 py-3 dark:border-zinc-800">
          <Lightbulb size={15} className="text-indigo-500" />
          <h3 className="text-sm font-semibold">Índices por aluno</h3>
          <span className="ml-auto text-xs text-zinc-400">
            engajamento (30d) · evolução (90d) · persistência (constância)
          </span>
        </div>
        {dadosInsights.indices.length === 0 ? (
          <Vazio titulo="Sem dados" descricao="Importe relatórios para calcular os índices." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-zinc-200 text-left text-xs uppercase tracking-wide text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
                  <th className="px-4 py-2 font-medium">Aluno</th>
                  <th className="hidden px-4 py-2 font-medium md:table-cell">Turma</th>
                  <th className="px-4 py-2 font-medium">Engajamento</th>
                  <th className="px-4 py-2 font-medium">Evolução</th>
                  <th className="px-4 py-2 font-medium">Persistência</th>
                </tr>
              </thead>
              <tbody>
                {dadosInsights.indices.map((item) => (
                  <tr key={item.aluno_id} className="border-b border-zinc-100 last:border-0 dark:border-zinc-800/60">
                    <td className="px-4 py-2.5">
                      <Link to={`/alunos/${item.aluno_id}`} className="font-medium hover:text-indigo-600 dark:hover:text-indigo-400">
                        {item.nome}
                      </Link>
                    </td>
                    <td className="hidden px-4 py-2.5 text-zinc-500 dark:text-zinc-400 md:table-cell">{item.turma}</td>
                    <td className="px-4 py-2.5"><BarraIndice valor={item.engajamento} /></td>
                    <td className="px-4 py-2.5"><BarraIndice valor={item.evolucao} /></td>
                    <td className="px-4 py-2.5"><BarraIndice valor={item.persistencia} /></td>
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
