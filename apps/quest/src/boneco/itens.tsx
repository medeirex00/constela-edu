/**
 * Itens vestíveis do boneco humanoide, alinhados ao viewBox 0 0 360 560:
 * acessórios de cabeça/rosto (chapeu), itens de costas, mão e pet.
 */

// Acessórios de cabeça/rosto (slot `chapeu`)
export function Acessorio({ slug }: { slug: string }) {
  switch (slug) {
    case "oculos":
      return (
        <g stroke="#231D4E" strokeWidth="5" fill="rgba(120,200,255,.35)">
          <rect x="120" y="128" width="44" height="34" rx="12" />
          <rect x="196" y="128" width="44" height="34" rx="12" />
          <line x1="164" y1="144" x2="196" y2="144" />
        </g>
      );
    case "bone":
      return (
        <g>
          <path d="M92 118 Q100 58 180 54 Q258 58 268 116 Q210 92 180 92 Q120 94 92 118 Z"
                fill="#E8384F" />
          <path d="M92 118 Q60 122 52 138 L120 138 Q108 120 92 118 Z" fill="#C43A54" />
          <circle cx="180" cy="74" r="9" fill="#fff" />
        </g>
      );
    case "coroa":
      return (
        <path d="M118 96 L118 56 L146 82 L180 48 L214 82 L242 56 L242 96 Z"
              fill="#FFC93C" stroke="#E0A414" strokeWidth="5" strokeLinejoin="round" />
      );
    case "fone":
      return (
        <g stroke="#231D4E" fill="#231D4E">
          <path d="M96 150 Q96 60 180 56 Q264 60 264 150" strokeWidth="14" fill="none"
                strokeLinecap="round" />
          <rect x="80" y="132" width="30" height="52" rx="14" />
          <rect x="250" y="132" width="30" height="52" rx="14" />
          <rect x="86" y="142" width="18" height="32" rx="9" fill="#FF5470" stroke="none" />
          <rect x="256" y="142" width="18" height="32" rx="9" fill="#FF5470" stroke="none" />
        </g>
      );
    case "nenhum":
    default:
      return null;
  }
}

// Itens de costas (slot `costas`) — desenhados ATRÁS do corpo
export function CostasH({ slug }: { slug: string }) {
  switch (slug) {
    case "asas":
      return (
        <g className="boneco-asas">
          <g className="asa esq">
            <path d="M150 300 C60 250 8 300 26 380 C100 348 128 380 158 372 Z"
                  fill="rgba(255,255,255,.92)" />
            <path d="M150 320 C86 300 48 330 54 372 C104 356 130 372 158 366 Z"
                  fill="rgba(94,193,255,.55)" />
          </g>
          <g className="asa dir">
            <path d="M210 300 C300 250 352 300 334 380 C260 348 232 380 202 372 Z"
                  fill="rgba(255,255,255,.92)" />
            <path d="M210 320 C274 300 312 330 306 372 C256 356 230 372 202 366 Z"
                  fill="rgba(180,140,255,.55)" />
          </g>
        </g>
      );
    case "mochila":
      return (
        <g>
          <rect x="118" y="250" width="124" height="150" rx="30" fill="#7C6FF0" />
          <rect x="118" y="250" width="124" height="150" rx="30" fill="rgba(0,0,0,.12)" />
          <rect x="146" y="286" width="68" height="52" rx="14" fill="#A78BFA" />
          <line x1="180" y1="250" x2="180" y2="228" stroke="#4EA8FF" strokeWidth="8" strokeLinecap="round" />
          <circle cx="180" cy="222" r="9" fill="#FFC93C" />
        </g>
      );
    case "nenhum":
    default:
      return null;
  }
}

// Item de mão (slot `mao`) — na mão direita erguida (~x=300, y=150)
export function MaoH({ slug }: { slug: string }) {
  if (slug !== "varinha") return null;
  return (
    <g className="boneco-varinha">
      <line x1="300" y1="150" x2="336" y2="82" stroke="#C89B3C" strokeWidth="9" strokeLinecap="round" />
      <path d="M336 60 l7 16 17 2 -13 12 4 17 -15 -9 -15 9 4 -17 -13 -12 17 -2 z"
            fill="#FFC93C" stroke="#E0A414" strokeWidth="3" strokeLinejoin="round" />
      <circle className="boneco-varinha-brilho" cx="341" cy="74" r="26" fill="#FFC93C" opacity=".25" />
    </g>
  );
}

// Pet (slot `pet`) — ao lado do boneco, na base
export function PetH({ slug }: { slug: string }) {
  switch (slug) {
    case "gatinho":
      return (
        <g className="boneco-pet" transform="translate(250 452)">
          <ellipse cx="34" cy="86" rx="30" ry="8" fill="rgba(0,0,0,.14)" />
          <ellipse cx="34" cy="60" rx="30" ry="26" fill="#FF8E3C" />
          <circle cx="34" cy="28" r="24" fill="#FF8E3C" />
          <path d="M14 12 l6 -18 10 14 z M54 12 l-6 -18 -10 14 z" fill="#FF8E3C" />
          <circle cx="26" cy="26" r="4" fill="#231D4E" />
          <circle cx="42" cy="26" r="4" fill="#231D4E" />
          <path d="M28 36 Q34 42 40 36" stroke="#231D4E" strokeWidth="3" fill="none" strokeLinecap="round" />
        </g>
      );
    case "dino":
      return (
        <g className="boneco-pet" transform="translate(246 448)">
          <ellipse cx="40" cy="92" rx="34" ry="8" fill="rgba(0,0,0,.14)" />
          <ellipse cx="40" cy="60" rx="34" ry="30" fill="#2EE6A8" />
          <circle cx="40" cy="26" r="22" fill="#2EE6A8" />
          <path d="M18 10 l8 -12 6 12 z M34 6 l8 -12 6 12 z" fill="#12B8A6" />
          <circle cx="33" cy="24" r="4" fill="#231D4E" />
          <circle cx="47" cy="24" r="4" fill="#231D4E" />
        </g>
      );
    case "estrelinha":
      return (
        <g className="boneco-pet flutua" transform="translate(258 372)">
          <path d="M32 0 l9 20 22 3 -16 15 4 22 -19 -11 -19 11 4 -22 -16 -15 22 -3 z"
                fill="#FFC93C" stroke="#E0A414" strokeWidth="3" strokeLinejoin="round" />
          <circle cx="25" cy="24" r="3.5" fill="#231D4E" />
          <circle cx="39" cy="24" r="3.5" fill="#231D4E" />
        </g>
      );
    case "nenhum":
    default:
      return null;
  }
}
