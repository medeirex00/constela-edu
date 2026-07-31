import { describe, expect, it } from "vitest";

import { SecaoRecolhivel } from "../components/ui";
import { render, screen, userEvent } from "./utils";

describe("SecaoRecolhivel", () => {
  it("começa aberta e recolhe/expande ao clicar no cabeçalho", async () => {
    render(
      <SecaoRecolhivel titulo="Localização no mapa">
        <p>conteúdo interno</p>
      </SecaoRecolhivel>,
    );
    const u = userEvent.setup();
    const cabecalho = screen.getByRole("button", { name: /localização no mapa/i });

    // Estado inicial: expandida (mantém o comportamento atual).
    expect(cabecalho).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("conteúdo interno")).toBeInTheDocument();

    await u.click(cabecalho);
    expect(cabecalho).toHaveAttribute("aria-expanded", "false");

    await u.click(cabecalho);
    expect(cabecalho).toHaveAttribute("aria-expanded", "true");
  });

  it("respeita inicialAberto=false", () => {
    render(
      <SecaoRecolhivel titulo="Códigos INEP das escolas" inicialAberto={false}>
        <p>códigos</p>
      </SecaoRecolhivel>,
    );
    expect(
      screen.getByRole("button", { name: /códigos inep/i }),
    ).toHaveAttribute("aria-expanded", "false");
  });

  it("clicar numa ação do cabeçalho NÃO recolhe a seção", async () => {
    render(
      <SecaoRecolhivel
        titulo="Localização no mapa"
        acoes={<button type="button">Salvar</button>}
      >
        <p>conteúdo</p>
      </SecaoRecolhivel>,
    );
    const u = userEvent.setup();
    const cabecalho = screen.getByRole("button", { name: /localização no mapa/i });
    expect(cabecalho).toHaveAttribute("aria-expanded", "true");

    await u.click(screen.getByRole("button", { name: "Salvar" }));
    // A ação fica FORA do botão de toggle — não altera o estado aberto/fechado.
    expect(cabecalho).toHaveAttribute("aria-expanded", "true");
  });
});
