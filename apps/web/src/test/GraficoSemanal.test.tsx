/**
 * Gráfico semanal da Visão Geral (identidade v2): semana sem coleta é LACUNA (a linha
 * quebra, não desce a 0), o último valor medido de cada série ganha rótulo, e o mesmo
 * conteúdo existe em texto (role="img" com resumo + tabela para leitor de tela).
 * No celular (contêiner medido < 480 px) o desenho fica 1:1 na largura real, com as
 * semanas alternadas no eixo X; sem medida (jsdom) ou no desktop, o desenho de sempre.
 * Dados fictícios.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  GraficoSemanal,
  caminhoMonotono,
  trechosContinuos,
  type SemanaDoGrafico,
  type SerieSemanal,
} from "../components/GraficoSemanal";
import { render, screen, within } from "./utils";

const SEMANAS: SemanaDoGrafico[] = [
  { inicio: "2026-09-28", fim: "2026-10-04" },
  { inicio: "2026-10-05", fim: "2026-10-11" },
  { inicio: "2026-10-12", fim: "2026-10-18" },
  { inicio: "2026-10-19", fim: "2026-10-25" },
  { inicio: "2026-10-26", fim: "2026-11-01" },
];

const LEITURA: SerieSemanal = {
  nome: "Leitura · Elefante Letrado",
  cor: "#6C5CE7",
  valores: [40, 45.5, null, 50, 52.3],
  alunos: [120, 136, null, 150, 157],
  area: true,
};
const MATEMATICA: SerieSemanal = {
  nome: "Matemática · Matific",
  cor: "#0D9488", // a mesma da Visão Geral (teal-600, contraste de traço ≥ 3:1)
  corTexto: "#10122A",
  valores: [30, null, null, 33, null],
  alunos: [90, null, null, 99, null],
};

describe("GraficoSemanal", () => {
  it("resume as séries no texto alternativo e na legenda", () => {
    render(<GraficoSemanal semanas={SEMANAS} series={[LEITURA, MATEMATICA]} titulo="Alunos ativos por semana" />);

    const grafico = screen.getByRole("img", { name: /^Alunos ativos por semana, 5 semanas, de 28\/09 a 01\/11/ });
    // O último valor MEDIDO de cada série (a Matemática não tem coleta na semana em curso).
    expect(grafico).toHaveAccessibleName(
      expect.stringContaining("Leitura · Elefante Letrado: 52,3% na semana de 26/10 a 01/11 (em curso)"),
    );
    expect(grafico).toHaveAccessibleName(
      expect.stringContaining("Matemática · Matific: 33% na semana de 19/10 a 25/10"),
    );
    const legenda = screen.getByRole("list");
    expect(within(legenda).getByText("Leitura · Elefante Letrado")).toBeInTheDocument();
    expect(within(legenda).getByText("Matemática · Matific")).toBeInTheDocument();
  });

  it("semana sem coleta quebra a linha (lacuna) e não vira ponto nem 0%", () => {
    const { container } = render(
      <GraficoSemanal semanas={SEMANAS} series={[LEITURA, MATEMATICA]} titulo="Alunos ativos por semana" />,
    );

    const leitura = container.querySelector('[data-serie="Leitura · Elefante Letrado"]') as SVGGElement;
    // 40, 45,5 | lacuna | 50, 52,3 → dois trechos de linha e quatro pontos.
    expect(leitura.querySelectorAll("path[data-trecho]")).toHaveLength(2);
    expect(leitura.querySelectorAll("circle[data-ponto]")).toHaveLength(4);

    const matematica = container.querySelector('[data-serie="Matemática · Matific"]') as SVGGElement;
    // 30 | lacuna | 33 | lacuna → só pontos soltos, nenhuma linha ligando por cima do buraco.
    expect(matematica.querySelectorAll("path[data-trecho]")).toHaveLength(0);
    expect(matematica.querySelectorAll("circle[data-ponto]")).toHaveLength(2);

    // A tabela para leitor de tela diz "sem coleta" — nunca "0%".
    const tabela = screen.getByRole("table", { name: "Alunos ativos por semana: valores por semana" });
    const linha = within(tabela).getByRole("row", { name: /12\/10 a 18\/10/ });
    expect(within(linha).getAllByText("sem coleta")).toHaveLength(2);
    expect(within(tabela).queryByText(/^0%/)).not.toBeInTheDocument();
    expect(within(tabela).getByRole("row", { name: /26\/10 a 01\/11 \(em curso\)/ })).toBeInTheDocument();
  });

  it("rotula o último ponto medido de cada série", () => {
    const { container } = render(
      <GraficoSemanal semanas={SEMANAS} series={[LEITURA, MATEMATICA]} titulo="Alunos ativos por semana" />,
    );
    const rotuloLeitura = container.querySelector('[data-rotulo-final="Leitura · Elefante Letrado"]');
    const rotuloMatematica = container.querySelector('[data-rotulo-final="Matemática · Matific"]');
    expect(rotuloLeitura?.textContent).toBe("52,3%");
    expect(rotuloMatematica?.textContent).toBe("33%");
  });

  it("sem nenhuma coleta não desenha um gráfico vazio de mentira", () => {
    render(
      <GraficoSemanal
        semanas={SEMANAS}
        series={[{ ...LEITURA, valores: [null, null, null, null, null] }]}
        titulo="Alunos ativos por semana"
      />,
    );
    expect(screen.getByText("Sem coleta nas semanas mostradas.")).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });
});

describe("GraficoSemanal — geometria", () => {
  it("trechos contínuos quebram em cada null", () => {
    expect(trechosContinuos([1, null, 2, 3, null])).toEqual([[0], [2, 3]]);
    expect(trechosContinuos([null, null])).toEqual([]);
  });

  it("a curva suave não ultrapassa os pontos (nunca passa de 100% nem fica abaixo de 0%)", () => {
    // y do SVG: 0 = topo (100%), 200 = base (0%). Subida brusca, platô e descida.
    const pontos: [number, number][] = [[0, 200], [10, 0], [20, 0], [30, 200], [40, 100]];
    const d = caminhoMonotono(pontos);
    const ys = [...d.matchAll(/(-?[\d.]+),(-?[\d.]+)/g)].map((m) => Number(m[2]));
    expect(ys.length).toBeGreaterThan(pontos.length);
    for (const valor of ys) {
      expect(valor).toBeGreaterThanOrEqual(0);
      expect(valor).toBeLessThanOrEqual(200);
    }
    // No platô (10→20, y = 0) os pontos de controle ficam no próprio platô.
    expect(d).toMatch(/C13\.3+4,0 16\.6+\d*,0 20,0/);
  });
});

/** Oito segundas-feiras (07/09 a 26/10), como na Visão Geral. */
const OITO_SEMANAS: SemanaDoGrafico[] = [
  ["2026-09-07", "2026-09-13"], ["2026-09-14", "2026-09-20"], ["2026-09-21", "2026-09-27"],
  ["2026-09-28", "2026-10-04"], ["2026-10-05", "2026-10-11"], ["2026-10-12", "2026-10-18"],
  ["2026-10-19", "2026-10-25"], ["2026-10-26", "2026-11-01"],
].map(([inicio, fim]) => ({ inicio, fim }));
const LEITURA_8: SerieSemanal = { ...LEITURA, valores: [10, 20, null, 40, 50, 60, 80, 100], alunos: undefined };

