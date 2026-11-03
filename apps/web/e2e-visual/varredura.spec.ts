/**
 * Varredura visual: percorre as rotas de cada perfil (coordenação, professor, Admin
 * Global e, numa rede FICTÍCIA criada pela própria API no fim, Admin Global com rede e
 * Secretaria) em 10 larguras (de 1920 a 375 px), grava capturas e um relatório JSON por fase: h1, URL final,
 * erros de console, respostas /api >= 400, rolagem horizontal e as inspeções de
 * `inspecao.ts` (acessibilidade, contraste, elementos cortados, foco visível). Não falha
 * por página: o objetivo é o inventário. Ver playwright.visual.config.ts.
 *
 * Filtros: VISUAL_ROTAS (lista de rotas), VISUAL_LARGURAS (nomes), VISUAL_PAPEIS,
 * VISUAL_CAPTURAS (larguras com captura de tela).
 */
import fs from "node:fs";
import path from "node:path";

import { test, type Page } from "@playwright/test";

import { CONTAS, entrar, type Conta } from "../e2e/helpers";
import { focoInvisivel, inspecionar, type Inspecao } from "./inspecao";

const OUT = process.env.VISUAL_OUT || path.resolve(__dirname, "saida");
const FASE = process.env.VISUAL_FASE || "atual";
const API = "http://localhost:8000/api/v1";
const TODAS_LARGURAS = [
  { nome: "desktop-xl", w: 1920, h: 1080 },
  { nome: "desktop", w: 1440, h: 900 },
  { nome: "notebook-hd", w: 1366, h: 768 },
  { nome: "notebook", w: 1280, h: 720 },
  { nome: "tablet-h-11", w: 1180, h: 820 },
  { nome: "tablet-h", w: 1024, h: 768 },
  { nome: "tablet-v", w: 820, h: 1180 },
  { nome: "tablet-v-768", w: 768, h: 1024 },
  { nome: "celular-g", w: 414, h: 896 },
  { nome: "celular", w: 375, h: 812 },
];
const filtro = (v: string | undefined) => (v || "").split(",").map((s) => s.trim()).filter(Boolean);
const SO_LARGURAS = filtro(process.env.VISUAL_LARGURAS);
const LARGURAS = TODAS_LARGURAS.filter((l) => !SO_LARGURAS.length || SO_LARGURAS.includes(l.nome));
const CAPTURA_EM = new Set(filtro(process.env.VISUAL_CAPTURAS || "desktop,tablet-h,tablet-v,celular"));
const SO_ROTAS = filtro(process.env.VISUAL_ROTAS);
const SO_PAPEIS = filtro(process.env.VISUAL_PAPEIS);
// O teste de foco (Tab) roda numa largura só: o comportamento não muda com ela.
const FOCO_EM = "desktop";

/** Conta da Secretaria criada no teste da rede fictícia (só existe no banco do seed). */
const SECRETARIA: Conta = { email: "secretaria.visual@example.com", senha: "Painel#Visual2026!", nome: "Secretaria Visual" };

