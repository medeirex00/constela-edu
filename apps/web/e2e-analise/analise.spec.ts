/**
 * E2E da INTELIGÊNCIA PEDAGÓGICA DA REDE contra o backend REAL (config:
 * playwright.analise.config.ts; dados: backend/scripts/seed_e2e_analise.py — tudo INVENTADO).
 *
 * A Secretaria tem TRÊS áreas no menu (DESENHO3 §1), conclusão primeiro:
 *  - Panorama da Rede ("/"): a rede no Constela (cadastradas × ativas × com uso no ano letivo),
 *    a participação no ano letivo, TODAS as escolas com a situação de uso (link para a ficha),
 *    as escolas em destaque (GET /redes/{id}/destaques, com o critério escrito), a vitrine
 *    pública ("Reconhecimento público") e as metas (recolhidas);
 *  - Escolas (/rede/escolas): todas as escolas no período, a comparação LADO A LADO de 2 a 4
 *    escolas (?comparar=), com as avaliações externas à parte, e a FICHA de cada escola
 *    (/rede/escolas/:id): cadastro, uso, Elefante e Matific, evolução só da escola e as
 *    avaliações externas da escola (ou o porquê de não ter);
 *  - Avaliações externas (/rede/avaliacoes-externas): um cartão por indicador, o DETALHE do
 *    escolhido ("Ver série histórica e escolas — <SIGLA>") e "Todas as escolas na edição mais
 *    recente…" (carrega ao rolar ou ao pedir).
 * As telas que saíram do menu dela (/rede, /rede/visao, /rede/acompanhamento, /rede/plataformas,
 * /rede/relatorios, /rede/ranking, /rede/analise, /rede/avaliacoes) continuam abrindo, com as
 * mesmas guardas; os `?ver=` antigos de /rede/analise continuam redirecionando. O Admin Global vê
 * o mesmo Panorama em /rede/visao (com o seletor de rede); o menu dele e o da Coordenação não
 * mudaram.
 *
 * O que o seed garante (e este spec confere):
 *  - Rede Fictícia do Litoral com 5 escolas: Alfa, Beta, Delta e Ébano com INEP inventado
 *    e a Gama SEM INEP; ICA da rede 2023 (participação baixa) / 2024 / 2025 = 58% (meta
 *    60%); SARESP 2025 da rede (5º LP 201,4; 2º LP 150,2; 2º MT 160,9) e por escola (Alfa
 *    5º LP 210,3; Beta 190,7 com TPS = 0; Delta só com estimativa); Ideb da rede 2019 5,8 /
 *    2021 5,4 / 2023 6,1; Saeb; e a "Estimativa Constela" fora das séries oficiais;
 *  - plataformas no ano corrente (2º e 5º ano em todas; Beta sem coleta do Elefante;
 *    Ébano com um 3º ano de 3 crianças, suprimido — com a vizinha escondida junto, e o
 *    MESMO texto de supressão nas duas); o Ideb 2023 da Delta é um número do 1 clique
 *    (sem registro oficial): marcado com "*" na visão por escolas, fora dos destaques;
 *  - RELAÇÃO: NÃO calculável por construção — avaliações até 2025 × plataformas do ano
 *    corrente (motivo `periodo_sem_sobreposicao`), e a rede tem menos de 8 escolas. A
 *    tela tem de mostrar o motivo, o "lado a lado" e nenhum coeficiente.
 *
 * Em todos os percursos: nenhuma mensagem de erro na tela, nenhuma exceção de página e
 * nenhuma resposta 4xx/5xx nas chamadas /analise (e nenhum 5xx em /api).
 */
import fs from "node:fs";
import path from "node:path";

import { expect, test, type Locator, type Page, type Response, type Route } from "@playwright/test";

const API = process.env.E2E_ANALISE_API_URL || "http://127.0.0.1:8010";
const PASTA_CAPTURAS = process.env.E2E_ANALISE_CAPTURAS
  || path.join(__dirname, "..", "test-results", "analise", "capturas");

interface Conta { email: string; senha: string }
const CONTAS: Record<"global" | "secretaria" | "coord" | "prof", Conta> = {
  global: { email: "global@analise-e2e.local", senha: process.env.E2E_ANALISE_SENHA_GLOBAL || "" },
  secretaria: { email: "secretaria@analise-e2e.local", senha: process.env.E2E_ANALISE_SENHA_SECRETARIA || "" },
  coord: { email: "coord@analise-e2e.local", senha: process.env.E2E_ANALISE_SENHA_COORD || "" },
  prof: { email: "prof@analise-e2e.local", senha: process.env.E2E_ANALISE_SENHA_PROF || "" },
};

const REDE = "Rede Fictícia do Litoral";
const ESCOLAS = {
  alfa: "EMEF Fictícia Alfa",
  beta: "EMEF Fictícia Beta",
  delta: "EMEF Fictícia Delta",
  gama: "EMEF Fictícia Gama",
  ebano: "EMEF Ébano Fictícia",
};
type ChaveEscola = keyof typeof ESCOLAS;

/** As três áreas do menu da Secretaria, na ordem (DESENHO3 §1). */
const MENU_DA_SECRETARIA = [
  { nome: "Panorama da Rede", href: "/" },
  { nome: "Escolas", href: "/rede/escolas" },
  { nome: "Avaliações externas", href: "/rede/avaliacoes-externas" },
];

/** As telas que SAÍRAM do menu da Secretaria e continuam abrindo para ela (mesma guarda). */
const ROTAS_FORA_DO_MENU = ["/rede", "/rede/visao", "/rede/acompanhamento", "/rede/plataformas", "/rede/relatorios",
                            "/rede/ranking", "/rede/analise", "/rede/avaliacoes"];

/** TODAS as telas da rede (as três áreas e as que saíram do menu): a guarda de rota manda a
 *  Coordenação e a professora para o "/" (a ficha de uma escola entra com um id real). */
const ROTAS_DA_REDE = ["/rede/escolas", "/rede/avaliacoes-externas", ...ROTAS_FORA_DO_MENU];

// --- Infra do teste ---------------------------------------------------------------------

/** Raiz real dos pacotes de fonte (resolve a junção do node_modules, se houver). */
const PASTA_FONTSOURCE = path.dirname(path.dirname(require.resolve("@fontsource/poppins/package.json")));

/** Fontes self-host entregues do disco (o Vite recusa servir node_modules fora da raiz num
 *  worktree com junção — a página cairia na fonte do sistema e as medidas mudariam). */
async function servirFontes(page: Page) {
  await page.route((url) => /\/@fontsource\/[\w-]+\/files\/[\w.-]+\.woff2?$/.test(url.pathname), (rota: Route) => {
    const caminho = decodeURIComponent(new URL(rota.request().url()).pathname);
    const relativo = caminho.slice(caminho.indexOf("@fontsource/") + "@fontsource/".length);
    return rota.fulfill({ path: path.join(PASTA_FONTSOURCE, relativo) });
  });
}

interface Chamada { metodo: string; status: number; caminho: string }

/** Vigia as chamadas à API real: todas as de /analise, as falhas e as exceções da página. */
function vigiar(page: Page) {
  const analise: Chamada[] = [];
  const problemas: string[] = [];
  const outros4xx: string[] = [];
  page.on("response", (r: Response) => {
    const u = new URL(r.url());
    if (!u.pathname.startsWith("/api/")) return;
    const c = { metodo: r.request().method(), status: r.status(), caminho: `${u.pathname}${u.search}` };
    const ehAnalise = u.pathname.includes("/analise");
    if (ehAnalise) analise.push(c);
    if (c.status >= 500 || (ehAnalise && c.status >= 400)) problemas.push(`${c.status} ${c.metodo} ${c.caminho}`);
    else if (c.status >= 400) outros4xx.push(`${c.status} ${c.metodo} ${c.caminho}`);
  });
  page.on("requestfailed", (req) => {
    const u = new URL(req.url());
    // ERR_ABORTED = a própria página cancelou (navegação ou troca de filtro): não é falha.
    if (u.pathname.startsWith("/api/") && req.failure()?.errorText !== "net::ERR_ABORTED") {
      problemas.push(`FALHOU ${req.method()} ${u.pathname}${u.search}: ${req.failure()?.errorText ?? "?"}`);
    }
  });
  page.on("pageerror", (e) => problemas.push(`EXCEÇÃO NA PÁGINA: ${e.message}`));
  return { analise, problemas, outros4xx };
}

/** Fecha o percurso: só leitura (GET), nenhuma falha; os 4xx fora da análise, informativos. */
function conferirChamadas(v: ReturnType<typeof vigiar>) {
  expect(v.analise.every((c) => c.metodo === "GET"), JSON.stringify(v.analise)).toBe(true);
  expect(v.problemas, v.problemas.join("\n")).toEqual([]);
  if (v.outros4xx.length) console.log("4xx fora da análise (informativo):", v.outros4xx);
}

async function entrar(page: Page, conta: Conta) {
  expect(conta.senha.length, "senha de teste ausente (rode pelo playwright.analise.config.ts)").toBeGreaterThan(7);
  await page.goto("/login");
  await page.getByLabel(/mail ou nome de usu/i).fill(conta.email);
  await page.getByLabel("Senha", { exact: true }).fill(conta.senha);
  await page.getByRole("button", { name: /^entrar$/i }).click();
  await page.waitForURL((u) => !u.pathname.startsWith("/login"));
  await expect(page.getByText("Abrindo o sistema...")).toHaveCount(0);
}

/** Nenhuma mensagem de erro de carregamento visível (nem "carregando" de um bloco). */
async function semErroNaTela(page: Page) {
  await expect(page.getByText(/[Nn]ão foi possível/)).toHaveCount(0);
  await expect(page.getByText(/[Cc]arregando/)).toHaveCount(0);
}

async function capturar(page: Page, nome: string) {
  fs.mkdirSync(PASTA_CAPTURAS, { recursive: true });
  await page.screenshot({ path: path.join(PASTA_CAPTURAS, `${nome}.png`), fullPage: true });
}

/** Espera a próxima resposta GET de um caminho da API (casando pelo trecho do caminho). */
function resposta(page: Page, trecho: string | RegExp) {
  return page.waitForResponse((r) => {
    if (r.request().method() !== "GET" || !r.url().startsWith(API)) return false;
    const u = new URL(r.url());
    const alvo = `${u.pathname}${u.search}`;
    return typeof trecho === "string" ? alvo.includes(trecho) : trecho.test(alvo);
  });
}

/** O catálogo da rede (`/redes/{id}/analise/indicadores`, sem o detalhe de um indicador). */
const CATALOGO = /\/analise\/indicadores$/;
/** As plataformas da rede no período (não a evolução, que é `/analise/plataformas/evolucao`). */
const PLATAFORMAS = /\/analise\/plataformas\?/;
/** O painel da rede: o cadastro de TODAS as escolas e os totais (cadastradas, ativas). */
const PAINEL = /\/redes\/\d+\/dashboard$/;
/** As escolas em destaque (o mesmo critério da vitrine pública). */
const DESTAQUES = /\/redes\/\d+\/destaques$/;

const aba = (page: Page, nome: string) => page.getByRole("tab", { name: nome, exact: true });
const menuLateral = (page: Page) => page.getByRole("navigation", { name: "Menu principal" }).filter({ visible: true });

function linhaDoAno(tabela: Locator, ano: number) {
  return tabela.locator("tbody tr").filter({ has: tabela.page().locator("th", { hasText: String(ano) }) });
}

const emOrdemDeNome = (nomes: string[]) =>
  [...nomes].sort((a, b) => a.localeCompare(b, "pt-BR", { sensitivity: "base" }));

/** "2 de 5 escolas…": os dois números na frase-conclusão, nessa ordem (a redação pode mudar). */
const contagemDe = (n: number, total: number) => new RegExp(String.raw`(^|\D)${n}\D[^.]*\D${total}(\D|$)`);

/** O número como a tela o escreve (`decimal(v, 1)`: vírgula, até uma casa). */
const decimalBR = (v: number) => v.toLocaleString("pt-BR", { maximumFractionDigits: 1 });

// --- O que a API devolve (só os campos conferidos) ----------------------------------------

interface EscolaDoPainel {
  escola_id: number; nome: string; status: string; total_alunos: number; total_turmas: number; total_professores: number;
}
interface PainelDaRede { rede_id: number; totais: { escolas: number; escolas_ativas: number }; escolas: EscolaDoPainel[] }
interface BlocoPlataforma {
  participacao_pct?: number | null; alunos_com_leitura?: number | null; alunos_medidos?: number | null;
  motivo_sem_dado?: string | null;
}
interface EscolaPlataformas {
  escola_id: number; nome: string; suprimido?: boolean; elefante: BlocoPlataforma | null; matific: BlocoPlataforma | null;
}
interface RespostaPlataformas {
  janela: { rotulo: string };
  modulos: { elefante: boolean; matific: boolean };
  rede: { alunos: number; elefante: BlocoPlataforma | null; matific: BlocoPlataforma | null };
  escolas: EscolaPlataformas[];
}
interface ListaDestaques { escolas: { escola_id: number; nome: string; valor: number }[]; fora_por_protecao: number }
interface Destaques { limite: number; k_minimo: number; leitura: ListaDestaques | null; matematica: ListaDestaques | null }
interface Diagnostico { escolas: { id: number; nome: string }[] }

/** A API mostra uso (alguém leu um livro — inclusive releitura — ou fez uma atividade, com o número à vista)? */
function houveUso(e: EscolaPlataformas): boolean {
  if (e.suprimido) return false;
  const usou = (b: BlocoPlataforma | null) => Boolean(b && !b.motivo_sem_dado
    && ((b.alunos_com_leitura ?? 0) > 0 || (b.participacao_pct ?? 0) > 0));
  return usou(e.elefante) || usou(e.matific);
}

/** A rede da conta logada, lida da API (a mesma sessão da tela): o painel e o id de cada escola
 *  do seed (as rotas com id — a ficha, a comparação — usam ids REAIS, nunca fixos). */
