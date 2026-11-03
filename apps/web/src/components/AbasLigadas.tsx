/**
 * Abas segmentadas LIGADAS a um painel — o mesmo visual do `Abas` de ui.tsx (pílula
 * violeta na ativa, caixa branca de cartão), com o que o `Abas` não tem: um `id` por
 * aba, para o painel (`role="tabpanel"`) ser rotulado pela aba ativa
 * (`aria-labelledby`), como as telas de Relatórios, Análise educacional e Elefante já
 * faziam (e os testes conferem).
 *
 * Padrão WAI-ARIA completo: role=tablist/tab, aria-selected, aria-controls, foco
 * itinerante (só a aba ativa tem tabIndex=0) e setas ←/→, Home e End — que trocam de
 * aba E levam o foco junto.
 */
import { useRef, type KeyboardEvent } from "react";
import type { LucideIcon } from "lucide-react";

export interface ItemAbaLigada<T extends string> {
  valor: T;
  /** O nome acessível da aba (o texto que os testes e o leitor de tela usam). */
  rotulo: string;
  icone?: LucideIcon;
}

export function AbasLigadas<T extends string>({
  itens,
  valor,
  aoMudar,
  rotulo,
  idDaAba,
  idPainel,
  className = "",
}: {
  itens: readonly ItemAbaLigada<T>[];
  valor: T;
  aoMudar: (valor: T) => void;
  /** Nome do grupo de abas (aria-label do tablist). */
  rotulo: string;
  /** O id de cada aba (o painel aponta para o da ativa em aria-labelledby). */
  idDaAba: (valor: T) => string;
  /** O id do painel que as abas controlam. */
  idPainel: string;
  className?: string;
}) {
  const refs = useRef<Partial<Record<string, HTMLButtonElement | null>>>({});

  function aoTecla(evento: KeyboardEvent<HTMLButtonElement>, indice: number) {
    const n = itens.length;
    const alvo = evento.key === "ArrowRight" ? (indice + 1) % n
      : evento.key === "ArrowLeft" ? (indice - 1 + n) % n
        : evento.key === "Home" ? 0
          : evento.key === "End" ? n - 1 : null;
    if (alvo == null) return;
    evento.preventDefault();
    const destino = itens[alvo].valor;
    aoMudar(destino);
    refs.current[destino]?.focus();
  }

  return (
    <div
      role="tablist"
      aria-label={rotulo}
      className={`inline-flex max-w-full flex-wrap gap-1 rounded-2xl border border-zinc-200/80 bg-white p-1 shadow-cartao dark:border-zinc-800 dark:bg-zinc-900 ${className}`}
    >
      {itens.map((item, i) => {
        const ativa = item.valor === valor;
        const Icone = item.icone;
        return (
          <button
            key={item.valor}
            ref={(el) => {
              refs.current[item.valor] = el;
            }}
            id={idDaAba(item.valor)}
            type="button"
            role="tab"
            aria-selected={ativa}
            aria-controls={idPainel}
            tabIndex={ativa ? 0 : -1}
            onClick={() => aoMudar(item.valor)}
            onKeyDown={(e) => aoTecla(e, i)}
            className={`inline-flex items-center gap-2 rounded-xl px-3.5 py-2 text-sm font-semibold transition-colors ${
              ativa
                ? "bg-indigo-600 text-white shadow-pilula"
                : "text-zinc-600 hover:bg-zinc-100 hover:text-zinc-900 dark:text-zinc-300 dark:hover:bg-zinc-800 dark:hover:text-white"
            }`}
          >
            {Icone && <Icone size={16} aria-hidden className="shrink-0" />}
            {item.rotulo}
          </button>
        );
      })}
    </div>
  );
}
