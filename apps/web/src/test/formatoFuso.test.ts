/**
 * Horários da API no fuso de Brasília. A API serializa UTC SEM marca de fuso
 * ("2026-11-01T01:00:00" = 22h de 31/10 em Brasília); `new Date(iso)` lia como horário
 * local e a tela mostrava "01/11, 01:00" — dado do dia seguinte, 3 h adiantado.
 */
import { describe, expect, it } from "vitest";

import { dataDia, dataHora } from "../lib/formato";

const FONTES = import.meta.glob(["../**/*.{ts,tsx}", "!../test/**", "!../**/publico/**", "!../lib/formato.ts"], {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

describe("datas da API no fuso de Brasília", () => {
  it("UTC sem marca de fuso vira o dia certo em Brasília", () => {
    expect(dataDia("2026-11-01T01:00:00")).toBe("31/10/2026");
    expect(dataDia("2026-11-01T01:00:00", true)).toBe("31/10");
    expect(dataHora("2026-11-01T01:00:00")).toBe("31/10/2026, 22:00");
    expect(dataDia("2026-10-31T15:00:00+00:00")).toBe("31/10/2026");
    expect(dataDia(null)).toBe("—");
  });

  it("nenhuma tela formata data sem o fuso explícito (use dataHora/dataDia)", () => {
    const sem: string[] = [];
    const chamada = /\.(toLocaleDateString|toLocaleString|toLocaleTimeString)\(\s*"pt-BR"\s*(,\s*\{[^}]*\})?\s*\)/g;
    for (const [arquivo, texto] of Object.entries(FONTES)) {
      for (const m of texto.matchAll(chamada)) {
        const opcoes = m[2] ?? "";
        // Número formatado (sem opções de data) não importa; data sem timeZone sim.
        const ehData = m[1] !== "toLocaleString" || /date|time|day|month|year|weekday|hour/i.test(opcoes);
        if (ehData && !/timeZone/.test(opcoes)) {
          const antes = texto.slice(Math.max(0, (m.index ?? 0) - 40), m.index);
          if (/\b(valor|numero|n|total|xp|contagem|catalogo|alunos|v)\s*\??\)?\s*$/.test(antes)) continue;
          sem.push(`${arquivo}:${texto.slice(0, m.index).split("\n").length}`);
        }
      }
    }
    expect(sem).toEqual([]);
  });
});
