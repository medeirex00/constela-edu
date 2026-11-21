import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { defineConfig, devices } from "@playwright/test";

/**
 * E2E da ANÁLISE EDUCACIONAL (/rede/analise e a análise na Visão da Escola) contra o
 * backend REAL — SEPARADO do playwright.config.ts de propósito:
 *
 *   1. backend: `scripts/seed_e2e_analise.py --servir 8010` APAGA e recria um SQLite
 *      descartável (só aceita caminho dentro da pasta de rascunho — ver o script), aplica
 *      as migrações do Alembic, semeia dados INVENTADOS (indicadores oficiais sintéticos +
 *      plataformas do ano corrente + 4 contas de teste) e sobe o uvicorn em 127.0.0.1:8010
 *      com `app.core.automacao.iniciar_verificacao` neutralizado e a saída de rede
 *      limitada ao loopback;
 *   2. web: Vite em 127.0.0.1:5175 (`--strictPort`) com VITE_API_URL apontando para a
 *      8010 (o proxy do vite.config.ts vai para a 8000 e não é usado aqui); o backend
 *      libera essa origem por CORS_ORIGINS;
 *   3. nunca reaproveita servidor (`reuseExistingServer: false`): porta ocupada = falha
 *      explícita, em vez de testar outro banco/código; 1 worker (um banco só).
 *
 * Rodar (em apps/web):
 *   E2E_PYTHON="<python da venv do backend>" npx playwright test -c playwright.analise.config.ts
 * Sem E2E_PYTHON, usa backend/.venv deste checkout (se existir) ou o `python` do PATH.
 * Senhas: só de TESTE, sobrescrevíveis por E2E_ANALISE_SENHA_{GLOBAL,SECRETARIA,COORD,PROF}.
 */
const PORTA_API = 8010;
const PORTA_WEB = 5175;
const BASE_URL = `http://127.0.0.1:${PORTA_WEB}`;
const API_URL = `http://127.0.0.1:${PORTA_API}`;
const BACKEND_DIR = path.resolve(__dirname, "../../backend");

// Pasta do banco descartável: a ÚNICA que o seed aceita apagar (E2E_ANALISE_PASTA, que
// vai para o backend). Sem a variável, uma pasta própria no temporário do sistema.
const PASTA_DADOS = process.env.E2E_ANALISE_PASTA || path.join(os.tmpdir(), "constela-e2e-analise");
fs.mkdirSync(PASTA_DADOS, { recursive: true });
const BANCO = `sqlite:///${PASTA_DADOS.replace(/\\/g, "/")}/e2e_analise.db`;

function python(): string {
  if (process.env.E2E_PYTHON) return process.env.E2E_PYTHON;
  for (const rel of [".venv/Scripts/python.exe", ".venv/bin/python"]) {
    const candidato = path.join(BACKEND_DIR, rel);
    if (fs.existsSync(candidato)) return candidato;
  }
  return "python";
}

// Senhas de TESTE (nunca de produção). Ficam no process.env para o spec ler as mesmas
// (o config é avaliado também nos workers) e para o seed recebê-las pelo ambiente.
const SENHAS_PADRAO: Record<string, string> = {
  E2E_ANALISE_SENHA_GLOBAL: "GlobalAnalise@2026",
  E2E_ANALISE_SENHA_SECRETARIA: "SecretariaAnalise@2026",
  E2E_ANALISE_SENHA_COORD: "CoordAnalise@2026",
  E2E_ANALISE_SENHA_PROF: "ProfAnalise@2026",
};
for (const [chave, valor] of Object.entries(SENHAS_PADRAO)) {
  if (!process.env[chave]) process.env[chave] = valor;
}
process.env.E2E_ANALISE_API_URL = API_URL;

const BACKEND_ENV: Record<string, string> = {
  ENV: "dev",
  DATABASE_URL: BANCO,
  SECRET_KEY: "e2e-analise-chave-de-teste-com-no-minimo-32-caracteres",
  DOCS_HABILITADOS: "false",
  CORS_ORIGINS: JSON.stringify([BASE_URL]),
  // SEM PUBLIC_BASE_URL, como a demo e o ambiente de teste: o padrão do código é o domínio
  // de produção, e o vitrine.spec.ts confere que mesmo assim o link aberto pela tela é desta
  // origem (o servidor usa a origem de loopback que a tela informa).
  SYNC_SCHEDULER_ENABLED: "false",
  // O --servir já neutraliza o diagnóstico do robô no processo; a variável garante o
  // mesmo se o seed mudar (sem geo-IP nem Chromium no boot, sem internet do runner).
  AUTOMACAO_VERIFICAR_NO_BOOT: "false",
  PYTHONIOENCODING: "utf-8",
  E2E_ANALISE_PASTA: PASTA_DADOS,
  // Uploads e exportações numa pasta TEMPORÁRIA, nunca nas do checkout: o expurgo de
  // fundo da API (core/expurgo_arquivos.py) roda no boot e aplica a retenção em
  // UPLOADS_DIR/temporarios e EXPORTS_DIR — sem DADOS_DIR, em dev, <repo>/exports, onde
  // ficam entregas guardadas à mão (REV2-OPS-1). A suíte do backend já faz o mesmo.
  DADOS_DIR: path.join(os.tmpdir(), "constela-e2e-analise-dados"),
  ...Object.fromEntries(Object.keys(SENHAS_PADRAO).map((k) => [k, process.env[k] as string])),
};

export default defineConfig({
  testDir: "./e2e-analise",
  outputDir: "./test-results/analise",
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: 0,
  timeout: 120_000,
  expect: { timeout: 15_000 },
  reporter: [["list"]],
  use: {
    baseURL: BASE_URL,
    serviceWorkers: "block",
    locale: "pt-BR",
    timezoneId: "America/Sao_Paulo",
    colorScheme: "light",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1366, height: 768 } } }],
  webServer: [
    {
      command: `"${python()}" scripts/seed_e2e_analise.py --servir ${PORTA_API}`,
      cwd: BACKEND_DIR,
      env: BACKEND_ENV,
      url: `${API_URL}/api/health/live`,
      reuseExistingServer: false,
      timeout: 180_000,
      stdout: "pipe",
      stderr: "pipe",
    },
    {
      command: `npm run dev -- --host 127.0.0.1 --port ${PORTA_WEB} --strictPort`,
      env: { VITE_API_URL: `${API_URL}/api/v1` },
      url: BASE_URL,
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
});