// "@aluno"/"@turma" viram o 1º perfil de aluno/turma da listagem; "@evolucao" é a
// evolução desse aluno. Da rede: "@ficha" é a ficha da 1ª escola da lista de Escolas
// (/rede/escolas/:id), "@comparar" a comparação lado a lado das duas primeiras
// (?comparar=), ids REAIS lidos da tela; "@avaliacoes-escolas" é /rede/avaliacoes-externas
// com a seção "Todas as escolas na edição mais recente…" carregada (ela só lê ao rolar).
const ROTAS = {
  coord: [
    "/", "/ranking", "/ranking?ver=leitura", "/ranking?ver=matematica", "/ranking?ver=evolucao",
    "/ranking?ver=turmas", "/premiacoes", "/alunos", "@aluno", "@evolucao", "/turmas", "@turma",
    "/professores", "/metricas", "/configuracoes", "/configuracoes/conquistas", "/conquistas",
    "/conquistas/biblioteca", "/insights", "/relatorios", "/relatorios/periodo", "/usuarios",
    "/minha-conta", "/suporte", "/comparador", "/escola", "/matific", "/elefante", "/livros",
    "/comecar", "/importacoes", "/sincronizacao", "/revisoes-identidade", "/diagnostico-elefante",
    "/assistente", "/painel-publico", "/simulador",
  ],
  prof: [
    "/", "/ranking", "/alunos", "@aluno", "/premiacoes", "/insights", "/conquistas/biblioteca",
    "/relatorios", "/minha-conta", "/suporte",
  ],
  admin: [
    "/", "/rede", "/rede/gerenciar", "/rede/avaliacoes", "/rede/analise", "/rede/ranking",
    "/escolas", "/sessoes", "/configuracoes", "/usuarios", "/metricas", "/importacoes",
  ],
  // A Visão da rede é o Panorama da Secretaria com o seletor de rede; as telas da Secretaria
  // (Escolas, a comparação, a ficha, as Avaliações externas) abrem para o global pelos links dela.
  "admin-rede": ["/", "/rede", "/rede/visao", "/rede/escolas", "@comparar", "@ficha", "/rede/avaliacoes-externas",
    "@avaliacoes-escolas", "/rede/gerenciar", "/rede/avaliacoes", "/rede/analise", "/rede/ranking",
    "/rede/ranking?ver=turmas"],
  // As três áreas da Secretaria (DESENHO3 §1: Panorama, Escolas — com a comparação e a ficha —,
  // Avaliações externas — com todas as escolas) e, como cobertura, as telas que saíram do menu
  // dela e continuam abrindo (mesmas guardas).
  secretaria: ["/", "/rede/escolas", "@comparar", "@ficha", "/rede/avaliacoes-externas", "@avaliacoes-escolas",
    "/rede/plataformas", "/rede/ranking", "/rede/ranking?ver=turmas", "/rede/avaliacoes", "/rede/acompanhamento",
    "/rede/relatorios", "/rede", "/rede/visao", "/rede/analise", "/rede/analise?ver=relacao",
    "/rede/analise?ver=escola", "/minha-conta", "/suporte"],
} as const;

/** Depois de abrir a rota (por largura): o que ela precisa para mostrar tudo. */
const PREPARO: Record<string, (page: Page) => Promise<void>> = {
  // A seção das escolas das Avaliações externas só lê o diagnóstico ao chegar perto da tela.
  "@avaliacoes-escolas": async (page) => {
    const secao = page.getByTestId("todas-as-escolas");
    if (!(await secao.isVisible().catch(() => false))) return;
    await secao.scrollIntoViewIfNeeded().catch(() => undefined);
    await secao.getByTestId("tabela-comparacao-escolas").or(secao.getByTestId("comparacao-vazia"))
      .first().waitFor({ timeout: 30_000 }).catch(() => undefined);
    await page.waitForLoadState("networkidle", { timeout: 20_000 }).catch(() => undefined);
    await page.evaluate(() => window.scrollTo(0, 0));
  },
};

interface Registro {
  fase: string;
  papel: string;
  rota: string;
  largura: string;
  urlFinal: string;
  h1: string;
  errosConsole: string[];
  apiComErro: string[];
  rolagemHorizontal: number;
  inspecao?: Inspecao;
  foco?: { testados: number; invisiveis: string[] };
  captura?: string;
  ms: number;
}

const registros: Registro[] = [];

