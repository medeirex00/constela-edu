/**
 * Cabelos do boneco (slot `cabelo`) — estilo + cor embutidos no preset.
 * Renderizados em duas camadas: `tras` (atrás da cabeça, p/ cabelos longos)
 * e `frente` (sobre o topo da cabeça). Cabeça: círculo cx=180 cy=140 r=92.
 */
export const CABELO_COR: Record<string, string> = {
  espetado_azul: "#3D7BFF",
  espetado_preto: "#2B2B2B",
  curto_castanho: "#6B3F1D",
  longo_loiro: "#F4C430",
  cacheado_preto: "#241C2E",
  chanel_rosa: "#E24AA0",
  moicano_vermelho: "#E8422C",
  careca: "transparent",
};

export function cabeloTras(slug: string) {
  const cor = CABELO_COR[slug];
  if (slug === "longo_loiro") {
    return (
      <g>
        <path d="M96 120 C70 190 72 270 96 320 L140 320 C120 250 122 180 132 120 Z" fill={cor} />
        <path d="M264 120 C290 190 288 270 264 320 L220 320 C240 250 238 180 228 120 Z" fill={cor} />
      </g>
    );
  }
  if (slug === "chanel_rosa") {
    return (
      <g>
        <path d="M92 120 C74 175 78 220 100 246 L130 246 C116 200 116 160 126 120 Z" fill={cor} />
        <path d="M268 120 C286 175 282 220 260 246 L230 246 C244 200 244 160 234 120 Z" fill={cor} />
      </g>
    );
  }
  return null;
}

export function cabeloFrente(slug: string) {
  const cor = CABELO_COR[slug];
  switch (slug) {
    case "careca":
      return null;

    case "espetado_azul":
    case "espetado_preto":
      return (
        <path
          d="M96 128 L108 70 L134 104 L158 58 L182 100 L206 56 L230 104 L256 70 L266 128
             Q210 96 180 96 Q150 96 96 128 Z"
          fill={cor}
        />
      );

    case "cacheado_preto":
      return (
        <g fill={cor}>
          <path d="M96 132 Q92 78 138 74 Q150 52 180 56 Q214 50 226 76 Q272 76 268 132
                   Q244 100 180 98 Q120 100 96 132 Z" />
          <circle cx="110" cy="104" r="20" />
          <circle cx="150" cy="82" r="20" />
          <circle cx="196" cy="80" r="20" />
          <circle cx="238" cy="98" r="20" />
          <circle cx="262" cy="118" r="16" />
        </g>
      );

    case "chanel_rosa":
      return (
        <path d="M92 128 Q92 60 180 54 Q268 60 268 128 Q244 92 210 96 L206 74 L176 96 L150 76
                 L146 98 Q116 96 92 128 Z" fill={cor} />
      );

    case "moicano_vermelho":
      return (
        <path d="M156 100 L162 44 L180 84 L198 44 L204 100 Q180 88 156 100 Z" fill={cor} />
      );

    case "longo_loiro":
      return (
        <path d="M94 130 Q96 58 180 52 Q264 58 266 130 Q244 96 210 98 L204 72 L176 98 L150 74
                 L144 100 Q116 98 94 130 Z" fill={cor} />
      );

    case "curto_castanho":
    default:
      return (
        <path d="M96 132 Q102 60 180 54 Q258 60 264 132 Q240 98 180 96 Q120 98 96 132 Z"
              fill={cor} />
      );
  }
}
