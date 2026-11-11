/**
 * Configurações: o “Ano letivo ativo” para quem não é Admin Global (S_G_VIRADA-6).
 *
 * O campo vinha editável para o admin da escola e o PATCH sempre levava
 * `ano_letivo_ativo`. Na virada, o admin trocava 2026 por 2027 e aproveitava para
 * corrigir o nome: o servidor recusava o PATCH inteiro (403, “Só o administrador
 * global altera o ano letivo ativo.”) e o nome digitado não era salvo. Agora o campo
 * fica só para leitura, com a dica de quem troca o ano, e o PATCH só leva o ano quando
 * o Admin Global o muda. Dados fictícios.
 */
import { describe, expect, it } from "vitest";

import Configuracoes from "../pages/configuracoes/Configuracoes";
import { api, renderComApp, responder, screen, userEvent, usuarioFake, within } from "./utils";

const URL_ESCOLA = "/escolas/1";

function carregar() {
  responder("GET", "/escolas/1/configuracoes/pesos/geral",
    { namespace: "geral", valores: { matific: 60, elefante: 40 }, soma: 100 });
  responder("GET", "/escolas/1/aparencia", { cor_primaria: "#1B2A4A" });
  responder("PATCH", URL_ESCOLA, { id: 1, nome: "Escola Ficticia Renomeada" });
}

function corposDoPatch(): Record<string, unknown>[] {
  return api.mock.calls
    .filter(([url, opcoes]) => url === URL_ESCOLA && (opcoes as RequestInit | undefined)?.method === "PATCH")
    .map(([, opcoes]) => JSON.parse(String((opcoes as RequestInit).body)));
}

describe("Configurações — ano letivo ativo para quem não é Admin Global", () => {
  it("admin da escola vê o ano só para leitura, com a dica, e salva o nome sem mandar o ano", async () => {
    const u = userEvent.setup();
    carregar();
    renderComApp(<Configuracoes />, {
      rota: "/configuracoes",
      usuario: usuarioFake({ cargo: "admin", is_global: false }),
    });

    const nome = await screen.findByDisplayValue("Escola Modelo Constela");
    const ano = screen.getByRole("spinbutton", { name: "Ano letivo ativo" }) as HTMLInputElement;
    expect(ano.readOnly || ano.disabled).toBe(true);
    expect(ano).toHaveValue(2026);
    expect(ano).toHaveAccessibleDescription(/Só o Admin Global troca o ano letivo ativo/);

    // Digitar no campo não muda o ano (só leitura).
    await u.type(ano, "7");
    expect(ano).toHaveValue(2026);

    await u.clear(nome);
    await u.type(nome, "Escola Ficticia Renomeada");
    await u.click(screen.getByRole("button", { name: "Salvar dados da escola" }));

    expect(await screen.findByText("Dados da escola atualizados.")).toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "Trocar o ano letivo ativo?" })).toBeNull();
    const corpos = corposDoPatch();
    expect(corpos).toHaveLength(1);
    expect(corpos[0]).toMatchObject({ nome: "Escola Ficticia Renomeada" });
    expect(corpos[0]).not.toHaveProperty("ano_letivo_ativo");
  });

  it("Admin Global: o campo segue editável e o ano só vai no PATCH quando muda", async () => {
    const u = userEvent.setup();
    carregar();
    renderComApp(<Configuracoes />, {
      rota: "/configuracoes",
      usuario: usuarioFake({ cargo: "admin", is_global: true }),
    });

    const nome = await screen.findByDisplayValue("Escola Modelo Constela");
    const ano = screen.getByRole("spinbutton", { name: "Ano letivo ativo" }) as HTMLInputElement;
    expect(ano.readOnly || ano.disabled).toBe(false);
    expect(screen.queryByText(/Só o Admin Global troca o ano letivo ativo/)).toBeNull();

    // Só o nome: o ano não vai.
    await u.clear(nome);
    await u.type(nome, "Escola Ficticia Renomeada");
    await u.click(screen.getByRole("button", { name: "Salvar dados da escola" }));
    expect(await screen.findByText("Dados da escola atualizados.")).toBeInTheDocument();
    expect(corposDoPatch()[0]).not.toHaveProperty("ano_letivo_ativo");

    // Trocar o ano: confirma e o ano vai.
    await u.clear(ano);
    await u.type(ano, "2027");
    await u.click(screen.getByRole("button", { name: "Salvar dados da escola" }));
    const dialogo = await screen.findByRole("dialog", { name: "Trocar o ano letivo ativo?" });
    await u.click(within(dialogo).getByRole("button", { name: "Trocar para 2027" }));
    await screen.findByText("Dados da escola atualizados.");
    const corpos = corposDoPatch();
    expect(corpos).toHaveLength(2);
    expect(corpos[1]).toMatchObject({ ano_letivo_ativo: 2027 });
  });
});
