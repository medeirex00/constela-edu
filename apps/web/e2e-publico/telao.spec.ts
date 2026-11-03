/**
 * Telão da escola (/p/:token): na TV a raiz tem overflow-hidden, então
 * document.scrollWidth NUNCA acusa transbordo — aqui se mede a CAIXA de cada
 * elemento do cabeçalho. Com nome de escola longo, Pausar e Modo TV têm de
 * ficar inteiros dentro da tela em todas as larguras e o nome aparece em até 2
 * linhas (na TV) ou inteiro numa linha própria (no celular); os pontos do
 * carrossel têm área de toque ≥ 24 px; o fundo é o compartilhado com a vitrine
 * (aria-hidden, nada brilhante atrás do conteúdo); no 4K o <html> escala e os
 * ícones crescem junto. Nas TVs, CADA slide (duas voltas do carrossel,
 * inclusive o pódio) cabe no palco sem nada escondido. No CELULAR (< 640 px de
 * largura ou < 500 px de altura) o telão é uma página rolável: todas as
 * posições aparecem, nenhuma linha recortada, pódio empilhado.
 */
import path from "node:path";

import { expect, test } from "@playwright/test";
import type { Locator, Page } from "@playwright/test";

import {
  MEDIA_TELAO_TV, PAINEL, PASTA_CAPTURAS, TELAS, TELAS_TELAO_CELULAR, TELAS_TELAO_TV, cruzam,
  ehTelaoCelular, nomeDaTela, simularPainel,
} from "./dados";

const URL_TELAO = "/p/tok-telao-teste";
const SLIDES = ["Ranking Geral", "Quem mais cresceu", "Estrelas em Destaque", "Mural da Escola"];

/** Três quadros: o ResizeObserver entrega a medida e o React re-renderiza. */
async function assentar(page: Page) {
  await page.evaluate(() => new Promise<void>((ok) =>
    requestAnimationFrame(() => requestAnimationFrame(() => requestAnimationFrame(() => ok())))));
}

/**
 * Astros brilhantes ([data-astro]: estrelas com hastes, lua e Saturno) que caem
 * sobre o conteúdo do telão. O texto é medido pela caixa do CONTEÚDO (Range):
 * o h2 e o rótulo do cabeçalho são blocos de largura total com o texto no meio.
 */
async function colisoesDoTelao(page: Page) {
  const caixas = await page.evaluate(() => {
    const visivel = (el: Element) => {
      const r = el.getBoundingClientRect();
      return r.width > 0 && r.height > 0 && getComputedStyle(el).display !== "none";
    };
    const astros = [...document.querySelectorAll("[data-astro]")].filter(visivel).map((el) => {
      const r = el.getBoundingClientRect();
      // Inclui as "hastes" do astro (320% do tamanho, centradas) e o anel de Saturno.
      const extra = el.classList.contains("painel-astro") ? r.width * 1.1 : r.width * 0.5;
      return { left: r.left - extra, top: r.top - extra, right: r.right + extra, bottom: r.bottom + extra };
    });
    const conteudo = (el: Element) => {
      const faixa = document.createRange();
      faixa.selectNodeContents(el);
      const r = faixa.getBoundingClientRect();
      return r.width > 0 ? r : el.getBoundingClientRect();
    };
    const alvos = [
      ...document.querySelectorAll("header img, header h1, header p, header button, main h2, main h2 + p"),
    ].filter(visivel).map((el) => ({ caixa: conteudo(el), nome: `${el.tagName} ${(el.textContent ?? "").slice(0, 20)}` }));
    const blocos = [
      ...document.querySelectorAll("main [data-barra], main li, .painel-podio-grade > div, section[aria-label], footer > *"),
    ].filter(visivel).map((el) => {
      const alvo = el.hasAttribute("data-barra") ? el.parentElement! : el;
      return { caixa: alvo.getBoundingClientRect(), nome: `${alvo.tagName} ${(alvo.textContent ?? "").slice(0, 20)}` };
    });
    return { astros, alvos: [...alvos, ...blocos].map((a) => ({
      left: a.caixa.left, top: a.caixa.top, right: a.caixa.right, bottom: a.caixa.bottom, nome: a.nome,
    })) };
  });
  const achadas: string[] = [];
  for (const a of caixas.astros) {
    for (const t of caixas.alvos) if (cruzam(a, t)) achadas.push(`astro ${JSON.stringify(a)} sobre ${t.nome}`);
  }
  return achadas;
}

