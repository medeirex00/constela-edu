/**
 * Painel Público (PRD §104–§128): acessível por URL sem login, pensado para
 * telão/TV da escola. Carrossel de slides configurável, atualização
 * automática dos dados e modo tela cheia. No celular (famílias pelo QR) vira
 * página rolável — ver `useModoCelular`.
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
import { useEffect, useLayoutEffect, useRef, useState, useSyncExternalStore } from "react";
import type { ReactNode, RefObject } from "react";
import type { LucideIcon } from "lucide-react";
import { useParams } from "react-router-dom";

import {
  BRONZE, FundoConstela, MEDALHAS, OURO, PRATA, useTelaPublica,
} from "../../components/FundoConstela";
import { useApi } from "../../hooks/useApi";
import { useSemIndexacao } from "../../hooks/useSemIndexacao";
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
  /** Agregados REAIS da escola (snapshots atuais) — faixa de indicadores. `null` =
   *  sem dado (plataforma sem coleta): a faixa mostra "—", nunca um 0 inventado. */
  estatisticas?: { alunos: number | null; atividades: number | null; estrelas: number | null; livros: number | null };
  mural: { icone: string; texto: string }[];
}

/** Valor ausente (null/undefined/NaN) vira "—" + "sem dado" para o leitor de tela:
 *  no telão público, ausência não pode virar 0 (nem quebrar a tela no `nota()`). */
