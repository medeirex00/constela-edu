import { expect, test } from "@playwright/test";

import { STORAGE } from "./helpers";

// CRUD completo numa entidade limpa: cria uma turma NOVA (sem alunos, então a
// exclusão é permitida), renomeia e exclui. Nomes únicos por execução.
test.use({ storageState: STORAGE.admin });

test("cria, edita e exclui uma turma (ciclo completo)", async ({ page }) => {
  const id = Date.now();
  const nome = `Turma E2E ${id}`;
  const nomeEditado = `Turma E2E ${id} (editada)`;

  await page.goto("/turmas");

  // CREATE ---------------------------------------------------------------
  await page.getByRole("button", { name: /adicionar turma/i }).click();
  await page.getByLabel(/Nome da turma/i).fill(nome);
  await page.getByLabel(/Série \/ Ano escolar/i).fill("9º Ano");
  await page.getByLabel(/^Turno/i).selectOption("manha");
  await page.getByRole("button", { name: /criar turma/i }).click();
  await expect(page.getByText(nome, { exact: true })).toBeVisible();

  // UPDATE ---------------------------------------------------------------
  await page.getByRole("button", { name: `Editar turma ${nome}` }).click();
  await page.getByLabel(/Nome da turma/i).fill(nomeEditado);
  await page.getByRole("button", { name: /salvar alterações/i }).click();
  await expect(page.getByText(nomeEditado, { exact: true })).toBeVisible();

  // DELETE ---------------------------------------------------------------
  await page.getByRole("button", { name: `Excluir turma ${nomeEditado}` }).click();
  await page.getByRole("button", { name: /sim, excluir/i }).click();
  await expect(page.getByText(nomeEditado, { exact: true })).toHaveCount(0);
});
