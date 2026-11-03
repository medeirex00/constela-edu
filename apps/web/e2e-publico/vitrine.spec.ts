/**
 * Vitrine pública da rede (/rede/p/:token) em todas as larguras do contrato:
 * sem rolagem horizontal, nomes de escola inteiros e legíveis, valores sem
 * corte, 1 coluna no estreito × 2 colunas na TV (a partir de 800×440: projetor
 * 800×600 e painel 854×480), 1 coluna larga no totem em retrato, cabe na altura
 * das TVs, 4K proporcional (sem "ilha"), decoração muda e longe do texto, o céu
 * vivo mesmo com "reduzir movimento" (pedido do dono) e a barra relativa visível.
 */
import path from "node:path";

import { expect, test } from "@playwright/test";

import {
  MEDIA_MODO_TV, MEDIA_TOTEM, PASTA_CAPTURAS, TELAS, TELAS_TV, VITRINE, cruzam, ehModoTv, ehTotem, nomeDaTela,
  simularVitrine,
} from "./dados";

const URL_VITRINE = "/rede/p/tok-vitrine-teste";

test("fixture: nomes inventados de 40–55 caracteres e valores de 1 a 4 dígitos", () => {
  for (const e of [...VITRINE.top_leitura, ...VITRINE.top_matematica]) {
    expect(e.nome.length).toBeGreaterThanOrEqual(40);
    expect(e.nome.length).toBeLessThanOrEqual(55);
    expect(Math.trunc(e.valor).toString().length).toBeLessThanOrEqual(4);
  }
});