interface RedeDoTeste { redeId: number; painel: PainelDaRede; id: Record<ChaveEscola, number> }
async function lerRede(page: Page): Promise<RedeDoTeste> {
  const token = await page.evaluate(() => localStorage.getItem("sgpe_token"));
  const cabecalho = { Authorization: `Bearer ${token}` };
  const redes = await page.request.get(`${API}/api/v1/redes`, { headers: cabecalho });
  expect(redes.ok(), "GET /redes").toBe(true);
  const redeId = (await redes.json())[0].id as number;
  const r = await page.request.get(`${API}/api/v1/redes/${redeId}/dashboard`, { headers: cabecalho });
  expect(r.ok(), "GET /redes/{id}/dashboard").toBe(true);
  const painel = (await r.json()) as PainelDaRede;
  const id = {} as Record<ChaveEscola, number>;
  for (const [chave, nome] of Object.entries(ESCOLAS) as [ChaveEscola, string][]) {
    const e = painel.escolas.find((x) => x.nome === nome);
    expect(e, `a escola ${nome} no painel da rede`).toBeTruthy();
    id[chave] = e!.escola_id;
  }
  return { redeId, painel, id };
}

/** A escola da conta (coordenação, professora): o id real, para a ficha da rede barrada. */
async function escolaDaConta(page: Page): Promise<number> {
  const token = await page.evaluate(() => localStorage.getItem("sgpe_token"));
  const r = await page.request.get(`${API}/api/v1/auth/me`, { headers: { Authorization: `Bearer ${token}` } });
  expect(r.ok()).toBe(true);
  const id = (await r.json()).escola_id as number;
  expect(id).toBeGreaterThan(0);
  return id;
}

/** Abre os recolhidos visíveis dentro de `raiz` (o texto deles também conta): um por vez. */
async function abrirRecolhidos(page: Page, raiz = "main", limite = 25) {
  const fechado = page.locator(`${raiz} button[aria-expanded=false]`).filter({ visible: true }).first();
  for (let i = 0; i < limite && (await fechado.count()) > 0; i++) await fechado.click();
}

/**
 * Linguagem administrativa no FLUXO PRINCIPAL (DESENHO2 §1.5 e §4): nenhum termo técnico
 * (Spearman, correlação, coorte, TPS, IC 95%, proveniência) nem palavra causal (causa,
 * efeito, impacto, graças) — esses só nas Análises avançadas. Confere o texto de `main`.
 */
const TERMOS_DO_FLUXO_AVANCADO =
  /\bSpearman\b|\bcorrela[çc][ãa]o|\bcoortes?\b|\bTPS\b|\bIC 95|\bproveni[êe]ncia|\bcausa|\befeito|\bimpacto|\bgra[çc]as\b/i;
async function semTermoTecnico(page: Page, rotulo: string) {
  const texto = (await page.locator("main").innerText()).replace(/\s+/g, " ");
  const achados = [...texto.matchAll(new RegExp(TERMOS_DO_FLUXO_AVANCADO.source, "gi"))]
    .map((m) => `"${m[0]}" em "…${texto.slice(Math.max(0, (m.index ?? 0) - 60), (m.index ?? 0) + 60)}…"`);
  expect(achados, `${rotulo}: termo técnico ou causal no fluxo principal:\n${achados.join("\n")}`).toEqual([]);
}

/**
 * Contraste do TEXTO (WCAG AA): cada elemento com texto próprio, visível, dentro de
 * `seletor`, contra o fundo efetivo (o primeiro ancestral com fundo opaco). Texto pequeno
 * (< 24 px, ou < 18,66 px em negrito) pede 4,5:1; o grande, 3:1. Controle desabilitado
 * fica de fora (a WCAG o dispensa); SVG também (o traço do gráfico não é texto).
 */
async function contrasteDoTexto(page: Page, seletor: string): Promise<string[]> {
  return page.evaluate((sel) => {
    const rgb = (c: string) => (c.match(/[\d.]+/g) ?? []).map(Number);
    const lum = ([r, g, b]: number[]) => {
      const f = (v: number) => { const s = v / 255; return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4; };
      return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
    };
    const misturar = (fg: number[], bg: number[]) => {
      const a = fg[3] ?? 1;
      return [0, 1, 2].map((i) => fg[i] * a + bg[i] * (1 - a));
    };
    function fundo(el: Element | null): number[] {
      const camadas: number[][] = [];
      for (let e = el; e; e = e.parentElement) {
        const c = rgb(getComputedStyle(e).backgroundColor);
        if (c.length >= 3 && (c[3] ?? 1) > 0) {
          camadas.push(c);
          if ((c[3] ?? 1) >= 1) break;
        }
      }
      let base = [255, 255, 255];
      const html = rgb(getComputedStyle(document.documentElement).backgroundColor);
      if (html.length >= 3 && (html[3] ?? 1) > 0) base = html.slice(0, 3);
      for (const c of camadas.reverse()) base = misturar(c, base);
      return base;
    }
    const falhas: string[] = [];
    for (const raiz of document.querySelectorAll(sel)) {
      for (const el of raiz.querySelectorAll<HTMLElement>("*")) {
        if (el.closest("svg") || el.closest("[aria-hidden=true]") || el.closest(".sr-only")) continue;
        const proprio = [...el.childNodes].filter((n) => n.nodeType === 3).map((n) => n.textContent ?? "").join("").trim();
        if (!proprio) continue;
        const r = el.getBoundingClientRect();
        const est = getComputedStyle(el);
        if (r.width === 0 || r.height === 0 || est.visibility === "hidden" || Number(est.opacity) < 1) continue;
        const rotulo = el.closest("label");
        if (rotulo?.querySelector("input:disabled, select:disabled") || el.closest(":disabled")) continue;
        const cor = rgb(est.color);
        const bg = fundo(el);
        const fg = misturar(cor, bg);
        const [l1, l2] = [lum(fg), lum(bg)].sort((a, b) => b - a);
        const razao = (l1 + 0.05) / (l2 + 0.05);
        const px = parseFloat(est.fontSize);
        const negrito = Number(est.fontWeight) >= 700;
        const minimo = px >= 24 || (negrito && px >= 18.66) ? 3 : 4.5;
        if (razao < minimo) falhas.push(`${razao.toFixed(2)}:1 < ${minimo} — "${proprio.slice(0, 60)}" (${est.color} sobre rgb(${bg.map(Math.round).join(",")}))`);
      }
    }
    return falhas;
  }, seletor);
}

async function semRolagemHorizontal(page: Page, rotulo: string) {
  const m = await page.evaluate(() => ({
    sw: document.documentElement.scrollWidth,
    cw: document.documentElement.clientWidth,
    bw: document.body.scrollWidth,
  }));
  expect(m.sw, `${rotulo}: rolagem horizontal da página (scrollWidth ${m.sw} > clientWidth ${m.cw})`)
    .toBeLessThanOrEqual(m.cw);
  expect(m.bw, `${rotulo}: corpo mais largo que a janela (${m.bw} > ${m.cw})`).toBeLessThanOrEqual(m.cw);
}

/** Os elementos ficam inteiros na largura da tela (o nome da escola não sai pela lateral). */
async function inteirosNaTela(lista: Locator, rotulo: string, quantos: number) {
  const caixas = await lista.evaluateAll((els) => els.map((el) => {
    const r = el.getBoundingClientRect();
    return { texto: (el.textContent ?? "").trim(), dentro: r.left >= -0.5 && r.right <= window.innerWidth + 0.5 };
  }));
  expect(caixas, rotulo).toHaveLength(quantos);
  for (const c of caixas) expect(c.dentro, `${rotulo}: fora da tela: ${c.texto}`).toBe(true);
}

/** "Todas as escolas na edição mais recente…" (Avaliações externas) carrega ao chegar perto da
 *  tela: rola até a seção e espera a tabela. */
async function rolarAteTodasAsEscolas(page: Page) {
  const secao = page.getByTestId("todas-as-escolas");
  await expect(secao).toBeVisible();
  await secao.scrollIntoViewIfNeeded();
  await expect(secao.getByTestId("tabela-comparacao-escolas")).toBeVisible({ timeout: 30_000 });
}

// --- As telas -------------------------------------------------------------------------------

/** Uma tela da rede e o que mostra que ela terminou de ler (o resto: nenhum "Carregando"). */
interface Vista { nome: string; caminho: string; pronto: (p: Page) => Locator; preparar?: (p: Page) => Promise<void> }

const PANORAMA: Vista = { nome: "panorama", caminho: "/", pronto: (p) => p.getByTestId("lista-escolas") };
const ESCOLAS_LISTA: Vista = {
  nome: "escolas", caminho: "/rede/escolas", pronto: (p) => p.getByTestId("tabela-escolas-periodo"),
};
const AVALIACOES: Vista = {
  nome: "avaliacoes", caminho: "/rede/avaliacoes-externas", pronto: (p) => p.getByTestId("indicador-cartao-ica"),
};
const AVALIACOES_ICA: Vista = {
  nome: "avaliacoes-ica", caminho: "/rede/avaliacoes-externas?indicador=ica", pronto: (p) => p.getByTestId("indicador-tabela"),
};
const AVALIACOES_SARESP_ESCOLAS: Vista = {
  nome: "avaliacoes-saresp-escolas", caminho: "/rede/avaliacoes-externas?indicador=saresp&visao=escolas&edicao=2025",
  pronto: (p) => p.getByTestId("indicador-escolas"),
};
const AVALIACOES_TODAS_AS_ESCOLAS: Vista = {
  nome: "avaliacoes-todas-as-escolas", caminho: "/rede/avaliacoes-externas", preparar: rolarAteTodasAsEscolas,
  pronto: (p) => p.getByTestId("tabela-comparacao-escolas"),
};
/** O detalhe do uso das plataformas (filha do Panorama: "Ver o uso em detalhe"). */
const PLATAFORMAS_DETALHE: Vista = {
  nome: "plataformas", caminho: "/rede/plataformas", pronto: (p) => p.getByTestId("tabela-evolucao-rede"),
};
const comparar = (r: RedeDoTeste): Vista => ({
  nome: "escolas-comparar", caminho: `/rede/escolas?comparar=${r.id.alfa},${r.id.beta},${r.id.gama}`,
  pronto: (p) => p.getByTestId("comparacao-avaliacoes"),
});
const ficha = (r: RedeDoTeste, chave: ChaveEscola): Vista => ({
  nome: `ficha-${chave}`, caminho: `/rede/escolas/${r.id[chave]}`, pronto: (p) => p.getByTestId("ficha-situacao-uso"),
});

/** As três áreas da Secretaria e o que mora dentro delas (comparação, ficha, detalhes). */
const telasPrincipais = (r: RedeDoTeste): Vista[] => [
  PANORAMA, ESCOLAS_LISTA, comparar(r), ficha(r, "alfa"), ficha(r, "gama"),
  AVALIACOES, AVALIACOES_ICA, AVALIACOES_SARESP_ESCOLAS, AVALIACOES_TODAS_AS_ESCOLAS, PLATAFORMAS_DETALHE,
];
/** Telas que saíram do menu e continuam abrindo (a régua da página vale nelas também). */
const TELAS_FORA_DO_MENU: Vista[] = [
  { nome: "acompanhamento", caminho: "/rede/acompanhamento", pronto: (p) => p.getByTestId("lista-acompanhamento") },
  { nome: "relatorios", caminho: "/rede/relatorios", pronto: (p) => p.getByTestId("relatorio-acompanhamento") },
];
/** As três abas das Análises avançadas (a área técnica: fora do menu da Secretaria, no do global). */
const ABAS_AVANCADAS: Vista[] = [
  { nome: "avancadas-diagnostico", caminho: "/rede/analise", pronto: (p) => p.getByTestId("tabela-diagnostico") },
  { nome: "avancadas-relacao", caminho: "/rede/analise?ver=relacao", pronto: (p) => p.getByTestId("relacao-lado-a-lado") },
  { nome: "avancadas-escola", caminho: "/rede/analise?ver=escola&escola=1", pronto: (p) => p.getByTestId("tabela-series-plataformas") },
];

/**
 * Abre a tela como na 1ª visita: com o contexto do topo em "Toda a Rede Municipal" (o seletor
 * persiste no localStorage e as telas de escola leem dele).
 */
async function abrirVista(page: Page, vista: Vista) {
  await page.evaluate(() => localStorage.removeItem("sgpe_escola"));
  await page.goto(vista.caminho);
  if (vista.preparar) await vista.preparar(page);
  await expect(vista.pronto(page)).toBeVisible();
  await page.waitForLoadState("networkidle");
  await semErroNaTela(page);
}

test.beforeEach(async ({ page }) => {
  await servirFontes(page);
});

// --- Secretaria: as três áreas --------------------------------------------------------------

