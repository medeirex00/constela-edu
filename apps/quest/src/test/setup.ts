/**
 * Setup global dos testes de UI do Quest. jsdom não tem WebAudio nem
 * SpeechSynthesis — o módulo de áudio já trata `undefined` como "sem som",
 * então tocar()/narrar() viram no-op nos testes (nada a mockar).
 */
import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

afterEach(() => {
  cleanup();
});
