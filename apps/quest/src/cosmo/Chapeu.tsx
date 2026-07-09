/**
 * Chapéus do Cosmo (slot `chapeu` do avatar). Sentam sobre a cúpula do
 * capacete (topo ~ y=132, centro x=210). Desenhados antes do visor para
 * ficarem atrás dele.
 */
export function Chapeu({ slug }: { slug: string }) {
  switch (slug) {
    case "coroa":
      return (
        <g>
          <path d="M150 148 L150 108 L178 134 L210 100 L242 134 L270 108 L270 148 Z"
                fill="#FFC93C" stroke="#E0A414" strokeWidth="5"
                strokeLinejoin="round" />
          <circle cx="210" cy="112" r="7" fill="#FF5470" />
          <circle cx="160" cy="120" r="5" fill="#4EA8FF" />
          <circle cx="260" cy="120" r="5" fill="#2EE6A8" />
        </g>
      );

    case "cartola":
      return (
        <g>
          <ellipse cx="210" cy="150" rx="96" ry="18" fill="#231D4E" />
          <rect x="158" y="66" width="104" height="88" rx="10" fill="#231D4E" />
          <rect x="158" y="124" width="104" height="16" fill="#FF5470" />
        </g>
      );

    case "laco":
      return (
        <g transform="translate(210 122)">
          <path d="M0 0 L-46 -22 L-46 22 Z" fill="#FF5470" />
          <path d="M0 0 L46 -22 L46 22 Z" fill="#FF5470" />
          <circle cx="0" cy="0" r="12" fill="#C43A54" />
        </g>
      );

    case "fone":
      return (
        <g stroke="#231D4E" fill="#231D4E">
          <path d="M120 200 Q120 96 210 96 Q300 96 300 200"
                strokeWidth="16" fill="none" strokeLinecap="round" />
          <rect x="104" y="188" width="34" height="56" rx="14" />
          <rect x="282" y="188" width="34" height="56" rx="14" />
          <rect x="110" y="198" width="22" height="36" rx="10" fill="#FF5470" stroke="none" />
          <rect x="288" y="198" width="22" height="36" rx="10" fill="#FF5470" stroke="none" />
        </g>
      );

    case "cowboy":
      return (
        <g>
          <ellipse cx="210" cy="150" rx="108" ry="20" fill="#8B5A2B" />
          <path d="M162 150 Q158 92 210 90 Q262 92 258 150 Z" fill="#A0642F" />
          <rect x="162" y="138" width="96" height="14" rx="6" fill="#5C3A18" />
        </g>
      );

    case "nenhum":
    default:
      return null;
  }
}