test.describe("Secretaria — as três áreas", () => {
  test("Panorama: cadastradas e ativas como no painel, todas as escolas com o uso, destaques iguais à API com o critério, a vitrine", async ({ page }) => {
    test.setTimeout(180_000);
    const v = vigiar(page);
    await entrar(page, CONTAS.secretaria);
    const rede = await lerRede(page);

    const painelResp = resposta(page, PAINEL);
    const platResp = resposta(page, PLATAFORMAS);
    const destResp = resposta(page, DESTAQUES);
    await page.evaluate(() => localStorage.removeItem("sgpe_escola"));
    await page.goto("/");
    const [rPainel, rPlat, rDest] = [await painelResp, await platResp, await destResp];
    for (const r of [rPainel, rPlat, rDest]) expect(r.status(), r.url()).toBe(200);
    expect(rPlat.url(), "o uso é o do ano letivo").toContain("periodo=ano_letivo");
    const painel = (await rPainel.json()) as PainelDaRede;
    const plat = (await rPlat.json()) as RespostaPlataformas;
    const dest = (await rDest.json()) as Destaques;
    await expect(page.getByRole("heading", { level: 1, name: "Panorama da Rede" })).toBeVisible();
    await expect(page.getByTestId("secretaria-rede-nome")).toHaveText(REDE);

    // (1) A rede no Constela: cadastradas e ativas = o painel; cadastrada ≠ ativa ≠ com uso.
    const valor = (id: string) => page.getByTestId(id).locator("p").nth(1);
    await expect(valor("numero-cadastradas")).toHaveText(String(painel.totais.escolas));
    await expect(valor("numero-ativas")).toHaveText(String(painel.totais.escolas_ativas));
    await expect(page.getByTestId("numero-ativas")).toContainText(/não indica uso/i);
    await expect(page.getByTestId("conclusao-rede"))
      .toContainText(contagemDe(painel.totais.escolas, painel.totais.escolas_ativas));
    for (const id of ["numero-cadastradas", "numero-ativas", "numero-com-uso", "numero-demais"]) {
      await expect(page.getByTestId(id)).toContainText("O que mede:");
      await expect(page.getByTestId(id)).toContainText("Calculado pelo Constela");
    }

    // (2) Participação no ano letivo: a da rede na API, com o período e o selo Plataforma.
    for (const p of ["elefante", "matific"] as const) {
      if (!plat.modulos[p]) continue;
      const cartao = page.getByTestId(`participacao-${p}`);
      await expect(cartao).toContainText(plat.janela.rotulo);
      await expect(page.getByTestId(`participacao-${p}-quando`)).toContainText("Plataforma");
      const pct = plat.rede[p]?.participacao_pct;
      if (pct != null) await expect(page.getByTestId(`participacao-${p}-pct`)).toContainText(`${decimalBR(pct)}%`);
    }
    await expect(page.getByTestId("participacao-ano-letivo").getByRole("link", { name: /Ver o uso em detalhe/ }))
      .toHaveAttribute("href", "/rede/plataformas");

    // (3) Todas as escolas: TODAS as do painel (inclusive a Gama, sem avaliação externa), em
    // ordem alfabética, cada uma com o cadastro do painel e o link para a ficha.
    const lista = page.getByTestId("lista-escolas");
    const linhas = lista.locator(":scope > li");
    await expect(linhas).toHaveCount(painel.escolas.length);
    expect(painel.escolas.length).toBe(painel.totais.escolas);
    const nomes = await lista.locator(":scope > li > p a").allInnerTexts();
    expect(nomes).toEqual(emOrdemDeNome(painel.escolas.map((e) => e.nome)));
    expect(nomes).toContain(ESCOLAS.gama);
    for (const e of painel.escolas) {
      const linha = page.getByTestId(`escola-${e.escola_id}`);
      await expect(linha.getByRole("link", { name: e.nome, exact: true })).toHaveAttribute("href", `/rede/escolas/${e.escola_id}`);
      await expect(linha.getByTestId("cadastro")).toHaveText(e.status === "ativa" ? "Ativa" : "Inativa");
      await expect(linha.getByTestId("situacao-geral")).not.toBeEmpty();
    }
    // O uso vem das COLETAS (a API das plataformas no ano letivo), nunca do painel: quem a API
    // mostra usando está "com uso"; o número "com uso" é o das escolas assim na lista.
    for (const e of plat.escolas.filter(houveUso)) {
      await expect(page.getByTestId(`escola-${e.escola_id}`), `${e.nome} tem uso na API`).toHaveAttribute("data-situacao", "com_uso");
    }
    const comUso = await lista.locator(':scope > li[data-situacao="com_uso"]').count();
    expect(comUso, "o seed tem escolas com uso").toBeGreaterThan(0);
    await expect(valor("numero-com-uso")).toHaveText(String(comUso));
    // Ausência ≠ zero: a Beta não tem coleta do Elefante — "sem dado", nunca "sem uso" nem 0%.
    const elefanteBeta = page.getByTestId(`escola-${rede.id.beta}`).getByTestId("uso-elefante");
    await expect(elefanteBeta.locator("[data-estado]")).toHaveAttribute("data-estado", "sem_dado");
    await expect(elefanteBeta).not.toContainText(/(^|\D)0(,0)?%/);
    // O filtro por situação: as contagens somam o total e filtram a lista.
    const filtro = page.getByTestId("filtro-situacao");
    const botaoFiltro = (rotulo: RegExp) => filtro.getByRole("button", { name: rotulo });
    const quantas = async (rotulo: RegExp) => Number((await botaoFiltro(rotulo).innerText()).match(/\((\d+)\)/)?.[1]);
    const [todas, com, sem, semDado] = [await quantas(/^Todas/), await quantas(/^Com uso/), await quantas(/^Sem uso/),
                                       await quantas(/^Sem dado/)];
    expect(todas).toBe(painel.escolas.length);
    expect(com).toBe(comUso);
    expect(com + sem + semDado).toBe(todas);
    await botaoFiltro(/^Com uso/).click();
    await expect(botaoFiltro(/^Com uso/)).toHaveAttribute("aria-pressed", "true");
    await expect(linhas).toHaveCount(com);
    await botaoFiltro(/^Todas/).click();
    await expect(linhas).toHaveCount(todas);
    await expect(page.getByTestId("todas-as-escolas")).toContainText("não é ranking");

    // (4) Escolas em destaque: as MESMAS da API, na mesma ordem, com o critério escrito ANTES.
    const destaque = page.getByTestId("escolas-em-destaque");
    const criterio = page.getByTestId("criterio-destaques");
    await expect(criterio).toContainText(/vitrine/);
    await expect(criterio).toContainText(String(dest.k_minimo));
    await expect(criterio).toContainText(String(dest.limite));
    await expect(destaque).toContainText("Calculado pelo Constela");
    expect((dest.leitura?.escolas.length ?? 0) + (dest.matematica?.escolas.length ?? 0), "o seed tem destaques")
      .toBeGreaterThan(0);
    for (const [materia, testId] of [["leitura", "destaques-leitura"], ["matematica", "destaques-matematica"]] as const) {
      const listaApi = dest[materia];
      const bloco = page.getByTestId(testId);
      if (listaApi == null) {
        await expect(bloco, `${materia} não contratada: sem lista`).toHaveCount(0);
        continue;
      }
      expect((await criterio.boundingBox())!.y, "o critério vem antes das listas").toBeLessThan((await bloco.boundingBox())!.y);
      const itens = bloco.locator("ol > li");
      await expect(itens).toHaveCount(listaApi.escolas.length);
      for (const [i, e] of listaApi.escolas.entries()) {
        const link = itens.nth(i).getByRole("link");
        await expect(link).toHaveText(e.nome);
        await expect(link).toHaveAttribute("href", `/rede/escolas/${e.escola_id}`);
        await expect(itens.nth(i)).toContainText(decimalBR(e.valor));
      }
      if (listaApi.escolas.length === 0) await expect(bloco.getByTestId(`${testId}-vazio`)).toBeVisible();
      if (listaApi.fora_por_protecao > 0) {
        await expect(bloco.getByTestId(`${testId}-fora`)).toContainText(String(listaApi.fora_por_protecao));
      }
    }
    await expect(destaque.getByRole("link", { name: /Ranking da Rede/ })).toHaveAttribute("href", "/rede/ranking");

    // (5) Reconhecimento público: a vitrine da rede, no Panorama (ligar ou abrir).
    const reconhecimento = page.getByTestId("reconhecimento-publico");
    await expect(reconhecimento.getByRole("heading", { name: /Vitrine pública/ })).toBeVisible();
    await expect(reconhecimento.getByRole("button", { name: "Ligar vitrine pública" })
      .or(reconhecimento.getByRole("link", { name: /Abrir vitrine/ }))).toBeVisible();

    // (6) As avaliações externas NÃO são o principal: só o link do rodapé, com a frase dos
    // períodos diferentes. O Panorama não lê o catálogo nem o diagnóstico, e não tem tabela.
    const rodape = page.getByTestId("rodape-panorama");
    await expect(rodape.getByRole("link", { name: "Avaliações externas" })).toHaveAttribute("href", "/rede/avaliacoes-externas");
    await expect(rodape.getByTestId("frase-separacao")).toContainText(/não se comparam/);
    expect(v.analise.filter((c) => /\/analise\/(diagnostico|indicadores)/.test(c.caminho)), "leitura pesada no Panorama")
      .toEqual([]);
    await expect(page.locator("main table")).toHaveCount(0);

    // (7) Metas da rede: recolhidas; abrir lê as metas.
    const botaoMetas = page.getByTestId("metas-da-rede").getByRole("button", { name: /Metas da rede/ });
    await expect(botaoMetas).toHaveAttribute("aria-expanded", "false");
    const metas = resposta(page, /\/redes\/\d+\/metas$/);
    await botaoMetas.click();
    expect((await metas).status()).toBe(200);
    await expect(botaoMetas).toHaveAttribute("aria-expanded", "true");
    await semErroNaTela(page);

    await abrirRecolhidos(page);
    await semTermoTecnico(page, "Panorama da Rede");
    await expect(page.locator("main")).not.toContainText("Criança Fictícia");
    await capturar(page, "secretaria-1-panorama");

    // A situação de uso é a MESMA na ficha (a mesma função); o nome leva até ela.
    const linhaAlfa = page.getByTestId(`escola-${rede.id.alfa}`);
    const geralAlfa = (await linhaAlfa.getByTestId("situacao-geral").innerText()).trim();
    await linhaAlfa.getByRole("link", { name: ESCOLAS.alfa, exact: true }).click();
    await page.waitForURL((u) => u.pathname === `/rede/escolas/${rede.id.alfa}`);
    await expect(page.getByRole("heading", { level: 1, name: ESCOLAS.alfa })).toBeVisible();
    await expect(page.getByTestId("ficha-situacao-uso")).toContainText(geralAlfa);
    conferirChamadas(v);
  });

  test("Escolas: todas como na API, ausência ≠ zero; comparação lado a lado (avaliações à parte); a ficha volta à lista", async ({ page }) => {
    test.setTimeout(180_000);
    const v = vigiar(page);
    await entrar(page, CONTAS.secretaria);
    const rede = await lerRede(page);
    const plataformas = resposta(page, PLATAFORMAS);
    await page.goto("/rede/escolas");
    const rPlat = await plataformas;
    expect(rPlat.status()).toBe(200);
    expect(rPlat.url(), "a lista abre no ano letivo").toContain("periodo=ano_letivo");
    const plat = (await rPlat.json()) as RespostaPlataformas;
    await expect(page.getByRole("heading", { level: 1, name: "Escolas" })).toBeVisible();
    await expect(page.getByTestId("secretaria-rede-nome")).toHaveText(REDE);
    await expect(page.getByRole("tab"), "sem abas: as avaliações de todas as escolas moram na área 3").toHaveCount(0);
    await expect(page.getByTestId("como-comparar")).toContainText("não é ranking");

    // Todas as escolas da API, em ordem alfabética; números da API; o nome leva à ficha.
    const tabela = page.getByTestId("tabela-escolas-periodo");
    const nomes = await tabela.locator("tbody th").allInnerTexts();
    expect(nomes).toHaveLength(5);
    expect(nomes).toEqual(emOrdemDeNome(plat.escolas.map((e) => e.nome)));
    const linha = (id: number) => page.getByTestId(`escola-periodo-${id}`);
    for (const e of plat.escolas) {
      await expect(linha(e.escola_id).getByRole("link", { name: e.nome, exact: true }))
        .toHaveAttribute("href", new RegExp(`^/rede/escolas/${e.escola_id}(\\?|$)`));
      if (e.suprimido) continue;
      for (const p of ["elefante", "matific"] as const) {
        const pct = e[p]?.participacao_pct;
        if (pct != null) await expect(linha(e.escola_id), `${e.nome} ${p}`).toContainText(`${decimalBR(pct)}%`);
      }
    }
    // A Beta não tem coleta do Elefante: diz isso (nunca 0%); a Ébano tem poucos alunos.
    await expect(linha(rede.id.beta)).toContainText(/sem coleta|nenhuma coleta/i);
    await expect(linha(rede.id.beta)).not.toContainText(/(^|\D)0(,0)?%/);
    await expect(linha(rede.id.ebano)).toContainText("para proteger as crianças");
    await expect(page.getByTestId("legenda-escolas-periodo")).toContainText("não é ranking");
    await expect(page.getByTestId("legenda-escolas-periodo")).toContainText(/não é zero/);
    await expect(page.getByTestId("natureza-plataformas")).toContainText("Plataforma");
    await expect(page.getByTestId("link-ranking").getByRole("link", { name: /Ranking da Rede/ }))
      .toHaveAttribute("href", "/rede/ranking");
    await expect(page.getByTestId("link-avaliacoes").getByRole("link", { name: /Avaliações externas/ }))
      .toHaveAttribute("href", "/rede/avaliacoes-externas");

    // ---- Comparar pela coluna "Comparar": com 1 marcada ainda não há lado a lado ------------
    const comparando = () => new URL(page.url()).searchParams.get("comparar");
    await page.getByRole("checkbox", { name: `Comparar ${ESCOLAS.gama}` }).check();
    await expect.poll(comparando).toBe(String(rede.id.gama));
    await expect(page.getByTestId("comparacao-lado-a-lado")).toHaveCount(0);
    const analiseAlfa = resposta(page, `/escolas/${rede.id.alfa}/analise?`);
    const analiseGama = resposta(page, `/escolas/${rede.id.gama}/analise?`);
    await page.getByRole("checkbox", { name: `Comparar ${ESCOLAS.alfa}` }).check();
    await expect.poll(comparando).toBe(`${rede.id.gama},${rede.id.alfa}`);
    for (const r of [await analiseAlfa, await analiseGama]) expect(r.status(), r.url()).toBe(200);
    const lado = page.getByTestId("comparacao-lado-a-lado");
    await expect(lado).toBeVisible();
    await expect(page.getByTestId("resumo-comparar")).toContainText(/\b2 escolas/);
    // Uma coluna por escola, em ordem alfabética (não é ranking), o nome levando à ficha.
    const cabecalho = page.getByTestId("comparacao-plataformas").locator("thead th a");
    await expect(cabecalho).toHaveText(emOrdemDeNome([ESCOLAS.alfa, ESCOLAS.gama]));
    await expect(cabecalho.first()).toHaveAttribute("href", new RegExp(`^/rede/escolas/${rede.id.alfa}(\\?|$)`));
    const pAlfa = plat.escolas.find((e) => e.escola_id === rede.id.alfa)!;
    for (const p of ["elefante", "matific"] as const) {
      const pct = pAlfa[p]?.participacao_pct;
      if (pct != null) await expect(page.getByTestId("comparacao-plataformas")).toContainText(`${decimalBR(pct)}%`);
    }
    // Plataformas e avaliações separadas pela frase dos períodos; as avaliações com a edição e,
    // sem número, o porquê por extenso (a Gama: sem INEP) — nunca 0.
    await expect(lado.getByTestId("frase-separacao")).toContainText(/não se comparam/);
    const avaliacoes = page.getByTestId("comparacao-avaliacoes");
    const sarespAlfa = avaliacoes.locator("tbody tr").filter({ hasText: "210,3" });
    await expect(sarespAlfa).toHaveCount(1);
    await expect(sarespAlfa.locator("td").nth(0)).toContainText("2025");
    await expect(sarespAlfa.locator("td").nth(1)).toContainText("sem código INEP");
    await expect(sarespAlfa.locator("td").nth(1)).not.toContainText(/\d/);

    // ---- Pela URL (?comparar=): a mesma comparação; a Beta com a média instável em língua simples
    const analiseBeta = resposta(page, `/escolas/${rede.id.beta}/analise?`);
    await page.goto(`/rede/escolas?comparar=${rede.id.beta},${rede.id.alfa}`);
    expect((await analiseBeta).status()).toBe(200);
    await expect(cabecalho).toHaveText(emOrdemDeNome([ESCOLAS.alfa, ESCOLAS.beta]));
    const sarespBeta = avaliacoes.locator("tbody tr").filter({ hasText: "210,3" }).locator("td").nth(1);
    await expect(sarespBeta).toContainText("190,7");
    await expect(sarespBeta).toContainText(/instáve/);
    await expect(avaliacoes).not.toContainText("TPS");
    await semErroNaTela(page);
    await abrirRecolhidos(page);
    await semTermoTecnico(page, "Escolas (lista e comparação)");
    await expect(page.locator("main")).not.toContainText("Criança Fictícia");
    await capturar(page, "secretaria-2-escolas-comparar");

    // ---- A ficha (pelo nome na tabela) e a volta à lista com a MESMA consulta ---------------
    await linha(rede.id.alfa).getByRole("link", { name: ESCOLAS.alfa, exact: true }).click();
    await page.waitForURL((u) => u.pathname === `/rede/escolas/${rede.id.alfa}`);
    await expect(page.getByRole("heading", { level: 1, name: ESCOLAS.alfa })).toBeVisible();
    await page.getByTestId("voltar-escolas").click();
    await page.waitForURL((u) => u.pathname === "/rede/escolas");
    await expect.poll(comparando).toBe(`${rede.id.beta},${rede.id.alfa}`);
    await expect(lado).toBeVisible();
    // "Tirar" uma escola: com uma só, a comparação sai.
    await page.getByRole("button", { name: `Tirar ${ESCOLAS.beta} da comparação` }).first().click();
    await expect.poll(comparando).toBe(String(rede.id.alfa));
    await expect(lado).toHaveCount(0);
    conferirChamadas(v);
  });

  test("Ficha da escola: cadastro e uso como no painel, Elefante e Matific da API, evolução só dela, avaliações externas ou o porquê", async ({ page }) => {
    test.setTimeout(180_000);
    const v = vigiar(page);
    await entrar(page, CONTAS.secretaria);
    const rede = await lerRede(page);
    const alfa = rede.painel.escolas.find((e) => e.escola_id === rede.id.alfa)!;

    const plataformas = resposta(page, PLATAFORMAS);
    const analise = resposta(page, `/escolas/${rede.id.alfa}/analise?`);
    const evolucao = resposta(page, /\/analise\/plataformas\/evolucao\?/);
    await page.goto(`/rede/escolas/${rede.id.alfa}`);
    const [rPlat, rAnalise, rEvo] = [await plataformas, await analise, await evolucao];
    for (const r of [rPlat, rAnalise, rEvo]) expect(r.status(), r.url()).toBe(200);
    expect(rEvo.url(), "a evolução é só da escola").toContain(`escola_id=${rede.id.alfa}`);
    const plat = (await rPlat.json()) as RespostaPlataformas;
    const daEscola = plat.escolas.find((e) => e.escola_id === rede.id.alfa)!;
    await expect(page.getByRole("heading", { level: 1, name: ESCOLAS.alfa })).toBeVisible();
    await expect(page.getByTestId("secretaria-rede-nome")).toHaveText(REDE);
    await expect(page.getByTestId("voltar-escolas")).toHaveAttribute("href", "/rede/escolas");

    // Cadastro: o cartão do painel da rede (situação do cadastro ≠ uso).
    const cadastro = page.getByTestId("ficha-cadastro");
    const campo = (rotulo: string) => cadastro.locator("div", { has: page.locator(`dt:text-is("${rotulo}")`) }).locator("dd").first();
    await expect(campo("Situação do cadastro")).toHaveText(alfa.status === "ativa" ? "Ativa" : "Inativa");
    await expect(cadastro).toContainText(/não indica uso/i);
    await expect(campo("Alunos no ano letivo")).toHaveText(alfa.total_alunos.toLocaleString("pt-BR"));
    await expect(campo("Turmas")).toHaveText(alfa.total_turmas.toLocaleString("pt-BR"));
    await expect(campo("Professores")).toHaveText(alfa.total_professores.toLocaleString("pt-BR"));

    // Uso no ano letivo: a situação geral e a de cada plataforma contratada.
    const uso = page.getByTestId("ficha-situacao-uso");
    if (houveUso(daEscola)) await expect(uso).toContainText("Com uso no ano letivo");
    for (const p of ["elefante", "matific"] as const) {
      await expect(page.getByTestId(`ficha-uso-${p}`)).toHaveCount(plat.modulos[p] ? 1 : 0);
    }
    await expect(uso).toContainText("Plataforma");

    // Elefante e Matific da escola, no período: o X de Y com o denominador da API.
    const fichaPlat = page.getByTestId("ficha-plataformas");
    await expect(page.getByTestId("ficha-recorte-plataformas")).toContainText(plat.janela.rotulo);
    const ele = daEscola.elefante;
    if (ele?.alunos_com_leitura != null && ele.alunos_medidos != null) {
      await expect(fichaPlat.getByTestId("plataforma-elefante"))
        .toContainText(`${ele.alunos_com_leitura} de ${ele.alunos_medidos} alunos com conta leram no período`);
    }
    if (daEscola.matific?.alunos_medidos != null) {
      await expect(fichaPlat.getByTestId("plataforma-matific"))
        .toContainText(`sobre ${daEscola.matific.alunos_medidos} alunos com dado no período`);
    }
    await expect(fichaPlat).toContainText("Plataforma");

    // A evolução no ano letivo: SÓ a escola (sem a tabela da rede).
    await expect(page.getByTestId("evolucao-escola")).toBeVisible();
    await expect(page.getByTestId("tabela-evolucao-rede")).toHaveCount(0);

    // Avaliações externas DA escola, em língua simples; o ICA (só da rede) diz o porquê.
    await expect(page.getByTestId("analise-escola-indicador-saresp")).toContainText("210,3");
    await expect(page.getByTestId("analise-escola-indisponiveis")).toContainText("ICA");
    await expect(page.getByTestId("frase-separacao")).toContainText(/não se comparam/);
    await expect(page.getByRole("link", { name: /Ver as avaliações externas de toda a rede/ }))
      .toHaveAttribute("href", "/rede/avaliacoes-externas");
    await semErroNaTela(page);
    await abrirRecolhidos(page);
    await semTermoTecnico(page, "Ficha da escola (Alfa)");
    await expect(page.locator("main")).not.toContainText("Criança Fictícia");
    await capturar(page, "secretaria-3-ficha-alfa");

    // "Ver as turmas da escola": a escola vai para o contexto e a Visão da Escola volta à ficha.
    await page.getByTestId("ver-turmas").click();
    await page.waitForURL((u) => u.pathname === "/escola");
    const topo = page.getByLabel("Contexto de visualização");
    await expect.poll(() => topo.evaluate((s: HTMLSelectElement) => s.selectedOptions[0]?.textContent)).toBe(ESCOLAS.alfa);
    await page.getByRole("link", { name: /Voltar para a ficha da escola/ }).click();
    await page.waitForURL((u) => u.pathname === `/rede/escolas/${rede.id.alfa}`);
    await expect(page.getByRole("heading", { level: 1, name: ESCOLAS.alfa })).toBeVisible();

    // A Gama (sem INEP): sem resultado oficial, a ficha diz por quê — nenhum número inventado.
    const analiseGama = resposta(page, `/escolas/${rede.id.gama}/analise?`);
    await page.goto(`/rede/escolas/${rede.id.gama}`);
    expect((await analiseGama).status()).toBe(200);
    await expect(page.getByRole("heading", { level: 1, name: ESCOLAS.gama })).toBeVisible();
    await expect(page.getByTestId("analise-escola-sem-inep")).toContainText(/sem código INEP/);
    await expect(page.getByTestId("ficha-situacao-uso")).toBeVisible();
    await semErroNaTela(page);
    await abrirRecolhidos(page);
    await semTermoTecnico(page, "Ficha da escola (Gama)");

    // Escola que não é da rede (ou não existe): a mensagem, sem chamar a API da escola.
    await page.goto("/rede/escolas/999999");
    await expect(page.getByTestId("ficha-nao-encontrada")).toBeVisible();
    await expect(page.getByRole("heading", { level: 1, name: "Escola não encontrada" })).toBeVisible();
    await page.waitForLoadState("networkidle");
    expect(v.analise.filter((c) => c.caminho.includes("/escolas/999999/"))).toEqual([]);
    await page.getByRole("link", { name: "Ver todas as escolas" }).click();
    await page.waitForURL((u) => u.pathname === "/rede/escolas");
    conferirChamadas(v);
  });

  test("Avaliações externas: cartões com disponibilidade; ICA, SARESP e Ideb no detalhe; todas as escolas ao pedir/rolar", async ({ page }) => {
    test.setTimeout(240_000);
    const v = vigiar(page);
    await entrar(page, CONTAS.secretaria);
    const rede = await lerRede(page);
    const catalogo = resposta(page, CATALOGO);
    const diagnostico = resposta(page, "/analise/diagnostico?");
    await page.goto("/rede/avaliacoes-externas");
    const respCatalogo = await catalogo;
    expect(respCatalogo.status()).toBe(200);
    const cat = await respCatalogo.json();
    await expect(page.getByRole("heading", { level: 1, name: "Avaliações externas" })).toBeVisible();
    await expect(page.getByTestId("secretaria-rede-nome")).toHaveText(REDE);

    // Um cartão por indicador do catálogo, cada um dizendo o que mede, com o selo Oficial e a
    // disponibilidade (a edição mais recente importada, ou "nenhuma").
    for (const ind of cat.indicadores as { chave: string; edicoes: number[]; edicao_mais_recente: number | null }[]) {
      const cartao = page.getByTestId(`indicador-cartao-${ind.chave}`);
      await expect(cartao).toContainText("O que mede:");
      await expect(cartao).toContainText("Oficial");
      const ultima = ind.edicao_mais_recente ?? (ind.edicoes.length ? Math.max(...ind.edicoes) : null);
      await expect(page.getByTestId(`indicador-disponibilidade-${ind.chave}`))
        .toContainText(ultima != null ? String(ultima) : /nenhuma edição/);
    }
    await expect(page.getByTestId("indicador-conclusao-ica")).toContainText("58%");
    await expect(page.getByTestId("indicador-conclusao-ica")).toContainText("60%");
    // A estimativa fica FORA dos cartões oficiais, rotulada; o número do 1 clique (sem
    // registro oficial) também, num aviso PRÓPRIO — não é estimativa.
    const cartoes = page.getByTestId("indicadores-disponiveis");
    await expect(page.getByTestId("estimativas-fora")).toContainText("Estimativa Constela");
    await expect(cartoes).not.toContainText("Estimativa");
    expect(cat.sem_registro_oficial?.length ?? 0).toBeGreaterThan(0);
    await expect(page.getByTestId("sem-registro-fora")).toContainText("sem o registro do arquivo oficial");
    await expect(page.getByTestId("estimativas-fora")).not.toContainText("sem o registro");
    await expect(cartoes).not.toContainText("7,7");
    // Fonte só em "Detalhes e fontes" (fechado): nada de arquivo/fonte nos cartões.
    await expect(page.getByText(/Fonte fictícia de teste/)).toHaveCount(0);
    const detalhes = page.getByTestId("detalhes-fontes-destaques");
    await detalhes.getByRole("button").click();
    await expect(detalhes.getByTestId("detalhe-fonte").first()).toBeVisible();
    await expect(detalhes).toContainText("Fonte fictícia de teste");
    // Os avisos sobre os dados oficiais: recolhidos, com a contagem; o de cadastro cita a Gama. O
    // aviso de "metodologia" (assunto das Análises avançadas) não entra nesta tela.
    const avisosDaTela = (cat.alertas as { tipo: string }[]).filter((a) => a.tipo !== "metodologia");
    const avisos = page.getByTestId("avisos-dados-oficiais");
    const abrirAvisos = avisos.getByRole("button", { name: /Avisos sobre os dados oficiais/ });
    await expect(abrirAvisos).toContainText(`(${avisosDaTela.length})`);
    await expect(page.getByTestId("alertas-analise")).toHaveCount(0);
    await abrirAvisos.click();
    const alertas = page.getByTestId("alertas-analise");
    await expect(alertas.locator(":scope > li")).toHaveCount(avisosDaTela.length);
    await expect(alertas).toContainText("Cadastro");
    await expect(alertas).toContainText(ESCOLAS.gama);
    // A fonte de cada número (arquivos oficiais); nenhum link para Análises avançadas nem Relatórios.
    await expect(page.getByTestId("links-avaliacoes").getByRole("link", { name: /Arquivos oficiais de cada número/ }))
      .toHaveAttribute("href", "/rede/avaliacoes");
    await expect(page.locator('main a[href^="/rede/analise"], main a[href^="/rede/relatorios"]')).toHaveCount(0);
    // Sem escolha, o detalhe espera; o seletor antigo (os rádios "(ICA)") não existe mais.
    await expect(page.getByTestId("detalhe-vazio")).toBeVisible();
    await expect(page.getByRole("radio", { name: /\(ICA\)/ })).toHaveCount(0);
    await semErroNaTela(page);

    // ---- Todas as escolas na edição mais recente: carrega ao chegar perto ou ao pedir ---------
    const secao = page.getByTestId("todas-as-escolas");
    await expect(secao.getByRole("heading", { level: 2 })).toBeVisible();
    const aCarregar = secao.getByTestId("escolas-a-carregar");
    if (await aCarregar.isVisible()) await aCarregar.getByRole("button", { name: /Mostrar as escolas/ }).click();
    const respDiag = await diagnostico;
    expect(respDiag.status()).toBe(200);
    const diag = (await respDiag.json()) as Diagnostico;
    const comparacao = secao.getByTestId("tabela-comparacao-escolas");
    await expect(comparacao).toBeVisible();
    const nomesAval = await comparacao.locator("tbody th").allInnerTexts();
    expect(nomesAval).toHaveLength(5);
    expect(nomesAval).toEqual(emOrdemDeNome(diag.escolas.map((e) => e.nome)));
    const linhaAval = (nome: string) => comparacao.locator("tbody tr").filter({ hasText: nome });
    // Sem número oficial: o porquê por extenso em cada célula, nenhum número.
    await expect(linhaAval(ESCOLAS.delta)).toContainText("sem resultado oficial");
    await expect(linhaAval(ESCOLAS.delta)).not.toContainText(/\d/);
    await expect(linhaAval(ESCOLAS.gama)).toContainText("sem código INEP");
    await expect(linhaAval(ESCOLAS.gama)).not.toContainText(/\d/);
    await expect(linhaAval(ESCOLAS.beta)).toContainText("média instável");
    await expect(linhaAval(ESCOLAS.beta)).not.toContainText("TPS");
    await expect(linhaAval(ESCOLAS.alfa)).toContainText("210,3");
    await expect(linhaAval(ESCOLAS.alfa).getByRole("link", { name: ESCOLAS.alfa, exact: true }))
      .toHaveAttribute("href", `/rede/escolas/${rede.id.alfa}`);
    await expect(secao.getByTestId("legenda-comparacao")).toContainText("não é ranking");
    await semErroNaTela(page);
    await abrirRecolhidos(page);
    await semTermoTecnico(page, "Avaliações externas (cartões e todas as escolas)");
    await capturar(page, "secretaria-4-avaliacoes-todas-as-escolas");

    // ---- Detalhe do ICA (série da rede; não existe por escola) ------------------------------
    let detalhe = resposta(page, "/analise/indicadores/ica?");
    await page.getByRole("button", { name: "Ver série histórica e escolas — ICA" }).click();
    expect((await detalhe).status()).toBe(200);
    await expect(page).toHaveURL(/[?&]indicador=ica/);
    await expect(page.getByRole("heading", { name: "Série histórica e escolas — ICA" })).toBeVisible();
    let tabela = page.getByTestId("indicador-tabela");
    await expect(linhaDoAno(tabela, 2025)).toContainText("58%");
    await expect(linhaDoAno(tabela, 2024)).toContainText("55%");
    // 2023 sem resultado: o motivo por extenso, nunca 0.
    const ica2023 = linhaDoAno(tabela, 2023);
    await expect(ica2023).toContainText(/participação/i);
    await expect(ica2023).not.toContainText(/(^|\D)0%/);
    await expect(page.getByTestId("motivo-sem-escola")).toContainText("O ICA é da rede");
    // Abrangência: a 2ª opção (a escola) desabilitada; a visão por escolas também.
    await expect(page.locator('input[name="abrangencia-indicador"]').nth(1)).toBeDisabled();
    await expect(page.getByRole("radio", { name: "Escolas numa edição" })).toBeDisabled();
    // Outra rede (SP/Brasil, rede pública): só contexto, fora do gráfico.
    await expect(page.getByTestId("fora-da-comparacao")).toBeVisible();
    await expect(page.getByTestId("avisos-comparabilidade")).toBeVisible();
    const detIca = page.getByTestId("detalhes-fontes-indicador");
    await expect(detIca.getByTestId("detalhe-fonte")).toHaveCount(0);
    await detIca.getByRole("button").click();
    await expect(detIca.getByTestId("detalhe-fonte").first()).toBeVisible();
    await semErroNaTela(page);
    await capturar(page, "secretaria-5-avaliacoes-ica");

    // ---- SARESP (etapa e componente) --------------------------------------------------------
    let saresp = resposta(page, "/analise/indicadores/saresp?");
    await page.getByRole("button", { name: "Ver série histórica e escolas — SARESP" }).click();
    expect((await saresp).status()).toBe(200);
    tabela = page.getByTestId("indicador-tabela");
    await expect(page.getByLabel("Etapa", { exact: true })).toHaveValue("5_ano");
    await expect(page.getByLabel("Componente", { exact: true })).toHaveValue("lp");
    await expect(linhaDoAno(tabela, 2025)).toContainText("201,4");

    saresp = resposta(page, /\/analise\/indicadores\/saresp\?.*etapa=2_ano/);
    await page.getByLabel("Etapa", { exact: true }).selectOption("2_ano");
    expect((await saresp).status()).toBe(200);
    await expect(linhaDoAno(tabela, 2025)).toContainText("150,2");

    saresp = resposta(page, /\/analise\/indicadores\/saresp\?.*componente=mt/);
    await page.getByLabel("Componente", { exact: true }).selectOption("mt");
    expect((await saresp).status()).toBe(200);
    await expect(linhaDoAno(tabela, 2025)).toContainText("160,9");
    await expect(page.getByTestId("indicador-grafico")).toContainText("2º ano · Matemática");
    await semErroNaTela(page);

    // ---- Escolas numa edição (5º ano, LP): ordem de NOME, instável em língua simples, sem INEP --
    await page.getByLabel("Etapa", { exact: true }).selectOption("5_ano");
    await page.getByLabel("Componente", { exact: true }).selectOption("lp");
    await expect(linhaDoAno(tabela, 2025)).toContainText("201,4");
    saresp = resposta(page, /\/analise\/indicadores\/saresp\?.*visao=escolas/);
    await page.getByRole("radio", { name: "Escolas numa edição" }).check();
    expect((await saresp).status()).toBe(200);
    const escolas = page.getByTestId("indicador-escolas");
    await expect(escolas).toBeVisible();
    await expect(page.getByTestId("escolas-sem-ranking")).toContainText("não é ranking");
    const nomes = (await escolas.locator("tbody th").allInnerTexts())
      .map((t) => t.replace(/sem código INEP/g, "").trim());
    expect(nomes).toEqual(emOrdemDeNome(nomes));
    expect(nomes).toHaveLength(5);
    const linhaDe = (nome: string) => escolas.locator("tbody tr").filter({ hasText: nome });
    await expect(linhaDe(ESCOLAS.alfa)).toContainText("210,3");
    // TPS = 0 na língua do fluxo principal (a sigla técnica fica nas Análises avançadas).
    await expect(linhaDe(ESCOLAS.beta)).toContainText("média instável");
    await expect(linhaDe(ESCOLAS.beta)).not.toContainText("TPS");
    await expect(linhaDe(ESCOLAS.gama)).toContainText("sem código INEP");
    // Delta só tem ESTIMATIVA (233,3): a visão oficial mostra a ausência, nunca o número.
    await expect(linhaDe(ESCOLAS.delta)).not.toContainText("233,3");
    await expect(page.getByText("233,3")).toHaveCount(0);
    await semErroNaTela(page);
    await capturar(page, "secretaria-6-saresp-escolas");
    await abrirRecolhidos(page);
    await semTermoTecnico(page, "Avaliações externas › SARESP escolas");

    // ---- Ideb (metas só até 2021): o cartão abre a série (as dimensões do SARESP não valem) --
    const ideb = resposta(page, /\/analise\/indicadores\/ideb\?.*visao=serie/);
    await page.getByRole("button", { name: "Ver série histórica e escolas — Ideb" }).click();
    expect((await ideb).status()).toBe(200);
    tabela = page.getByTestId("indicador-tabela");
    await expect(linhaDoAno(tabela, 2023)).toContainText("6,1");
    await expect(linhaDoAno(tabela, 2021)).toContainText("5,4");
    await expect(linhaDoAno(tabela, 2021)).toContainText("não atingiu a meta");
    await expect(linhaDoAno(tabela, 2019)).toContainText("5,8");
    await expect(linhaDoAno(tabela, 2019)).toContainText("atingiu a meta");
    await expect(linhaDoAno(tabela, 2019)).not.toContainText("não atingiu");
    await expect(linhaDoAno(tabela, 2023)).toContainText("não definiu meta");
    await expect(tabela).not.toContainText("7,7");       // o 1 clique da Delta não entra na rede
    // Na visão por escolas, o 1 clique da Delta aparece MARCADO (*), com a legenda.
    const idebEscolas = resposta(page, /\/analise\/indicadores\/ideb\?.*visao=escolas/);
    await page.getByRole("radio", { name: "Escolas numa edição" }).check();
    expect((await idebEscolas).status()).toBe(200);
    const linhaDelta = page.getByTestId("indicador-escolas").locator("tbody tr").filter({ hasText: ESCOLAS.delta });
    await expect(linhaDelta).toContainText("7,7*");
    await expect(page.getByTestId("legenda-sem-registro")).toContainText("sem o registro do arquivo oficial");
    await expect(page.getByTestId("legenda-sem-registro")).toContainText("Não é a Estimativa Constela");
    await semErroNaTela(page);
    await capturar(page, "secretaria-7-ideb");
    await abrirRecolhidos(page);
    await semTermoTecnico(page, "Avaliações externas › Ideb escolas");
    await expect(page.locator("main")).not.toContainText("Criança Fictícia");

    expect(v.analise.length).toBeGreaterThan(6);
    conferirChamadas(v);
  });

  test("Elefante e Matific (o detalhe do uso, a partir do Panorama): o X de Y com o denominador da API; lacunas por série", async ({ page }) => {
    const v = vigiar(page);
    await entrar(page, CONTAS.secretaria);
    const plataformas = resposta(page, PLATAFORMAS);
    await page.goto("/rede/plataformas");
    const respPlataformas = await plataformas;
    expect(respPlataformas.status()).toBe(200);
    expect(respPlataformas.url()).toContain("periodo=ano_letivo");     // a tela abre no ano letivo
    const plat = await respPlataformas.json();
    await expect(page.getByRole("heading", { level: 1, name: "Elefante e Matific" })).toBeVisible();
    await expect(page.getByTestId("secretaria-rede-nome")).toHaveText(REDE);
    await expect(page.getByLabel("Período", { exact: true })).toHaveValue("ano_letivo");
    await expect(page.locator("main")).toContainText("não é avaliação oficial de aprendizagem");
    await expect(page.getByTestId("conclusao-plataformas")).not.toBeEmpty();
    // No menu, a tela mora DENTRO do Panorama da Rede (o item aceso).
    await expect(menuLateral(page).locator('a[aria-current="page"]')).toHaveAttribute("href", "/");

    // O "X de Y" usa o MESMO denominador do percentual (os alunos com conta), conferido com a API.
    const elefante = page.getByTestId("plataforma-elefante");
    await expect(elefante).toContainText("Participação");
    const ele = plat.rede.elefante;
    expect(ele.alunos_medidos).toBeGreaterThan(0);
    await expect(elefante).toContainText(`${ele.alunos_com_leitura} de ${ele.alunos_medidos} alunos com conta leram no período`);
    if (plat.rede.alunos > ele.alunos_medidos) {
      await expect(page.getByTestId("fora-da-conta-elefante"))
        .toContainText(`${plat.rede.alunos - ele.alunos_medidos} de ${plat.rede.alunos} alunos do recorte não entram na conta`);
    }
    await expect(page.getByTestId("plataforma-matific")).toContainText("Atividades por aluno");
    await expect(page.getByTestId("plataforma-matific"))
      .toContainText(`sobre ${plat.rede.matific.alunos_medidos} alunos com dado no período`);
    await expect(page.getByTestId("texto-blocos")).toContainText("somam só as escolas e as séries mostradas");
    await expect(page.getByTestId("o-que-mede-elefante")).toContainText("Participação:");
    await expect(page.getByTestId("o-que-mede-matific")).toContainText("Desempenho:");
    await expect(page.getByTestId("o-que-cada-numero-mede")).toContainText(/zero/);
    await expect(page.getByTestId("totais-gerais")).toBeVisible();

    // "Sobre os dados" (recolhido): as lacunas por série — as 5 séries, com as escolas de cada plataforma.
    await expect(page.getByTestId("tabela-lacunas-serie")).toHaveCount(0);
    await page.getByTestId("sobre-os-dados").getByRole("button", { name: /Sobre os dados/ }).click();
    const lacunas = page.getByTestId("tabela-lacunas-serie").locator("tbody tr");
    await expect(lacunas).toHaveCount(5);
    await expect(lacunas.nth(2)).toContainText("com a série oculta: poucos alunos");          // o 3º ano da Ébano
    await expect(page.getByTestId("lacunas-por-serie")).toContainText(/não é zero/);
    await abrirRecolhidos(page);
    await expect(page.locator("main")).not.toContainText("Criança Fictícia");
    // O caminho para comparar as escolas (a área Escolas).
    expect(await page.locator('main a[href^="/rede/escolas"]').count()).toBeGreaterThan(0);
    await semErroNaTela(page);
    await capturar(page, "secretaria-8-plataformas");
    conferirChamadas(v);
    // Por último (com todos os recolhidos abertos, inclusive "Como ler a evolução"): a régua da
    // linguagem do fluxo principal.
    await semTermoTecnico(page, "Elefante e Matific");
  });
});

