/**
 * O app mobile roda no Hermes (React Native), que NÃO tem `DOMException`
 * global — só navegador e Node têm. O fetch do React Native (whatwg-fetch) cria
 * um DOMException LOCAL para o abort. Este teste simula esse runtime: a falha
 * de rede tem de continuar virando ApiError(0) em pt-BR e o abort/timeout tem
 * de continuar propagando, sem ReferenceError.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, MENSAGEM_SEM_REDE, api } from "./cliente";

describe("cliente HTTP sem DOMException global (React Native/Hermes)", () => {
  const fetchOriginal = globalThis.fetch;
  const domExceptionOriginal = globalThis.DOMException;

  beforeEach(() => {
    Reflect.deleteProperty(globalThis, "DOMException");
  });
  afterEach(() => {
    globalThis.fetch = fetchOriginal;
    Object.defineProperty(globalThis, "DOMException", {
      value: domExceptionOriginal,
      configurable: true,
      writable: true,
    });
    vi.restoreAllMocks();
  });

  it("o ambiente simulado não tem DOMException global", () => {
    expect(typeof (globalThis as { DOMException?: unknown }).DOMException).toBe("undefined");
  });

  it("falha de rede vira ApiError(0) em pt-BR, não ReferenceError", async () => {
    globalThis.fetch = vi.fn(() =>
      Promise.reject(new TypeError("Network request failed")),
    ) as unknown as typeof fetch;

    const erro = (await api("/qualquer").catch((e) => e)) as ApiError;
    expect(erro).toBeInstanceOf(ApiError);
    expect(erro.status).toBe(0);
    expect(erro.message).toBe(MENSAGEM_SEM_REDE);
  });

  it.each(["AbortError", "TimeoutError"])("%s continua propagando para o chamador", async (nome) => {
    const abort = Object.assign(new Error("Aborted"), { name: nome });
    globalThis.fetch = vi.fn(() => Promise.reject(abort)) as unknown as typeof fetch;

    await expect(api("/qualquer")).rejects.toBe(abort);
  });
});
