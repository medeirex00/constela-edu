import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { VitePWA } from "vite-plugin-pwa";

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: "autoUpdate",
      includeAssets: ["favicon.png", "apple-touch-icon.png"],
      // Precache SÓ do app shell (build estático). Nada de cache de /api:
      // as respostas são autenticadas e multi-escola — não podem persistir
      // no Cache Storage de computadores compartilhados da escola.
      workbox: {
        globPatterns: ["**/*.{js,css,html,svg,png,woff,woff2}"],
        navigateFallback: "/index.html",
        navigateFallbackDenylist: [/^\/api/, /^\/p\//],
        cleanupOutdatedCaches: true,
      },
      manifest: false, // usamos o public/manifest.webmanifest versionado
    }),
  ],
  // O pacote @constela/core é fonte TypeScript no workspace — sem pré-bundle.
  optimizeDeps: {
    exclude: ["@constela/core"],
  },
  build: {
    rollupOptions: {
      output: {
        // Separa as dependências estáveis (react, router) num chunk "vendor"
        // de cache longo: elas quase nunca mudam, então um deploy que altera
        // uma tela não força o usuário a rebaixar o runtime inteiro. Combinado
        // com o code-splitting por rota (React.lazy), só o chunk da página
        // alterada muda entre deploys.
        manualChunks(id) {
          // Barra final em "react/" para NÃO capturar react-leaflet (mapa da
          // Secretaria) no vendor — ele deve ficar no chunk lazy da rota /rede,
          // carregando o Leaflet só quando a Secretaria abre.
          if (
            id.includes("node_modules/react/") ||
            id.includes("node_modules/react-dom/") ||
            id.includes("node_modules/react-router") ||
            id.includes("node_modules/scheduler")
          ) {
            return "vendor";
          }
          return undefined;
        },
      },
    },
  },
  server: {
    // Exposto na rede local para acesso pelo celular/tablet (docs/CELULAR.md)
    host: true,
    // Blindagem do dev server: nunca servir banco, .env ou segredos via /@fs/.
    fs: {
      deny: [".env", ".env.*", "**/*.db", "**/*.sqlite", "**/database/**"],
    },
    proxy: {
      // Em desenvolvimento, o frontend fala com a API sem configurar CORS
      "/api": "http://localhost:8000",
    },
  },
});
