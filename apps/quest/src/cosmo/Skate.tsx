/**
 * Skate voador com jatos de propulsão — primeiro meio de locomoção do Quest
 * (slot `veiculo`). Duas fases:
 *   - `entrando`: voa desde a constelação até debaixo do personagem;
 *   - idle: flutua com os jatos piscando enquanto o astronauta anda em cima.
 */
import "./skate.css";

export function Skate({ entrando = false }: { entrando?: boolean }) {
  return (
    <svg
      className={`skate${entrando ? " entrando" : ""}`}
      viewBox="0 0 260 150"
      aria-hidden
    >
      {/* rastro de brilho */}
      <ellipse cx="130" cy="78" rx="120" ry="20" fill="#5EC1FF" opacity=".25" />

      {/* jatos laterais (propulsão) */}
      <g className="skate-jato esq">
        <rect x="30" y="58" width="42" height="20" rx="10" fill="#3A2E66" />
        <rect x="24" y="61" width="14" height="14" rx="7" fill="#231D4E" />
        <path className="chama" d="M24 68 L2 62 L2 74 Z" fill="#FF8E3C" />
        <path className="chama-int" d="M24 68 L10 64 L10 72 Z" fill="#FFC93C" />
      </g>
      <g className="skate-jato dir">
        <rect x="188" y="58" width="42" height="20" rx="10" fill="#3A2E66" />
        <rect x="222" y="61" width="14" height="14" rx="7" fill="#231D4E" />
        <path className="chama" d="M236 68 L258 62 L258 74 Z" fill="#FF8E3C" />
        <path className="chama-int" d="M236 68 L250 64 L250 72 Z" fill="#FFC93C" />
      </g>

      {/* deck */}
      <ellipse cx="130" cy="60" rx="90" ry="24" fill="#231D4E" />
      <ellipse cx="130" cy="54" rx="90" ry="22" fill="url(#deckGrad)" />
      <ellipse cx="130" cy="50" rx="76" ry="15" fill="rgba(255,255,255,.18)" />
      <defs>
        <linearGradient id="deckGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#7C6FF0" />
          <stop offset="1" stopColor="#4EA8FF" />
        </linearGradient>
      </defs>
      {/* faixa de brilho */}
      <path d="M70 50 Q130 34 190 50" stroke="rgba(255,255,255,.5)"
            strokeWidth="4" fill="none" strokeLinecap="round" />
      {/* estrelinhas na prancha */}
      <text x="104" y="58" fontSize="20" fill="rgba(255,255,255,.85)">★</text>
      <text x="146" y="56" fontSize="14" fill="rgba(255,255,255,.7)">✦</text>
    </svg>
  );
}
