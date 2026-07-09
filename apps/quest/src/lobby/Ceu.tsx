/**
 * Céu vivo de fundo: gradiente, constelação e neblina (protótipo v7).
 *
 * No lobby o céu é TOCÁVEL: cada estrela acende com uma nota pentatônica;
 * acender todas completa a constelação do dia (linhas brilham + festa do
 * Cosmo). Reseta a cada dia — um micro-ritual de 20 segundos que ensaia o
 * conceito central do produto (a Constelação de progresso).
 */
import { useCallback, useEffect, useState } from "react";

import { tocarNota } from "../audio/audio";

const CHAVE_CEU = "quest_ceu";

// Estrelas da constelação (as 8 ligadas por linhas) + soltas (decorativas)
// Nenhuma estrela dentro da coluna central (~35–65%): ali vive o Cosmo,
// e a área de toque dele "roubaria" o dedo da criança.
const ESTRELAS = [
  { x: "8%", y: "16%", r: 3.5 },
  { x: "16%", y: "26%", r: 5 },
  { x: "27%", y: "19%", r: 3.5 },
  { x: "24%", y: "37%", r: 4.5 },
  { x: "70%", y: "14%", r: 4 },
  { x: "79%", y: "22%", r: 5.5 },
  { x: "88%", y: "15%", r: 3.5 },
  { x: "84%", y: "34%", r: 4 },
];
const SOLTAS = [
  { x: "50%", y: "10%", r: 3 },
  { x: "60%", y: "40%", r: 3 },
  { x: "12%", y: "44%", r: 3 },
  { x: "93%", y: "46%", r: 3.5 },
];
const LINHAS = [[0, 1], [1, 2], [2, 3], [4, 5], [5, 6], [5, 7]];

// Escala pentatônica: qualquer ordem de toques soa bem
const NOTAS = [523.25, 587.33, 659.25, 783.99, 880, 1046.5, 1174.66, 1318.51];

function hoje(): string {
  return new Date().toISOString().slice(0, 10);
}

function lerAcesas(): number[] {
  try {
    const bruto = JSON.parse(localStorage.getItem(CHAVE_CEU) ?? "null");
    return bruto && bruto.dia === hoje() ? bruto.acesas : [];
  } catch {
    return [];
  }
}

interface CeuProps {
  /** Estrelas respondem ao toque (só no lobby). */
  tocavel?: boolean;
  /** Chamado quando a criança acende a constelação inteira do dia. */
  aoCompletar?: () => void;
}

export function Ceu({ tocavel = false, aoCompletar }: CeuProps) {
  const [acesas, setAcesas] = useState<number[]>(tocavel ? lerAcesas : []);
  const completa = acesas.length === ESTRELAS.length;

  useEffect(() => {
    if (!tocavel) return;
    localStorage.setItem(CHAVE_CEU,
      JSON.stringify({ dia: hoje(), acesas }));
  }, [acesas, tocavel]);

  const acender = useCallback((indice: number) => {
    if (acesas.includes(indice)) {
      tocarNota(NOTAS[indice], 0.06); // re-tocar ainda faz música
      return;
    }
    tocarNota(NOTAS[indice]);
    const novas = [...acesas, indice];
    setAcesas(novas);
    if (novas.length === ESTRELAS.length) {
      window.setTimeout(() => aoCompletar?.(), 400);
    }
  }, [acesas, aoCompletar]);

  return (
    <>
      <div className="ceu" />
      <svg
        className={`constelacao${tocavel ? " tocavel" : ""}${completa ? " completa" : ""}`}
        width="100%" height="100%"
        preserveAspectRatio="none"
        aria-hidden
      >
        {LINHAS.map(([a, b]) => (
          <line
            key={`${a}-${b}`}
            x1={ESTRELAS[a].x} y1={ESTRELAS[a].y}
            x2={ESTRELAS[b].x} y2={ESTRELAS[b].y}
            className={acesas.includes(a) && acesas.includes(b) ? "acesa" : ""}
          />
        ))}
        {ESTRELAS.map((estrela, indice) => (
          <circle
            key={indice}
            cx={estrela.x} cy={estrela.y}
            r={acesas.includes(indice) ? estrela.r + 2 : estrela.r}
            className={acesas.includes(indice) ? "acesa" : ""}
            onPointerDown={tocavel ? () => acender(indice) : undefined}
          />
        ))}
        {SOLTAS.map((estrela, indice) => (
          <circle key={`s${indice}`} cx={estrela.x} cy={estrela.y} r={estrela.r} />
        ))}
      </svg>
      <div className="neblina" />
    </>
  );
}
