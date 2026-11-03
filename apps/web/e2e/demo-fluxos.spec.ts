/**
 * Fluxos da demonstração (prefeitura de Jacareí, 04/11/2026) contra o sistema REAL
 * (backend + SQLite do seed E2E, dados FICTÍCIOS): navegação, pesquisa, filtros,
 * rankings, relatórios e exportações, certificados, Elefante e Matific, permissões
 * do professor e navegação no celular. Cada fluxo confere também que a tela não
 * mostrou erro ("Não foi possível...") nem resposta de erro da API.
 */
import fs from "node:fs";

import { expect, test, type Page } from "@playwright/test";

import { STORAGE } from "./helpers";

/** Falha o teste se a tela registrar resposta /api >= 400 ou erro de página. */
function vigiarErros(page: Page): string[] {
  const erros: string[] = [];
  page.on("response", (r) => {
    if (r.url().includes("/api/") && r.status() >= 400) erros.push(`${r.status()} ${new URL(r.url()).pathname}`);
  });
  page.on("pageerror", (e) => erros.push(`pageerror: ${e.message}`));
  return erros;
}

async function semErroNaTela(page: Page): Promise<void> {
  await expect(page.getByText(/Não foi possível/).first()).toHaveCount(0);
}

async function baixar(page: Page, nome: string | RegExp): Promise<{ arquivo: string; bytes: Buffer }> {
  const [download] = await Promise.all([
    page.waitForEvent("download", { timeout: 60_000 }),
    // Nome EXATO: "Geral" (o certificado) também casaria com "Baixar Ranking Geral em PDF".
    page.getByRole("button", { name: nome, exact: typeof nome === "string" }).click(),
  ]);
  return { arquivo: download.suggestedFilename(), bytes: fs.readFileSync(await download.path()) };
}