/** Linhas do nome da escola: as visíveis e as que o texto inteiro precisa. */
async function linhasDoNome(h1: Locator) {
  return h1.evaluate((el) => {
    const cs = getComputedStyle(el);
    const lh = parseFloat(cs.lineHeight);
    const visiveis = Math.round(el.clientHeight / lh);
    const h = el as HTMLElement;
    const antes = h.getAttribute("style") ?? "";
    h.style.setProperty("display", "block");
    h.style.setProperty("-webkit-line-clamp", "none");
    h.style.setProperty("overflow", "visible");
    const necessarias = Math.round(h.clientHeight / lh);
    h.setAttribute("style", antes);
    return {
      visiveis, necessarias, sw: el.scrollWidth, cw: el.clientWidth, sh: el.scrollHeight, ch: el.clientHeight,
      clamp: cs.getPropertyValue("-webkit-line-clamp"), reticencias: cs.textOverflow === "ellipsis",
    };
  });
}

for (const tela of TELAS) {
  const nome = nomeDaTela(tela);
  const celular = ehTelaoCelular(tela);

  test.describe(`telão ${nome}`, () => {
    test.use({
      viewport: { width: tela.largura, height: tela.altura },
      isMobile: !!tela.movel,
      hasTouch: !!tela.movel,
    });

    test("cabeçalho inteiro na tela, controles alcançáveis e fundo mudo", async ({ page }) => {
      await simularPainel(page);
      await page.goto(URL_TELAO);
      const h1 = page.getByRole("heading", { level: 1 });
      await expect(h1).toHaveText(PAINEL.escola.nome);
      await expect(h1).toHaveAttribute("title", PAINEL.escola.nome);
      await page.evaluate(() => document.fonts.ready);
      // Modo pela MESMA condição do componente (TV ≥ 640 × 500 px).
      await expect(page.locator("[data-modo]")).toHaveAttribute("data-modo", celular ? "celular" : "tv");
      const vw = await page.evaluate(() => document.documentElement.clientWidth);
      const vh = await page.evaluate(() => window.innerHeight);

      // Botões do cabeçalho: caixa inteira dentro da viewport e, na TV, à
      // direita do nome; no celular, na linha de cima (o nome vem embaixo).
      const caixaH1 = (await h1.boundingBox())!;
      for (const rotulo of [/Pausar carrossel/, /Modo TV/]) {
        const botao = page.getByRole("button", { name: rotulo });
        await expect(botao).toBeVisible();
        const b = (await botao.boundingBox())!;
        expect(b.x, `${rotulo} saiu pela esquerda`).toBeGreaterThanOrEqual(0);
        expect(b.y).toBeGreaterThanOrEqual(0);
        expect(b.x + b.width, `${rotulo} cortado na direita`).toBeLessThanOrEqual(vw + 0.5);
        expect(b.y + b.height).toBeLessThanOrEqual(vh + 0.5);
        if (celular) expect(b.y + b.height, `${rotulo} deveria ficar acima do nome`).toBeLessThanOrEqual(caixaH1.y + 0.5);
        else expect(b.x).toBeGreaterThanOrEqual(caixaH1.x + caixaH1.width - 0.5);
      }

      // TV: nome da escola em até 2 linhas — e usando as 2 quando precisa
      // (antes, o truncate deixava só "EMEI/EMEF …"). Celular: o nome INTEIRO.
      const linhasH1 = await linhasDoNome(h1);
      if (celular) {
        expect(linhasH1.visiveis, "nome da escola cortado no celular").toBe(linhasH1.necessarias);
      } else {
        expect(linhasH1.visiveis, "nome da escola com mais de 2 linhas").toBeLessThanOrEqual(2);
        expect(linhasH1.visiveis, "nome da escola cortado antes de 2 linhas")
          .toBe(Math.min(2, linhasH1.necessarias));
      }
      expect(linhasH1.sw, "nome cortado na horizontal").toBeLessThanOrEqual(linhasH1.cw + 1);

      // Nada do cabeçalho passa da borda (o overflow-hidden da raiz esconderia).
      const fora = await page.evaluate((largura) =>
        [...document.querySelectorAll("header, header *")].filter((el) => {
          const r = el.getBoundingClientRect();
          return r.width > 0 && (r.right > largura + 0.5 || r.left < -0.5);
        }).map((el) => `${el.tagName}.${String(el.getAttribute("class")).slice(0, 50)}`), vw);
      expect(fora).toEqual([]);

      // Pontos do carrossel: área de toque ≥ 24 × 24 px (WCAG 2.5.8).
      const pontos = page.getByRole("button", { name: /^Ir para / });
      await expect(pontos).toHaveCount(PAINEL.slides.length);
      for (let i = 0; i < PAINEL.slides.length; i++) {
        const b = (await pontos.nth(i).boundingBox())!;
        expect(b.height).toBeGreaterThanOrEqual(24);
        expect(b.width).toBeGreaterThanOrEqual(24);
      }

      // Fundo: o MESMO componente da vitrine (fim da cópia duplicada), fora da
      // árvore de acessibilidade e sem o SVG esticado que virava "traços".
      await expect(page.locator("[data-fundo-constela]")).toHaveCount(1);
      await expect(page.locator("[data-fundo-constela]")).toHaveAttribute("aria-hidden", "true");
      expect(await page.locator('svg[preserveAspectRatio="none"]').count()).toBe(0);
      // Nenhum astro brilhante (estrelas com hastes, lua, Saturno) sobre o conteúdo.
      expect(await colisoesDoTelao(page)).toEqual([]);

      // Escala do 4K pela mesma classe da vitrine; ícones dos botões crescem junto.
      const rem = await page.evaluate(() => parseFloat(getComputedStyle(document.documentElement).fontSize));
      if (tela.largura === 3840) expect(rem).toBe(30);
      else if (tela.largura <= 1920) expect(rem).toBe(16);
      const icone = await page.getByRole("button", { name: /Pausar carrossel/ }).locator("svg")
        .evaluate((el) => el.getBoundingClientRect().width);
      expect(icone, "ícone do botão não acompanha o rem").toBeGreaterThanOrEqual(1.125 * rem - 0.5);

      await page.screenshot({ path: path.join(PASTA_CAPTURAS, `telao-${nome}.png`) });
    });

    // Nas TVs: duas voltas pelos 4 slides (a 2ª troca era a que quebrava: o palco
    // remonta a cada slide e o observador ficava preso ao nó morto, que mede 0).
    // Em cada slide, nada escondido na rolagem invisível do palco e, quando a
    // lista corta, a linha "+ N" visível dentro do palco. Inclui o pódio.
    if (TELAS_TELAO_TV.has(nome)) {
      test("cada slide cabe no palco, nas duas voltas do carrossel", async ({ page }) => {
        await simularPainel(page);
        await page.goto(URL_TELAO);
        await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
        await page.evaluate(() => document.fonts.ready);
        for (let volta = 1; volta <= 2; volta++) {
          for (const titulo of SLIDES) {
            await page.getByRole("button", { name: `Ir para ${titulo}` }).click();
            await expect(page.getByRole("heading", { level: 2 })).toHaveText(titulo);
            await assentar(page);
            const m = await page.evaluate(() => {
              const palco = document.querySelector("main .painel-sem-barra") as HTMLElement;
              const caixa = palco.getBoundingClientRect();
              const mais = [...palco.querySelectorAll("p, li")].find((e) => /^\+ \d/.test((e.textContent ?? "").trim()));
              const r = mais?.getBoundingClientRect();
              const itens = palco.querySelectorAll("[data-barra]").length
                || [...palco.querySelectorAll("li")].filter((e) => !/^\+ \d/.test((e.textContent ?? "").trim())).length;
              return {
                sobra: palco.scrollHeight - palco.clientHeight,
                itens,
                mais: mais ? (mais.textContent ?? "").trim() : null,
                maisDentro: r ? r.top >= caixa.top - 0.5 && r.bottom <= caixa.bottom + 0.5 : false,
              };
            });
            expect(m.sobra, `${titulo} (volta ${volta}): conteúdo escondido no palco`).toBeLessThanOrEqual(1);
            if (titulo !== "Estrelas em Destaque" && m.itens < 10) {
              expect(m.itens, `${titulo}: menos de 3 linhas (as 3 medalhas)`).toBeGreaterThanOrEqual(3);
              expect(m.mais, `${titulo} (volta ${volta}): falta a linha "+ N"`).toBe(`+ ${10 - m.itens} ${
                titulo === "Mural da Escola" ? "novidades no mural" : "alunos brilhando na jornada"}`);
              expect(m.maisDentro, `${titulo}: "+ N" fora da área visível`).toBe(true);
            }
            if (titulo === "Estrelas em Destaque") {
              // Pódio inteiro (nomes e bases 2/1/3 dentro do palco) e na ordem 2-1-3.
              for (const aluno of ["Carla D.", "Bruno C.", "Davi E."]) {
                await expect(page.getByText(aluno, { exact: true })).toBeVisible();
              }
              const xs = await page.evaluate(() => ["Aluno da Semana", "Aluno do Dia", "Aluno do Mês"].map((t) =>
                [...document.querySelectorAll("main p")].find((p) => p.textContent === t)!.getBoundingClientRect().left));
              expect(xs[0]).toBeLessThan(xs[1]);
              expect(xs[1]).toBeLessThan(xs[2]);
            }
            expect(await colisoesDoTelao(page), `${titulo}: astro sobre o conteúdo`).toEqual([]);
            if (volta === 1) {
              const arquivo = `telao-${nome}-${titulo.split(" ")[0].toLowerCase()}.png`;
              await page.screenshot({ path: path.join(PASTA_CAPTURAS, arquivo) });
            }
          }
        }
      });
    }

    // Celular (as famílias abrem o telão pelo QR): página rolável comum. Roda em
    // TODA tela fora do modo TV — os 5 celulares do contrato e também 683×384
    // (zoom 200%) e 854×480.
    if (celular) {
      test("celular: página rolável com todas as posições, nome inteiro e controles tocáveis", async ({ page }) => {
        await simularPainel(page);
        await page.goto(URL_TELAO);
        const h1 = page.getByRole("heading", { level: 1 });
        await expect(h1).toHaveText(PAINEL.escola.nome);
        await page.evaluate(() => document.fonts.ready);
        await assentar(page);
        expect(await page.evaluate((q) => matchMedia(q).matches, MEDIA_TELAO_TV), "deveria estar fora do modo TV")
          .toBe(false);
        const vw = await page.evaluate(() => document.documentElement.clientWidth);
        const vh = await page.evaluate(() => window.innerHeight);

        // Raiz SEM altura fixa nem overflow-hidden na vertical (só o eixo X é
        // recortado); o palco não tem rolagem própria.
        const raiz = await page.locator("[data-modo]").evaluate((el) => {
          const cs = getComputedStyle(el);
          return { modo: el.getAttribute("data-modo"), x: cs.overflowX, y: cs.overflowY, altura: (el as HTMLElement).style.height };
        });
        expect(raiz).toEqual({ modo: "celular", x: "clip", y: "visible", altura: "" });
        expect(await page.locator("[data-palco]").evaluate((el) => getComputedStyle(el).overflowY)).toBe("visible");

        // Pausar e Modo TV: inteiros na viewport, área de toque ≥ 24 px, na linha
        // de cima — e o nome da escola numa linha PRÓPRIA, embaixo, inteiro.
        const caixaH1 = (await h1.boundingBox())!;
        for (const rotulo of [/Pausar carrossel/, /Modo TV/]) {
          const b = (await page.getByRole("button", { name: rotulo }).boundingBox())!;
          expect(b.x).toBeGreaterThanOrEqual(0);
          expect(b.y).toBeGreaterThanOrEqual(0);
          expect(b.x + b.width, `${rotulo} cortado na direita`).toBeLessThanOrEqual(vw + 0.5);
          expect(b.y + b.height, `${rotulo} cortado embaixo`).toBeLessThanOrEqual(vh + 0.5);
          expect(b.width).toBeGreaterThanOrEqual(24);
          expect(b.height).toBeGreaterThanOrEqual(24);
          expect(b.y + b.height, `${rotulo} sobre o nome`).toBeLessThanOrEqual(caixaH1.y + 0.5);
        }
        const logo = (await page.locator("header img").first().boundingBox())!;
        expect(Math.abs(caixaH1.x - logo.x), "o nome não começa na margem (linha própria)").toBeLessThanOrEqual(1);
        expect(caixaH1.x + caixaH1.width).toBeLessThanOrEqual(vw + 0.5);
        const linhas = await linhasDoNome(h1);
        expect(linhas.reticencias, "nome com reticências").toBe(false);
        expect(linhas.clamp, "nome com limite de linhas").toBe("none");
        expect(linhas.visiveis, "nome cortado").toBe(linhas.necessarias);
        expect(linhas.sh, "nome cortado na vertical").toBeLessThanOrEqual(linhas.ch + 1);
        expect(linhas.sw, "nome cortado na horizontal").toBeLessThanOrEqual(linhas.cw + 1);

        // Foco visível (contorno âmbar) também no celular.
        await page.keyboard.press("Tab");
        const pausar = page.getByRole("button", { name: /Pausar carrossel/ });
        await expect(pausar).toBeFocused();
        expect(await pausar.evaluate((el) => getComputedStyle(el).outlineStyle)).toBe("solid");
        await pausar.blur();

        for (const titulo of SLIDES) {
          await page.getByRole("button", { name: `Ir para ${titulo}` }).click();
          await expect(page.getByRole("heading", { level: 2 })).toHaveText(titulo);
          await assentar(page);
          const m = await page.evaluate(() => {
            const vwi = document.documentElement.clientWidth;
            const docH = document.documentElement.scrollHeight;
            const sy = window.scrollY;
            const rotulo = (el: Element) => (el.textContent ?? "").trim().slice(0, 30);
            // Ancestral com overflow ≠ visible que recorta o elemento (no eixo dele).
            const recortes = (el: Element) => {
              const r = el.getBoundingClientRect();
              const achados: string[] = [];
              for (let a = el.parentElement; a && a !== document.documentElement; a = a.parentElement) {
                const cs = getComputedStyle(a);
                const ra = a.getBoundingClientRect();
                if (cs.overflowY !== "visible" && (r.top < ra.top - 0.5 || r.bottom > ra.bottom + 0.5)) {
                  achados.push(`${rotulo(el)} recortada na vertical por ${a.tagName}.${String(a.getAttribute("class")).slice(0, 40)}`);
                }
                if (cs.overflowX !== "visible" && (r.left < ra.left - 0.5 || r.right > ra.right + 0.5)) {
                  achados.push(`${rotulo(el)} recortada na horizontal por ${a.tagName}.${String(a.getAttribute("class")).slice(0, 40)}`);
                }
              }
              return achados;
            };
            const linhas = [...document.querySelectorAll("main [data-barra]")].map((b) => b.parentElement!);
            const mural = [...document.querySelectorAll("main li")];
            const podio = [...document.querySelectorAll(".painel-podio-grade > div")];
            const textosPodio = [...document.querySelectorAll(
              ".painel-podio-grade .painel-podio-nome, .painel-podio-grade .painel-podio-nome-campeao, .painel-podio-grade .painel-podio-chips, .painel-podio-grade .painel-podio-ganhos")];
            const alvos = [...linhas, ...mural, ...podio, ...textosPodio];
            const problemas = alvos.flatMap((el) => {
              const r = el.getBoundingClientRect();
              const erros = recortes(el);
              if (r.top + sy < -0.5 || r.bottom + sy > docH + 0.5) erros.push(`${rotulo(el)} fora do documento`);
              if (r.left < -0.5 || r.right > vwi + 0.5) erros.push(`${rotulo(el)} fora da largura`);
              return erros;
            });
            // Nada do conteúdo (fora o fundo decorativo) passa da largura da tela.
            const largos = [...document.querySelectorAll("header *, main *, section *, footer *, .painel-dica")]
              .filter((el) => {
                const r = el.getBoundingClientRect();
                return r.width > 0 && (r.right > vwi + 0.5 || r.left < -0.5);
              }).map((el) => `${el.tagName}.${String(el.getAttribute("class")).slice(0, 40)}`);
            const caixa = (sel: string) => {
              const r = document.querySelector(sel)!.getBoundingClientRect();
              return { topo: r.top + sy, base: r.bottom + sy };
            };
            return {
              linhas: linhas.map(rotulo),
              mural: mural.map(rotulo),
              podio: podio.map((el) => {
                const r = el.getBoundingClientRect();
                return { x: r.left, topo: r.top + sy, base: r.bottom + sy, largura: r.width, texto: rotulo(el) };
              }),
              mais: [...document.querySelectorAll("main p, main li")].some((e) => /^\+ \d/.test((e.textContent ?? "").trim())),
              problemas,
              largos,
              sw: document.documentElement.scrollWidth,
              cw: vwi,
              docH,
              fluxo: [caixa("main"), caixa("section[aria-label]"), caixa(".painel-dica"), caixa("footer")],
            };
          });
          expect(m.sw, `${titulo}: rolagem horizontal`).toBeLessThanOrEqual(m.cw);
          expect(m.largos, `${titulo}: conteúdo passa da largura`).toEqual([]);
          expect(m.problemas, `${titulo}: linha cortada`).toEqual([]);
          expect(m.mais, `${titulo}: "+ N" escondendo gente no celular`).toBe(false);
          // Números, dica e rodapé seguem no fluxo, um abaixo do outro, depois do palco.
          for (let i = 1; i < m.fluxo.length; i++) {
            expect(m.fluxo[i].topo, `${titulo}: bloco ${i} sobreposto ao anterior`).toBeGreaterThanOrEqual(m.fluxo[i - 1].base - 0.5);
          }
          expect(m.fluxo[m.fluxo.length - 1].base).toBeLessThanOrEqual(m.docH + 0.5);

          if (titulo === "Ranking Geral" || titulo === "Quem mais cresceu") {
            // TODAS as posições configuradas, na ordem — a página rola para mostrá-las.
            const itens = titulo === "Ranking Geral" ? PAINEL.ranking : PAINEL.evolucao;
            expect(m.linhas).toHaveLength(itens.length);
            itens.forEach((item, i) => expect(m.linhas[i]).toContain(item.nome));
            expect(m.docH, "a lista inteira não cabe numa tela: a página deveria rolar").toBeGreaterThan(vh);
            const ultima = page.locator("main [data-barra]").last().locator("..");
            await ultima.scrollIntoViewIfNeeded();
            await expect(ultima, "a última posição não aparece inteira rolando").toBeInViewport({ ratio: 1 });
            await page.evaluate(() => window.scrollTo(0, 0));
          }
          if (titulo === "Mural da Escola") {
            expect(m.mural).toHaveLength(PAINEL.mural.length);
            PAINEL.mural.forEach((evento, i) => expect(m.mural[i]).toContain(evento.texto.slice(0, 20)));
          }
          if (titulo === "Estrelas em Destaque") {
            // Pódio EMPILHADO: uma coluna (mesma margem e largura), Dia → Semana → Mês.
            expect(m.podio).toHaveLength(3);
            for (const aluno of ["Bruno C.", "Carla D.", "Davi E."]) {
              await expect(page.getByText(aluno, { exact: true })).toBeVisible();
            }
            const [primeiro, segundo, terceiro] = [...m.podio].sort((a, b) => a.topo - b.topo);
            expect(primeiro.texto).toContain("Aluno do Dia");
            expect(segundo.texto).toContain("Aluno da Semana");
            expect(terceiro.texto).toContain("Aluno do Mês");
            for (const coluna of [segundo, terceiro]) {
              expect(Math.abs(coluna.x - primeiro.x), "pódio fora de coluna única").toBeLessThanOrEqual(1);
              expect(Math.abs(coluna.largura - primeiro.largura)).toBeLessThanOrEqual(1);
            }
            expect(segundo.topo).toBeGreaterThanOrEqual(primeiro.base - 0.5);
            expect(terceiro.topo).toBeGreaterThanOrEqual(segundo.base - 0.5);
          }
          expect(await colisoesDoTelao(page), `${titulo}: astro sobre o conteúdo`).toEqual([]);
          const arquivo = `telao-${nome}-celular-${titulo.split(" ")[0].toLowerCase()}.png`;
          await page.screenshot({ path: path.join(PASTA_CAPTURAS, arquivo), fullPage: true });
          await page.evaluate(() => window.scrollTo(0, 0));
        }
      });

      test("celular: o carrossel gira sozinho e o Pausar segura o slide", async ({ page }) => {
        await page.clock.install();
        // Intervalo curto (4 s, o mínimo do componente): só o relógio falso anda.
        await simularPainel(page, { ...PAINEL, intervalo_s: 4 });
        await page.goto(URL_TELAO);
        const h2 = page.getByRole("heading", { level: 2 });
        await expect(h2).toHaveText("Ranking Geral");
        const tocar = (alvo: Locator) => (tela.movel ? alvo.tap() : alvo.click());
        await page.clock.runFor(4_100);
        await expect(h2).toHaveText("Quem mais cresceu");
        await tocar(page.getByRole("button", { name: /Pausar carrossel/ }));
        await expect(page.getByRole("button", { name: /Retomar carrossel/ })).toBeVisible();
        await page.clock.runFor(12_000);
        await expect(h2).toHaveText("Quem mais cresceu");
        await tocar(page.getByRole("button", { name: /Retomar carrossel/ }));
        await page.clock.runFor(4_100);
        await expect(h2).toHaveText("Estrelas em Destaque");
      });

      test("celular: em tela cheia (Modo TV) a página continua rolando", async ({ page }) => {
        await simularPainel(page);
        await page.goto(URL_TELAO);
        await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
        const modoTv = page.getByRole("button", { name: /Modo TV/ });
        await (tela.movel ? modoTv.tap() : modoTv.click());
        await expect.poll(() => page.evaluate(() => !!document.fullscreenElement)).toBe(true);
        // Em tela cheia o navegador fixa a raiz na altura da tela: ela mesma rola.
        const m = await page.locator("[data-modo]").evaluate((el) => {
          el.scrollTop = el.scrollHeight;
          return { cheia: document.fullscreenElement === el, y: getComputedStyle(el).overflowY, rolou: el.scrollTop };
        });
        expect(m.cheia).toBe(true);
        expect(m.y).toBe("auto");
        expect(m.rolou, "em tela cheia o fim da página ficou inalcançável").toBeGreaterThan(0);
      });
    }
  });
}