// --- Secretaria: o que saiu do menu (as rotas ficam) e as Análises avançadas ------------------

test.describe("Secretaria — rotas fora do menu e Análises avançadas", () => {
  test("as telas que saíram do menu continuam abrindo (h1, sem erro); os ?ver= antigos de /rede/analise redirecionam", async ({ page }) => {
    test.setTimeout(180_000);
    const v = vigiar(page);
    await entrar(page, CONTAS.secretaria);
    for (const rota of ROTAS_FORA_DO_MENU) {
      await page.goto(rota);
      await page.waitForLoadState("networkidle");
      expect(new URL(page.url()).pathname, `a Secretaria continua abrindo ${rota}`).toBe(rota);
      await expect(page.getByRole("heading", { level: 1 }).first(), `h1 em ${rota}`).toBeVisible();
      await semErroNaTela(page);
    }

    // As abas que viraram telas redirecionam (com os parâmetros do indicador).
    await page.goto("/rede/analise?ver=visao");
    await page.waitForURL((u) => u.pathname === "/" && !u.searchParams.has("ver"));
    await expect(page.getByRole("heading", { level: 1, name: "Panorama da Rede" })).toBeVisible();
    for (const [antigo, destino] of [
      ["/rede/analise?ver=avaliacoes", "/rede/avaliacoes-externas"],
      ["/rede/analise?ver=indicador&indicador=saresp&visao=escolas&edicao=2025",
       "/rede/avaliacoes-externas?indicador=saresp&visao=escolas&edicao=2025"],
      ["/rede/analise?ver=plataformas", "/rede/plataformas"],
      ["/rede/analise?ver=relatorios", "/rede/relatorios"],
    ] as const) {
      const alvo = new URL(destino, "http://x");
      await page.goto(antigo);
      await page.waitForURL((u) => u.pathname === alvo.pathname);
      const atual = new URL(page.url());
      expect(Object.fromEntries(atual.searchParams), `parâmetros levados de ${antigo}`)
        .toEqual(Object.fromEntries(alvo.searchParams));
      await expect(page.getByRole("heading", { level: 1 }).first()).toBeVisible();
    }
    // O detalhe do link antigo do indicador abre o MESMO recorte (escolas numa edição).
    await page.goto("/rede/analise?ver=indicador&indicador=saresp&visao=escolas&edicao=2025");
    await expect(page.getByTestId("indicador-escolas")).toBeVisible();
    await expect(page.getByRole("radio", { name: "Escolas numa edição" })).toBeChecked();

    // A página das Análises avançadas (fora do menu dela): a faixa da área técnica e três abas.
    const diagnostico = resposta(page, "/analise/diagnostico?");
    await page.goto("/rede/analise");
    expect((await diagnostico).status()).toBe(200);
    await expect(page.getByRole("heading", { level: 1, name: "Análises avançadas" })).toBeVisible();
    await expect(page.getByTestId("analise-rede-nome")).toHaveText(REDE);
    await expect(page.getByTestId("faixa-area-tecnica")).toContainText("Área técnica");
    await expect(page.getByRole("tab")).toHaveText(["Diagnóstico exploratório", "Relação com as plataformas",
                                                    "Análise detalhada por escola"]);
    await expect(aba(page, "Diagnóstico exploratório")).toHaveAttribute("aria-selected", "true");
    // Sem item no menu da Secretaria: nada aceso, nenhum acordeão abre por causa da rota.
    await expect(menuLateral(page).locator('a[aria-current="page"]')).toHaveCount(0);
    await expect(menuLateral(page).locator("button[aria-expanded]")).toHaveCount(0);
    await expect(page.getByTestId("faixa-hipotese")).toContainText("não é ranking");
    const nomes = await page.locator('[data-testid="tabela-diagnostico"] tbody tr[data-testid^="diagnostico-escola-"] th > span')
      .allInnerTexts();
    expect(nomes).toHaveLength(5);
    expect(nomes).toEqual(emOrdemDeNome(nomes));
    await expect(page.locator("main")).not.toContainText("Criança Fictícia");
    await semErroNaTela(page);
    await capturar(page, "secretaria-9-diagnostico");
    conferirChamadas(v);
  });

  test("Relação com as plataformas: NÃO calculável, com os motivos, o lado a lado e nenhum coeficiente", async ({ page }) => {
    const v = vigiar(page);
    await entrar(page, CONTAS.secretaria);
    const primeira = resposta(page, "/analise/relacao?");
    await page.goto("/rede/analise?ver=relacao");
    let r = await primeira;
    expect(r.status()).toBe(200);
    await expect(aba(page, "Relação com as plataformas")).toHaveAttribute("aria-selected", "true");
    // O SARESP (por escola); se a aba abrir em outro indicador, escolhe-o.
    if (!/[?&]indicador=saresp/.test(r.url())) {
      const relacao = resposta(page, /\/analise\/relacao\?.*indicador=saresp/);
      await page.getByRole("radio", { name: /^SARESP/ }).check();
      r = await relacao;
      expect(r.status()).toBe(200);
    }
    let corpo = await r.json();
    expect(corpo.calculavel).toBe(false);
    expect(corpo.motivos).toContain("periodo_sem_sobreposicao");
    expect(corpo.coeficiente).toBeNull();
    await expect(page.getByRole("radio", { name: /\(ICA\)/ })).toBeDisabled();
    await expect(page.getByText(/o ICA é da rede: não existe por escola/).first()).toBeVisible();
    const naoCalc = page.getByTestId("relacao-nao-calculavel");
    await expect(naoCalc).toContainText("Não dá para calcular a relação");
    await expect(naoCalc).toContainText(/sem sobreposição/i);
    await expect(page.getByTestId("relacao-coeficiente")).toHaveCount(0);
    await expect(page.getByTestId("relacao-dispersao")).toHaveCount(0);
    // O motivo geral sem repetir o ano letivo.
    await expect(naoCalc).not.toContainText(/\(ano letivo \d{4}\)/);
    const lado = page.getByTestId("relacao-lado-a-lado");
    await expect(lado.locator("tbody tr")).toHaveCount(5);
    const nomesLado = await lado.locator("tbody th").allInnerTexts();
    expect(nomesLado).toEqual(emOrdemDeNome(nomesLado));
    await expect(lado.locator("tbody tr").filter({ hasText: ESCOLAS.alfa })).toContainText("2025");
    // Cada escola com o motivo PRÓPRIO, quando há (a API o calcula mesmo com o motivo geral).
    for (const par of corpo.pares as { nome: string; motivo_escola: string | null }[]) {
      const linha = lado.locator("tbody tr").filter({ hasText: par.nome });
      await expect(linha).toContainText(par.motivo_escola
        ? `não: ${par.motivo_escola.slice(0, 25)}` : "não: fica de fora pelo motivo geral");
    }
    await expect(page.getByTestId("aviso-causalidade")).toContainText("Correlação não é causalidade");
    await page.getByRole("button", { name: /Metodologia da relação/ }).click();
    await expect(page.getByTestId("relacao-metodologia")).toContainText("Spearman");
    await expect(page.getByTestId("relacao-criterios")).toBeVisible();

    // Componente Matemática com métrica do Elefante: outra área, outro motivo.
    let relacao = resposta(page, /\/analise\/relacao\?.*componente=mt/);
    await page.getByTestId("dimensoes-relacao").getByLabel("Componente", { exact: true }).selectOption("mt");
    expect((await relacao).status()).toBe(200);
    relacao = resposta(page, /\/analise\/relacao\?.*metrica=livros_por_aluno/);
    await page.getByLabel("Métrica da plataforma", { exact: true }).selectOption("livros_por_aluno");
    r = await relacao;
    corpo = await r.json();
    expect(corpo.calculavel).toBe(false);
    expect(corpo.motivos).toEqual(expect.arrayContaining(["periodo_sem_sobreposicao", "componente_incompativel"]));
    await expect(naoCalc.locator("li")).toHaveCount(corpo.textos.length);
    await expect(page.getByTestId("relacao-coeficiente")).toHaveCount(0);
    await semErroNaTela(page);
    await capturar(page, "secretaria-10-relacao");
    conferirChamadas(v);
  });

  test("Análise detalhada por escola: o filtro Escola leva o contexto do topo; o topo com uma escola abre a ficha dela", async ({ page }) => {
    const v = vigiar(page);
    await entrar(page, CONTAS.secretaria);
    const rede = await lerRede(page);
    await page.goto("/rede/analise?ver=escola");
    await expect(aba(page, "Análise detalhada por escola")).toHaveAttribute("aria-selected", "true");
    await expect(page.getByText("Escolha uma escola", { exact: true })).toBeVisible();
    let daEscola = resposta(page, /\/escolas\/\d+\/analise/);
    await page.getByLabel("Escola", { exact: true }).selectOption({ label: ESCOLAS.alfa });
    expect((await daEscola).status()).toBe(200);
    await expect(page.getByTestId("por-escola-nome")).toHaveText(ESCOLAS.alfa);
    // O filtro Escola é o seletor de contexto do topo: escolher aqui leva o topo junto (sem sair da página).
    const topo = page.getByLabel("Contexto de visualização");
    await expect.poll(() => topo.evaluate((s: HTMLSelectElement) => s.selectedOptions[0]?.textContent))
      .toBe(ESCOLAS.alfa);
    expect(new URL(page.url()).pathname).toBe("/rede/analise");
    await expect(page.getByTestId("analise-escola-indicador-saresp")).toContainText("210,3");
    await expect(page.getByTestId("tabela-series-plataformas")).toContainText("2º ano");
    await expect(page.getByTestId("tabela-series-plataformas")).toContainText("5º ano");
    await expect(page.getByTestId("analise-escola-indisponiveis")).toContainText("ICA");

    daEscola = resposta(page, /\/escolas\/\d+\/analise/);
    await page.getByLabel("Escola", { exact: true }).selectOption({ label: ESCOLAS.ebano });
    expect((await daEscola).status()).toBe(200);
    await expect(page.getByTestId("por-escola-nome")).toHaveText(ESCOLAS.ebano);
    // 3º ano com 3 crianças: números ocultos (e o 5º ano, em complemento).
    await expect(page.getByTestId("tabela-series-plataformas").locator("tbody tr").filter({ hasText: "3º ano" }))
      .toContainText("para proteger as crianças");

    daEscola = resposta(page, /\/escolas\/\d+\/analise/);
    await page.getByLabel("Escola", { exact: true }).selectOption({ label: `${ESCOLAS.gama} (sem código INEP)` });
    expect((await daEscola).status()).toBe(200);
    await expect(page.getByTestId("por-escola-nome")).toHaveText(ESCOLAS.gama);
    await expect(page.getByTestId("analise-escola-sem-inep")).toBeVisible();
    await semErroNaTela(page);
    await capturar(page, "secretaria-11-por-escola");

    // "Toda a Rede Municipal" no topo traz o filtro junto e fica na página (não é tela de escola)…
    await topo.selectOption({ index: 0 });
    await expect(page.getByLabel("Escola", { exact: true })).toHaveValue("");
    await expect(page.getByText("Escolha uma escola", { exact: true })).toBeVisible();
    expect(new URL(page.url()).pathname).toBe("/rede/analise");
    // …e UMA escola no topo (o cartão Contexto da Secretaria) abre a FICHA dela.
    await topo.selectOption({ label: ESCOLAS.beta });
    await page.waitForURL((u) => u.pathname === `/rede/escolas/${rede.id.beta}`);
    await expect(page.getByRole("heading", { level: 1, name: ESCOLAS.beta })).toBeVisible();
    await expect(page.locator("main")).not.toContainText("Criança Fictícia");
    conferirChamadas(v);
  });
});

