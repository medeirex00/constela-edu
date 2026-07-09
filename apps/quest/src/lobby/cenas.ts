/**
 * Cenários temáticos de fundo por matéria (SVG), portados do protótipo
 * constela-play-v7 (SCENES). As classes .sk/.fl/.f1/.f2/.f3/.spin/.rise são
 * estilizadas em cena.css, escopadas sob `.cena`. Cor via var(--scene-ink).
 */
const linhas = (n: number, f: (i: number) => string) =>
  Array.from({ length: n }, (_, i) => f(i)).join("");

export const CENAS: Record<string, string> = {
  lobby: `<svg viewBox="0 0 1440 900" preserveAspectRatio="xMidYMax slice">
    <g class="f1"><circle cx="1170" cy="190" r="80" fill="none" stroke="var(--scene-ink)" stroke-width="10" opacity=".7"/>
      <ellipse cx="1170" cy="190" rx="140" ry="34" fill="none" stroke="var(--scene-ink)" stroke-width="9" transform="rotate(-18 1170 190)" opacity=".8"/></g>
    <g class="f2" opacity=".8"><circle cx="240" cy="200" r="42" class="fl"/><circle cx="300" cy="188" r="56" class="fl"/><circle cx="366" cy="204" r="40" class="fl"/><rect x="216" y="200" width="176" height="44" rx="22" class="fl"/></g>
    <g class="f3" opacity=".6"><circle cx="760" cy="120" r="30" class="fl"/><circle cx="806" cy="112" r="40" class="fl"/><circle cx="852" cy="124" r="28" class="fl"/><rect x="742" y="122" width="136" height="32" rx="16" class="fl"/></g>
  </svg>`,

  matematica: `<svg viewBox="0 0 1440 900" preserveAspectRatio="xMidYMax slice">
    <defs><pattern id="gridm" width="72" height="72" patternUnits="userSpaceOnUse">
      <path d="M72 0H0V72" fill="none" stroke="var(--scene-ink)" stroke-width="1.5" opacity=".22"/></pattern></defs>
    <rect width="1440" height="900" fill="url(#gridm)"/>
    <g class="f1"><circle cx="1150" cy="230" r="95" class="sk" stroke-width="12" stroke-dasharray="26 20"/></g>
    <g class="f2"><path d="M170 320 l95 -160 95 160 z" class="sk" stroke-width="12"/></g>
    <g class="f3"><rect x="1080" y="520" width="130" height="130" rx="18" class="sk" stroke-width="12" transform="rotate(14 1145 585)"/></g>
    <text x="420" y="260" font-size="150" class="f2" opacity=".85">π</text>
    <text x="900" y="430" font-size="120" class="f1" opacity=".8">√</text>
    <text x="240" y="560" font-size="100" class="f3" opacity=".75">÷</text>
  </svg>`,

  portugues: `<svg viewBox="0 0 1440 900" preserveAspectRatio="xMidYMax slice">
    <g opacity=".5">${linhas(7, (i) => `<line x1="0" y1="${430 + i * 66}" x2="1440" y2="${430 + i * 66}" stroke="var(--scene-ink)" stroke-width="2.5"/>`)}
      <line x1="120" y1="400" x2="120" y2="880" stroke="var(--scene-ink)" stroke-width="4" opacity=".8"/></g>
    <text x="220" y="300" font-size="190" class="f1" opacity=".9">A</text>
    <text x="1040" y="260" font-size="150" class="f2" opacity=".85">?</text>
    <text x="1240" y="470" font-size="130" class="f3" opacity=".8">!</text>
    <g class="f2" transform="rotate(32 300 660)"><rect x="240" y="640" width="330" height="52" rx="14" class="fl"/>
      <path d="M570 640 l64 26 -64 26z" class="fl"/></g>
  </svg>`,

  ingles: `<svg viewBox="0 0 1440 900" preserveAspectRatio="xMidYMax slice">
    <g opacity=".85">
      <rect x="60" y="620" width="90" height="260" class="fl" opacity=".55"/>
      <rect x="170" y="560" width="110" height="320" class="fl" opacity=".7"/>
      <rect x="300" y="640" width="80" height="240" class="fl" opacity=".5"/>
      <rect x="1240" y="600" width="100" height="280" class="fl" opacity=".6"/>
      <rect x="1130" y="540" width="90" height="340" class="fl" opacity=".75"/>
      <rect x="1150" y="440" width="50" height="110" class="fl" opacity=".9"/>
      <path d="M1147 420 l28 -46 28 46z" class="fl"/></g>
    <g class="f1"><rect x="330" y="150" width="330" height="130" rx="34" class="fl" opacity=".95"/>
      <path d="M410 280 l-24 54 66 -54z" class="fl" opacity=".95"/>
      <text x="495" y="235" font-size="62" text-anchor="middle" fill="rgba(0,0,0,.45)">Hello!</text></g>
    <g class="f3"><rect x="880" y="120" width="230" height="104" rx="30" class="fl" opacity=".8"/>
      <path d="M1040 224 l30 44 -66 -44z" class="fl" opacity=".8"/>
      <text x="995" y="190" font-size="52" text-anchor="middle" fill="rgba(0,0,0,.4)">Yes!</text></g>
  </svg>`,

  geografia: `<svg viewBox="0 0 1440 900" preserveAspectRatio="xMidYMax slice">
    <circle cx="1120" cy="230" r="90" class="fl f1" opacity=".9"/>
    <g opacity=".55"><path d="M-20 880 L260 560 L520 880 Z" class="fl"/><path d="M340 880 L640 500 L960 880 Z" class="fl"/><path d="M840 880 L1120 590 L1420 880 Z" class="fl"/></g>
    <g opacity=".8"><path d="M600 528 l40 -52 40 52" class="sk" stroke-width="9"/><path d="M700 545 l30 -40 30 40" class="sk" stroke-width="8"/></g>
    <g class="spin" opacity=".85">
      <circle cx="220" cy="640" r="98" class="sk" stroke-width="9"/>
      <path d="M220 542 V738 M122 640 H318 M152 572 L288 708 M288 572 L152 708" class="sk" stroke-width="7"/>
      <path d="M220 542 l-16 44 h32 z" class="fl"/></g>
    <path class="sk f3" stroke-width="8" d="M540 300 q22 -30 44 0 q22 30 44 0" opacity=".8"/>
    <path class="sk f1" stroke-width="8" d="M760 340 q20 -26 40 0 q20 26 40 0" opacity=".7"/>
  </svg>`,

  historia: `<svg viewBox="0 0 1440 900" preserveAspectRatio="xMidYMax slice">
    <circle cx="720" cy="640" r="130" class="fl f1" opacity=".55"/>
    <g opacity=".7"><path d="M-30 880 L300 480 L630 880 Z" class="fl"/><path d="M430 880 L700 580 L970 880 Z" class="fl" opacity=".8"/></g>
    <g opacity=".9"><rect x="1010" y="560" width="360" height="34" rx="8" class="fl"/>
      <path d="M1000 560 l190 -84 190 84z" class="fl"/>
      ${linhas(5, (i) => `<rect x="${1036 + i * 66}" y="600" width="34" height="200" rx="8" class="fl" opacity=".85"/>`)}
      <rect x="1010" y="800" width="360" height="36" rx="8" class="fl"/></g>
    <g class="f2" opacity=".9"><path d="M170 220 h120 M170 380 h120 M180 220 L280 380 M280 220 L180 380" class="sk" stroke-width="10"/></g>
  </svg>`,

  ciencias: `<svg viewBox="0 0 1440 900" preserveAspectRatio="xMidYMax slice">
    <g class="f1"><circle cx="1080" cy="250" r="26" class="fl"/>
      <g class="spin"><ellipse cx="1080" cy="250" rx="150" ry="56" class="sk" stroke-width="9"/></g>
      <g class="spin-r"><ellipse cx="1080" cy="250" rx="150" ry="56" class="sk" stroke-width="9" transform="rotate(60 1080 250)"/></g>
      <g class="spin"><ellipse cx="1080" cy="250" rx="150" ry="56" class="sk" stroke-width="9" transform="rotate(-60 1080 250)"/></g>
      <circle cx="1224" cy="222" r="12" class="fl"/><circle cx="948" cy="290" r="12" class="fl"/></g>
    <g opacity=".9"><path d="M240 560 h90 v90 l70 150 q10 40 -34 40 h-162 q-44 0 -34 -40 l70 -150z" class="sk" stroke-width="11"/>
      <path d="M212 720 h146 l32 68 q6 24 -20 24 h-170 q-26 0 -20 -24z" class="fl" opacity=".55"/></g>
    <circle cx="560" cy="380" r="12" class="fl rise"/>
    <circle cx="300" cy="430" r="9" class="fl rise" style="animation-delay:-5s"/>
    <circle cx="640" cy="500" r="7" class="fl rise" style="animation-delay:-9s"/>
    <text x="760" y="220" font-size="76" class="f2" opacity=".85">H₂O</text>
  </svg>`,

  outros: `<svg viewBox="0 0 1440 900" preserveAspectRatio="xMidYMax slice">
    <g class="f1" opacity=".9"><path d="M200 200 h90 a30 30 0 1 1 0 60 v60 h-60 a30 30 0 1 0 -60 0 h-60 v-120 z" class="sk" stroke-width="11"/></g>
    <g class="f2" opacity=".9"><circle cx="1120" cy="240" r="16" class="fl"/><rect x="1130" y="120" width="12" height="120" rx="6" class="fl"/>
      <circle cx="1210" cy="220" r="16" class="fl"/><rect x="1220" y="100" width="12" height="120" rx="6" class="fl"/>
      <rect x="1130" y="100" width="102" height="14" rx="7" class="fl" transform="rotate(-6 1180 107)"/></g>
    <g class="f3" opacity=".9"><rect x="540" y="620" width="300" height="150" rx="70" class="sk" stroke-width="11"/>
      <circle cx="760" cy="680" r="10" class="fl"/><circle cx="800" cy="712" r="10" class="fl"/></g>
    ${linhas(10, (i) => `<rect x="${80 + i * 130}" y="${140 + (i % 4) * 80}" width="16" height="30" rx="5" class="fl f${(i % 3) + 1}" opacity=".5" transform="rotate(${(i * 31) % 80 - 40} ${88 + i * 130} ${155 + (i % 4) * 80})"/>`)}
  </svg>`,
};
