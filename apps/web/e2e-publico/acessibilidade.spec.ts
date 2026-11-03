/**
 * Acessibilidade básica das telas públicas (vitrine da rede e telão da escola), com
 * dados INVENTADOS. Sem @axe-core no node_modules (nada é instalado nesta rodada),
 * as regras são medidas aqui mesmo:
 *
 *  - CONTRASTE pelos PIXELS: o fundo do telão não é a cor de um ancestral (é o céu
 *    em camadas absolutas: gradiente, nebulosas, estrelas), então a cor de fundo
 *    vem da própria captura — o texto fica transparente, a tela é fotografada e,
 *    na caixa de cada texto, o fundo é o pixel do percentil 90 de luminância (o
 *    mais claro "típico": uma estrelinha isolada não decide). AA: 4,5:1 (3:1 no
 *    texto grande: ≥ 24 px, ou ≥ 18,66 px em negrito);
 *  - teclado: ordem do Tab no telão (Pausar → Modo TV → pontos), foco visível
 *    (contorno âmbar de 3 px), Enter e Espaço acionam o ponto focado;
 *  - nomes: todo botão (vários são só ícone) tem nome acessível;
 *  - "reduzir movimento": os efeitos de interface param; o CÉU continua vivo por
 *    decisão do dono (commits b261b3e e e0f083f) — conferido, não alterado.
 */
import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

import { VITRINE, simularPainel, simularVitrine } from "./dados";

const URL_TELAO = "/p/tok-a11y";
const URL_VITRINE = "/rede/p/tok-a11y";
const SLIDES = ["Ranking Geral", "Quem mais cresceu", "Estrelas em Destaque", "Mural da Escola"];

/**
 * Contraste medido na captura. Devolve as falhas ("razão < mínimo — texto").
 * Só entra texto com letra ou número (emoji e "·" não são texto a ler), visível,
 * dentro da janela e fora de [aria-hidden]/.sr-only/fundo decorativo.
 */
