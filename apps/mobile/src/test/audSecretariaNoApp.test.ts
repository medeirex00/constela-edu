// @vitest-environment jsdom
/**
 * Secretaria no app (auditoria MOBILE-1, parte do app).
 *
 * O pacote /sincronizacao recorta tudo pelas turmas permitidas, que para a
 * Secretaria é a lista vazia de propósito (ela nunca vê nome de criança): o Painel
 * mostrava a escola com "0 Alunos · Média geral 0,0 · 0 Livros · 0 Turmas" e o
 * Ranking "Sem dados no período.", como se fossem os números dela. O servidor
 * passou a responder 403 com a explicação (54088a01); aqui, o app não mostra o
 * Painel nem o Ranking da escola à Secretaria, e sim a mesma explicação.
 * Navegação real do app (navegacao.tsx) com os navegadores trocados por dublês que
 * desenham todas as abas. Dados fictícios.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

const { apiMock, sessao } = vi.hoisted(() => ({
  apiMock: vi.fn(),
  sessao: { usuario: null as unknown },
}));

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
  useAutenticacao: () => ({
    usuario: sessao.usuario,
    escolaId: 1,
    escolas: [{ id: 1, nome: "EM FICTICIA" }],
    selecionarEscola: () => undefined,
    sair: async () => undefined,
  }),
}));
vi.mock("../api", () => ({ BASE_API: "http://servidor-ficticio/api/v1" }));
vi.mock("@react-native-community/netinfo", () => ({ useNetInfo: () => ({ isConnected: true }) }));
vi.mock("expo-linking", () => ({ openURL: async () => undefined }));
vi.mock("expo-camera", () => ({
  useCameraPermissions: () => [{ granted: false }, async () => ({ granted: false })],
  CameraView: () => null,
}));
vi.mock("@react-navigation/native", () => ({ useNavigation: () => ({ navigate: () => undefined }) }));
vi.mock("@react-navigation/bottom-tabs", async () => {
  const { createElement, Children } = await import("react");
  type Tela = { name: string; component: () => unknown };
  return {
    // Desenha TODAS as abas, cada uma numa <section data-aba="..."> (como o
    // react-navigation, ignora o que não é tela: Children.toArray tira o null).
    createBottomTabNavigator: () => ({
      Navigator: ({ children }: { children: unknown }) =>
        createElement("main", null, (Children.toArray(children as never) as { props: Tela }[])
          .map((filho) => createElement("section", { key: filho.props.name, "data-aba": filho.props.name },
            createElement(filho.props.component as never)))),
      Screen: () => null,
    }),
  };
});
vi.mock("@react-navigation/native-stack", async () => {
  const { createElement, Children } = await import("react");
  return {
    // A pilha desenha só a primeira tela (as abas).
    createNativeStackNavigator: () => ({
      Navigator: ({ children }: { children: unknown }) => {
        const [primeira] = Children.toArray(children as never) as { props: { component: never } }[];
        return createElement(primeira.props.component);
      },
      Screen: () => null,
    }),
  };
});

import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, waitFor } from "@testing-library/react";

import type { PacoteSincronizacao } from "@constela/core";

import { NavegacaoPrincipal } from "../navegacao";

(globalThis as { React?: unknown }).React = React;

const SECRETARIA = { id: 3, nome: "Secretaria Ficticia", email: "seduc@ficticio.local",
  cargo: "coordenador", is_global: false, escola_id: null, rede_id: 1 };
const COORDENADORA = { ...SECRETARIA, id: 4, email: "coord@ficticio.local", escola_id: 1, rede_id: null };
const ADMIN_GLOBAL = { ...SECRETARIA, id: 5, email: "admin@ficticio.local", cargo: "admin", is_global: true };

// O pacote que o servidor ANTES desta correção devolvia à Secretaria (tudo zerado).
const PACOTE_ZERADO: PacoteSincronizacao = {
  gerado_em: "2026-11-10T12:00:00Z",
  dashboard: {
    escola: { id: 1, nome: "EM FICTICIA", cidade: null, estado: null } as never,
    total_alunos: 0, total_turmas: 0, total_professores: 0, total_atividades: 0,
    total_livros: 0, tempo_leitura_min: 0, media_geral: 0, top10: [],
  },
  ranking: [], evolucao: [], alertas: [], mural: [],
};

function montar() {
  const cliente = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(React.createElement(QueryClientProvider, { client: cliente },
    React.createElement(NavegacaoPrincipal)));
}

const abas = (container: HTMLElement) =>
  Array.from(container.querySelectorAll("section[data-aba]")).map((s) => s.getAttribute("data-aba"));

afterEach(() => {
  cleanup();
  apiMock.mockReset();
});

describe("Secretaria no app", () => {
  it("não vê o Painel nem o Ranking da escola zerados, e sim a explicação", async () => {
    sessao.usuario = SECRETARIA;
    apiMock.mockResolvedValue(PACOTE_ZERADO);
    const { container } = montar();
    await new Promise((r) => setTimeout(r, 30));
    const texto = container.textContent ?? "";
    expect(texto).not.toContain("Alunos");
    expect(texto).not.toContain("Média geral");
    expect(texto).not.toContain("Sem dados no período.");
    expect(texto).toContain("A Secretaria acompanha a rede pelo Panorama da Rede, na versão web.");
    expect(abas(container)).not.toContain("Ranking");
    expect(apiMock).not.toHaveBeenCalledWith("/escolas/1/sincronizacao");
  });

  it.each([
    ["coordenação", COORDENADORA],
    ["admin global (tem rede, mas é global)", ADMIN_GLOBAL],
  ])("%s continua com Painel e Ranking", async (_rotulo, usuario) => {
    sessao.usuario = usuario;
    apiMock.mockResolvedValue({ ...PACOTE_ZERADO, dashboard: { ...PACOTE_ZERADO.dashboard, total_alunos: 4 } });
    const { container } = montar();
    await waitFor(() => expect(container.textContent).toContain("Alunos"));
    expect(abas(container)).toEqual(["Painel", "Ranking", "Scanner", "Ajustes"]);
    expect(container.textContent).not.toContain("Panorama da Rede");
  });
});
