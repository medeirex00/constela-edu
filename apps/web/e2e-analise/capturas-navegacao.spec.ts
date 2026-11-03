/**
 * CAPTURAS de navegação (antes/depois) dos quatro perfis — ferramenta de evidência, não
 * teste de regressão: só roda com CAPTURAS_NAV=1 (fora disso, pulada).
 *
 * Mesmo backend e mesmos dados INVENTADOS do playwright.analise.config.ts (rede fictícia,
 * 4 contas de teste). Para cada perfil grava, em CAPTURAS_PASTA (padrão
 * test-results/analise/capturas-nav):
 *   - menu-<fase>-<perfil>.json   a árvore do menu lateral (seção > grupo > item), lida do DOM;
 *   - <fase>-<perfil>-menu-desktop.png / -menu-celular.png   o menu com TODOS os grupos abertos;
 *   - <fase>-<perfil>-<tela>.png   as telas principais (1440 px, página inteira); uma rota que
 *     não existe nesta versão (redireciona para "/") é pulada e anotada no JSON.
 *
 * Rodar (em apps/web):
 *   CAPTURAS_NAV=1 CAPTURAS_FASE=antes E2E_PYTHON=<python> npx playwright test \
 *     -c playwright.analise.config.ts capturas-navegacao
 */
import fs from "node:fs";
import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

const FASE = process.env.CAPTURAS_FASE || "atual";
const PASTA = process.env.CAPTURAS_PASTA || path.join(__dirname, "..", "test-results", "analise", "capturas-nav");

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

/**
 * Telas de cada perfil. Rotas novas entram aqui; na versão que não as tem, são puladas. Rotas com
 * id: "@ficha" é a ficha da 1ª escola da lista de Escolas e "@comparar", a comparação das duas
 * primeiras (ids REAIS, lidos da tela). O 3º elemento, "rolar-escolas", rola até "Todas as
 * escolas na edição mais recente…" (Avaliações externas), que só carrega ao chegar perto da tela.
 */
type Preparo = "rolar-escolas";
const TELAS: Record<Perfil, [string, string, Preparo?][]> = {
  // DESENHO3 §1: as três áreas (Panorama, Escolas — com a comparação e a ficha —, Avaliações
  // externas — com todas as escolas) e as telas que saíram do menu e continuam abrindo.
  secretaria: [
    ["inicio", "/"],
    ["escolas", "/rede/escolas"],
    ["escolas-comparar", "@comparar"],
    ["ficha-escola", "@ficha"],
    ["avaliacoes", "/rede/avaliacoes-externas"],
    ["avaliacoes-ica", "/rede/avaliacoes-externas?indicador=ica"],
    ["avaliacoes-todas-as-escolas", "/rede/avaliacoes-externas", "rolar-escolas"],
    ["plataformas", "/rede/plataformas"],
    ["ranking-rede", "/rede/ranking"],
    ["fontes", "/rede/avaliacoes"],
    ["acompanhamento", "/rede/acompanhamento"],
    ["relatorios", "/rede/relatorios"],
    ["painel-rede", "/rede"],
    ["avancadas-diagnostico", "/rede/analise"],
    ["avancadas-relacao", "/rede/analise?ver=relacao"],
    ["avancadas-escola", "/rede/analise?ver=escola"],
  ],
  global: [
    ["inicio", "/"], ["painel-rede", "/rede"], ["visao-rede", "/rede/visao"], ["escolas", "/rede/escolas"],
    ["escolas-comparar", "@comparar"], ["ficha-escola", "@ficha"], ["avaliacoes", "/rede/avaliacoes-externas"],
    ["avaliacoes-todas-as-escolas", "/rede/avaliacoes-externas", "rolar-escolas"], ["analise-visao", "/rede/analise"],
  ],
  coord: [["inicio", "/"], ["escola", "/escola"], ["turmas", "/turmas"], ["alunos", "/alunos"]],
  prof: [["inicio", "/"], ["alunos", "/alunos"]],
};

/** "@ficha"/"@comparar" → a rota real, pelos links da lista de Escolas (com o ?rede= do global,
 *  quando houver); `null` = a lista não tem escolas suficientes (ou a tela não existe). */
async function resolverRota(page: Page, rota: string): Promise<string | null> {
  if (!rota.startsWith("@")) return rota;
  await page.goto("/rede/escolas");
  await page.waitForLoadState("networkidle");
  await page.locator('main a[href^="/rede/escolas/"]').first().waitFor({ timeout: 20_000 }).catch(() => undefined);
  const hrefs = (await page.locator('main a[href^="/rede/escolas/"]').evaluateAll((as) =>
    as.map((a) => a.getAttribute("href") || ""))).filter((h) => /^\/rede\/escolas\/\d+/.test(h));
  if (rota === "@ficha") return hrefs[0] ?? null;
  const ids = [...new Set(hrefs.map((h) => h.match(/^\/rede\/escolas\/(\d+)/)![1]))].slice(0, 2);
  if (ids.length < 2) return null;
  const rede = new URL(hrefs[0], "http://x").searchParams.get("rede");
  return `/rede/escolas?comparar=${ids.join(",")}${rede ? `&rede=${rede}` : ""}`;
}

