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
import type { LucideIcon } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

import { useApi } from "../hooks/useApi";
import { api } from "../lib/api";
import { numero } from "../lib/formato";
import { EsqueletoLista } from "./PessoasUi";
import {
  periodoParaQuery,
  SeletorPeriodo,
  type Periodo,
} from "./SeletorPeriodo";
import { Badge, Botao, Card, Erro, IconePastel, Mensagem, StatCard, Vazio } from "./ui";
import type { TomPastel } from "./ui";

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

/** Cor do quadrado pastel por plataforma (Elefante violeta, Matific verde-azulado). */
const TOM_PLATAFORMA: Record<string, TomPastel> = {
  elefante: "violeta",
  matific: "teal",
};

const ICONE_TIPO: Record<string, LucideIcon> = {
  leitura: BookOpen,
  atividade: Gamepad2,
  questao: CheckCircle2,
  medalha: Medal,
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

function Etiqueta({ children }: { children: ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-lg bg-zinc-100 px-2 py-0.5 text-xs font-medium tabular-nums text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300">
      {children}
    </span>
  );
}

function EventoCard({ ev }: { ev: Evento }) {
  const { hora } = partes(ev.ocorrido_em);
  const t = tempo(ev.tempo_segundos);
  const genero = typeof ev.dados?.genero === "string" ? ev.dados.genero : null;
  return (
    <div className="flex gap-3 rounded-2xl border border-zinc-200/80 bg-white p-3.5 transition-colors hover:border-indigo-200 dark:border-zinc-800 dark:bg-zinc-900/40 dark:hover:border-indigo-500/30">
      <IconePastel
        icone={ICONE_TIPO[ev.tipo_evento] ?? Layers}
        tom={TOM_PLATAFORMA[ev.plataforma] ?? "neutro"}
      />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span className="font-semibold text-zinc-900 dark:text-zinc-100">
            {ev.conteudo_titulo || ROTULO_TIPO[ev.tipo_evento] || ev.tipo_evento}
          </span>
          <Badge>{ROTULO_PLATAFORMA[ev.plataforma] ?? ev.plataforma}</Badge>
          {ev.nivel_codigo && <Badge tom="destaque">Nível {ev.nivel_codigo}</Badge>}
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          {hora && (
            <Etiqueta>
              <Clock size={11} aria-hidden /> {hora}
            </Etiqueta>
          )}
          {t && <Etiqueta>{t}</Etiqueta>}
          {ev.acertos != null && <Etiqueta>{numero(ev.acertos)} acertos</Etiqueta>}
          {ev.erros != null && <Etiqueta>{numero(ev.erros)} erros</Etiqueta>}
          {ev.tentativas != null && <Etiqueta>{numero(ev.tentativas)} tentativas</Etiqueta>}
          {ev.pontuacao != null && <Etiqueta>{numero(ev.pontuacao)} pts</Etiqueta>}
          {ev.habilidade && <Etiqueta>{ev.habilidade}</Etiqueta>}
          {genero && <Etiqueta>{genero}</Etiqueta>}
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
        // Recomeço (troca de período) que falha não pode deixar a lista do período
        // ANTERIOR na tela como se fosse deste.
        if (reset) setItens([]);
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
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <SeletorPeriodo valor={periodo} onChange={setPeriodo} />
        {esp && (
          <span className="rounded-full bg-white px-3 py-1 text-sm font-medium text-zinc-600 shadow-cartao dark:bg-zinc-900 dark:text-zinc-300">
            {Object.entries(esp.por_plataforma)
              .map(([p, n]) => `${ROTULO_PLATAFORMA[p] ?? p}: ${numero(n)}`)
              .join(" · ") || "sem eventos"}
          </span>
        )}
      </div>

      {esp && (
        <div className="grid grid-cols-1 gap-5 sm:grid-cols-3">
          {/* O resumo é do histórico INTEIRO do aluno (não segue o período da lista). */}
          <StatCard icone={<Layers size={20} />} tom="violeta" rotulo="Atividades registradas"
                    valor={numero(esp.total_eventos)} detalhe="Desde o primeiro registro" />
          <StatCard icone={<Clock size={20} />} tom="azul" rotulo="Tempo total"
                    valor={tempo(esp.tempo_total_segundos) ?? "—"} detalhe="Desde o primeiro registro" />
          <StatCard icone={<CalendarClock size={20} />} tom="verde" rotulo="Primeira atividade"
                    valor={esp.primeira_atividade ? partes(esp.primeira_atividade).diaLabel : "—"} />
        </div>
      )}

      <Card className="p-5">
        {carregando && itens.length === 0 ? (
          <EsqueletoLista texto="Carregando a linha do tempo..." />
        ) : erro && itens.length === 0 ? (
          <Erro descricao={erro} aoTentar={() => carregar(null, true)} />
        ) : itens.length === 0 ? (
          <Vazio
            icone={CalendarClock}
            titulo="Nenhuma atividade no período"
            descricao="Ajuste o período ou importe o relatório individual do Elefante Letrado — cada leitura vira um ponto na linha do tempo."
          />
        ) : (
          <div className="space-y-6">
            {grupos.map((g) => (
              <div key={g.diaLabel} className="relative">
                <div className="sticky top-0 z-[1] mb-3 flex items-center gap-2 bg-white/90 py-1 backdrop-blur dark:bg-zinc-900/80">
                  <span aria-hidden className="h-2.5 w-2.5 rounded-full bg-indigo-600 ring-4 ring-indigo-100 dark:ring-indigo-500/20" />
                  <span className="text-sm font-bold tabular-nums text-zinc-900 dark:text-white">{g.diaLabel}</span>
                  <span className="text-xs text-zinc-500 dark:text-zinc-400">
                    {g.eventos.length} {g.eventos.length === 1 ? "atividade" : "atividades"}
                  </span>
                </div>
                <div className="ml-[5px] space-y-2.5 border-l-2 border-indigo-100 pl-4 dark:border-zinc-800">
                  {g.eventos.map((ev) => (
                    <EventoCard key={ev.id} ev={ev} />
                  ))}
                </div>
              </div>
            ))}
            {/* Falha ao carregar MAIS: a lista já carregada continua na tela. */}
            {erro && (
              <Mensagem tipo="erro">Não foi possível carregar mais atividades: {erro}</Mensagem>
            )}
            {temMais && (
              <div className="pt-1 text-center">
                <Botao
                  variante="secundario"
                  onClick={() => carregar(cursor, false)}
                  disabled={carregando}
                >
                  {carregando ? "Carregando…" : "Carregar mais"}
                </Botao>
              </div>
            )}
          </div>
        )}
      </Card>
    </div>
  );
}
