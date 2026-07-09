import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { VitePWA } from "vite-plugin-pwa";

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: "autoUpdate",
      includeAssets: ["favicon.svg"],
      // Mesma política do Edu: precache SÓ do app shell. Nada de /api no
      // Cache Storage — tablets de escola são compartilhados entre alunos.
      workbox: {
        globPatterns: ["**/*.{js,css,html,svg,png,woff,woff2}"],
        navigateFallback: "/index.html",
        navigateFallbackDenylist: [/^\/api/],
        cleanupOutdatedCaches: true,
      },
      manifest: false, // public/manifest.webmanifest versionado
    }),
  ],
  // Pacotes do workspace são fonte TypeScript — sem pré-bundle.
  optimizeDeps: {
    exclude: ["@constela/core", "@constela/quest-core"],
  },
  server: {
    // Porta própria (o Edu web usa 5173) e exposto na rede local para o
    // teste de corredor com tablets (critério de pronto da Fase Q0).
    port: 5174,
    host: true,
    fs: {
      deny: [".env", ".env.*", "**/*.db", "**/*.sqlite", "**/database/**"],
    },
    proxy: {
      "/api": "http://localhost:8000",
    },
  },
});
