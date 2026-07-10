import { expect, test } from "@playwright/test";

import { STORAGE } from "./helpers";

test.use({ storageState: STORAGE.admin });

test("o Ranking Geral lista alunos com nota já calculada no seed", async ({ page }) => {
  await page.goto("/ranking");

  await expect(page.getByRole("heading", { name: "Ranking Geral" })).toBeVisible();
  // O seed de demonstração calcula o ranking acumulado; alunos aparecem como
  // links para a ficha. "Ana Beatriz Souza" é o primeiro aluno do seed.
  await expect(page.getByRole("link", { name: "Ana Beatriz Souza" })).toBeVisible();
});
