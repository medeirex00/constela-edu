/**
 * Invocação cinematográfica do Skate Voador (docs do usuário, 15 passos):
 * uma constelação brilha no alto → as estrelas se conectam e desenham a
 * silhueta do skate → ele se materializa → sai da constelação e voa com um
 * rastro de luz até os pés do personagem → o personagem pula e aterrissa em
 * cima. Overlay que toca uma vez e some.
 */
import { useEffect } from "react";

import { Skate } from "./Skate";
import "./invocacao.css";

interface Props {
  /** Disparado quando o skate chega aos pés (personagem deve pular). */
  aoPular?: () => void;
  /** Disparado ao final — o skate persistente do avatar assume. */
  aoTerminar: () => void;
}

// Silhueta do skate desenhada pela constelação (viewBox 0 0 260 150)
const OUTLINE = "M40 92 Q40 66 78 62 L182 62 Q220 66 220 92 Q220 116 182 118 " +
  "L78 118 Q40 116 40 92 Z";
const ESTRELAS: [number, number][] = [
  [40, 92], [78, 62], [130, 58], [182, 62], [220, 92], [182, 118], [78, 118],
];

export function InvocacaoSkate({ aoPular, aoTerminar }: Props) {
  useEffect(() => {
    const reduzido = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduzido) {
      aoPular?.();
      const t = window.setTimeout(aoTerminar, 400);
      return () => window.clearTimeout(t);
    }
    const tPular = window.setTimeout(() => aoPular?.(), 4200);
    const tFim = window.setTimeout(aoTerminar, 5200);
    return () => { window.clearTimeout(tPular); window.clearTimeout(tFim); };
  }, [aoPular, aoTerminar]);

  return (
    <div className="invocacao" aria-hidden>
      {/* nasce: constelação que brilha e desenha a silhueta do skate */}
      <div className="inv-nasce">
        <svg viewBox="0 0 260 150" className="inv-svg">
          <path className="inv-outline" d={OUTLINE} pathLength={1} />
          {ESTRELAS.map(([x, y], i) => (
            <circle key={i} className="inv-estrela" cx={x} cy={y} r={5}
                    style={{ animationDelay: `${i * 0.12}s` } as React.CSSProperties} />
          ))}
        </svg>
      </div>

      {/* voo: o skate materializado viaja até os pés com rastro de luz */}
      <div className="inv-voo">
        <div className="inv-rastro" />
        <div className="inv-skate"><Skate /></div>
      </div>
    </div>
  );
}
