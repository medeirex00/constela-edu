import os from "node:os";
import path from "node:path";

import { defineConfig, devices } from "@playwright/test";

/**
 * Varredura VISUAL do app web (identidade visual v2): sobe o mesmo ambiente do E2E
 * (backend FastAPI + SQLite semeado com a escola de demonstração FICTÍCIA + Vite) e
 * percorre as rotas de cada perfil em várias larguras, gravando capturas de tela e um
 * relatório JSON (erros de console, respostas /api com erro, rolagem horizontal).
 *
 * Não roda no CI: é uma ferramenta local de validação visual. Saída em VISUAL_OUT
 * (padrão: e2e-visual/saida, ignorada pelo git). Os dados exibidos são do seed de
 * teste — nunca dados reais de escola.
 *
 *   E2E_PYTHON=<python do venv> npx playwright test -c playwright.visual.config.ts
 */
const BACKEND_DIR = path.resolve(__dirname, "../../backend");
const PY = process.env.E2E_PYTHON || "python";
const BASE_URL = "http://localhost:5173";

const BACKEND_ENV = {
  ENV: "dev",
  DATABASE_URL: "sqlite:///./visual.db",
  SECRET_KEY: "visual-chave-de-teste-com-no-minimo-32-caracteres-0",
  ADMIN_INITIAL_PASSWORD: "AdminE2E@2026",
  COORD_PASSWORD: "CoordE2E@2026",
  PROF_PASSWORD: "ProfE2E@2026",
  DOCS_HABILITADOS: "false",
  AUTOMACAO_VERIFICAR_NO_BOOT: "false",
  // Uploads e exportações numa pasta TEMPORÁRIA, nunca nas do checkout: o expurgo de
  // fundo da API (core/expurgo_arquivos.py) roda no boot e aplica a retenção em
  // UPLOADS_DIR/temporarios e EXPORTS_DIR — sem DADOS_DIR, em dev, <repo>/exports, onde
  // ficam entregas guardadas à mão (REV2-OPS-1). A suíte do backend já faz o mesmo.
  DADOS_DIR: path.join(os.tmpdir(), "constela-e2e-visual-dados"),
};

export default defineConfig({
  testDir: "./e2e-visual",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 15 * 60_000,
  expect: { timeout: 10_000 },
  reporter: [["list"]],
  use: {
    baseURL: BASE_URL,
    ...devices["Desktop Chrome"],
    trace: "off",
    screenshot: "off",
    video: "off",
  },
  webServer: [
    {
      command: `${PY} scripts/seed_e2e.py && ${PY} -m uvicorn app.main:app --host 127.0.0.1 --port 8000`,
      cwd: BACKEND_DIR,
      env: BACKEND_ENV,
      url: "http://localhost:8000/api/health/live",
      // Nunca reaproveita um servidor já em pé: a varredura tem de ver ESTE código.
      reuseExistingServer: false,
      timeout: 180_000,
      stdout: "ignore",
      stderr: "pipe",
    },
    {
      command: "npm run dev -- --port 5173 --strictPort",
      url: BASE_URL,
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
});
