import { defineConfig, devices } from "@playwright/test";

/**
 * E2E de RESPONSIVIDADE das telas públicas (vitrine da rede /rede/p/:token e
 * telão da escola /p/:token) — SEPARADO do playwright.config.ts de propósito:
 *
 *   - sobe SÓ o Vite (porta 5174, `--strictPort`): sem backend, sem seed, sem
 *     login. A API pública é simulada com `page.route` e payload INVENTADO
 *     (e2e-publico/dados.ts) — nenhum número ou nome real;
 *   - `serviceWorkers: "block"`: o service worker do PWA não fura o page.route;
 *   - `reducedMotion: "reduce"` por padrão (um bloco do spec liga o movimento
 *     para conferir as animações e a barra relativa);
 *   - as fontes self-host (@fontsource) são servidas pelo próprio teste quando
 *     o Vite as recusa (node_modules fora da raiz, ex.: worktree com junção) —
 *     sem Poppins/Inter as medidas de largura não valeriam.
 *
 * Rodar (em apps/web): npx playwright test -c playwright.publico.config.ts
 * Capturas para revisão visual: test-results/capturas-publico/ (ou a pasta em
 * CAPTURAS_PUBLICO). Nada disso vai para o repositório (.gitignore).
 */
const PORTA = 5174;
const BASE_URL = `http://localhost:${PORTA}`;

export default defineConfig({
  testDir: "./e2e-publico",
  outputDir: "./test-results/publico",
  fullyParallel: true,
  workers: process.env.CI ? 2 : 4,
  forbidOnly: !!process.env.CI,
  retries: 0,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : [["list"]],
  use: {
    baseURL: BASE_URL,
    serviceWorkers: "block",
    // reducedMotion é opção de CONTEXTO (não há atalho em `use`).
    contextOptions: { reducedMotion: "reduce" },
    colorScheme: "dark",
    locale: "pt-BR",
    timezoneId: "America/Sao_Paulo",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: `npm run dev -- --port ${PORTA} --strictPort`,
    url: BASE_URL,
    // Nunca reaproveita: outro servidor na 5174 (de outro worktree) testaria o
    // código errado. Com --strictPort, porta ocupada = falha explícita.
    reuseExistingServer: false,
    timeout: 120_000,
  },
});
