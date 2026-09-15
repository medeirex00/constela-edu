/**
 * Ranking de Matemática — dois blocos:
 *  1. CLASSIFICAÇÃO OFICIAL (nota 0–100 do ano letivo, só alunos aferidos;
 *     `components/DesempenhoDimensao`) — respeita turma/série e o turno global;
 *  2. PLACAR MATIFIC (estrelas e atividades no período):
 *     • ANO LETIVO → lê o BANCO LOCAL (mantido pela sincronização diária).
 *       Rápido e não depende do Matific estar no ar. O turno vai na query.
 *     • Sub-períodos (Hoje, Ontem, Esta/Semana passada, Mês/Mês passado,
 *       Bimestre/Bimestre passado, Personalizado) → CONSULTA O MATIFIC AO VIVO
 *       (API interna por HTTP; navegador só para autenticar). Mostra os mesmos
 *       alunos, estrelas e atividades do site. Resultado tem cache curto;
 *       "Atualizar" força a busca. O turno é aplicado NO CLIENTE (nome da turma
 *       → turno, pelo cadastro de turmas); turma cujo NOME existe em mais de um
 *       turno fica fora do recorte, com aviso na tela.
 */
import { Calculator, Database, Radio, RefreshCw } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { DesempenhoDimensao, type FiltrosDimensao } from "../components/DesempenhoDimensao";
import { SeletorPeriodo, periodoParaQuery, type Periodo } from "../components/SeletorPeriodo";
import { SeletorTurno } from "../components/SeletorTurno";
import { Card, Carregando, PageHeader, Vazio, estiloInput } from "../components/ui";
import { useApp } from "../context/AppContext";
import { useApi } from "../hooks/useApi";
import { numero } from "../lib/formato";
import { TURNO_TODOS, chaveTurno, turnoEfetivo, turnoParaQuery } from "../lib/turnos";
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
  const { escolaId, periodo, definirPeriodo, turno, definirTurno } = useApp();
  // Alvo do filtro: "" (todas), "turma:<nome>" (uma turma) ou "serie:<ano_escolar>"
  // (série consolidada). O placar vem do Matific AO VIVO e é filtrado no cliente,
  // então guardamos o NOME da turma (não um id) — igual às linhas retornadas.
  const [alvo, setAlvo] = useState("");
  const [forcarTick, setForcarTick] = useState(0);

  // Turmas da BASE: mapeiam turma → série (o placar ao vivo traz a série crua
  // do Matific, ex. "3"; a base tem o rótulo bonito, ex. "3º Ano"), turma →
  // turno (filtro global no placar ao vivo) e turma → id (classificação oficial).
  const { dados: turmasBase } = useApi<Turma[]>(
    escolaId ? `/escolas/${escolaId}/turmas` : null, { cacheMs: 60_000 });
  const turnoAtivo = turnoEfetivo(turno, turmasBase);

  const isAno = periodo.preset === "ano_letivo";
  // Personalizado só busca com as duas datas — evita disparar login pela metade.
  const periodoCompleto =
    periodo.preset !== "personalizado" || Boolean(periodo.inicio && periodo.fim);

  const q = periodoParaQuery(periodo);
  // Trocar de período zera o "forçar" NA MESMA atualização (sem efeito atrasado
  // que dispararia uma busca forcada indevida do período novo).
  const trocarPeriodo = (p: Periodo) => {
    setForcarTick(0);
    definirPeriodo(p);   // período é global (segue o usuário entre as abas)
  };

  // ANO LETIVO: banco local (sincronização diária), turno na query. Sub-períodos:
  // Matific ao vivo (turno aplicado no cliente, abaixo).
  const forcarQS = forcarTick > 0 ? `&forcar=true&r=${forcarTick}` : "";
  const turnoQS = turnoParaQuery(turnoAtivo);
  const local = useApi<PlacarItem[]>(
    escolaId && isAno
      ? `/escolas/${escolaId}/ranking/matematica?periodo=ano_letivo${turnoQS ? `&${turnoQS}` : ""}`
      : null,
  );
  const live = useApi<PlacarAoVivo>(
    escolaId && !isAno && periodoCompleto
      ? `/escolas/${escolaId}/sync/matific/placar-ao-vivo?${q}${forcarQS}`
      : null,
    { timeoutMs: 180_000, tentativas: 0 },
  );

  const carregando = isAno ? local.carregando : live.carregando;
  const erro = isAno ? local.erro : live.erro;
  const atualizar = () => (isAno ? local.recarregar() : setForcarTick((t) => t + 1));

  // Nome da turma → série / turno / id (rótulos da base). Best-effort: turma sem
  // correspondência na base não entra em nenhuma série nem em nenhum turno
  // (segue visível em "Todas"/"Todos os turnos").
  const turmaDaBase = useMemo(() => {
    const mapa = new Map<string, Turma>();
    (turmasBase ?? []).forEach((t) => mapa.set(t.nome, t));
    return mapa;
  }, [turmasBase]);

  // Nome da turma → turnos em que esse NOME existe no cadastro. O placar ao
  // vivo só traz o nome: "3º Ano A" da manhã e "3º Ano A" da tarde chegam
  // iguais, então um nome em mais de um turno é AMBÍGUO para o filtro de turno.
  const turnosPorNome = useMemo(() => {
    const mapa = new Map<string, Set<string>>();
    (turmasBase ?? []).forEach((t) => {
      const turnos = mapa.get(t.nome) ?? new Set<string>();
      turnos.add(chaveTurno(t.turno));
      mapa.set(t.nome, turnos);
    });
    return mapa;
  }, [turmasBase]);

  // TURNO no placar AO VIVO: filtrado no cliente (o Matific não conhece turno).
  // No ano letivo o backend já filtrou pela query. Aluno de turma com nome
  // ambíguo fica FORA do recorte (não dá para saber o turno dele) e é contado
  // para a tela avisar, em vez de ser encaixado no turno errado.
  const { itens, foraPorNomeRepetido } = useMemo(() => {
    const brutos: PlacarItem[] = isAno ? (local.dados ?? []) : (live.dados?.itens ?? []);
    if (isAno || turnoAtivo === TURNO_TODOS) return { itens: brutos, foraPorNomeRepetido: 0 };
    let ambiguos = 0;
    const filtrados = brutos.filter((i) => {
      const turnos = i.turma ? turnosPorNome.get(i.turma) : undefined;
      if (turnos === undefined) return false;   // turma fora do cadastro: turno desconhecido
      if (turnos.size > 1) {
        ambiguos += 1;
        return false;
      }
      return turnos.has(turnoAtivo);
    });
    return { itens: filtrados, foraPorNomeRepetido: ambiguos };
  }, [isAno, local.dados, live.dados, turnoAtivo, turnosPorNome]);

  // Opções de TURMA vêm dos dados exibidos (como antes — casam sempre com as linhas).
  const turmas = useMemo(
    () => (Array.from(new Set(itens.map((i) => i.turma).filter(Boolean))) as string[]).sort(),
    [itens],
  );
  // Séries consolidadas presentes no placar (via mapa da base).
  const series = useMemo(
    () => Array.from(new Set(
      turmas.map((nome) => turmaDaBase.get(nome)?.ano_escolar).filter(Boolean) as string[],
    )).sort(),
    [turmas, turmaDaBase],
  );

  const visiveis = useMemo(() => {
    if (alvo.startsWith("turma:")) {
      const nome = alvo.slice(6);
      return itens.filter((i) => i.turma === nome);
    }
    if (alvo.startsWith("serie:")) {
      const serie = alvo.slice(6);
      return itens.filter((i) => turmaDaBase.get(i.turma ?? "")?.ano_escolar === serie);
    }
    return itens;
  }, [alvo, itens, turmaDaBase]);

  // A classificação oficial usa ids do cadastro: traduz o alvo (nome/série) do
  // placar. Uma turma do placar sem correspondência no cadastro não filtra a
  // classificação — e a tela avisa, em vez de fingir que filtrou.
  const filtrosOficial: FiltrosDimensao & { semCorrespondencia?: boolean } = useMemo(() => {
    if (alvo.startsWith("turma:")) {
      const t = turmaDaBase.get(alvo.slice(6));
      return t ? { turma_id: String(t.id), turno: turnoAtivo }
               : { turno: turnoAtivo, semCorrespondencia: true };
    }
    if (alvo.startsWith("serie:")) return { ano_escolar: alvo.slice(6), turno: turnoAtivo };
    return { turno: turnoAtivo };
  }, [alvo, turmaDaBase, turnoAtivo]);

  const atualizadoEm = !isAno && live.dados?.atualizado_em
    ? new Date(live.dados.atualizado_em).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" })
    : null;

  return (
    <div>
      {!embutido && (
        <PageHeader
          titulo="Placar Matific (estrelas e atividades no período)"
          descricao="Classificação oficial (nota 0–100) no topo. No placar, o ano letivo vem do banco local (sincronizado diariamente); qualquer outro período é consultado no Matific em tempo real — os mesmos alunos, estrelas e atividades do site."
        />
      )}

      {/* Filtros que valem para a classificação oficial E para o placar. */}
      <Card className="mb-4 flex flex-wrap items-center gap-3 p-4">
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
        <SeletorTurno turmas={turmasBase ?? []} valor={turno} onChange={definirTurno} />
      </Card>

      {/* 1. CLASSIFICAÇÃO OFICIAL: só aferidos, nota do ano, não aferidos ao lado. */}
      <div className="mb-6">
        {filtrosOficial.semCorrespondencia && (
          <p className="mb-2 text-xs text-amber-700 dark:text-amber-300">
            A turma escolhida não existe no cadastro de turmas; a classificação oficial mostra todas as turmas.
          </p>
        )}
        <DesempenhoDimensao dimensao="matematica" filtros={filtrosOficial} />
      </div>

      {/* 2. PLACAR MATIFIC no período (estrelas e atividades). */}
      <h2 className="mb-1 text-sm font-semibold text-zinc-700 dark:text-zinc-300">
        Estrelas e atividades no período
      </h2>
      <p className="mb-3 text-xs text-zinc-500 dark:text-zinc-400">
        Placar do Matific: estrelas, atividades e pontuação média só no período
        escolhido. Não é a classificação oficial acima.
      </p>

      <Card className="mb-4 flex flex-wrap items-center gap-3 p-4">
        <SeletorPeriodo valor={periodo} onChange={trocarPeriodo} />
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

      {!isAno && periodoCompleto && !carregando && foraPorNomeRepetido > 0 && (
        <p role="status" className="mb-2 text-xs text-amber-700 dark:text-amber-300">
          {numero(foraPorNomeRepetido)} aluno(s) de turmas com o mesmo nome em turnos diferentes
          não entram no filtro de turno do placar ao vivo.
        </p>
      )}

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
                 descricao="Ninguém pontuou no Matific nesse intervalo. Ajuste o período ou o turno." />
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
                    <td className="hidden px-4 py-2.5 text-right text-zinc-500 dark:text-zinc-400 sm:table-cell">{item.pontuacao_media.toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
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
