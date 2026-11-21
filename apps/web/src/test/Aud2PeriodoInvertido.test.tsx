/**
 * Período personalizado com as datas trocadas (PERIODOS-6): o calendário do campo
 * "Data final" não oferece dia antes da data inicial, e o da "Data inicial" não oferece
 * dia depois da final. O backend também recusa (422, "inverta as duas"); aqui é a camada
 * de uso, para a pessoa nem chegar ao erro pelo calendário.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DatasDoPeriodo, SeletorPeriodo, type Periodo } from "../components/SeletorPeriodo";

describe("SeletorPeriodo — datas do personalizado", () => {
  it("a data final começa na inicial e a inicial termina na final", () => {
    const valor: Periodo = { preset: "personalizado", inicio: "2026-10-01", fim: "2026-10-31" };
    render(<SeletorPeriodo valor={valor} onChange={vi.fn()} />);
    expect(screen.getByLabelText("Data final")).toHaveAttribute("min", "2026-10-01");
    expect(screen.getByLabelText("Data inicial")).toHaveAttribute("max", "2026-10-31");
  });

  it("sem a outra data, o campo não tem limite (nada é travado à toa)", () => {
    render(<DatasDoPeriodo valor={{ preset: "personalizado" }} onChange={vi.fn()} estilo="" />);
    expect(screen.getByLabelText("Data final")).not.toHaveAttribute("min");
    expect(screen.getByLabelText("Data inicial")).not.toHaveAttribute("max");
  });

  it("o dia específico continua sem limite", () => {
    render(<DatasDoPeriodo valor={{ preset: "dia", inicio: "2026-10-05" }} onChange={vi.fn()} estilo="" />);
    const dia = screen.getByLabelText("Dia");
    expect(dia).not.toHaveAttribute("min");
    expect(dia).not.toHaveAttribute("max");
  });
});
