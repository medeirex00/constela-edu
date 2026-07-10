import { expect, test } from "@playwright/test";

import { STORAGE } from "./helpers";

// Cadastro de novo usuário: só o admin/global cria (por isso a sessão de admin).
test.use({ storageState: STORAGE.admin });

test("admin cadastra um novo professor e ele aparece na lista", async ({ page }) => {
  const id = Date.now();
  const nome = `Prof Cadastro ${id}`;
  const email = `novo.prof.${id}@escola.com`;

  await page.goto("/usuarios");
  await page.getByRole("button", { name: /novo usuário/i }).click();

  // Rótulos exatos: "Nome"/"E-mail" senão casam com "Nome de usuário
  // (opcional — ... no lugar do e-mail)".
  await page.getByLabel("Nome", { exact: true }).fill(nome);
  await page.getByLabel("E-mail", { exact: true }).fill(email);
  await page.getByLabel(/^Senha/).fill("NovoProf@2026");
  // "Cargo" já vem como professor por padrão.

  await page.getByRole("button", { name: /criar usuário/i }).click();

  // O novo usuário passa a constar na listagem (recarregada após o POST).
  await expect(page.getByText(nome)).toBeVisible();
});
