import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, MENSAGEM_SEM_REDE, api } from "./cliente";

describe("cliente HTTP: falha de rede vira ApiError(0) em pt-BR", () => {
  const fetchOriginal = globalThis.fetch;
  afterEach(() => {
    globalThis.fetch = fetchOriginal;
    vi.restoreAllMocks();
  });

  it("rejeição do fetch (rede/DNS/offline) → ApiError(0) com mensagem pt-BR, nunca 'Failed to fetch'", async () => {
    globalThis.fetch = vi.fn(() =>
      Promise.reject(new TypeError("Failed to fetch")),
    ) as unknown as typeof fetch;

    const erro = (await api("/qualquer").catch((e) => e)) as ApiError;
    expect(erro).toBeInstanceOf(ApiError);
    expect(erro.status).toBe(0);
    expect(erro.message).toBe(MENSAGEM_SEM_REDE);
    expect(erro.message).not.toMatch(/failed to fetch/i);
  });

  it("resposta HTTP de erro preserva o status do servidor (não é tratada como rede)", async () => {
    globalThis.fetch = vi.fn(() =>
      Promise.resolve(
        new Response(JSON.stringify({ detail: "Requisição inválida." }), {
          status: 400,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    ) as unknown as typeof fetch;

    const erro = (await api("/qualquer").catch((e) => e)) as ApiError;
    expect(erro).toBeInstanceOf(ApiError);
    expect(erro.status).toBe(400);
  });
});
