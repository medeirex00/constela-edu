// @vitest-environment jsdom
/**
 * Erro do servidor nas telas do app (auditoria MOBILE-4 e OBSERVABILIDADE-5).
 *
 * Painel, Ranking e Perfil do aluno só olhavam `data`/`isLoading` do useQuery. Com o
 * aparelho ONLINE e o servidor respondendo erro (403, 404, 500, 503) e nada salvo, o
 * Ranking dizia "Sem dados no período." e o Painel e o Perfil diziam para "conectar-se
 * uma vez" (texto de quem está sem internet), sem a mensagem do servidor nem como
 * tentar de novo. Telas reais no jsdom; só o `api` do core é trocado. Dados fictícios.
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

import * as React from "react";
import { QueryClient, QueryClientProvider, onlineManager } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import { ApiError, type PacoteSincronizacao } from "@constela/core";

import { clienteQuery } from "../cliente-query";
import Painel from "../telas/Painel";
import PerfilAluno from "../telas/PerfilAluno";
import Ranking from "../telas/Ranking";

(globalThis as { React?: unknown }).React = React;

let cliente: QueryClient;

function montar(tela: React.ReactElement) {
  // A política do app (offlineFirst, 3 retentativas para rede/5xx, nenhuma para
  // 4xx), sem a espera entre as tentativas.
  cliente = new QueryClient({
    defaultOptions: { queries: { ...clienteQuery.getDefaultOptions().queries, retryDelay: 0 } },
  });
  return render(React.createElement(QueryClientProvider, { client: cliente }, tela));
}

const perfilProps = { route: { params: { alunoId: 7, nome: "Aluna Ficticia" } } } as never;

const PACOTE: PacoteSincronizacao = {
  gerado_em: "2026-11-10T12:00:00Z",
  dashboard: {
    escola: { id: 1, nome: "EM FICTICIA", cidade: null, estado: null } as never,
    total_alunos: 4, total_turmas: 1, total_professores: 1, total_atividades: 11,
    total_livros: 12, tempo_leitura_min: 93, media_geral: 91.2, top10: [],
  },
  ranking: [{
    posicao: 1, aluno_id: 7, nome: "Aluna Ficticia", turma: "3º A", ano_escolar: "3º ano",
    nota_matific: 90, nota_elefante: 92, nota_geral: 91.2,
    aferido_leitura: true, aferido_matematica: true,
  }],
  evolucao: [],
  alertas: [],
  mural: [],
};

afterEach(() => {
  cleanup();
  cliente?.clear();
  apiMock.mockReset();
  onlineManager.setOnline(true);
});

describe("aparelho ONLINE, servidor responde erro e não há nada salvo", () => {
  it("Ranking com 403 mostra a mensagem do servidor, não 'Sem dados no período.'", async () => {
    apiMock.mockRejectedValue(new ApiError(403, "Acesso negado aos dados desta escola."));
    const { container } = montar(React.createElement(Ranking));
    await screen.findByText("Acesso negado aos dados desta escola.");
    expect(container.textContent).not.toContain("Sem dados no período.");
  });

  it("Painel com 503 mostra o erro, não 'conecte-se uma vez'", async () => {
    apiMock.mockRejectedValue(new ApiError(503, "Serviço indisponível"));
    const { container } = montar(React.createElement(Painel));
    await screen.findByText("Serviço indisponível");
    expect(container.textContent).not.toContain("conecte-se uma vez");
  });

  it("Perfil com 404 mostra 'Aluno não encontrado.', não 'indisponível offline'", async () => {
    apiMock.mockRejectedValue(new ApiError(404, "Aluno não encontrado."));
    const { container } = montar(React.createElement(PerfilAluno, perfilProps));
    await screen.findByText("Aluno não encontrado.");
    expect(container.textContent).not.toContain("indisponível offline");
  });

  it("'Tentar de novo' busca outra vez e mostra os dados quando o servidor volta", async () => {
    apiMock.mockRejectedValue(new ApiError(500, "Erro interno. Tente novamente em instantes."));
    const { container } = montar(React.createElement(Painel));
    const botao = await screen.findByText("Tentar de novo");
    expect(apiMock).toHaveBeenCalledTimes(4); // 1 + 3 retentativas do app
    apiMock.mockResolvedValue(PACOTE);
    await act(async () => {
      fireEvent.click(botao);
    });
    await waitFor(() => expect(container.textContent).toContain("Alunos"));
    expect(apiMock).toHaveBeenCalledTimes(5);
    expect(container.textContent).not.toContain("Erro interno");
  });
});

describe("os outros estados continuam como eram", () => {
  it("SEM rede e nada salvo: o texto de offline continua (Painel e Perfil)", async () => {
    onlineManager.setOnline(false);
    apiMock.mockRejectedValue(new ApiError(0, "Não foi possível conectar. Verifique a internet e tente de novo."));
    const painel = montar(React.createElement(Painel));
    await waitFor(() => expect(painel.container.textContent).toContain("conecte-se uma vez"));
    cleanup();
    const perfil = montar(React.createElement(PerfilAluno, perfilProps));
    await waitFor(() => expect(perfil.container.textContent).toContain("indisponível offline"));
  });

  it("SEM rede e nada salvo: o Ranking não afirma 'Sem dados no período.'", async () => {
    onlineManager.setOnline(false);
    apiMock.mockRejectedValue(new ApiError(0, "Não foi possível conectar. Verifique a internet e tente de novo."));
    const { container } = montar(React.createElement(Ranking));
    await waitFor(() => expect(container.textContent).toContain("conecte-se uma vez"));
    expect(container.textContent).not.toContain("Sem dados no período.");
  });

  it("com dados salvos e a atualização falhando: mantém os dados e avisa", async () => {
    apiMock.mockResolvedValueOnce(PACOTE);
    const { container } = montar(React.createElement(Ranking));
    await screen.findByText("Aluna Ficticia");
    apiMock.mockRejectedValue(new ApiError(500, "Erro interno. Tente novamente em instantes."));
    await act(async () => {
      await cliente.refetchQueries({ queryKey: ["sincronizacao", 1] });
    });
    await screen.findByText(/Erro interno\. Tente novamente em instantes\./);
    expect(container.textContent).toContain("Aluna Ficticia");
  });

  it("lista vazia de verdade continua 'Sem dados no período.'", async () => {
    apiMock.mockResolvedValue({ ...PACOTE, ranking: [] });
    await act(async () => {
      montar(React.createElement(Ranking));
    });
    await screen.findByText("Sem dados no período.");
  });
});
