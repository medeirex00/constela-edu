/**
 * Painel Público (PRD §104–§128): acessível por URL sem login, pensado para
 * telão/TV da escola. Carrossel de slides configurável, atualização
 * automática dos dados e modo tela cheia.
 *
 * Visual: "noite Constela" — fundo azul profundo da marca (#0F1626→#1B2A4A)
 * com uma constelação sutil de estrelas (o próprio nome da marca), acento pela
 * cor primária da escola e ouro/prata/bronze celebrativos no pódio. Pensado
 * para leitura à distância numa TV: nomes/números grandes em Poppins.
 */
import {
  Calendar,
  Crown,
  Expand,
  Medal,
  Pause,
  Play,
  Sparkles,
  Star,
  TrendingUp,
  Trophy,
} from "lucide-react";
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { ReactNode, RefObject } from "react";
import type { LucideIcon } from "lucide-react";
import { useParams } from "react-router-dom";

import { useApi } from "../../hooks/useApi";
import { ApiError } from "../../lib/api";
import { nota } from "../../lib/formato";

interface ItemRanking {
  posicao: number;
  aluno_id: number;
  nome: string;
  turma: string | null;
  nota_geral?: number;
  nota_evolucao?: number;
}

interface Destaque {
  aluno_id: number;
  nome: string;
  turma: string | null;
  nota_evolucao: number;
  /** Ganhos reais do período (o que a criança avançou) — vêm do backend. */
  ganhos?: {
    atividades?: number;
    estrelas?: number;
    livros?: number;
    tempo_leitura_min?: number;
    acertos?: number;
  };
}

interface DadosPainel {
  escola: { nome: string; cor_primaria: string };
  slides: string[];
  intervalo_s: number;
  ranking: ItemRanking[];
  evolucao: ItemRanking[];
  destaques: { dia: Destaque | null; semana: Destaque | null; mes: Destaque | null };
  /** Agregados REAIS da escola (snapshots atuais) — faixa de indicadores. */
  estatisticas?: { alunos: number; atividades: number; estrelas: number; livros: number };
  mural: { icone: string; texto: string }[];
}

const TITULOS: Record<string, { titulo: string; icone: LucideIcon; legenda: string }> = {
  ranking: { titulo: "Ranking Geral", icone: Trophy, legenda: "Os destaques da escola" },
  evolucao: { titulo: "Quem mais cresceu", icone: TrendingUp, legenda: "Evolução dos últimos 30 dias" },
  destaques: { titulo: "Estrelas em Destaque", icone: Sparkles, legenda: "Do dia, da semana e do mês" },
  mural: { titulo: "Mural da Escola", icone: Star, legenda: "Novidades e conquistas" },
};

// Dica do dia: mensagens fixas de motivação (giram com o dia — nada é dado).
const DICAS = [
  "Cada pequena conquista é um passo para uma grande jornada!",
  "Capricho vale mais que pressa: acertar bem sobe mais que fazer correndo.",
  "Quem lê um pouquinho todo dia constrói um universo inteiro.",
  "Todo mundo pode ser a estrela do mês — continue brilhando!",
  "Errar faz parte: tentar de novo é o que faz a estrela crescer.",
  "Constância vence: um passo por dia leva mais longe que um salto por mês.",
];

// Pódio: cada posição/ período ganha uma cor de metal e um emoji de medalha.
const OURO = "#F5B942"; // âmbar-estrela da marca
const PRATA = "#CBD5E9";
const BRONZE = "#E0955A";
const MEDALHAS: Record<number, { emoji: string; cor: string }> = {
  1: { emoji: "🥇", cor: OURO },
  2: { emoji: "🥈", cor: PRATA },
  3: { emoji: "🥉", cor: BRONZE },
};

/**
 * Modo telão: quantas linhas cabem no palco SEM rolagem. Mede a 1ª linha real
 * (a altura varia com o clamp/viewport) e corta a lista no que couber — nada é
 * cortado no meio nem gera barra de rolagem. `reserva` guarda espaço para a
 * linha "+ N alunos" quando nem todos couberem.
 */
function useLinhasQueCabem(
  listaRef: RefObject<HTMLElement | null>,
  altura: number,
  total: number,
  gap: number,
  reserva: number,
) {
  const [visiveis, setVisiveis] = useState(total);
  useLayoutEffect(() => {
    const primeira = listaRef.current?.firstElementChild as HTMLElement | null;
    const alturaLinha = primeira?.offsetHeight ?? 0;
    if (altura <= 0 || alturaLinha <= 0) return;
    const cabem = Math.floor((altura + gap) / (alturaLinha + gap));
    // Se TODAS cabem, mostra todas; senão, corta reservando a linha "+ N".
    const cortadas = Math.floor((altura - reserva + gap) / (alturaLinha + gap));
    setVisiveis(cabem >= total ? total : Math.max(3, cortadas));
  }, [listaRef, altura, total, gap, reserva]);
  return Math.min(visiveis, total);
}

