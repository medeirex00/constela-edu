/**
 * Gráfico SEMANAL de participação (identidade visual v2 — Visão Geral, referência 1).
 *
 * Linhas suaves de % (eixo fixo 0–100%) por semana, uma por plataforma, com a área
 * suave sob a série principal, grade fina, o rótulo do último ponto de cada série e a
 * semana corrente destacada como "em curso". SVG puro, sem dependências: o desenho
 * escala com a largura do cartão (viewBox), então serve de 820 a 1440 px.
 *
 * No celular (contêiner < 480 px) o viewBox passa a ser a largura MEDIDA do contêiner:
 * o desenho fica 1:1 e o texto sai no tamanho nominal (11–12 px) — com o viewBox de 580
 * reduzido a ~300 px, eixos e datas caíam para ~6 px. O eixo X mostra então só as semanas
 * que cabem (uma sim, uma não, contando da semana em curso, que sempre aparece); todas
 * continuam na dica de cada ponto e na tabela do leitor de tela. Sem medida (1º render,
 * jsdom) e em qualquer contêiner de tablet/desktop, o desenho de sempre.
 *
 * Regras de dado (as mesmas do backend e do `Grafico.tsx`):
 *  - `null` é SEM COLETA: a linha QUEBRA ali (lacuna), nunca desce a 0 nem liga os
 *    vizinhos por cima do buraco;
 *  - o gráfico não calcula nada: desenha os percentuais que chegaram prontos.
 *
 * Acessibilidade: o SVG é `role="img"` com um texto alternativo que resume as séries
 * (o último valor medido de cada uma) e há uma tabela só para leitor de tela com
 * todos os valores, semana a semana ("sem coleta" onde não há medida). A legenda
 * repete o nome de cada série em texto, para a cor não ser o único portador.
 *
 * Componente NOVO (não mexe no `Grafico.tsx`, que tem snapshots em teste).
 */
import { useId } from "react";

import { useLarguraDoConteiner } from "./Grafico";

export interface SemanaDoGrafico {
  /** Segunda-feira da semana (AAAA-MM-DD). */
  inicio: string;
  /** Domingo da semana (AAAA-MM-DD). */
  fim: string;
}

export interface SerieSemanal {
  /** Nome completo (legenda, texto alternativo e tabela), ex.: "Leitura · Elefante Letrado". */
  nome: string;
  /** Cor da linha, da área e dos pontos (hex). */
  cor: string;
  /** Cor do texto sobre a pílula do último valor (contraste com `cor`). Padrão: branco. */
  corTexto?: string;
  /** Percentual (0–100) por semana, na MESMA ordem de `semanas`; `null` = sem coleta. */
  valores: (number | null)[];
  /** Quantos alunos por semana (para a tabela e as dicas); opcional. */
  alunos?: (number | null)[];
  /** Pinta a área sob a linha com um degradê suave. */
  area?: boolean;
}

const LARGURA = 580;
const MARGEM = { esquerda: 46, direita: 64, topo: 18, base: 42 };
const MARCAS_Y = [0, 25, 50, 75, 100];
/** Contêiner mais estreito que isto = celular. O menor contêiner do gráfico no tablet e
 *  no desktop é ~540 px (640 px de tela); no celular, de ~300 a ~380 px. */
const LIMITE_CELULAR = 480;
/** Menor viewBox no celular (abaixo disso o desenho volta a encolher, sem quebrar). */
const LARGURA_MINIMA_CELULAR = 260;
/** Espaço de um rótulo de semana ("07/09", 12 px) com folga, no desenho 1:1. */
const ESPACO_ROTULO_SEMANA = 44;

/** "2026-10-05" → "05/10" (sem passar por `Date`: nada de fuso num dia). */
function diaMes(iso: string): string {
  const [, mes, dia] = iso.slice(0, 10).split("-");
  return mes && dia ? `${dia}/${mes}` : iso;
}

/** 45.3 → "45,3%"; 100 → "100%". */
export function formatarPercentual(valor: number): string {
  return `${valor.toLocaleString("pt-BR", { maximumFractionDigits: 1 })}%`;
}

function limitar(valor: number): number {
  return Math.max(0, Math.min(100, valor));
}

/**
 * Curva monotônica em X (a mesma ideia do `curveMonotoneX` do d3, Fritsch–Carlson):
 * suave, mas SEM ultrapassar os pontos — a linha nunca passa de 100% nem fica
 * abaixo de 0% entre duas semanas, e um platô continua plano.
 */
