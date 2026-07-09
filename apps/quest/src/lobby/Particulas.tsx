/**
 * Campo de partículas temáticas do planeta: glifos da matéria (números,
 * letras…) ou formas (bolhas, folhas, faíscas, tinta) que sobem e flutuam
 * pelo espaço. Contagem limitada e só transform/opacity (leve em tablet).
 */
import { useMemo } from "react";

import type { Particula } from "./materias";

const QUANTIDADE = 16;

const CORES_TINTA = ["#FF5FA0", "#FFC93C", "#2EE6A8", "#4EA8FF", "#A78BFA", "#FF8E3C"];

export function Particulas({ config }: { config: Particula }) {
  // Posições/durações aleatórias fixadas por render (não recalcula por frame)
  const itens = useMemo(() =>
    Array.from({ length: QUANTIDADE }, (_, i) => ({
      esquerda: Math.round(Math.random() * 96) + 2,
      base: Math.round(Math.random() * 40),
      dur: (7 + Math.random() * 8).toFixed(1),
      atraso: (-Math.random() * 12).toFixed(1),
      tam: Math.round(14 + Math.random() * 26),
      glifo: config.glifos?.[i % (config.glifos?.length || 1)] ?? "",
      cor: config.tipo === "tinta"
        ? CORES_TINTA[i % CORES_TINTA.length]
        : (config.cor ?? "rgba(255,255,255,.75)"),
    })),
    [config],
  );

  return (
    <div className="particulas" aria-hidden>
      {itens.map((p, i) => (
        <span
          key={i}
          className={`particula p-${config.tipo}`}
          style={{
            left: `${p.esquerda}%`,
            bottom: `${p.base}%`,
            animationDuration: `${p.dur}s`,
            animationDelay: `${p.atraso}s`,
            fontSize: config.tipo === "glifo" ? `${p.tam + 12}px` : undefined,
            width: config.tipo === "glifo" ? undefined : `${p.tam * 0.5}px`,
            height: config.tipo === "glifo" ? undefined : `${p.tam * 0.5}px`,
            color: p.cor,
            background: config.tipo === "glifo" ? undefined : p.cor,
          }}
        >
          {config.tipo === "glifo" ? p.glifo : ""}
        </span>
      ))}
    </div>
  );
}
