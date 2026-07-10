/**
 * Setup global dos testes de UI. Roda antes de cada arquivo de teste.
 *
 *   1. Mata a rede: `vi.mock("@/lib/api")` faz TODO import de `../lib/api`
 *      (telas, hooks, contexto) usar o mock manual de src/lib/__mocks__/api.ts.
 *   2. Matchers do jest-dom (toBeInTheDocument, toHaveTextContent...).
 *   3. Preenche o que o jsdom não implementa e que o app usa (matchMedia etc.).
 *   4. Limpa estado entre testes (DOM, localStorage, handlers, cache).
 */
import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

import { limparCacheApi } from "@/hooks/useApi";
import { resetApiMock } from "@/lib/__mocks__/api";

// (1) Mock global do cliente de API — vale para todos os arquivos de teste.
vi.mock("@/lib/api");

// (3) jsdom não tem matchMedia; o AppContext usa para o tema inicial.
if (!window.matchMedia) {
  window.matchMedia = (query: string) =>
    ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => undefined, // APIs antigas (compat)
      removeListener: () => undefined,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      dispatchEvent: () => false,
    }) as unknown as MediaQueryList;
}

// Observers e utilidades de layout ausentes no jsdom (gráficos, drawers, foco).
class ObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
  takeRecords() {
    return [];
  }
}
(globalThis as unknown as { ResizeObserver: unknown }).ResizeObserver = ObserverStub;
(globalThis as unknown as { IntersectionObserver: unknown }).IntersectionObserver = ObserverStub;
if (!window.scrollTo) window.scrollTo = () => undefined;
if (!Element.prototype.scrollIntoView) Element.prototype.scrollIntoView = () => undefined;

// (4) Isolamento entre testes.
afterEach(() => {
  cleanup();
  resetApiMock();
  limparCacheApi();
  localStorage.clear();
});
