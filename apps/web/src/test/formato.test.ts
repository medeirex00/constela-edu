import { describe, expect, it } from "vitest";

import { dataHora } from "../lib/formato";

describe("dataHora — horário de Brasília", () => {
  it("trata timestamp UTC SEM sufixo de fuso como UTC (não como local)", () => {
    // 14:31 UTC → 11:31 em São Paulo (UTC-3). Antes do fix mostrava 14:31.
    const naive = dataHora("2026-07-12T14:31:00");
    expect(naive).toContain("11:31");
    expect(naive).toContain("12/07/2026");
  });

  it("naive e com 'Z' produzem exatamente o mesmo horário", () => {
    expect(dataHora("2026-07-12T14:31:00")).toBe(dataHora("2026-07-12T14:31:00Z"));
  });

  it("respeita offset explícito", () => {
    // 14:31-03:00 já é horário de Brasília → 14:31.
    expect(dataHora("2026-07-12T14:31:00-03:00")).toContain("14:31");
  });

  it("valor vazio vira travessão", () => {
    expect(dataHora(null)).toBe("—");
  });
});
