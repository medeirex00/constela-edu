import { describe, expect, it, vi } from "vitest";

import { ApiError } from "@constela/core";

// O cliente-query monta o persister (que toca o armazenamento cifrado): mockamos
// o armazenamento para o import não puxar os módulos nativos do Expo.
vi.mock("../armazenamento/armazenamentoCifrado", () => ({
  armazenamentoCifrado: {
    getItem: async () => null,
    setItem: async () => undefined,
    removeItem: async () => undefined,
  },
}));

import { clienteQuery } from "../cliente-query";

const queries = clienteQuery.getDefaultOptions().queries!;
const retry = queries.retry as (contador: number, erro: unknown) => boolean;
const retryDelay = queries.retryDelay as (tentativa: number) => number;

describe("política de retry do React Query (offline-first)", () => {
  it("não retenta erros 4xx do cliente (inclui 401/403/422)", () => {
    expect(retry(0, new ApiError(401, "sessão expirou"))).toBe(false);
    expect(retry(0, new ApiError(403, "sem acesso"))).toBe(false);
    expect(retry(0, new ApiError(422, "inválido"))).toBe(false);
  });

  it("retenta rede/5xx até 3 vezes", () => {
    expect(retry(0, new ApiError(500, "erro do servidor"))).toBe(true);
    expect(retry(2, new Error("rede caiu"))).toBe(true);
    expect(retry(3, new Error("rede caiu"))).toBe(false);
  });

  it("usa backoff exponencial com teto de 30s", () => {
    expect(retryDelay(0)).toBe(1000);
    expect(retryDelay(1)).toBe(2000);
    expect(retryDelay(2)).toBe(4000);
    expect(retryDelay(10)).toBe(30000); // capado
  });
});