// --- Secretaria: o que vale para todas as telas -----------------------------------------------

test.describe("Secretaria — todas as telas da rede", () => {
  test("respostas da API sem nome de criança; as da rede e da análise sem aluno_id", async ({ page }) => {
    test.setTimeout(240_000);
    const corpos: { url: string; texto: string }[] = [];
    page.on("response", async (r) => {
      if (r.url().startsWith(API) && new URL(r.url()).pathname.startsWith("/api/") && r.ok()) {
        corpos.push({ url: r.url(), texto: await r.text().catch(() => "") });
      }
    });
    await entrar(page, CONTAS.secretaria);
    const rede = await lerRede(page);
    for (const vista of [...telasPrincipais(rede), ficha(rede, "ebano"), ...TELAS_FORA_DO_MENU, ...ABAS_AVANCADAS]) {
      await page.goto(vista.caminho);
      if (vista.preparar) await vista.preparar(page);
      await page.waitForLoadState("networkidle");
    }
    for (const rota of ["/rede", "/rede/ranking", "/rede/avaliacoes"]) {
      await page.goto(rota);
      await page.waitForLoadState("networkidle");
    }
    expect(corpos.length).toBeGreaterThan(20);
    for (const url of ["/destaques", "/dashboard", "/analise/plataformas?", "/analise/diagnostico?", "/analise/indicadores"]) {
      expect(corpos.some((c) => c.url.includes(url)), `a varredura leu ${url}`).toBe(true);
    }
    for (const c of corpos) {
      expect(c.texto, c.url).not.toContain("Criança Fictícia");
      if (/\/redes\/|\/analise/.test(c.url)) expect(c.texto, c.url).not.toMatch(/"aluno_id"/);
    }
  });

  test("sem rolagem horizontal da página em 320, 768 e 1366 px", async ({ page }) => {
    test.setTimeout(600_000);
    const v = vigiar(page);
    await entrar(page, CONTAS.secretaria);
    const rede = await lerRede(page);
    for (const largura of [320, 768, 1366]) {
      await page.setViewportSize({ width: largura, height: largura < 768 ? 640 : 900 });
      for (const vista of [...telasPrincipais(rede), ...TELAS_FORA_DO_MENU, ...ABAS_AVANCADAS]) {
        await abrirVista(page, vista);
        await semRolagemHorizontal(page, `${vista.nome} @ ${largura}px`);
        if (vista === AVALIACOES_ICA) {
          // O gráfico cabe na largura que há: nada do ano mais recente escondido fora da vista.
          const caixa = page.getByTestId("indicador-grafico").locator(".overflow-x-auto").first();
          const m = await caixa.evaluate((el) => ({ sw: el.scrollWidth, cw: el.clientWidth }));
          expect(m.sw, `gráfico rola por dentro a ${largura}px (${m.sw} > ${m.cw})`).toBeLessThanOrEqual(m.cw);
        }
        await capturar(page, `largura-${largura}-${vista.nome}`);
      }
    }
    expect(v.problemas, v.problemas.join("\n")).toEqual([]);
  });

  test("menu: as três áreas, sem acordeão, com o item certo aceso; a 1280 px a trilha não corta o nome", async ({ page }) => {
    const v = vigiar(page);
    await page.setViewportSize({ width: 1280, height: 800 });
    await entrar(page, CONTAS.secretaria);
    const rede = await lerRede(page);
    const menu = menuLateral(page);
    // Exatamente três itens, numa seção "Rede municipal", sem nenhum acordeão.
    await expect(menu.locator("a[href]")).toHaveCount(MENU_DA_SECRETARIA.length);
    const itens = await menu.locator("a[href]").evaluateAll((as) =>
      as.map((a) => ({ nome: (a.textContent ?? "").replace(/\s+/g, " ").trim(), href: a.getAttribute("href") })));
    expect(itens).toEqual(MENU_DA_SECRETARIA);
    await expect(menu.locator("button[aria-expanded]")).toHaveCount(0);
    await expect(menu).toContainText(/Rede municipal/i);

    const cortado = (l: Locator) => l.evaluate((el) => el.scrollWidth > el.clientWidth);
    const trilha = page.getByRole("navigation", { name: "Trilha de navegação" });
    // A trilha: Panorama da Rede › Rede municipal › a página (as três áreas e o que mora nelas);
    // fora do menu, só Panorama da Rede › a página. O item aceso: a área da página (ou nenhum).
    for (const [caminho, contexto, titulo, aceso] of [
      ["/rede/escolas", "Rede municipal", "Escolas", "/rede/escolas"],
      [`/rede/escolas/${rede.id.alfa}`, "Rede municipal", "Ficha da escola", "/rede/escolas"],
      [`/rede/escolas?comparar=${rede.id.alfa},${rede.id.beta}`, "Rede municipal", "Escolas", "/rede/escolas"],
      ["/rede/avaliacoes-externas", "Rede municipal", "Avaliações externas", "/rede/avaliacoes-externas"],
      ["/rede/plataformas", "Rede municipal", "Elefante e Matific", "/"],
      ["/rede/ranking", "Rede municipal", "Ranking da Rede", "/rede/escolas"],
      ["/rede/avaliacoes", "Rede municipal", "Fontes dos indicadores", "/rede/avaliacoes-externas"],
      ["/rede/analise", null, "Análises avançadas", null],
      ["/rede/acompanhamento", null, "Escolas em acompanhamento", null],
    ] as const) {
      await page.goto(caminho);
      await page.waitForLoadState("networkidle");
      const pagina = trilha.locator("[data-trilha=pagina]");
      await expect(pagina, `trilha em ${caminho}`).toHaveText(titulo);
      await expect(pagina).toHaveAttribute("title", titulo);
      expect(await cortado(pagina), `trilha cortada em ${caminho}`).toBe(false);
      if (contexto) await expect(trilha.locator("[data-trilha=contexto]")).toHaveText(contexto);
      else await expect(trilha.locator("[data-trilha=contexto]")).toHaveCount(0);
      const marcados = menu.locator('a[aria-current="page"]');
      if (aceso) {
        await expect(marcados, `item aceso em ${caminho}`).toHaveCount(1);
        await expect(marcados).toHaveAttribute("href", aceso);
      } else {
        await expect(marcados, `nenhum item aceso em ${caminho}`).toHaveCount(0);
      }
    }
    // O rótulo do item quebra em até duas linhas (não corta) e o nome inteiro fica no title.
    for (const { nome } of MENU_DA_SECRETARIA) {
      const rotulo = menu.getByRole("link", { name: nome, exact: true }).locator("span[title]");
      await expect(rotulo).toBeVisible();
      await expect(rotulo).toHaveAttribute("title", nome);
      expect(await rotulo.evaluate((el) => el.scrollHeight > el.clientHeight + 1), `rótulo cortado: ${nome}`).toBe(false);
    }
    expect(v.problemas, v.problemas.join("\n")).toEqual([]);
  });

  test("contraste do texto (AA) nas três áreas, na ficha, nos detalhes e nas abas avançadas, no tema claro e no escuro", async ({ page }) => {
    test.setTimeout(600_000);
    const v = vigiar(page);
    await entrar(page, CONTAS.secretaria);
    const rede = await lerRede(page);
    const vistas: Vista[] = [
      PANORAMA,
      ESCOLAS_LISTA,
      comparar(rede),
      ficha(rede, "alfa"),
      ficha(rede, "gama"),
      { nome: "avaliacoes-saresp", caminho: "/rede/avaliacoes-externas?indicador=saresp", pronto: (p) => p.getByTestId("indicador-tabela") },
      { nome: "avaliacoes-ideb-escolas", caminho: "/rede/avaliacoes-externas?indicador=ideb&visao=escolas&edicao=2023",
        pronto: (p) => p.getByTestId("indicador-escolas") },
      AVALIACOES_TODAS_AS_ESCOLAS,
      PLATAFORMAS_DETALHE,
      ABAS_AVANCADAS[0],
      { nome: "avancadas-relacao", caminho: "/rede/analise?ver=relacao&indicador=saresp", pronto: (p) => p.getByTestId("relacao-lado-a-lado") },
      ABAS_AVANCADAS[2],
    ];
    const falhas: string[] = [];
    for (const tema of ["claro", "escuro"] as const) {
      await page.evaluate((t) => localStorage.setItem("sgpe_tema", t), tema);
      for (const vista of vistas) {
        await abrirVista(page, vista);
        // Os recolhidos abertos também (o texto deles conta): um por vez, até não sobrar.
        await abrirRecolhidos(page);
        falhas.push(...(await contrasteDoTexto(page, "main")).map((f) => `${tema} ${vista.nome}: ${f}`));
      }
    }
    expect(falhas, falhas.join("\n")).toEqual([]);
    expect(v.problemas, v.problemas.join("\n")).toEqual([]);
  });
});

