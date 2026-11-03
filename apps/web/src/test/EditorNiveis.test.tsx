/**
 * Editor das faixas de dificuldade (EditorNiveis): remover um nível pede
 * confirmação no diálogo da v2 (antes era window.confirm). Abrir o diálogo não
 * chama a API; confirmar faz o MESMO DELETE de antes; cancelar não apaga nada.
 * Fora do Admin Global a tela é somente leitura (sem botão de remover).
 */
import { describe, expect, it } from "vitest";

import { EditorNiveis } from "../pages/configuracoes/dificuldade";
import { api, renderComApp, responder, screen, userEvent, usuarioFake, within } from "./utils";

const URL_DIFICULDADE = "/escolas/1/configuracoes/dificuldade";
const URL_NIVEL_2 = "/escolas/1/configuracoes/niveis/2";
const global = usuarioFake({ is_global: true, cargo: "admin", nome: "Root" });

const NIVEIS = [
  { id: 1, nome: "Pré-Leitor", codigos: ["AA"], pontos_padrao: 1, ordem: 1 },
  { id: 2, nome: "Nível 1", codigos: ["BB", "CC"], pontos_padrao: 2, ordem: 2 },
];

function chamouDelete(): boolean {
  return api.mock.calls.some(
    ([, opcoes]) => (opcoes as RequestInit | undefined)?.method === "DELETE",
  );
}

describe("EditorNiveis — remover nível", () => {
  it("abrir a confirmação não chama a API; confirmar faz o DELETE do nível", async () => {
    const u = userEvent.setup();
    let niveis = NIVEIS;
    responder("GET", URL_DIFICULDADE, () => ({ niveis }));
    responder("DELETE", URL_NIVEL_2, () => {
      niveis = NIVEIS.filter((n) => n.id !== 2);
      return { ok: true };
    });
    renderComApp(<EditorNiveis />, { usuario: global });

    await u.click(await screen.findByRole("button", { name: "Remover nível Nível 1" }));
    const dialogo = await screen.findByRole("dialog", { name: "Remover este nível?" });
    expect(dialogo).toHaveTextContent("Remover o nível “Nível 1”?");
    expect(dialogo).toHaveTextContent(/pontuações que dependem dele serão recalculadas/);
    expect(chamouDelete()).toBe(false);

    await u.click(within(dialogo).getByRole("button", { name: "Remover nível" }));

    expect(await screen.findByText("Nível “Nível 1” removido. Notas recalculadas.")).toBeInTheDocument();
    expect(api).toHaveBeenCalledWith(URL_NIVEL_2, { method: "DELETE" });
    expect(screen.queryByRole("dialog", { name: "Remover este nível?" })).toBeNull();
    // Recarregado: a faixa removida sai da tabela.
    expect(await screen.findByRole("button", { name: "Remover nível Pré-Leitor" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Remover nível Nível 1" })).toBeNull();
  });

  it("cancelar a confirmação não remove nada", async () => {
    const u = userEvent.setup();
    responder("GET", URL_DIFICULDADE, { niveis: NIVEIS });
    responder("DELETE", URL_NIVEL_2, { ok: true });
    renderComApp(<EditorNiveis />, { usuario: global });

    await u.click(await screen.findByRole("button", { name: "Remover nível Nível 1" }));
    const dialogo = await screen.findByRole("dialog", { name: "Remover este nível?" });
    await u.click(within(dialogo).getByRole("button", { name: "Cancelar" }));

    expect(screen.queryByRole("dialog", { name: "Remover este nível?" })).toBeNull();
    expect(chamouDelete()).toBe(false);
    expect(screen.getByRole("button", { name: "Remover nível Nível 1" })).toBeInTheDocument();
  });

  it("fora do Admin Global a tela é somente leitura: sem remover", async () => {
    responder("GET", URL_DIFICULDADE, { niveis: NIVEIS });
    renderComApp(<EditorNiveis />, { usuario: usuarioFake({ is_global: false, cargo: "admin" }) });

    expect(await screen.findByDisplayValue("Nível 1")).toBeDisabled();
    expect(screen.queryByRole("button", { name: /Remover nível/ })).toBeNull();
  });
});
