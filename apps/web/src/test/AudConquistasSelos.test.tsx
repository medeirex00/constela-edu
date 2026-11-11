/**
 * Conquistas: os selos "evolução N" dos três destaques (Aluno do Dia, da Semana e
 * do Mês) saem com o MESMO número de casas decimais.
 *
 * O selo usava `nota()` do pacote compartilhado, que mostra de 1 a 2 casas
 * conforme o valor: "evolução 99,33" ao lado de "evolução 87,3" e "evolução 50,0".
 * Agora o selo tem sempre 1 casa; `nota()` (contrato do produto todo, travado em
 * formatoNota.test.ts) não muda. Achados RANKINGS-12 e WEB-5.
 */
import { describe, expect, it } from "vitest";

import Conquistas from "../pages/Conquistas";
import { renderComApp, responder, screen } from "./utils";

const URL_MURAL = "/escolas/1/gamificacao/mural";
const URL_XP = "/escolas/1/gamificacao/ranking-xp";

describe("Conquistas: selos de evolução", () => {
  it("os três destaques mostram a evolução com 1 casa decimal", async () => {
    responder("GET", URL_MURAL, {
      destaques: {
        dia: { aluno_id: 7, nome: "Ana Dia", turma: "3º Ano A", nota_evolucao: 99.33, ganhos: {} },
        semana: { aluno_id: 9, nome: "Caio Semana", turma: "3º Ano A", nota_evolucao: 87.3, ganhos: {} },
        mes: { aluno_id: 8, nome: "Bruno Mes", turma: "4º Ano B", nota_evolucao: 50, ganhos: {} },
      },
      eventos: [],
    });
    responder("GET", URL_XP, []);
    renderComApp(<Conquistas />);

    const selos = await screen.findAllByText(/^evolução /);
    expect(selos.map((s) => s.textContent)).toEqual([
      "evolução 99,3",
      "evolução 87,3",
      "evolução 50,0",
    ]);
  });

  it("arredonda em pt-BR (vírgula, 1 casa) também com um destaque vazio", async () => {
    responder("GET", URL_MURAL, {
      destaques: {
        dia: { aluno_id: 7, nome: "Ana Dia", turma: "3º Ano A", nota_evolucao: 12.25, ganhos: {} },
        semana: null,
        mes: { aluno_id: 8, nome: "Bruno Mes", turma: "4º Ano B", nota_evolucao: 0.04, ganhos: {} },
      },
      eventos: [],
    });
    responder("GET", URL_XP, []);
    renderComApp(<Conquistas />);

    const selos = await screen.findAllByText(/^evolução /);
    const textos = selos.map((s) => s.textContent ?? "");
    for (const texto of textos) expect(texto).toMatch(/^evolução \d{1,3}(\.\d{3})*,\d$/);
    expect(textos[1]).toBe("evolução 0,0");
  });
});
