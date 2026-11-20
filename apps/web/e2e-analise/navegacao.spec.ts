/**
 * NAVEGAÇÃO dos quatro perfis contra o backend REAL (config: playwright.analise.config.ts;
 * dados: backend/scripts/seed_e2e_analise.py — tudo INVENTADO).
 *
 * Para cada perfil (Admin Global, Secretaria, Coordenação, Professora), no desktop e na
 * gaveta do celular: abre todos os grupos do menu lateral, clica em CADA item e confere
 *   - que a página aberta é a do item (sem cair no "/" de uma guarda de rota);
 *   - que o item clicado fica marcado (aria-current="page") e é o ÚNICO marcado;
 *   - que a página tem título (h1), nenhuma exceção e nenhuma resposta 5xx da API;
 *   - que não há dois itens para o mesmo endereço.
 * E, por perfil, que o acesso DIRETO por URL às telas de outros perfis cai no "/" e que as
 * rotas novas da análise (diagnóstico e evolução) respondem 403 a quem não lê a rede — e,
 * para a Secretaria, 200 sem nome de criança nem aluno_id. Da Secretaria (DESENHO3 §1), também
 * os atalhos Alt+1..3 (as três áreas; as outras teclas não navegam) e o cartão Contexto
 * (escolher uma escola abre a ficha dela).
 */
import { expect, test, type Page } from "@playwright/test";

const API = process.env.E2E_ANALISE_API_URL || "http://127.0.0.1:8010";

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

/** Telas que o perfil NÃO pode abrir: o acesso direto pela URL tem de cair no "/". */
const BARRADAS: Record<Perfil, string[]> = {
  global: [],
  secretaria: ["/alunos", "/premiacoes", "/insights", "/relatorios", "/usuarios", "/importacoes",
               "/sincronizacao", "/comparador", "/matific", "/elefante", "/rede/gerenciar", "/escolas", "/sessoes"],
  coord: ["/rede", "/rede/analise", "/rede/avaliacoes", "/rede/ranking", "/rede/gerenciar", "/rede/escolas",
          "/rede/escolas/1", "/rede/avaliacoes-externas", "/escolas", "/sessoes", "/configuracoes"],
  prof: ["/rede", "/rede/analise", "/rede/avaliacoes", "/rede/escolas", "/rede/escolas/1", "/rede/avaliacoes-externas",
         "/turmas", "/professores", "/escola", "/metricas", "/configuracoes", "/sincronizacao", "/importacoes",
         "/escolas", "/matific", "/elefante"],
};

interface Item { texto: string; href: string }

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

function vigiar(page: Page) {
  const problemas: string[] = [];
  page.on("response", (r) => {
    const u = new URL(r.url());
    if (u.pathname.startsWith("/api/") && r.status() >= 500) problemas.push(`${r.status()} ${u.pathname}${u.search}`);
  });
  page.on("pageerror", (e) => problemas.push(`EXCEÇÃO NA PÁGINA: ${e.message}`));
  return problemas;
}

/** O menu (desktop: a barra; celular: a gaveta) com todos os grupos abertos. */
function menu(page: Page, celular: boolean) {
  const raiz = celular ? page.getByRole("dialog", { name: "Menu de navegação" }) : page.locator("body");
  return raiz.locator('nav[aria-label="Menu principal"]').filter({ visible: true }).first();
}

async function abrirGrupos(page: Page, celular: boolean) {
  const nav = menu(page, celular);
  await expect(nav).toBeVisible();
  const fechados = nav.locator('button[aria-expanded="false"]');
  for (let i = 0; i < 30 && (await fechados.count()) > 0; i++) await fechados.first().click();
}

async function lerItens(page: Page, celular: boolean): Promise<Item[]> {
  await abrirGrupos(page, celular);
  return menu(page, celular).locator("a[href]").evaluateAll((as) =>
    as.map((a) => ({ texto: (a.textContent || "").replace(/\s+/g, " ").trim(), href: a.getAttribute("href") || "" })));
}