function desenhar() {
  const { container } = render(
    <GraficoSemanal semanas={OITO_SEMANAS} series={[LEITURA_8]} titulo="Alunos ativos por semana" altura={300} />,
  );
  const svg = container.querySelector("svg") as SVGSVGElement;
  const rotulosX = [...container.querySelectorAll("[data-rotulo-semana] text")].map((t) => t.textContent);
  return { container, svg, rotulosX };
}

describe("GraficoSemanal — celular", () => {
  afterEach(() => vi.restoreAllMocks());

  it("sem medida do contêiner (jsdom), o desenho de sempre: viewBox 580 e as 8 semanas no eixo", () => {
    const { svg, rotulosX } = desenhar();
    expect(svg).toHaveAttribute("viewBox", "0 0 580 300");
    expect(rotulosX).toEqual(["07/09", "14/09", "21/09", "28/09", "05/10", "12/10", "19/10", "26/10", "em curso"]);
  });

  it("contêiner de desktop/tablet medido: continua o desenho de sempre", () => {
    vi.spyOn(Element.prototype, "clientWidth", "get").mockReturnValue(620);
    const { svg, rotulosX } = desenhar();
    expect(svg).toHaveAttribute("viewBox", "0 0 580 300");
    expect(rotulosX).toHaveLength(9);
  });

  it("contêiner de celular: viewBox na largura real (texto a 12 px), semanas alternadas e nada some", () => {
    vi.spyOn(Element.prototype, "clientWidth", "get").mockReturnValue(320);
    const { container, svg, rotulosX } = desenhar();

    // 1:1 — o texto de 12 unidades sai com 12 px na tela (antes: 580 → ~300 px, ~6 px).
    expect(svg).toHaveAttribute("viewBox", "0 0 320 230");
    const eixoY = [...svg.querySelectorAll("text")].find((t) => t.textContent === "100%");
    expect(eixoY).toHaveClass("text-[12px]");
    // Uma semana sim, uma não, contando da semana em curso (que sempre aparece).
    expect(rotulosX).toEqual(["14/09", "28/09", "12/10", "26/10", "em curso"]);
    // A pílula do último valor cabe no desenho.
    const pilula = container.querySelector('[data-rotulo-final="Leitura · Elefante Letrado"] rect') as SVGRectElement;
    expect(Number(pilula.getAttribute("x")) + Number(pilula.getAttribute("width"))).toBeLessThanOrEqual(320);
    // Todas as semanas continuam nos pontos (dica) e na tabela do leitor de tela.
    expect(container.querySelectorAll("circle[data-ponto]")).toHaveLength(7);
    const tabela = screen.getByRole("table", { name: "Alunos ativos por semana: valores por semana" });
    expect(within(tabela).getAllByRole("row")).toHaveLength(9);
    expect(within(tabela).getByRole("row", { name: /21\/09 a 27\/09/ })).toHaveTextContent("sem coleta");
    expect(screen.getByRole("img", { name: /^Alunos ativos por semana, 8 semanas, de 07\/09 a 01\/11/ }))
      .toBeInTheDocument();
  });
});
