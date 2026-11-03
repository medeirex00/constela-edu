/**
 * VITRINE PÚBLICA — painel público da escola (`/p/:token`) e vitrine da rede (`/rede/p/:token`)
 * — nos quatro perfis, contra o backend REAL (config: playwright.analise.config.ts; dados
 * INVENTADOS de backend/scripts/seed_e2e_analise.py).
 *
 * A causa do "não abre": o link vinha do backend com `PUBLIC_BASE_URL` (padrão = domínio de
 * produção) e, numa instalação local, levava para a produção, onde o token local não existe.
 * O backend daqui roda SEM a variável (playwright.analise.config.ts), como a demo: sem a
 * correção, o link é o da produção e estes testes falham. Aqui se confere que o link aberto
 * pela tela é da MESMA origem que serve a tela e que a página pública abre DE VERDADE
 * (título, conteúdo, sem exceção) — não só HTTP 200 —, inclusive com um token de sessão
 * VENCIDO guardado no navegador (antes, a página pública virava a tela de login).
 *
 * Regras de acesso (existentes, não mudam): o painel da escola é configurado pela coordenação,
 * pela administração da escola e pelo admin global; a vitrine da rede, pela Secretaria e pelo
 * admin global. A Secretaria liga e abre a vitrine no PANORAMA DA REDE ("/", seção
 * "Reconhecimento público" — DESENHO3 §2); o admin global, no Painel da Rede (/rede). A
 * professora não configura nem recebe o link pela tela (rota barrada), mas abre a página
 * pública como qualquer pessoa que tenha o link — logada ou não.
 */
import { expect, test, type APIRequestContext, type BrowserContext, type Page } from "@playwright/test";

const API = process.env.E2E_ANALISE_API_URL || "http://127.0.0.1:8010";
const PRODUCAO = "constelaedu.com";

type Perfil = "global" | "secretaria" | "coord" | "prof";
const EMAIL: Record<Perfil, string> = {
  global: "global@analise-e2e.local",
  secretaria: "secretaria@analise-e2e.local",
  coord: "coord@analise-e2e.local",
  prof: "prof@analise-e2e.local",
};
const SENHA: Record<Perfil, string | undefined> = {
  global: process.env.E2E_ANALISE_SENHA_GLOBAL,
  secretaria: process.env.E2E_ANALISE_SENHA_SECRETARIA,
  coord: process.env.E2E_ANALISE_SENHA_COORD,
  prof: process.env.E2E_ANALISE_SENHA_PROF,
};

async function entrar(page: Page, perfil: Perfil) {
  const senha = SENHA[perfil];
  expect(senha && senha.length > 7, "rode pelo playwright.analise.config.ts").toBeTruthy();
  await page.goto("/login");
  await page.getByLabel(/mail ou nome de usu/i).fill(EMAIL[perfil]);
  await page.getByLabel("Senha", { exact: true }).fill(senha as string);
  await page.getByRole("button", { name: /^entrar$/i }).click();
  await page.waitForURL((u) => !u.pathname.startsWith("/login"));
  await expect(page.getByText("Abrindo o sistema...")).toHaveCount(0);
}

async function token(request: APIRequestContext, perfil: Perfil): Promise<string> {
  const r = await request.post(`${API}/api/v1/auth/login`, {
    form: { username: EMAIL[perfil], password: SENHA[perfil] as string },
  });
  expect(r.ok(), `login ${perfil}`).toBeTruthy();
  return (await r.json()).access_token as string;
}

/** Problemas da página: exceções, erros de console e respostas 5xx da API. */
function vigiar(page: Page) {
  const problemas: string[] = [];
  page.on("pageerror", (e) => problemas.push(`EXCEÇÃO: ${e.message}`));
  page.on("console", (m) => { if (m.type() === "error") problemas.push(`console: ${m.text()}`); });
  page.on("response", (r) => { if (r.url().includes("/api/") && r.status() >= 500) problemas.push(`${r.status()} ${r.url()}`); });
  return problemas;
}

/** Clica no link que abre a página pública numa NOVA aba e confere que ela abre de verdade
 *  (`conferirAba`: o que mais a aba aberta tem de mostrar). */
