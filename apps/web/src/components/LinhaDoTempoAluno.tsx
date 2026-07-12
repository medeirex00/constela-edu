/**
 * Linha do tempo cronológica do aluno — o "espelho" evento a evento.
 *
 * Mostra tudo o que o aluno fez em cada dia (uma leitura, uma atividade…), do
 * mais recente ao mais antigo, agrupado por dia, com resumo no topo. Consome os
 * eventos granulares (EventoAluno): hoje leitura do Elefante Letrado; preparado
 * para Matific e outros tipos quando disponíveis. Paginação por CURSOR
 * (keyset): "Carregar mais" busca a próxima página e anexa — aguenta milhares
 * de eventos por aluno sem travar.
 */
import {
  BookOpen,
  CalendarClock,
  CheckCircle2,
  Clock,
  Gamepad2,
  Layers,
  Medal,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { useApi } from "../hooks/useApi";
import { api } from "../lib/api";
import { numero } from "../lib/formato";
import {
  periodoParaQuery,
  SeletorPeriodo,
  type Periodo,
} from "./SeletorPeriodo";
import { Badge, Card, Carregando, StatCard, Vazio } from "./ui";

interface Evento {
  id: number;
  plataforma: string;
  tipo_evento: string;
  ocorrido_em: string;
  conteudo_titulo: string | null;
  habilidade: string | null;
  nivel_codigo: string | null;
  acertos: number | null;
  erros: number | null;
  tentativas: number | null;
  pontuacao: number | null;
  tempo_segundos: number | null;
  dados: Record<string, unknown>;
}

interface RespTimeline {
  itens: Evento[];
  proximo_cursor: string | null;
}

interface RespEspelho {
  espelho: {
    total_eventos: number;
    primeira_atividade: string | null;
    ultima_atividade: string | null;
    tempo_total_segundos: number;
    por_tipo: Record<string, number>;
    por_plataforma: Record<string, number>;
  };
}

const ROTULO_TIPO: Record<string, string> = {
  leitura: "Leitura",
  atividade: "Atividade",
  questao: "Questão",
  medalha: "Conquista",
};

const ROTULO_PLATAFORMA: Record<string, string> = {
  elefante: "Elefante Letrado",
  matific: "Matific",
};

/** Data ISO → partes locais (a hora guardada já é local, sem fuso). */
function partes(iso: string): { dia: string; diaLabel: string; hora: string | null } {
  const [d, t] = iso.split("T");
  const [ano, mes, dia] = d.split("-");
  return { dia: d, diaLabel: `${dia}/${mes}/${ano}`, hora: t ? t.slice(0, 5) : null };
}

/** Segundos → "1h 05min" / "8min" / "45s" (ou null). */
function tempo(seg: number | null): string | null {
  if (!seg || seg <= 0) return null;
  const h = Math.floor(seg / 3600);
  const m = Math.floor((seg % 3600) / 60);
  const s = seg % 60;
  if (h) return `${h}h ${String(m).padStart(2, "0")}min`;
  if (m) return `${m}min`;
  return `${s}s`;
}

function IconeTipo({ tipo }: { tipo: string }) {
  const props = { size: 15 };
  if (tipo === "leitura") return <BookOpen {...props} />;
  if (tipo === "atividade") return <Gamepad2 {...props} />;
  if (tipo === "questao") return <CheckCircle2 {...props} />;
  if (tipo === "medalha") return <Medal {...props} />;
  return <Layers {...props} />;
}

function Chip({ children }: { children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-md bg-zinc-100 px-1.5 py-0.5 text-xs tabular-nums text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">
      {children}
    </span>
  );
}

function EventoCard({ ev }: { ev: Evento }) {
  const { hora } = partes(ev.ocorrido_em);
  const t = tempo(ev.tempo_segundos);
  const genero = typeof ev.dados?.genero === "string" ? ev.dados.genero : null;
  return (
    <div className="flex gap-3 rounded-lg border border-zinc-200 bg-white p-3 dark:border-zinc-800 dark:bg-zinc-900/40">
      <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-indigo-50 text-indigo-600 dark:bg-indigo-500/15 dark:text-indigo-300">
        <IconeTipo tipo={ev.tipo_evento} />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span className="font-medium">
            {ev.conteudo_titulo || ROTULO_TIPO[ev.tipo_evento] || ev.tipo_evento}
          </span>
          <Badge>{ROTULO_PLATAFORMA[ev.plataforma] ?? ev.plataforma}</Badge>
          {ev.nivel_codigo && <Badge tom="destaque">Nível {ev.nivel_codigo}</Badge>}
        </div>
        <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
          {hora && (
            <Chip>
              <Clock size={11} /> {hora}
            </Chip>
          )}
          {t && <Chip>{t}</Chip>}
          {ev.acertos != null && <Chip>{numero(ev.acertos)} acertos</Chip>}
          {ev.erros != null && <Chip>{numero(ev.erros)} erros</Chip>}
          {ev.tentativas != null && <Chip>{numero(ev.tentativas)} tentativas</Chip>}
          {ev.pontuacao != null && <Chip>{numero(ev.pontuacao)} pts</Chip>}
          {ev.habilidade && <Chip>{ev.habilidade}</Chip>}
          {genero && <Chip>{genero}</Chip>}
        </div>
      </div>
    </div>
  );
}

export default function LinhaDoTempoAluno({ escolaId, alunoId }: {
  escolaId: number;
  alunoId: number | string;
}) {
  const [periodo, setPeriodo] = useState<Periodo>({ preset: "tudo" });
  const [itens, setItens] = useState<Evento[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [temMais, setTemMais] = useState(false);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState<string | null>(null);

  const q = periodoParaQuery(periodo);
  const { dados: resumo } = useApi<RespEspelho>(
    `/escolas/${escolaId}/alunos/${alunoId}/espelho`,
  );

  const carregar = useCallback(
    async (cur: string | null, reset: boolean) => {
      setCarregando(true);
      setErro(null);
      try {
        const params = new URLSearchParams(q);
        params.set("limite", "50");
        if (cur) params.set("cursor", cur);
        const r = await api<RespTimeline>(
          `/escolas/${escolaId}/alunos/${alunoId}/linha-do-tempo?${params.toString()}`,
        );
        setItens((prev) => (reset ? r.itens : [...prev, ...r.itens]));
        setCursor(r.proximo_cursor);
        setTemMais(Boolean(r.proximo_cursor));
      } catch (e) {
        setErro(e instanceof Error ? e.message : "Não foi possível carregar a linha do tempo.");
      } finally {
        setCarregando(false);
      }
    },
    [escolaId, alunoId, q],
  );

  // Recarrega do zero quando o período muda (q entra na dependência de carregar).
  useEffect(() => {
    carregar(null, true);
  }, [carregar]);

  const grupos = useMemo(() => {
    const mapa = new Map<string, { diaLabel: string; eventos: Evento[] }>();
    for (const ev of itens) {
      const { dia, diaLabel } = partes(ev.ocorrido_em);
      if (!mapa.has(dia)) mapa.set(dia, { diaLabel, eventos: [] });
      mapa.get(dia)!.eventos.push(ev);
    }
    return Array.from(mapa.values());
  }, [itens]);

  const esp = resumo?.espelho;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <SeletorPeriodo valor={periodo} onChange={setPeriodo} />
        {esp && (
          <span className="text-sm text-zinc-500 dark:text-zinc-400">
            {Object.entries(esp.por_plataforma)
              .map(([p, n]) => `${ROTULO_PLATAFORMA[p] ?? p}: ${numero(n)}`)
              .join(" · ") || "sem eventos"}
          </span>
        )}
      </div>

      {esp && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <StatCard icone={<Layers size={15} />} rotulo="Atividades registradas"
                    valor={numero(esp.total_eventos)} />
          <StatCard icone={<Clock size={15} />} rotulo="Tempo total"
                    valor={tempo(esp.tempo_total_segundos) ?? "—"} />
          <StatCard icone={<CalendarClock size={15} />} rotulo="Primeira atividade"
                    valor={esp.primeira_atividade ? partes(esp.primeira_atividade).diaLabel : "—"} />
        </div>
      )}

      <Card>
        {carregando && itens.length === 0 ? (
          <Carregando />
        ) : erro ? (
          <Vazio titulo="Não foi possível carregar" descricao={erro} />
        ) : itens.length === 0 ? (
          <Vazio
            titulo="Nenhuma atividade no período"
            descricao="Ajuste o período ou importe o relatório individual do Elefante Letrado — cada leitura vira um ponto na linha do tempo."
          />
        ) : (
          <div className="space-y-6 p-1">
            {grupos.map((g) => (
              <div key={g.diaLabel} className="relative">
                <div className="sticky top-0 z-[1] mb-2 flex items-center gap-2 bg-white/90 py-1 backdrop-blur dark:bg-zinc-900/80">
                  <CalendarClock size={14} className="text-zinc-400" />
                  <span className="text-sm font-semibold tabular-nums">{g.diaLabel}</span>
                  <span className="text-xs text-zinc-400">
                    {g.eventos.length} {g.eventos.length === 1 ? "atividade" : "atividades"}
                  </span>
                </div>
                <div className="space-y-2 border-l-2 border-zinc-100 pl-3 dark:border-zinc-800">
                  {g.eventos.map((ev) => (
                    <EventoCard key={ev.id} ev={ev} />
                  ))}
                </div>
              </div>
            ))}
            {temMais && (
              <div className="pt-1 text-center">
                <button
                  type="button"
                  onClick={() => carregar(cursor, false)}
                  disabled={carregando}
                  className="rounded-lg border border-zinc-200 px-4 py-2 text-sm font-medium text-zinc-700 transition-colors hover:bg-zinc-50 disabled:opacity-50 dark:border-zinc-700 dark:text-zinc-200 dark:hover:bg-zinc-800"
                >
                  {carregando ? "Carregando…" : "Carregar mais"}
                </button>
              </div>
            )}
          </div>
        )}
      </Card>
    </div>
  );
}
