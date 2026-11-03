/**
 * Peças visuais da GAMIFICAÇÃO (Conquistas e Mural, Biblioteca de Conquistas e o
 * editor em Configurações) na identidade visual v2 — docs/design/IDENTIDADE-VISUAL-V2.md.
 *
 * Só apresentação: nada aqui decide quem desbloqueou o quê, calcula XP ou muda a
 * ordem das conquistas (isso é do backend, services/gamificacao.py). São os
 * pedaços que se repetem nas três telas: o emoji da conquista num quadrado pastel
 * na cor da raridade, o selo de raridade, o chip da plataforma, a pílula de XP e o
 * tempo relativo do mural.
 */
import { Gem } from "lucide-react";
import { paraData } from "@constela/core";
import type { ReactNode } from "react";

/** Nome de exibição da plataforma de uma conquista ("" = deduzida pelo critério). */
export const NOME_PLATAFORMA: Record<string, string> = {
  elefante: "Elefante Letrado",
  matific: "Matific",
  geral: "Geral",
};

const NOMES_RARIDADE: Record<string, string> = {
  comum: "Comum", rara: "Rara", epica: "Épica", lendaria: "Lendária",
};

/** Cores por raridade: selo (texto escuro sobre pastel, contraste AA) e o quadrado do emoji. */
const ESTILO_RARIDADE: Record<string, { selo: string; quadrado: string }> = {
  comum: {
    selo: "bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-200",
    quadrado: "bg-zinc-100 ring-zinc-200 dark:bg-zinc-800 dark:ring-zinc-700",
  },
  rara: {
    selo: "bg-indigo-50 text-indigo-700 dark:bg-indigo-500/15 dark:text-indigo-200",
    quadrado: "bg-gradient-to-br from-indigo-50 to-indigo-100 ring-indigo-200 dark:from-indigo-500/20 dark:to-indigo-500/5 dark:ring-indigo-500/30",
  },
  epica: {
    selo: "bg-ouro-50 text-ouro-700 dark:bg-ouro-400/15 dark:text-ouro-200",
    quadrado: "bg-gradient-to-br from-ouro-50 to-ouro-100 ring-ouro-200 dark:from-ouro-400/20 dark:to-ouro-400/5 dark:ring-ouro-400/30",
  },
  lendaria: {
    selo: "bg-fuchsia-50 text-fuchsia-700 dark:bg-fuchsia-500/15 dark:text-fuchsia-200",
    quadrado: "bg-gradient-to-br from-fuchsia-50 to-fuchsia-100 ring-fuchsia-200 dark:from-fuchsia-500/20 dark:to-fuchsia-500/5 dark:ring-fuchsia-500/30",
  },
};

const estiloDa = (raridade?: string | null) => ESTILO_RARIDADE[raridade ?? ""] ?? ESTILO_RARIDADE.comum;

/** Selo da raridade (pílula com ícone). A raridade vai em TEXTO, não só na cor. */
export function BadgeRaridade({ raridade, rotulo }: { raridade: string; rotulo?: string }) {
  return (
    <span className={`inline-flex shrink-0 items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-semibold ${estiloDa(raridade).selo}`}>
      <Gem size={11} strokeWidth={2.4} aria-hidden />
      {rotulo ?? NOMES_RARIDADE[raridade] ?? raridade}
    </span>
  );
}

/**
 * O emoji da conquista num quadrado pastel na cor da raridade. Decorativo
 * (aria-hidden): o nome da conquista sempre aparece em texto ao lado.
 */
export function QuadradoEmoji({
  emoji,
  raridade,
  tamanho = "md",
  className = "",
}: {
  emoji: string;
  raridade?: string | null;
  tamanho?: "sm" | "md" | "lg" | "xl";
  className?: string;
}) {
  const caixa = {
    sm: "h-9 w-9 rounded-xl text-lg",
    md: "h-11 w-11 rounded-xl text-xl",
    lg: "h-14 w-14 rounded-2xl text-[28px]",
    xl: "h-20 w-20 rounded-3xl text-[40px]",
  }[tamanho];
  return (
    <span
      aria-hidden
      className={`grid shrink-0 place-items-center leading-none ring-1 ${caixa} ${estiloDa(raridade).quadrado} ${className}`}
    >
      {emoji || "🏅"}
    </span>
  );
}

const ESTILO_PLATAFORMA: Record<string, string> = {
  elefante: "bg-indigo-50 text-indigo-700 dark:bg-indigo-500/15 dark:text-indigo-200",
  matific: "bg-teal-50 text-teal-800 dark:bg-teal-500/15 dark:text-teal-200",
  geral: "bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-200",
};

/** Chip da plataforma (Elefante Letrado violeta, Matific verde-azulado, Geral neutro). */
export function ChipPlataforma({ plataforma }: { plataforma: string }) {
  return (
    <span className={`inline-flex shrink-0 items-center rounded-lg px-2 py-0.5 text-xs font-semibold ${ESTILO_PLATAFORMA[plataforma] ?? ESTILO_PLATAFORMA.geral}`}>
      {NOME_PLATAFORMA[plataforma] ?? (plataforma || "Geral")}
    </span>
  );
}

/** Pílula âmbar de XP ("+100 XP"). Texto marinho sobre o âmbar (nunca branco). */
export function PilulaXp({ children }: { children: ReactNode }) {
  return (
    <span className="inline-flex shrink-0 items-center rounded-full bg-ouro-100 px-2.5 py-0.5 text-xs font-bold tabular-nums text-marinho-900 dark:bg-ouro-400/20 dark:text-ouro-200">
      {children}
    </span>
  );
}

const FUSO_BR = "America/Sao_Paulo";

/**
 * "há 2 h" a partir de um horário da API (UTC sem sufixo, a mesma regra do
 * `paraData` do pacote compartilhado), com a data completa no horário de Brasília
 * para o `title`. Mais de 30 dias: a data por extenso. Inválido: null.
 */
export function tempoRelativo(
  iso: string | null | undefined,
  agora: number = Date.now(),
): { texto: string; completo: string } | null {
  if (!iso) return null;
  const data = paraData(iso);
  if (Number.isNaN(data.getTime())) return null;
  const completo = data.toLocaleString("pt-BR", { timeZone: FUSO_BR, dateStyle: "short", timeStyle: "short" });
  const minutos = Math.floor((agora - data.getTime()) / 60000);
  let texto: string;
  if (minutos < 1) texto = "agora há pouco";
  else if (minutos < 60) texto = `há ${minutos} min`;
  else if (minutos < 60 * 24) texto = `há ${Math.floor(minutos / 60)} h`;
  else if (minutos < 60 * 48) texto = "ontem";
  else if (minutos < 60 * 24 * 30) texto = `há ${Math.floor(minutos / (60 * 24))} dias`;
  else texto = data.toLocaleDateString("pt-BR", { timeZone: FUSO_BR });
  return { texto, completo };
}

/** "1 aluno" / "3 alunos". */
export function plural(n: number, um: string, varios: string): string {
  return `${n.toLocaleString("pt-BR")} ${n === 1 ? um : varios}`;
}