for (const tela of TELAS) {
  const nome = nomeDaTela(tela);
  const tv = ehModoTv(tela);
  const totem = ehTotem(tela);

  test.describe(`vitrine ${nome}`, () => {
    test.use({
      viewport: { width: tela.largura, height: tela.altura },
      isMobile: !!tela.movel,
      hasTouch: !!tela.movel,
    });

    test("layout responsivo, nomes legíveis e decoração fora do texto", async ({ page }) => {
      await simularVitrine(page);
      await page.goto(URL_VITRINE);
      await expect(page.getByRole("heading", { level: 1 })).toHaveText(VITRINE.rede_nome);
      await page.evaluate(() => document.fonts.ready);

      // O modo do CSS é o esperado para esta tela.
      const modoTv = await page.evaluate((m) => matchMedia(m).matches, MEDIA_MODO_TV);
      expect(modoTv).toBe(tv);
      const modoTotem = await page.evaluate((m) => matchMedia(m).matches, MEDIA_TOTEM);
      expect(modoTotem).toBe(totem);

      // (1) Sem rolagem horizontal.
      const doc = await page.evaluate(() => ({
        sw: document.documentElement.scrollWidth,
        cw: document.documentElement.clientWidth,
        sh: document.documentElement.scrollHeight,
        ih: window.innerHeight,
      }));
      expect(doc.sw, "rolagem horizontal").toBeLessThanOrEqual(doc.cw);

      // (4) Nas resoluções de TV, cabeçalho + 5 + 5 + rodapé cabem sem rolar.
      if (TELAS_TV.has(nome)) {
        expect(doc.sh, "a vitrine passou da altura da TV").toBeLessThanOrEqual(doc.ih);
      }

      // (5/7) Duas listas ordenadas com 5 itens; medalhas com texto acessível.
      const listas = page.locator("section ol");
      await expect(listas).toHaveCount(2);
      for (let i = 0; i < 2; i++) await expect(listas.nth(i).locator("> li")).toHaveCount(5);
      await expect(page.getByText("1º lugar", { exact: true })).toHaveCount(2);
      await expect(page.getByText("3º lugar", { exact: true })).toHaveCount(2);

      // (3) Nomes: inteiros, dentro da tela, fonte legível; na TV, até 2 linhas.
      const nomes = await page.locator(".vitrine-nome").evaluateAll((els) => els.map((el) => {
        const r = el.getBoundingClientRect();
        const cs = getComputedStyle(el);
        const lh = parseFloat(cs.lineHeight);
        const visiveis = Math.round(el.clientHeight / lh);
        // Quantas linhas o nome PRECISA (sem o limite de 2 linhas do modo TV):
        // se for mais do que as visíveis, houve corte com reticências.
        const h = el as HTMLElement;
        const antes = h.getAttribute("style") ?? "";
        h.style.setProperty("display", "block");
        h.style.setProperty("-webkit-line-clamp", "none");
        h.style.setProperty("overflow", "visible");
        const necessarias = Math.round(h.clientHeight / lh);
        h.setAttribute("style", antes);
        return {
          texto: el.textContent ?? "", title: el.getAttribute("title"),
          sw: el.scrollWidth, cw: el.clientWidth, visiveis, necessarias,
          fonte: parseFloat(cs.fontSize), esq: r.left, dir: r.right,
        };
      }));
      const largura = doc.cw;
      expect(nomes).toHaveLength(10);
      for (const n of nomes) {
        expect(n.title, "title com o nome completo").toBe(n.texto);
        expect(n.sw, `nome cortado na horizontal: ${n.texto}`).toBeLessThanOrEqual(n.cw + 1);
        expect(n.visiveis, `nome cortado (reticências): ${n.texto}`).toBe(n.necessarias);
        expect(n.esq).toBeGreaterThanOrEqual(0);
        expect(n.dir).toBeLessThanOrEqual(largura);
        expect(n.fonte, "fonte do nome pequena demais").toBeGreaterThanOrEqual(12);
        if (tv || totem) expect(n.visiveis, `mais de 2 linhas na TV: ${n.texto}`).toBeLessThanOrEqual(2);
      }
      // Os nomes com prefixo comum continuam distinguíveis (texto inteiro no DOM).
      const textos = new Set(nomes.map((n) => n.texto));
      expect(textos.size).toBe(9); // uma escola aparece nas duas matérias

      // (5) Valores inteiros ("1.234,5"), com tabular-nums, sem corte na linha.
      const valores = await page.locator(".vitrine-valor").evaluateAll((els) => els.map((el) => {
        const r = el.getBoundingClientRect();
        const linha = el.closest("li")!.getBoundingClientRect();
        return {
          texto: el.textContent ?? "", sw: el.scrollWidth, cw: el.clientWidth,
          numerico: getComputedStyle(el).fontVariantNumeric, dir: r.right, linhaDir: linha.right,
        };
      }));
      expect(valores.map((v) => v.texto)).toContain("1.234,5");
      for (const v of valores) {
        expect(v.sw, `valor cortado: ${v.texto}`).toBeLessThanOrEqual(v.cw + 1);
        expect(v.dir).toBeLessThanOrEqual(v.linhaDir + 0.5);
        expect(v.numerico).toContain("tabular-nums");
      }

      // (2) Cartões: 1 coluna no estreito; 2 lado a lado na TV, com teto e centrados.
      const cartoes = await page.locator("section.vitrine-cartao").evaluateAll((els) =>
        els.map((el) => el.getBoundingClientRect().toJSON() as DOMRect));
      const rem = await page.evaluate(() => parseFloat(getComputedStyle(document.documentElement).fontSize));
      expect(cartoes).toHaveLength(2);
      if (tv) {
        expect(Math.abs(cartoes[0].top - cartoes[1].top)).toBeLessThan(1);
        expect(cartoes[1].left).toBeGreaterThan(cartoes[0].right);
      } else {
        expect(cartoes[1].top).toBeGreaterThanOrEqual(cartoes[0].bottom);
      }
      if (totem) {
        // Totem em retrato: 1 coluna que ocupa ~90% da largura (não a "ilha" de
        // 56rem no meio da tela) e tipografia escalada pela largura.
        for (const c of cartoes) {
          expect(c.width / largura, "cartão estreito demais no totem").toBeGreaterThan(0.85);
          expect(c.width / largura).toBeLessThanOrEqual(0.93);
        }
        expect(Math.min(...nomes.map((n) => n.fonte)), "nome pequeno no totem").toBeGreaterThanOrEqual(0.022 * largura);
      } else {
        for (const c of cartoes) expect(c.width).toBeLessThanOrEqual(56 * rem + 1);
      }
      const sobraEsq = Math.min(...cartoes.map((c) => c.left));
      const sobraDir = largura - Math.max(...cartoes.map((c) => c.right));
      expect(Math.abs(sobraEsq - sobraDir), "bloco de cartões descentralizado").toBeLessThanOrEqual(2);

      // (6) Fundo é decoração: aria-hidden; nenhum astro visível sobre texto.
      await expect(page.locator("[data-fundo-constela]")).toHaveAttribute("aria-hidden", "true");
      const colisoes = await page.evaluate(() => {
        const visivel = (el: Element) => {
          const r = el.getBoundingClientRect();
          return r.width > 0 && r.height > 0 && getComputedStyle(el).display !== "none";
        };
        const astros = [...document.querySelectorAll("[data-astro]")].filter(visivel);
        const textos = [...document.querySelectorAll(
          ".vitrine h1, .vitrine header p, .vitrine h2, .vitrine-unidade, .vitrine li, .vitrine footer span",
        )].filter(visivel);
        const caixa = (el: Element) => {
          const r = el.getBoundingClientRect();
          // Inclui as "hastes" do astro (320% do tamanho, centradas).
          const extra = el.classList.contains("painel-astro") ? r.width * 1.1 : 0;
          return { left: r.left - extra, top: r.top - extra, right: r.right + extra, bottom: r.bottom + extra };
        };
        return { astros: astros.map(caixa), textos: textos.map((t) => ({ ...caixa(t), nome: t.tagName })) };
      });
      for (const a of colisoes.astros) {
        for (const t of colisoes.textos) {
          expect(cruzam(a, t), `astro sobre ${t.nome} em ${JSON.stringify(a)}`).toBe(false);
        }
      }

      // Rodapé: no celular os blocos quebram em linhas sem começar com "·" (o
      // separador é um span próprio que só aparece a partir de sm).
      const rodape = await page.locator("footer.vitrine-rodape > *").evaluateAll((els) => els
        .filter((el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; })
        .map((el) => (el.textContent ?? "").trim()));
      for (const texto of rodape.filter((t) => t.length > 1)) {
        expect(texto.startsWith("·"), `rodapé começa com "·": ${texto}`).toBe(false);
      }
      expect(rodape.join(" ")).toContain("sem dados individuais de estudantes");

      // (4) TV 4K: o <html> escala e o conteúdo ocupa a tela (não vira "ilha").
      if (tela.largura === 3840) {
        expect(rem).toBe(30);
        const ocupacao = (Math.max(...cartoes.map((c) => c.right)) - Math.min(...cartoes.map((c) => c.left))) / largura;
        expect(ocupacao).toBeGreaterThan(0.8);
        expect(Math.min(...nomes.map((n) => n.fonte))).toBeGreaterThanOrEqual(40);
      } else if (tela.largura <= 1920) {
        expect(rem).toBe(16);
      }

      await page.screenshot({ path: path.join(PASTA_CAPTURAS, `vitrine-${nome}.png`), fullPage: true });
    });
  });
}

