import { expect, test } from "@playwright/test";

import { CONTAS, entrar } from "./helpers";

// A UI de login é o objeto de teste: começa SEM sessão.
test.use({ storageState: { cookies: [], origins: [] } });

test.describe("Login", () => {
  test("entra com credenciais válidas e chega ao painel", async ({ page }) => {
    await entrar(page, CONTAS.admin);
    await expect(page).not.toHaveURL(/\/login/);
    await expect(page.getByLabel("Selecionar escola")).toBeVisible();
  });

  test("mostra mensagem de erro com senha inválida", async ({ page }) => {
    await page.goto("/login");
    await page.getByLabel(/mail ou nome de usu/i).fill(CONTAS.admin.email);
    await page.getByLabel("Senha").fill("senha-totalmente-errada");
    await page.getByRole("button", { name: /entrar/i }).click();

    await expect(page.getByText(/incorretos|inv[aá]lid/i)).toBeVisible();
    // Continua na tela de login (não criou sessão).
    await expect(page.getByLabel("Selecionar escola")).toHaveCount(0);
  });
});
