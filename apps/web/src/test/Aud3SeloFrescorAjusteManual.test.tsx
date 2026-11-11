/**
 * S_G_AJUSTE-2: o selo de frescor não chama de "coleta" o que não foi coleta.
 *
 * O backend deixou de renovar a data do dado com o ajuste manual de uma criança
 * (`frescor_ranking`): o ajuste vem à parte, em `ajuste_manual_mais_recente_em`, e o selo o
 * menciona sem mudar a data nem o aviso. O estado "parcial" diz só que PARTE dos dados é
 * antiga — numa escola sem integração (que digita os números) ele acontece sem nenhuma
 * coleta, e "Coleta parcial" afirmava uma coleta que não houve. Dados fictícios.
 */
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SeloFrescor, SeloFrescorDaRede, type Frescor } from "../components/SeloFrescor";
import { renderComApp, responder, screen } from "./utils";

function bloco(over: Record<string, unknown> = {}) {
  return {
    plataforma: "matific", contratada: true, estado: "desatualizado",
    dado_mais_recente_em: "2026-10-22", dado_mais_antigo_em: "2026-10-22",
    dias_desde_dado: 20, alunos_com_dado: 3, alunos_com_dado_antigo: 3,
    ajuste_manual_mais_recente_em: null,
    ultima_sincronizacao_ok_em: null, dias_desde_sincronizacao_ok: null,
    ...over,
  };
}

function frescor(matematica: Record<string, unknown> = {}): Frescor {
  return {
    limite_dias: 7, hoje: "2026-11-11", estado: "desatualizado",
    dimensoes: {
      leitura: bloco({ plataforma: "elefante", contratada: false, estado: null }),
      matematica: bloco(matematica),
    },
  } as Frescor;
}

describe("Selo de frescor — ajuste manual", () => {
  it("o ajuste manual aparece à parte: a data e o aviso continuam os da coleta", () => {
    render(<SeloFrescor frescor={frescor({ ajuste_manual_mais_recente_em: "2026-11-11" })}
                        dimensoes={["matematica"]} />);
    expect(screen.getByText(
      "Matemática (Matific): dados de 22/10/2026 (há 20 dias); ajuste manual em 11/11/2026",
    )).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(
      "Dado com mais de 7 dias: o mais recente é de 22/10/2026 (há 20 dias)");
  });

  it("sem ajuste manual em vigor, o selo fica como sempre", () => {
    render(<SeloFrescor frescor={frescor()} dimensoes={["matematica"]} />);
    expect(screen.getByText("Matemática (Matific): dados de 22/10/2026 (há 20 dias)"))
      .toBeInTheDocument();
    expect(screen.queryByText(/ajuste manual/)).not.toBeInTheDocument();
  });

  it("parte dos dados antiga não é chamada de coleta", () => {
    render(<SeloFrescor
      frescor={frescor({ estado: "parcial", dado_mais_recente_em: "2026-11-11",
        dias_desde_dado: 0, alunos_com_dado_antigo: 2 })}
      dimensoes={["matematica"]} />);
    const aviso = screen.getByRole("status");
    expect(aviso).toHaveTextContent("Parte dos dados é antiga: 2 de 3 aluno(s)");
    expect(aviso).toHaveTextContent("22/10/2026");
    expect(aviso).not.toHaveTextContent(/coleta parcial/i);
  });

  it("no painel da rede, a escola com parte dos dados antiga não é chamada de coleta parcial", async () => {
    responder("GET", "/redes/7/ranking/frescor", {
      limite_dias: 7, hoje: "2026-11-11",
      escolas: [{ ...frescor({ estado: "parcial", dado_mais_recente_em: "2026-11-11",
                               dias_desde_dado: 0, alunos_com_dado_antigo: 2 }),
                  escola_id: 1, nome: "EMEF Ficticia Ajuste" }],
    });
    renderComApp(<SeloFrescorDaRede redeId={7} dimensoes={["matematica"]} />);
    const aviso = await screen.findByRole("status");
    expect(aviso).toHaveTextContent(
      "1 escola(s) com dado de mais de 7 dias (ou parte dos dados antiga) entram nestes números");
    expect(aviso).not.toHaveTextContent(/coleta parcial/i);
  });
});