export function caminhoMonotono(pontos: [number, number][]): string {
  const n = pontos.length;
  if (n === 0) return "";
  const inicio = `M${pontos[0][0]},${pontos[0][1]}`;
  if (n === 1) return inicio;
  if (n === 2) return `${inicio}L${pontos[1][0]},${pontos[1][1]}`;

  const secantes: number[] = [];
  for (let i = 0; i < n - 1; i++) {
    const dx = pontos[i + 1][0] - pontos[i][0];
    secantes.push(dx === 0 ? 0 : (pontos[i + 1][1] - pontos[i][1]) / dx);
  }
  const tangentes: number[] = new Array(n).fill(0);
  for (let i = 1; i < n - 1; i++) {
    const h0 = pontos[i][0] - pontos[i - 1][0];
    const h1 = pontos[i + 1][0] - pontos[i][0];
    const s0 = secantes[i - 1];
    const s1 = secantes[i];
    const p = (s0 * h1 + s1 * h0) / (h0 + h1 || 1);
    tangentes[i] = (Math.sign(s0) + Math.sign(s1)) * Math.min(Math.abs(s0), Math.abs(s1), 0.5 * Math.abs(p)) || 0;
  }
  // Pontas: tangente de 3 pontos "espelhada" (como o d3), sem passar da secante.
  tangentes[0] = (3 * secantes[0] - tangentes[1]) / 2;
  tangentes[n - 1] = (3 * secantes[n - 2] - tangentes[n - 2]) / 2;
  if (Math.sign(tangentes[0]) !== Math.sign(secantes[0])) tangentes[0] = 0;
  if (Math.sign(tangentes[n - 1]) !== Math.sign(secantes[n - 2])) tangentes[n - 1] = 0;

  let d = inicio;
  for (let i = 0; i < n - 1; i++) {
    const [x0, y0] = pontos[i];
    const [x1, y1] = pontos[i + 1];
    const terco = (x1 - x0) / 3;
    d += `C${x0 + terco},${y0 + terco * tangentes[i]} ${x1 - terco},${y1 - terco * tangentes[i + 1]} ${x1},${y1}`;
  }
  return d;
}

/** Trechos contínuos (índices) de uma série: cada `null` quebra a linha. */
export function trechosContinuos(valores: (number | null)[]): number[][] {
  const saida: number[][] = [];
  let atual: number[] = [];
  valores.forEach((valor, indice) => {
    if (valor == null || Number.isNaN(valor)) {
      if (atual.length) saida.push(atual);
      atual = [];
      return;
    }
    atual.push(indice);
  });
  if (atual.length) saida.push(atual);
  return saida;
}

function ultimoMedido(valores: (number | null)[]): number {
  for (let i = valores.length - 1; i >= 0; i--) if (valores[i] != null) return i;
  return -1;
}

