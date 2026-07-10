import { expect, test } from "@playwright/test";

import { STORAGE } from "./helpers";

test.describe("Permissões — professor (acesso restrito)", () => {
  test.use({ storageState: STORAGE.prof });

  test("não vê a ação de criar usuários", async ({ page }) => {
    await page.goto("/usuarios");
    // A tela carrega, mas a ação administrativa não existe para o professor.
    await expect(page.getByRole("button", { name: /novo usuário/i })).toHaveCount(0);
  });

  test("é bloqueado na gestão de escolas (só admin global)", async ({ page }) => {
    await page.goto("/escolas");
    await expect(page.getByText("Somente o administrador global")).toBeVisible();
  });
});

test.describe("Permissões — admin global (acesso total)", () => {
  test.use({ storageState: STORAGE.admin });

  test("vê a ação de criar usuários", async ({ page }) => {
    await page.goto("/usuarios");
    await expect(page.getByRole("button", { name: /novo usuário/i })).toBeVisible();
  });

  test("acessa a gestão de escolas", async ({ page }) => {
    await page.goto("/escolas");
    await expect(page.getByText("Somente o administrador global")).toHaveCount(0);
  });
});