/** Céu estrelado determinístico (posições estáveis entre renders). */
function useEstrelas(qtd: number) {
  return useMemo(() => {
    let semente = 987654321;
    const rnd = () => (semente = (semente * 1103515245 + 12345) & 0x7fffffff) / 0x7fffffff;
    return Array.from({ length: qtd }, () => ({
      x: rnd() * 100,
      y: rnd() * 100,
      r: 0.5 + rnd() * 1.7,
      atraso: (rnd() * 4).toFixed(2),
    }));
  }, [qtd]);
}

/** Fundo: gradiente azul da marca + brilho na cor da escola + constelação. */
function FundoConstela({ cor }: { cor: string }) {
  const estrelas = useEstrelas(52);
  return (
    <div className="pointer-events-none absolute inset-0 overflow-hidden">
      <div
        className="absolute inset-0"
        style={{
          background:
            "radial-gradient(120% 80% at 50% -10%, #26365F 0%, #1B2A4A 42%, #0F1626 100%)",
        }}
      />
      {/* Dois halos suaves tingidos pela cor da escola — dão vida sem poluir. */}
      <div
        className="absolute -left-40 top-1/4 h-[46rem] w-[46rem] rounded-full opacity-30 blur-3xl"
        style={{ background: `radial-gradient(circle, ${cor}, transparent 60%)` }}
      />
      <div
        className="absolute -right-40 bottom-0 h-[42rem] w-[42rem] rounded-full opacity-20 blur-3xl"
        style={{ background: `radial-gradient(circle, ${OURO}, transparent 62%)` }}
      />
      <svg className="absolute inset-0 h-full w-full" preserveAspectRatio="none" viewBox="0 0 100 100">
        {estrelas.map((e, i) => (
          <circle
            key={i}
            cx={e.x}
            cy={e.y}
            r={e.r * 0.12}
            fill="#ffffff"
            className="painel-estrela"
            style={{ animationDelay: `${e.atraso}s` }}
          />
        ))}
      </svg>
    </div>
  );
}

/** Chip discreto de turma. */
function ChipTurma({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <span
      className={`inline-flex items-center rounded-full bg-white/10 px-3 py-1 text-sm font-medium text-white/80 ring-1 ring-inset ring-white/15 ${className}`}
    >
      {children}
    </span>
  );
}

/* ------------------------------------------------------------------ Destaques */

const inteiro = (v?: number) => Math.round(v ?? 0).toLocaleString("pt-BR");

/** Ganhos reais do período em micro-chips ("+91 atividades · +3 livros"). */
function MicroGanhos({ ganhos }: { ganhos?: Destaque["ganhos"] }) {
  if (!ganhos) return null;
  const partes = [
    ganhos.atividades ? `+${inteiro(ganhos.atividades)} atividades` : null,
    ganhos.estrelas ? `+${inteiro(ganhos.estrelas)} estrelas` : null,
    ganhos.livros ? `+${inteiro(ganhos.livros)} livros` : null,
  ].filter(Boolean) as string[];
  if (partes.length === 0) return null;
  return (
    <p className="mt-2 text-[clamp(0.7rem,1.2vw,0.95rem)] font-medium tabular-nums text-white/55">
      {partes.slice(0, 3).join(" · ")}
    </p>
  );
}

/** Iniciais do aluno (1º + último nome) — avatar sem foto, sem PII extra. */
function iniciaisDe(nome: string): string {
  const partes = nome.trim().split(/\s+/).filter(Boolean);
  if (partes.length === 0) return "★";
  const primeira = partes[0][0] ?? "";
  const ultima = partes.length > 1 ? partes[partes.length - 1][0] ?? "" : "";
  return (primeira + ultima).toUpperCase();
}

/** Avatar circular com iniciais + medalha numerada sobreposta (estilo pódio). */
function AvatarPodio({
  nome,
  cor,
  posicao,
  campeao,
}: {
  nome: string;
  cor: string;
  posicao: number;
  campeao: boolean;
}) {
  return (
    <div className={`painel-flutua relative ${campeao ? "h-28 w-28 sm:h-32 sm:w-32" : "h-20 w-20 sm:h-24 sm:w-24"}`}>
      <div
        className="flex h-full w-full items-center justify-center rounded-full ring-4"
        style={{
          background: `linear-gradient(140deg, ${cor}, ${cor}55 65%, #1B2A4A)`,
          boxShadow: `0 0 40px -6px ${cor}AA`,
          borderColor: cor,
          // ring-4 usa currentColor via CSS var do Tailwind; forçamos com boxShadow interno
          outline: `3px solid ${cor}`,
          outlineOffset: "-3px",
        }}
      >
        <span
          className={`font-extrabold text-white ${campeao ? "text-4xl sm:text-5xl" : "text-2xl sm:text-3xl"}`}
          style={{ fontFamily: "Poppins, Inter, sans-serif", textShadow: "0 2px 8px rgba(0,0,0,.35)" }}
        >
          {iniciaisDe(nome)}
        </span>
      </div>
      {/* Medalha numerada sobreposta, como nas premiações. */}
      <span
        className={`absolute -right-1 -top-1 flex items-center justify-center rounded-full font-extrabold text-[#1B2A4A] ring-2 ring-white/70 ${
          campeao ? "h-10 w-10 text-lg" : "h-8 w-8 text-sm"
        }`}
        style={{ background: `radial-gradient(circle at 35% 30%, #fff8, transparent 45%), ${cor}` }}
        aria-label={`${posicao}º lugar`}
      >
        {posicao}
      </span>
    </div>
  );
}

