/**
 * Fundo "noite Constela" — céu profundo azul da marca com constelação, nebulosas,
 * planetas, lua, satélite lento e estrelas cadentes (tudo sutil, atrás do conteúdo).
 * Compartilhado pelo Painel Público da escola e pela Vitrine pública da Secretaria.
 *
 * As animações (painel-estrela, painel-astro, painel-satelite, painel-cadente…)
 * vivem no CSS global e valem para qualquer tela que use este fundo. O céu
 * (cintilar, cadentes e satélite) continua vivo mesmo com "reduzir movimento" —
 * pedido do dono, ver o bloco prefers-reduced-motion do index.css.
 *
 * É pura decoração: `aria-hidden` no conjunto (o leitor de tela não lê 70
 * círculos) e nada brilhante atrás do texto — os astros ficam nas bordas e a
 * lua/Saturno só aparecem onde há margem livre. Cada tela tem seu mapa de áreas
 * livres (`variante`): na vitrine os cantos do cabeçalho (título centralizado);
 * no telão os cantos do cabeçalho têm logo, relógio e botões, então lua,
 * Saturno e as estrelas brilhantes de dentro ficam nas margens laterais do
 * palco, só nas telas largas em que o pódio não chega até elas. Tamanhos em
 * rem: na TV 4K (escala do <html> em `tela-publica`) a decoração cresce na
 * mesma proporção do conteúdo.
 */
import { useLayoutEffect, useMemo } from "react";

// Metais celebrativos do pódio (ouro/prata/bronze da marca).
export const OURO = "#F5B942";
export const PRATA = "#CBD5E9";
export const BRONZE = "#E0955A";
export const MEDALHAS: Record<number, { emoji: string; cor: string }> = {
  1: { emoji: "🥇", cor: OURO },
  2: { emoji: "🥈", cor: PRATA },
  3: { emoji: "🥉", cor: BRONZE },
};

/**
 * Telas públicas (vitrine da rede e telão da escola): marca o <html> com a
 * classe `tela-publica` enquanto a tela está montada. O CSS dessa classe
 * (index.css) pinta o fundo escuro (sem "flash" claro nem sobra branca ao
 * rolar), deixa o foco visível no tema noite e aplica a escala tipográfica
 * fluida acima de 1920 px — na TV 4K todo `rem` cresce junto.
 */
export function useTelaPublica(): void {
  useLayoutEffect(() => {
    const html = document.documentElement;
    html.classList.add("tela-publica");
    return () => html.classList.remove("tela-publica");
  }, []);
}

/** Céu estrelado determinístico (posições estáveis entre renders). */
const CORES_ESTRELA = ["#ffffff", "#ffffff", "#ffffff", "#dbe6ff", "#cfe0ff", "#ffe9c7"];
function useEstrelas(qtd: number) {
  return useMemo(() => {
    let semente = 987654321;
    const rnd = () => (semente = (semente * 1103515245 + 12345) & 0x7fffffff) / 0x7fffffff;
    return Array.from({ length: qtd }, () => ({
      x: rnd() * 100,
      y: rnd() * 100,
      r: 0.5 + rnd() * 1.7,
      atraso: (rnd() * 4).toFixed(2),
      cor: CORES_ESTRELA[Math.floor(rnd() * CORES_ESTRELA.length)],
    }));
  }, [qtd]);
}

// Estrelas brilhantes curadas nas BORDAS (não competem com o conteúdo central).
// As da faixa externa (x < 2% ou > 98%) ficam fora do bloco de conteúdo em
// qualquer largura e em qualquer tela; as de dentro (`largas`) só aparecem em
// telas largas, cada variante no seu lugar livre. Nenhuma no centro da tela.
// `size` em px a 16 px de rem (vira rem: cresce junto no 4K).
const ASTROS_BORDA = [
  { top: "46%", left: "1.2%", size: 4, d: "1.4s" },
  { top: "78%", left: "0.8%", size: 4.5, d: "0.7s" },
  { top: "36%", left: "98.6%", size: 3.5, d: "1.8s" },
  { top: "88%", left: "98.9%", size: 4, d: "3.2s" },
];

