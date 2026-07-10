import { expect, test } from "@playwright/test";

import { STORAGE } from "./helpers";

test.describe("Logout", () => {
  test.use({ storageState: STORAGE.admin });

  test("sair encerra a sessão e volta ao login", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByLabel("Selecionar escola")).toBeVisible();

    await page.getByLabel("Sair do sistema").click();
    await expect(page).toHaveURL(/\/login$/);
  });
});

test.describe("Proteção de rota", () => {
  // Sem sessão.
  test.use({ storageState: { cookies: [], origins: [] } });

  test("rota protegida sem sessão redireciona para o login", async ({ page }) => {
    await page.goto("/ranking");
    await expect(page).toHaveURL(/\/login$/);
  });
});