async function abrirEConferir(contexto: BrowserContext, page: Page, nomeDoLink: RegExp, caminho: RegExp,
                              conteudo: RegExp, conferirAba?: (aba: Page) => Promise<void>) {
  const link = page.getByRole("link", { name: nomeDoLink });
  await expect(link).toBeVisible();
  const href = (await link.getAttribute("href")) ?? "";
  expect(href, "o link aponta para a produção").not.toContain(PRODUCAO);
  expect(new URL(href).origin, "o link é da mesma origem que serve a tela").toBe(new URL(page.url()).origin);
  expect(new URL(href).pathname).toMatch(caminho);
  const [aba] = await Promise.all([contexto.waitForEvent("page"), link.click()]);
  const problemas = vigiar(aba);
  await aba.waitForLoadState("networkidle");
  await expect(aba.getByRole("heading", { level: 1 }).first()).toBeVisible();
  await expect(aba.getByText(/não encontrad[oa] ou desativad[oa]/)).toHaveCount(0);
  await expect(aba.locator("body")).toContainText(conteudo);
  if (conferirAba) await conferirAba(aba);
  expect(problemas, problemas.join("\n")).toEqual([]);
  await aba.close();
  return href;
}

async function ligarPainelDaEscola(page: Page) {
  await page.goto("/painel-publico");
  const chave = page.getByRole("checkbox", { name: "Painel público ativo" });
  await expect(chave).toBeAttached();
  // A caixa é só para leitor de tela (a chave desenhada fica por cima): clica no rótulo, como a pessoa.
  if (!(await chave.isChecked())) await page.locator("label", { hasText: "Painel público ativo" }).click();
  await expect(chave).toBeChecked();
  await expect(page.getByRole("link", { name: "Abrir", exact: true })).toBeVisible();
}

/** Liga a vitrine da rede onde o perfil a encontra: o Painel da Rede (admin global, "/rede") ou
 *  o Panorama da Rede (Secretaria, "/", na seção "Reconhecimento público"). */
async function ligarVitrineDaRede(page: Page, caminho: "/rede" | "/") {
  await page.goto(caminho);
  const onde = caminho === "/" ? page.getByTestId("reconhecimento-publico") : page.locator("main");
  const ligar = onde.getByRole("button", { name: "Ligar vitrine pública" });
  const abrir = onde.getByRole("link", { name: /Abrir vitrine/ });
  await expect(ligar.or(abrir)).toBeVisible();
  if (await ligar.isVisible()) await ligar.click();
  await expect(abrir).toBeVisible();
}

test.describe.configure({ mode: "serial" });

test("coordenação: o painel público da escola abre pela tela e mostra o telão", async ({ page, context }) => {
  await entrar(page, "coord");
  await ligarPainelDaEscola(page);
  await abrirEConferir(context, page, /^Abrir$/, /^\/p\/[^/]+$/, /Fictícia|Ébano/);
});

test("admin global: painel da escola e vitrine da rede abrem pela tela", async ({ page, context }) => {
  await entrar(page, "global");
  await ligarPainelDaEscola(page);
  await abrirEConferir(context, page, /^Abrir$/, /^\/p\/[^/]+$/, /Fictícia|Ébano/);
  await ligarVitrineDaRede(page, "/rede");
  await abrirEConferir(context, page, /Abrir vitrine/, /^\/rede\/p\/[^/]+$/, /escolas em destaque/i);
});

test("Secretaria: a vitrine da rede abre pelo Panorama da Rede (o link copiado é o mesmo e mostra os destaques dele)", async ({ page, context }) => {
  await entrar(page, "secretaria");
  await ligarVitrineDaRede(page, "/");
  await expect(page.getByRole("heading", { level: 1, name: "Panorama da Rede" })).toBeVisible();
  // As escolas em destaque do Panorama (o mesmo critério da vitrine; para a Secretaria, sem as que
  // ficaram fora para proteger as crianças): todas estão na vitrine aberta.
  const destaques = page.getByTestId("escolas-em-destaque");
  await expect(page.getByTestId("criterio-destaques")).toBeVisible();
  const nomes = await destaques.locator("ol > li a").allInnerTexts();
  expect(nomes.length, "o seed tem escolas em destaque").toBeGreaterThan(0);
  const reconhecimento = page.getByTestId("reconhecimento-publico");
  const href = await abrirEConferir(context, page, /Abrir vitrine/, /^\/rede\/p\/[^/]+$/, /Rede Fictícia do Litoral/,
    async (aba) => {
      for (const nome of new Set(nomes)) await expect(aba.locator("body")).toContainText(nome);
    });
  await expect(reconhecimento.locator("code").filter({ hasText: "/rede/p/" })).toHaveText(href);
  // A Secretaria não configura o painel de UMA escola (opera a rede; o backend recusa): quem chega
  // a /painel-publico por um link antigo NÃO fica em "Carregando..." — a tela a leva à vitrine da
  // rede, que fica no Panorama da Rede.
  const problemas = vigiar(page);
  await page.goto("/painel-publico");
  await expect(page.getByText(/A vitrine da rede fica no Panorama da Rede/)).toBeVisible();
  await expect(page.getByText("Carregando...")).toHaveCount(0);
  await page.getByRole("link", { name: /Ir para a vitrine da rede/ }).click();
  await page.waitForURL((u) => u.pathname === "/");
  await expect(page.getByTestId("reconhecimento-publico").getByRole("link", { name: /Abrir vitrine/ })).toBeVisible();
  expect(problemas, problemas.join("\n")).toEqual([]);
});

