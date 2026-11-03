/** Gráficos SVG leves — sem dependências externas (PRD §23: consultas enxutas). */
import { useLayoutEffect, useState } from "react";

/**
 * Largura (px) do contêiner de um gráfico, medida no navegador e atualizada quando ele
 * muda de tamanho (girar o celular, abrir a gaveta). `0` = ainda sem medida (1º render,
 * jsdom): quem usa fica no desenho de sempre (o do desktop). A ref é por callback, então
 * mede também o elemento que só aparece depois (estado vazio → gráfico).
 *
 * Para quê: um SVG com viewBox fixo encolhe junto com o texto. No celular, quem usa passa
 * a largura medida como viewBox e o texto sai no tamanho nominal (12–13 px).
 */
export function useLarguraDoConteiner<T extends HTMLElement = HTMLDivElement>(): {
  ref: (elemento: T | null) => void;
  largura: number;
} {
  const [elemento, setElemento] = useState<T | null>(null);
  const [largura, setLargura] = useState(0);
  useLayoutEffect(() => {
    if (!elemento) return undefined;
    const medir = () => {
      const atual = Math.round(elemento.clientWidth);
      setLargura((antes) => (antes === atual ? antes : atual));
    };
    medir();
    if (typeof ResizeObserver === "undefined") {
      window.addEventListener("resize", medir);
      return () => window.removeEventListener("resize", medir);
    }
    const observador = new ResizeObserver(medir);
    observador.observe(elemento);
    return () => observador.disconnect();
  }, [elemento]);
  return { ref: setElemento, largura };
}

export interface PontoSerie {
  rotulo: string; // data formatada (ou a categoria do eixo X, ex. o ano)
  /** `null` = sem resultado naquele ponto: vira LACUNA na linha, nunca 0. */
  valor: number | null;
}

export interface SerieLinha {
  nome: string;
  pontos: PontoSerie[];
  /** Linha tracejada (ex.: metas). A legenda também mostra o traço. */
  tracejada?: boolean;
  /** Cor própria; sem ela, a paleta pela posição da série. */
  cor?: string;
}

// Paleta de séries da identidade v2 (docs/design/IDENTIDADE-VISUAL-V2.md): violeta da
// marca (Leitura), teal-600 (Matemática), âmbar-600, vermelho-600, azul-600, rosa-600,
// ardósia-500 e roxo-600. Todas com >= 3:1 sobre o branco e sobre o cartão escuro
// (#1A1C38) — o traço e o marcador são elementos gráficos (WCAG 1.4.11). As 4 primeiras
// servem aos usos de sempre; as demais, às comparações com mais séries.
const CORES = ["#6C5CE7", "#0D9488", "#D97706", "#DC2626", "#0284C7", "#DB2777", "#64748B", "#9333EA"];

const formatoPadrao = (valor: number) => valor.toLocaleString("pt-BR");

/**
 * Linha(s) de evolução.
 *
 * Uso de sempre: as séries alinhadas pela POSIÇÃO do ponto, eixo Y a partir de 0.
 * Extensões (todas opcionais — sem elas o desenho é o mesmo de antes):
 *  - `eixoX`: categorias do eixo (ex. anos); cada ponto vai para a posição do seu
 *    `rotulo` — séries com anos desalinhados e lacunas (`valor: null` ou o ano que
 *    a série não tem) ficam certas: a linha quebra, nunca liga os vizinhos;
 *  - `minimo`/`maximo`: faixa do eixo Y (ex. 40–90% para a variação ficar legível);
 *  - série `tracejada` e `cor`; até 8 cores na paleta;
 *  - `formato` dos números (ex. "33,5%"), `rotulo` (texto alternativo do SVG) e
 *    `tabela` (legenda de uma tabela equivalente, num "ver os números");
 *  - `larguraViewBox`: a largura REAL do contêiner, medida por quem usa (celular).
 */
