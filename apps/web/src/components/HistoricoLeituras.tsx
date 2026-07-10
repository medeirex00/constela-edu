/**
 * Histórico de Leituras do aluno, filtrado por período (ou por um dia).
 *
 * Lista cronológica: livro, nível, plataforma, data, horário, tempo e pontos
 * de dificuldade de cada leitura, com um resumo do período. O tempo/nível
 * vêm do relatório individual do Elefante Letrado.
 */
import { BookMarked, Clock, Sparkles } from "lucide-react";
import { useState } from "react";

import { useApi } from "../hooks/useApi";
import { numero, tempoLeitura } from "../lib/formato";
import type { HistoricoLeituras as Historico } from "../lib/types";
import { SeletorPeriodo, periodoParaQuery, type Periodo } from "./SeletorPeriodo";
import { Badge, Card, Carregando, StatCard, Vazio } from "./ui";

/** Formata a data ISO sem depender de fuso (a hora guardada já é local). */
function partesData(iso: string): { data: string; hora: string | null } {
  const [d, t] = iso.split("T");
  const [ano, mes, dia] = d.split("-");
  return { data: `${dia}/${mes}/${ano}`, hora: t ? t.slice(0, 5) : null };
}

export default function HistoricoLeituras({ escolaId, alunoId }: {
  escolaId: number;
  alunoId: number | string;
}) {
  const [periodo, setPeriodo] = useState<Periodo>({ preset: "tudo" });
  const q = periodoParaQuery(periodo);
  const { dados, erro, carregando } = useApi<Historico>(
    `/escolas/${escolaId}/alunos/${alunoId}/leituras?${q}`,
  );

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <SeletorPeriodo valor={periodo} onChange={setPeriodo} />
        {dados && (
          <span className="text-sm text-zinc-500 dark:text-zinc-400">{dados.periodo.rotulo}</span>
        )}
      </div>

      {dados && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <StatCard icone={<BookMarked size={15} />} rotulo="Livros lidos" valor={numero(dados.resumo.total_livros)} />
          <StatCard icone={<Sparkles size={15} />} rotulo="Pontos de dificuldade" valor={numero(dados.resumo.pontos)} />
          <StatCard icone={<Clock size={15} />} rotulo="Tempo de leitura" valor={tempoLeitura(dados.resumo.tempo_total_min)} />
        </div>
      )}

      <Card>
        {carregando ? (
          <Carregando />
        ) : erro ? (
          <Vazio titulo="Não foi possível carregar" descricao={erro.message} />
        ) : !dados || dados.itens.length === 0 ? (
          <Vazio titulo="Nenhuma leitura no período"
                 descricao="Ajuste o período ou importe o relatório individual do Elefante Letrado." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-zinc-200 text-left text-xs uppercase tracking-wide text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
                  <th className="px-4 py-2 font-medium">Livro</th>
                  <th className="px-2 py-2 text-center font-medium">Nível</th>
                  <th className="px-2 py-2 font-medium">Plataforma</th>
                  <th className="px-2 py-2 font-medium">Data</th>
                  <th className="px-2 py-2 font-medium">Horário</th>
                  <th className="px-2 py-2 text-right font-medium">Tempo</th>
                  <th className="px-4 py-2 text-right font-medium">Pontos</th>
                </tr>
              </thead>
              <tbody>
                {dados.itens.map((leitura) => {
                  const { data, hora } = partesData(leitura.data);
                  return (
                    <tr key={leitura.id} className="border-b border-zinc-100 last:border-0 dark:border-zinc-800/60">
                      <td className="px-4 py-2.5">
                        <span className="font-medium">{leitura.livro}</span>
                        {leitura.categoria && (
                          <span className="ml-2 text-xs text-zinc-400">{leitura.categoria}</span>
                        )}
                      </td>
                      <td className="px-2 py-2.5 text-center">
                        <Badge>{leitura.nivel || "—"}</Badge>
                      </td>
                      <td className="px-2 py-2.5 text-zinc-500 dark:text-zinc-400">Elefante Letrado</td>
                      <td className="px-2 py-2.5 tabular-nums">{data}</td>
                      <td className="px-2 py-2.5 tabular-nums text-zinc-500 dark:text-zinc-400">{hora ?? "—"}</td>
                      <td className="px-2 py-2.5 text-right tabular-nums text-zinc-500 dark:text-zinc-400">
                        {leitura.tempo_leitura_min != null ? tempoLeitura(leitura.tempo_leitura_min) : "—"}
                      </td>
                      <td className="px-4 py-2.5 text-right font-medium tabular-nums">{numero(leitura.pontos)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