async function contrastePorPixel(page: Page, rotulo: string): Promise<string[]> {
  const total = await page.evaluate(() => {
    let i = 0;
    for (const el of document.querySelectorAll<HTMLElement>("body *")) {
      if (el.closest("[aria-hidden=true], .sr-only, [data-fundo-constela], svg, script, style")) continue;
      const proprio = [...el.childNodes].filter((n) => n.nodeType === 3).map((n) => n.textContent ?? "").join("").trim();
      if (!/[\p{L}\p{N}]/u.test(proprio)) continue;
      const r = el.getBoundingClientRect();
      const cs = getComputedStyle(el);
      if (r.width < 1 || r.height < 1 || cs.visibility === "hidden") continue;
      if (r.bottom <= 0 || r.top >= innerHeight || r.right <= 0 || r.left >= innerWidth) continue;
      el.dataset.contraste = String(i++);
      el.dataset.contrasteCor = cs.color;
      el.dataset.contrastePx = cs.fontSize;
      el.dataset.contrastePeso = cs.fontWeight;
      el.dataset.contrasteTexto = proprio.slice(0, 50);
    }
    const estilo = document.createElement("style");
    estilo.id = "contraste-sem-texto";
    estilo.textContent = "[data-contraste]{color:transparent!important;-webkit-text-fill-color:transparent!important;"
      + "text-shadow:none!important;text-decoration-color:transparent!important}";
    document.head.appendChild(estilo);
    return i;
  });
  expect(total, `${rotulo}: nenhum texto medido`).toBeGreaterThan(3);
  // Animações congeladas no quadro inicial: a captura é determinística.
  const png = (await page.screenshot({ animations: "disabled" })).toString("base64");
  const falhas = await page.evaluate(async (b64) => {
    const img = new Image();
    img.src = `data:image/png;base64,${b64}`;
    await img.decode();
    const tela = document.createElement("canvas");
    tela.width = img.width;
    tela.height = img.height;
    const ctx = tela.getContext("2d", { willReadFrequently: true })!;
    ctx.drawImage(img, 0, 0);
    const escala = img.width / innerWidth;
    const lin = (v: number) => { const s = v / 255; return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4; };
    const lum = (c: number[]) => 0.2126 * lin(c[0]) + 0.7152 * lin(c[1]) + 0.0722 * lin(c[2]);
    const achadas: string[] = [];
    for (const el of document.querySelectorAll<HTMLElement>("[data-contraste]")) {
      const r = el.getBoundingClientRect();
      const x = Math.max(0, Math.floor(r.left * escala));
      const y = Math.max(0, Math.floor(r.top * escala));
      const w = Math.min(img.width - x, Math.ceil(r.width * escala));
      const h = Math.min(img.height - y, Math.ceil(r.height * escala));
      if (w < 1 || h < 1) continue;
      const px = ctx.getImageData(x, y, w, h).data;
      const amostras: { l: number; c: number[] }[] = [];
      const passo = Math.max(1, Math.floor((w * h) / 4000));
      for (let i = 0; i < w * h; i += passo) {
        const c = [px[i * 4], px[i * 4 + 1], px[i * 4 + 2]];
        amostras.push({ l: lum(c), c });
      }
      amostras.sort((a, b) => a.l - b.l);
      const fundo = amostras[Math.floor(amostras.length * 0.9)].c;
      const [cr, cg, cb, ca = 1] = (el.dataset.contrasteCor!.match(/[\d.]+/g) ?? []).map(Number);
      const frente = [cr, cg, cb].map((v, i) => v * ca + fundo[i] * (1 - ca));
      const [l1, l2] = [lum(frente), lum(fundo)].sort((a, b) => b - a);
      const razao = (l1 + 0.05) / (l2 + 0.05);
      const tamanho = parseFloat(el.dataset.contrastePx!);
      const grande = tamanho >= 24 || (Number(el.dataset.contrastePeso) >= 700 && tamanho >= 18.66);
      const minimo = grande ? 3 : 4.5;
      if (razao < minimo) {
        achadas.push(`${razao.toFixed(2)}:1 < ${minimo} — "${el.dataset.contrasteTexto}" (${el.dataset.contrasteCor} sobre rgb(${fundo.join(",")}), ${tamanho}px)`);
      }
    }
    for (const el of document.querySelectorAll<HTMLElement>("[data-contraste]")) {
      for (const k of ["contraste", "contrasteCor", "contrastePx", "contrastePeso", "contrasteTexto"]) delete el.dataset[k];
    }
    document.getElementById("contraste-sem-texto")?.remove();
    return achadas;
  }, png);
  return falhas.map((f) => `${rotulo}: ${f}`);
}

for (const tela of [{ largura: 375, altura: 812, movel: true }, { largura: 1366, altura: 768 }, { largura: 1920, altura: 1080 }]) {
  test.describe(`contraste ${tela.largura}x${tela.altura}`, () => {
    test.use({ viewport: { width: tela.largura, height: tela.altura }, isMobile: !!tela.movel, hasTouch: !!tela.movel });

    test("telão: texto com contraste AA em cada slide", async ({ page }) => {
      await simularPainel(page);
      await page.goto(URL_TELAO);
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      await page.evaluate(() => document.fonts.ready);
      const falhas: string[] = [];
      for (const titulo of SLIDES) {
        await page.getByRole("button", { name: `Ir para ${titulo}` }).click();
        await expect(page.getByRole("heading", { level: 2 })).toHaveText(titulo);
        await page.mouse.move(0, 0);
        falhas.push(...(await contrastePorPixel(page, titulo)));
      }
      expect(falhas, falhas.join("\n")).toEqual([]);
    });

    test("vitrine: texto com contraste AA", async ({ page }) => {
      await simularVitrine(page);
      await page.goto(URL_VITRINE);
      await expect(page.getByRole("heading", { level: 1 })).toHaveText(VITRINE.rede_nome);
      await page.evaluate(() => document.fonts.ready);
      const falhas = await contrastePorPixel(page, "vitrine");
      expect(falhas, falhas.join("\n")).toEqual([]);
    });
  });
}

