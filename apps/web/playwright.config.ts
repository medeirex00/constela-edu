import path from "node:path";

import { defineConfig, devices } from "@playwright/test";

/**
 * Testes End-to-End do app web contra o sistema REAL (frontend Vite + backend
 * FastAPI + SQLite semeado). O Playwright sobe os dois servidores (`webServer`)
 * e roda os cenários num navegador de verdade.
 *
 * Fluxo:
 *   1. Backend: `seed_e2e.py` reseta e popula um SQLite de teste com contas de
 *      senha conhecida (admin/coord/prof) + dados de demonstração; depois sobe
 *      o uvicorn na 8000.
 *   2. Frontend: `vite dev` na 5173 (o proxy /api aponta para a 8000).
 *   3. O projeto "setup" faz login das 3 contas e salva o estado de sessão;
 *      os specs reaproveitam esse estado (rápido e sem repetir login).
 */
const BACKEND_DIR = path.resolve(__dirname, "../../backend");
const PY = process.env.E2E_PYTHON || "python";
const BASE_URL = process.env.E2E_BASE_URL || "http://localhost:5173";

// Ambiente do backend de teste. Senhas fixas: são de teste, nunca de produção.
const BACKEND_ENV = {
  ENV: "dev",
  DATABASE_URL: "sqlite:///./e2e.db",
  SECRET_KEY: "e2e-chave-de-teste-com-no-minimo-32-caracteres-000",
  ADMIN_INITIAL_PASSWORD: process.env.ADMIN_INITIAL_PASSWORD || "AdminE2E@2026",
  COORD_PASSWORD: process.env.COORD_PASSWORD || "CoordE2E@2026",
  PROF_PASSWORD: process.env.PROF_PASSWORD || "ProfE2E@2026",
  DOCS_HABILITADOS: "false",
};

export default defineConfig({
  testDir: "./e2e",
  // Um único banco compartilhado -> execução serial evita interferência entre
  // cenários que gravam (cadastro, CRUD). Cada teste usa nomes únicos mesmo assim.
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  timeout: 30_000,
  expect: { timeout: 10_000 },
  reporter: process.env.CI
    ? [["list"], ["html", { open: "never" }]]
    : [["list"]],
  use: {
    baseURL: BASE_URL,
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    // 1) autentica as 3 contas e salva o storageState de cada uma.
    { name: "setup", testMatch: /auth\.setup\.ts/ },
    // 2) roda os cenários (dependem do setup).
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
      dependencies: ["setup"],
    },
  ],
  webServer: [
    {
      // Semeia o banco e sobe a API. Em CI sempre do zero; localmente reaproveita
      // um backend já em pé (comece o seu com o mesmo DATABASE_URL para reusar).
      command: `${PY} scripts/seed_e2e.py && ${PY} -m uvicorn app.main:app --host 127.0.0.1 --port 8000`,
      cwd: BACKEND_DIR,
      env: BACKEND_ENV,
      url: "http://localhost:8000/api/health/live",
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      stdout: "pipe",
      stderr: "pipe",
    },
    {
      command: "npm run dev -- --port 5173 --strictPort",
      url: BASE_URL,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
  ],
});
