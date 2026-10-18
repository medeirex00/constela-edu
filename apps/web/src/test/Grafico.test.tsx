/**
 * Gráficos SVG leves (`components/Grafico.tsx`).
 *
 * 1. Os USOS ANTIGOS ficam idênticos: o markup do `GraficoLinha` chamado como na
 *    evolução do aluno (uma série por índice, eixo a partir de 0) e com duas séries
 *    foi gravado ANTES da extensão da etapa E3 — qualquer diferença quebra aqui.
 * 2. As extensões (E3, aba do ICA): eixo X por categoria (anos desalinhados e
 *    lacunas — valor nulo OU ano sem ponto quebram a linha, "sem resultado" ≠ 0),
 *    série tracejada, eixo Y que não começa em 0, mais cores, texto alternativo.
 * 3. `BarraEmpilhada` (níveis): segmentos proporcionais, legenda, tabela
 *    equivalente, barra sem dado diz "sem resultado" (nunca uma barra vazia de 0).
 */
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { BarraEmpilhada, GraficoLinha } from "../components/Grafico";

const PONTOS = [
  { rotulo: "jan", valor: 3 },
  { rotulo: "fev", valor: 7 },
  { rotulo: "mar", valor: 7 },
  { rotulo: "abr", valor: 12.5 },
];

