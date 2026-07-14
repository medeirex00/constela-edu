/**
 * Ranking de Matemática (Matific) EM TEMPO REAL — "Premiar por período".
 *
 * A tela não lê mais snapshots locais: ao escolher o período, o Constela
 * CONSULTA o Placar do Matific ao vivo (mesmo mecanismo do site — duration/
 * start_date+end_date) e mostra exatamente os mesmos alunos, estrelas e
 * atividades. A 1ª consulta após ociosidade faz login (mais lenta); as
 * seguintes reusam a sessão cifrada e são rápidas.
 */
import { Calculator, Radio, RefreshCw } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { SeletorPeriodo, periodoParaQuery, type Periodo } from "../components/SeletorPeriodo";
import { Card, Carregando, PageHeader, Vazio, estiloInput } from "../components/ui";
import { useApp } from "../context/AppContext";
import { useApi } from "../hooks/useApi";
import { numero } from "../lib/formato";

type PlacarItem = {
  posicao: number;
  nome: string;
  turma: string | null;
  serie: string | null;
  estrelas: number;
  atividades: number;
  pontuacao_media: number;
  aluno_id: number | null;
};
type PlacarAoVivo = {
  periodo: string;
  filtro: string;
  atualizado_em: string;
  total: number;
  com_link: number;
  itens: PlacarItem[];
};

export default function RankingMatematica({ embutido = false }: { embutido?: boolean } = {}) {
  const { escolaId } = useApp();
  const [periodo, setPeriodo] = useState<Periodo>({ preset: "mes" });
  const [turmaSel, setTurmaSel] = useState("");

  // Só consulta quando o período está completo (personalizado exige as 2 datas)
  // — evita disparar um login no Matific com o intervalo pela metade.
  const periodoCompleto =
    periodo.preset !== "personalizado" || Boolean(periodo.inicio && periodo.fim);

  const q = periodoParaQuery(periodo);
  const { dados, erro, carregando, recarregar } = useApi<PlacarAoVivo>(
    escolaId ? `/escolas/${escolaId}/sync/matific/placar-ao-vivo?${q}` : null,
    {
      ativo: Boolean(escolaId) && periodoCompleto,
      // Login no Matific pode levar ~1 min na 1ª consulta; não retentar (não
      // queremos disparar um segundo login por timeout).
      timeoutMs: 180_000,
      tentativas: 0,
    },
  );

  const itens = dados?.itens ?? [];
  const turmas = useMemo(
    () => (Array.from(new Set(itens.map((i) => i.turma).filter(Boolean))) as string[]).sort(),
    [itens],
  );
  const visiveis = turmaSel ? itens.filter((i) => i.turma === turmaSel) : itens;

  const atualizadoEm = dados?.atualizado_em
    ? new Date(dados.atualizado_em).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" })
    : null;

  return (
    <div>
      {!embutido && (
        <PageHeader
          titulo="Premiar por período (Matific ao vivo)"
          descricao="Consulta o Placar do Matific em tempo real para o período escolhido — os mesmos alunos, estrelas e atividades do site oficial."
        />
      )}

      <Card className="mb-4 flex flex-wrap items-center gap-3 p-4">
        <SeletorPeriodo valor={periodo} onChange={setPeriodo} />
        <select
          aria-label="Filtrar por turma"
          className={`${estiloInput} w-auto`}
          value={turmaSel}
          onChange={(e) => setTurmaSel(e.target.value)}
        >
          <option value="">Todas as turmas</option>
          {turmas.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
        <button
          type="button"
          onClick={() => recarregar()}
          disabled={carregando || !periodoCompleto}
          className={`${estiloInput} inline-flex w-auto items-center gap-1.5 disabled:opacity-50`}
        >
          <RefreshCw size={14} className={carregando ? "animate-spin" : ""} /> Atualizar
        </button>
        {atualizadoEm && !carregando && (
          <span className="inline-flex items-center gap-1.5 text-xs text-emerald-600 dark:text-emerald-400">
            <Radio size={13} /> Dados do Matific · {atualizadoEm}
          </span>
        )}
      </Card>

      <Card>
        {!periodoCompleto ? (
          <Vazio titulo="Escolha as duas datas"
                 descricao="Para o período personalizado, informe a data inicial e a final." />
        ) : carregando ? (
          <div className="flex flex-col items-center gap-2 py-10 text-center">
            <Carregando />
            <p className="text-sm text-zinc-500 dark:text-zinc-400">
              Consultando o Matific em tempo real…
            </p>
            <p className="max-w-md text-xs text-zinc-400">
              A primeira consulta pode levar cerca de um minuto (o robô faz login no
              Matific). As próximas ficam rápidas.
            </p>
          </div>
        ) : erro ? (
          <Vazio titulo="Não foi possível consultar o Matific" descricao={erro.message} />
        ) : visiveis.length === 0 ? (
          <Vazio titulo="Nenhuma atividade de matemática no período"
                 descricao="Ninguém pontuou no Matific nesse intervalo. Ajuste o período." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm tabular-nums">
              <thead>
                <tr className="border-b border-zinc-200 text-left text-xs uppercase tracking-wide text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
                  <th className="px-4 py-2 font-medium">#</th>
                  <th className="px-4 py-2 font-medium">Aluno</th>
                  <th className="hidden px-4 py-2 font-medium md:table-cell">Turma</th>
                  <th className="px-4 py-2 text-right font-medium">Estrelas</th>
                  <th className="px-4 py-2 text-right font-medium">Atividades</th>
                  <th className="hidden px-4 py-2 text-right font-medium sm:table-cell">Pontuação média (no período)</th>
                </tr>
              </thead>
              <tbody>
                {visiveis.map((item, idx) => (
                  <tr key={`${item.posicao}-${item.nome}-${idx}`} className="border-b border-zinc-100 last:border-0 dark:border-zinc-800/60">
                    <td className="px-4 py-2.5">{item.posicao}º</td>
                    <td className="px-4 py-2.5">
                      {item.aluno_id ? (
                        <Link to={`/alunos/${item.aluno_id}`} className="inline-flex items-center gap-1.5 font-medium hover:text-indigo-600 dark:hover:text-indigo-400">
                          <Calculator size={13} className="text-zinc-400" /> {item.nome}
                        </Link>
                      ) : (
                        <span className="inline-flex items-center gap-1.5 font-medium">
                          <Calculator size={13} className="text-zinc-400" /> {item.nome}
                        </span>
                      )}
                    </td>
                    <td className="hidden px-4 py-2.5 text-zinc-500 dark:text-zinc-400 md:table-cell">{item.turma ?? "—"}</td>
                    <td className="px-4 py-2.5 text-right font-semibold">⭐ {numero(item.estrelas)}</td>
                    <td className="px-4 py-2.5 text-right">{numero(item.atividades)}</td>
                    <td className="hidden px-4 py-2.5 text-right text-zinc-500 dark:text-zinc-400 sm:table-cell">{item.pontuacao_media.toFixed(2)}</td>
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
