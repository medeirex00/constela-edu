/**
 * Rostos do Cosmo (slot `rosto` do avatar). Desenhados dentro do visor
 * (elipse cx=210 cy=216). Variantes com pupila usam a classe `cosmo-pupila`
 * para os olhos seguirem o ponteiro; as demais (olhos fechados) não.
 */
const OLHO_ESQ = 176;
const OLHO_DIR = 244;

function OlhosComPupila({ r = 7 }: { r?: number }) {
  return (
    <>
      <g className="cosmo-olho">
        <ellipse cx={OLHO_ESQ} cy="204" rx="15" ry="22" fill="#fff" />
        <circle className="cosmo-pupila" cx={OLHO_ESQ} cy="208" r={r} fill="#221C46" />
      </g>
      <g className="cosmo-olho">
        <ellipse cx={OLHO_DIR} cy="204" rx="15" ry="22" fill="#fff" />
        <circle className="cosmo-pupila" cx={OLHO_DIR} cy="208" r={r} fill="#221C46" />
      </g>
    </>
  );
}

export function Rosto({ slug }: { slug: string }) {
  switch (slug) {
    case "sorrisao":
      return (
        <>
          <OlhosComPupila />
          <path d="M180 244 Q210 300 240 244 Z" fill="#fff" />
          <path d="M196 268 Q210 288 224 268 Z" fill="#FF7DA0" />
        </>
      );

    case "fofo":
      return (
        <>
          <path d="M162 210 Q176 190 190 210" stroke="#fff" strokeWidth="9"
                strokeLinecap="round" fill="none" />
          <path d="M230 210 Q244 190 258 210" stroke="#fff" strokeWidth="9"
                strokeLinecap="round" fill="none" />
          <path d="M188 250 Q210 268 232 250" stroke="#fff" strokeWidth="8"
                strokeLinecap="round" fill="none" />
          <circle cx="150" cy="238" r="12" fill="#FF7DA0" opacity=".6" />
          <circle cx="270" cy="238" r="12" fill="#FF7DA0" opacity=".6" />
        </>
      );

    case "surpreso":
      return (
        <>
          <circle cx={OLHO_ESQ} cy="206" r="17" fill="#fff" />
          <circle className="cosmo-pupila" cx={OLHO_ESQ} cy="206" r="8" fill="#221C46" />
          <circle cx={OLHO_DIR} cy="206" r="17" fill="#fff" />
          <circle className="cosmo-pupila" cx={OLHO_DIR} cy="206" r="8" fill="#221C46" />
          <ellipse cx="210" cy="256" rx="14" ry="17" fill="#fff" />
        </>
      );

    case "oculos":
      return (
        <>
          <OlhosComPupila r={6} />
          <g stroke="#221C46" strokeWidth="6" fill="rgba(255,255,255,.18)">
            <rect x="150" y="188" width="52" height="40" rx="14" />
            <rect x="218" y="188" width="52" height="40" rx="14" />
            <line x1="202" y1="206" x2="218" y2="206" />
          </g>
          <path d="M186 252 Q210 270 234 252" stroke="#fff" strokeWidth="8"
                strokeLinecap="round" fill="none" />
        </>
      );

    case "heroi":
      return (
        <>
          <OlhosComPupila />
          <path d="M150 182 L200 196" stroke="#221C46" strokeWidth="8"
                strokeLinecap="round" />
          <path d="M270 182 L220 196" stroke="#221C46" strokeWidth="8"
                strokeLinecap="round" />
          <path d="M188 250 Q212 266 236 246" stroke="#fff" strokeWidth="8"
                strokeLinecap="round" fill="none" />
          <text x="150" y="250" fontSize="26" fill="#FFC93C">★</text>
        </>
      );

    case "sorriso":
    default:
      return (
        <>
          <OlhosComPupila />
          <path d="M186 248 Q210 268 234 248" stroke="#fff" strokeWidth="8"
                strokeLinecap="round" fill="none" />
        </>
      );
  }
}
