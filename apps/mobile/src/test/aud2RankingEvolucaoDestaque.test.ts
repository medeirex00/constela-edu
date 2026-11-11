// @vitest-environment jsdom
/**
 * Aba "Evolução (30d)" do Ranking do app: o destaque de top 3 é só de quem CRESCEU
 * (auditoria RANKINGS-4, pendência da fase B).
 *
 * O backend já não manda quem não tem dado, mas quem tem dado e não cresceu (0,0)
 * continua na lista — e a etiqueta de posição pintava de destaque os 3 primeiros sem
 * olhar o valor: num período em que ninguém cresceu, três "medalhas" para 0,0. A web
 * (pódio do Ranking de Evolução) e o telão só destacam quem tem evolução acima de zero.
 * A lista continua com todos (0,0 de quem tem dado é zero legítimo). Dados fictícios.
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
  useAutenticacao: () => ({ escolaId: 1, escolas: [{ id: 1, nome: "EM FICTICIA" }] }),
}));
vi.mock("@react-navigation/native", () => ({ useNavigation: () => ({ navigate: () => undefined }) }));
vi.mock("../armazenamento/armazenamentoCifrado", () => ({
  armazenamentoCifrado: {
    getItem: async () => null,
    setItem: async () => undefined,
    removeItem: async () => undefined,
  },
}));
// O dublê do react-native não leva o estilo ao DOM: a etiqueta expõe o tom num atributo.
vi.mock("../componentes/basicos", async (real) => {
  const { createElement } = await import("react");
  return {
    ...(await real<typeof import("../componentes/basicos")>()),
    Etiqueta: ({ texto, tom = "neutro" }: { texto: string; tom?: string }) =>
      createElement("span", { "data-testid": `posicao-${texto}`, "data-tom": tom }, texto),
  };
});

import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import type { PacoteSincronizacao } from "@constela/core";

import { clienteQuery } from "../cliente-query";
import Ranking from "../telas/Ranking";

(globalThis as { React?: unknown }).React = React;

let cliente: QueryClient;

function montar() {
  cliente = new QueryClient({
    defaultOptions: { queries: { ...clienteQuery.getDefaultOptions().queries, retryDelay: 0 } },
  });
  return render(React.createElement(QueryClientProvider, { client: cliente }, React.createElement(Ranking)));
}

const linhaGeral = (posicao: number, aluno_id: number, nome: string) => ({
  posicao, aluno_id, nome, turma: "3º A", ano_escolar: "3º ano",
  nota_matific: 80, nota_elefante: 80, nota_geral: 80 - posicao,
  aferido_leitura: true, aferido_matematica: true,
});
const linhaEvolucao = (posicao: number, aluno_id: number, nome: string, nota_evolucao: number) => ({
  posicao, aluno_id, nome, turma: "3º A", nota_evolucao,
});

function pacote(evolucao: ReturnType<typeof linhaEvolucao>[]): PacoteSincronizacao {
  return {
    gerado_em: "2026-11-10T12:00:00Z",
    dashboard: {
      escola: { id: 1, nome: "EM FICTICIA", cidade: null, estado: null } as never,
      total_alunos: 3, total_turmas: 1, total_professores: 1, total_atividades: 0,
      total_livros: 0, tempo_leitura_min: 0, media_geral: null, top10: [],
    },
    ranking: [
      linhaGeral(1, 1, "Aluna Ficticia Um"), linhaGeral(2, 2, "Aluno Ficticio Dois"),
      linhaGeral(3, 3, "Aluna Ficticia Tres"),
    ],
    evolucao,
    alertas: [],
    mural: [],
  } as unknown as PacoteSincronizacao;
}

const tomDa = (posicao: number) => screen.getByTestId(`posicao-${posicao}º`).getAttribute("data-tom");

afterEach(() => {
  cleanup();
  cliente?.clear();
  apiMock.mockReset();
});

async function abrirEvolucao() {
  await screen.findByText("Aluna Ficticia Um");
  fireEvent.click(screen.getByText("Evolução (30d)"));
}

describe("Ranking do app, aba Evolução (30d)", () => {
  it("ninguém cresceu: nenhuma posição em destaque, e a lista continua com todos", async () => {
    apiMock.mockResolvedValue(pacote([
      linhaEvolucao(1, 1, "Aluna Ficticia Um", 0), linhaEvolucao(2, 2, "Aluno Ficticio Dois", 0),
      linhaEvolucao(3, 3, "Aluna Ficticia Tres", 0),
    ]));
    montar();
    await abrirEvolucao();
    await screen.findByText("Aluna Ficticia Tres");
    expect([tomDa(1), tomDa(2), tomDa(3)], "destaque de top 3 para 0,0 de evolução")
      .toEqual(["neutro", "neutro", "neutro"]);
  });

  it("só o 1º cresceu: só ele fica em destaque", async () => {
    apiMock.mockResolvedValue(pacote([
      linhaEvolucao(1, 3, "Aluna Ficticia Tres", 7.5), linhaEvolucao(2, 1, "Aluna Ficticia Um", 0),
      linhaEvolucao(3, 2, "Aluno Ficticio Dois", 0),
    ]));
    montar();
    await abrirEvolucao();
    await screen.findByText("7,5");
    expect([tomDa(1), tomDa(2), tomDa(3)]).toEqual(["destaque", "neutro", "neutro"]);
  });

  it("o Ranking Geral continua destacando os 3 primeiros", async () => {
    apiMock.mockResolvedValue(pacote([]));
    montar();
    await screen.findByText("Aluna Ficticia Um");
    expect([tomDa(1), tomDa(2), tomDa(3)]).toEqual(["destaque", "destaque", "destaque"]);
  });
});