type Variante = "vitrine" | "telao";
interface Posicao { top: string; left?: string; right?: string }

/**
 * Mapa das áreas livres de cada tela (as classes ficam LITERAIS no código para
 * o Tailwind gerá-las).
 * - vitrine: cabeçalho centralizado → cantos de cima livres a partir de `lg`.
 * - telão: cantos de cima ocupados (logo + nome; relógio + Pausar/Modo TV) →
 *   margens laterais do palco, livres só a partir de 1800 px (abaixo disso o
 *   pódio, de até 88rem, chega perto da borda). Satélite na altura de sempre
 *   do telão (36%).
 */
const MAPA: Record<Variante, {
  largas: string;
  astros: (Posicao & { size: number; d: string })[];
  saturno: Posicao;
  lua: Posicao;
  satelite: Posicao;
}> = {
  vitrine: {
    largas: "hidden lg:block",
    astros: [
      { top: "5%", left: "4%", size: 5, d: "0s" },
      { top: "15%", left: "11%", size: 3.5, d: "2.1s" },
      { top: "4%", left: "88%", size: 5, d: "1.1s" },
      { top: "17%", left: "95%", size: 4, d: "2.6s" },
    ],
    saturno: { top: "3.5%", right: "3%" },
    lua: { top: "4%", left: "2.5%" },
    satelite: { top: "14%", left: "1.5%" },
  },
  telao: {
    largas: "hidden min-[1800px]:block",
    astros: [
      { top: "30%", left: "3%", size: 5, d: "0s" },
      { top: "52%", left: "8%", size: 3.5, d: "2.1s" },
      { top: "26%", left: "94%", size: 4, d: "1.1s" },
      { top: "70%", left: "93%", size: 5, d: "2.6s" },
    ],
    saturno: { top: "40%", right: "4.5%" },
    lua: { top: "62%", left: "5%" },
    satelite: { top: "36%", left: "4%" },
  },
};

/** Fundo "espaço" completo. `cor` é a cor de acento (nebulosa/satélite);
 *  `variante` escolhe o mapa de áreas livres da tela (ver MAPA). */
