/**
 * Projeto "setup": autentica cada papel UMA vez e salva o estado da sessão
 * (token no localStorage) em e2e/.auth/*.json. Os specs reaproveitam esse
 * estado via `test.use({ storageState })`, sem repetir o login a cada teste.
 */
import { test as setup } from "@playwright/test";

import { CONTAS, STORAGE, entrar } from "./helpers";

setup("autenticar admin", async ({ page }) => {
  await entrar(page, CONTAS.admin);
  await page.context().storageState({ path: STORAGE.admin });
});

setup("autenticar coordenador", async ({ page }) => {
  await entrar(page, CONTAS.coord);
  await page.context().storageState({ path: STORAGE.coord });
});

setup("autenticar professor", async ({ page }) => {
  await entrar(page, CONTAS.prof);
  await page.context().storageState({ path: STORAGE.prof });
});
