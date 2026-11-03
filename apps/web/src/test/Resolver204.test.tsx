/**
 * "Resolver" um alerta da sincronização: POST /sync/alertas/<id>/resolver
 * responde 204 SEM CORPO. Este teste usa o cliente REAL do @constela/core (não o
 * mock das telas, que devolve o valor do handler e esconderia o problema) com um
 * fetch que devolve exatamente um 204 vazio, e o `useMutation` REAL da tela.
 *
 * Antes, o cliente fazia `resposta.json()` no 204 → SyntaxError → o useMutation
 * mostrava "Falha de conexão" e NÃO chamava o aoSucesso (a tela não recarregava),
 * embora o servidor tivesse resolvido o alerta.
 */
import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { api as apiReal, configurarApi } from "@constela/core";

import { useMutation } from "../hooks/useMutation";

const fetchOriginal = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = fetchOriginal;
});

function configurar204() {
  configurarApi({
    base: "",
    armazenamento: { obter: () => "token-ficticio", guardar: () => undefined, remover: () => undefined },
    aoExpirarSessao: () => undefined,
  });
  globalThis.fetch = vi.fn(async () => new Response(null, { status: 204 })) as unknown as typeof fetch;
}

describe("204 sem corpo no cliente real", () => {
  it("api() resolve um 204 vazio sem erro", async () => {
    configurar204();
    await expect(
      apiReal("/escolas/17/sync/alertas/1/resolver", { method: "POST" }),
    ).resolves.toBeUndefined();
  });

  it("useMutation da tela: 'Resolver' com 204 chama o aoSucesso uma vez e não mostra erro", async () => {
    configurar204();
    const aoSucesso = vi.fn();
    const aoErro = vi.fn();
    const { result } = renderHook(() => useMutation(async (id: number) => {
      await apiReal(`/escolas/17/sync/alertas/${id}/resolver`, { method: "POST" });
    }, { aoSucesso, aoErro }));
    await act(async () => { await result.current.executar(1); });
    expect(aoSucesso).toHaveBeenCalledTimes(1);
    expect(aoErro).not.toHaveBeenCalled();
    expect(result.current.erro).toBeNull();
    expect(result.current.enviando).toBe(false);
  });
});