// Rede com UM módulo no plano: o cartão do outro NÃO aparece (services/modulos.py)
// e o que sobra fica centralizado — no modo TV a grade fixa 2 colunas, e sem a
// classe `vitrine-cartoes-um` o cartão único ficaria na metade esquerda.
const TELAS_UM_MODULO = new Set(["375x812", "800x600", "1366x768", "1920x1080", "3840x2160", "1080x1920"]);
for (const tela of TELAS.filter((t) => TELAS_UM_MODULO.has(nomeDaTela(t)))) {
  const nome = nomeDaTela(tela);
  const tv = ehModoTv(tela);
  const totem = ehTotem(tela);

  test.describe(`vitrine ${nome} com a Matemática fora do plano`, () => {
    test.use({
      viewport: { width: tela.largura, height: tela.altura },
      isMobile: !!tela.movel,
      hasTouch: !!tela.movel,
    });

    test("só o cartão da Leitura, centralizado, sem 'Sem dados ainda.'", async ({ page }) => {
      await simularVitrine(page, { ...VITRINE, top_matematica: [], modulos: ["leitura"] });
      await page.goto(URL_VITRINE);
      await expect(page.getByRole("heading", { level: 1 })).toHaveText(VITRINE.rede_nome);
      await page.evaluate(() => document.fonts.ready);

      await expect(page.getByRole("region", { name: "Leitura" })).toBeVisible();
      await expect(page.getByRole("region", { name: "Matemática" })).toHaveCount(0);
      await expect(page.getByText("Sem dados ainda.")).toHaveCount(0);
      await expect(page.locator("section ol > li")).toHaveCount(5);

      const m = await page.evaluate(() => {
        const cartoes = [...document.querySelectorAll("section.vitrine-cartao")];
        const r = cartoes[0].getBoundingClientRect();
        return {
          quantos: cartoes.length, esq: r.left, dir: r.right, largura: r.width,
          rem: parseFloat(getComputedStyle(document.documentElement).fontSize),
          sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth,
        };
      });
      expect(m.quantos).toBe(1);
      expect(m.sw, "rolagem horizontal").toBeLessThanOrEqual(m.cw);
      expect(Math.abs(m.esq - (m.cw - m.dir)), "cartão único descentralizado").toBeLessThanOrEqual(2);
      if (totem) {
        // Totem: a mesma coluna larga de sempre (~90% da largura).
        expect(m.largura / m.cw).toBeGreaterThan(0.85);
      } else {
        expect(m.largura).toBeLessThanOrEqual(56 * m.rem + 1);   // mesmo teto por cartão
      }
      if (tv) expect(m.largura, "cartão encolhido no modo TV").toBeGreaterThan(0.4 * m.cw);

      await page.screenshot({ path: path.join(PASTA_CAPTURAS, `vitrine-um-modulo-${nome}.png`), fullPage: true });
    });
  });
}