test("professora: não configura (rota barrada, sem item no menu), mas abre o link público — logada ou não",
  async ({ page, request, browser }) => {
    // Os links públicos, como a coordenação e a Secretaria os entregariam.
    const tCoord = await token(request, "coord");
    const me = await (await request.get(`${API}/api/v1/auth/me`, { headers: { Authorization: `Bearer ${tCoord}` } })).json();
    const painel = await (await request.get(`${API}/api/v1/escolas/${me.escola_id}/painel-publico`,
      { headers: { Authorization: `Bearer ${tCoord}` } })).json();
    expect(painel.ativo, "o teste da coordenação liga o painel antes").toBe(true);
    const tSec = await token(request, "secretaria");
    const redes = await (await request.get(`${API}/api/v1/redes`, { headers: { Authorization: `Bearer ${tSec}` } })).json();
    const vitrine = await (await request.get(`${API}/api/v1/redes/${redes[0].id}/publico`,
      { headers: { Authorization: `Bearer ${tSec}` } })).json();
    expect(vitrine.ativo, "o teste da Secretaria liga a vitrine antes").toBe(true);
    const caminhos = [new URL(painel.url).pathname, new URL(vitrine.url).pathname];

    await entrar(page, "prof");
    const menu = page.getByRole("navigation", { name: "Menu principal" }).filter({ visible: true }).first();
    await expect(menu.getByRole("link", { name: /Painel Público|Vitrine/ })).toHaveCount(0);
    await page.goto("/painel-publico");
    await page.waitForURL((u) => u.pathname === "/");
    for (const [i, caminho] of caminhos.entries()) {
      const problemas = vigiar(page);
      await page.goto(caminho);
      await page.waitForLoadState("networkidle");
      await expect(page.getByRole("heading", { level: 1 }).first()).toBeVisible();
      await expect(page.locator("body")).toContainText(i === 0 ? /Fictícia|Ébano/ : /escolas em destaque/i);
      expect(problemas, problemas.join("\n")).toEqual([]);
    }
    // Sem login (quem recebe o link): também abre.
    const anonimo = await browser.newContext();
    const visitante = await anonimo.newPage();
    for (const caminho of caminhos) {
      await visitante.goto(caminho);
      await expect(visitante.getByRole("heading", { level: 1 }).first()).toBeVisible();
      await expect(visitante.getByText(/não encontrad[oa] ou desativad[oa]/)).toHaveCount(0);
    }
    await anonimo.close();
    // Com um token de sessão VENCIDO guardado no navegador (a TV que religa no dia seguinte):
    // a página pública abre e NÃO vira a tela de login (antes, o /auth/me dava 401 e redirecionava).
    const vencido = await browser.newContext();
    await vencido.addInitScript(() => localStorage.setItem("sgpe_token", "token-vencido-de-teste"));
    const tv = await vencido.newPage();
    for (const [i, caminho] of caminhos.entries()) {
      await tv.goto(caminho);
      await tv.waitForLoadState("networkidle");
      expect(new URL(tv.url()).pathname, "a página pública não manda para o login").toBe(caminho);
      await expect(tv.getByRole("heading", { level: 1 }).first()).toBeVisible();
      await expect(tv.locator("body")).toContainText(i === 0 ? /Fictícia|Ébano/ : /escolas em destaque/i);
    }
    await vencido.close();
  });