// Os 5 celulares do contrato estão de fato fora do modo TV (e na lista de telas).
test("celulares do contrato caem no modo celular do telão", () => {
  for (const nome of TELAS_TELAO_CELULAR) {
    const tela = TELAS.find((t) => nomeDaTela(t) === nome);
    expect(tela, `${nome} fora de TELAS`).toBeDefined();
    expect(ehTelaoCelular(tela!), `${nome} no modo TV`).toBe(true);
  }
  for (const nome of TELAS_TELAO_TV) {
    expect(ehTelaoCelular(TELAS.find((t) => nomeDaTela(t) === nome)!), `${nome} no modo celular`).toBe(false);
  }
});

test.describe("telão: foco visível no tema noite", () => {
  test.use({ viewport: { width: 1366, height: 768 } });

  test("Tab no botão Pausar mostra contorno âmbar", async ({ page }) => {
    await simularPainel(page);
    await page.goto(URL_TELAO);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    const pausar = page.getByRole("button", { name: /Pausar carrossel/ });
    await page.keyboard.press("Tab");
    await expect(pausar).toBeFocused();
    const contorno = await pausar.evaluate((el) => {
      const cs = getComputedStyle(el);
      return { estilo: cs.outlineStyle, largura: cs.outlineWidth, cor: cs.outlineColor };
    });
    expect(contorno.estilo).toBe("solid");
    expect(parseFloat(contorno.largura)).toBeGreaterThanOrEqual(2);
    expect(contorno.cor).toBe("rgb(252, 211, 77)");
  });
});