/** Coluna do pódio: cartão do aluno (SÓ exibição — sem link/clique) + base. */
function ColunaPodio({
  titulo,
  icone: Icone,
  cor,
  posicao,
  campeao = false,
  destaque,
}: {
  titulo: string;
  icone: LucideIcon;
  cor: string;
  posicao: number;
  campeao?: boolean;
  destaque: Destaque | null;
}) {
  return (
    <div className="flex h-full flex-col">
      <div
        className={`relative flex flex-1 flex-col items-center justify-start overflow-hidden text-center ring-1 ring-inset ${
          campeao
            ? "painel-brilho rounded-[2.25rem] px-6 pb-8 pt-9 ring-amber-300/40 sm:px-8 sm:pb-10 sm:pt-10"
            : "rounded-3xl bg-white/[0.06] px-5 pb-6 pt-7 ring-white/10"
        }`}
        style={
          campeao
            ? {
                background:
                  "linear-gradient(165deg, rgba(245,185,66,0.26), rgba(27,42,74,0.6) 62%, rgba(15,22,38,0.75))",
                boxShadow: `0 0 90px -14px ${OURO}88, inset 0 1px 0 0 rgba(255,255,255,0.12)`,
              }
            : {
                background: `linear-gradient(170deg, ${cor}14, rgba(255,255,255,0.05) 55%)`,
                boxShadow: "inset 0 1px 0 0 rgba(255,255,255,0.06)",
              }
        }
      >
        {!campeao && <span className="absolute inset-x-0 top-0 h-1.5" style={{ background: cor }} />}
        {/* Brilhos celebrativos (reusam a animação de cintilar; some em reduced-motion). */}
        {campeao && (
          <>
            <span className="painel-estrela absolute left-6 top-8 text-xl text-amber-200/80" aria-hidden>✦</span>
            <span className="painel-estrela absolute right-8 top-16 text-sm text-amber-100/70" style={{ animationDelay: "1.2s" }} aria-hidden>✦</span>
            <span className="painel-estrela absolute bottom-16 left-10 text-base text-amber-200/60" style={{ animationDelay: "2.1s" }} aria-hidden>✦</span>
            <span className="painel-estrela absolute bottom-24 right-6 text-lg text-white/50" style={{ animationDelay: "0.6s" }} aria-hidden>✦</span>
          </>
        )}
        {campeao && (
          <div className="mb-2 flex h-12 w-12 items-center justify-center">
            <Crown className="painel-flutua h-11 w-11 text-amber-300 drop-shadow-[0_0_14px_rgba(245,185,66,0.7)]" strokeWidth={2.1} />
          </div>
        )}
        {destaque ? (
          <AvatarPodio nome={destaque.nome} cor={cor} posicao={posicao} campeao={campeao} />
        ) : (
          <div
            className={`flex items-center justify-center rounded-full bg-white/5 ${campeao ? "h-28 w-28" : "h-20 w-20"}`}
          >
            <Icone className="h-8 w-8 text-white/25" />
          </div>
        )}
        <p
          className={`mt-3 font-semibold uppercase ${
            campeao ? "text-sm tracking-[0.28em] text-amber-200 sm:text-base" : "text-xs tracking-[0.22em] text-white/60"
          }`}
        >
          {titulo}
        </p>
        {destaque ? (
          <>
            {/* Nome protagonista: grande mas SEMPRE dentro do cartão (nomes longos
               quebram com equilíbrio — nada de letras cortadas na borda). */}
            <p
              className={`mt-2 w-full break-words px-1 font-extrabold leading-[1.12] text-white [text-wrap:balance] ${
                campeao ? "text-[clamp(1.45rem,2.5vw,2.6rem)]" : "text-[clamp(1.1rem,1.7vw,1.7rem)]"
              }`}
              style={{ fontFamily: "Poppins, Inter, sans-serif" }}
            >
              {destaque.nome}
            </p>
            <div className="mt-3 flex flex-wrap items-center justify-center gap-2 sm:gap-3">
              {destaque.turma && <ChipTurma>{destaque.turma}</ChipTurma>}
              <span
                className={`inline-flex items-center gap-1.5 rounded-full bg-emerald-400/15 px-3 py-1 font-bold tabular-nums text-emerald-300 ring-1 ring-inset ring-emerald-300/25 ${
                  campeao ? "text-lg" : "text-base"
                }`}
              >
                <TrendingUp className={campeao ? "h-5 w-5" : "h-4 w-4"} /> {nota(destaque.nota_evolucao)}
              </span>
            </div>
            <MicroGanhos ganhos={destaque.ganhos} />
          </>
        ) : (
          <p className="mt-5 text-white/45">Sem destaque no período.</p>
        )}
      </div>
      {/* Base do pódio: tablado com bisel, número e estrelinhas. */}
      <div
        className={`mx-2 flex items-center justify-center gap-3 rounded-b-3xl ${campeao ? "h-16" : "h-11"}`}
        style={{
          background: `linear-gradient(180deg, ${cor}66, ${cor}1e)`,
          boxShadow: `inset 0 3px 0 0 ${cor}AA, inset 0 -8px 16px -8px rgba(0,0,0,0.5)`,
        }}
      >
        <Star className="h-4 w-4 opacity-70" style={{ color: cor }} fill="currentColor" />
        <span
          className={`font-extrabold tabular-nums ${campeao ? "text-4xl" : "text-2xl"}`}
          style={{ color: cor, fontFamily: "Poppins, Inter, sans-serif", textShadow: `0 0 18px ${cor}88` }}
        >
          {posicao}
        </span>
        <Star className="h-4 w-4 opacity-70" style={{ color: cor }} fill="currentColor" />
      </div>
    </div>
  );
}