test.describe("coordenação: pessoas, rankings, relatórios e plataformas", () => {
  test.use({ storageState: STORAGE.coord });

  test("Alunos: a pesquisa e o filtro de turma recortam a lista; o perfil abre com as abas", async ({ page }) => {
    const erros = vigiarErros(page);
    await page.goto("/alunos");
    await expect(page.getByRole("link", { name: "Ana Beatriz Souza" })).toBeVisible();
    await page.getByPlaceholder("Pesquisar por nome...").fill("Camila");
    await expect(page.getByRole("link", { name: "Camila Ferreira Dias" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Ana Beatriz Souza" })).toHaveCount(0);
    await page.getByPlaceholder("Pesquisar por nome...").fill("");
    await page.getByLabel("Filtrar por turma").selectOption({ label: "2º Ano A" });
    await expect(page.getByRole("link", { name: "Ana Beatriz Souza" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Camila Ferreira Dias" })).toHaveCount(0);

    await page.getByRole("link", { name: "Ana Beatriz Souza" }).click();
    await expect(page.getByRole("heading", { level: 1 })).toContainText("Ana Beatriz Souza");
    for (const aba of ["Linha do tempo", "Histórico de Leituras", "Evolução", "Perfil"]) {
      await page.getByRole("tab", { name: aba }).click();
      await expect(page.getByRole("tab", { name: aba })).toHaveAttribute("aria-selected", "true");
      await semErroNaTela(page);
    }
    expect(erros).toEqual([]);
  });

  test("Turmas → detalhe da turma com os alunos dela", async ({ page }) => {
    const erros = vigiarErros(page);
    await page.goto("/turmas");
    await page.getByRole("link", { name: "2º Ano A" }).first().click();
    await expect(page.getByRole("heading", { level: 1 })).toContainText("2º Ano A");
    await expect(page.getByRole("link", { name: "Ana Beatriz Souza" })).toBeVisible();
    await semErroNaTela(page);
    expect(erros).toEqual([]);
  });

  test("Ranking: as cinco visões carregam sem erro e o filtro de turma recorta a lista", async ({ page }) => {
    const erros = vigiarErros(page);
    for (const ver of ["", "?ver=leitura", "?ver=matematica", "?ver=evolucao", "?ver=turmas"]) {
      await page.goto(`/ranking${ver}`);
      await page.waitForLoadState("networkidle");
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      await semErroNaTela(page);
    }
    await page.goto("/ranking");
    await expect(page.getByRole("link", { name: "Camila Ferreira Dias" })).toBeVisible();
    await page.getByRole("combobox", { name: /turma/i }).first().selectOption({ label: "2º Ano A" });
    await expect(page.getByRole("link", { name: "Ana Beatriz Souza" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Camila Ferreira Dias" })).toHaveCount(0);
    expect(erros).toEqual([]);
  });

  test("Premiações: categorias com pódio e certificados do pódio abrem o lote", async ({ page }) => {
    const erros = vigiarErros(page);
    await page.goto("/premiacoes");
    await expect(page.getByRole("heading", { level: 1 })).toContainText("Premiações");
    await page.getByRole("button", { name: /Certificados do pódio/ }).first().click();
    await expect(page.getByRole("dialog", { name: "Gerar certificados" })).toBeVisible();
    await page.keyboard.press("Escape");
    await semErroNaTela(page);
    expect(erros).toEqual([]);
  });

  test("Relatórios: exportações em PDF, Excel e CSV e o certificado individual baixam arquivos válidos", async ({ page }) => {
    test.setTimeout(120_000);
    const erros = vigiarErros(page);
    await page.goto("/relatorios");
    const pdf = await baixar(page, "Baixar Ranking Geral em PDF");
    expect(pdf.arquivo).toMatch(/\.pdf$/);
    expect(pdf.bytes.subarray(0, 4).toString("latin1")).toBe("%PDF");
    const xlsx = await baixar(page, "Baixar Lista de Alunos em Excel");
    expect(xlsx.arquivo).toMatch(/\.xlsx$/);
    expect(xlsx.bytes.subarray(0, 2).toString("latin1")).toBe("PK");
    const csv = await baixar(page, "Baixar Catálogo de Livros em CSV");
    expect(csv.arquivo).toMatch(/\.csv$/);
    expect(csv.bytes.length).toBeGreaterThan(20);

    // Certificado individual: escolhe o aluno e baixa o modelo Geral.
    await page.getByRole("combobox", { name: "Aluno", exact: true }).selectOption({ label: "Ana Beatriz Souza" });
    const cert = await baixar(page, "Geral");
    expect(cert.bytes.subarray(0, 4).toString("latin1")).toBe("%PDF");
    expect(erros).toEqual([]);
  });

  test("Relatório por Período abre com o recorte e sem erro", async ({ page }) => {
    const erros = vigiarErros(page);
    await page.goto("/relatorios/periodo");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await page.waitForLoadState("networkidle");
    await semErroNaTela(page);
    expect(erros).toEqual([]);
  });

  test("Elefante Letrado e Matific: lista com a data do dado e busca pelo nome", async ({ page }) => {
    const erros = vigiarErros(page);
    for (const rota of ["/elefante", "/matific"]) {
      await page.goto(rota);
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      const busca = page.getByLabel("Buscar aluno pelo nome");
      await expect(busca).toBeVisible();
      await busca.fill("Ana Beatriz");
      await expect(page.getByText("Ana Beatriz Souza").first()).toBeVisible();
      await expect(page.getByText("Camila Ferreira Dias")).toHaveCount(0);
      await semErroNaTela(page);
    }
    expect(erros).toEqual([]);
  });

  test("Integrações: sem conexão configurada a tela diz isso (não finge sincronização)", async ({ page }) => {
    const erros = vigiarErros(page);
    await page.goto("/sincronizacao");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(page.getByText(/Configure e valide a conexão/).first()).toBeVisible();
    expect(erros).toEqual([]);
  });

  test("Visão da Escola, Insights, Importações e Critérios abrem sem erro", async ({ page }) => {
    const erros = vigiarErros(page);
    for (const rota of ["/escola", "/insights", "/importacoes", "/metricas", "/conquistas", "/configuracoes/conquistas"]) {
      await page.goto(rota);
      await page.waitForLoadState("networkidle");
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      await semErroNaTela(page);
    }
    expect(erros).toEqual([]);
  });

  test("Pesquisa global (Ctrl+K) leva à página escolhida", async ({ page }) => {
    await page.goto("/");
    await page.keyboard.press("Control+k");
    await page.getByLabel(/Pesquisar páginas, alunos, turmas/).fill("Premia");
    await page.getByRole("button", { name: /Premiações/ }).first().click();
    await expect(page).toHaveURL(/\/premiacoes$/);
  });
});

test.describe("professor: só as turmas dele", () => {
  test.use({ storageState: STORAGE.prof });

  test("vê os alunos das turmas dele e não os de outra turma; gestão fica fora", async ({ page }) => {
    const erros = vigiarErros(page);
    await page.goto("/alunos");
    await expect(page.getByRole("link", { name: "Ana Beatriz Souza" })).toBeVisible();
    // 5º Ano A é do outro professor do seed.
    await expect(page.getByRole("link", { name: "Camila Ferreira Dias" })).toHaveCount(0);
    await page.goto("/ranking");
    await expect(page.getByRole("link", { name: "Ana Beatriz Souza" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Camila Ferreira Dias" })).toHaveCount(0);
    // Rotas de gestão mandam de volta para a Visão geral. (/usuarios abre para o
    // professor com só a própria conta — coberto em permissoes.spec.ts.)
    for (const rota of ["/turmas", "/importacoes", "/metricas", "/sincronizacao", "/escolas"]) {
      await page.goto(rota);
      await expect(page).toHaveURL(/\/$/);
    }
    expect(erros).toEqual([]);
  });
});

test.describe("celular (375 × 812)", () => {
  test.use({ storageState: STORAGE.coord, viewport: { width: 375, height: 812 } });

  test("menu pela gaveta, telas principais sem rolagem lateral e diálogo de certificados usável", async ({ page }) => {
    const erros = vigiarErros(page);
    await page.goto("/");
    await page.getByRole("button", { name: "Abrir menu" }).click();
    // O Ranking Geral mora no grupo "Reconhecimento" (fechado na 1ª visita; só "Minha
    // Escola" nasce aberta).
    await page.getByRole("dialog", { name: "Menu de navegação" }).getByRole("button", { name: "Reconhecimento" }).click();
    await page.getByRole("link", { name: "Ranking Geral" }).click();
    await expect(page).toHaveURL(/\/ranking$/);
    await expect(page.getByRole("heading", { level: 1 })).toContainText("Ranking");
    for (const rota of ["/", "/ranking", "/alunos", "/turmas", "/premiacoes", "/relatorios", "/metricas", "/sincronizacao"]) {
      await page.goto(rota);
      await page.waitForLoadState("networkidle");
      const sobra = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      expect(sobra, `rolagem lateral em ${rota}`).toBeLessThanOrEqual(0);
    }
    await page.goto("/ranking");
    await page.getByRole("button", { name: "Gerar certificados" }).click();
    const dialogo = page.getByRole("dialog", { name: "Gerar certificados" });
    await expect(dialogo.getByRole("button", { name: "Verificar" })).toBeInViewport();
    await dialogo.getByRole("button", { name: "Fechar" }).click();
    await expect(dialogo).toBeHidden();
    expect(erros).toEqual([]);
  });
});
