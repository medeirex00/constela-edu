import { describe, expect, it } from "vitest";

import { ehErroDeChunk } from "../lib/atualizacao";

describe("ehErroDeChunk (deploy novo × chunk lazy obsoleto)", () => {
  it("reconhece as falhas de import dinâmico dos navegadores", () => {
    const casos = [
      new Error("Failed to fetch dynamically imported module: https://x/assets/Dashboard-abc.js"),
      new Error("error loading dynamically imported module"),
      new Error("Importing a module script failed."),
      Object.assign(new Error("loading chunk 5 failed"), { name: "ChunkLoadError" }),
    ];
    for (const erro of casos) expect(ehErroDeChunk(erro)).toBe(true);
  });

  it("NÃO confunde com erros comuns de aplicação", () => {
    expect(ehErroDeChunk(new Error("Não foi possível conectar"))).toBe(false);
    expect(ehErroDeChunk(new TypeError("undefined is not a function"))).toBe(false);
    expect(ehErroDeChunk(null)).toBe(false);
  });
});