function ValorOuAusencia({ valor, formatar }: { valor: number | null | undefined; formatar: (v: number) => string }) {
  if (typeof valor !== "number" || !Number.isFinite(valor)) {
    return <><span aria-hidden>—</span><span className="sr-only">sem dado</span></>;
  }
  return <>{formatar(valor)}</>;
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

// Pódio: cada posição/período ganha uma cor de metal e um emoji de medalha
// (OURO/PRATA/BRONZE/MEDALHAS vêm do fundo compartilhado com a vitrine).

/**
 * Modo TV × modo celular. O telão foi desenhado para TV: altura EXATA da tela,
 * sem rolagem, palco medido. No celular (as famílias abrem pelo QR) isso
 * espremia o palco a 1,5 linha e truncava o nome da escola. Então, abaixo de
 * 640 px de largura OU com menos de 500 px de altura (celular deitado:
 * 667×375, 844×390, 932×430), o telão vira uma PÁGINA ROLÁVEL comum: raiz sem
 * altura fixa, palco sem medição (todas as posições aparecem), nome da escola
 * inteiro numa linha própria e pódio empilhado. A condição de TV é esta
 * abaixo; o celular é o complemento EXATO dela (`not all and …`, sem a fresta
 * de 639,98 px). Os blocos do "modo compacto por altura" do index.css repetem
 * `(min-width: 640px) and (min-height: 500px)` para valer só na TV.
 */
const MEDIA_TELAO_TV = "(min-width: 640px) and (min-height: 500px)";
const MEDIA_TELAO_CELULAR = `not all and ${MEDIA_TELAO_TV}`;

function assinarModoCelular(avisar: () => void): () => void {
  const consulta = window.matchMedia?.(MEDIA_TELAO_CELULAR);
  if (!consulta) return () => undefined;
  if (consulta.addEventListener) {
    consulta.addEventListener("change", avisar);
    return () => consulta.removeEventListener("change", avisar);
  }
  // Safari < 14 (celulares antigos das famílias) só tem addListener.
  consulta.addListener(avisar);
  return () => consulta.removeListener(avisar);
}

/** true no celular (página rolável); acompanha girar o aparelho. */
function useModoCelular(): boolean {
  return useSyncExternalStore(
    assinarModoCelular,
    () => window.matchMedia?.(MEDIA_TELAO_CELULAR).matches ?? false,
    () => false,
  );
}

/**
 * Modo telão: quantas linhas cabem no palco SEM rolagem. Mede a 1ª linha real
 * (a altura varia com o clamp/viewport) e corta a lista no que couber — nada é
 * cortado no meio nem gera barra de rolagem. `reserva` guarda espaço para a
 * linha "+ N alunos" quando nem todos couberem. `altura` null = página rolável
 * do celular: sem medição, a lista inteira aparece.
 */
function useLinhasQueCabem(
  listaRef: RefObject<HTMLElement | null>,
  altura: number | null,
  total: number,
  gap: number,
  reserva: number,
) {
  const [visiveis, setVisiveis] = useState(total);
  useLayoutEffect(() => {
    if (altura === null) return;
    const primeira = listaRef.current?.firstElementChild as HTMLElement | null;
    const alturaLinha = primeira?.offsetHeight ?? 0;
    if (altura <= 0 || alturaLinha <= 0) return;
    // `gap`/`reserva` são px a 16px de rem: na TV 4K (.tela-publica) o rem cresce
    // e o vão (gap-2.5/gap-3) e a linha "+ N" crescem junto — escala a conta.
    const escala = parseFloat(getComputedStyle(document.documentElement).fontSize) / 16 || 1;
    const vao = gap * escala;
    const cabem = Math.floor((altura + vao) / (alturaLinha + vao));
    // Se TODAS cabem, mostra todas; senão, corta reservando a linha "+ N".
    const cortadas = Math.floor((altura - reserva * escala + vao) / (alturaLinha + vao));
    setVisiveis(cabem >= total ? total : Math.max(3, cortadas));
  }, [listaRef, altura, total, gap, reserva]);
  return altura === null ? total : Math.min(visiveis, total);
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
    <p className="painel-podio-ganhos mt-2 text-[clamp(0.7rem,1.2vw,0.95rem)] font-medium tabular-nums text-white/70">
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
    <div className={`painel-flutua relative ${campeao ? "painel-podio-avatar-campeao h-28 w-28 sm:h-32 sm:w-32 xl:h-44 xl:w-44" : "painel-podio-avatar h-20 w-20 sm:h-24 sm:w-24 xl:h-32 xl:w-32"}`}>
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
        {/* Iniciais = desenho do avatar: o nome inteiro vem logo abaixo (o leitor de
            tela lia "BC" antes de "Bruno C."). Halo escuro mais firme: no lado claro
            do degradê prata/ouro o branco ficava a ~2,8:1. */}
        <span
          aria-hidden
          className={`font-extrabold text-white ${campeao ? "painel-podio-iniciais-campeao text-4xl sm:text-5xl xl:text-7xl" : "painel-podio-iniciais text-2xl sm:text-3xl xl:text-5xl"}`}
          style={{ fontFamily: "Poppins, Inter, sans-serif",
            textShadow: "0 1px 2px rgba(15,22,38,.85), 0 0 10px rgba(15,22,38,.7)" }}
        >
          {iniciaisDe(nome)}
        </span>
      </div>
      {/* Medalha numerada sobreposta, como nas premiações. O "Nº lugar" vai em
          texto oculto: aria-label num <span> sem papel é ignorado pelos leitores. */}
      <span
        className={`absolute -right-1 -top-1 flex items-center justify-center rounded-full font-extrabold text-[#1B2A4A] ring-2 ring-white/70 ${
          campeao ? "painel-podio-medalha-campeao h-10 w-10 text-lg" : "painel-podio-medalha h-8 w-8 text-sm"
        }`}
        style={{ background: `radial-gradient(circle at 35% 30%, #fff8, transparent 45%), ${cor}` }}
      >
        <span aria-hidden>{posicao}</span>
        <span className="sr-only">{posicao}º lugar</span>
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
            ? "painel-brilho painel-podio-cartao-campeao rounded-[2.25rem] px-6 pb-8 pt-9 ring-white/10 sm:px-8 sm:pb-10 sm:pt-10"
            : "painel-podio-cartao rounded-3xl bg-white/[0.06] px-5 pb-6 pt-7 ring-white/10"
        }`}
        style={
          campeao
            ? {
                // Faixa dourada do topo mais TRANSPARENTE (0.26→0.12) e o corpo
                // menos opaco, para as estrelas do fundo aparecerem através do
                // cartão do campeão — sem perder o destaque (a sombra dourada fica).
                background:
                  "linear-gradient(165deg, rgba(245,185,66,0.12), rgba(27,42,74,0.34) 60%, rgba(15,22,38,0.5))",
                // Só o brilho dourado difuso (sem linha branca no topo nem aro
                // âmbar): elimina a "borda que acaba do nada" no cartão translúcido.
                boxShadow: `0 0 90px -14px ${OURO}88`,
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
          <div className="painel-podio-coroa mb-2 flex h-12 w-12 items-center justify-center">
            <Crown className="painel-flutua h-11 w-11 text-amber-300 drop-shadow-[0_0_14px_rgba(245,185,66,0.7)]" strokeWidth={2.1} />
          </div>
        )}
        {destaque ? (
          <AvatarPodio nome={destaque.nome} cor={cor} posicao={posicao} campeao={campeao} />
        ) : (
          <div
            className={`flex items-center justify-center rounded-full bg-white/5 ${campeao ? "painel-podio-avatar-campeao h-28 w-28 sm:h-32 sm:w-32 xl:h-44 xl:w-44" : "painel-podio-avatar h-20 w-20 sm:h-24 sm:w-24 xl:h-32 xl:w-32"}`}
          >
            <Icone className="h-8 w-8 text-white/25" />
          </div>
        )}
        <p
          className={`painel-podio-rotulo mt-3 font-semibold uppercase ${
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
                campeao ? "painel-podio-nome-campeao text-[clamp(1.45rem,2.5vw,3.8rem)]" : "painel-podio-nome text-[clamp(1.1rem,1.7vw,2.6rem)]"
              }`}
              style={{ fontFamily: "Poppins, Inter, sans-serif" }}
            >
              {destaque.nome}
            </p>
            <div className="painel-podio-chips mt-3 flex flex-wrap items-center justify-center gap-2 sm:gap-3">
              {destaque.turma && <ChipTurma>{destaque.turma}</ChipTurma>}
              <span
                className={`inline-flex items-center gap-1.5 rounded-full bg-emerald-400/15 px-3 py-1 font-bold tabular-nums text-emerald-300 ring-1 ring-inset ring-emerald-300/25 ${
                  campeao ? "text-lg" : "text-base"
                }`}
              >
                <TrendingUp aria-hidden className={campeao ? "h-5 w-5" : "h-4 w-4"} />{" "}
                <ValorOuAusencia valor={destaque.nota_evolucao} formatar={nota} />
              </span>
            </div>
            <MicroGanhos ganhos={destaque.ganhos} />
          </>
        ) : (
          <p className="mt-5 text-white/70">Sem destaque no período.</p>
        )}
      </div>
      {/* Base do pódio: tablado com bisel, número e estrelinhas. */}
      <div
        className={`mx-2 flex items-center justify-center gap-3 rounded-b-3xl ${campeao ? "painel-podio-base-campeao h-16" : "painel-podio-base h-11"}`}
        style={{
          background: `linear-gradient(180deg, ${cor}66, ${cor}1e)`,
          boxShadow: `inset 0 3px 0 0 ${cor}AA, inset 0 -8px 16px -8px rgba(0,0,0,0.5)`,
        }}
      >
        <Star className="h-4 w-4 opacity-70" style={{ color: cor }} fill="currentColor" />
        <span
          className={`font-extrabold tabular-nums ${campeao ? "painel-podio-base-num-campeao text-4xl" : "painel-podio-base-num text-2xl"}`}
          style={{ color: cor, fontFamily: "Poppins, Inter, sans-serif", textShadow: `0 0 18px ${cor}88` }}
        >
          {posicao}
        </span>
        <Star className="h-4 w-4 opacity-70" style={{ color: cor }} fill="currentColor" />
      </div>
    </div>
  );
}

/** Pódio: Aluno do DIA no centro (campeão do agora!), Semana 2º, Mês 3º.
 *  `empilhado` (celular): uma coluna em qualquer largura — Dia, Semana, Mês. */
function SlideDestaques({
  destaques,
  empilhado = false,
}: {
  destaques: DadosPainel["destaques"];
  empilhado?: boolean;
}) {
  return (
    <div className="mx-auto w-full max-w-[min(88rem,92vw)]">
      <div className={`painel-podio-grade grid items-end gap-5 sm:gap-6${empilhado ? "" : " lg:grid-cols-3"}`}>
        <div className={`painel-podio-col-2 order-2${empilhado ? "" : " lg:order-1"}`}>
          <ColunaPodio titulo="Aluno da Semana" icone={Medal} cor={PRATA} posicao={2}
                       destaque={destaques.semana} />
        </div>
        <div className={`painel-podio-col-1 order-1${empilhado ? "" : " lg:order-2 lg:-translate-y-4"}`}>
          <ColunaPodio titulo="Aluno do Dia" icone={Crown} cor={OURO} posicao={1} campeao
                       destaque={destaques.dia} />
        </div>
        <div className="painel-podio-col-3 order-3">
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
  celular,
}: {
  item: ItemRanking;
  campo: "nota_geral" | "nota_evolucao";
  /** null = sem valor: nenhuma barra (ausência não é "pouco"). */
  larguraRelativa: number | null;
  celular: boolean;
}) {
  const medalha = MEDALHAS[item.posicao];
  const top3 = item.posicao <= 3;
  // Sem `?? 0`: um valor ausente aparece como ausência ("—"), nunca como zero.
  const valor = item[campo];
  // SÓ exibição: o painel público não abre dados individuais de aluno.
  return (
    // `isolate`: a barra relativa (-z-10) é pintada DENTRO da linha, por cima do
    // fundo dela. Sem isso ela só aparecia enquanto o painel-surgir deixava um
    // transform aplicado; em "reduzir movimento" ia para trás do fundo e sumia.
    <div
      className={`group relative isolate flex items-center gap-3 overflow-hidden rounded-2xl px-4 py-3 ring-1 ring-inset sm:gap-4 sm:px-5 ${
        top3 ? "bg-white/[0.09] ring-white/15" : "bg-white/[0.04] ring-white/[0.07]"
      }`}
      style={top3 ? { boxShadow: `inset 4px 0 0 0 ${medalha?.cor ?? OURO}` } : undefined}
    >
      {/* Barra de progresso relativa ao 1º lugar (derivada dos dados exibidos). */}
      <span
        aria-hidden
        data-barra
        className="absolute inset-y-0 left-0 -z-10 rounded-2xl opacity-[0.10]"
        style={{ width: `${larguraRelativa ?? 0}%`, background: medalha?.cor ?? "#6B7DE4" }}
      />
      {/* Posição: emoji + "Nº lugar" em texto oculto (aria-label num <span> sem
          papel não é lido); fora do pódio, o número (white/70: contraste AA). */}
      <span className="flex w-10 shrink-0 items-center justify-center text-[clamp(1.4rem,2vw,2.4rem)] sm:w-12 xl:w-16">
        {medalha ? (
          <>
            <span aria-hidden>{medalha.emoji}</span>
            <span className="sr-only">{item.posicao}º lugar</span>
          </>
        ) : (
          <span className="font-bold tabular-nums text-white/70">
            {item.posicao}º<span className="sr-only"> lugar</span>
          </span>
        )}
      </span>
      {/* TV: uma linha (o palco é medido por linha; o nome inteiro fica no title).
          Celular: a página rola, então o nome INTEIRO quebra linha — com o nome
          completo ligado pela escola, o truncate cortava "Maria Eduarda dos…". */}
      <span
        className={`min-w-0 flex-1 font-semibold text-white text-[clamp(1.05rem,2vw,2.4rem)] ${
          celular ? "break-words [overflow-wrap:anywhere]" : "truncate"} ${top3 ? "" : "text-white/90"}`}
        style={{ fontFamily: "Poppins, Inter, sans-serif" }}
        title={item.nome}
        data-nome-aluno
      >
        {item.nome}
      </span>
      {item.turma && <ChipTurma className="hidden sm:inline-flex">{item.turma}</ChipTurma>}
      {/* Valor: coluna fixa na TV (alinha os números); no celular só a largura do
          número — a 320 px a coluna de 80 px deixava ~100 px para o nome, que
          quebrava no meio da palavra ("Albuquerqu-e"). */}
      <span
        className={`shrink-0 text-right font-bold tabular-nums text-white text-[clamp(1.2rem,2vw,2.6rem)] ${
          celular ? "min-w-[3.5rem]" : "w-20 sm:w-28 xl:w-36"}`}
        style={top3 ? { color: medalha?.cor } : undefined}
      >
        <ValorOuAusencia valor={valor} formatar={nota} />
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
  /** Altura disponível do palco (px) — a lista corta no que couber. null =
   *  página rolável do celular: todas as posições aparecem. */
  altura: number | null;
}) {
  const listaRef = useRef<HTMLDivElement | null>(null);
  // gap-2.5 = 10px; reserva ~30px para a linha "+ N alunos".
  const visiveis = useLinhasQueCabem(listaRef, altura, itens.length, 10, 30);
  if (itens.length === 0) {
    return <p className="py-16 text-center text-xl text-white/70">Ainda sem dados para exibir.</p>;
  }
  // Topo = maior valor exibido (posição 1). Base para as barras relativas.
  const valorDe = (item: ItemRanking) => {
    const v = item[campo];
    return typeof v === "number" && Number.isFinite(v) ? v : null;
  };
  const topo = Math.max(...itens.map((i) => valorDe(i) ?? 0), 0) || 1;
  const ocultos = itens.length - visiveis;
  return (
    <div ref={listaRef} className="mx-auto flex w-full max-w-[min(76rem,92vw)] flex-col gap-2.5">
      {itens.slice(0, visiveis).map((item) => {
        const v = valorDe(item);
        return (
          <LinhaRanking
            key={item.aluno_id}
            item={item}
            campo={campo}
            larguraRelativa={v === null ? null : Math.max(6, (v / topo) * 100)}
            celular={altura === null}
          />
        );
      })}
      {ocultos > 0 && (
        <p className="text-center text-sm font-medium text-white/70">
          + {ocultos} {ocultos === 1 ? "aluno brilhando" : "alunos brilhando"} na jornada
        </p>
      )}
    </div>
  );
}

function SlideMural({ mural, altura }: { mural: DadosPainel["mural"]; altura: number | null }) {
  const listaRef = useRef<HTMLUListElement | null>(null);
  // gap-3 = 12px; reserva ~30px para a linha "+ N novidades".
  const visiveis = useLinhasQueCabem(listaRef, altura, mural.length, 12, 30);
  if (mural.length === 0) {
    return <p className="py-16 text-center text-xl text-white/70">Nada no mural ainda.</p>;
  }
  const ocultos = mural.length - visiveis;
  return (
    <ul ref={listaRef} className="mx-auto grid w-full max-w-[min(76rem,92vw)] gap-3">
      {mural.slice(0, visiveis).map((evento, indice) => (
        <li
          key={indice}
          className="painel-surgir painel-mural-item flex items-center gap-4 rounded-2xl bg-white/[0.06] px-5 py-4 text-lg text-white/90 ring-1 ring-inset ring-white/10"
          style={{ animationDelay: `${Math.min(indice, 8) * 0.06}s` }}
        >
          <span className="painel-mural-icone flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-white/10 text-2xl">
            {evento.icone}
          </span>
          <span className="text-[clamp(1rem,1.8vw,2rem)]">{evento.texto}</span>
        </li>
      ))}
      {ocultos > 0 && (
        <li className="list-none text-center text-sm font-medium text-white/70">
          + {ocultos} {ocultos === 1 ? "novidade" : "novidades"} no mural
        </li>
      )}
    </ul>
  );
}

/* --------------------------------------------------------------------- Painel */

export default function PainelPublico() {
  // Mesma classe da vitrine no <html>: fundo escuro, foco visível e escala do
  // texto acima de 1920 px (TV 4K) — todo rem do telão cresce junto.
  useTelaPublica();
  // Link sem login com nome de criança: buscador não indexa nem arquiva.
  useSemIndexacao();
  // Celular (< 640 px de largura ou < 500 px de altura): página rolável.
  const celular = useModoCelular();
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
    // O palco fica dentro do <div key={slide}>, que REMONTA a cada troca de
    // slide: o observador precisa ser refeito para o nó novo (deps com
    // slideAtivo). E um nó já desligado do DOM mede 0 — essa medida é ignorada,
    // senão o slide seguinte montava com altura 0 e mostrava a lista inteira
    // (itens cortados na rolagem invisível e sem a linha "+ N").
    // No celular a página rola: nada de medir — as listas mostram tudo.
    if (celular) return;
    const palco = palcoRef.current;
    if (!palco) return;
    const medir = () => {
      const altura = palco.clientHeight;
      if (altura > 0) setAlturaPalco(altura);
    };
    medir();
    const observador = new ResizeObserver(medir);
    observador.observe(palco);
    return () => observador.disconnect();
  }, [dados, slideAtivo, celular]);

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
    // Atalhos de telão: F = tela cheia, Espaço = pausar/retomar o carrossel. Com o
    // foco num BOTÃO, o Espaço é dele (aciona o ponto do slide): antes o atalho o
    // engolia e quem navega pelo teclado não conseguia escolher o slide com Espaço.
    const aoTeclar = (evento: KeyboardEvent) => {
      if (evento.key === "f" || evento.key === "F") alternarTelaCheia();
      if (evento.key === " " && !(evento.target instanceof HTMLButtonElement)) {
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
        <FundoConstela cor="#5B6EE1" variante="telao" />
        <p className="relative text-xl" role="status">
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
        <FundoConstela cor="#5B6EE1" variante="telao" />
        <p className="relative flex items-center gap-3 text-lg" role="status">
          <span aria-hidden data-carregando
            className="h-5 w-5 rounded-full border-2 border-white/20 border-t-white/80 motion-safe:animate-spin" />
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

  const logo = (
    <img src="/simbolo-escuro.svg" alt="Constela Edu" width={44} height={44} className="h-9 w-9 shrink-0 sm:h-11 sm:w-11 xl:h-16 xl:w-16" />
  );
  const nomeDaEscola = (
    <div className="min-w-0">
      <p className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-[0.22em] text-amber-300 sm:text-sm">
        <Trophy className="h-3.5 w-3.5" /> Painel de Conquistas
      </p>
      {/* TV: nome da escola em até 2 linhas (prefixos comuns como "EMEI/EMEF
          PROFª …" continuam distinguíveis); 2.1vw (era 3vw numa linha só
          truncada): as 2 linhas cabem na altura que o palco tinha. Celular:
          linha própria, sem limite de linhas — o nome sai INTEIRO. O texto
          inteiro fica sempre no DOM (leitor de tela) e no title. */}
      <h1
        className={`painel-nome-escola ${celular ? "" : "line-clamp-2 "}font-extrabold leading-tight text-white text-[clamp(1.25rem,2.1vw,4rem)] [overflow-wrap:anywhere]`}
        style={{ fontFamily: "Poppins, Inter, sans-serif" }}
        title={dados.escola.nome}
      >
        {dados.escola.nome}
      </h1>
    </div>
  );
  // Relógio + Pausar/Modo TV (os mesmos nos dois modos).
  const controles = (
    <div className="flex shrink-0 items-center gap-3 sm:gap-4">
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
          {/* Ícone em rem (não size={18} fixo): cresce junto no 4K. */}
          {pausado
            ? <Play aria-hidden className="h-[1.125rem] w-[1.125rem]" />
            : <Pause aria-hidden className="h-[1.125rem] w-[1.125rem]" />}
        </button>
        <button
          aria-label="Modo TV — tela cheia (F)"
          title="Modo TV (F)"
          className="rounded-xl bg-white/10 p-2.5 text-white/80 ring-1 ring-inset ring-white/15 transition-colors hover:bg-white/20"
          onClick={alternarTelaCheia}
        >
          <Expand aria-hidden className="h-[1.125rem] w-[1.125rem]" />
        </button>
      </div>
    </div>
  );

  return (
    <div
      ref={raiz}
      data-modo={celular ? "celular" : "tv"}
      // TV: altura EXATA da tela (100dvh; h-screen é o fallback) +
      // overflow-hidden — o telão nunca tem barra de rolagem nem conteúdo
      // cortado pela borda. Celular: página rolável (altura mínima da tela,
      // cresce com o conteúdo); só o eixo X é recortado. Em tela cheia o
      // navegador fixa a raiz na altura da tela, então ela mesma passa a rolar.
      className={celular
        ? `relative flex min-h-screen flex-col overflow-x-clip bg-[#0F1626] text-white ${telaCheia ? "overflow-y-auto" : ""} ${modoTv ? "cursor-none" : ""}`
        : `relative flex h-screen flex-col overflow-hidden bg-[#0F1626] text-white ${modoTv ? "cursor-none" : ""}`}
      style={celular ? { minHeight: "100dvh" } : { height: "100dvh" }}
    >
      <FundoConstela cor={cor} variante="telao" />

      {/* ---------------------------------------------------------- Cabeçalho */}
      {celular ? (
        // Celular: logo + controles numa linha; o nome da escola embaixo, na
        // largura toda (quebra em quantas linhas precisar).
        <header className="painel-cabecalho relative flex flex-col gap-3 px-5 py-4 sm:px-8 sm:py-5">
          <div className="flex items-center justify-between gap-3 sm:gap-4">
            {logo}
            {controles}
          </div>
          {nomeDaEscola}
        </header>
      ) : (
        <header className="painel-cabecalho relative flex items-center justify-between gap-4 px-5 py-4 sm:px-8 sm:py-5">
          {/* min-w-0 + flex-1: o grupo do nome ENCOLHE (o h1 quebra em até 2
              linhas) em vez de empurrar relógio e botões para fora da tela (a
              raiz corta o excesso). */}
          <div className="flex min-w-0 flex-1 items-center gap-3 sm:gap-4">
            {logo}
            {nomeDaEscola}
          </div>
          {controles}
        </header>
      )}

      {/* Filete com a cor da escola separando cabeçalho do palco. */}
      <div className="relative mx-5 h-px sm:mx-8" style={{ background: `linear-gradient(90deg, ${cor}, transparent 80%)` }} />

      {/* -------------------------------------------------------------- Palco */}
      {/* Celular: sem min-h-0 — o palco cresce com a lista e a página rola. */}
      <main className={`painel-area relative flex ${celular ? "" : "min-h-0 "}flex-1 flex-col px-4 pb-2 pt-4 sm:px-8 sm:pt-5`}>
        <div key={slide} className={`painel-surgir flex ${celular ? "" : "min-h-0 "}w-full flex-1 flex-col`}>
          {/* Título sempre visível (fora da área rolável — nunca é cortado). */}
          <div className="painel-titulo-bloco mb-3 shrink-0 text-center sm:mb-4">
            <h2
              className="painel-titulo flex items-center justify-center gap-3 font-extrabold text-white text-[clamp(1.5rem,3vw,4rem)]"
              style={{ fontFamily: "Poppins, Inter, sans-serif" }}
            >
              <meta.icone className="h-7 w-7 shrink-0 sm:h-9 sm:w-9 xl:h-14 xl:w-14" style={{ color: OURO }} strokeWidth={2.3} />
              {meta.titulo}
            </h2>
            <p className="painel-legenda mt-1 text-sm text-white/70 sm:text-base">{meta.legenda}</p>
          </div>

          {/* TV: palco medido — as listas mostram só o que cabe (sem barra, sem
             corte), com a rolagem invisível de reserva. Celular: sem medição,
             sem limite de altura e sem rolagem própria — a lista inteira entra
             no fluxo e quem rola é a página. */}
          <div
            ref={palcoRef}
            data-palco
            className={celular ? "flex flex-1 flex-col" : "painel-sem-barra flex min-h-0 flex-1 flex-col overflow-y-auto"}
          >
            <div className="my-auto w-full py-1">
              {slide === "ranking" && (
                <SlideRanking itens={dados.ranking} campo="nota_geral" altura={celular ? null : alturaPalco} />
              )}
              {slide === "evolucao" && (
                <SlideRanking itens={dados.evolucao} campo="nota_evolucao" altura={celular ? null : alturaPalco} />
              )}
              {slide === "destaques" && <SlideDestaques destaques={dados.destaques} empilhado={celular} />}
              {slide === "mural" && <SlideMural mural={dados.mural} altura={celular ? null : alturaPalco} />}
            </div>
          </div>
        </div>
      </main>

      {/* --------------------------------------- Indicadores REAIS da escola */}
      {dados.estatisticas && (
        <section
          aria-label="Números da escola"
          className="painel-numeros relative mx-4 mb-1 grid grid-cols-2 gap-2 rounded-2xl bg-white/[0.05] px-3 py-2.5 ring-1 ring-inset ring-white/10 sm:mx-8 sm:grid-cols-4 sm:gap-3 sm:px-5"
        >
          {[
            { emoji: "👥", rotulo: "Alunos", valor: dados.estatisticas.alunos },
            { emoji: "🎯", rotulo: "Atividades", valor: dados.estatisticas.atividades },
            { emoji: "⭐", rotulo: "Estrelas", valor: dados.estatisticas.estrelas },
            { emoji: "📚", rotulo: "Livros lidos", valor: dados.estatisticas.livros },
          ].map((e) => (
            <div key={e.rotulo} className="flex items-center justify-center gap-2.5">
              <span className="painel-numero-emoji text-xl sm:text-2xl xl:text-4xl" aria-hidden>{e.emoji}</span>
              <div className="text-left leading-tight">
                <p
                  className="painel-numero font-extrabold tabular-nums text-white text-[clamp(1.1rem,2.2vw,3rem)]"
                  style={{ fontFamily: "Poppins, Inter, sans-serif" }}
                >
                  <ValorOuAusencia valor={e.valor} formatar={(v) => v.toLocaleString("pt-BR")} />
                </p>
                <p className="painel-numero-rotulo text-[clamp(0.6rem,1vw,1.2rem)] font-semibold uppercase tracking-wider text-white/70">
                  {e.rotulo}
                </p>
              </div>
            </div>
          ))}
        </section>
      )}

      {/* Dica do dia: motivação discreta, gira com o dia do ano. */}
      <p className="painel-dica relative px-6 pb-1 text-center text-[clamp(0.75rem,1.3vw,1.5rem)] text-white/70">
        <Sparkles className="mr-1.5 inline h-3.5 w-3.5 text-amber-300/80" aria-hidden />
        {DICAS[Math.floor((agora.getTime() / 86_400_000)) % DICAS.length]}
      </p>

      {/* ------------------------------------------------------------- Rodapé */}
      <footer
        className={`painel-rodape relative flex flex-col items-center gap-3 px-5 py-4 transition-opacity duration-500 sm:flex-row sm:justify-between sm:px-8 ${
          modoTv ? "opacity-30" : "opacity-100"
        }`}
      >
        <div className="flex items-center gap-2 text-sm font-medium text-white/70">
          <img src="/simbolo-escuro.svg" alt="" aria-hidden width={18} height={18} className="h-4 w-4 opacity-70" />
          <span style={{ fontFamily: "Poppins, Inter, sans-serif" }}>
            constela<span className="text-amber-300">edu</span>
          </span>
        </div>

        {dados.slides.length > 1 && (
          <div className="flex items-center">
            {/* Área de toque de 24 px de altura (WCAG 2.5.8) em volta do ponto. */}
            {dados.slides.map((nomeSlide, indice) => (
              <button
                key={nomeSlide}
                aria-label={`Ir para ${TITULOS[nomeSlide]?.titulo ?? nomeSlide}`}
                // O ponto aceso é só cor: o slide atual também vai para o leitor de tela.
                aria-current={indice === slideAtivo % dados.slides.length ? "true" : undefined}
                className="group flex h-6 items-center justify-center rounded-full px-[7px]"
                onClick={() => setSlideAtivo(indice)}
              >
                <span
                  aria-hidden
                  className={`block h-2.5 rounded-full transition-all motion-reduce:transition-none ${
                    indice === slideAtivo % dados.slides.length ? "w-8 bg-amber-300" : "w-2.5 bg-white/25 group-hover:bg-white/40"
                  }`}
                />
              </button>
            ))}
          </div>
        )}

        <div className="flex items-center gap-2 text-xs text-white/70">
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
