import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LimiteErro } from "../components/LimiteErro";

function Bomba(): never {
  throw new Error("boom de render");
}

describe("LimiteErro (Error Boundary)", () => {
  beforeEach(() => {
    // React loga o erro capturado no console — silencia o ruído esperado.
    vi.spyOn(console, "error").mockImplementation(() => undefined);
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("mostra a tela de recuperação quando um filho quebra ao renderizar", () => {
    render(
      <LimiteErro>
        <Bomba />
      </LimiteErro>,
    );
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByText("Algo deu errado")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Recarregar" }),
    ).toBeInTheDocument();
  });

  it("renderiza os filhos normalmente quando não há erro", () => {
    render(
      <LimiteErro>
        <p>conteudo ok</p>
      </LimiteErro>,
    );
    expect(screen.getByText("conteudo ok")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
