/**
 * Itens de costas do Cosmo (slot `costas`): asas de luz e mochila espacial.
 * Desenhados ATRÁS do corpo (antes das pernas/tronco no SVG).
 */
export function Costas({ slug }: { slug: string }) {
  switch (slug) {
    case "asas":
      return (
        <g className="cosmo-asas">
          {/* asa esquerda */}
          <g className="asa esq">
            <path d="M188 300 C90 250 30 300 46 380 C120 350 150 380 188 372 Z"
                  fill="rgba(255,255,255,.9)" />
            <path d="M188 320 C120 300 78 330 84 372 C130 356 156 372 188 366 Z"
                  fill="rgba(94,193,255,.55)" />
          </g>
          {/* asa direita */}
          <g className="asa dir">
            <path d="M232 300 C330 250 390 300 374 380 C300 350 270 380 232 372 Z"
                  fill="rgba(255,255,255,.9)" />
            <path d="M232 320 C300 300 342 330 336 372 C290 356 264 372 232 366 Z"
                  fill="rgba(180,140,255,.55)" />
          </g>
        </g>
      );

    case "mochila":
      return (
        <g>
          <rect x="150" y="250" width="120" height="150" rx="30"
                fill="#7C6FF0" />
          <rect x="150" y="250" width="120" height="150" rx="30"
                fill="rgba(0,0,0,.12)" />
          <rect x="176" y="286" width="68" height="52" rx="14" fill="#A78BFA" />
          <line x1="210" y1="250" x2="210" y2="230" stroke="#4EA8FF" strokeWidth="8" strokeLinecap="round" />
          <circle cx="210" cy="224" r="9" fill="#FFC93C" />
        </g>
      );

    case "nenhum":
    default:
      return null;
  }
}