async function abrirGaveta(page: Page) {
  await page.getByRole("button", { name: "Abrir menu" }).click();
  await expect(page.getByRole("dialog", { name: "Menu de navegação" })).toBeVisible();
}

async function conferirDestino(page: Page, item: Item, celular: boolean, problemas: string[]) {
  const alvo = new URL(item.href, "http://x");
  await page.waitForURL((u) => u.pathname === alvo.pathname
    && (!alvo.searchParams.get("ver") || u.searchParams.get("ver") === alvo.searchParams.get("ver")));
  await page.waitForLoadState("networkidle");
  await expect(page.getByRole("heading", { level: 1 }).first(), `título em ${item.href}`).toBeVisible();
  if (celular) {
    await expect(page.getByRole("dialog", { name: "Menu de navegação" })).toHaveCount(0);
  } else {
    const marcados = await menu(page, false).locator('a[aria-current="page"]').evaluateAll(
      (as) => as.map((a) => a.getAttribute("href")));
    expect(marcados, `item marcado em ${item.href}`).toEqual([item.href]);
  }
  expect(problemas, `sem 5xx nem exceção em ${item.href}`).toEqual([]);
}

const PERFIS: Perfil[] = ["coord", "secretaria", "prof", "global"];

for (const perfil of PERFIS) {
  test.describe(`navegação — ${perfil}`, () => {
    test("desktop: cada item abre a sua página e fica marcado", async ({ page }) => {
      test.setTimeout(240_000);
      const problemas = vigiar(page);
      await page.setViewportSize({ width: 1440, height: 900 });
      await entrar(page, perfil);
      const itens = await lerItens(page, false);
      // A Secretaria tem três (as três áreas); os demais perfis, mais.
      expect(itens.length).toBeGreaterThanOrEqual(3);
      const hrefs = itens.map((i) => i.href);
      expect(new Set(hrefs).size, `itens repetidos: ${hrefs.join(", ")}`).toBe(hrefs.length);
      for (const item of itens) {
        await abrirGrupos(page, false);
        await menu(page, false).locator(`a[href="${item.href}"]`).click();
        await conferirDestino(page, item, false, problemas);
      }
    });

    test("celular: a gaveta leva a cada página e fecha", async ({ page }) => {
      test.setTimeout(240_000);
      const problemas = vigiar(page);
      await page.setViewportSize({ width: 375, height: 812 });
      await entrar(page, perfil);
      await abrirGaveta(page);
      const itens = await lerItens(page, true);
      await page.keyboard.press("Escape");
      for (const item of itens) {
        await abrirGaveta(page);
        await abrirGrupos(page, true);
        await menu(page, true).locator(`a[href="${item.href}"]`).click();
        await conferirDestino(page, item, true, problemas);
        // Mede DEPOIS de os cartões montarem (uma tabela larga só aparece com os dados; medir
        // cedo demais deixou passar a tabela do ICA, que saía 12 px da tela em 375 px).
        await page.waitForTimeout(1000);
        const largura = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
        expect(largura, `rolagem lateral em ${item.href}`).toBeLessThanOrEqual(0);
      }
    });

    test("URL direta de tela de outro perfil cai no início", async ({ page }) => {
      await entrar(page, perfil);
      for (const rota of BARRADAS[perfil]) {
        await page.goto(rota);
        await page.waitForURL((u) => u.pathname === "/");
      }
    });
  });
}

test("celular: o histórico do ICA rola dentro do cartão", async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 800 });
  await entrar(page, "global");
  await page.goto("/rede/avaliacoes");

  const historico = page.getByRole("table", { name: "Importações do ICA desta rede" });
  await expect(historico.getByText(/arquivo_ficticio\.csv/)).toBeVisible();
  await page.evaluate(() => document.fonts.ready);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(360);
  const regiao = page.getByRole("region", { name: "Histórico de importações do ICA: tabela completa" });
  await expect(regiao).toHaveAttribute("tabindex", "0");
  await expect(regiao.getByRole("columnheader", { name: "Quando" })).toBeVisible();
});