export function FundoConstela({ cor, variante = "vitrine" }: { cor: string; variante?: Variante }) {
  const estrelas = useEstrelas(70);
  const mapa = MAPA[variante];
  const astros = [
    ...ASTROS_BORDA.map((a) => ({ ...a, classe: "" })),
    ...mapa.astros.map((a) => ({ ...a, classe: mapa.largas })),
  ];
  return (
    <div aria-hidden="true" data-fundo-constela
      className="pointer-events-none absolute inset-0 overflow-hidden">
      <div className="absolute inset-0" style={{
        background: "radial-gradient(120% 80% at 50% -10%, #26365F 0%, #1B2A4A 42%, #0F1626 100%)",
      }} />
      {/* Nebulosas suaves — profundidade cósmica. */}
      <div className="absolute -left-40 top-1/4 h-[46rem] w-[46rem] rounded-full opacity-30 blur-3xl"
        style={{ background: `radial-gradient(circle, ${cor}, transparent 60%)` }} />
      <div className="absolute -right-40 bottom-0 h-[42rem] w-[42rem] rounded-full opacity-20 blur-3xl"
        style={{ background: `radial-gradient(circle, ${OURO}, transparent 62%)` }} />
      <div className="absolute left-1/4 top-1/3 h-[34rem] w-[34rem] rounded-full opacity-[0.16] blur-3xl"
        style={{ background: "radial-gradient(circle, #7c5cff, transparent 60%)" }} />
      <div className="absolute right-1/4 top-2 h-[26rem] w-[26rem] rounded-full opacity-[0.12] blur-3xl"
        style={{ background: "radial-gradient(circle, #2fb6c9, transparent 62%)" }} />

      {/* Campo de estrelas pequenas: pontos REDONDOS em qualquer proporção de
          tela (o SVG esticado com preserveAspectRatio="none" virava "traços"
          na TV) e em rem, para crescer junto no 4K. */}
      {estrelas.map((e, i) => (
        <span key={i} className="painel-estrela absolute rounded-full"
          style={{
            left: `${e.x}%`, top: `${e.y}%`, width: `${e.r * 0.14}rem`, height: `${e.r * 0.14}rem`,
            background: e.cor, animationDelay: `${e.atraso}s`,
          }} />
      ))}

      {/* Estrelas brilhantes (cintilam) — só nas bordas. */}
      {astros.map((a, i) => (
        <span key={i} data-astro aria-hidden
          className={`painel-astro painel-estrela ${a.classe}`}
          style={{ top: a.top, left: a.left, width: `${a.size / 16}rem`, height: `${a.size / 16}rem`,
            animationDelay: a.d }} />
      ))}

      {/* Planeta grande no canto inferior-esquerdo (escuro: não tira contraste). */}
      <div className="absolute" aria-hidden style={{
        bottom: "-7.5rem", left: "-5.625rem", width: "21.25rem", height: "21.25rem", borderRadius: "50%",
        background: "radial-gradient(circle at 34% 30%, #3d4d80 0%, #26325a 46%, #131b32 80%)",
        boxShadow: "inset -22px -16px 46px rgba(0,0,0,0.45)", opacity: 0.5,
      }} />

      {/* Planeta com anel (Saturno) — só em telas largas, na área livre da variante. */}
      <div data-astro className={`absolute ${mapa.largas}`} aria-hidden
        style={{ ...mapa.saturno, width: "3.875rem", height: "3.875rem", opacity: 0.6 }}>
        <div style={{ width: "100%", height: "100%", borderRadius: "50%",
          background: "radial-gradient(circle at 36% 32%, #d8b27a 0%, #a9793f 52%, #61421f 84%)" }} />
        <div style={{ position: "absolute", left: "50%", top: "50%", width: "7.5rem", height: "7.5rem",
          transform: "translate(-50%,-50%) rotate(-22deg) scaleY(0.32)",
          borderRadius: "50%", border: "3px solid rgba(232,214,180,0.5)" }} />
      </div>

      {/* Lua discreta (clara) — só em telas largas, na área livre: nunca atrás do texto. */}
      <div data-astro className={`absolute ${mapa.largas}`} aria-hidden style={{
        ...mapa.lua, width: "2.5rem", height: "2.5rem", borderRadius: "50%",
        background: "radial-gradient(circle at 36% 34%, #eef1f8 0%, #c6cde0 58%, #9aa2ba 100%)",
        boxShadow: "0 0 16px rgba(210,216,235,0.28)", opacity: 0.7,
      }} />

      {/* Satélite cruzando o céu devagar (passagem rápida e translúcida; o halo do
          texto da vitrine segura a leitura se ele cruzar uma letra). */}
      <svg className="painel-satelite" aria-hidden="true" focusable="false" viewBox="0 0 44 20"
        style={{ ...mapa.satelite, width: "1.875rem", height: "0.875rem" }}>
        <line x1="22" y1="10" x2="22" y2="1" stroke="#aeb8d4" strokeWidth="1" />
        <circle cx="22" cy="1.5" r="1.4" fill="#e6ebf7" />
        <rect x="18" y="6" width="8" height="8" rx="1.2" fill="#d3dae9" />
        <rect x="3" y="5.5" width="12" height="9" fill="#8fa2d6" stroke="#5b6ea6" strokeWidth="0.6" />
        <rect x="29" y="5.5" width="12" height="9" fill="#8fa2d6" stroke="#5b6ea6" strokeWidth="0.6" />
      </svg>

      {/* Estrelas cadentes. */}
      <span className="painel-cadente" style={{ top: "8%", left: "80%", animationDelay: "1s", animationDuration: "8s" }} aria-hidden />
      <span className="painel-cadente" style={{ top: "18%", left: "94%", animationDelay: "4s", animationDuration: "9s" }} aria-hidden />
      <span className="painel-cadente" style={{ top: "5%", left: "55%", animationDelay: "7s", animationDuration: "11s" }} aria-hidden />
      <span className="painel-cadente" style={{ top: "30%", left: "72%", animationDelay: "10s", animationDuration: "10s" }} aria-hidden />
      <span className="painel-cadente" style={{ top: "13%", left: "38%", animationDelay: "13.5s", animationDuration: "12s" }} aria-hidden />
    </div>
  );
}
