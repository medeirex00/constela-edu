/**
 * Fusão de alunos: "(o bimestre atual)" só quando o bimestre está em curso.
 *
 * O DEFEITO (ALUNOS-2, PERIODOS-5, WEB-2): na virada do ano (janeiro de 2027, escola
 * ainda no ano letivo 2026) a prévia da fusão manda como bimestre da premiação o 4º
 * de 2026, que já acabou, e as duas telas (aviso da ficha e "Fundir duplicatas")
 * escreviam "(o bimestre atual)" sempre que o número batia. Agora o backend manda
 * `ano` e `atual`; fora do bimestre em curso a tela escreve o bimestre e o ano
 * ("4º bimestre de 2026"), como recomendado na lista de pendências do dono.
 * Dados fictícios.
 */
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import LeiturasRepetidas, {
  type ResumoLeiturasRepetidas, textoBimestres,
} from "../components/LeiturasRepetidas";
import ModalAlunosDuplicados from "../components/ModalAlunosDuplicados";
import { renderComApp, responder, screen, userEvent } from "./utils";

const NA_VIRADA: ResumoLeiturasRepetidas = {
  livros_repetidos: 2,
  com_data_diferente: 2,
  no_bimestre: 1,
  // o que ``leituras_repetidas(db, 2026, ..., hoje=date(2027, 1, 15))`` devolve:
  bimestre: { numero: 4, rotulo: "4º bimestre", inicio: "2026-10-05", fim: "2026-12-31",
              ano: 2026, atual: false },
  por_bimestre: [{ numero: 3, rotulo: "3º bimestre", livros: 1 },
                 { numero: 4, rotulo: "4º bimestre", livros: 1 }],
  exemplos: [],
};

const EM_CURSO: ResumoLeiturasRepetidas = {
  ...NA_VIRADA,
  bimestre: { ...NA_VIRADA.bimestre!, atual: true },
};

describe("textoBimestres", () => {
  it("na virada do ano escreve o bimestre e o ano, não 'o bimestre atual'", () => {
    const texto = textoBimestres(NA_VIRADA);
    expect(texto).toBe("1 no 3º bimestre de 2026 e 1 no 4º bimestre de 2026");
    const { getByRole } = render(
      <LeiturasRepetidas resumo={NA_VIRADA} nomeFica="A" nomeSai="B" />);
    expect(getByRole("note").textContent).not.toContain("(o bimestre atual)");
    expect(getByRole("note")).toHaveTextContent("1 no 4º bimestre de 2026");
  });

  it("com o bimestre em curso, marca o da premiação como o atual", () => {
    expect(textoBimestres(EM_CURSO)).toBe(
      "1 no 3º bimestre e 1 no 4º bimestre (o bimestre atual)");
  });

  it("resposta sem 'atual' (backend antigo) não afirma que o bimestre é o atual", () => {
    const { ano: _ano, atual: _atual, ...semMarca } = NA_VIRADA.bimestre!;
    const texto = textoBimestres({ ...NA_VIRADA, bimestre: semMarca });
    expect(texto).toBe("1 no 3º bimestre e 1 no 4º bimestre");
  });
});

describe("Fundir duplicatas — painel de confirmação", () => {
  function previa(leituras: ResumoLeiturasRepetidas) {
    return {
      total: 1, alta: 1, provavel: 0, revisar: 0,
      candidatos: [{
        loser_id: 10, manter_id: 11,
        apagar: "Bruno Alves Costa", manter: "Bruno Alves Costa",
        turma: "4º C", confianca: "alta", motivo: "nome_identico",
        impacto: { leituras: 2, snapshots_matific: 0, snapshots_elefante: 0,
                   eventos: 0, notas: 0, plataformas: [] },
        leituras,
      }],
    };
  }

  async function painel(leituras: ResumoLeiturasRepetidas) {
    responder("GET", "/escolas/1/alunos/duplicados", previa(leituras));
    const u = userEvent.setup();
    renderComApp(<ModalAlunosDuplicados escolaId={1} aoFechar={() => {}} aoConcluir={() => {}} />);
    await screen.findByText(/deixam de contar/);
    await u.click(screen.getByRole("button", { name: /Unir 1 selecionada/ }));
    return screen.findByText(/Nos pares marcados/);
  }

  it("na virada do ano diz o bimestre e o ano", async () => {
    const aviso = await painel(NA_VIRADA);
    expect(aviso.textContent).not.toContain("(o bimestre atual)");
    expect(aviso).toHaveTextContent("1 deixa(m) de contar no 4º bimestre de 2026");
  });

  it("com o bimestre em curso, continua dizendo que é o atual", async () => {
    const aviso = await painel(EM_CURSO);
    expect(aviso).toHaveTextContent("1 deixa(m) de contar no 4º bimestre (o bimestre atual)");
  });
});