describe("GraficoLinha — usos antigos (markup gravado antes da E3)", () => {
  it("uma série (evolução do aluno): igual ao de antes", () => {
    const { container } = render(<GraficoLinha series={[{ nome: "Livros lidos", pontos: PONTOS }]} />);
    expect(container.innerHTML).toMatchInlineSnapshot(`"<div><svg viewBox="0 0 500 180" class="w-full" role="img" aria-label="Gráfico de evolução"><g><line x1="46" x2="488" y1="154" y2="154" class="stroke-zinc-200 dark:stroke-zinc-700" stroke-width="1"></line><text x="40" y="158" text-anchor="end" class="fill-zinc-400 text-[13px] tabular-nums">0</text></g><g><line x1="46" x2="488" y1="92" y2="92" class="stroke-zinc-200 dark:stroke-zinc-700" stroke-width="1"></line><text x="40" y="96" text-anchor="end" class="fill-zinc-400 text-[13px] tabular-nums">6</text></g><g><line x1="46" x2="488" y1="30" y2="30" class="stroke-zinc-200 dark:stroke-zinc-700" stroke-width="1"></line><text x="40" y="34" text-anchor="end" class="fill-zinc-400 text-[13px] tabular-nums">13</text></g><g><polyline fill="none" stroke="#6366f1" stroke-width="2" points="46,124.24 193.33333333333331,84.56 340.66666666666663,84.56 488,30"></polyline><g><circle cx="46" cy="124.24" r="3" fill="#6366f1"><title>Livros lidos — jan: 3</title></circle><text x="46" y="117.24" text-anchor="start" class="text-[13px] font-semibold tabular-nums" fill="#6366f1">3</text></g><g><circle cx="193.33333333333331" cy="84.56" r="3" fill="#6366f1"><title>Livros lidos — fev: 7</title></circle><text x="193.33333333333331" y="77.56" text-anchor="middle" class="text-[13px] font-semibold tabular-nums" fill="#6366f1">7</text></g><g><circle cx="340.66666666666663" cy="84.56" r="3" fill="#6366f1"><title>Livros lidos — mar: 7</title></circle></g><g><circle cx="488" cy="30" r="3" fill="#6366f1"><title>Livros lidos — abr: 12,5</title></circle><text x="488" y="23" text-anchor="end" class="text-[13px] font-semibold tabular-nums" fill="#6366f1">12,5</text></g></g><text x="46" y="172" text-anchor="middle" class="fill-zinc-400 text-[12px]">jan</text><text x="193.33333333333331" y="172" text-anchor="middle" class="fill-zinc-400 text-[12px]">fev</text><text x="340.66666666666663" y="172" text-anchor="middle" class="fill-zinc-400 text-[12px]">mar</text><text x="488" y="172" text-anchor="middle" class="fill-zinc-400 text-[12px]">abr</text></svg><div class="mt-1 flex flex-wrap gap-3"><span class="flex items-center gap-1.5 text-xs text-zinc-500 dark:text-zinc-400"><span class="h-2 w-2 rounded-full" style="background: rgb(99, 102, 241);"></span>Livros lidos</span></div></div>"`);
  });

  it("duas séries com altura própria: igual ao de antes", () => {
    const { container } = render(
      <GraficoLinha
        altura={185}
        series={[
          { nome: "Escola", pontos: PONTOS },
          { nome: "Rede", pontos: [{ rotulo: "jan", valor: 5 }, { rotulo: "fev", valor: 4 }] },
        ]}
      />,
    );
    expect(container.innerHTML).toMatchInlineSnapshot(`"<div><svg viewBox="0 0 500 185" class="w-full" role="img" aria-label="Gráfico de evolução"><g><line x1="46" x2="488" y1="159" y2="159" class="stroke-zinc-200 dark:stroke-zinc-700" stroke-width="1"></line><text x="40" y="163" text-anchor="end" class="fill-zinc-400 text-[13px] tabular-nums">0</text></g><g><line x1="46" x2="488" y1="94.5" y2="94.5" class="stroke-zinc-200 dark:stroke-zinc-700" stroke-width="1"></line><text x="40" y="98.5" text-anchor="end" class="fill-zinc-400 text-[13px] tabular-nums">6</text></g><g><line x1="46" x2="488" y1="30" y2="30" class="stroke-zinc-200 dark:stroke-zinc-700" stroke-width="1"></line><text x="40" y="34" text-anchor="end" class="fill-zinc-400 text-[13px] tabular-nums">13</text></g><g><polyline fill="none" stroke="#6366f1" stroke-width="2" points="46,128.04000000000002 193.33333333333331,86.75999999999999 340.66666666666663,86.75999999999999 488,30"></polyline><g><circle cx="46" cy="128.04000000000002" r="3" fill="#6366f1"><title>Escola — jan: 3</title></circle></g><g><circle cx="193.33333333333331" cy="86.75999999999999" r="3" fill="#6366f1"><title>Escola — fev: 7</title></circle></g><g><circle cx="340.66666666666663" cy="86.75999999999999" r="3" fill="#6366f1"><title>Escola — mar: 7</title></circle></g><g><circle cx="488" cy="30" r="3" fill="#6366f1"><title>Escola — abr: 12,5</title></circle></g></g><g><polyline fill="none" stroke="#10b981" stroke-width="2" points="46,107.39999999999999 193.33333333333331,117.72"></polyline><g><circle cx="46" cy="107.39999999999999" r="3" fill="#10b981"><title>Rede — jan: 5</title></circle></g><g><circle cx="193.33333333333331" cy="117.72" r="3" fill="#10b981"><title>Rede — fev: 4</title></circle></g></g><text x="46" y="177" text-anchor="middle" class="fill-zinc-400 text-[12px]">jan</text><text x="193.33333333333331" y="177" text-anchor="middle" class="fill-zinc-400 text-[12px]">fev</text><text x="340.66666666666663" y="177" text-anchor="middle" class="fill-zinc-400 text-[12px]">mar</text><text x="488" y="177" text-anchor="middle" class="fill-zinc-400 text-[12px]">abr</text></svg><div class="mt-1 flex flex-wrap gap-3"><span class="flex items-center gap-1.5 text-xs text-zinc-500 dark:text-zinc-400"><span class="h-2 w-2 rounded-full" style="background: rgb(99, 102, 241);"></span>Escola</span><span class="flex items-center gap-1.5 text-xs text-zinc-500 dark:text-zinc-400"><span class="h-2 w-2 rounded-full" style="background: rgb(16, 185, 129);"></span>Rede</span></div></div>"`);
  });

  it("sem pontos: a mesma mensagem de antes", () => {
    const { container } = render(<GraficoLinha series={[{ nome: "Vazia", pontos: [] }]} />);
    expect(container.innerHTML).toMatchInlineSnapshot(`"<p class="py-8 text-center text-sm text-zinc-400">Sem dados suficientes para o gráfico.</p>"`);
  });
});

