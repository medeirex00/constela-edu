/**
 * Cosmo — o mascote vivo (portado do protótipo constela-play-v7).
 *
 * Comportamentos: olhos seguem o ponteiro (suave, com limite), piscadas em
 * intervalos naturais (às vezes dupla), tchau de vez em quando e pulo de
 * alegria sob demanda. Tudo desligado com prefers-reduced-motion.
 */
import { useCallback, useEffect, useRef } from "react";

import "./cosmo.css";
import { tocar } from "../audio/audio";

interface CosmoProps {
  /** Cor do traje; sem valor usa a var --skin global (cor equipada). */
  cor?: string;
  /** Olhos seguem o ponteiro + agenda de piscar/acenar (padrão: sim). */
  vivo?: boolean;
  altura?: string;
  aoClicar?: () => void;
}

export function Cosmo({ cor, vivo = true, altura = "60vh", aoClicar }: CosmoProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const alvoOlhar = useRef({ x: 0, y: 0 });
  const olhar = useRef({ x: 0, y: 0 });
  const ultimoPonteiro = useRef(0);

  const acenar = useCallback(() => {
    const braco = svgRef.current?.querySelector(".cosmo-bracoR");
    if (!braco) return;
    braco.classList.remove("acenando");
    void (braco as SVGGElement).getBoundingClientRect();
    braco.classList.add("acenando");
    window.setTimeout(() => braco.classList.remove("acenando"), 1900);
  }, []);

  const pular = useCallback(() => {
    const svg = svgRef.current;
    if (!svg) return;
    svg.classList.remove("feliz");
    void svg.getBoundingClientRect();
    svg.classList.add("feliz");
    window.setTimeout(() => svg.classList.remove("feliz"), 700);
  }, []);

  useEffect(() => {
    if (!vivo) return;
    const reduzido = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduzido) return;

    const aoMover = (evento: PointerEvent) => {
      const nx = (evento.clientX / window.innerWidth - 0.5) * 2;
      const ny = (evento.clientY / window.innerHeight - 0.42) * 2;
      alvoOlhar.current = {
        x: Math.max(-1, Math.min(1, nx)) * 7,
        y: Math.max(-1, Math.min(1, ny)) * 5.5,
      };
      ultimoPonteiro.current = performance.now();
    };
    window.addEventListener("pointermove", aoMover, { passive: true });
    window.addEventListener("pointerdown", aoMover, { passive: true });

    // Olhar aleatório quando o ponteiro está parado há um tempo
    const olharCurioso = window.setInterval(() => {
      if (performance.now() - ultimoPonteiro.current > 3500) {
        alvoOlhar.current = {
          x: (Math.random() * 2 - 1) * 6,
          y: (Math.random() * 2 - 1) * 4,
        };
      }
    }, 2600);

    let quadro = 0;
    const animarOlhos = () => {
      olhar.current.x += (alvoOlhar.current.x - olhar.current.x) * 0.14;
      olhar.current.y += (alvoOlhar.current.y - olhar.current.y) * 0.14;
      svgRef.current
        ?.querySelectorAll<SVGCircleElement>(".cosmo-pupila")
        .forEach((pupila) => {
          pupila.style.transform =
            `translate(${olhar.current.x.toFixed(2)}px, ${olhar.current.y.toFixed(2)}px)`;
        });
      quadro = requestAnimationFrame(animarOlhos);
    };
    quadro = requestAnimationFrame(animarOlhos);

    // Piscadas naturais (às vezes dupla)
    const piscar = () => {
      svgRef.current?.querySelectorAll(".cosmo-olho").forEach((olho) => {
        olho.classList.remove("piscando");
        void (olho as SVGGElement).getBoundingClientRect();
        olho.classList.add("piscando");
      });
    };
    let temporizadorPiscar = 0;
    const agendarPiscar = () => {
      temporizadorPiscar = window.setTimeout(() => {
        piscar();
        if (Math.random() < 0.22) window.setTimeout(piscar, 260);
        agendarPiscar();
      }, 1800 + Math.random() * 3800);
    };
    agendarPiscar();

    // Tchau de vez em quando (o primeiro logo que aparece)
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
      window.removeEventListener("pointerdown", aoMover);
      window.clearInterval(olharCurioso);
      cancelAnimationFrame(quadro);
      window.clearTimeout(temporizadorPiscar);
      window.clearTimeout(temporizadorTchau);
    };
  }, [vivo, acenar]);

  const clicar = () => {
    pular();
    acenar();
    tocar("clique");
    aoClicar?.();
  };

  return (
    <svg
      ref={svgRef}
      className="cosmo"
      viewBox="0 0 520 575"
      style={{ height: altura, width: "auto", cursor: "pointer", ...(cor ? ({ ["--skin"]: cor } as React.CSSProperties) : {}) }}
      aria-label="Cosmo, seu companheiro de aventuras"
      role="img"
      onClick={clicar}
    >
      <g transform="translate(55 0)">
        {/* pernas ficam paradas: o gingado é do tronco */}
        <rect className="pele" x="126" y="428" width="70" height="118" rx="34" />
        <rect className="pele" x="224" y="428" width="70" height="118" rx="34" />
        <ellipse cx="161" cy="540" rx="35" ry="14" fill="rgba(0,0,0,.14)" />
        <ellipse cx="259" cy="540" rx="35" ry="14" fill="rgba(0,0,0,.14)" />
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
          <circle cx="210" cy="34" r="13" fill="#FFC93C" />
          <circle cx="210" cy="34" r="22" fill="#FFC93C" opacity=".25" />
          <ellipse cx="210" cy="216" rx="100" ry="84" fill="#221C46" />
          <ellipse cx="210" cy="216" rx="100" ry="84" fill="none"
                   stroke="rgba(255,255,255,.55)" strokeWidth="7" />
          <g className="cosmo-olho">
            <ellipse cx="176" cy="204" rx="15" ry="22" fill="#fff" />
            <circle className="cosmo-pupila" cx="176" cy="208" r="7" fill="#221C46" />
          </g>
          <g className="cosmo-olho">
            <ellipse cx="244" cy="204" rx="15" ry="22" fill="#fff" />
            <circle className="cosmo-pupila" cx="244" cy="208" r="7" fill="#221C46" />
          </g>
          <path d="M186 248 Q210 268 234 248" stroke="#fff" strokeWidth="8"
                strokeLinecap="round" fill="none" />
          <path d="M136 178 Q150 152 184 146" stroke="rgba(255,255,255,.5)"
                strokeWidth="10" strokeLinecap="round" fill="none" />
          <text x="210" y="342" textAnchor="middle" fontSize="34"
                fill="rgba(255,255,255,.85)">★</text>
        </g>
      </g>
    </svg>
  );
}
