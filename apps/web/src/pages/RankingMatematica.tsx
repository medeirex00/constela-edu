/**
 * Ranking de Matemática (Matific) — "Premiar por período".
 *
 * Arquitetura:
 *  • ANO LETIVO → lê o BANCO LOCAL (mantido pela sincronização diária). Rápido e
 *    não depende do Matific estar no ar.
 *  • Sub-períodos (Hoje, Ontem, Esta/Semana passada, Mês/Mês passado, Bimestre/
 *    Bimestre passado, Personalizado) → CONSULTA O MATIFIC AO VIVO (API interna
 *    por HTTP; navegador só para autenticar). Mostra os mesmos alunos, estrelas e
 *    atividades do site. Resultado tem cache curto; "Atualizar" força a busca.
 */
import { Calculator, Database, Radio, RefreshCw } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { SeletorPeriodo, periodoParaQuery, type Periodo } from "../components/SeletorPeriodo";
import { Card, Carregando, PageHeader, Vazio, estiloInput } from "../components/ui";
import { useApp } from "../context/AppContext";
import { useApi } from "../hooks/useApi";
import { numero } from "../lib/formato";
import type { Turma } from "../lib/types";

type PlacarItem = {
  posicao: number;
  nome: string;
  turma: string | null;
  serie?: string | null;
  estrelas: number;
  atividades: number;
  pontuacao_media: number;
  aluno_id: number | null;
};
type PlacarAoVivo = {
  periodo: string;
  atualizado_em: string;
  total: number;
  itens: PlacarItem[];
};

