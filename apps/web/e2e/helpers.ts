/**
 * Utilitários compartilhados dos testes E2E: as contas semeadas por
 * `backend/scripts/seed_e2e.py`, os caminhos de storageState e um login por UI.
 */
import { expect, type Page } from "@playwright/test";

export interface Conta {
  email: string;
  senha: string;
  nome: string;
}

/** As três contas do seed E2E (senhas conhecidas — ambiente de teste). */
export const CONTAS: Record<"admin" | "coord" | "prof", Conta> = {
  admin: { email: "admin@constela.local", senha: process.env.ADMIN_INITIAL_PASSWORD || "AdminE2E@2026", nome: "Administrador" },
  coord: { email: "coord@constela.local", senha: process.env.COORD_PASSWORD || "CoordE2E@2026", nome: "Coordenadora E2E" },
  prof: { email: "prof@constela.local", senha: process.env.PROF_PASSWORD || "ProfE2E@2026", nome: "Professor E2E" },
};

/** Arquivos onde o projeto "setup" salva a sessão de cada papel. */
export const STORAGE = {
  admin: "e2e/.auth/admin.json",
  coord: "e2e/.auth/coord.json",
  prof: "e2e/.auth/prof.json",
} as const;

/** Login pela interface (usado no setup e no próprio teste de Login). */
export async function entrar(page: Page, conta: Conta): Promise<void> {
  await page.goto("/login");
  await page.getByLabel(/mail ou nome de usu/i).fill(conta.email);
  await page.getByLabel("Senha").fill(conta.senha);
  await page.getByRole("button", { name: /entrar/i }).click();
  // O seletor de escola do Dashboard só existe depois da sessão criada.
  await expect(page.getByLabel("Selecionar escola")).toBeVisible();
}