/** Rola até a seção das escolas (Avaliações externas) e espera a tabela ou o "sem resultado". */
async function rolarAteTodasAsEscolas(page: Page) {
  const secao = page.getByTestId("todas-as-escolas");
  if (!(await secao.isVisible())) return;
  await secao.scrollIntoViewIfNeeded();
  await secao.getByTestId("tabela-comparacao-escolas").or(secao.getByTestId("comparacao-vazia"))
    .first().waitFor({ timeout: 30_000 }).catch(() => undefined);
  await page.waitForLoadState("networkidle");
  // A captura da página inteira sai do topo (sem o topo fixo no meio da imagem).
  await page.evaluate(() => window.scrollTo(0, 0));
}

interface NoMenu { tipo: "secao" | "grupo" | "item"; texto: string; href?: string; nivel: number }

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

/** Abre todos os grupos fechados do menu indicado e devolve a árvore lida do DOM. */
async function abrirELerMenu(page: Page, raiz: string): Promise<NoMenu[]> {
  const nav = page.locator(raiz).locator('nav[aria-label="Menu principal"]').first();
  await expect(nav).toBeVisible();
  const fechados = nav.locator('button[aria-expanded="false"]');
  for (let i = 0; i < 30 && (await fechados.count()) > 0; i++) {
    await fechados.first().click();
  }
  await page.waitForTimeout(400); // fim da animação de abrir
  return nav.evaluate((el) => {
    const nos: { tipo: "secao" | "grupo" | "item"; texto: string; href?: string; nivel: number }[] = [];
    const paineis = new Set(
      [...el.querySelectorAll("button[aria-controls]")].map((b) => b.getAttribute("aria-controls")),
    );
    el.querySelectorAll("p, button[aria-expanded], a[href]").forEach((n) => {
      const texto = (n.textContent || "").replace(/\s+/g, " ").trim();
      if (!texto) return;
      if (n.tagName === "P") nos.push({ tipo: "secao", texto, nivel: 0 });
      else if (n.tagName === "BUTTON") nos.push({ tipo: "grupo", texto, nivel: 1 });
      else {
        let dentro = false;
        for (let p = n.parentElement; p && p !== el; p = p.parentElement) {
          if (p.id && paineis.has(p.id)) { dentro = true; break; }
        }
        nos.push({ tipo: "item", texto, href: (n as HTMLAnchorElement).getAttribute("href") || "", nivel: dentro ? 2 : 1 });
      }
    });
    return nos;
  });
}

const PERFIS: Perfil[] = ["coord", "secretaria", "prof", "global"];

for (const perfil of PERFIS) {
  test(`capturas de navegação — ${perfil}`, async ({ page }) => {
    test.skip(!process.env.CAPTURAS_NAV, "só com CAPTURAS_NAV=1");
    test.setTimeout(300_000);
    fs.mkdirSync(PASTA, { recursive: true });
    const saida: { fase: string; perfil: Perfil; menu_desktop: NoMenu[]; menu_celular: NoMenu[]; telas: Record<string, string> } = {
      fase: FASE, perfil, menu_desktop: [], menu_celular: [], telas: {},
    };

    // Menu no desktop, alto o bastante para caber inteiro (a lista rola por dentro).
    await page.setViewportSize({ width: 1440, height: 1600 });
    await entrar(page, perfil);
    await page.goto("/");
    await page.waitForLoadState("networkidle");
    saida.menu_desktop = await abrirELerMenu(page, "body");
    const barra = page.locator('nav[aria-label="Menu principal"]:visible').first();
    await barra.screenshot({ path: path.join(PASTA, `${FASE}-${perfil}-menu-desktop.png`) });

    // Telas principais a 1440×900.
    await page.setViewportSize({ width: 1440, height: 900 });
    for (const [nome, pedida, preparo] of TELAS[perfil]) {
      const rota = await resolverRota(page, pedida);
      if (!rota) { saida.telas[nome] = `${pedida}: sem escolas na lista (rota não resolvida)`; continue; }
      await page.goto(rota);
      await page.waitForLoadState("networkidle");
      if (preparo === "rolar-escolas") await rolarAteTodasAsEscolas(page);
      await page.waitForTimeout(600);
      const atual = new URL(page.url());
      const pedido = new URL(rota, "http://x");
      // Outra rota (a guarda manda ao "/"; um link antigo vai para a tela que o substituiu) ou
      // um parâmetro pedido que não ficou na URL (aba que não existe nesta versão): pula.
      if (atual.pathname !== pedido.pathname) {
        saida.telas[nome] = `redirecionou para ${atual.pathname}${atual.search} (rota ausente ou bloqueada)`; continue;
      }
      const perdido = [...pedido.searchParams].find(([chave, valor]) => atual.searchParams.get(chave) !== valor);
      if (perdido) { saida.telas[nome] = `${perdido[0]}=${perdido[1]} ausente nesta versão`; continue; }
      await page.screenshot({ path: path.join(PASTA, `${FASE}-${perfil}-${nome}.png`), fullPage: true });
      saida.telas[nome] = `${atual.pathname}${atual.search}`;
    }

    // Menu no celular: a gaveta (diálogo) com todos os grupos abertos.
    await page.setViewportSize({ width: 375, height: 1400 });
    await page.goto("/");
    await page.waitForLoadState("networkidle");
    await page.getByRole("button", { name: "Abrir menu" }).click();
    const gaveta = page.getByRole("dialog", { name: "Menu de navegação" });
    await expect(gaveta).toBeVisible();
    saida.menu_celular = await abrirELerMenu(page, '[role="dialog"]');
    await gaveta.screenshot({ path: path.join(PASTA, `${FASE}-${perfil}-menu-celular.png`) });

    fs.writeFileSync(path.join(PASTA, `menu-${FASE}-${perfil}.json`), JSON.stringify(saida, null, 2), "utf-8");
  });
}