export default function RankingMatematica({ embutido = false }: { embutido?: boolean } = {}) {
  const { escolaId } = useApp();
  const [periodo, setPeriodo] = useState<Periodo>({ preset: "mes" });
  // Alvo do filtro: "" (todas), "turma:<nome>" (uma turma) ou "serie:<ano_escolar>"
  // (série consolidada). O placar vem do Matific AO VIVO e é filtrado no cliente,
  // então guardamos o NOME da turma (não um id) — igual às linhas retornadas.
  const [alvo, setAlvo] = useState("");
  const [forcarTick, setForcarTick] = useState(0);

  // Turmas da BASE só para mapear turma → série (o placar ao vivo traz a série
  // crua do Matific, ex. "3"; a base tem o rótulo bonito, ex. "3º Ano").
  const { dados: turmasBase } = useApi<Turma[]>(
    escolaId ? `/escolas/${escolaId}/turmas` : null, { cacheMs: 60_000 });

  const isAno = periodo.preset === "ano_letivo";
  // Personalizado só busca com as duas datas — evita disparar login pela metade.
  const periodoCompleto =
    periodo.preset !== "personalizado" || Boolean(periodo.inicio && periodo.fim);

  const q = periodoParaQuery(periodo);
  // Trocar de período zera o "forçar" NA MESMA atualização (sem efeito atrasado
  // que dispararia uma busca forcada indevida do período novo).
  const trocarPeriodo = (p: Periodo) => {
    setForcarTick(0);
    setPeriodo(p);
  };

  // ANO LETIVO: banco local (sincronização diária). Sub-períodos: Matific ao vivo.
  const forcarQS = forcarTick > 0 ? `&forcar=true&r=${forcarTick}` : "";
  const local = useApi<PlacarItem[]>(
    escolaId && isAno ? `/escolas/${escolaId}/ranking/matematica?periodo=ano_letivo` : null,
  );
  const live = useApi<PlacarAoVivo>(
    escolaId && !isAno && periodoCompleto
      ? `/escolas/${escolaId}/sync/matific/placar-ao-vivo?${q}${forcarQS}`
      : null,
    { timeoutMs: 180_000, tentativas: 0 },
  );

  const carregando = isAno ? local.carregando : live.carregando;
  const erro = isAno ? local.erro : live.erro;
  const itens: PlacarItem[] = isAno ? (local.dados ?? []) : (live.dados?.itens ?? []);
  const atualizar = () => (isAno ? local.recarregar() : setForcarTick((t) => t + 1));

  // Nome da turma → série (rótulo da base). Best-effort: turma sem correspondência
  // na base simplesmente não entra em nenhuma série (segue visível em "Todas").
  const serieDaTurma = useMemo(() => {
    const mapa = new Map<string, string>();
    (turmasBase ?? []).forEach((t) => mapa.set(t.nome, t.ano_escolar));
    return mapa;
  }, [turmasBase]);

  // Opções de TURMA vêm dos dados ao vivo (como antes — casam sempre com as linhas).
  const turmas = useMemo(
    () => (Array.from(new Set(itens.map((i) => i.turma).filter(Boolean))) as string[]).sort(),
    [itens],
  );
  // Séries consolidadas presentes no placar (via mapa da base).
  const series = useMemo(
    () => Array.from(new Set(
      turmas.map((nome) => serieDaTurma.get(nome)).filter(Boolean) as string[],
    )).sort(),
    [turmas, serieDaTurma],
  );

  const visiveis = useMemo(() => {
    if (alvo.startsWith("turma:")) {
      const nome = alvo.slice(6);
      return itens.filter((i) => i.turma === nome);
    }
    if (alvo.startsWith("serie:")) {
      const serie = alvo.slice(6);
      return itens.filter((i) => serieDaTurma.get(i.turma ?? "") === serie);
    }
    return itens;
  }, [alvo, itens, serieDaTurma]);

  const atualizadoEm = !isAno && live.dados?.atualizado_em
    ? new Date(live.dados.atualizado_em).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" })
    : null;

  return (
    <div>
      {!embutido && (
        <PageHeader
          titulo="Premiar por período"
          descricao="Ano letivo vem do banco local (sincronizado diariamente). Qualquer outro período é consultado no Matific em tempo real — os mesmos alunos, estrelas e atividades do site."
        />
      )}

      <Card className="mb-4 flex flex-wrap items-center gap-3 p-4">
        <SeletorPeriodo valor={periodo} onChange={trocarPeriodo} />
        <select
          aria-label="Filtrar por turma ou série"
          className={`${estiloInput} w-auto`}
          value={alvo}
          onChange={(e) => setAlvo(e.target.value)}
        >
          <option value="">Todas as turmas</option>
          {series.length > 0 && (
            <optgroup label="Séries — consolidado">
              {series.map((s) => (
                <option key={`s-${s}`} value={`serie:${s}`}>{s} (todas as turmas)</option>
              ))}
            </optgroup>
          )}
          {turmas.length > 0 && (
            <optgroup label="Turmas">
              {turmas.map((t) => <option key={`t-${t}`} value={`turma:${t}`}>{t}</option>)}
            </optgroup>
          )}
        </select>
        <button
          type="button"
          onClick={atualizar}
          disabled={carregando || !periodoCompleto}
          className={`${estiloInput} inline-flex w-auto items-center gap-1.5 disabled:opacity-50`}
        >
          <RefreshCw size={14} className={carregando ? "animate-spin" : ""} /> Atualizar
        </button>
        {!carregando && isAno && (
          <span className="inline-flex items-center gap-1.5 text-xs text-zinc-500 dark:text-zinc-400">
            <Database size={13} /> Banco local · sincronização diária
          </span>
        )}
        {!carregando && !isAno && atualizadoEm && (
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
            {!isAno && (
              <>
                <p className="text-sm text-zinc-500 dark:text-zinc-400">
                  Consultando o Matific em tempo real…
                </p>
                <p className="max-w-md text-xs text-zinc-400">
                  Normalmente rápido. Se a sessão expirou, a primeira consulta pode levar
                  cerca de um minuto (o robô refaz o login no Matific).
                </p>
              </>
            )}
          </div>
        ) : erro ? (
          <Vazio titulo={isAno ? "Não foi possível carregar" : "Não foi possível consultar o Matific"}
                 descricao={erro.message} />
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
