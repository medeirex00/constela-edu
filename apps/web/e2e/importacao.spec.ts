import { expect, test } from "@playwright/test";

import { STORAGE } from "./helpers";

// Importação: valida a central de importações contra o backend REAL — histórico
// semeado e o formulário de análise disponíveis. (Um parse+confirmação completo
// exigiria um arquivo de relatório; aqui garantimos o carregamento fim-a-fim.)
test.use({ storageState: STORAGE.admin });

test("a central de importações mostra o histórico semeado e o formulário", async ({ page }) => {
  await page.goto("/importacoes");

  await expect(page.getByRole("heading", { name: "Histórico" })).toBeVisible();
  // O seed criou importações (matific/elefante), então NÃO é o estado vazio.
  await expect(page.getByText("Nenhuma importação ainda")).toHaveCount(0);
  // O formulário de análise (importação individual) está disponível ao gestor.
  await expect(page.getByRole("button", { name: /analisar e ver prévia/i })).toBeVisible();
});