/** Pódio: Aluno do DIA no centro (campeão do agora!), Semana 2º, Mês 3º. */
function SlideDestaques({ destaques }: { destaques: DadosPainel["destaques"] }) {
  return (
    <div className="mx-auto w-full max-w-7xl">
      <div className="grid items-end gap-5 sm:gap-6 lg:grid-cols-3">
        <div className="order-2 lg:order-1">
          <ColunaPodio titulo="Aluno da Semana" icone={Medal} cor={PRATA} posicao={2}
                       destaque={destaques.semana} />
        </div>
        <div className="order-1 lg:order-2 lg:-translate-y-4">
          <ColunaPodio titulo="Aluno do Dia" icone={Crown} cor={OURO} posicao={1} campeao
                       destaque={destaques.dia} />
        </div>
        <div className="order-3">
          <ColunaPodio titulo="Aluno do Mês" icone={Star} cor={BRONZE} posicao={3}
                       destaque={destaques.mes} />
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------- Rankings */

function LinhaRanking({
  item,
  campo,
  larguraRelativa,
}: {
  item: ItemRanking;
  campo: "nota_geral" | "nota_evolucao";
  larguraRelativa: number;
}) {
  const medalha = MEDALHAS[item.posicao];
  const top3 = item.posicao <= 3;
  const valor = item[campo] ?? 0;
  // SÓ exibição: o painel público não abre dados individuais de aluno.
  return (
    <div
      className={`group relative flex items-center gap-3 overflow-hidden rounded-2xl px-4 py-3 ring-1 ring-inset sm:gap-4 sm:px-5 ${
        top3 ? "bg-white/[0.09] ring-white/15" : "bg-white/[0.04] ring-white/[0.07]"
      }`}
      style={top3 ? { boxShadow: `inset 4px 0 0 0 ${medalha?.cor ?? OURO}` } : undefined}
    >
      {/* Barra de progresso relativa ao 1º lugar (derivada dos dados exibidos). */}
      <span
        aria-hidden
        className="absolute inset-y-0 left-0 -z-10 rounded-2xl opacity-[0.10]"
        style={{ width: `${larguraRelativa}%`, background: medalha?.cor ?? "#6B7DE4" }}
      />
      <span className="flex w-10 shrink-0 items-center justify-center text-2xl sm:w-12">
        {medalha ? (
          <span aria-label={`${item.posicao}º lugar`}>{medalha.emoji}</span>
        ) : (
          <span className="font-bold tabular-nums text-white/45">{item.posicao}º</span>
        )}
      </span>
      <span
        className={`flex-1 truncate font-semibold text-white text-[clamp(1.05rem,2vw,1.6rem)] ${top3 ? "" : "text-white/90"}`}
        style={{ fontFamily: "Poppins, Inter, sans-serif" }}
      >
        {item.nome}
      </span>
      {item.turma && <ChipTurma className="hidden sm:inline-flex">{item.turma}</ChipTurma>}
      <span
        className="w-20 shrink-0 text-right font-bold tabular-nums text-white text-[clamp(1.1rem,2vw,1.75rem)] sm:w-28"
        style={top3 ? { color: medalha?.cor } : undefined}
      >
        {nota(valor)}
      </span>
    </div>
  );
}

function SlideRanking({
  itens,
  campo,
  altura,
}: {
  itens: ItemRanking[];
  campo: "nota_geral" | "nota_evolucao";
  /** Altura disponível do palco (px) — a lista corta no que couber. */
  altura: number;
}) {
  const listaRef = useRef<HTMLDivElement | null>(null);
  // gap-2.5 = 10px; reserva ~30px para a linha "+ N alunos".
  const visiveis = useLinhasQueCabem(listaRef, altura, itens.length, 10, 30);
  if (itens.length === 0) {
    return <p className="py-16 text-center text-xl text-white/40">Ainda sem dados para exibir.</p>;
  }
  // Topo = maior valor exibido (posição 1). Base para as barras relativas.
  const topo = Math.max(...itens.map((i) => i[campo] ?? 0), 0) || 1;
  const ocultos = itens.length - visiveis;
  return (
    <div ref={listaRef} className="mx-auto flex w-full max-w-3xl flex-col gap-2.5">
      {itens.slice(0, visiveis).map((item) => (
        <LinhaRanking
          key={item.aluno_id}
          item={item}
          campo={campo}
          larguraRelativa={Math.max(6, ((item[campo] ?? 0) / topo) * 100)}
        />
      ))}
      {ocultos > 0 && (
        <p className="text-center text-sm font-medium text-white/40">
          + {ocultos} {ocultos === 1 ? "aluno brilhando" : "alunos brilhando"} na jornada
        </p>
      )}
    </div>
  );
}

function SlideMural({ mural, altura }: { mural: DadosPainel["mural"]; altura: number }) {
  const listaRef = useRef<HTMLUListElement | null>(null);
  // gap-3 = 12px; reserva ~30px para a linha "+ N novidades".
  const visiveis = useLinhasQueCabem(listaRef, altura, mural.length, 12, 30);
  if (mural.length === 0) {
    return <p className="py-16 text-center text-xl text-white/40">Nada no mural ainda.</p>;
  }
  const ocultos = mural.length - visiveis;
  return (
    <ul ref={listaRef} className="mx-auto grid w-full max-w-3xl gap-3">
      {mural.slice(0, visiveis).map((evento, indice) => (
        <li
          key={indice}
          className="painel-surgir flex items-center gap-4 rounded-2xl bg-white/[0.06] px-5 py-4 text-lg text-white/90 ring-1 ring-inset ring-white/10"
          style={{ animationDelay: `${Math.min(indice, 8) * 0.06}s` }}
        >
          <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-white/10 text-2xl">
            {evento.icone}
          </span>
          <span className="text-[clamp(1rem,1.8vw,1.4rem)]">{evento.texto}</span>
        </li>
      ))}
      {ocultos > 0 && (
        <li className="list-none text-center text-sm font-medium text-white/40">
          + {ocultos} {ocultos === 1 ? "novidade" : "novidades"} no mural
        </li>
      )}
    </ul>
  );
}

/* --------------------------------------------------------------------- Painel */

export default function PainelPublico() {
  const { token = "" } = useParams();
  // Cliente compartilhado: usa a base configurada (VITE_API_URL) — um fetch
  // relativo funcionaria só em dev (proxy do Vite); na Vercel o rewrite do SPA
  // devolveria HTML no lugar do JSON e o painel quebrava.
  const { dados, erro, recarregar } = useApi<DadosPainel>(
    token ? `/publico/${token}/painel` : null,
  );
  const [slideAtivo, setSlideAtivo] = useState(0);
  const [pausado, setPausado] = useState(false);
  const [agora, setAgora] = useState(() => new Date());
  const [atualizadoEm, setAtualizadoEm] = useState<Date | null>(null);
  const [telaCheia, setTelaCheia] = useState(false);
  const [ocioso, setOcioso] = useState(false);
  const raiz = useRef<HTMLDivElement | null>(null);
  // Palco = área útil do slide. A altura medida aqui é o que decide quantas
  // linhas cada lista mostra (telão nunca rola nem corta pela metade).
  const palcoRef = useRef<HTMLDivElement | null>(null);
  const [alturaPalco, setAlturaPalco] = useState(0);

  useEffect(() => {
    const palco = palcoRef.current;
    if (!palco) return;
    const medir = () => setAlturaPalco(palco.clientHeight);
    medir();
    const observador = new ResizeObserver(medir);
    observador.observe(palco);
    return () => observador.disconnect();
  }, [dados]);

  const alternarTelaCheia = () => {
    // Fallback com prefixo webkit: Android (Samsung Internet / versões antigas) e
    // Safari expõem requestFullscreen/exitFullscreen só como webkit*. Sem isto, o
    // botão "não fazia nada" no celular. try/catch: se o navegador bloquear
    // (alguns mobile exigem gesto/são restritos), ignora sem quebrar o telão.
    const d = document as Document & {
      webkitFullscreenElement?: Element;
      webkitExitFullscreen?: () => void;
    };
    const el = raiz.current as (HTMLElement & { webkitRequestFullscreen?: () => void }) | null;
    try {
      if (d.fullscreenElement || d.webkitFullscreenElement) {
        (d.exitFullscreen ?? d.webkitExitFullscreen)?.call(d);
      } else if (el) {
        (el.requestFullscreen ?? el.webkitRequestFullscreen)?.call(el);
      }
    } catch {
      /* fullscreen indisponível neste navegador — segue em janela normal */
    }
  };

  useEffect(() => {
    // Modo TV: acompanha o estado real do fullscreen (inclusive tecla Esc e o
    // evento com prefixo webkit dos navegadores mobile).
    const d = document as Document & { webkitFullscreenElement?: Element };
    const aoMudar = () => setTelaCheia(Boolean(d.fullscreenElement || d.webkitFullscreenElement));
    document.addEventListener("fullscreenchange", aoMudar);
    document.addEventListener("webkitfullscreenchange", aoMudar);
    return () => {
      document.removeEventListener("fullscreenchange", aoMudar);
      document.removeEventListener("webkitfullscreenchange", aoMudar);
    };
  }, []);

  useEffect(() => {
    // Numa TV, controles e cursor somem após 5s parados — só o palco fica.
    let timer = 0;
    const acordar = () => {
      setOcioso(false);
      window.clearTimeout(timer);
      timer = window.setTimeout(() => setOcioso(true), 5_000);
    };
    acordar();
    window.addEventListener("mousemove", acordar);
    window.addEventListener("keydown", acordar);
    return () => {
      window.clearTimeout(timer);
      window.removeEventListener("mousemove", acordar);
      window.removeEventListener("keydown", acordar);
    };
  }, []);

  useEffect(() => {
    // Atalhos de telão: F = tela cheia, Espaço = pausar/retomar o carrossel.
    const aoTeclar = (evento: KeyboardEvent) => {
      if (evento.key === "f" || evento.key === "F") alternarTelaCheia();
      if (evento.key === " ") {
        evento.preventDefault();
        setPausado((atual) => !atual);
      }
    };
    window.addEventListener("keydown", aoTeclar);
    return () => window.removeEventListener("keydown", aoTeclar);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    // Wake Lock: a TV/tablet não pode dormir no meio da exposição. Reaquire ao
    // voltar a ficar visível (o navegador solta o lock quando a aba esconde).
    type WakeLockSentinel = { release?: () => Promise<void> };
    let trava: WakeLockSentinel | null = null;
    const pedir = async () => {
      try {
        trava = await (navigator as Navigator & {
          wakeLock?: { request: (t: "screen") => Promise<WakeLockSentinel> };
        }).wakeLock?.request("screen") ?? null;
      } catch {
        /* sem suporte/permitido — segue sem trava */
      }
    };
    void pedir();
    const rearmar = () => {
      if (document.visibilityState === "visible") void pedir();
    };
    document.addEventListener("visibilitychange", rearmar);
    return () => {
      document.removeEventListener("visibilitychange", rearmar);
      void trava?.release?.();
    };
  }, []);

  useEffect(() => {
    // Dados sempre frescos no telão: recarrega a cada 60s (o hook cuida do
    // cancelamento e do timeout de cada busca).
    const atualizador = window.setInterval(recarregar, 60_000);
    return () => window.clearInterval(atualizador);
  }, [recarregar]);

  useEffect(() => {
    // Relógio do cabeçalho (data/hora atual) — atualiza a cada 30s.
    const relogio = window.setInterval(() => setAgora(new Date()), 30_000);
    return () => window.clearInterval(relogio);
  }, []);

  useEffect(() => {
    // Marca quando o último quadro bom chegou (rodapé "atualizado às HH:MM").
    if (dados) setAtualizadoEm(new Date());
  }, [dados]);

  useEffect(() => {
    if (!dados || pausado || dados.slides.length <= 1) return;
    const timer = window.setInterval(
      () => setSlideAtivo((atual) => (atual + 1) % dados.slides.length),
      Math.max(4, dados.intervalo_s) * 1000,
    );
    return () => window.clearInterval(timer);
  }, [dados, pausado]);

  // O erro só derruba o telão quando NUNCA houve dados: token inválido/painel
  // desativado é 404. Uma falha transitória (rede caiu, servidor reiniciando)
  // NÃO apaga o último quadro bom — o ciclo de 60s recupera sozinho.
  if (erro && !dados) {
    // Transitório = mesma definição do useApi (rede/timeout/sobrecarga/5xx): o
    // cold-start numa rede lenta mostra "Reconectando", não "não encontrado".
    const transitorio =
      !(erro instanceof ApiError) ||
      erro.status === 0 || erro.status === 408 || erro.status === 429 ||
      erro.status >= 500;
    return (
      <div className="relative flex min-h-screen items-center justify-center bg-[#0F1626] text-white/70">
        <FundoConstela cor="#5B6EE1" />
        <p className="relative text-xl">
          {transitorio
            ? "Reconectando ao painel..."
            : "Painel não encontrado ou desativado."}
        </p>
      </div>
    );
  }
  if (!dados) {
    return (
      <div className="relative flex min-h-screen items-center justify-center bg-[#0F1626] text-white/60">
        <FundoConstela cor="#5B6EE1" />
        <p className="relative flex items-center gap-3 text-lg">
          <span className="h-5 w-5 animate-spin rounded-full border-2 border-white/20 border-t-white/80" />
          Carregando painel...
        </p>
      </div>
    );
  }

  const slide = dados.slides[slideAtivo % dados.slides.length];
  const meta = TITULOS[slide] ?? TITULOS.ranking;
  const cor = dados.escola.cor_primaria;
  const dataFmt = agora.toLocaleDateString("pt-BR", { weekday: "long", day: "2-digit", month: "long" });
  const horaFmt = agora.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });

  // Em fullscreen ocioso, controles/cursor somem — só o palco fica (modo TV).
  const modoTv = telaCheia && ocioso;

  return (
    <div
      ref={raiz}
      // Altura EXATA da tela (100dvh; h-screen é o fallback) + overflow-hidden:
      // o telão nunca tem barra de rolagem nem conteúdo cortado pela borda.
      className={`relative flex h-screen flex-col overflow-hidden bg-[#0F1626] text-white ${modoTv ? "cursor-none" : ""}`}
      style={{ height: "100dvh" }}
    >
      <FundoConstela cor={cor} />

      {/* ---------------------------------------------------------- Cabeçalho */}
      <header className="relative flex items-center justify-between gap-4 px-5 py-4 sm:px-8 sm:py-5">
        <div className="flex items-center gap-3 sm:gap-4">
          <img src="/simbolo-escuro.svg" alt="Constela Edu" width={44} height={44} className="h-9 w-9 sm:h-11 sm:w-11" />
          <div className="min-w-0">
            <p className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-[0.22em] text-amber-300 sm:text-sm">
              <Trophy className="h-3.5 w-3.5" /> Painel de Conquistas
            </p>
            <h1
              className="truncate font-extrabold leading-tight text-white text-[clamp(1.25rem,3vw,2.5rem)]"
              style={{ fontFamily: "Poppins, Inter, sans-serif" }}
            >
              {dados.escola.nome}
            </h1>
          </div>
        </div>
        <div className="flex items-center gap-3 sm:gap-4">
          <div className="hidden text-right sm:block">
            <p className="flex items-center justify-end gap-1.5 text-sm font-medium capitalize text-white/80">
              <Calendar className="h-4 w-4 text-white/50" /> {dataFmt}
            </p>
            <p className="text-lg font-bold tabular-nums text-white/95">{horaFmt}</p>
          </div>
          <div
            className={`flex items-center gap-2 transition-opacity duration-500 ${modoTv ? "pointer-events-none opacity-0" : "opacity-100"}`}
          >
            <button
              aria-label={pausado ? "Retomar carrossel (Espaço)" : "Pausar carrossel (Espaço)"}
              title={pausado ? "Retomar (Espaço)" : "Pausar (Espaço)"}
              className="rounded-xl bg-white/10 p-2.5 text-white/80 ring-1 ring-inset ring-white/15 transition-colors hover:bg-white/20"
              onClick={() => setPausado((atual) => !atual)}
            >
              {pausado ? <Play size={18} /> : <Pause size={18} />}
            </button>
            <button
              aria-label="Modo TV — tela cheia (F)"
              title="Modo TV (F)"
              className="rounded-xl bg-white/10 p-2.5 text-white/80 ring-1 ring-inset ring-white/15 transition-colors hover:bg-white/20"
              onClick={alternarTelaCheia}
            >
              <Expand size={18} />
            </button>
          </div>
        </div>
      </header>

      {/* Filete com a cor da escola separando cabeçalho do palco. */}
      <div className="relative mx-5 h-px sm:mx-8" style={{ background: `linear-gradient(90deg, ${cor}, transparent 80%)` }} />

      {/* -------------------------------------------------------------- Palco */}
      <main className="relative flex min-h-0 flex-1 flex-col px-4 pb-2 pt-4 sm:px-8 sm:pt-5">
        <div key={slide} className="painel-surgir flex min-h-0 w-full flex-1 flex-col">
          {/* Título sempre visível (fora da área rolável — nunca é cortado). */}
          <div className="mb-3 shrink-0 text-center sm:mb-4">
            <h2
              className="flex items-center justify-center gap-3 font-extrabold text-white text-[clamp(1.5rem,3vw,2.6rem)]"
              style={{ fontFamily: "Poppins, Inter, sans-serif" }}
            >
              <meta.icone className="h-7 w-7 shrink-0 sm:h-9 sm:w-9" style={{ color: OURO }} strokeWidth={2.3} />
              {meta.titulo}
            </h2>
            <p className="mt-1 text-sm text-white/50 sm:text-base">{meta.legenda}</p>
          </div>

          {/* Palco medido: as listas mostram só o que cabe (sem barra, sem corte).
             A rolagem invisível fica de reserva para telas pequenas (celular). */}
          <div ref={palcoRef} className="painel-sem-barra flex min-h-0 flex-1 flex-col overflow-y-auto">
            <div className="my-auto w-full py-1">
              {slide === "ranking" && (
                <SlideRanking itens={dados.ranking} campo="nota_geral" altura={alturaPalco} />
              )}
              {slide === "evolucao" && (
                <SlideRanking itens={dados.evolucao} campo="nota_evolucao" altura={alturaPalco} />
              )}
              {slide === "destaques" && <SlideDestaques destaques={dados.destaques} />}
              {slide === "mural" && <SlideMural mural={dados.mural} altura={alturaPalco} />}
            </div>
          </div>
        </div>
      </main>

      {/* --------------------------------------- Indicadores REAIS da escola */}
      {dados.estatisticas && (
        <section
          aria-label="Números da escola"
          className="relative mx-4 mb-1 grid grid-cols-2 gap-2 rounded-2xl bg-white/[0.05] px-3 py-2.5 ring-1 ring-inset ring-white/10 sm:mx-8 sm:grid-cols-4 sm:gap-3 sm:px-5"
        >
          {[
            { emoji: "👥", rotulo: "Alunos", valor: dados.estatisticas.alunos },
            { emoji: "🎯", rotulo: "Atividades", valor: dados.estatisticas.atividades },
            { emoji: "⭐", rotulo: "Estrelas", valor: dados.estatisticas.estrelas },
            { emoji: "📚", rotulo: "Livros lidos", valor: dados.estatisticas.livros },
          ].map((e) => (
            <div key={e.rotulo} className="flex items-center justify-center gap-2.5">
              <span className="text-xl sm:text-2xl" aria-hidden>{e.emoji}</span>
              <div className="text-left leading-tight">
                <p
                  className="font-extrabold tabular-nums text-white text-[clamp(1.1rem,2.2vw,1.8rem)]"
                  style={{ fontFamily: "Poppins, Inter, sans-serif" }}
                >
                  {e.valor.toLocaleString("pt-BR")}
                </p>
                <p className="text-[clamp(0.6rem,1vw,0.8rem)] font-semibold uppercase tracking-wider text-white/50">
                  {e.rotulo}
                </p>
              </div>
            </div>
          ))}
        </section>
      )}

      {/* Dica do dia: motivação discreta, gira com o dia do ano. */}
      <p className="relative px-6 pb-1 text-center text-[clamp(0.75rem,1.3vw,1rem)] text-white/45">
        <Sparkles className="mr-1.5 inline h-3.5 w-3.5 text-amber-300/80" aria-hidden />
        {DICAS[Math.floor((agora.getTime() / 86_400_000)) % DICAS.length]}
      </p>

      {/* ------------------------------------------------------------- Rodapé */}
      <footer
        className={`relative flex flex-col items-center gap-3 px-5 py-4 transition-opacity duration-500 sm:flex-row sm:justify-between sm:px-8 ${
          modoTv ? "opacity-30" : "opacity-100"
        }`}
      >
        <div className="flex items-center gap-2 text-sm font-medium text-white/50">
          <img src="/simbolo-escuro.svg" alt="" aria-hidden width={18} height={18} className="h-4 w-4 opacity-70" />
          <span style={{ fontFamily: "Poppins, Inter, sans-serif" }}>
            constela<span className="text-amber-300">edu</span>
          </span>
        </div>

        {dados.slides.length > 1 && (
          <div className="flex items-center gap-2">
            {dados.slides.map((nomeSlide, indice) => (
              <button
                key={nomeSlide}
                aria-label={`Ir para ${TITULOS[nomeSlide]?.titulo ?? nomeSlide}`}
                className={`h-2.5 rounded-full transition-all ${
                  indice === slideAtivo % dados.slides.length ? "w-8 bg-amber-300" : "w-2.5 bg-white/25 hover:bg-white/40"
                }`}
                onClick={() => setSlideAtivo(indice)}
              />
            ))}
          </div>
        )}

        <div className="flex items-center gap-2 text-xs text-white/40">
          <span className="painel-pulso h-2 w-2 rounded-full bg-emerald-400" />
          Atualização automática
          {atualizadoEm && (
            <span className="hidden tabular-nums sm:inline">
              · {atualizadoEm.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}
            </span>
          )}
        </div>
      </footer>
    </div>
  );
}