test.describe("telão em reduced-motion (padrão do config)", () => {
  test.use({ viewport: { width: 1920, height: 1080 } });

  test("barra relativa visível, texto secundário legível e céu vivo", async ({ page }) => {
    await simularPainel(page);
    await page.goto(URL_TELAO);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    expect(await page.evaluate(() => matchMedia("(prefers-reduced-motion: reduce)").matches)).toBe(true);

    // Barra relativa: a linha isola o empilhamento e a barra fica ACIMA do fundo
    // dela. Sem o `isolate`, em reduce (sem o transform que o painel-surgir
    // deixa) ela ia para trás do fundo opaco do telão e sumia.
    const barra = await page.evaluate(() => {
      const span = document.querySelectorAll("main [data-barra]")[3] as HTMLElement;
      const linha = span.parentElement!;
      const r = span.getBoundingClientRect();
      const pilha = document.elementsFromPoint(r.left + r.width * 0.5, r.bottom - 2);
      return {
        isolamento: getComputedStyle(linha).isolation,
        largura: r.width,
        barraAntesDaLinha: pilha.indexOf(span) > -1 && pilha.indexOf(span) < pilha.indexOf(linha),
      };
    });
    expect(barra.isolamento).toBe("isolate");
    expect(barra.largura).toBeGreaterThan(0);
    expect(barra.barraAntesDaLinha).toBe(true);

    // Texto pequeno secundário com contraste AA: nada em white/40–45.
    const alfa = (cor: string) => {
      const partes = cor.match(/rgba?\(([^)]+)\)/)![1].split(",").map((p) => parseFloat(p));
      return partes.length === 4 ? partes[3] : 1;
    };
    for (const alvo of [
      page.getByText(/alunos brilhando na jornada/),
      page.getByText("Atualização automática"),
      page.locator(".painel-dica"),
    ]) {
      const cor = await alvo.evaluate((el) => getComputedStyle(el).color);
      expect(alfa(cor), `contraste baixo: ${cor}`).toBeGreaterThanOrEqual(0.6);
    }

    // O céu continua vivo (pedido do dono); os efeitos de UI param.
    const animacoes = await page.evaluate(() => ({
      estrela: getComputedStyle(document.querySelector(".painel-estrela")!).animationName,
      cadente: getComputedStyle(document.querySelector(".painel-cadente")!).animationName,
      satelite: getComputedStyle(document.querySelector(".painel-satelite")!).animationName,
      pulso: getComputedStyle(document.querySelector(".painel-pulso")!).animationName,
    }));
    expect(animacoes).toEqual({
      estrela: "painel-cintila", cadente: "painel-cadente", satelite: "painel-satelite", pulso: "none",
    });
    await page.screenshot({ path: path.join(PASTA_CAPTURAS, "telao-1920x1080-reduce.png") });
  });
});

for (const movimento of ["reduce", "no-preference"] as const) {
  test.describe(`telão carregando (${movimento})`, () => {
    test.use({ viewport: { width: 1366, height: 768 }, contextOptions: { reducedMotion: movimento } });

    test("o spinner respeita reduzir movimento", async ({ page }) => {
      let liberar = () => {};
      const resposta = new Promise<void>((ok) => { liberar = ok; });
      await simularPainel(page);
      // Rota registrada depois tem prioridade: segura a resposta do painel.
      await page.route((url) => /^\/api\/v1\/publico\/[^/]+\/painel$/.test(url.pathname), async (rota) => {
        await resposta;
        await rota.fulfill({ json: PAINEL });
      });
      await page.goto(URL_TELAO);
      await expect(page.getByRole("status")).toHaveText(/Carregando painel/);
      const nomeAnimacao = await page.locator("[data-carregando]").evaluate((el) => getComputedStyle(el).animationName);
      expect(nomeAnimacao).toBe(movimento === "reduce" ? "none" : "spin");
      liberar();
      await expect(page.getByRole("heading", { level: 1 })).toHaveText(PAINEL.escola.nome);
    });
  });
}