export function GraficoSemanal({
  semanas,
  series,
  titulo,
  ultimaEmCurso = true,
  altura = 260,
}: {
  semanas: SemanaDoGrafico[];
  series: SerieSemanal[];
  /** Nome do gráfico (começo do texto alternativo e legenda da tabela). */
  titulo: string;
  /** A última semana ainda está em andamento (destaca a coluna e marca "em curso"). */
  ultimaEmCurso?: boolean;
  altura?: number;
}) {
  const idBase = useId().replace(/[^a-zA-Z0-9_-]/g, "");
  const { ref: refConteiner, largura: larguraMedida } = useLarguraDoConteiner();
  const quantidade = semanas.length;
  const comDado = series.filter((serie) => serie.valores.some((valor) => valor != null));

  if (quantidade === 0 || comDado.length === 0) {
    return (
      <p className="py-10 text-center text-sm text-zinc-500 dark:text-zinc-400">
        Sem coleta nas semanas mostradas.
      </p>
    );
  }

  // Celular: desenho 1:1 na largura medida, um pouco mais baixo (proporção de ~0,72).
  const celular = larguraMedida > 0 && larguraMedida < LIMITE_CELULAR;
  const largura = celular ? Math.max(LARGURA_MINIMA_CELULAR, larguraMedida) : LARGURA;
  const alturaDesenho = celular ? Math.min(altura, Math.max(200, Math.round(largura * 0.72))) : altura;

  const larguraUtil = largura - MARGEM.esquerda - MARGEM.direita;
  const alturaUtil = alturaDesenho - MARGEM.topo - MARGEM.base;
  const passo = quantidade <= 1 ? 0 : larguraUtil / (quantidade - 1);
  // Rótulos do eixo X: todos no desenho de sempre; no celular, os que cabem, contando da
  // última semana (a "em curso" sempre aparece).
  const saltoRotulo = celular && passo > 0 ? Math.max(1, Math.ceil(ESPACO_ROTULO_SEMANA / passo)) : 1;
  const x = (indice: number) =>
    MARGEM.esquerda + (quantidade <= 1 ? larguraUtil / 2 : indice * passo);
  const y = (valor: number) => MARGEM.topo + (1 - limitar(valor) / 100) * alturaUtil;
  const base = y(0);

  // Rótulos do último ponto: afastados um do outro quando caem na mesma altura.
  const rotulos = comDado
    .map((serie) => {
      const indice = ultimoMedido(serie.valores);
      return { serie, indice, valor: serie.valores[indice] as number, yAlvo: y(serie.valores[indice] as number) };
    })
    .sort((a, b) => a.yAlvo - b.yAlvo);
  for (let i = 1; i < rotulos.length; i++) {
    const minimo = rotulos[i - 1].yAlvo + 20;
    if (rotulos[i].yAlvo < minimo) rotulos[i].yAlvo = minimo;
  }
  // Cabem no quadro (o de baixo não passa da base; empurra os de cima se preciso).
  for (let i = rotulos.length - 1; i >= 0; i--) {
    const teto = i === rotulos.length - 1 ? base : rotulos[i + 1].yAlvo - 20;
    if (rotulos[i].yAlvo > teto) rotulos[i].yAlvo = teto;
    if (rotulos[i].yAlvo < MARGEM.topo) rotulos[i].yAlvo = MARGEM.topo;
  }

  const textoSemana = (indice: number) => {
    const semana = semanas[indice];
    const emCurso = ultimaEmCurso && indice === quantidade - 1;
    return `${diaMes(semana.inicio)} a ${diaMes(semana.fim)}${emCurso ? " (em curso)" : ""}`;
  };

  const resumo = series
    .map((serie) => {
      const indice = ultimoMedido(serie.valores);
      if (indice < 0) return `${serie.nome}: sem coleta no intervalo`;
      return `${serie.nome}: ${formatarPercentual(serie.valores[indice] as number)} na semana de ${textoSemana(indice)}`;
    })
    .join("; ");
  const textoAlternativo =
    `${titulo}, ${quantidade} semanas, de ${diaMes(semanas[0].inicio)} a ${diaMes(semanas[quantidade - 1].fim)}. ` +
    `Último valor medido — ${resumo}. Semanas sem coleta ficam vazias.`;

  const xEmCurso = ultimaEmCurso && quantidade > 1 ? x(quantidade - 1) - passo / 2 : null;

  return (
    <div ref={refConteiner}>
      <svg
        viewBox={`0 0 ${largura} ${alturaDesenho}`}
        className="block h-auto w-full overflow-visible"
        role="img"
        aria-label={textoAlternativo}
      >
        <defs>
          {comDado
            .filter((serie) => serie.area)
            .map((serie, i) => (
              <linearGradient key={serie.nome} id={`${idBase}-area-${i}`} x1="0" x2="0" y1="0" y2="1">
                <stop offset="0%" stopColor={serie.cor} stopOpacity={0.24} />
                <stop offset="100%" stopColor={serie.cor} stopOpacity={0} />
              </linearGradient>
            ))}
        </defs>

        {/* Semana corrente: faixa lavanda clarinha atrás de tudo. */}
        {xEmCurso != null && (
          <rect
            x={xEmCurso}
            y={MARGEM.topo - 6}
            width={x(quantidade - 1) + 14 - xEmCurso}
            height={alturaUtil + 12}
            rx={10}
            className="fill-indigo-50 dark:fill-indigo-500/10"
          />
        )}

        {/* Grade fina e eixo Y (0–100%). */}
        {MARCAS_Y.map((marca) => (
          <g key={marca}>
            <line
              x1={MARGEM.esquerda}
              x2={largura - MARGEM.direita + 14}
              y1={y(marca)}
              y2={y(marca)}
              strokeWidth={1}
              strokeDasharray={marca === 0 ? undefined : "3 5"}
              className="stroke-zinc-200 dark:stroke-zinc-700"
            />
            <text
              x={MARGEM.esquerda - 10}
              y={y(marca) + 4}
              textAnchor="end"
              className="fill-zinc-500 text-[12px] tabular-nums dark:fill-zinc-400"
            >
              {marca}%
            </text>
          </g>
        ))}

        {/* Eixo X: a segunda-feira de cada semana; a corrente diz "em curso". No celular,
            só as semanas que cabem (a corrente sempre). */}
        {semanas.map((semana, indice) => {
          const emCurso = ultimaEmCurso && indice === quantidade - 1;
          if ((quantidade - 1 - indice) % saltoRotulo !== 0) return null;
          return (
            <g key={semana.inicio} data-rotulo-semana="">
              <text
                x={x(indice)}
                y={alturaDesenho - 22}
                textAnchor="middle"
                className={`text-[12px] tabular-nums ${
                  emCurso ? "fill-indigo-700 font-semibold dark:fill-indigo-300" : "fill-zinc-500 dark:fill-zinc-400"
                }`}
              >
                {diaMes(semana.inicio)}
              </text>
              {emCurso && (
                <text
                  x={x(indice)}
                  y={alturaDesenho - 7}
                  textAnchor="middle"
                  className="fill-indigo-700 text-[11px] font-medium dark:fill-indigo-300"
                >
                  em curso
                </text>
              )}
            </g>
          );
        })}

        {/* Séries: área (opcional) + linha suave por trecho contínuo + pontos. */}
        {comDado.map((serie) => {
          const indiceArea = comDado.filter((s) => s.area).indexOf(serie);
          const trechos = trechosContinuos(serie.valores);
          return (
            <g key={serie.nome} data-serie={serie.nome}>
              {trechos.map((trecho) => {
                const pontos = trecho.map((i) => [x(i), y(serie.valores[i] as number)] as [number, number]);
                const linha = caminhoMonotono(pontos);
                const primeiro = pontos[0];
                const ultimo = pontos[pontos.length - 1];
                return (
                  <g key={trecho[0]}>
                    {serie.area && pontos.length > 1 && (
                      <path
                        d={`${linha}L${ultimo[0]},${base}L${primeiro[0]},${base}Z`}
                        fill={`url(#${idBase}-area-${indiceArea})`}
                        stroke="none"
                      />
                    )}
                    {pontos.length > 1 && (
                      <path
                        data-trecho=""
                        d={linha}
                        fill="none"
                        stroke={serie.cor}
                        strokeWidth={3}
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      />
                    )}
                  </g>
                );
              })}
              {serie.valores.map((valor, indice) => {
                if (valor == null) return null;
                const alunos = serie.alunos?.[indice];
                const extra = alunos != null ? ` (${alunos.toLocaleString("pt-BR")} alunos)` : "";
                return (
                  <circle
                    key={indice}
                    data-ponto=""
                    cx={x(indice)}
                    cy={y(valor)}
                    r={4.5}
                    fill={serie.cor}
                    strokeWidth={2}
                    className="stroke-white dark:stroke-zinc-900"
                  >
                    <title>{`${serie.nome} — semana de ${textoSemana(indice)}: ${formatarPercentual(valor)}${extra}`}</title>
                  </circle>
                );
              })}
            </g>
          );
        })}

        {/* Pílula com o último valor medido de cada série. */}
        {rotulos.map(({ serie, indice, valor, yAlvo }) => {
          const texto = formatarPercentual(valor);
          const larguraPilula = texto.length * 7.4 + 14;
          const xPilula = Math.min(x(indice) + 9, largura - larguraPilula - 2);
          return (
            <g key={serie.nome} data-rotulo-final={serie.nome}>
              <rect x={xPilula} y={yAlvo - 10} width={larguraPilula} height={20} rx={10} fill={serie.cor} />
              <text
                x={xPilula + larguraPilula / 2}
                y={yAlvo + 4}
                textAnchor="middle"
                fill={serie.corTexto ?? "#FFFFFF"}
                className="text-[12px] font-bold tabular-nums"
              >
                {texto}
              </text>
            </g>
          );
        })}
      </svg>

      {/* Legenda em texto (a cor não é o único portador da informação). */}
      <ul className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-2 text-xs font-medium text-zinc-600 dark:text-zinc-300">
        {series.map((serie) => (
          <li key={serie.nome} className="inline-flex items-center gap-2">
            <span aria-hidden className="relative inline-flex h-2.5 w-5 items-center">
              <span className="h-[3px] w-full rounded-full" style={{ background: serie.cor }} />
              <span
                className="absolute left-1/2 h-2.5 w-2.5 -translate-x-1/2 rounded-full ring-2 ring-white dark:ring-zinc-900"
                style={{ background: serie.cor }}
              />
            </span>
            {serie.nome}
          </li>
        ))}
        <li className="inline-flex items-center gap-2 text-zinc-500 dark:text-zinc-400">
          <span aria-hidden className="inline-block h-0 w-5 border-t-2 border-dotted border-zinc-300 dark:border-zinc-600" />
          semana sem coleta fica em branco
        </li>
      </ul>

      {/* Os mesmos números, semana a semana, para leitor de tela. O sr-only fica num
          invólucro: numa <table> o width de 1px não vale e ela alargava a página no celular. */}
      <div className="sr-only">
      <table>
        <caption>{titulo}: valores por semana</caption>
        <thead>
          <tr>
            <th scope="col">Semana</th>
            {series.map((serie) => (
              <th key={serie.nome} scope="col">{serie.nome}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {semanas.map((semana, indice) => (
            <tr key={semana.inicio}>
              <th scope="row">{textoSemana(indice)}</th>
              {series.map((serie) => {
                const valor = serie.valores[indice];
                const alunos = serie.alunos?.[indice];
                return (
                  <td key={serie.nome}>
                    {valor == null
                      ? "sem coleta"
                      : `${formatarPercentual(valor)}${alunos != null ? ` (${alunos.toLocaleString("pt-BR")} alunos)` : ""}`}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      </div>
    </div>
  );
}

export default GraficoSemanal;