test("tela baixa: o menu rola sozinho até o item ativo da última seção (sem roubar o 1º Tab)", async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 560 });
  await entrar(page, "coord");
  // O Simulador fica na última seção da coordenação (Gestão › Regras de pontuação); "Usuários",
  // que servia aqui, foi para Minha Escola, o primeiro grupo, já aberto.
  await page.goto("/simulador");
  await page.waitForLoadState("networkidle");
  const ativo = menu(page, false).locator('a[aria-current="page"]');
  await expect(ativo).toHaveAttribute("href", "/simulador");
  await expect(ativo).toBeInViewport();
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Pular para o conteúdo" })).toBeFocused();
});

test("coordenação: Minha Escola tem Visão da Escola, Turmas, Alunos, Professores, Usuários e Relatórios — no desktop e na gaveta", async ({ page }) => {
  await entrar(page, "coord");
  for (const celular of [false, true]) {
    if (celular) {
      await page.setViewportSize({ width: 390, height: 844 });
      await page.goto("/");
      await abrirGaveta(page);
    }
    const nav = menu(page, celular);
    const grupo = nav.getByRole("button", { name: /^Minha Escola/ });
    if ((await grupo.getAttribute("aria-expanded")) === "false") await grupo.click();
    const painel = page.locator(`[id="${await grupo.getAttribute("aria-controls")}"]`);
    const hrefs = await painel.locator("a[href]").evaluateAll((as) => as.map((a) => a.getAttribute("href")));
    expect(hrefs, celular ? "gaveta do celular" : "desktop")
      .toEqual(["/escola", "/turmas", "/alunos", "/professores", "/usuarios", "/relatorios"]);
    // E "Usuários" não aparece em nenhum outro lugar do menu.
    await abrirGrupos(page, celular);
    await expect(nav.locator('a[href="/usuarios"]')).toHaveCount(1);
  }
});

/** O item aceso no menu do desktop (o href) — um só. */
async function itemAceso(page: Page) {
  const marcados = menu(page, false).locator('a[aria-current="page"]');
  await expect(marcados).toHaveCount(1);
  return marcados.getAttribute("href");
}

