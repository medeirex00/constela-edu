/**
 * Identidade visual de cada plataforma (identidade v2): Elefante Letrado = violeta
 * (Leitura), Matific = verde-azulado (Matemática). Fonte única para ícone, tom pastel
 * e pílula — Integrações, Importações, Relatório por Período, Elefante/Matific e a
 * Análise usam o mesmo código de cor, como nas telas de referência.
 *
 * Plataforma desconhecida (valor novo do backend) cai no neutro com o nome cru —
 * nunca é rotulada como outra plataforma.
 */
import { BookOpen, Calculator, Plug } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { IconePastel, type TomPastel } from "./ui";

export interface IdentidadePlataforma {
  nome: string;
  /** Primeiro nome, para pílulas curtas ("Elefante"). */
  curto: string;
  area: string;
  tom: TomPastel;
  icone: LucideIcon;
  pilula: string;
  ponto: string;
}

export const IDENTIDADE_PLATAFORMA: Record<"elefante" | "matific", IdentidadePlataforma> = {
  elefante: {
    nome: "Elefante Letrado",
    curto: "Elefante",
    area: "Leitura",
    tom: "violeta",
    icone: BookOpen,
    pilula: "bg-indigo-50 text-indigo-700 dark:bg-indigo-500/15 dark:text-indigo-300",
    ponto: "bg-indigo-500",
  },
  matific: {
    nome: "Matific",
    curto: "Matific",
    area: "Matemática",
    tom: "teal",
    icone: Calculator,
    pilula: "bg-teal-50 text-teal-700 dark:bg-teal-500/15 dark:text-teal-300",
    ponto: "bg-teal-500",
  },
};

export function identidadeDe(plataforma: string | null | undefined): IdentidadePlataforma | null {
  if (plataforma === "elefante" || plataforma === "matific") return IDENTIDADE_PLATAFORMA[plataforma];
  return null;
}

/** Pílula com a cor da plataforma (o nome vai em texto; a cor é só reforço). */
export function PilulaPlataforma({ plataforma, curto = false }: { plataforma: string; curto?: boolean }) {
  const id = identidadeDe(plataforma);
  const nome = id ? (curto ? id.curto : id.nome) : plataforma;
  return (
    <span
      className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-semibold ${
        id?.pilula ?? "bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300"
      }`}
    >
      <span aria-hidden className={`h-1.5 w-1.5 rounded-full ${id?.ponto ?? "bg-zinc-400"}`} />
      {nome}
    </span>
  );
}

/** Ícone da plataforma no quadrado pastel da cor dela. */
export function IconePlataforma({
  plataforma,
  tamanho = "md",
  className = "",
}: {
  plataforma: string;
  tamanho?: "sm" | "md" | "lg";
  className?: string;
}) {
  const id = identidadeDe(plataforma);
  return (
    <IconePastel icone={id?.icone ?? Plug} tom={id?.tom ?? "neutro"} tamanho={tamanho} className={className} />
  );
}