const ANOS = ["2023", "2024", "2025", "2026", "2027"];

describe("GraficoLinha — extensões da E3 (eixo por ano, lacunas, tracejada, eixo Y, cores)", () => {
  it("eixo X por categoria: séries com anos desalinhados ficam no ano certo; lacuna quebra a linha", () => {
    const { container } = render(
      <GraficoLinha
        eixoX={ANOS}
        series={[
          { nome: "Rede", pontos: [{ rotulo: "2023", valor: 20 }, { rotulo: "2024", valor: null }, { rotulo: "2025", valor: 30 }] },
          { nome: "Meta", tracejada: true, pontos: ["2024", "2025", "2026", "2027"].map((rotulo, i) => (
            { rotulo, valor: 25 + 3 * i })) },
        ]}
      />,
    );
    const linhas = [...container.querySelectorAll("polyline")];
    // "Rede": dois trechos (2023) e (2025) — a lacuna de 2024 NÃO vira 0 nem liga os pontos
    expect(linhas).toHaveLength(3);
    const x = (i: number) => 46 + (i / 4) * (500 - 46 - 24);     // margem direita maior com eixoX
    expect(linhas[0].getAttribute("points")).toMatch(new RegExp(`^${x(0)},`));
    expect(linhas[1].getAttribute("points")).toMatch(new RegExp(`^${x(2)},`));
    // "Meta": todos os anos de 2024 (posição 1) a 2027 (posição 4) — um trecho só, tracejado
    const meta = (linhas[2].getAttribute("points") ?? "").split(" ");
    expect(meta).toHaveLength(4);
    expect(meta[0].startsWith(`${x(1)},`) && meta[3].startsWith(`${x(4)},`)).toBe(true);
    expect(linhas[2].getAttribute("stroke-dasharray")).toBe("6 4");
    expect(linhas[0].getAttribute("stroke-dasharray")).toBeNull();
    // 6 pontos desenhados (o nulo não tem círculo); os 5 anos no eixo
    expect(container.querySelectorAll("circle")).toHaveLength(6);
    expect([...container.querySelectorAll("svg > text")].map((t) => t.textContent)).toEqual(
      expect.arrayContaining(ANOS));
    expect(container.textContent).toContain("Meta (tracejada)");
  });

  it("ano que a série NÃO tem (sem ponto, nem nulo) também quebra a linha: os vizinhos não se ligam", () => {
    const { container, getByRole } = render(
      <GraficoLinha
        eixoX={ANOS} tabela="Números"
        series={[
          // só 2023 e 2025 (ex.: os microdados de 2024 não foram importados)
          { nome: "SP (redes municipais)", pontos: [{ rotulo: "2023", valor: 19.73 }, { rotulo: "2025", valor: 31.57 }] },
          { nome: "Contínua", pontos: [{ rotulo: "2025", valor: 30 }, { rotulo: "2026", valor: 32 }, { rotulo: "2027", valor: 34 }] },
        ]}
      />,
    );
    const x = (i: number) => 46 + (i / 4) * (500 - 46 - 24);
    const linhas = [...container.querySelectorAll("polyline")].map((l) => (l.getAttribute("points") ?? "").split(" "));
    // a série sem 2024: dois trechos de um ponto (2023) e (2025) — nenhuma reta passa por 2024
    expect(linhas).toHaveLength(3);
    expect(linhas[0]).toHaveLength(1);
    expect(linhas[0][0].startsWith(`${x(0)},`)).toBe(true);
    expect(linhas[1]).toHaveLength(1);
    expect(linhas[1][0].startsWith(`${x(2)},`)).toBe(true);
    // a série de anos seguidos continua um trecho só
    expect(linhas[2]).toHaveLength(3);
    expect(container.querySelectorAll("circle")).toHaveLength(5);
    // a tabela equivalente diz "—" no ano que não existe (não "sem resultado", não 0)
    expect(getByRole("table", { name: "Números" })).toHaveTextContent("SP (redes municipais)19,73—31,57——");
  });

  it("eixo Y com mínimo e máximo próprios, formato, texto alternativo e tabela equivalente", () => {
    const { container, getByRole, getByText } = render(
      <GraficoLinha
        eixoX={ANOS} minimo={20} maximo={60} rotulo="ICA por ano" tabela="Números do ICA"
        formato={(v) => `${v.toLocaleString("pt-BR")}%`}
        series={[{ nome: "Rede", pontos: [{ rotulo: "2023", valor: 33.5 }, { rotulo: "2024", valor: null }] }]}
      />,
    );
    expect(getByRole("img", { name: "ICA por ano" })).toBeInTheDocument();
    const ticks = [...container.querySelectorAll("svg > g > text")].map((t) => t.textContent);
    expect(ticks).toEqual(["20", "40", "60"]);                 // não começa em 0
    expect(container.querySelector("circle title")?.textContent).toBe("Rede — 2023: 33,5%");
    const tabela = getByRole("table", { name: "Números do ICA" });
    expect(tabela).toHaveTextContent("33,5%");
    expect(tabela).toHaveTextContent("sem resultado");         // 2024: nulo ≠ 0
    expect(tabela).not.toHaveTextContent("0%");
    expect(getByText("Ver os números do gráfico")).toBeInTheDocument();
  });

  it("mais cores que as 4 de antes; série toda nula não entra; tudo nulo = sem dados", () => {
    const serie = (nome: string, valor: number | null) => ({ nome, pontos: [{ rotulo: "2023", valor }] });
    const { container } = render(
      <GraficoLinha eixoX={["2023"]} series={["A", "B", "C", "D", "E"].map((n, i) => serie(n, 10 + i))} />,
    );
    const cores = [...container.querySelectorAll("circle")].map((c) => c.getAttribute("fill"));
    expect(cores).toEqual(["#6366f1", "#10b981", "#f59e0b", "#ef4444", "#0ea5e9"]);
    const { container: c2 } = render(<GraficoLinha series={[serie("Nula", null), serie("Ok", 3)]} />);
    expect(c2.textContent).not.toContain("Nula");
    const { container: c3 } = render(<GraficoLinha series={[serie("Nula", null)]} />);
    expect(c3.textContent).toBe("Sem dados suficientes para o gráfico.");
  });
});

