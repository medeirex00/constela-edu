/**
 * CONTRATO das telas públicas nas 6 telas da auditoria de 20/10 — celular 320×568
 * e 375×812, tablet 768×1024, notebook 1366×768, Full HD 1920×1080 e TV 4K
 * 3840×2160 — com dados INVENTADOS (e2e-publico/dados.ts e os desta página):
 *
 *  - ZERO rolagem horizontal pela régua pedida (document.scrollingElement.scrollWidth
 *    ≤ innerWidth) e nenhum bloco de conteúdo passando da borda (na TV a raiz do
 *    telão corta o excesso, então a régua da página sozinha não acusaria);
 *  - telão: no celular o nome COMPLETO do aluno aparece (quebra linha); na TV, uma
 *    linha com o nome inteiro no title; a coluna de posição nunca é cortada;
 *  - empates: a vitrine dá a MESMA posição a valores iguais (1º, 1º, 3º); o telão
 *    mostra a posição que o servidor mandou (não renumera);
 *  - ausência aparece como ausência ("—" / "sem dado" / "Sem dados ainda."), nunca 0;
 *  - estados de erro (404 e 503) e de carregamento cabem na tela.
 * A versão de TV (palco medido, "+ N", pódio 2-1-3, 4K) segue coberta por
 * telao.spec.ts e vitrine.spec.ts — este arquivo não afrouxa nada de lá.
 */
import path from "node:path";

import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

import { PAINEL, PASTA_CAPTURAS, VITRINE, ehTelaoCelular, nomeDaTela, simularPainel, simularVitrine } from "./dados";
import type { Tela } from "./dados";

const URL_TELAO = "/p/tok-contrato";
const URL_VITRINE = "/rede/p/tok-contrato";
const SLIDES = ["Ranking Geral", "Quem mais cresceu", "Estrelas em Destaque", "Mural da Escola"];

const TELAS_CONTRATO: Tela[] = [
  { largura: 320, altura: 568, movel: true },
  { largura: 375, altura: 812, movel: true },
  { largura: 768, altura: 1024, movel: true },
  { largura: 1366, altura: 768 },
  { largura: 1920, altura: 1080 },
  { largura: 3840, altura: 2160 },
];

/** Nomes COMPLETOS inventados (a escola pode desligar a anonimização): os mais
 *  longos que um telão vai ver, inclusive uma palavra composta sem espaço. */
const NOMES_LONGOS = [
  "Aluna Teste Anastácia Valadares de Albuquerque Nascimento",
  "Aluno Teste Baltazar Quintino da Silveira Luz Filho",
  "Aluna Teste Celestina Bitencourt Guimarães de Souza",
  "Aluno Teste Dorival-Constelação-Esteves-Machado",
  "Aluna Teste Elisa Floripes Tavares Rocha Neta",
  "Aluno Teste Fábio Geraldino Hortêncio Lima Barros",
  "Aluna Teste Gabriela Iara Joaquina Kátia Lemos",
  "Aluno Teste Heitor Ismael Jordão Kauã Leite",
  "Aluna Teste Iracema Jussara Kelly Lorena Mota",
  "Aluno Teste Joaquim Lauro Moisés Nogueira Prado",
];
/** Empate vindo do servidor: o telão mostra a posição do payload (1º, 1º, 3º…). */
const POSICOES_EMPATE = [1, 1, 3, 4, 5, 6, 7, 8, 9, 10];

const PAINEL_NOMES_LONGOS = {
  ...PAINEL,
  ranking: PAINEL.ranking.map((item, i) => ({ ...item, nome: NOMES_LONGOS[i], posicao: POSICOES_EMPATE[i] })),
  evolucao: PAINEL.evolucao.map((item, i) => ({ ...item, nome: NOMES_LONGOS[i] })),
};

/** Vitrine com dois empates: no topo (3,1 e 3,1) e no fim (1,2 e 1,2). */
const VITRINE_EMPATE = {
  ...VITRINE,
  top_leitura: [
    { nome: "EMEF FICTÍCIA ALFA DO EMPATE NO PRIMEIRO LUGAR DA REDE", valor: 3.1 },
    { nome: "EMEF FICTÍCIA BETA DO EMPATE NO PRIMEIRO LUGAR DA REDE", valor: 3.1 },
    { nome: "EMEF FICTÍCIA GAMA LOGO ABAIXO DAS DUAS EMPATADAS", valor: 2.4 },
    { nome: "EMEF FICTÍCIA DELTA EMPATADA NO QUARTO LUGAR DA REDE", valor: 1.2 },
    { nome: "EMEF FICTÍCIA ÉPSILON EMPATADA NO QUARTO LUGAR DA REDE", valor: 1.2 },
  ],
};

