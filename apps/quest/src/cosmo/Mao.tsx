/**
 * Item de mão do Cosmo (slot `mao`): a varinha estelar, segurada na mão
 * direita erguida (mão em cx≈394, cy≈120).
 */
export function Mao({ slug }: { slug: string }) {
  switch (slug) {
    case "varinha":
      return (
        <g className="cosmo-varinha">
          <line x1="394" y1="120" x2="430" y2="52" stroke="#C89B3C"
                strokeWidth="9" strokeLinecap="round" />
          <path d="M430 30 l7 16 17 2 -13 12 4 17 -15 -9 -15 9 4 -17 -13 -12 17 -2 z"
                fill="#FFC93C" stroke="#E0A414" strokeWidth="3"
                strokeLinejoin="round" />
          <circle className="varinha-brilho" cx="435" cy="44" r="26"
                  fill="#FFC93C" opacity=".25" />
        </g>
      );

    case "nenhum":
    default:
      return null;
  }
}