/** Telas do contrato da auditoria de 20/10 (celular, tablet, notebook, Full HD e TV 4K). */
const TELAS_CONTRATO = [
  { largura: 320, altura: 568 }, { largura: 375, altura: 812 }, { largura: 768, altura: 1024 },
  { largura: 1366, altura: 768 }, { largura: 1920, altura: 1080 }, { largura: 3840, altura: 2160 },
];

/** A régua pedida na auditoria: document.scrollingElement.scrollWidth <= innerWidth. */
async function semRolagemPelaRegua(page: Page, rotulo: string) {
  const m = await page.evaluate(() => ({ sw: document.scrollingElement!.scrollWidth, iw: window.innerWidth }));
  expect(m.sw, `${rotulo}: rolagem horizontal (scrollWidth ${m.sw} > innerWidth ${m.iw})`).toBeLessThanOrEqual(m.iw);
}

test.describe("Secretaria — contrato das 6 telas (320 a 4K)", () => {
  test("sem rolagem lateral; nomes das escolas inteiros; meta × resultado e oficial × estimativa inequívocos; ausência por extenso", async ({ page }) => {
    test.setTimeout(900_000);
    const v = vigiar(page);
    await entrar(page, CONTAS.secretaria);
    const rede = await lerRede(page);
    for (const tela of TELAS_CONTRATO) {
      const nome = `${tela.largura}x${tela.altura}`;
      await page.setViewportSize({ width: tela.largura, height: tela.altura });

      // Panorama: todas as escolas, cada nome inteiro na tela; o critério dos destaques à vista.
      await abrirVista(page, PANORAMA);
      await semRolagemPelaRegua(page, `panorama @ ${nome}`);
      await inteirosNaTela(page.getByTestId("lista-escolas").locator(":scope > li > p a"), `panorama @ ${nome}`,
                          rede.painel.escolas.length);
      await expect(page.getByTestId("criterio-destaques")).toBeVisible();
      await capturar(page, `contrato-${nome}-panorama`);

      // Avaliações externas com o ICA aberto: a estimativa e o número sem registro oficial FORA
      // dos cartões oficiais, cada um no seu aviso rotulado; resultado em linha CHEIA e meta
      // TRACEJADA, de cores diferentes, com a legenda dizendo qual é qual; o gráfico cabe sem
      // rolar por dentro; 2023 sem resultado = motivo.
      await abrirVista(page, AVALIACOES_ICA);
      await semRolagemPelaRegua(page, `avaliações › ICA @ ${nome}`);
      await expect(page.getByTestId("estimativas-fora")).toContainText("Estimativa Constela");
      await expect(page.getByTestId("indicadores-disponiveis")).not.toContainText("Estimativa");
      await expect(page.getByTestId("sem-registro-fora")).toContainText("sem o registro do arquivo oficial");
      const grafico = page.getByTestId("indicador-grafico");
      const linhas = await grafico.locator("svg polyline").evaluateAll((els) => els.map((el) => ({
        cor: el.getAttribute("stroke"), traco: el.getAttribute("stroke-dasharray"),
      })));
      const resultado = linhas.filter((l) => !l.traco);
      const meta = linhas.filter((l) => l.traco);
      expect(resultado.length, "linha do resultado").toBeGreaterThan(0);
      expect(meta.length, "linha da meta").toBeGreaterThan(0);
      expect(new Set(meta.map((l) => l.cor)).size).toBe(1);
      expect(resultado.map((l) => l.cor), "meta e resultado com a mesma cor").not.toContain(meta[0].cor);
      await expect(grafico).toContainText("(tracejada)");
      await expect(grafico).toContainText(/Meta —/);
      const caixa = grafico.locator(".overflow-x-auto").first();
      const g = await caixa.evaluate((el) => ({ sw: el.scrollWidth, cw: el.clientWidth }));
      expect(g.sw, `gráfico rola por dentro @ ${nome}`).toBeLessThanOrEqual(g.cw);
      const tabela = page.getByTestId("indicador-tabela");
      await expect(linhaDoAno(tabela, 2023)).toContainText(/participação/i);
      await expect(linhaDoAno(tabela, 2023)).not.toContainText(/(^|\D)0%/);
      await capturar(page, `contrato-${nome}-ica`);

      // Escolas numa edição: a tabela pode rolar DENTRO da caixa no celular, mas o nome da
      // escola (1ª coluna) aparece inteiro na tela; a estimativa nunca entra na visão oficial.
      await abrirVista(page, AVALIACOES_SARESP_ESCOLAS);
      await semRolagemPelaRegua(page, `SARESP escolas @ ${nome}`);
      await expect(page.getByTestId("escolas-sem-ranking")).toContainText("não é ranking");
      await inteirosNaTela(page.getByTestId("indicador-escolas").locator("tbody th"), `SARESP escolas @ ${nome}`, 5);
      await expect(page.getByText("233,3")).toHaveCount(0);

      // Todas as escolas nas avaliações (ao rolar) e a lista de Escolas: o nome inteiro na tela.
      await abrirVista(page, AVALIACOES_TODAS_AS_ESCOLAS);
      await semRolagemPelaRegua(page, `avaliações › todas as escolas @ ${nome}`);
      await inteirosNaTela(page.getByTestId("tabela-comparacao-escolas").locator("tbody th"),
                          `avaliações › todas as escolas @ ${nome}`, 5);
      await abrirVista(page, ESCOLAS_LISTA);
      await semRolagemPelaRegua(page, `escolas @ ${nome}`);
      await inteirosNaTela(page.getByTestId("tabela-escolas-periodo").locator("tbody th"), `escolas @ ${nome}`, 5);

      // A comparação, a ficha, o detalhe do uso e as três abas avançadas: a régua da página.
      for (const vista of [comparar(rede), ficha(rede, "alfa"), PLATAFORMAS_DETALHE, ...ABAS_AVANCADAS]) {
        await abrirVista(page, vista);
        await semRolagemPelaRegua(page, `${vista.nome} @ ${nome}`);
      }
      await capturar(page, `contrato-${nome}-avancadas-escola`);
    }
    expect(v.problemas, v.problemas.join("\n")).toEqual([]);
  });
});

