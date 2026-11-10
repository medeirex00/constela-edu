/** Ficha do aluno no app: sem dado é "—", zero legítimo é 0,0 — o mesmo da web
 *  (`apps/web/src/test/PerfilAlunoDimensoes.test.tsx`). Dados fictícios. */
import { describe, expect, it } from "vitest";

import { notasDoPerfil } from "../notasDoPerfil";

function bloco(dimensao: string, plataforma: string, aferido: boolean, nota: number | null) {
  return { dimensao, plataforma, contratada: true, aferido, nota, posicao: null,
    n_aferidos: 0, snapshot_em: null, dados: {} };
}

const ZERADO = { nota_matific: 0, nota_elefante: 0, nota_geral: 0 };

describe("notas da ficha do aluno no app", () => {
  it("quem nunca abriu o Matific vê “—” em Matific, não 0,0, e sem o passo a passo dele", () => {
    const n = notasDoPerfil({ ...ZERADO, nota_elefante: 62.5, nota_geral: 62.5,
      dimensoes: [bloco("leitura", "elefante", true, 62.5), bloco("matematica", "matific", false, null)] });
    expect(n.matific).toBe("—");
    expect(n.leitura).toBe("62,5");
    expect(n.geral).toBe("62,5");
    expect(n.calculoMatific).toBe(false);
    expect(n.calculoLeitura).toBe(true);
    expect(n.semDadoNenhum).toBe(false);
  });

  it("sem dado em nenhuma: as três notas são “—” e nenhum passo a passo", () => {
    const n = notasDoPerfil({ ...ZERADO,
      dimensoes: [bloco("leitura", "elefante", false, null), bloco("matematica", "matific", false, null)] });
    expect([n.matific, n.leitura, n.geral]).toEqual(["—", "—", "—"]);
    expect(n.calculoMatific || n.calculoLeitura).toBe(false);
    expect(n.semDadoNenhum).toBe(true);
  });

  it("zero legítimo (tem retrato, ainda não produziu) continua 0,0", () => {
    const n = notasDoPerfil({ ...ZERADO,
      dimensoes: [bloco("leitura", "elefante", true, 0), bloco("matematica", "matific", true, 0)] });
    expect([n.matific, n.leitura, n.geral]).toEqual(["0,0", "0,0", "0,0"]);
    expect(n.calculoMatific && n.calculoLeitura).toBe(true);
  });

  it("servidor sem `dimensoes`: mostra o número que veio; fora do plano (null) é “—”", () => {
    const n = notasDoPerfil({ nota_matific: null, nota_elefante: 0, nota_geral: 0 });
    expect([n.matific, n.leitura, n.geral]).toEqual(["—", "0,0", "0,0"]);
    expect(n.calculoMatific && n.calculoLeitura).toBe(true);
    expect(n.semDadoNenhum).toBe(false);
  });
});