export function GraficoLinha({
  series,
  altura = 180,
  eixoX,
  minimo,
  maximo: maximoFixo,
  formato = formatoPadrao,
  rotulo = "Gráfico de evolução",
  tabela,
  larguraViewBox,
}: {
  series: SerieLinha[];
  altura?: number;
  eixoX?: string[];
  minimo?: number;
  maximo?: number;
  formato?: (valor: number) => string;
  rotulo?: string;
  tabela?: string;
  /**
   * Largura do viewBox (sem ela, 500). No celular, quem mede o contêiner passa a largura
   * real: o desenho fica 1:1 e o texto sai no tamanho nominal, em vez de encolher junto
   * com o SVG (500 → 270 px deixava os números com ~6 px). Com ela, o eixo X mostra só as
   * datas que cabem (uma a cada ~52 px) e as das pontas se alinham pela borda: a primeira
   * não encosta no "0" do eixo Y e a última não é cortada. Sem ela, o desenho de sempre.
   */
  larguraViewBox?: number;
}) {
  const visiveis = series.filter(
    (serie) => serie.pontos.length > 0 && serie.pontos.some((ponto) => ponto.valor != null),
  );
  if (visiveis.length === 0) {
    return <p className="py-8 text-center text-sm text-zinc-400">Sem dados suficientes para o gráfico.</p>;
  }
  // viewBox menor => fontes, pontos e linhas renderizam MAIORES (o SVG escala
  // para a largura do container). Com 2 gráficos por linha (~450px), os números
  // saem em ~12px, legíveis.
  const largura = larguraViewBox ?? 500;
  // topo folgado: os rótulos de valor ficam ACIMA do ponto; nos pontos de valor
  // MÁXIMO (colados no teto) o número precisa caber sem ser cortado pela borda.
  // Com eixoX (anos), o último rótulo ("2030") é largo: mais folga à direita para
  // não ser cortado. Sem eixoX, a margem de sempre.
  const margem = { esquerda: 46, direita: eixoX ? 24 : 12, topo: 30, base: 26 };
  const valores = visiveis.flatMap((serie) =>
    serie.pontos.flatMap((ponto) => (ponto.valor == null ? [] : [ponto.valor])));
  const maximo = maximoFixo ?? Math.max(1, ...valores);
  const base = minimo ?? 0;
  const quantidade = eixoX ? eixoX.length : Math.max(...visiveis.map((serie) => serie.pontos.length));
  // Posição no eixo X: pela categoria (eixoX) ou, como sempre, pelo índice do ponto.
  const posicao = (ponto: PontoSerie, indice: number) => (eixoX ? eixoX.indexOf(ponto.rotulo) : indice);

  const x = (indice: number) =>
    margem.esquerda +
    (quantidade <= 1 ? 0 : (indice / (quantidade - 1)) * (largura - margem.esquerda - margem.direita));
  const y = (valor: number) =>
    margem.topo + (1 - (valor - base) / (maximo - base)) * (altura - margem.topo - margem.base);

  const rotulos = eixoX ?? visiveis[0].pontos.map((ponto) => ponto.rotulo);
  // Rotula os pontos com o VALOR visível só quando há UMA série (mini-gráfico
  // por métrica) — assim os números não se sobrepõem entre séries. Mostra no
  // 1º, no último e sempre que o valor MUDA (pula os trechos planos repetidos).
  const rotularPontos = visiveis.length === 1;
  const corDa = (serie: SerieLinha, indice: number) => serie.cor ?? CORES[indice % CORES.length];
  // Rótulos do eixo X: até 8 no desenho de sempre; com a largura medida, os que cabem.
  const maxRotulosX = larguraViewBox == null
    ? 8
    : Math.max(2, Math.floor((largura - margem.esquerda - margem.direita) / 52) + 1);
  const ancoraDoRotuloX = (indice: number) => {
    if (larguraViewBox == null) return "middle";
    // Um ponto só fica na margem esquerda (x de `x(0)`): a data alinha pela borda dela.
    return indice === 0 ? "start" : indice === quantidade - 1 ? "end" : "middle";
  };

  /**
   * Com a largura medida (celular), rótulo de valor em todo ponto que muda empilharia
   * números (série acumulada com coleta diária muda todo dia). Se as mudanças passam do
   * que cabe no eixo, rotula só o primeiro, o último e o maior — a dica (title) de cada
   * ponto continua. `null` = sem corte (o desenho de sempre).
   */
  function indicesRotulaveis(serie: SerieLinha): Set<number> | null {
    if (larguraViewBox == null) return null;
    const validos = serie.pontos
      .map((ponto, indice) => ({ ponto, indice }))
      .filter(({ ponto, indice }) => ponto.valor != null && posicao(ponto, indice) >= 0);
    const mudancas = validos.filter(({ ponto, indice }, i) =>
      i === 0 || i === validos.length - 1 || ponto.valor !== serie.pontos[indice - 1]?.valor).length;
    if (mudancas <= maxRotulosX || validos.length === 0) return null;
    const maior = validos.reduce((a, b) => ((b.ponto.valor as number) > (a.ponto.valor as number) ? b : a));
    return new Set([validos[0].indice, validos[validos.length - 1].indice, maior.indice]);
  }

  /**
   * Trechos contínuos da série. A lacuna quebra a linha: valor nulo, ponto fora do
   * eixo e — com `eixoX` — a categoria que a série simplesmente não tem (ex.: 2023 e
   * 2025 sem ponto de 2024): ligar os vizinhos sugeriria um valor que não existe.
   */
  function trechos(serie: SerieLinha): string[] {
    const saida: string[][] = [[]];
    let anterior: number | null = null;
    serie.pontos.forEach((ponto, indice) => {
      const p = posicao(ponto, indice);
      if (ponto.valor == null || p < 0) {
        if (saida[saida.length - 1].length > 0) saida.push([]);
        anterior = null;
        return;
      }
      if (eixoX && anterior != null && p !== anterior + 1 && saida[saida.length - 1].length > 0) {
        saida.push([]);
      }
      saida[saida.length - 1].push(`${x(p)},${y(ponto.valor)}`);
      anterior = p;
    });
    return saida.filter((t) => t.length > 0).map((t) => t.join(" "));
  }

  return (
    <div>
      <svg viewBox={`0 0 ${largura} ${altura}`} className="w-full" role="img" aria-label={rotulo}>
        {[0, 0.5, 1].map((fracao) => (
          <g key={fracao}>
            <line
              x1={margem.esquerda} x2={largura - margem.direita}
              y1={y(base + (maximo - base) * fracao)} y2={y(base + (maximo - base) * fracao)}
              className="stroke-zinc-200 dark:stroke-zinc-700" strokeWidth={1}
            />
            <text
              x={margem.esquerda - 6} y={y(base + (maximo - base) * fracao) + 4} textAnchor="end"
              className="fill-zinc-400 text-[13px] tabular-nums"
            >
              {Math.round(base + (maximo - base) * fracao).toLocaleString("pt-BR")}
            </text>
          </g>
        ))}
        {visiveis.map((serie, indiceSerie) => {
          const soRotular = indicesRotulaveis(serie);
          return (
          <g key={serie.nome}>
            {trechos(serie).map((pontos, indiceTrecho) => (
              <polyline
                key={indiceTrecho}
                fill="none"
                stroke={corDa(serie, indiceSerie)}
                strokeWidth={2}
                strokeDasharray={serie.tracejada ? "6 4" : undefined}
                points={pontos}
              />
            ))}
            {serie.pontos.map((ponto, indice) => {
              const p = posicao(ponto, indice);
              if (ponto.valor == null || p < 0) return null;
              const mudou = indice === 0
                || indice === serie.pontos.length - 1
                || ponto.valor !== serie.pontos[indice - 1].valor;
              const ancora = eixoX
                ? (p === 0 ? "start" : p === quantidade - 1 ? "end" : "middle")
                : (indice === 0 ? "start" : indice === serie.pontos.length - 1 ? "end" : "middle");
              return (
                <g key={indice}>
                  <circle
                    cx={x(p)} cy={y(ponto.valor)} r={3}
                    fill={corDa(serie, indiceSerie)}
                  >
                    <title>{`${serie.nome} — ${ponto.rotulo}: ${formato(ponto.valor)}`}</title>
                  </circle>
                  {rotularPontos && mudou && (soRotular == null || soRotular.has(indice)) && (
                    <text
                      x={x(p)}
                      y={y(ponto.valor) - 7}
                      textAnchor={ancora}
                      className="text-[13px] font-semibold tabular-nums"
                      fill={corDa(serie, indiceSerie)}
                    >
                      {formato(ponto.valor)}
                    </text>
                  )}
                </g>
              );
            })}
          </g>
          );
        })}
        {rotulos.map((texto, indice) =>
          quantidade <= maxRotulosX || indice % Math.ceil(quantidade / maxRotulosX) === 0 ? (
            <text
              key={indice}
              x={x(indice)} y={altura - 8} textAnchor={ancoraDoRotuloX(indice)}
              className="fill-zinc-400 text-[12px]"
            >
              {texto}
            </text>
          ) : null,
        )}
      </svg>
      <div className="mt-1 flex flex-wrap gap-3">
        {visiveis.map((serie, indice) => (
          <span key={serie.nome} className="flex items-center gap-1.5 text-xs text-zinc-500 dark:text-zinc-400">
            {serie.tracejada ? (
              <span className="inline-block w-4 border-t-2 border-dashed" style={{ borderColor: corDa(serie, indice) }}
                    aria-hidden="true" />
            ) : (
              <span className="h-2 w-2 rounded-full" style={{ background: corDa(serie, indice) }} />
            )}
            {serie.nome}{serie.tracejada ? " (tracejada)" : ""}
          </span>
        ))}
      </div>
      {tabela && <TabelaDasSeries legenda={tabela} series={series} categorias={rotulos} formato={formato} />}
    </div>
  );
}

