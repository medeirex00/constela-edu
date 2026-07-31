/** Visão da escola (PRD §78): comparação entre todas as turmas. */
import { ChevronLeft } from "lucide-react";
import { Link } from "react-router-dom";

import { Card, Carregando, PageHeader, Vazio } from "../components/ui";
import { useApp } from "../context/AppContext";
import { useApi } from "../hooks/useApi";
import { usePerfil } from "../hooks/usePerfil";
import { nota, numero, tempoLeitura } from "../lib/formato";

interface ResumoTurma {
  turma: { id: number; nome: string; ano_escolar: string };
  total_alunos: number;
  media_geral: number;
  media_matific: number;
  media_elefante: number;
  indicadores: Record<string, number>;
}

interface ResumoEscola {
  escola: { id: number; nome: string };
  turmas: ResumoTurma[];
}

export default function VisaoEscola() {
  const { escolaId } = useApp();
  const { rede } = usePerfil();
  const { dados: resumo, erro, carregando } = useApi<ResumoEscola>(
    escolaId ? `/escolas/${escolaId}/resumo-escola` : null,
  );

  // Em vez de engolir a falha, mostra um estado de erro discreto.
  if (!carregando && erro) {
    return <Vazio titulo="Não foi possível carregar" descricao={erro.message} />;
  }
  if (!resumo) return <Carregando />;

  const maiorMedia = Math.max(...resumo.turmas.map((turma) => turma.media_geral), 0);

  return (
    <div>
      {rede && (
        <Link
          to="/rede"
          className="mb-3 inline-flex items-center gap-1 text-sm text-zinc-500 transition-colors hover:text-indigo-600 dark:hover:text-indigo-400"
        >
          <ChevronLeft size={16} /> Voltar para a visão da rede
        </Link>
      )}
      <PageHeader
        titulo="Visão da Escola"
        descricao="Comparação entre turmas: médias das notas e totais de cada plataforma."
      />
      <Card>
        {resumo.turmas.length === 0 ? (
          <Vazio titulo="Nenhuma turma no ano letivo ativo" />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm tabular-nums">
              <thead>
                <tr className="border-b border-zinc-200 text-left text-xs uppercase tracking-wide text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
                  <th className="px-4 py-2 font-medium">Turma</th>
                  <th className="px-4 py-2 text-right font-medium">Alunos</th>
                  <th className="px-4 py-2 text-right font-medium">Média geral</th>
                  <th className="hidden px-4 py-2 text-right font-medium sm:table-cell">Matific</th>
                  <th className="hidden px-4 py-2 text-right font-medium sm:table-cell">Leitura</th>
                  <th className="hidden px-4 py-2 text-right font-medium md:table-cell">Livros</th>
                  <th className="hidden px-4 py-2 text-right font-medium md:table-cell">Tempo</th>
                  <th className="px-4 py-2 font-medium" />
                </tr>
              </thead>
              <tbody>
                {resumo.turmas.map((item) => (
                  <tr key={item.turma.id} className="border-b border-zinc-100 last:border-0 dark:border-zinc-800/60">
                    <td className="px-4 py-2.5">
                      <Link to={`/turmas/${item.turma.id}`} className="font-medium hover:text-indigo-600 dark:hover:text-indigo-400">
                        {item.turma.nome}
                      </Link>
                      <span className="ml-2 text-xs text-zinc-400">{item.turma.ano_escolar}</span>
                    </td>
                    <td className="px-4 py-2.5 text-right">{numero(item.total_alunos)}</td>
                    <td className="px-4 py-2.5 text-right">
                      <div className="flex items-center justify-end gap-2">
                        <div className="h-2 w-24 overflow-hidden rounded bg-zinc-100 dark:bg-zinc-800">
                          <div
                            className="h-full rounded bg-indigo-500"
                            style={{ width: `${maiorMedia ? (item.media_geral / maiorMedia) * 100 : 0}%` }}
                          />
                        </div>
                        <span className="font-semibold">{nota(item.media_geral)}</span>
                      </div>
                    </td>
                    <td className="hidden px-4 py-2.5 text-right sm:table-cell">{nota(item.media_matific)}</td>
                    <td className="hidden px-4 py-2.5 text-right sm:table-cell">{nota(item.media_elefante)}</td>
                    <td className="hidden px-4 py-2.5 text-right md:table-cell">{numero(item.indicadores.livros_unicos ?? 0)}</td>
                    <td className="hidden px-4 py-2.5 text-right md:table-cell">{tempoLeitura(item.indicadores.tempo_leitura_min ?? 0)}</td>
                    <td className="px-4 py-2.5 text-right">
                      <Link to={`/turmas/${item.turma.id}`} className="text-xs text-indigo-600 hover:underline dark:text-indigo-400">
                        detalhes
                      </Link>
                    </td>
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
