// @vitest-environment jsdom
/**
 * G_MODULOS-4 (app) — o Painel não mostra o cartão do módulo fora do plano.
 *
 * Numa rede só com Leitura, o Painel mostrava "Atividades" (a soma do Matific, ou
 * "Atividades 0" numa rede que nunca o teve). O pacote `/sincronizacao` passa a
 * dizer os módulos da escola; o Painel esconde o que a rede não contratou — nem
 * zerado. Pacote antigo (sem a lista) segue mostrando tudo. Dados fictícios.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

const { apiMock } = vi.hoisted(() => ({ apiMock: vi.fn() }));

vi.mock("react", async () => {
  const { createRequire } = await import("node:module");
  const path = await import("node:path");
  const exigir = createRequire(import.meta.url);
  const dirReactDom = path.dirname(exigir.resolve("react-dom/package.json"));
  return exigir(exigir.resolve("react", { paths: [dirReactDom] }));
});
vi.mock("react-native", async () => (await import("./_rnFalso")).reactNativeFalso);
vi.mock("@constela/core", async (real) => ({
  ...(await real<typeof import("@constela/core")>()),
  api: apiMock,
}));
vi.mock("../contexto/Autenticacao", () => ({
  useAutenticacao: () => ({ escolaId: 1, escolas: [{ id: 1, nome: "EM INVENTADA" }] }),
}));
vi.mock("@react-navigation/native", () => ({ useNavigation: () => ({ navigate: () => undefined }) }));
vi.mock("../armazenamento/armazenamentoCifrado", () => ({
  armazenamentoCifrado: {
    getItem: async () => null,
    setItem: async () => undefined,
    removeItem: async () => undefined,
  },
}));

import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, waitFor } from "@testing-library/react";

import type { PacoteSincronizacao } from "@constela/core";

import Painel from "../telas/Painel";

(globalThis as { React?: unknown }).React = React;

let cliente: QueryClient;

function montar() {
  cliente = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(React.createElement(QueryClientProvider, { client: cliente },
    React.createElement(Painel)));
}

function pacote(modulos?: PacoteSincronizacao["modulos"]): PacoteSincronizacao {
  return {
    gerado_em: "2026-11-10T12:00:00Z",
    ...(modulos ? { modulos } : {}),
    dashboard: {
      escola: { id: 1, nome: "EM INVENTADA", cidade: null, estado: null } as never,
      total_alunos: 4, total_turmas: 1, total_professores: 1, total_atividades: 0,
      total_livros: 12, tempo_leitura_min: 93, media_geral: 91.2, top10: [],
    },
    ranking: [],
    evolucao: [],
    alertas: [],
    mural: [],
  };
}

afterEach(() => {
  cleanup();
  cliente?.clear();
  apiMock.mockReset();
});

describe("Painel do app e o contrato da rede", () => {
  it("rede só com Leitura: sem o cartão 'Atividades' (nem zerado)", async () => {
    apiMock.mockResolvedValue(pacote(["leitura"]));
    const { container } = montar();
    await waitFor(() => expect(container.textContent).toContain("Alunos"));
    expect(container.textContent).not.toContain("Atividades");
    expect(container.textContent).toContain("Livros");
  });

  it("rede só com Matemática: sem 'Livros' nem 'Leitura'", async () => {
    apiMock.mockResolvedValue(pacote(["matematica"]));
    const { container } = montar();
    await waitFor(() => expect(container.textContent).toContain("Alunos"));
    expect(container.textContent).toContain("Atividades");
    expect(container.textContent).not.toContain("Livros");
    expect(container.textContent).not.toMatch(/\bLeitura\b/);
  });

  it("pacote de servidor antigo (sem a lista): mostra os dois, como antes", async () => {
    apiMock.mockResolvedValue(pacote());
    const { container } = montar();
    await waitFor(() => expect(container.textContent).toContain("Alunos"));
    expect(container.textContent).toContain("Atividades");
    expect(container.textContent).toContain("Livros");
  });
});