test.describe("vitrine com movimento liberado (1920x1080)", () => {
  test.use({ viewport: { width: 1920, height: 1080 }, contextOptions: { reducedMotion: "no-preference" } });

  test("céu anima e a barra relativa é pintada sobre o fundo da linha", async ({ page }) => {
    await simularVitrine(page);
    await page.goto(URL_VITRINE);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();

    const animacoes = await page.evaluate(() => ({
      cadente: getComputedStyle(document.querySelector(".painel-cadente")!).animationName,
      satelite: getComputedStyle(document.querySelector(".painel-satelite")!).animationName,
      estrela: getComputedStyle(document.querySelector(".painel-estrela")!).animationName,
    }));
    expect(animacoes).toEqual({ cadente: "painel-cadente", satelite: "painel-satelite", estrela: "painel-cintila" });

    // Barra relativa: a linha isola o empilhamento e a barra fica ACIMA do fundo
    // da linha (antes, com -z-10 sem contexto, ia para trás do fundo da página).
    const barra = await page.evaluate(() => {
      const li = document.querySelector(".vitrine li")!;
      const span = li.querySelector("[data-barra]")!;
      const r = span.getBoundingClientRect();
      const pilha = document.elementsFromPoint(r.left + r.width * 0.5, r.bottom - 2);
      return {
        isolamento: getComputedStyle(li).isolation,
        largura: r.width,
        barraAntesDaLinha: pilha.indexOf(span) > -1 && pilha.indexOf(span) < pilha.indexOf(li),
      };
    });
    expect(barra.isolamento).toBe("isolate");
    expect(barra.largura).toBeGreaterThan(0);
    expect(barra.barraAntesDaLinha).toBe(true);
    await page.screenshot({ path: path.join(PASTA_CAPTURAS, "vitrine-1920x1080-movimento.png") });
  });
});

test.describe("vitrine em reduced-motion (padrão do config)", () => {
  test.use({ viewport: { width: 1280, height: 720 } });

  // Decisão do dono (commits b261b3e e e0f083f): o céu é decoração de vitrine e
  // "a graça pedida é justamente o céu vivo" — com "reduzir movimento" (TV-box
  // Android com animações removidas, o próprio desktop do dono) o cintilar, as
  // cadentes e o satélite CONTINUAM. A legibilidade vem do layout: nada brilhante
  // atrás do texto (teste de colisão acima) e o halo das letras do cabeçalho.
  test("o céu continua vivo: cintilar, cadentes e satélite animam", async ({ page }) => {
    await simularVitrine(page);
    await page.goto(URL_VITRINE);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    expect(await page.evaluate(() => matchMedia("(prefers-reduced-motion: reduce)").matches)).toBe(true);
    const nomes = await page.evaluate(() =>
      [".painel-cadente", ".painel-satelite", ".painel-estrela"].map(
        (s) => getComputedStyle(document.querySelector(s)!).animationName));
    expect(nomes).toEqual(["painel-cadente", "painel-satelite", "painel-cintila"]);
    const halo = await page.locator(".vitrine-cabecalho").evaluate((el) => getComputedStyle(el).textShadow);
    expect(halo).not.toBe("none");
  });
});

test.describe("vitrine: falha transitória da recarga", () => {
  test.use({ viewport: { width: 1280, height: 720 } });

  test("mantém o último quadro bom (não pisca para 'Reconectando')", async ({ page }) => {
    await page.clock.install();
    let chamadas = 0;
    let avisarTerceira = () => {};
    const terceiraRespondida = new Promise<void>((resolver) => { avisarTerceira = resolver; });
    await simularVitrine(page);
    await page.route((url) => /^\/api\/v1\/publico\/rede\/[^/]+$/.test(url.pathname), async (rota) => {
      chamadas += 1;
      if (chamadas === 1) {
        await rota.fulfill({ json: VITRINE });
        return;
      }
      await rota.fulfill({ status: 503, json: { detail: "reiniciando" } });
      if (chamadas === 3) avisarTerceira();
    });
    await page.goto(URL_VITRINE);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(VITRINE.rede_nome);

    // Recarga de 60 s: 503. A retentativa do useApi (backoff de 300 ms no relógio
    // falso) só é agendada depois que a página processa esse 503 — por isso o
    // relógio avança aos poucos até a 3ª chamada sair (a 2ª sozinha não prova
    // nada: o erro só chega ao estado depois que a retentativa também falha).
    await page.clock.runFor(61_000);
    await expect.poll(async () => {
      await page.clock.runFor(400);
      return chamadas;
    }).toBeGreaterThanOrEqual(3);
    await terceiraRespondida;
    // Tempo real para o 503 da retentativa virar estado (setErro) e o React
    // renderizar — só então a ausência de "Reconectando" vale alguma coisa.
    await page.waitForTimeout(500);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(VITRINE.rede_nome);
    await expect(page.getByText(/Reconectando|não encontrada/)).toHaveCount(0);
  });
});
