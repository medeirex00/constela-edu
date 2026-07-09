/**
 * Pet do Cosmo (slot `pet`): um bichinho ao lado do astronauta, na base.
 * Desenhado à direita das pernas (x≈360, y≈470).
 */
export function Pet({ slug }: { slug: string }) {
  switch (slug) {
    case "gatinho":
      return (
        <g className="cosmo-pet" transform="translate(356 452)">
          <ellipse cx="34" cy="86" rx="30" ry="8" fill="rgba(0,0,0,.14)" />
          <ellipse cx="34" cy="60" rx="30" ry="26" fill="#FF8E3C" />
          <circle cx="34" cy="28" r="24" fill="#FF8E3C" />
          <path d="M14 12 l6 -18 10 14 z" fill="#FF8E3C" />
          <path d="M54 12 l-6 -18 -10 14 z" fill="#FF8E3C" />
          <circle cx="26" cy="26" r="4" fill="#231D4E" />
          <circle cx="42" cy="26" r="4" fill="#231D4E" />
          <path d="M28 36 Q34 42 40 36" stroke="#231D4E" strokeWidth="3"
                fill="none" strokeLinecap="round" />
          <path d="M60 60 q22 -6 18 -28" stroke="#FF8E3C" strokeWidth="9"
                fill="none" strokeLinecap="round" className="pet-rabo" />
        </g>
      );

    case "dino":
      return (
        <g className="cosmo-pet" transform="translate(352 448)">
          <ellipse cx="40" cy="92" rx="34" ry="8" fill="rgba(0,0,0,.14)" />
          <ellipse cx="40" cy="60" rx="34" ry="30" fill="#2EE6A8" />
          <circle cx="40" cy="26" r="22" fill="#2EE6A8" />
          <path d="M18 10 l8 -12 6 12 z M34 6 l8 -12 6 12 z" fill="#12B8A6" />
          <circle cx="33" cy="24" r="4" fill="#231D4E" />
          <circle cx="47" cy="24" r="4" fill="#231D4E" />
          <path d="M32 36 Q40 42 48 36" stroke="#231D4E" strokeWidth="3"
                fill="none" strokeLinecap="round" />
        </g>
      );

    case "estrelinha":
      return (
        <g className="cosmo-pet flutua" transform="translate(360 380)">
          <path d="M32 0 l9 20 22 3 -16 15 4 22 -19 -11 -19 11 4 -22 -16 -15 22 -3 z"
                fill="#FFC93C" stroke="#E0A414" strokeWidth="3" strokeLinejoin="round" />
          <circle cx="25" cy="24" r="3.5" fill="#231D4E" />
          <circle cx="39" cy="24" r="3.5" fill="#231D4E" />
          <path d="M26 32 Q32 37 38 32" stroke="#231D4E" strokeWidth="2.6"
                fill="none" strokeLinecap="round" />
        </g>
      );

    case "nenhum":
    default:
      return null;
  }
}
