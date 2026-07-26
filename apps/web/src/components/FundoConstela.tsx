/**
 * Fundo "noite Constela" — céu profundo azul da marca com constelação, nebulosas,
 * planetas, lua, satélite lento e estrelas cadentes (tudo sutil, atrás do conteúdo).
 * Compartilhado pelo Painel Público da escola e pela Vitrine pública da Secretaria.
 *
 * As animações (painel-estrela, painel-astro, painel-satelite, painel-cadente…)
 * vivem no CSS global e valem para qualquer tela que use este fundo.
 */
import { useMemo } from "react";

// Metais celebrativos do pódio (ouro/prata/bronze da marca).
export const OURO = "#F5B942";
export const PRATA = "#CBD5E9";
export const BRONZE = "#E0955A";
export const MEDALHAS: Record<number, { emoji: string; cor: string }> = {
  1: { emoji: "🥇", cor: OURO },
  2: { emoji: "🥈", cor: PRATA },
  3: { emoji: "🥉", cor: BRONZE },
};

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

// Estrelas brilhantes curadas nas bordas (não competem com o conteúdo central).
const ASTROS = [
  { top: "13%", left: "7%", size: 5, d: "0s" },
  { top: "72%", left: "5%", size: 4, d: "1.4s" },
  { top: "26%", left: "20%", size: 3.5, d: "2.1s" },
  { top: "84%", left: "18%", size: 4.5, d: "0.7s" },
  { top: "15%", left: "90%", size: 5, d: "1.1s" },
  { top: "58%", left: "95%", size: 4, d: "2.6s" },
  { top: "86%", left: "86%", size: 3.5, d: "1.8s" },
  { top: "40%", left: "49%", size: 3, d: "3.2s" },
];

/** Fundo "espaço" completo. `cor` é a cor de acento (nebulosa/satélite). */
export function FundoConstela({ cor }: { cor: string }) {
  const estrelas = useEstrelas(70);
  return (
    <div className="pointer-events-none absolute inset-0 overflow-hidden">
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

      {/* Campo de estrelas pequenas. */}
      <svg className="absolute inset-0 h-full w-full" preserveAspectRatio="none" viewBox="0 0 100 100">
        {estrelas.map((e, i) => (
          <circle key={i} cx={e.x} cy={e.y} r={e.r * 0.12} fill={e.cor}
            className="painel-estrela" style={{ animationDelay: `${e.atraso}s` }} />
        ))}
      </svg>

      {/* Estrelas brilhantes (cintilam). */}
      {ASTROS.map((a, i) => (
        <span key={i} className="painel-astro painel-estrela" aria-hidden
          style={{ top: a.top, left: a.left, width: a.size, height: a.size, animationDelay: a.d }} />
      ))}

      {/* Planeta grande no canto inferior-esquerdo. */}
      <div className="absolute" aria-hidden style={{
        bottom: "-120px", left: "-90px", width: "340px", height: "340px", borderRadius: "50%",
        background: "radial-gradient(circle at 34% 30%, #3d4d80 0%, #26325a 46%, #131b32 80%)",
        boxShadow: "inset -22px -16px 46px rgba(0,0,0,0.45)", opacity: 0.5,
      }} />

      {/* Planeta com anel (Saturno) no canto superior-direito. */}
      <div className="absolute" aria-hidden style={{ top: "8%", right: "6%", width: "62px", height: "62px", opacity: 0.6 }}>
        <div style={{ width: "100%", height: "100%", borderRadius: "50%",
          background: "radial-gradient(circle at 36% 32%, #d8b27a 0%, #a9793f 52%, #61421f 84%)" }} />
        <div style={{ position: "absolute", left: "50%", top: "50%", width: "120px", height: "120px",
          transform: "translate(-50%,-50%) rotate(-22deg) scaleY(0.32)",
          borderRadius: "50%", border: "3px solid rgba(232,214,180,0.5)" }} />
      </div>

      {/* Lua discreta. */}
      <div className="absolute" aria-hidden style={{
        top: "18%", left: "12%", width: "40px", height: "40px", borderRadius: "50%",
        background: "radial-gradient(circle at 36% 34%, #eef1f8 0%, #c6cde0 58%, #9aa2ba 100%)",
        boxShadow: "0 0 16px rgba(210,216,235,0.28)", opacity: 0.7,
      }} />

      {/* Satélite cruzando o céu devagar. */}
      <svg className="painel-satelite" aria-hidden viewBox="0 0 44 20"
        style={{ top: "36%", left: "4%", width: "30px", height: "14px" }}>
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