/** Tabela equivalente ao gráfico (acessibilidade): "sem resultado" ≠ 0. */
function TabelaDasSeries({ legenda, series, categorias, formato }: {
  legenda: string; series: SerieLinha[]; categorias: string[]; formato: (valor: number) => string;
}) {
  return (
    <details className="mt-2 text-xs">
      <summary className="cursor-pointer text-zinc-500">Ver os números do gráfico</summary>
      <div className="mt-1 overflow-x-auto">
        <table className="w-full">
          <caption className="sr-only">{legenda}</caption>
          <thead>
            <tr className="text-left text-zinc-500">
              <th className="py-1 pr-2 font-medium">Série</th>
              {categorias.map((c) => <th key={c} className="py-1 pr-2 font-medium tabular-nums">{c}</th>)}
            </tr>
          </thead>
          <tbody>
            {series.map((serie) => {
              const porRotulo = new Map(serie.pontos.map((p) => [p.rotulo, p.valor]));
              return (
                <tr key={serie.nome} className="border-t border-zinc-100 dark:border-zinc-800">
                  <th scope="row" className="py-1 pr-2 text-left font-normal">{serie.nome}</th>
                  {categorias.map((c) => {
                    const v = porRotulo.get(c);
                    return (
                      <td key={c} className="py-1 pr-2 tabular-nums">
                        {v == null ? <span className="text-zinc-400">{porRotulo.has(c) ? "sem resultado" : "—"}</span> : formato(v)}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </details>
  );
}

export interface SegmentoBarra {
  nome: string;
  /** `null` = sem resultado (não desenha e a tabela diz "sem resultado", nunca 0). */
  valor: number | null;
}

// Escala sequencial (um tom só, do claro ao escuro): a ordem dos níveis fica
// visível sem depender de "cor boa × cor ruim"; a legenda e a tabela dizem o nível.
// Os tons 100 a 900 da escala violeta da v2 (a `indigo` remapeada do tailwind.config.js).
const CORES_EMPILHADA = ["#E8E4FD", "#D3CBFB", "#B5AAF7", "#9688F2", "#7F6FEC", "#6C5CE7", "#5A4AD4",
  "#4637AE", "#1F2250"];

/**
 * Barras empilhadas horizontais (ex.: distribuição por nível, que soma 100%). Cada
 * segmento ocupa a sua parte do total da barra; a legenda e a tabela equivalente
 * dão os números. Barra sem nenhum valor diz "sem resultado" — nunca uma barra
 * vazia que pareça 0. `tabela={false}` tira a tabela equivalente embutida (uma coluna
 * por segmento) quando quem usa dá a sua — ex.: com 10 ou 11 níveis, uma tabela com os
 * níveis nas LINHAS, que cabe no celular sem rolagem lateral.
 */
export function BarraEmpilhada({
  barras,
  rotulo,
  cores = CORES_EMPILHADA,
  formato = formatoPadrao,
  tabela = true,
}: {
  barras: { rotulo: string; segmentos: SegmentoBarra[] }[];
  rotulo: string;
  cores?: string[];
  formato?: (valor: number) => string;
  tabela?: boolean;
}) {
  if (barras.length === 0) {
    return <p className="py-4 text-center text-sm text-zinc-400">Sem resultado para o gráfico.</p>;
  }
  const nomes = barras[0].segmentos.map((s) => s.nome);
  const cor = (indice: number) => cores[indice % cores.length];
  return (
    <figure role="group" aria-label={rotulo} className="space-y-2">
      {barras.map((barra) => {
        const total = barra.segmentos.reduce((soma, s) => soma + (s.valor ?? 0), 0);
        const semDado = barra.segmentos.every((s) => s.valor == null) || total <= 0;
        const descricao = barra.segmentos
          .map((s) => `${s.nome}: ${s.valor == null ? "sem resultado" : formato(s.valor)}`)
          .join("; ");
        return (
          <div key={barra.rotulo}>
            <p className="mb-1 text-xs text-zinc-600 dark:text-zinc-400">{barra.rotulo}</p>
            {semDado ? (
              <p className="text-xs text-zinc-500" data-testid="barra-sem-resultado">sem resultado</p>
            ) : (
              <div className="flex h-5 w-full overflow-hidden rounded bg-zinc-100 dark:bg-zinc-800"
                   role="img" aria-label={`${barra.rotulo} — ${descricao}`}>
                {barra.segmentos.map((s, indice) =>
                  s.valor == null || s.valor <= 0 ? null : (
                    <div key={s.nome} className="h-full" title={`${s.nome}: ${formato(s.valor)}`}
                         style={{ width: `${(s.valor / total) * 100}%`, background: cor(indice) }} />
                  ),
                )}
              </div>
            )}
          </div>
        );
      })}
      <figcaption className="flex flex-wrap gap-x-3 gap-y-1 pt-1">
        {nomes.map((nome, indice) => (
          <span key={nome} className="flex items-center gap-1.5 text-xs text-zinc-500 dark:text-zinc-400">
            <span className="h-2.5 w-2.5 rounded-sm" style={{ background: cor(indice) }} aria-hidden="true" />
            {nome}
          </span>
        ))}
      </figcaption>
      {tabela && (
        <details className="text-xs">
          <summary className="cursor-pointer text-zinc-500">Ver os números do gráfico</summary>
          <div className="mt-1 overflow-x-auto">
            <table className="w-full">
              <caption className="sr-only">{rotulo}</caption>
              <thead>
                <tr className="text-left text-zinc-500">
                  <th className="py-1 pr-2 font-medium" />
                  {nomes.map((nome) => <th key={nome} className="py-1 pr-2 font-medium">{nome}</th>)}
                </tr>
              </thead>
              <tbody>
                {barras.map((barra) => (
                  <tr key={barra.rotulo} className="border-t border-zinc-100 dark:border-zinc-800">
                    <th scope="row" className="py-1 pr-2 text-left font-normal">{barra.rotulo}</th>
                    {barra.segmentos.map((s) => (
                      <td key={s.nome} className="py-1 pr-2 tabular-nums">
                        {s.valor == null ? <span className="text-zinc-400">sem resultado</span> : formato(s.valor)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}
    </figure>
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
