// @vitest-environment jsdom
/**
 * "Sair da conta" dá retorno (auditoria MOBILE-2): enquanto a saída acontece, o
 * botão diz "Saindo..." e não aceita um segundo toque. Antes, `onPress={() =>
 * sair()}` não mostrava nada e cada toque disparava outra saída. Tela real de
 * Ajustes; o contexto, a rede e o cliente da API são dublês. Dados fictícios.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

const { sair } = vi.hoisted(() => ({ sair: vi.fn() }));

vi.mock("react", async () => {
  const { createRequire } = await import("node:module");
  const path = await import("node:path");
  const exigir = createRequire(import.meta.url);
  const dirReactDom = path.dirname(exigir.resolve("react-dom/package.json"));
  return exigir(exigir.resolve("react", { paths: [dirReactDom] }));
});
vi.mock("react-native", async () => (await import("./_rnFalso")).reactNativeFalso);
vi.mock("../contexto/Autenticacao", () => ({
  useAutenticacao: () => ({
    usuario: { id: 9, nome: "Prof Ficticia", email: "prof@ficticio.local", cargo: "professor" },
    escolas: [{ id: 1, nome: "EM FICTICIA" }],
    escolaId: 1,
    selecionarEscola: () => undefined,
    sair,
  }),
}));
vi.mock("../api", () => ({ BASE_API: "http://servidor-ficticio/api/v1" }));
vi.mock("@react-native-community/netinfo", () => ({ useNetInfo: () => ({ isConnected: true }) }));

import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";

import Ajustes from "../telas/Ajustes";

(globalThis as { React?: unknown }).React = React;

function montar() {
  return render(React.createElement(QueryClientProvider, { client: new QueryClient() },
    React.createElement(Ajustes)));
}

afterEach(() => {
  cleanup();
  sair.mockReset();
});

describe("botão 'Sair da conta'", () => {
  it("mostra 'Saindo...' e não dispara uma segunda saída", async () => {
    sair.mockReturnValue(new Promise(() => undefined)); // a saída ainda não terminou
    montar();
    await act(async () => {
      fireEvent.click(screen.getByText("Sair da conta"));
    });
    expect(screen.getByText("Saindo...")).toBeTruthy();
    await act(async () => {
      fireEvent.click(screen.getByText("Saindo..."));
    });
    expect(sair).toHaveBeenCalledTimes(1);
  });

  it("se a saída falhar, o botão volta a 'Sair da conta'", async () => {
    sair.mockRejectedValue(new Error("falhou"));
    montar();
    await act(async () => {
      fireEvent.click(screen.getByText("Sair da conta"));
    });
    expect(screen.getByText("Sair da conta")).toBeTruthy();
  });
});