function nomeArquivo(papel: string, rota: string, largura: string): string {
  const r = rota === "/" ? "inicio" : rota.replace(/^\//, "").replace(/[/?=&@]+/g, "_");
  return `${FASE}__${papel}__${r}__${largura}.png`;
}

async function resolve(page: Page, rota: string): Promise<string | null> {
  if (!rota.startsWith("@")) return rota;
  if (rota === "@avaliacoes-escolas") return "/rede/avaliacoes-externas";
  if (rota === "@ficha" || rota === "@comparar") {
    // Os links da lista de Escolas (o nome de cada escola leva à ficha; o global leva o ?rede=).
    await page.goto("/rede/escolas");
    await page.waitForLoadState("networkidle", { timeout: 20_000 }).catch(() => undefined);
    const links = page.locator('main a[href^="/rede/escolas/"]');
    await links.first().waitFor({ timeout: 20_000 }).catch(() => undefined);
    const hrefs = (await links.evaluateAll((as) => as.map((a) => a.getAttribute("href") || "")))
      .filter((h) => /^\/rede\/escolas\/\d+/.test(h));
    if (rota === "@ficha") return hrefs[0] ?? null;
    const ids = [...new Set(hrefs.map((h) => h.match(/^\/rede\/escolas\/(\d+)/)![1]))].slice(0, 2);
    if (ids.length < 2) return null;
    const rede = new URL(hrefs[0], "http://x").searchParams.get("rede");
    return `/rede/escolas?comparar=${ids.join(",")}${rede ? `&rede=${rede}` : ""}`;
  }
  const lista = rota === "@turma" ? "/turmas" : "/alunos";
  await page.goto(lista);
  await page.waitForLoadState("networkidle", { timeout: 20_000 }).catch(() => undefined);
  const re = rota === "@turma" ? /^\/turmas\/\d+$/ : /^\/alunos\/\d+$/;
  const hrefs = await page.locator("a[href]").evaluateAll((as) => as.map((a) => a.getAttribute("href") || ""));
  const achou = hrefs.find((h) => re.test(h)) ?? null;
  return achou && rota === "@evolucao" ? `${achou}/evolucao` : achou;
}

async function registrar(page: Page, papel: string, rotaRotulo: string, largura: string, ms: number,
  erros: string[], api: string[]): Promise<Registro> {
  const rolagem = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  const h1 = ((await page.locator("h1").first().textContent({ timeout: 1_000 }).catch(() => "")) || "").trim();
  const inspecao = await inspecionar(page).catch(() => undefined);
  const url = new URL(page.url());
  return { fase: FASE, papel, rota: rotaRotulo, largura, urlFinal: url.pathname + url.search, h1: h1.slice(0, 120),
    errosConsole: [...erros], apiComErro: [...new Set(api)], rolagemHorizontal: Math.max(0, rolagem), inspecao, ms };
}

async function varre(page: Page, papel: string, rotas: readonly string[]): Promise<void> {
  let erros: string[] = [];
  let api: string[] = [];
  page.on("console", (m) => {
    if (m.type() === "error") erros.push(m.text().slice(0, 300));
  });
  page.on("pageerror", (e) => erros.push(("pageerror: " + e.message).slice(0, 300)));
  page.on("response", (r) => {
    if (r.url().includes("/api/") && r.status() >= 400) api.push(`${r.status()} ${new URL(r.url()).pathname}`);
  });
  for (const original of rotas) {
    if (SO_ROTAS.length && !SO_ROTAS.includes(original)) continue;
    const rota = await resolve(page, original);
    if (!rota) {
      registros.push({ fase: FASE, papel, rota: original, largura: "-", urlFinal: "", h1: "(sem item na listagem)",
        errosConsole: [], apiComErro: [], rolagemHorizontal: 0, ms: 0 });
      continue;
    }
    for (const l of LARGURAS) {
      erros = [];
      api = [];
      await page.setViewportSize({ width: l.w, height: l.h });
      const t0 = Date.now();
      await page.goto(rota);
      await page.waitForLoadState("networkidle", { timeout: 20_000 }).catch(() => undefined);
      await PREPARO[original]?.(page);
      await page.waitForTimeout(400);
      const ms = Date.now() - t0;
      const reg = await registrar(page, papel, original === rota ? rota : `${original} (${rota})`, l.nome, ms, erros, api);
      if (CAPTURA_EM.has(l.nome)) {
        const arq = nomeArquivo(papel, original, l.nome);
        await page.screenshot({ path: path.join(OUT, arq), fullPage: true });
        reg.captura = arq;
      }
      if (l.nome === FOCO_EM) reg.foco = await focoInvisivel(page).catch(() => undefined);
      registros.push(reg);
    }
  }
}

async function chamar(page: Page, metodo: "GET" | "POST" | "PUT", caminho: string, corpo?: unknown) {
  const token = await page.evaluate(() => localStorage.getItem("sgpe_token"));
  const r = await page.request.fetch(API + caminho, {
    method: metodo,
    headers: { Authorization: `Bearer ${token}` },
    ...(corpo === undefined ? {} : { data: corpo }),
  });
  if (!r.ok()) throw new Error(`${metodo} ${caminho} → ${r.status()} ${(await r.text()).slice(0, 200)}`);
  return r.json();
}

async function sair(page: Page): Promise<void> {
  await page.evaluate(() => localStorage.clear());
  await page.context().clearCookies();
}

const papelAtivo = (p: string) => !SO_PAPEIS.length || SO_PAPEIS.includes(p);

test.describe.configure({ mode: "serial" });

test.afterAll(() => {
  fs.mkdirSync(OUT, { recursive: true });
  fs.writeFileSync(path.join(OUT, `relatorio-${FASE}.json`), JSON.stringify(registros, null, 1), "utf-8");
});

test("telas sem sessão (login e redefinição de senha)", async ({ page }) => {
  test.skip(!papelAtivo("anonimo"));
  fs.mkdirSync(OUT, { recursive: true });
  for (const rota of ["/login", "/redefinir-senha?token=token-de-exemplo-invalido"]) {
    if (SO_ROTAS.length && !SO_ROTAS.includes(rota)) continue;
    for (const l of LARGURAS) {
      const erros: string[] = [];
      page.removeAllListeners("console");
      page.on("console", (m) => { if (m.type() === "error") erros.push(m.text().slice(0, 300)); });
      await page.setViewportSize({ width: l.w, height: l.h });
      await page.goto(rota);
      await page.waitForLoadState("networkidle", { timeout: 20_000 }).catch(() => undefined);
      const reg = await registrar(page, "anonimo", rota, l.nome, 0, erros, []);
      if (CAPTURA_EM.has(l.nome)) {
        reg.captura = nomeArquivo("anonimo", rota.split("?")[0], l.nome);
        await page.screenshot({ path: path.join(OUT, reg.captura), fullPage: true });
      }
      if (l.nome === FOCO_EM) reg.foco = await focoInvisivel(page).catch(() => undefined);
      registros.push(reg);
    }
  }
});

for (const papel of ["coord", "prof", "admin"] as const) {
  test(`rotas do perfil ${papel}`, async ({ page }) => {
    test.skip(!papelAtivo(papel));
    test.setTimeout(90 * 60_000);
    await page.setViewportSize({ width: 1440, height: 900 });
    await entrar(page, CONTAS[papel]);
    await varre(page, papel, ROTAS[papel]);
  });
}

test("rede fictícia: Admin Global com rede e Secretaria", async ({ page }) => {
  test.skip(!papelAtivo("admin-rede") && !papelAtivo("secretaria"));
  test.setTimeout(60 * 60_000);
  await page.setViewportSize({ width: 1440, height: 900 });
  await entrar(page, CONTAS.admin);
  // Monta a rede pela própria API (só no banco descartável do seed): a escola de
  // demonstração + uma segunda escola vazia, e uma conta promovida a Secretaria.
  const escolas = (await chamar(page, "GET", "/escolas")) as { id: number; nome: string }[];
  const demo = escolas[0];
  const segunda = await chamar(page, "POST", "/escolas", { nome: "EMEF Fictícia Segunda Unidade", cidade: "Cidade Fictícia", estado: "SP" });
  const rede = await chamar(page, "POST", "/redes", { nome: "Rede Municipal Fictícia", uf: "SP" });
  await chamar(page, "PUT", `/redes/${rede.id}/escolas`, { escola_ids: [demo.id, segunda.id] });
  const conta = await chamar(page, "POST", `/escolas/${demo.id}/usuarios`, {
    nome: SECRETARIA.nome, email: SECRETARIA.email, senha: SECRETARIA.senha, cargo: "coordenador",
  });
  await chamar(page, "PUT", `/redes/${rede.id}/usuarios`, { usuario_ids: [conta.id] });

  if (papelAtivo("admin-rede")) {
    await page.goto("/");
    await varre(page, "admin-rede", ROTAS["admin-rede"]);
  }
  if (papelAtivo("secretaria")) {
    await sair(page);
    await page.setViewportSize({ width: 1440, height: 900 });
    await entrar(page, SECRETARIA);
    await varre(page, "secretaria", ROTAS.secretaria);
  }
});
