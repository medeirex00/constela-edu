import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  // O pacote @constela/core é fonte TypeScript no workspace — sem pré-bundle.
  optimizeDeps: {
    exclude: ["@constela/core"],
  },
  server: {
    proxy: {
      // Em desenvolvimento, o frontend fala com a API sem configurar CORS
      "/api": "http://localhost:8000",
    },
  },
});