/** Três quadros: ResizeObserver mede e o React re-renderiza. */
async function assentar(page: Page) {
  await page.evaluate(() => new Promise<void>((ok) =>
    requestAnimationFrame(() => requestAnimationFrame(() => requestAnimationFrame(() => ok())))));
}

/** A régua da auditoria + os blocos de conteúdo dentro da largura da janela. */
async function semRolagemLateral(page: Page, rotulo: string) {
  const m = await page.evaluate(() => {
    const iw = window.innerWidth;
    const fora = [...document.querySelectorAll("header *, main *, section *, footer *, [role=status], .painel-dica")]
      .filter((el) => {
        if (el.closest("[data-fundo-constela], .sr-only")) return false;
        const r = el.getBoundingClientRect();
        return r.width > 0 && r.height > 0 && (r.right > iw + 0.5 || r.left < -0.5);
      })
      .map((el) => `${el.tagName}.${String(el.getAttribute("class")).slice(0, 40)}`);
    return { sw: document.scrollingElement!.scrollWidth, iw, fora };
  });
  expect(m.sw, `${rotulo}: rolagem horizontal (scrollWidth ${m.sw} > innerWidth ${m.iw})`).toBeLessThanOrEqual(m.iw);
  expect(m.fora, `${rotulo}: conteúdo passa da borda`).toEqual([]);
}

/** Linhas do ranking do telão: nome, posição e caixas (para corte e reticências). */
async function linhasDoTelao(page: Page) {
  return page.evaluate(() => [...document.querySelectorAll("main [data-barra]")].map((barra) => {
    const linha = barra.parentElement!;
    const posicao = linha.children[1] as HTMLElement;            // [0] é a barra
    const nome = linha.querySelector("[data-nome-aluno]") as HTMLElement;
    const r = linha.getBoundingClientRect();
    const rp = posicao.getBoundingClientRect();
    const cs = getComputedStyle(nome);
    // Palavra partida no meio (ex.: "Albuquerqu|e"): a faixa da palavra ocupa 2+ linhas.
    // Hífen é ponto de quebra legítimo, então conta cada pedaço entre espaços/hífens.
    const texto = nome.firstChild as Text | null;
    const partidas: string[] = [];
    if (texto) {
      for (const m of (texto.data).matchAll(/[^\s-]+/g)) {
        const faixa = document.createRange();
        faixa.setStart(texto, m.index!);
        faixa.setEnd(texto, m.index! + m[0].length);
        const linhas = new Set([...faixa.getClientRects()].map((q) => Math.round(q.top)));
        if (linhas.size > 1) partidas.push(m[0]);
      }
    }
    return {
      partidas,
      texto: nome.textContent ?? "",
      title: nome.getAttribute("title"),
      reticencias: cs.textOverflow === "ellipsis" && nome.scrollWidth > nome.clientWidth + 1,
      nomeCortado: nome.scrollWidth > nome.clientWidth + 1 || nome.scrollHeight > nome.clientHeight + 1,
      posicaoLida: posicao.textContent ?? "",
      posicaoCortada: posicao.scrollWidth > posicao.clientWidth + 1
        || rp.left < r.left - 0.5 || rp.right > r.right + 0.5 || rp.left < -0.5 || rp.right > window.innerWidth + 0.5,
    };
  }));
}

