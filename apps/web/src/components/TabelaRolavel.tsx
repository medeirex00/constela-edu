/**
 * Moldura de tabela larga (identidade v2, celular e tablet). Quando a tabela não cabe,
 * ela rola de lado DENTRO do cartão, com degradê na borda que tem mais colunas e um
 * aviso em texto ACIMA da tabela ("Deslize para o lado..."), visível sem rolar a lista
 * inteira. Só quando rola, a região ganha nome e foco (rolagem pelo teclado).
 *
 * Para a coluna que não pode sumir no celular (nota, índice, ações), use a classe
 * `presa-celular` (index.css) no <th>/<td>: ela fica presa à direita abaixo de 640 px.
 */
import { useRef, type ReactNode } from "react";

import { useBordasDaRolagem } from "../hooks/useBordasDaRolagem";

export function TabelaRolavel({ rotulo, children, className = "" }: {
  /** Nome da região quando ela rola (ex.: "Ranking Geral: tabela completa"). */
  rotulo: string;
  children: ReactNode;
  className?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const { inicio: esquerda, fim: direita } = useBordasDaRolagem(ref, "x");
  const rola = esquerda || direita;
  return (
    <div className={className}>
      {rola && (
        <p className="flex items-center gap-1.5 px-4 pb-2 pt-1 text-xs font-medium text-zinc-500 dark:text-zinc-400">
          <span aria-hidden>↔</span> Deslize a tabela para o lado para ver todas as colunas.
        </p>
      )}
      <div className="relative">
        <div
          ref={ref}
          className="relative overflow-x-auto"
          {...(rola ? { role: "region", "aria-label": rotulo, tabIndex: 0 } : {})}
        >
          {children}
        </div>
        {esquerda && (
          <div aria-hidden className="pointer-events-none absolute inset-y-0 left-0 w-8 bg-gradient-to-r from-white dark:from-zinc-900" />
        )}
        {direita && (
          <div aria-hidden className="pointer-events-none absolute inset-y-0 right-0 w-10 bg-gradient-to-l from-white dark:from-zinc-900" />
        )}
      </div>
    </div>
  );
}