test.describe("telão pelo teclado (1366x768)", () => {
  test.use({ viewport: { width: 1366, height: 768 } });

  test("ordem do Tab, foco visível âmbar e Enter/Espaço acionam o ponto focado", async ({ page }) => {
    await simularPainel(page);
    await page.goto(URL_TELAO);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    const esperados = [/Pausar carrossel/, /Modo TV/, ...SLIDES.map((t) => new RegExp(`^Ir para ${t}$`))];
    for (const nome of esperados) {
      await page.keyboard.press("Tab");
      const foco = page.getByRole("button", { name: nome });
      await expect(foco).toBeFocused();
      const contorno = await foco.evaluate((el) => {
        const cs = getComputedStyle(el);
        return { estilo: cs.outlineStyle, largura: parseFloat(cs.outlineWidth), cor: cs.outlineColor };
      });
      expect(contorno, `foco invisível em ${nome}`).toEqual({ estilo: "solid", largura: 3, cor: "rgb(252, 211, 77)" });
    }
    // Enter no ponto focado (o último: Mural) troca o slide e marca o ponto atual.
    await page.keyboard.press("Enter");
    await expect(page.getByRole("heading", { level: 2 })).toHaveText("Mural da Escola");
    await expect(page.getByRole("button", { name: "Ir para Mural da Escola" })).toHaveAttribute("aria-current", "true");
    // Espaço num ponto focado aciona O PONTO (antes o atalho global de pausar o engolia).
    await page.keyboard.press("Shift+Tab");
    await expect(page.getByRole("button", { name: "Ir para Estrelas em Destaque" })).toBeFocused();
    await page.keyboard.press(" ");
    await expect(page.getByRole("heading", { level: 2 })).toHaveText("Estrelas em Destaque");
    await expect(page.getByRole("button", { name: /Pausar carrossel/ }), "Espaço no ponto pausou o carrossel")
      .toBeVisible();
    // Fora de um botão, Espaço segue sendo o atalho de pausar.
    await page.locator("main").click({ position: { x: 5, y: 5 } });
    await page.keyboard.press(" ");
    await expect(page.getByRole("button", { name: /Retomar carrossel/ })).toBeVisible();
  });

  test("todo botão tem nome acessível e as posições são lidas por extenso", async ({ page }) => {
    await simularPainel(page);
    await page.goto(URL_TELAO);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    const semNome = await page.evaluate(() => [...document.querySelectorAll("button")]
      .filter((b) => !b.closest("[aria-hidden=true]"))
      .filter((b) => !(b.getAttribute("aria-label") || b.textContent || "").trim())
      .map((b) => b.outerHTML.slice(0, 80)));
    expect(semNome).toEqual([]);
    // Ranking: "1º lugar" etc. em texto (o emoji é decorativo).
    for (const p of [1, 2, 3]) await expect(page.locator("main .sr-only", { hasText: `${p}º lugar` })).toHaveCount(1);
    await expect(page.locator("main [data-barra]").nth(3).locator("..")).toContainText("4º lugar");
    // Pódio: posição por extenso na medalha; iniciais do avatar fora do leitor.
    await page.getByRole("button", { name: "Ir para Estrelas em Destaque" }).click();
    await expect(page.locator(".painel-podio-grade .sr-only", { hasText: /º lugar/ })).toHaveCount(3);
    await expect(page.locator(".painel-podio-grade [aria-hidden=true]", { hasText: "BC" })).toHaveCount(1);
  });
});

test.describe("reduzir movimento (padrão do config)", () => {
  test.use({ viewport: { width: 1366, height: 768 } });

  test("efeitos de interface parados; o céu segue vivo (decisão do dono)", async ({ page }) => {
    await simularPainel(page);
    await page.goto(URL_TELAO);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    expect(await page.evaluate(() => matchMedia("(prefers-reduced-motion: reduce)").matches)).toBe(true);
    await page.getByRole("button", { name: "Ir para Estrelas em Destaque" }).click();
    const m = await page.evaluate(() => {
      const anim = (sel: string) => getComputedStyle(document.querySelector(sel)!).animationName;
      return {
        surgir: anim(".painel-surgir"), flutua: anim(".painel-flutua"), pulso: anim(".painel-pulso"),
        brilho: getComputedStyle(document.querySelector(".painel-brilho")!, "::after").animationName,
        estrela: anim("[data-fundo-constela] .painel-estrela"), cadente: anim(".painel-cadente"),
      };
    });
    expect(m).toEqual({
      surgir: "none", flutua: "none", pulso: "none", brilho: "none",
      estrela: "painel-cintila", cadente: "painel-cadente",
    });
  });
});
