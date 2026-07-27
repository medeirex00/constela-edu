/** Gráficos SVG leves — sem dependências externas (PRD §23: consultas enxutas). */

export interface PontoSerie {
  rotulo: string; // data formatada
  valor: number;
}

const CORES = ["#6366f1", "#10b981", "#f59e0b", "#ef4444"];

export function GraficoLinha({
  series,
  altura = 180,
}: {
  series: { nome: string; pontos: PontoSerie[] }[];
  altura?: number;
}) {
  const visiveis = series.filter((serie) => serie.pontos.length > 0);
  if (visiveis.length === 0) {
    return <p className="py-8 text-center text-sm text-zinc-400">Sem dados suficientes para o gráfico.</p>;
  }
  // viewBox menor => fontes, pontos e linhas renderizam MAIORES (o SVG escala
  // para a largura do container). Com 2 gráficos por linha (~450px), os números
  // saem em ~12px, legíveis.
  const largura = 500;
  const margem = { esquerda: 46, direita: 12, topo: 14, base: 26 };
  const maximo = Math.max(1, ...visiveis.flatMap((serie) => serie.pontos.map((ponto) => ponto.valor)));
  const quantidade = Math.max(...visiveis.map((serie) => serie.pontos.length));

  const x = (indice: number) =>
    margem.esquerda +
    (quantidade <= 1 ? 0 : (indice / (quantidade - 1)) * (largura - margem.esquerda - margem.direita));
  const y = (valor: number) =>
    margem.topo + (1 - valor / maximo) * (altura - margem.topo - margem.base);

  const rotulos = visiveis[0].pontos;
  // Rotula os pontos com o VALOR visível só quando há UMA série (mini-gráfico
  // por métrica) — assim os números não se sobrepõem entre séries. Mostra no
  // 1º, no último e sempre que o valor MUDA (pula os trechos planos repetidos).
  const rotularPontos = visiveis.length === 1;

  return (
    <div>
      <svg viewBox={`0 0 ${largura} ${altura}`} className="w-full" role="img" aria-label="Gráfico de evolução">
        {[0, 0.5, 1].map((fracao) => (
          <g key={fracao}>
            <line
              x1={margem.esquerda} x2={largura - margem.direita}
              y1={y(maximo * fracao)} y2={y(maximo * fracao)}
              className="stroke-zinc-200 dark:stroke-zinc-700" strokeWidth={1}
            />
            <text
              x={margem.esquerda - 6} y={y(maximo * fracao) + 4} textAnchor="end"
              className="fill-zinc-400 text-[13px] tabular-nums"
            >
              {Math.round(maximo * fracao).toLocaleString("pt-BR")}
            </text>
          </g>
        ))}
        {visiveis.map((serie, indiceSerie) => (
          <g key={serie.nome}>
            <polyline
              fill="none"
              stroke={CORES[indiceSerie % CORES.length]}
              strokeWidth={2}
              points={serie.pontos.map((ponto, indice) => `${x(indice)},${y(ponto.valor)}`).join(" ")}
            />
            {serie.pontos.map((ponto, indice) => {
              const mudou = indice === 0
                || indice === serie.pontos.length - 1
                || ponto.valor !== serie.pontos[indice - 1].valor;
              return (
                <g key={indice}>
                  <circle
                    cx={x(indice)} cy={y(ponto.valor)} r={3}
                    fill={CORES[indiceSerie % CORES.length]}
                  >
                    <title>{`${serie.nome} — ${ponto.rotulo}: ${ponto.valor.toLocaleString("pt-BR")}`}</title>
                  </circle>
                  {rotularPontos && mudou && (
                    <text
                      x={x(indice)}
                      y={y(ponto.valor) - 7}
                      textAnchor={indice === 0 ? "start" : indice === serie.pontos.length - 1 ? "end" : "middle"}
                      className="text-[13px] font-semibold tabular-nums"
                      fill={CORES[indiceSerie % CORES.length]}
                    >
                      {ponto.valor.toLocaleString("pt-BR")}
                    </text>
                  )}
                </g>
              );
            })}
          </g>
        ))}
        {rotulos.map((ponto, indice) =>
          quantidade <= 8 || indice % Math.ceil(quantidade / 8) === 0 ? (
            <text
              key={indice}
              x={x(indice)} y={altura - 8} textAnchor="middle"
              className="fill-zinc-400 text-[12px]"
            >
              {ponto.rotulo}
            </text>
          ) : null,
        )}
      </svg>
      <div className="mt-1 flex flex-wrap gap-3">
        {visiveis.map((serie, indice) => (
          <span key={serie.nome} className="flex items-center gap-1.5 text-xs text-zinc-500 dark:text-zinc-400">
            <span className="h-2 w-2 rounded-full" style={{ background: CORES[indice % CORES.length] }} />
            {serie.nome}
          </span>
        ))}
      </div>
    </div>
  );
}

export function BarraDupla({
  rotulo,
  nomeA,
  valorA,
  nomeB,
  valorB,
  formato = (valor: number) => valor.toLocaleString("pt-BR"),
}: {
  rotulo: string;
  nomeA: string;
  valorA: number;
  nomeB: string;
  valorB: number;
  formato?: (valor: number) => string;
}) {
  const maximo = Math.max(valorA, valorB, 1);
  return (
    <div className="py-2">
      <p className="mb-1.5 text-xs font-medium uppercase tracking-wide text-zinc-500 dark:text-zinc-400">{rotulo}</p>
      {[
        { nome: nomeA, valor: valorA, cor: "bg-indigo-500" },
        { nome: nomeB, valor: valorB, cor: "bg-emerald-500" },
      ].map((barra) => (
        <div key={barra.nome} className="mb-1 flex items-center gap-2">
          <span className="w-28 truncate text-xs text-zinc-500 dark:text-zinc-400" title={barra.nome}>
            {barra.nome}
          </span>
          <div className="h-4 flex-1 overflow-hidden rounded bg-zinc-100 dark:bg-zinc-800">
            <div
              className={`h-full rounded ${barra.cor}`}
              style={{ width: `${Math.max(2, (barra.valor / maximo) * 100)}%` }}
            />
          </div>
          <span className="w-16 text-right text-xs tabular-nums">{formato(barra.valor)}</span>
        </div>
      ))}
    </div>
  );
}