test.describe("Shell (menu e topo) pelo teclado", () => {
  /** O elemento focado está de fato visível (não um link dentro de grupo fechado). */
  async function focoVisivel(page: Page) {
    return page.evaluate(() => {
      const el = document.activeElement as HTMLElement | null;
      if (!el || el === document.body) return { ok: true, rotulo: "body" };
      const r = el.getBoundingClientRect();
      const cs = getComputedStyle(el);
      const rotulo = `${el.tagName} ${(el.getAttribute("aria-label") ?? el.textContent ?? "").trim().slice(0, 30)}`;
      return { ok: r.width > 0 && r.height > 0 && cs.visibility !== "hidden", rotulo };
    });
  }

  test("desktop (Secretaria): menu sem acordeão; 1º Tab pula para o conteúdo; o foco sempre visível; contraste do shell", async ({ page }) => {
    const v = vigiar(page);
    await page.setViewportSize({ width: 1366, height: 768 });
    await entrar(page, CONTAS.secretaria);
    const rede = await lerRede(page);
    const menu = menuLateral(page);
    // As três áreas, soltas: nenhum acordeão (nada escondido atrás de um grupo fechado).
    await expect(menu.locator("a[href]")).toHaveCount(MENU_DA_SECRETARIA.length);
    await expect(menu.locator("button[aria-expanded]")).toHaveCount(0);

    // Na ficha de uma escola, o item "Escolas" fica aceso e à vista — sem roubar o 1º Tab do
    // "Pular para o conteúdo".
    await page.goto(`/rede/escolas/${rede.id.alfa}`);
    await expect(page.getByTestId("ficha-situacao-uso")).toBeVisible();
    await page.waitForLoadState("networkidle");
    const ativo = menu.locator('a[aria-current="page"]');
    await expect(ativo).toHaveAttribute("href", "/rede/escolas");
    await expect(ativo).toBeInViewport();
    await page.keyboard.press("Tab");
    const pular = page.getByRole("link", { name: "Pular para o conteúdo" });
    await expect(pular).toBeFocused();
    await expect(pular).toBeInViewport();
    const anel = await pular.evaluate((el) => getComputedStyle(el).boxShadow);
    expect(anel, "foco do 'Pular' sem anel").not.toBe("none");
    await page.keyboard.press("Enter");
    await expect(page.locator("main#conteudo")).toBeFocused();
    expect(new URL(page.url()).hash).toBe("");

    // No Panorama, do começo da página: 40 Tabs pelo menu, pelo topo e pelo conteúdo, sempre
    // num elemento visível.
    await page.goto("/");
    await expect(page.getByTestId("lista-escolas")).toBeVisible();
    await page.waitForLoadState("networkidle");
    const percorridos: string[] = [];
    for (let i = 0; i < 40; i++) {
      await page.keyboard.press("Tab");
      if (i === 0) await expect(pular).toBeFocused();
      const f = await focoVisivel(page);
      percorridos.push(f.rotulo);
      expect(f.ok, `foco invisível no ${i + 1}º Tab: ${f.rotulo}\n${percorridos.join(" → ")}`).toBe(true);
    }

    const falhas: string[] = [];
    for (const tema of ["claro", "escuro"] as const) {
      await page.evaluate((t) => localStorage.setItem("sgpe_tema", t), tema);
      // O Panorama (item "/" aceso) e a ficha (item "Escolas" aceso).
      for (const [caminho, pronto] of [["/", "lista-escolas"], [`/rede/escolas/${rede.id.alfa}`, "ficha-situacao-uso"]] as const) {
        await page.goto(caminho);
        await expect(page.getByTestId(pronto)).toBeVisible();
        // A marca (logotipo "constela EDU") é isenta pela WCAG 1.4.3: confere o menu e o topo.
        falhas.push(...(await contrasteDoTexto(page, "header, aside nav")).map((f) => `${tema} ${caminho}: ${f}`));
      }
    }
    expect(falhas, falhas.join("\n")).toEqual([]);
    expect(v.problemas, v.problemas.join("\n")).toEqual([]);
  });

  test("desktop (coordenação): o foco nunca cai num grupo FECHADO; contraste do menu com acordeões", async ({ page }) => {
    const v = vigiar(page);
    await page.setViewportSize({ width: 1366, height: 768 });
    await entrar(page, CONTAS.coord);
    await page.goto("/");
    await page.waitForLoadState("networkidle");
    // 1ª visita: só "Minha Escola" nasce aberta; "Reconhecimento" fica fechado.
    const menu = menuLateral(page);
    await expect(menu.getByRole("button", { name: "Minha Escola" })).toHaveAttribute("aria-expanded", "true");
    const fechado = menu.getByRole("button", { name: "Reconhecimento" });
    await expect(fechado).toHaveAttribute("aria-expanded", "false");
    const idPainelFechado = await fechado.getAttribute("aria-controls");
    expect(idPainelFechado).toBeTruthy();
    const percorridos: string[] = [];
    for (let i = 0; i < 40; i++) {
      await page.keyboard.press("Tab");
      // O 1º Tab é o "Pular para o conteúdo", mesmo com um item do menu marcado nesta página.
      if (i === 0) await expect(page.getByRole("link", { name: "Pular para o conteúdo" })).toBeFocused();
      const f = await focoVisivel(page);
      percorridos.push(f.rotulo);
      expect(f.ok, `foco invisível no ${i + 1}º Tab: ${f.rotulo}\n${percorridos.join(" → ")}`).toBe(true);
      const noFechado = await page.evaluate((id) => !!document.getElementById(id!)?.contains(document.activeElement),
        idPainelFechado);
      expect(noFechado, `o ${i + 1}º Tab caiu num link do grupo FECHADO: ${f.rotulo}`).toBe(false);
    }
    const falhas: string[] = [];
    for (const tema of ["claro", "escuro"] as const) {
      await page.evaluate((t) => localStorage.setItem("sgpe_tema", t), tema);
      await page.goto("/turmas");
      await page.waitForLoadState("networkidle");
      falhas.push(...(await contrasteDoTexto(page, "header, aside nav")).map((f) => `${tema}: ${f}`));
    }
    expect(falhas, falhas.join("\n")).toEqual([]);
    expect(v.problemas, v.problemas.join("\n")).toEqual([]);
  });

  test("celular: a gaveta do menu é um diálogo — foco dentro, Tab preso, Esc devolve o foco", async ({ page }) => {
    const v = vigiar(page);
    await page.setViewportSize({ width: 375, height: 812 });
    await entrar(page, CONTAS.secretaria);
    await page.goto("/");
    await expect(page.getByTestId("lista-escolas")).toBeVisible();
    const abrir = page.getByRole("button", { name: "Abrir menu" });
    await abrir.click();
    const dialogo = page.getByRole("dialog", { name: "Menu de navegação" });
    await expect(dialogo).toBeVisible();
    // A gaveta da Secretaria: as mesmas três áreas, sem acordeão.
    await expect(dialogo.locator('nav[aria-label="Menu principal"] a[href]')).toHaveCount(MENU_DA_SECRETARIA.length);
    await expect(dialogo.locator('nav[aria-label="Menu principal"] button[aria-expanded]')).toHaveCount(0);
    const dentro = () => dialogo.evaluate((d) => d.contains(document.activeElement));
    expect(await dentro(), "o foco não entrou na gaveta").toBe(true);
    for (let i = 0; i < 25; i++) {
      await page.keyboard.press(i % 5 === 4 ? "Shift+Tab" : "Tab");
      expect(await dentro(), `o foco saiu da gaveta no ${i + 1}º Tab`).toBe(true);
      const f = await focoVisivel(page);
      expect(f.ok, `foco invisível na gaveta: ${f.rotulo}`).toBe(true);
    }
    await page.keyboard.press("Escape");
    await expect(dialogo).toHaveCount(0);
    await expect(abrir).toBeFocused();
    await capturar(page, "teclado-celular-gaveta-fechada");
    expect(v.problemas, v.problemas.join("\n")).toEqual([]);
  });
});

