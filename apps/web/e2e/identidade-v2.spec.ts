/**
 * Fluxos da identidade visual v2 contra o sistema REAL (backend + SQLite do seed E2E):
 * indicadores e gráfico da Visão geral vindos da API, exportação CSV e lote de
 * certificados no Ranking (PDF de verdade), Critérios sem controles de peso para a
 * escola, teclado nos diálogos e as correções de layout (Relatórios no tablet deitado,
 * h1 nas telas da rede).
 */
import fs from "node:fs";

import { expect, test } from "@playwright/test";

import { STORAGE } from "./helpers";

test.describe("coordenação", () => {
  test.use({ storageState: STORAGE.coord });

  test("Visão geral mostra os indicadores do bimestre e o gráfico semanal com dado da API", async ({ page }) => {
    const visao = page.waitForResponse((r) => r.url().includes("/visao-geral") && r.status() === 200);
    const semanal = page.waitForResponse((r) => r.url().includes("/atividade-semanal") && r.status() === 200);
    await page.goto("/");
    await Promise.all([visao, semanal]);
    await expect(page.getByRole("heading", { level: 1 })).toContainText("Olá");
    for (const rotulo of ["Alunos ativos", "Livros lidos no bimestre", "Horas de leitura", "Atividades no Matific"]) {
      await expect(page.getByText(rotulo, { exact: true }).first()).toBeVisible();
    }
    await expect(page.getByText("Alunos ativos por semana", { exact: true })).toBeVisible();
    await expect(page.getByText("Desempenho por turma", { exact: true })).toBeVisible();
  });

  test("Ranking: Exportar lista (CSV) baixa a lista exibida", async ({ page }) => {
    await page.goto("/ranking");
    await expect(page.getByRole("heading", { name: "Ranking Geral", level: 1 })).toBeVisible();
    await expect(page.getByRole("link", { name: "Ana Beatriz Souza" })).toBeVisible();
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.getByRole("button", { name: "Exportar lista (CSV)" }).click(),
    ]);
    expect(download.suggestedFilename()).toMatch(/\.csv$/);
    const conteudo = fs.readFileSync(await download.path(), "utf-8");
    expect(conteudo).toContain("Ana Beatriz Souza");
    expect(conteudo.split(/\r?\n/).filter(Boolean).length).toBeGreaterThan(3);
  });

  test("Gerar certificados em lote: verifica os alunos, mostra a recusa com motivo e baixa um PDF só", async ({ page }) => {
    test.setTimeout(120_000);
    await page.goto("/ranking");
    await expect(page.getByRole("link", { name: "Ana Beatriz Souza" })).toBeVisible();
    await page.getByRole("button", { name: "Gerar certificados" }).click();
    const dialogo = page.getByRole("dialog", { name: "Gerar certificados" });
    await expect(dialogo).toBeVisible();
    await dialogo.getByRole("button", { name: "Verificar" }).click();
    await expect(dialogo.getByText("Verificação:")).toBeVisible({ timeout: 30_000 });
    // O seed deixa o 1º colocado fora da Lista Piloto: ele é recusado com o motivo e
    // NÃO é trocado pelo 4º (o lote continua com 3 nomes).
    await expect(dialogo.getByText("2 aptos", { exact: true }).first()).toBeVisible();
    await expect(dialogo.getByText("1 não emitido", { exact: true }).first()).toBeVisible();
    await expect(dialogo.getByText(/Lista Piloto/).first()).toBeVisible();
    const gerar = dialogo.getByRole("button", { name: "Gerar PDF (2 aptos)" });
    await expect(gerar).toBeEnabled();
    const [download] = await Promise.all([page.waitForEvent("download", { timeout: 90_000 }), gerar.click()]);
    expect(download.suggestedFilename()).toMatch(/\.pdf$/);
    expect(fs.readFileSync(await download.path()).subarray(0, 4).toString("latin1")).toBe("%PDF");
    await expect(dialogo.getByText("PDF com 2 certificados baixado")).toBeVisible();
  });

  test("teclado: o diálogo de certificados abre com Enter, Esc fecha e o foco volta ao botão", async ({ page }) => {
    await page.goto("/ranking");
    await expect(page.getByRole("link", { name: "Ana Beatriz Souza" })).toBeVisible();
    const botao = page.getByRole("button", { name: "Gerar certificados" });
    await expect(botao).toBeEnabled();
    await botao.focus();
    await page.keyboard.press("Enter");
    const dialogo = page.getByRole("dialog", { name: "Gerar certificados" });
    await expect(dialogo).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(dialogo).toBeHidden();
    await expect(botao).toBeFocused();
  });

  test("Critérios: a escola vê a Régua Padrão Constela sem controles de peso", async ({ page }) => {
    await page.goto("/metricas");
    await expect(page.getByRole("heading", { level: 1 })).toContainText("Critérios");
    // Espera a régua carregada (os pesos vêm da API) antes de afirmar a ausência.
    await expect(page.getByRole("heading", { name: "Como a pontuação é calculada" })).toBeVisible();
    await expect(page.getByText("Régua Padrão Constela — a mesma para toda a rede")).toBeVisible();
    await expect(page.getByRole("slider")).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Salvar pesos" })).toHaveCount(0);
  });

  test("Relatórios no tablet deitado (1024×768) sem rolagem horizontal", async ({ page }) => {
    await page.setViewportSize({ width: 1024, height: 768 });
    await page.goto("/relatorios");
    await expect(page.getByRole("heading", { name: "Relatórios", level: 1 })).toBeVisible();
    const sobra = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(sobra).toBeLessThanOrEqual(0);
  });
});

