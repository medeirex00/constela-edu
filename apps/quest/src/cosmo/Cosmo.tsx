/**
 * Cosmo — o mascote vivo e CUSTOMIZÁVEL (avatar do vestiário).
 *
 * - Idle: flutua, gingado, pisca, acena, olhos seguem o ponteiro.
 * - `fisica`: tocar no corpo dá uma CUTUCADA — mola de física (corpo, braços,
 *   pernas e olhos balançam juntos como se levasse cócegas). SEM falas.
 * - Aparência dirigida pelo avatar: cor do traje, rosto e chapéu.
 *
 * A mola é integrada num wrapper próprio (`.cosmo-fisica`), separado dos
 * grupos que já têm animação CSS (float/sway/wave), para não conflitar.
 */
import { useCallback, useEffect, useRef } from "react";

import "./cosmo.css";
import { tocar } from "../audio/audio";
import { Rosto } from "./Rosto";
import { Chapeu } from "./Chapeu";

interface CosmoProps {
  cor?: string;
  rosto?: string;
  chapeu?: string;
  /** Olhos seguem o ponteiro + agenda de piscar/acenar (padrão: sim). */
  vivo?: boolean;
  /** Tocar no corpo dá cócegas com física de mola (só no lobby). */
  fisica?: boolean;
  altura?: string;
  aoClicar?: () => void;
}

