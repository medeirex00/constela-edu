/**
 * Assistente — F02 (Onda 3): erro ao abrir uma conversa antiga é SURFAÇADO,
 * não engolido. Antes, abrirConversa fazia `.catch(() => null)` e o clique
 * virava um no-op silencioso (nenhuma mensagem, nenhum feedback).
 */
import { expect, test } from "vitest";

import Assistente from "../pages/Assistente";
import { renderComApp, responder, responderErro, screen, userEvent } from "./utils";

function _prepararLista() {
  responder("GET", "/escolas/1/assistente/conversas", [
    { id: 7, titulo: "Conversa antiga", provedor: "local", created_at: "2026-07-01T10:00:00Z" },
  ]);
  responder("GET", "/escolas/1/assistente/status", { provedor: "local" });
}

test("F02: falha ao abrir conversa mostra o erro (não é engolido)", async () => {
  _prepararLista();
  responderErro("GET", /\/assistente\/conversas\/7$/, 500, "Servidor fora do ar");

  renderComApp(<Assistente />);
  const item = await screen.findByText("Conversa antiga");
  await userEvent.click(item);

  // O erro aparece na coluna de conversas (antes: silêncio total).
  expect(await screen.findByText("Servidor fora do ar")).toBeInTheDocument();
});

test("F02: abrir conversa com sucesso carrega as mensagens e não deixa erro", async () => {
  _prepararLista();
  responder("GET", /\/assistente\/conversas\/7$/, {
    id: 7,
    mensagens: [{ papel: "usuario", conteudo: "Olá?" }],
  });

  renderComApp(<Assistente />);
  await userEvent.click(await screen.findByText("Conversa antiga"));

  expect(await screen.findByText("Olá?")).toBeInTheDocument();
  expect(screen.queryByText("Não consegui abrir esta conversa. Tente de novo.")).toBeNull();
});
