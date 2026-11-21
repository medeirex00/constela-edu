/**
 * Histórico de Leituras do aluno, filtrado por período (ou por um dia).
 *
 * Lista cronológica: livro, nível, data, horário, tempo e pontos de dificuldade
 * de cada leitura, com um resumo do período. O tempo/nível vêm do relatório
 * individual do Elefante Letrado (a plataforma de todas as linhas — dita uma vez
 * no cabeçalho do cartão, em vez de repetida em cada linha).
 */
import { BookMarked, BookOpen, Clock, Sparkles } from "lucide-react";
import { useState } from "react";

import { useApi } from "../hooks/useApi";
import { numero, tempoLeitura } from "../lib/formato";
import type { HistoricoLeituras as Historico } from "../lib/types";
import { CabecalhoCartao, ChipNivel, EsqueletoLista } from "./PessoasUi";
import { SeletorPeriodo, periodoParaQuery, type Periodo } from "./SeletorPeriodo";
import { Card, Erro, StatCard, Vazio, classesTabela } from "./ui";

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
  const { dados, erro, carregando, recarregar } = useApi<Historico>(
    `/escolas/${escolaId}/alunos/${alunoId}/leituras?${q}`,
  );

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <SeletorPeriodo valor={periodo} onChange={setPeriodo} comTudo />
        {dados && (
          <span className="rounded-full bg-white px-3 py-1 text-sm font-medium text-zinc-600 shadow-cartao dark:bg-zinc-900 dark:text-zinc-300">
            {dados.periodo.rotulo}
          </span>
        )}
      </div>

      {dados && (
        <div className="grid grid-cols-1 gap-5 sm:grid-cols-3">
          <StatCard icone={<BookMarked size={20} />} tom="violeta" rotulo="Livros lidos"
                    valor={numero(dados.resumo.total_livros)} />
          <StatCard icone={<Sparkles size={20} />} tom="ambar" rotulo="Pontos de dificuldade"
                    valor={numero(dados.resumo.pontos)} />
          <StatCard icone={<Clock size={20} />} tom="azul" rotulo="Tempo de leitura"
                    valor={tempoLeitura(dados.resumo.tempo_total_min)} />
        </div>
      )}

      <Card className="overflow-hidden">
        <CabecalhoCartao
          titulo="Leituras no Elefante Letrado"
          contagem={dados ? `${numero(dados.itens.length)} leitura${dados.itens.length === 1 ? "" : "s"}` : undefined}
        />
        {carregando ? (
          <EsqueletoLista texto="Carregando leituras..." />
        ) : erro ? (
          <Erro descricao={erro.message} aoTentar={recarregar} />
        ) : !dados || dados.itens.length === 0 ? (
          <Vazio icone={BookOpen} titulo="Nenhuma leitura no período"
                 descricao="Ajuste o período ou importe o relatório individual do Elefante Letrado." />
        ) : (
          <div className={classesTabela.moldura}>
            <table className={classesTabela.tabela}>
              <thead>
                <tr>
                  <th className={classesTabela.th}>Livro</th>
                  <th className={`text-center ${classesTabela.th}`}>Nível</th>
                  <th className={classesTabela.th}>Data</th>
                  <th className={classesTabela.th}>Horário</th>
                  <th className={`text-right ${classesTabela.th}`}>Tempo</th>
                  <th className={`text-right ${classesTabela.th}`}>Pontos</th>
                </tr>
              </thead>
              <tbody>
                {dados.itens.map((leitura) => {
                  const { data, hora } = partesData(leitura.data);
                  return (
                    <tr key={leitura.id} className={classesTabela.tr}>
                      <td className={classesTabela.td}>
                        <span className="block font-semibold text-zinc-900 dark:text-zinc-100">{leitura.livro}</span>
                        {leitura.categoria && (
                          <span className="block text-xs text-zinc-500 dark:text-zinc-400">{leitura.categoria}</span>
                        )}
                      </td>
                      <td className={`text-center ${classesTabela.td}`}>
                        {leitura.nivel ? (
                          <ChipNivel>{leitura.nivel}</ChipNivel>
                        ) : (
                          <span className="text-zinc-500">—</span>
                        )}
                      </td>
                      <td className={`whitespace-nowrap tabular-nums ${classesTabela.td}`}>{data}</td>
                      <td className={`tabular-nums text-zinc-500 dark:text-zinc-400 ${classesTabela.td}`}>{hora ?? "—"}</td>
                      <td className={`whitespace-nowrap text-right tabular-nums text-zinc-500 dark:text-zinc-400 ${classesTabela.td}`}>
                        {leitura.tempo_leitura_min != null ? tempoLeitura(leitura.tempo_leitura_min) : "—"}
                      </td>
                      <td className={`text-right font-bold tabular-nums text-zinc-900 dark:text-zinc-100 ${classesTabela.td}`}>
                        {numero(leitura.pontos)}
                      </td>
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
