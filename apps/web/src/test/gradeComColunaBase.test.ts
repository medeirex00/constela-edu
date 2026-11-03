/**
 * Trava estática (prontidão para a demo, celular): uma `grid` com só colunas
 * responsivas (`sm:/md:/lg:/xl:grid-cols-N`) não tem colunas no celular — a coluna
 * implícita é `auto` e cresce até a largura mínima do item mais largo (uma tabela),
 * alargando a página inteira em 375 px. Toda grade responsiva leva uma coluna base
 * (`grid-cols-1` = minmax(0, 1fr)); o conteúdo largo rola dentro do próprio cartão.
 */
import { describe, expect, it } from "vitest";

const FONTES = import.meta.glob(["../**/*.tsx", "!../test/**", "!../**/publico/**"], {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

const CLASSE = /className=\{?[`"]([^`"]*)[`"]/g;
const RESPONSIVO = /(?:^|\s)(?:sm|md|lg|xl|2xl|min-\[[^\]]+\]):grid-cols-/;
const BASE = /(?:^|\s)grid-cols-/;

describe("grade responsiva tem coluna base", () => {
  it("a varredura acha os arquivos do app", () => {
    expect(Object.keys(FONTES).length).toBeGreaterThan(50);
  });

  it("toda `grid` com colunas por breakpoint define a coluna do celular", () => {
    const sem: string[] = [];
    for (const [arquivo, texto] of Object.entries(FONTES)) {
      for (const m of texto.matchAll(CLASSE)) {
        const classes = m[1];
        if (!classes.split(/\s+/).includes("grid") || !RESPONSIVO.test(classes)) continue;
        if (/grid-flow-col|auto-cols-|grid-rows-/.test(classes)) continue;
        if (!BASE.test(classes)) {
          const linha = texto.slice(0, m.index).split("\n").length;
          sem.push(`${arquivo}:${linha} ${classes.slice(0, 80)}`);
        }
      }
    }
    expect(sem).toEqual([]);
  });
});