// --- Admin global ---------------------------------------------------------------------------

test("admin global: a Visão da rede é o Panorama (mesmos números, links com a rede); o menu dele não mudou; Análises avançadas", async ({ page }) => {
  test.setTimeout(180_000);
  const v = vigiar(page);
  await entrar(page, CONTAS.global);
  const rede = await lerRede(page);
  const painelResp = resposta(page, PAINEL);
  await page.goto("/rede/visao");
  expect((await painelResp).status()).toBe(200);
  await expect(page.getByRole("heading", { level: 1, name: "Visão da rede" })).toBeVisible();
  await expect(page.getByTestId("secretaria-rede-nome")).toHaveText(REDE);
  // Uma rede só: sem o seletor "Rede analisada".
  await expect(page.getByLabel("Rede analisada")).toHaveCount(0);
  const valor = (id: string) => page.getByTestId(id).locator("p").nth(1);
  await expect(valor("numero-cadastradas")).toHaveText(String(rede.painel.totais.escolas));
  await expect(valor("numero-ativas")).toHaveText(String(rede.painel.totais.escolas_ativas));
  const lista = page.getByTestId("lista-escolas");
  await expect(lista.locator(":scope > li")).toHaveCount(rede.painel.escolas.length);
  // Os links levam a rede escolhida (?rede=): a ficha abre a MESMA rede.
  const linkAlfa = page.getByTestId(`escola-${rede.id.alfa}`).getByRole("link", { name: ESCOLAS.alfa, exact: true });
  await expect(linkAlfa).toHaveAttribute("href", `/rede/escolas/${rede.id.alfa}?rede=${rede.redeId}`);
  await expect(page.getByTestId("criterio-destaques")).toBeVisible();
  await expect(page.getByTestId("reconhecimento-publico").getByRole("heading", { name: /Vitrine pública/ })).toBeVisible();
  await semErroNaTela(page);

  // O menu do global: o grupo "Redes e municípios" igual, com a Visão da rede acesa; nenhum
  // item das três áreas da Secretaria.
  const menu = menuLateral(page);
  const grupo = menu.getByRole("button", { name: "Redes e municípios" });
  if ((await grupo.getAttribute("aria-expanded")) === "false") await grupo.click();
  const painelGrupo = page.locator(`[id="${await grupo.getAttribute("aria-controls")}"]`);
  const hrefs = await painelGrupo.locator("a[href]").evaluateAll((as) => as.map((a) => a.getAttribute("href")));
  expect(hrefs).toEqual(["/rede", "/rede/visao", "/rede/ranking", "/rede/analise", "/rede/avaliacoes", "/rede/gerenciar"]);
  await expect(menu.locator('a[aria-current="page"]')).toHaveAttribute("href", "/rede/visao");
  await expect(menu.locator('a[href="/rede/escolas"], a[href="/rede/avaliacoes-externas"]')).toHaveCount(0);
  await capturar(page, "global-visao-da-rede");

  // A ficha (pelo Panorama): a mesma rede, a Visão da rede continua acesa.
  await linkAlfa.click();
  await page.waitForURL((u) => u.pathname === `/rede/escolas/${rede.id.alfa}` && u.searchParams.get("rede") === String(rede.redeId));
  await expect(page.getByRole("heading", { level: 1, name: ESCOLAS.alfa })).toBeVisible();
  await expect(page.getByTestId("ficha-situacao-uso")).toBeVisible();
  await expect(menu.locator('a[aria-current="page"]')).toHaveAttribute("href", /^\/rede\/visao(\?|$)/);

  await page.goto("/rede/analise");
  await expect(page.getByRole("heading", { level: 1, name: "Análises avançadas" })).toBeVisible();
  await expect(page.getByTestId("analise-rede-nome")).toHaveText(REDE);
  await expect(page.getByLabel("Rede analisada")).toHaveCount(0);
  await expect(aba(page, "Diagnóstico exploratório")).toHaveAttribute("aria-selected", "true");
  await expect(page.getByTestId("tabela-diagnostico")).toBeVisible();
  await semErroNaTela(page);
  // O link antigo da visão geral leva o global à Visão da rede (o "/" dele é o Panorama Global).
  await page.goto("/rede/analise?ver=visao");
  await page.waitForURL((u) => u.pathname === "/rede/visao");
  await expect(page.getByTestId("lista-escolas")).toBeVisible();
  expect(v.problemas, v.problemas.join("\n")).toEqual([]);
});

// --- Coordenação: a análise da escola na Visão da Escola ------------------------------------

test("coordenador vê a análise da própria escola na Visão da Escola e não entra em nenhuma tela da rede (nem na ficha)", async ({ page }) => {
  const v = vigiar(page);
  await entrar(page, CONTAS.coord);
  const daEscola = resposta(page, /\/escolas\/\d+\/analise/);
  await page.goto("/escola");
  expect((await daEscola).status()).toBe(200);
  const secao = page.getByTestId("analise-escola");
  await expect(secao).toBeVisible();
  await expect(page.getByTestId("analise-escola-nome")).toHaveText(ESCOLAS.alfa);
  await expect(page.getByTestId("analise-escola-indicador-saresp")).toContainText("210,3");
  await expect(secao.getByTestId("tabela-series-plataformas")).toContainText("2º ano");
  await expect(page.getByTestId("analise-escola-indisponiveis")).toContainText("ICA");
  // Sem filtro de série nesta tela: o texto não cita um; os títulos seguem h2 › h3 › h4.
  await expect(page.getByTestId("analise-escola-filtros")).toContainText("A tabela mostra cada série do 1º ao 5º ano");
  await expect(secao.getByRole("heading", { level: 4, name: "SARESP" })).toBeVisible();
  // A meta e a diferença da rede de referência (o ICA só chega como referência).
  await expect(page.getByTestId("analise-escola-indicador-ica")).toContainText("meta 60% · −2 p.p. · não atingiu a meta");
  // Contraste do texto (AA) na seção, com os recolhidos abertos.
  await abrirRecolhidos(page, "[data-testid=analise-escola]", 12);
  const falhas = await contrasteDoTexto(page, "[data-testid=analise-escola]");
  expect(falhas, falhas.join("\n")).toEqual([]);
  // Sem ranking: nenhuma outra escola da rede aparece na seção.
  for (const outra of [ESCOLAS.beta, ESCOLAS.delta, ESCOLAS.gama, ESCOLAS.ebano]) {
    await expect(secao).not.toContainText(outra);
  }
  await semErroNaTela(page);
  await capturar(page, "coordenador-visao-escola");

  // As telas da REDE não são do coordenador: cada rota (as três áreas, a ficha da PRÓPRIA escola
  // e as que saíram do menu da Secretaria) redireciona, e nada de /redes/*/analise.
  const id = await escolaDaConta(page);
  for (const rota of [...ROTAS_DA_REDE, `/rede/escolas/${id}`, `/rede/escolas?comparar=${id}`]) {
    await page.goto(rota);
    await page.waitForURL((u) => u.pathname === "/");
  }
  await page.waitForLoadState("networkidle");
  expect(v.analise.filter((c) => c.caminho.includes("/redes/"))).toEqual([]);
  expect(v.analise.every((c) => /\/escolas\/\d+\/analise/.test(c.caminho))).toBe(true);
  expect(v.problemas, v.problemas.join("\n")).toEqual([]);
});

// --- Professor: nem rota nem chamada ----------------------------------------------------------

test("professor é redirecionado de todas as telas da rede (inclusive a ficha) e nenhuma chamada /analise sai", async ({ page }) => {
  const v = vigiar(page);
  await entrar(page, CONTAS.prof);
  await page.waitForLoadState("networkidle");
  const id = await escolaDaConta(page);
  for (const rota of [...ROTAS_DA_REDE, `/rede/escolas/${id}`]) {
    await page.goto(rota);
    await page.waitForURL((u) => u.pathname === "/");
  }
  await page.waitForLoadState("networkidle");
  await expect(page.getByRole("heading", { name: "Análises avançadas" })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Análise educacional" })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Panorama da Rede" })).toHaveCount(0);
  // A Visão da Escola também é de gestão: o professor volta ao Dashboard.
  await page.goto("/escola");
  await page.waitForURL((u) => u.pathname === "/");
  await page.waitForLoadState("networkidle");
  await expect(page.getByTestId("analise-escola")).toHaveCount(0);
  expect(v.analise, JSON.stringify(v.analise)).toEqual([]);
  expect(v.problemas, v.problemas.join("\n")).toEqual([]);
});
