/**
 * Fluxos de REDE (roda por último: cria uma rede no banco descartável do E2E).
 * O Admin Global monta pela API uma rede fictícia com a escola de demonstração e uma
 * segunda escola vazia, e promove uma conta a Secretaria. Confere: o que a Secretaria
 * vê (as três áreas do menu — Panorama da Rede, Escolas, com a comparação e a ficha de
 * cada escola, e Avaliações externas — e as telas que saíram do menu dela e continuam
 * abrindo), o que ela NÃO abre (telas com nome de criança, escrita na escola) e o
 * isolamento direto na API.
 */
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

import { CONTAS, entrar, type Conta } from "./helpers";

const API = "http://localhost:8000/api/v1";
const SECRETARIA: Conta = { email: "secretaria.e2e@example.com", senha: "Painel#Rede2026!", nome: "Secretaria E2E" };

async function token(page: Page): Promise<string> {
  return (await page.evaluate(() => localStorage.getItem("sgpe_token"))) ?? "";
}

async function chamar(req: APIRequestContext, tk: string, metodo: string, caminho: string, corpo?: unknown) {
  return req.fetch(API + caminho, {
    method: metodo,
    headers: { Authorization: `Bearer ${tk}` },
    ...(corpo === undefined ? {} : { data: corpo }),
  });
}

test.describe.configure({ mode: "serial" });

let escolaDemo = 0;
let nomeDemo = "";
let escolaSegunda = 0;
const NOME_SEGUNDA = "EMEF Fictícia Segunda Unidade";

test("Admin Global monta a rede e vê o Painel da Rede e o ranking das escolas", async ({ page }) => {
  await entrar(page, CONTAS.admin);
  const tk = await token(page);
  const escolas = await (await chamar(page.request, tk, "GET", "/escolas")).json();
  escolaDemo = escolas[0].id;
  nomeDemo = escolas[0].nome;
  const segunda = await (await chamar(page.request, tk, "POST", "/escolas",
    { nome: NOME_SEGUNDA, cidade: "Cidade Fictícia", estado: "SP" })).json();
  escolaSegunda = segunda.id;
  const rede = await (await chamar(page.request, tk, "POST", "/redes", { nome: "Rede Municipal Fictícia E2E", uf: "SP" })).json();
  expect((await chamar(page.request, tk, "PUT", `/redes/${rede.id}/escolas`, { escola_ids: [escolaDemo, segunda.id] })).ok()).toBe(true);
  const conta = await (await chamar(page.request, tk, "POST", `/escolas/${escolaDemo}/usuarios`,
    { nome: SECRETARIA.nome, email: SECRETARIA.email, senha: SECRETARIA.senha, cargo: "coordenador" })).json();
  expect((await chamar(page.request, tk, "PUT", `/redes/${rede.id}/usuarios`, { usuario_ids: [conta.id] })).ok()).toBe(true);

  await page.goto("/rede");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  // O Painel da Rede não repete mais a lista das escolas (duplicava o Ranking da Rede):
  // o cartão "Comparar as escolas" leva a Comparar escolas e ao Ranking da Rede.
  await expect(page.getByRole("heading", { name: "Comparar as escolas" })).toBeVisible();
  await expect(page.getByRole("link", { name: /Ranking da Rede/ }).first()).toBeVisible();
  await page.goto("/rede/ranking");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Ranking da Rede");
  await expect(page.getByText(/Não foi possível/)).toHaveCount(0);
});

