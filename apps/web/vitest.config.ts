/// <reference types="vitest" />
/**
 * Configuração dos testes de UI (Vitest + Testing Library).
 *
 * Deliberadamente SEPARADA do vite.config.ts: os testes não carregam o plugin
 * de PWA (service worker / módulo virtual `virtual:pwa-register`), que só faz
 * sentido no build real. Aqui usamos apenas o plugin React (JSX + Fast Refresh
 * desligado) e o ambiente jsdom.
 */
import path from "node:path";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  resolve: {
    // Atalho "@/..." para src, usado pelos utilitários de teste.
    alias: { "@": path.resolve(__dirname, "src") },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/test/**/*.test.{ts,tsx}"],
    // O CSS (Tailwind) não influencia o comportamento; ignorá-lo acelera e evita
    // ruído de PostCSS nos testes.
    css: false,
    // NÃO usar restoreMocks/mockReset globais: apagariam a implementação dos
    // nossos vi.fn (api, loginRequest...). A limpeza é feita por resetApiMock
    // (só mockClear) no afterEach do setup.
    coverage: {
      provider: "v8",
      reportsDirectory: "./coverage",
      reporter: ["text", "text-summary", "html"],
      include: ["src/**/*.{ts,tsx}"],
      exclude: [
        "src/test/**",
        "src/lib/__mocks__/**",
        "src/**/*.d.ts",
        "src/main.tsx",
        "src/vite-env.d.ts",
      ],
    },
  },
});
