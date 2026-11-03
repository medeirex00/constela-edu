/**
 * Assistente — F02 (Onda 3): erro ao abrir uma conversa antiga é SURFAÇADO,
 * não engolido. Antes, abrirConversa fazia `.catch(() => null)` e o clique
 * virava um no-op silencioso (nenhuma mensagem, nenhum feedback).
 */
import { expect, test, vi } from "vitest";

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

test("revisão v2: a página não abre rolada — só a caixa das mensagens rola até a última", async () => {
  // Antes: scrollIntoView no fim da lista também rolava a JANELA, e a página já
  // abria com o título escondido sob o cabeçalho fixo.
  _prepararLista();
  responder("GET", /\/assistente\/conversas\/7$/, {
    id: 7,
    mensagens: [
      { papel: "usuario", conteudo: "Como estão as turmas?" },
      { papel: "assistente", conteudo: "Todas com dados recentes." },
    ],
  });
  const rolarElemento = vi.spyOn(Element.prototype, "scrollIntoView");
  const rolarJanela = vi.spyOn(window, "scrollTo").mockImplementation(() => undefined);
  try {
    renderComApp(<Assistente />);
    await screen.findByText("Conversa antiga");
    expect(rolarElemento).not.toHaveBeenCalled();
    expect(rolarJanela).not.toHaveBeenCalled();

    // A caixa das mensagens é a área rolável logo acima do campo de pergunta.
    const caixa = screen.getByRole("textbox", { name: "Sua pergunta" })
      .closest("form")?.previousElementSibling as HTMLElement;
    expect(caixa).toHaveClass("overflow-y-auto");
    let topo = 0;
    Object.defineProperty(caixa, "scrollHeight", { configurable: true, value: 640 });
    Object.defineProperty(caixa, "scrollTop", {
      configurable: true,
      get: () => topo,
      set: (valor: number) => { topo = valor; },
    });

    await userEvent.click(screen.getByText("Conversa antiga"));
    expect(await screen.findByText("Todas com dados recentes.")).toBeInTheDocument();
    expect(topo).toBe(640);
    expect(rolarElemento).not.toHaveBeenCalled();
    expect(rolarJanela).not.toHaveBeenCalled();
  } finally {
    rolarElemento.mockRestore();
    rolarJanela.mockRestore();
  }
});
