/**
 * Boneco — o AVATAR humanoide do jogador (estilo Roblox/mockup). Camadas
 * trocáveis: pele, cabelo, camiseta, calça, tênis, acessório, costas
 * (mochila/asas), mão (varinha), pet. Rosto vivo (olhos seguem o ponteiro,
 * pisca, acena) e física de cutucada. viewBox 0 0 360 560.
 */
import { useCallback, useEffect, useRef } from "react";

import "./boneco.css";
import { tocar } from "../audio/audio";
import { cabeloFrente, cabeloTras } from "./cabelos";
import { Acessorio, CostasH, MaoH, PetH } from "./itens";

interface BonecoProps {
  pele?: string;
  cabelo?: string;
  camiseta?: string;
  calca?: string;
  tenis?: string;
  chapeu?: string;
  costas?: string;
  mao?: string;
  pet?: string;
  vivo?: boolean;
  fisica?: boolean;
  altura?: string;
  aoClicar?: () => void;
}

const PADRAO = {
  pele: "#F6C8A0", cabelo: "curto_castanho", camiseta: "#4EA8FF",
  calca: "#3A2E66", tenis: "#FF5470", chapeu: "nenhum",
  costas: "nenhum", mao: "nenhum", pet: "nenhum",
};

export function Boneco(props: BonecoProps) {
  const {
    pele = PADRAO.pele, cabelo = PADRAO.cabelo, camiseta = PADRAO.camiseta,
    calca = PADRAO.calca, tenis = PADRAO.tenis, chapeu = PADRAO.chapeu,
    costas = PADRAO.costas, mao = PADRAO.mao, pet = PADRAO.pet,
    vivo = true, fisica = false, altura = "60vh", aoClicar,
  } = props;

  const svgRef = useRef<SVGSVGElement>(null);
  const molaRef = useRef<SVGGElement>(null);
  const alvo = useRef({ x: 0, y: 0 });
  const olhar = useRef({ x: 0, y: 0 });
  const ultimo = useRef(0);
  const qOlhos = useRef(0);
  const olhosOn = useRef(false);
  const mola = useRef({ lean: 0, leanV: 0, sq: 0, sqV: 0 });
  const qMola = useRef(0);
  const molaOn = useRef(false);

  const acenar = useCallback(() => {
    const b = svgRef.current?.querySelector(".boneco-bracoR");
    if (!b) return;
    b.classList.remove("acenando");
    void (b as SVGGElement).getBoundingClientRect();
    b.classList.add("acenando");
    window.setTimeout(() => b.classList.remove("acenando"), 1900);
  }, []);

  const piscar = useCallback(() => {
    svgRef.current?.querySelectorAll(".boneco-olho").forEach((o) => {
      o.classList.remove("piscando");
      void (o as SVGGElement).getBoundingClientRect();
      o.classList.add("piscando");
    });
  }, []);

  const passoMola = useCallback(() => {
    const f = mola.current;
    const k = 180, c = 11, dt = 1 / 60;
    f.leanV += (-k * f.lean - c * f.leanV) * dt;
    f.lean += f.leanV * dt;
    f.sqV += (-k * f.sq - c * f.sqV) * dt;
    f.sq += f.sqV * dt;
    const el = molaRef.current;
    if (el) el.style.transform =
      `rotate(${f.lean.toFixed(2)}deg) scale(${(1 - f.sq * 0.55).toFixed(3)}, ${(1 + f.sq).toFixed(3)})`;
    if (Math.abs(f.lean) < 0.04 && Math.abs(f.leanV) < 0.4
        && Math.abs(f.sq) < 0.001 && Math.abs(f.sqV) < 0.02) {
      molaOn.current = false;
      if (el) el.style.transform = "";
      return;
    }
    qMola.current = requestAnimationFrame(passoMola);
  }, []);

  const cutucar = useCallback(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const f = mola.current;
    f.leanV += (Math.random() * 2 - 1) * 130;
    f.sqV += -2.4;
    if (!molaOn.current) { molaOn.current = true; qMola.current = requestAnimationFrame(passoMola); }
  }, [passoMola]);

  useEffect(() => {
    if (!vivo || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const pupilas = Array.from(
      svgRef.current?.querySelectorAll<SVGCircleElement>(".boneco-pupila") ?? []);

    const anim = () => {
      const dx = alvo.current.x - olhar.current.x;
      const dy = alvo.current.y - olhar.current.y;
      if (Math.abs(dx) < 0.1 && Math.abs(dy) < 0.1) { olhosOn.current = false; return; }
      olhar.current.x += dx * 0.14; olhar.current.y += dy * 0.14;
      for (const p of pupilas)
        p.style.transform = `translate(${olhar.current.x.toFixed(2)}px, ${olhar.current.y.toFixed(2)}px)`;
      qOlhos.current = requestAnimationFrame(anim);
    };
    const acordar = () => { if (!olhosOn.current) { olhosOn.current = true; qOlhos.current = requestAnimationFrame(anim); } };
    const aoMover = (e: PointerEvent) => {
      alvo.current = {
        x: Math.max(-1, Math.min(1, (e.clientX / innerWidth - 0.5) * 2)) * 6,
        y: Math.max(-1, Math.min(1, (e.clientY / innerHeight - 0.42) * 2)) * 5,
      };
      ultimo.current = performance.now(); acordar();
    };
    addEventListener("pointermove", aoMover, { passive: true });
    const curioso = window.setInterval(() => {
      if (performance.now() - ultimo.current > 3500) {
        alvo.current = { x: (Math.random() * 2 - 1) * 5, y: (Math.random() * 2 - 1) * 3.5 };
        acordar();
      }
    }, 2600);
    let tp = 0;
    const agPiscar = () => {
      tp = window.setTimeout(() => {
        piscar();
        if (Math.random() < 0.22) window.setTimeout(piscar, 260);
        agPiscar();
      }, 1800 + Math.random() * 3800);
    };
    agPiscar();
    let tt = window.setTimeout(acenar, 1400);
    const agTchau = () => { tt = window.setTimeout(() => { acenar(); agTchau(); }, 6000 + Math.random() * 7000); };
    agTchau();

    return () => {
      removeEventListener("pointermove", aoMover);
      window.clearInterval(curioso);
      cancelAnimationFrame(qOlhos.current);
      cancelAnimationFrame(qMola.current);
      window.clearTimeout(tp); window.clearTimeout(tt);
    };
  }, [vivo, acenar, piscar]);

  const aoTocar = () => { if (!fisica) return; cutucar(); tocar("clique"); aoClicar?.(); };

  const tenisSvg = (x: number, mao2 = false) => (
    <g key={mao2 ? "d" : "e"}>
      <path d={`M${x} 470 Q${x - 4} 462 ${x + 10} 460 L${x + 38} 460 Q${x + 46} 462 ${x + 46} 476
        L${x + 46} 492 Q${x + 46} 500 ${x + 36} 500 L${x + 6} 500 Q${x - 2} 500 ${x - 2} 492 Z`}
        fill={tenis} />
      <rect x={x - 4} y="492" width="52" height="9" rx="4" fill="#F2EFFF" />
    </g>
  );

  return (
    <svg
      ref={svgRef}
      className="boneco"
      viewBox="0 0 360 560"
      style={{ height: altura, width: "auto", cursor: fisica ? "pointer" : "default" }}
      role="img"
      aria-label="Seu personagem"
      onPointerDown={aoTocar}
    >
      <g className="boneco-fisica" ref={molaRef}>
        <CostasH slug={costas} />
        <ellipse cx="180" cy="532" rx="112" ry="16" fill="rgba(0,0,0,.16)" />

        {/* pernas + tênis */}
        <rect x="148" y="356" width="33" height="118" rx="16" fill={calca} />
        <rect x="180" y="356" width="33" height="118" rx="16" fill={calca} />
        {tenisSvg(136)}{tenisSvg(178, true)}

        {/* corpo (upper body balança) */}
        <g className="boneco-tronco">
          {/* camiseta */}
          <path d="M112 268 Q112 238 150 234 L210 234 Q248 238 248 268 L252 356
                   Q252 374 230 374 L130 374 Q108 374 108 356 Z" fill={camiseta} />
          <rect x="98" y="240" width="42" height="46" rx="20" fill={camiseta} />
          <rect x="220" y="240" width="42" height="46" rx="20" fill={camiseta} />

          {/* braços (pele) */}
          <rect x="100" y="276" width="33" height="104" rx="16" fill={pele} />
          <g className="boneco-bracoR">
            <rect x="248" y="152" width="30" height="120" rx="15" fill={pele}
                  transform="rotate(24 263 272)" />
            <circle cx="302" cy="150" r="22" fill={pele} />
            <MaoH slug={mao} />
          </g>

          {/* pescoço + cabeça */}
          <rect x="162" y="214" width="36" height="30" fill={pele} />
          {cabeloTras(cabelo)}
          <circle cx="96" cy="150" r="15" fill={pele} />
          <circle cx="264" cy="150" r="15" fill={pele} />
          <circle cx="180" cy="140" r="92" fill={pele} />
          {cabeloFrente(cabelo)}

          {/* rosto */}
          <ellipse cx="126" cy="170" rx="15" ry="9" fill="rgba(255,120,120,.4)" />
          <ellipse cx="234" cy="170" rx="15" ry="9" fill="rgba(255,120,120,.4)" />
          <g className="boneco-olho">
            <ellipse cx="152" cy="146" rx="16" ry="21" fill="#fff" />
            <circle className="boneco-pupila" cx="152" cy="150" r="8" fill="#231D4E" />
          </g>
          <g className="boneco-olho">
            <ellipse cx="208" cy="146" rx="16" ry="21" fill="#fff" />
            <circle className="boneco-pupila" cx="208" cy="150" r="8" fill="#231D4E" />
          </g>
          <path d="M156 184 Q180 208 204 184" stroke="#8A4B36" strokeWidth="6"
                fill="none" strokeLinecap="round" />
          <Acessorio slug={chapeu} />
        </g>

        <PetH slug={pet} />
      </g>
    </svg>
  );
}
