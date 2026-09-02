/// <reference types="vitest" />
/**
 * Testes de UI do Quest (Vitest + Testing Library) — primeiro harness de teste
 * do app dos alunos. Separado do vite.config.ts: os testes não carregam o
 * plugin de PWA (service worker), só o plugin React e o ambiente jsdom.
 */
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/test/**/*.test.{ts,tsx}"],
    css: false,
  },
});
