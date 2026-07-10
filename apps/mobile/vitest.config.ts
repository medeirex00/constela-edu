/// <reference types="vitest" />
/**
 * Testes de LÓGICA PURA do app mobile (Vitest, ambiente Node).
 *
 * Não carregamos o React Native nem o runtime do Expo: os módulos nativos
 * (expo-crypto, expo-secure-store, AsyncStorage, NetInfo) são mockados nos
 * próprios testes. O que exercitamos é a lógica que mais importa offline e para
 * a LGPD — cifra AES-256 do cache, fila de escritas offline e a política de
 * retry — com o código REAL, sem depender de um emulador.
 */
import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "node",
    include: ["src/test/**/*.test.ts"],
    coverage: {
      provider: "v8",
      reportsDirectory: "./coverage",
      reporter: ["text", "text-summary", "html"],
      include: ["src/**/*.ts"],
      exclude: ["src/test/**", "src/**/*.d.ts"],
    },
  },
});
