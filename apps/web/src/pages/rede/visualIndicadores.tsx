/**
 * Peças VISUAIS comuns dos cartões dos indicadores oficiais (ICA, SARESP, Ideb/Saeb)
 * — identidade visual v2. Só apresentação: nenhum número, nenhuma regra.
 *
 * - `CabecalhoIndicador`: ícone em quadrado pastel + nome + chip da fonte (o h2).
 * - `classeTrilhoAbas` / `classeAba`: as abas por SUBLINHADO viraram as abas
 *   segmentadas da referência (pílula violeta na ativa). Os papéis (tablist/tab/
 *   tabpanel), os ids e o comportamento continuam nos próprios cartões.
 */
import type { LucideIcon } from "lucide-react";

import { Badge, IconePastel, type TomPastel } from "../../components/ui";

export function CabecalhoIndicador({ icone, tom, titulo, fonte, descricao }: {
  icone: LucideIcon; tom: TomPastel; titulo: string; fonte: string; descricao?: string;
}) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div className="flex min-w-0 items-start gap-3">
        <IconePastel icone={icone} tom={tom} />
        <div className="min-w-0">
          <h2 className="text-base font-semibold tracking-tight text-zinc-900 dark:text-white">{titulo}</h2>
          {descricao && <p className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">{descricao}</p>}
        </div>
      </div>
      <Badge tom="destaque">{fonte}</Badge>
    </div>
  );
}

export const classeTrilhoAbas =
  "inline-flex max-w-full flex-wrap gap-1 rounded-2xl border border-zinc-200/80 bg-zinc-50 p-1 dark:border-zinc-800 dark:bg-zinc-900";

export function classeAba(ativa: boolean): string {
  return `rounded-xl px-3.5 py-2 text-sm font-semibold transition-colors ${
    ativa
      ? "bg-indigo-600 text-white shadow-pilula"
      : "text-zinc-600 hover:bg-white hover:text-zinc-900 dark:text-zinc-300 dark:hover:bg-zinc-800 dark:hover:text-white"
  }`;
}
