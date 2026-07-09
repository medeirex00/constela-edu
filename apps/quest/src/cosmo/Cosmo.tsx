/**
 * Cosmo — o mascote vivo (portado do protótipo constela-play-v7).
 *
 * Comportamentos: olhos seguem o ponteiro, piscadas naturais, tchau de vez
 * em quando, pulo de alegria — e ZONAS DE TOQUE com reações próprias
 * (antena acende e bipa, barriga faz cócegas, olhos piscam), porque
 * descobrir segredos no mascote é metade do vínculo.
 *
 * Econômico de propósito (tablet fraco de escola): o loop de olhos SÓ roda
 * enquanto há movimento a fazer (dorme convergido — em touch isso é ~99%
 * do tempo) e não há filtro CSS sobre elementos animados.
 */
import { useCallback, useEffect, useRef } from "react";

import "./cosmo.css";
import { narrar, tocar } from "../audio/audio";

interface CosmoProps {
  /** Cor do traje; sem valor usa a var --skin global (cor equipada). */
  cor?: string;
  /** Olhos seguem o ponteiro + agenda de piscar/acenar (padrão: sim). */
  vivo?: boolean;
  altura?: string;
  aoClicar?: () => void;
}

const FALAS_COCEGAS = [
  "Ha ha! Que cócegas!",
  "Ai ai ai, para, que eu rio!",
  "Hi hi hi! Você me pegou!",
];

export function Cosmo({ cor, vivo = true, altura = "60vh", aoClicar }: CosmoProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const alvoOlhar = useRef({ x: 0, y: 0 });
  const olhar = useRef({ x: 0, y: 0 });
  const ultimoPonteiro = useRef(0);
  const quadro = useRef(0);
  const rodando = useRef(false);
  const pupilas = useRef<SVGCircleElement[]>([]);

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

  const piscar = useCallback(() => {
    svgRef.current?.querySelectorAll(".cosmo-olho").forEach((olho) => {
      olho.classList.remove("piscando");
      void (olho as SVGGElement).getBoundingClientRect();
      olho.classList.add("piscando");
    });
  }, []);

  useEffect(() => {
    if (!vivo) return;
    const reduzido = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduzido) return;

    pupilas.current = Array.from(
      svgRef.current?.querySelectorAll<SVGCircleElement>(".cosmo-pupila") ?? [],
    );

    // Loop dos olhos: acorda com eventos, dorme quando converge
    const animarOlhos = () => {
      const dx = alvoOlhar.current.x - olhar.current.x;
      const dy = alvoOlhar.current.y - olhar.current.y;
      if (Math.abs(dx) < 0.1 && Math.abs(dy) < 0.1) {
        rodando.current = false;
        return;
      }
      olhar.current.x += dx * 0.14;
      olhar.current.y += dy * 0.14;
      for (const pupila of pupilas.current) {
        pupila.style.transform =
          `translate(${olhar.current.x.toFixed(2)}px, ${olhar.current.y.toFixed(2)}px)`;
      }
      quadro.current = requestAnimationFrame(animarOlhos);
    };
    const acordar = () => {
      if (rodando.current) return;
      rodando.current = true;
      quadro.current = requestAnimationFrame(animarOlhos);
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
    window.addEventListener("pointerdown", aoMover, { passive: true });

    // Olhar aleatório quando o ponteiro está parado há um tempo
    const olharCurioso = window.setInterval(() => {
      if (performance.now() - ultimoPonteiro.current > 3500) {
        alvoOlhar.current = {
          x: (Math.random() * 2 - 1) * 6,
          y: (Math.random() * 2 - 1) * 4,
        };
        acordar();
      }
    }, 2600);

    // Piscadas naturais (às vezes dupla)
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
      cancelAnimationFrame(quadro.current);
      rodando.current = false;
      window.clearTimeout(temporizadorPiscar);
      window.clearTimeout(temporizadorTchau);
    };
  }, [vivo, acenar, piscar]);

  // --- Zonas de toque (segredinhos do mascote) ---------------------------

  const tocarAntena = (evento: React.PointerEvent) => {
    evento.stopPropagation();
    tocar("bip");
    const luz = svgRef.current?.querySelector(".cosmo-antena-luz");
    if (luz) {
      luz.classList.remove("acesa");
      void (luz as SVGCircleElement).getBoundingClientRect();
      luz.classList.add("acesa");
    }
  };

  const tocarBarriga = (evento: React.PointerEvent) => {
    evento.stopPropagation();
    if (!vivo) return;
    const svg = svgRef.current;
    if (svg) {
      svg.classList.remove("cocegas");
      void svg.getBoundingClientRect();
      svg.classList.add("cocegas");
      window.setTimeout(() => svg.classList.remove("cocegas"), 650);
    }
    tocar("sucesso");
    narrar(FALAS_COCEGAS[Math.floor(Math.random() * FALAS_COCEGAS.length)]);
  };

  const tocarOlhos = (evento: React.PointerEvent) => {
    evento.stopPropagation();
    piscar();
    window.setTimeout(piscar, 240);
    tocar("clique");
  };

  const clicarCorpo = () => {
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
      onClick={clicarCorpo}
    >
      <g transform="translate(55 0)">
        {/* pernas ficam paradas: o gingado é do tronco */}
        <rect className="pele" x="126" y="428" width="70" height="118" rx="34" />
        <rect className="pele" x="224" y="428" width="70" height="118" rx="34" />
        <ellipse cx="161" cy="540" rx="35" ry="14" fill="rgba(0,0,0,.14)" />
        <ellipse cx="259" cy="540" rx="35" ry="14" fill="rgba(0,0,0,.14)" />
        {/* sombra do corpo desenhada (substitui o drop-shadow CSS, que
            re-rasterizava o SVG inteiro a cada quadro de animação) */}
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

          {/* Zonas de toque invisíveis (alvos generosos para dedo pequeno) */}
          <circle cx="210" cy="34" r="44" fill="transparent"
                  onPointerDown={tocarAntena} aria-hidden />
          <ellipse cx="210" cy="206" rx="90" ry="46" fill="transparent"
                   onPointerDown={tocarOlhos} aria-hidden />
          <ellipse cx="210" cy="350" rx="95" ry="80" fill="transparent"
                   onPointerDown={tocarBarriga} aria-hidden />
        </g>
      </g>
    </svg>
  );
}