export function Cosmo({
  cor, rosto = "sorriso", chapeu = "nenhum",
  vivo = true, fisica = false, altura = "60vh", aoClicar,
}: CosmoProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const molaRef = useRef<SVGGElement>(null);
  const alvoOlhar = useRef({ x: 0, y: 0 });
  const olhar = useRef({ x: 0, y: 0 });
  const ultimoPonteiro = useRef(0);
  const quadroOlhos = useRef(0);
  const olhosRodando = useRef(false);
  const pupilas = useRef<SVGCircleElement[]>([]);

  // Física de mola (cutucada) — lean (graus) + squash (escala vertical)
  const molaEstado = useRef({ lean: 0, leanV: 0, squash: 0, squashV: 0 });
  const quadroMola = useRef(0);
  const molaRodando = useRef(false);

  const acenar = useCallback(() => {
    const braco = svgRef.current?.querySelector(".cosmo-bracoR");
    if (!braco) return;
    braco.classList.remove("acenando");
    void (braco as SVGGElement).getBoundingClientRect();
    braco.classList.add("acenando");
    window.setTimeout(() => braco.classList.remove("acenando"), 1900);
  }, []);

  const piscar = useCallback(() => {
    svgRef.current?.querySelectorAll(".cosmo-olho").forEach((olho) => {
      olho.classList.remove("piscando");
      void (olho as SVGGElement).getBoundingClientRect();
      olho.classList.add("piscando");
    });
  }, []);

  // --- Física de mola --------------------------------------------------
  const passoMola = useCallback(() => {
    const f = molaEstado.current;
    const k = 180, c = 11, dt = 1 / 60;
    f.leanV += (-k * f.lean - c * f.leanV) * dt;
    f.lean += f.leanV * dt;
    f.squashV += (-k * f.squash - c * f.squashV) * dt;
    f.squash += f.squashV * dt;

    const el = molaRef.current;
    if (el) {
      const sy = 1 + f.squash;
      const sx = 1 - f.squash * 0.55;
      el.style.transform = `rotate(${f.lean.toFixed(2)}deg) scale(${sx.toFixed(3)}, ${sy.toFixed(3)})`;
    }
    const parado = Math.abs(f.lean) < 0.04 && Math.abs(f.leanV) < 0.4
      && Math.abs(f.squash) < 0.001 && Math.abs(f.squashV) < 0.02;
    if (parado) {
      molaRodando.current = false;
      if (el) el.style.transform = "";
      return;
    }
    quadroMola.current = requestAnimationFrame(passoMola);
  }, []);

  const cutucar = useCallback(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const f = molaEstado.current;
    f.leanV += (Math.random() * 2 - 1) * 130;   // balança para um lado
    f.squashV += -2.4;                            // e "afunda" de cócegas
    if (!molaRodando.current) {
      molaRodando.current = true;
      quadroMola.current = requestAnimationFrame(passoMola);
    }
  }, [passoMola]);

  // --- Idle (olhos, piscada, tchau) ------------------------------------
  useEffect(() => {
    if (!vivo) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

    pupilas.current = Array.from(
      svgRef.current?.querySelectorAll<SVGCircleElement>(".cosmo-pupila") ?? [],
    );

    const animarOlhos = () => {
      const dx = alvoOlhar.current.x - olhar.current.x;
      const dy = alvoOlhar.current.y - olhar.current.y;
      if (Math.abs(dx) < 0.1 && Math.abs(dy) < 0.1) {
        olhosRodando.current = false;
        return;
      }
      olhar.current.x += dx * 0.14;
      olhar.current.y += dy * 0.14;
      for (const pupila of pupilas.current) {
        pupila.style.transform =
          `translate(${olhar.current.x.toFixed(2)}px, ${olhar.current.y.toFixed(2)}px)`;
      }
      quadroOlhos.current = requestAnimationFrame(animarOlhos);
    };
    const acordar = () => {
      if (olhosRodando.current) return;
      olhosRodando.current = true;
      quadroOlhos.current = requestAnimationFrame(animarOlhos);
    };

    const aoMover = (evento: PointerEvent) => {
      const nx = (evento.clientX / window.innerWidth - 0.5) * 2;
      const ny = (evento.clientY / window.innerHeight - 0.42) * 2;
      alvoOlhar.current = {
        x: Math.max(-1, Math.min(1, nx)) * 7,
        y: Math.max(-1, Math.min(1, ny)) * 5.5,
      };
      ultimoPonteiro.current = performance.now();
      acordar();
    };
    window.addEventListener("pointermove", aoMover, { passive: true });

    const olharCurioso = window.setInterval(() => {
      if (performance.now() - ultimoPonteiro.current > 3500) {
        alvoOlhar.current = {
          x: (Math.random() * 2 - 1) * 6,
          y: (Math.random() * 2 - 1) * 4,
        };
        acordar();
      }
    }, 2600);

    let temporizadorPiscar = 0;
    const agendarPiscar = () => {
      temporizadorPiscar = window.setTimeout(() => {
        piscar();
        if (Math.random() < 0.22) window.setTimeout(piscar, 260);
        agendarPiscar();
      }, 1800 + Math.random() * 3800);
    };
    agendarPiscar();

    let temporizadorTchau = window.setTimeout(acenar, 1400);
    const agendarTchau = () => {
      temporizadorTchau = window.setTimeout(() => {
        acenar();
        agendarTchau();
      }, 6000 + Math.random() * 7000);
    };
    agendarTchau();

    return () => {
      window.removeEventListener("pointermove", aoMover);
      window.clearInterval(olharCurioso);
      cancelAnimationFrame(quadroOlhos.current);
      cancelAnimationFrame(quadroMola.current);
      olhosRodando.current = false;
      molaRodando.current = false;
      window.clearTimeout(temporizadorPiscar);
      window.clearTimeout(temporizadorTchau);
    };
  }, [vivo, acenar, piscar]);

  const aoTocar = () => {
    if (!fisica) return;
    cutucar();
    tocar("clique");
    aoClicar?.();
  };

  const aoTocarAntena = (evento: React.PointerEvent) => {
    if (!fisica) return;
    evento.stopPropagation();
    const luz = svgRef.current?.querySelector(".cosmo-antena-luz");
    if (luz) {
      luz.classList.remove("acesa");
      void (luz as SVGCircleElement).getBoundingClientRect();
      luz.classList.add("acesa");
    }
    tocar("bip");
    cutucar();
  };

  return (
    <svg
      ref={svgRef}
      className="cosmo"
      viewBox="0 0 520 575"
      style={{ height: altura, width: "auto", cursor: fisica ? "pointer" : "default", ...(cor ? ({ ["--skin"]: cor } as React.CSSProperties) : {}) }}
      aria-label="Cosmo, seu companheiro de aventuras"
      role="img"
      onPointerDown={aoTocar}
    >
      <g transform="translate(55 0)">
        <g className="cosmo-fisica" ref={molaRef}>
          {/* pernas ficam paradas: o gingado é do tronco */}
          <rect className="pele" x="126" y="428" width="70" height="118" rx="34" />
          <rect className="pele" x="224" y="428" width="70" height="118" rx="34" />
          <ellipse cx="161" cy="540" rx="35" ry="14" fill="rgba(0,0,0,.14)" />
          <ellipse cx="259" cy="540" rx="35" ry="14" fill="rgba(0,0,0,.14)" />
          <ellipse cx="210" cy="552" rx="120" ry="16" fill="rgba(0,0,0,.16)" />
          <g className="cosmo-tronco">
            <rect className="pele" x="46" y="252" width="62" height="164" rx="31"
                  transform="rotate(16 77 334)" />
            <g className="cosmo-bracoR">
              <rect className="pele" x="312" y="100" width="60" height="178" rx="30"
                    transform="rotate(26 342 278)" />
              <circle className="pele" cx="394" cy="120" r="34" />
              <circle cx="394" cy="120" r="34" fill="rgba(255,255,255,.22)" />
            </g>
            <rect className="pele" x="86" y="112" width="248" height="352" rx="124" />
            <path d="M120 160 Q108 260 128 350" stroke="rgba(255,255,255,.4)"
                  strokeWidth="16" strokeLinecap="round" fill="none" />
            <line x1="210" y1="96" x2="210" y2="42" stroke="rgba(0,0,0,.25)"
                  strokeWidth="8" strokeLinecap="round" />
            <circle className="cosmo-antena-luz" cx="210" cy="34" r="13" fill="#FFC93C" />
            <circle cx="210" cy="34" r="22" fill="#FFC93C" opacity=".25" />
            {/* Chapéu (atrás do visor, sobre o capacete) */}
            <Chapeu slug={chapeu} />
            <ellipse cx="210" cy="216" rx="100" ry="84" fill="#221C46" />
            <ellipse cx="210" cy="216" rx="100" ry="84" fill="none"
                     stroke="rgba(255,255,255,.55)" strokeWidth="7" />
            <Rosto slug={rosto} />
            <path d="M136 178 Q150 152 184 146" stroke="rgba(255,255,255,.5)"
                  strokeWidth="10" strokeLinecap="round" fill="none" />
            <text x="210" y="342" textAnchor="middle" fontSize="34"
                  fill="rgba(255,255,255,.85)">★</text>
            {/* zona da antena: bip + luz (o resto do corpo dá cócegas) */}
            <circle cx="210" cy="34" r="46" fill="transparent"
                    onPointerDown={aoTocarAntena} aria-hidden />
          </g>
        </g>
      </g>
    </svg>
  );
}