test("Secretaria: Alt+1, Alt+2 e Alt+3 levam às três áreas; as outras teclas não navegam", async ({ page }) => {
  const problemas = vigiar(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await entrar(page, "secretaria");
  await page.goto("/rede/plataformas");
  await page.waitForLoadState("networkidle");
  for (const [tecla, destino, titulo] of [
    ["Alt+2", "/rede/escolas", "Escolas"],
    ["Alt+3", "/rede/avaliacoes-externas", "Avaliações externas"],
    ["Alt+1", "/", "Panorama da Rede"],
  ] as const) {
    await page.keyboard.press(tecla);
    await page.waitForURL((u) => u.pathname === destino);
    await expect(page.getByRole("heading", { level: 1, name: titulo })).toBeVisible();
    expect(await itemAceso(page), `item aceso depois de ${tecla}`).toBe(destino);
  }
  // As demais (antes: Ranking, Conquistas, Assistente… telas de escola sem uso para ela) não navegam.
  await page.keyboard.press("Alt+2");
  await page.waitForURL((u) => u.pathname === "/rede/escolas");
  await page.waitForLoadState("networkidle");
  for (const tecla of ["Alt+4", "Alt+5", "Alt+6", "Alt+8", "Alt+9", "Alt+0"]) {
    await page.keyboard.press(tecla);
    await page.waitForTimeout(300);
    expect(new URL(page.url()).pathname, `${tecla} não navega para a Secretaria`).toBe("/rede/escolas");
  }
  expect(problemas, problemas.join("\n")).toEqual([]);
});

test("coordenação: os atalhos dela não mudaram (Alt+2 vai ao Ranking)", async ({ page }) => {
  await entrar(page, "coord");
  await page.waitForLoadState("networkidle");
  await page.keyboard.press("Alt+2");
  await page.waitForURL((u) => u.pathname === "/ranking");
  await page.keyboard.press("Alt+1");
  await page.waitForURL((u) => u.pathname === "/");
});

test("Secretaria: escolher uma escola no Contexto abre a ficha dela; 'Toda a Rede Municipal' numa tela da escola volta ao Panorama", async ({ page }) => {
  const problemas = vigiar(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await entrar(page, "secretaria");
  await page.goto("/rede/avaliacoes-externas");
  await page.waitForLoadState("networkidle");
  const contexto = page.getByLabel("Contexto de visualização");
  const opcoes = await contexto.locator("option").evaluateAll((os) =>
    os.map((o) => ({ valor: (o as HTMLOptionElement).value, texto: (o.textContent || "").trim() })));
  expect(opcoes[0], "a 1ª opção é a rede inteira").toEqual({ valor: "", texto: "Toda a Rede Municipal" });
  const escola = opcoes[1];
  expect(escola?.valor, "a rede tem escolas no Contexto").toBeTruthy();

  // Uma escola, de qualquer tela: a FICHA dela, com o item Escolas aceso.
  await contexto.selectOption(escola.valor);
  await page.waitForURL((u) => u.pathname === `/rede/escolas/${escola.valor}`);
  await expect(page.getByRole("heading", { level: 1, name: escola.texto })).toBeVisible();
  expect(await itemAceso(page)).toBe("/rede/escolas");

  // "Toda a Rede Municipal" fora de uma tela da escola: fica onde está.
  await contexto.selectOption("");
  await page.waitForTimeout(500);
  expect(new URL(page.url()).pathname).toBe(`/rede/escolas/${escola.valor}`);

  // Numa tela da escola (a Visão da Escola), "Toda a Rede Municipal" leva ao Panorama.
  await contexto.selectOption(escola.valor);
  await page.waitForURL((u) => u.pathname === `/rede/escolas/${escola.valor}`);
  await page.goto("/escola");
  await expect(page.getByRole("heading", { level: 1, name: "Visão da Escola" })).toBeVisible();
  await contexto.selectOption("");
  await page.waitForURL((u) => u.pathname === "/");
  await expect(page.getByRole("heading", { level: 1, name: "Panorama da Rede" })).toBeVisible();
  expect(problemas, problemas.join("\n")).toEqual([]);
});

test("rotas novas da análise: 403 para quem não lê a rede; Secretaria sem dado pessoal", async ({ page, request }) => {
  // O token de cada conta sai do próprio login da API (o mesmo que a tela usa).
  async function token(perfil: Perfil): Promise<string> {
    const r = await request.post(`${API}/api/v1/auth/login`, {
      form: { username: EMAIL[perfil], password: SENHA[perfil] as string },
    });
    expect(r.ok(), `login ${perfil}`).toBeTruthy();
    return (await r.json()).access_token as string;
  }
  const tSec = await token("secretaria");
  const redes = await request.get(`${API}/api/v1/redes`, { headers: { Authorization: `Bearer ${tSec}` } });
  const redeId = (await redes.json())[0].id as number;
  // As leituras da rede que as telas novas da Secretaria usam (o diagnóstico, a evolução e as
  // escolas em destaque do Panorama).
  const rotas = [`/api/v1/redes/${redeId}/analise/diagnostico`, `/api/v1/redes/${redeId}/analise/plataformas/evolucao`,
                 `/api/v1/redes/${redeId}/destaques`];
  for (const perfil of ["coord", "prof"] as Perfil[]) {
    const t = await token(perfil);
    for (const rota of rotas) {
      const r = await request.get(`${API}${rota}`, { headers: { Authorization: `Bearer ${t}` } });
      expect(r.status(), `${perfil} ${rota}`).toBe(403);
    }
  }
  for (const rota of rotas) {
    const r = await request.get(`${API}${rota}`, { headers: { Authorization: `Bearer ${tSec}` } });
    expect(r.status(), rota).toBe(200);
    const corpo = await r.text();
    expect(corpo).not.toContain("Criança Fictícia");
    expect(corpo).not.toMatch(/"aluno_id"/);
  }
  void page;
});