for (const tela of TELAS_CONTRATO) {
  const nome = nomeDaTela(tela);
  const celular = ehTelaoCelular(tela);

  test.describe(`contrato ${nome}`, () => {
    test.use({
      viewport: { width: tela.largura, height: tela.altura },
      isMobile: !!tela.movel,
      hasTouch: !!tela.movel,
    });

    test("vitrine: sem rolagem lateral, empate com a mesma posição e posição inteira", async ({ page }) => {
      await simularVitrine(page, VITRINE_EMPATE);
      await page.goto(URL_VITRINE);
      await expect(page.getByRole("heading", { level: 1 })).toHaveText(VITRINE.rede_nome);
      await page.evaluate(() => document.fonts.ready);
      await semRolagemLateral(page, "vitrine");
      const leitura = page.getByRole("region", { name: "Leitura" });
      const posicoes = await leitura.locator(".vitrine-medalha").evaluateAll((els) => els.map((el) => {
        const r = el.getBoundingClientRect();
        const linha = el.closest("li")!.getBoundingClientRect();
        return {
          lida: (el.textContent ?? "").match(/\d+º lugar/)?.[0],
          dentro: r.left >= linha.left - 0.5 && r.right <= linha.right + 0.5,
          inteira: el.scrollWidth <= el.clientWidth + 1,
        };
      }));
      expect(posicoes.map((p) => p.lida)).toEqual(["1º lugar", "1º lugar", "3º lugar", "4º lugar", "4º lugar"]);
      for (const p of posicoes) expect(p.dentro && p.inteira, `posição cortada: ${p.lida}`).toBe(true);
      // Mesma medalha para as empatadas do topo.
      const emojis = await leitura.locator(".vitrine-medalha [aria-hidden]").allTextContents();
      expect(emojis.slice(0, 3)).toEqual(["🥇", "🥇", "🥉"]);
      await page.screenshot({ path: path.join(PASTA_CAPTURAS, `contrato-vitrine-empate-${nome}.png`), fullPage: true });
    });

    test("telão: cada slide sem rolagem lateral, nome do aluno inteiro e posição sem corte", async ({ page }) => {
      await simularPainel(page, PAINEL_NOMES_LONGOS);
      await page.goto(URL_TELAO);
      await expect(page.getByRole("heading", { level: 1 })).toHaveText(PAINEL.escola.nome);
      await page.evaluate(() => document.fonts.ready);
      await expect(page.locator("[data-modo]")).toHaveAttribute("data-modo", celular ? "celular" : "tv");
      for (const titulo of SLIDES) {
        await page.getByRole("button", { name: `Ir para ${titulo}` }).click();
        await expect(page.getByRole("heading", { level: 2 })).toHaveText(titulo);
        await assentar(page);
        await semRolagemLateral(page, `telão ${titulo}`);
        if (titulo === "Ranking Geral" || titulo === "Quem mais cresceu") {
          const linhas = await linhasDoTelao(page);
          expect(linhas.length).toBeGreaterThanOrEqual(3);
          for (const l of linhas) {
            expect(l.title, "nome completo no title").toBe(l.texto);
            expect(l.posicaoCortada, `posição cortada: ${l.posicaoLida}`).toBe(false);
            if (celular) {
              // Celular: o nome COMPLETO aparece — sem reticências, sem recorte.
              expect(l.reticencias, `nome com reticências: ${l.texto}`).toBe(false);
              expect(l.nomeCortado, `nome cortado: ${l.texto}`).toBe(false);
              expect(l.partidas, `palavra quebrada no meio: ${l.texto}`).toEqual([]);
            }
          }
          if (celular) expect(linhas.map((l) => l.texto)).toEqual(NOMES_LONGOS);
          if (titulo === "Ranking Geral") {
            // Empate do servidor exibido como veio: duas medalhas de ouro e o 3º.
            expect(linhas.slice(0, 3).map((l) => l.posicaoLida)).toEqual([
              expect.stringContaining("1º lugar"), expect.stringContaining("1º lugar"), expect.stringContaining("3º lugar")]);
          }
        }
        const arquivo = `contrato-telao-${nome}-${titulo.split(" ")[0].toLowerCase()}.png`;
        await page.screenshot({ path: path.join(PASTA_CAPTURAS, arquivo), fullPage: celular });
      }
    });

    test("ausência é ausência: '—'/'sem dado' e listas vazias por extenso, nunca 0", async ({ page }) => {
      // Telão: a 2ª criança sem o valor da evolução, a faixa sem livros (plataforma
      // sem coleta), o pódio sem o Aluno do Mês e o mural vazio.
      await simularPainel(page, {
        ...PAINEL,
        slides: ["evolucao", "destaques", "mural"],
        evolucao: PAINEL.evolucao.slice(0, 3).map((item, i) => {
          if (i !== 1) return item;
          const { nota_evolucao: _semValor, ...resto } = item;
          return resto;
        }),
        destaques: { ...PAINEL.destaques, mes: null },
        estatisticas: { ...PAINEL.estatisticas, livros: null },
        mural: [],
      });
      await page.goto(URL_TELAO);
      await expect(page.getByRole("heading", { level: 2 })).toHaveText("Quem mais cresceu");
      await assentar(page);
      const linhaSemValor = page.locator("main [data-barra]").nth(1).locator("..");
      await expect(linhaSemValor).toContainText("sem dado");
      await expect(linhaSemValor).toContainText("—");
      await expect(linhaSemValor).not.toContainText(/\b0,0\b/);
      expect(await linhaSemValor.locator("[data-barra]").evaluate((el) => el.getBoundingClientRect().width)).toBe(0);
      const numeros = page.getByRole("region", { name: "Números da escola" });
      await expect(numeros).toContainText("sem dado");
      await expect(numeros).toContainText("1.234");                 // os outros números seguem
      await semRolagemLateral(page, "telão com ausências");
      await page.getByRole("button", { name: "Ir para Estrelas em Destaque" }).click();
      await expect(page.getByText("Sem destaque no período.")).toBeVisible();
      await page.getByRole("button", { name: "Ir para Mural da Escola" }).click();
      await expect(page.getByText("Nada no mural ainda.")).toBeVisible();
      await semRolagemLateral(page, "telão mural vazio");
      await page.screenshot({ path: path.join(PASTA_CAPTURAS, `contrato-telao-ausencia-${nome}.png`), fullPage: celular });

      // Vitrine sem nenhuma escola com dado: o texto, não uma lista de zeros.
      await page.unrouteAll({ behavior: "ignoreErrors" });
      await simularVitrine(page, { ...VITRINE, top_leitura: [], top_matematica: [] });
      await page.goto(URL_VITRINE);
      await expect(page.getByText("Sem dados ainda.")).toHaveCount(2);
      await expect(page.locator(".vitrine-valor")).toHaveCount(0);
      await semRolagemLateral(page, "vitrine vazia");
    });

    test("erro (404, 503) e carregamento cabem na tela e são anunciados", async ({ page }) => {
      const casos = [
        { url: URL_TELAO, padrao: /^\/api\/v1\/publico\/[^/]+\/painel$/, status: 404, texto: "Painel não encontrado ou desativado." },
        { url: URL_TELAO, padrao: /^\/api\/v1\/publico\/[^/]+\/painel$/, status: 503, texto: "Reconectando ao painel..." },
        { url: URL_VITRINE, padrao: /^\/api\/v1\/publico\/rede\/[^/]+$/, status: 404, texto: "Vitrine não encontrada ou desativada." },
        { url: URL_VITRINE, padrao: /^\/api\/v1\/publico\/rede\/[^/]+$/, status: 503, texto: "Reconectando à vitrine..." },
      ];
      for (const caso of casos) {
        await page.unrouteAll({ behavior: "ignoreErrors" });
        await simularPainel(page);
        await page.route((u) => caso.padrao.test(u.pathname), (rota) =>
          rota.fulfill({ status: caso.status, json: { detail: "simulado" } }));
        await page.goto(caso.url);
        const aviso = page.getByRole("status").filter({ hasText: caso.texto });
        await expect(aviso).toBeVisible({ timeout: 15_000 });
        await expect(aviso).toBeInViewport({ ratio: 1 });
        await semRolagemLateral(page, `${caso.url} ${caso.status}`);
      }
      // Carregando (resposta segurada): o aviso também cabe.
      await page.unrouteAll({ behavior: "ignoreErrors" });
      let liberar = () => {};
      const segura = new Promise<void>((ok) => { liberar = ok; });
      await simularPainel(page);
      await page.route((u) => /^\/api\/v1\/publico\/[^/]+\/painel$/.test(u.pathname), async (rota) => {
        await segura;
        await rota.fulfill({ json: PAINEL });
      });
      await page.goto(URL_TELAO);
      await expect(page.getByRole("status")).toHaveText(/Carregando painel/);
      await expect(page.getByRole("status")).toBeInViewport({ ratio: 1 });
      await semRolagemLateral(page, "telão carregando");
      liberar();
      await expect(page.getByRole("heading", { level: 1 })).toHaveText(PAINEL.escola.nome);
    });
  });
}