test("Secretaria: vê a rede, não abre telas com nome de criança e a API nega o acesso nominal", async ({ page }) => {
  test.setTimeout(90_000);
  const erros: string[] = [];
  page.on("pageerror", (e) => erros.push(e.message));
  await entrar(page, SECRETARIA);
  // O menu dela: só as três áreas, sem acordeão.
  const menu = page.getByRole("navigation", { name: "Menu principal" }).filter({ visible: true });
  const hrefs = await menu.locator("a[href]").evaluateAll((as) => as.map((a) => a.getAttribute("href")));
  expect(hrefs).toEqual(["/", "/rede/escolas", "/rede/avaliacoes-externas"]);
  await expect(menu.locator("button[aria-expanded]")).toHaveCount(0);
  // As três áreas (o Panorama, as Escolas com a comparação e a ficha de cada escola — a de
  // demonstração e a vazia —, as Avaliações externas) e as telas que saíram do menu dela
  // (o Painel, o detalhe do uso, o acompanhamento, os relatórios, as Análises avançadas, o
  // Ranking e as fontes) abrem com título e sem erro.
  expect(escolaDemo, "o 1º teste monta a rede").toBeGreaterThan(0);
  for (const [rota, titulo] of [
    ["/", "Panorama da Rede"],
    ["/rede/escolas", "Escolas"],
    [`/rede/escolas?comparar=${escolaDemo},${escolaSegunda}`, "Escolas"],
    [`/rede/escolas/${escolaDemo}`, nomeDemo],
    [`/rede/escolas/${escolaSegunda}`, NOME_SEGUNDA],
    ["/rede/avaliacoes-externas", "Avaliações externas"],
    ["/rede/plataformas", null], ["/rede/acompanhamento", null], ["/rede/relatorios", null], ["/rede", null],
    ["/rede/visao", null], ["/rede/analise", null], ["/rede/ranking", null], ["/rede/avaliacoes", null],
  ] as const) {
    await page.goto(rota);
    await page.waitForLoadState("networkidle");
    expect(new URL(page.url()).pathname, `a Secretaria fica em ${rota}`).toBe(new URL(rota, "http://x").pathname);
    const h1 = page.getByRole("heading", { level: 1 });
    await expect(h1).toBeVisible();
    if (titulo) await expect(h1).toHaveText(titulo);
    await expect(page.getByText(/Não foi possível/)).toHaveCount(0);
    // Só agregado: nenhum nome de criança da escola de demonstração.
    await expect(page.locator("main")).not.toContainText("Ana Beatriz");
  }
  // O Panorama lista as DUAS escolas da rede (a vazia também), cada uma com o link da ficha.
  await page.goto("/");
  for (const id of [escolaDemo, escolaSegunda]) {
    await expect(page.getByTestId(`escola-${id}`).getByRole("link")).toHaveAttribute("href", `/rede/escolas/${id}`);
  }
  // A ficha de uma escola que não é da rede: a mensagem, sem quebrar.
  await page.goto("/rede/escolas/999999");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Escola não encontrada");
  // Telas com dado individual de criança e de operação da escola mandam para o início.
  for (const rota of ["/alunos", "/premiacoes", "/insights", "/relatorios", "/usuarios", "/importacoes", "/sincronizacao", "/matific", "/elefante"]) {
    await page.goto(rota);
    await expect(page, `a Secretaria não deve ficar em ${rota}`).toHaveURL(/\/$/);
  }
  // Isolamento na API: nada nominal nem escrita na escola.
  const tk = await token(page);
  const alunos = await chamar(page.request, tk, "GET", `/escolas/${escolaDemo}/alunos`);
  if (alunos.ok()) {
    // A página da lista, vazia e sem nenhum outro campo (nada de nome por outro caminho);
    // o mesmo contrato de backend/tests/test_rbac_secretaria.py.
    const texto = await alunos.text();
    expect(JSON.parse(texto)).toEqual({ total: 0, pagina: 1, por_pagina: 25, itens: [] });
    expect(texto).not.toContain("Ana Beatriz");
  }
  else expect([401, 403, 404]).toContain(alunos.status());
  const criar = await chamar(page.request, tk, "POST", `/escolas/${escolaDemo}/turmas`,
    { nome: "9º Z", ano_escolar: "5º Ano", ano_letivo: 2026 });
  expect([401, 403]).toContain(criar.status());
  expect(erros).toEqual([]);
});

test("isolamento entre escolas: a coordenação de uma escola não lê a outra", async ({ page }) => {
  await entrar(page, CONTAS.coord);
  const tk = await token(page);
  const minhas = await (await chamar(page.request, tk, "GET", "/escolas")).json() as { id: number }[];
  expect(minhas.map((e) => e.id)).toEqual([escolaDemo]);
  // A segunda escola existe (criada acima), mas não é da coordenação.
  const outra = escolaSegunda;
  expect(outra).toBeGreaterThan(0);
  for (const caminho of [`/escolas/${outra}/alunos`, `/escolas/${outra}/turmas`, `/escolas/${outra}/visao-geral?periodo=bimestre`]) {
    const r = await chamar(page.request, tk, "GET", caminho);
    expect([401, 403, 404], caminho).toContain(r.status());
  }
});
