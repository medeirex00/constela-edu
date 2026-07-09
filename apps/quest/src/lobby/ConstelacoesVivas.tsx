/**
 * Constelações VIVAS de ambiente: pequenas constelações que desenham suas
 * linhas aos poucos, brilham, somem e reaparecem — o espaço parece vivo.
 * Decorativas (não tocáveis); usadas no lobby e no vestiário.
 *
 * O desenho das linhas usa pathLength="1" + stroke-dashoffset (independe do
 * tamanho real da linha, funciona com viewBox esticado).
 */
type Ponto = [number, number]; // percentuais 0–100

interface Constela {
  estrelas: Ponto[];
  arestas: [number, number][];
  atraso: number; // segundos
}

const CONSTELAS: Constela[] = [
  { estrelas: [[8, 14], [15, 24], [24, 17], [31, 28]], arestas: [[0, 1], [1, 2], [2, 3]], atraso: 0 },
  { estrelas: [[70, 12], [78, 20], [87, 13], [82, 30]], arestas: [[0, 1], [1, 2], [1, 3]], atraso: 3 },
  { estrelas: [[90, 46], [95, 56], [88, 62]], arestas: [[0, 1], [1, 2]], atraso: 6 },
  { estrelas: [[6, 52], [12, 60], [10, 72], [3, 66]], arestas: [[0, 1], [1, 2], [2, 3], [3, 0]], atraso: 8 },
  { estrelas: [[50, 8], [58, 16], [64, 9]], arestas: [[0, 1], [1, 2]], atraso: 4.5 },
];

export function ConstelacoesVivas() {
  return (
    <svg className="constelacoes-vivas" width="100%" height="100%"
         preserveAspectRatio="none" aria-hidden>
      {CONSTELAS.map((c, ci) => (
        <g key={ci} style={{ animationDelay: `${c.atraso}s` } as React.CSSProperties}
           className="cv-grupo">
          {c.arestas.map(([a, b], ei) => (
            <line
              key={ei}
              x1={`${c.estrelas[a][0]}%`} y1={`${c.estrelas[a][1]}%`}
              x2={`${c.estrelas[b][0]}%`} y2={`${c.estrelas[b][1]}%`}
              className="cv-linha"
              pathLength={1}
              style={{ animationDelay: `${c.atraso + ei * 0.4}s` } as React.CSSProperties}
            />
          ))}
          {c.estrelas.map(([x, y], si) => (
            <circle key={si} cx={`${x}%`} cy={`${y}%`} r={si === 0 ? 3.5 : 2.5}
                    className="cv-estrela"
                    style={{ animationDelay: `${c.atraso + si * 0.3}s` } as React.CSSProperties} />
          ))}
        </g>
      ))}
    </svg>
  );
}