describe("BarraEmpilhada (níveis)", () => {
  const segs = (valores: (number | null)[]) => valores.map((valor, i) => ({ nome: `Nível ${i}`, valor }));

  it("segmentos proporcionais ao total, legenda e tabela equivalente", () => {
    const { container, getByRole } = render(
      <BarraEmpilhada rotulo="Níveis por ano" formato={(v) => `${v.toLocaleString("pt-BR")}%`}
                      barras={[{ rotulo: "Rede — 2025", segmentos: segs([25, 25, 50]) }]} />,
    );
    const pedacos = [...container.querySelectorAll('[role="img"] > div')] as HTMLElement[];
    expect(pedacos.map((p) => p.style.width)).toEqual(["25%", "25%", "50%"]);
    expect(pedacos[2].getAttribute("title")).toBe("Nível 2: 50%");
    expect(getByRole("img", { name: /Rede — 2025 — Nível 0: 25%; Nível 1: 25%; Nível 2: 50%/ })).toBeInTheDocument();
    expect(getByRole("group", { name: "Níveis por ano" })).toHaveTextContent("Nível 0Nível 1Nível 2");
    expect(getByRole("table", { name: "Níveis por ano" })).toHaveTextContent("Rede — 202525%25%50%");
  });

  it("sem resultado ≠ 0: barra sem valor diz 'sem resultado'; zero de verdade aparece como 0", () => {
    const { getAllByTestId, getByRole } = render(
      <BarraEmpilhada rotulo="Níveis"
                      barras={[{ rotulo: "2023", segmentos: segs([null, null, null]) },
                               { rotulo: "2024", segmentos: segs([0, 40, null]) }]} />,
    );
    expect(getAllByTestId("barra-sem-resultado")).toHaveLength(1);
    const linhas = [...getByRole("table", { name: "Níveis" }).querySelectorAll("tbody tr")];
    expect(linhas[0]).toHaveTextContent("2023sem resultadosem resultadosem resultado");
    expect(linhas[1]).toHaveTextContent("2024040sem resultado");
  });
});
