/**
 * Seletor em PÍLULA (identidade v2, docs/design/IDENTIDADE-VISUAL-V2.md): um
 * <select> NATIVO vestido como a pílula branca das telas de referência — ícone
 * violeta à esquerda, chevron à direita, sombra de cartão.
 *
 * Continua nativo de propósito: ~30 testes e o E2E usam `selectOptions`, e no
 * celular/tablet a lista aberta é a do sistema (acessível e confortável ao toque).
 * Os nomes acessíveis (aria-label) ficam com quem usa (SeletorPeriodo, SeletorTurno).
 */
import { ChevronDown } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

/** Classes do <select> dentro de `MolduraPilula` (espaço para o ícone e o chevron). */
export const estiloSelectPilula =
  "h-10 w-auto min-w-0 max-w-full cursor-pointer appearance-none truncate rounded-xl border border-zinc-200 bg-white pl-9 pr-9 text-sm font-medium text-zinc-800 shadow-cartao transition-colors hover:border-zinc-300 focus:border-indigo-500 disabled:cursor-not-allowed disabled:opacity-60 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100 dark:hover:border-zinc-600";

/** Classes de um campo de data ao lado da pílula (mesma altura e raio). */
export const estiloDataPilula =
  "h-10 w-auto rounded-xl border border-zinc-200 bg-white px-3 text-sm text-zinc-800 shadow-cartao transition-colors hover:border-zinc-300 focus:border-indigo-500 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100 dark:[color-scheme:dark]";

/** Moldura com o ícone e o chevron por cima do <select> (decorativos, aria-hidden). */
export function MolduraPilula({
  icone: Icone,
  children,
  className = "",
}: {
  icone: LucideIcon;
  children: ReactNode;
  className?: string;
}) {
  return (
    <span className={`relative inline-flex min-w-0 max-w-full items-center ${className}`}>
      <Icone
        size={16}
        strokeWidth={2}
        aria-hidden
        className="pointer-events-none absolute left-3 text-indigo-600 dark:text-indigo-300"
      />
      {children}
      <ChevronDown
        size={16}
        aria-hidden
        className="pointer-events-none absolute right-3 text-zinc-500 dark:text-zinc-400"
      />
    </span>
  );
}