test.describe("Admin Global", () => {
  test.use({ storageState: STORAGE.admin });

  test("Critérios: só o Admin Global vê os editores de peso", async ({ page }) => {
    await page.goto("/metricas");
    await expect(page.getByRole("button", { name: "Salvar pesos" }).first()).toBeVisible();
  });

  // As três áreas da Secretaria (que o global abre pela Visão da rede) e as demais telas da rede.
  for (const rota of ["/rede", "/rede/avaliacoes", "/rede/analise", "/rede/ranking", "/rede/visao",
                      "/rede/escolas", "/rede/avaliacoes-externas", "/rede/acompanhamento", "/rede/plataformas",
                      "/rede/relatorios"]) {
    test(`${rota} tem um título principal (h1)`, async ({ page }) => {
      await page.goto(rota);
      await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    });
  }

  // A ficha de uma escola (/rede/escolas/:id) e a comparação (?comparar=), com ids REAIS da API:
  // um h1 só (o nome da escola; sem rede, ou com a escola fora dela, a mensagem tem o seu h1).
  test("/rede/escolas/:id e /rede/escolas?comparar= têm um título principal (h1)", async ({ page }) => {
    await page.goto("/");
    const token = await page.evaluate(() => localStorage.getItem("sgpe_token"));
    const r = await page.request.get("http://localhost:8000/api/v1/escolas", { headers: { Authorization: `Bearer ${token}` } });
    expect(r.ok()).toBe(true);
    const ids = ((await r.json()) as { id: number }[]).map((e) => e.id);
    expect(ids.length).toBeGreaterThan(0);
    for (const rota of [`/rede/escolas/${ids[0]}`, `/rede/escolas?comparar=${ids.slice(0, 2).join(",")}`]) {
      await page.goto(rota);
      await expect(page.getByRole("heading", { level: 1 }), rota).toHaveCount(1);
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    }
  });
});

test.describe("professor", () => {
  test.use({ storageState: STORAGE.prof });

  test("Visão geral do professor: gráfico semanal sem o bloco de turmas (o backend nega)", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByText("Alunos ativos por semana", { exact: true })).toBeVisible();
    await expect(page.getByText("Desempenho por turma", { exact: true })).toHaveCount(0);
  });
});
