/**
 * Corpo do planeta da matéria — flutua no cenário (canto superior direito),
 * com halo de luz, anéis opcionais, uma lua em órbita e crateras. Dá a
 * sensação de estar viajando para um mundo próprio por disciplina.
 */
import type { Materia } from "./materias";

export function Planeta({ materia }: { materia: Materia }) {
  const { corpo } = materia;
  return (
    <svg className="cena-planeta" viewBox="0 0 420 420" aria-hidden>
      <defs>
        <radialGradient id="pgrad" cx="38%" cy="34%" r="72%">
          <stop offset="0%" stopColor={corpo.c1} />
          <stop offset="100%" stopColor={corpo.c2} />
        </radialGradient>
      </defs>

      {/* halo de luz */}
      <circle cx="210" cy="210" r="150" fill={corpo.c1} opacity=".18"
              className="planeta-halo" />

      {/* anéis atrás */}
      {corpo.aneis && (
        <ellipse cx="210" cy="210" rx="196" ry="58" fill="none"
                 stroke="rgba(255,255,255,.5)" strokeWidth="10"
                 transform="rotate(-22 210 210)" />
      )}

      {/* corpo */}
      <circle cx="210" cy="210" r="120" fill="url(#pgrad)" />
      {/* crateras / manchas */}
      <ellipse cx="168" cy="170" rx="26" ry="18" fill="rgba(255,255,255,.16)" />
      <ellipse cx="250" cy="240" rx="34" ry="22" fill="rgba(0,0,0,.12)" />
      <ellipse cx="196" cy="256" rx="16" ry="12" fill="rgba(0,0,0,.1)" />
      {/* brilho */}
      <path d="M150 150 Q140 210 168 262" stroke="rgba(255,255,255,.4)"
            strokeWidth="14" strokeLinecap="round" fill="none" />

      {/* anéis na frente */}
      {corpo.aneis && (
        <path d="M40 236 A196 58 -22 0 0 356 176" fill="none"
              stroke="rgba(255,255,255,.7)" strokeWidth="10" strokeLinecap="round" />
      )}

      {/* lua em órbita */}
      <g className="planeta-lua">
        <circle cx="210" cy="40" r="18" fill="rgba(255,255,255,.9)" />
        <circle cx="204" cy="36" r="5" fill="rgba(0,0,0,.12)" />
      </g>
    </svg>
  );
}
