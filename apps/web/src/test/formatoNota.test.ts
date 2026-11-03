/** `nota()` sem valor: o servidor pode não mandar a média (grupo pequeno escondido da
 *  Secretaria, matéria fora do plano). A tela mostra "—" — nunca quebra nem inventa 0. */
import { describe, expect, it } from "vitest";

import { nota, numero, tempoLeitura } from "../lib/formato";

describe("nota(), numero() e tempoLeitura()", () => {
  it("formata com uma ou duas casas", () => {
    expect(nota(72)).toBe("72,0");
    expect(nota(72.456)).toBe("72,46");
    expect(nota(0)).toBe("0,0");
  });

  it("sem valor vira '—'", () => {
    expect(nota(null)).toBe("—");
    expect(nota(undefined)).toBe("—");
    expect(numero(null)).toBe("—");
    expect(tempoLeitura(null)).toBe("—");
    expect(numero(1234)).toBe("1.234");
    expect(tempoLeitura(95)).toBe("1h 35min");
  });
});
