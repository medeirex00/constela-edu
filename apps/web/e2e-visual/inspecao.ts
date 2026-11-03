/**
 * Inspeções automáticas da varredura visual, feitas DENTRO da página (sem dependência
 * nova): h1, nome acessível de controles, rótulo de campos, alt de imagem, ids
 * repetidos, contraste do texto (WCAG 2.1 AA, 4,5:1 e 3:1 para texto grande),
 * elementos que passam da borda direita sem estar num contêiner que rola, texto
 * truncado sem `title` e foco visível ao navegar com Tab.
 *
 * O contraste é uma aproximação honesta: compõe as cores de fundo dos ancestrais até
 * achar uma opaca e PULA (conta como "indeterminado") texto sobre degradê ou imagem.
 */
import type { Page } from "@playwright/test";

export interface ProblemaContraste {
  texto: string;
  razao: number;
  minimo: number;
  cor: string;
  fundo: string;
  onde: string;
}

export interface Inspecao {
  h1s: number;
  semNome: string[];
  semRotulo: string[];
  imgSemAlt: number;
  idsRepetidos: string[];
  contraste: ProblemaContraste[];
  contrasteIndeterminado: number;
  foraDaTela: string[];
  truncadoSemTitle: number;
  truncados: string[];
}

export async function inspecionar(page: Page): Promise<Inspecao> {
  return page.evaluate(() => {
    const MAX = 12;
    const visivel = (el: Element): boolean => {
      const r = el.getBoundingClientRect();
      if (r.width <= 1 || r.height <= 1) return false;
      const s = getComputedStyle(el);
      return s.visibility !== "hidden" && s.display !== "none" && Number(s.opacity) > 0.05;
    };
    const descrever = (el: Element): string => {
      const cls = (el.getAttribute("class") || "").split(/\s+/).filter(Boolean).slice(0, 3).join(".");
      const txt = (el.textContent || "").replace(/\s+/g, " ").trim().slice(0, 40);
      return `${el.tagName.toLowerCase()}${cls ? "." + cls : ""}${txt ? ` "${txt}"` : ""}`;
    };
    const nomeAcessivel = (el: Element): string => {
      const aria = el.getAttribute("aria-label");
      if (aria && aria.trim()) return aria.trim();
      const por = el.getAttribute("aria-labelledby");
      if (por) {
        const t = por.split(/\s+/).map((id) => document.getElementById(id)?.textContent || "").join(" ").trim();
        if (t) return t;
      }
      if (el instanceof HTMLInputElement || el instanceof HTMLSelectElement || el instanceof HTMLTextAreaElement) {
        if (el.labels && el.labels.length) return Array.from(el.labels).map((l) => l.textContent || "").join(" ").trim();
        if (el instanceof HTMLInputElement && ["submit", "button", "reset"].includes(el.type)) return el.value;
        return (el.getAttribute("title") || "").trim();
      }
      const alts = Array.from(el.querySelectorAll("img[alt]")).map((i) => i.getAttribute("alt") || "").join(" ");
      return ((el.textContent || "") + " " + alts + " " + (el.getAttribute("title") || "")).replace(/\s+/g, " ").trim();
    };

    const h1s = Array.from(document.querySelectorAll("h1")).filter(visivel).length;

    const semNome: string[] = [];
    const controles = document.querySelectorAll('button, a[href], [role="button"], [role="tab"], [role="switch"], [role="link"], [role="menuitem"]');
    for (const el of Array.from(controles)) {
      if (!visivel(el) || el.closest('[aria-hidden="true"]')) continue;
      if (!nomeAcessivel(el)) semNome.push(descrever(el));
      if (semNome.length >= MAX) break;
    }

    const semRotulo: string[] = [];
    for (const el of Array.from(document.querySelectorAll("input, select, textarea"))) {
      const tipo = (el.getAttribute("type") || "").toLowerCase();
      if (["hidden", "submit", "button", "reset"].includes(tipo) || !visivel(el)) continue;
      if (!nomeAcessivel(el)) semRotulo.push(descrever(el) + (el.getAttribute("placeholder") ? ` [placeholder: ${el.getAttribute("placeholder")}]` : ""));
      if (semRotulo.length >= MAX) break;
    }

    const imgSemAlt = Array.from(document.querySelectorAll("img")).filter((i) => visivel(i) && !i.hasAttribute("alt")).length;

    const vistos = new Map<string, number>();
    for (const el of Array.from(document.querySelectorAll("[id]"))) vistos.set(el.id, (vistos.get(el.id) || 0) + 1);
    const idsRepetidos = Array.from(vistos.entries()).filter(([, n]) => n > 1).map(([id, n]) => `${id} ×${n}`).slice(0, MAX);

    // ---- contraste ----
    type Cor = { r: number; g: number; b: number; a: number };
    const ler = (c: string): Cor | null => {
      const m = c.match(/rgba?\(([^)]+)\)/);
      if (!m) return null;
      const p = m[1].split(/[\s,/]+/).filter(Boolean).map(Number);
      return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 };
    };
    const sobre = (cima: Cor, baixo: Cor): Cor => ({
      r: cima.r * cima.a + baixo.r * (1 - cima.a),
      g: cima.g * cima.a + baixo.g * (1 - cima.a),
      b: cima.b * cima.a + baixo.b * (1 - cima.a),
      a: 1,
    });
    const lum = (c: Cor): number => {
      const f = (v: number) => {
        const s = v / 255;
        return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
      };
      return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b);
    };
    const hex = (c: Cor) => "#" + [c.r, c.g, c.b].map((v) => Math.round(v).toString(16).padStart(2, "0")).join("");
    const fundoDe = (el: Element): Cor | null => {
      const camadas: Cor[] = [];
      let atual: Element | null = el;
      while (atual) {
        const s = getComputedStyle(atual);
        if (s.backgroundImage && s.backgroundImage !== "none") return null;
        const c = ler(s.backgroundColor);
        if (c && c.a > 0) {
          camadas.push(c);
          if (c.a >= 1) break;
        }
        atual = atual.parentElement;
      }
      let base: Cor = { r: 255, g: 255, b: 255, a: 1 };
      for (let i = camadas.length - 1; i >= 0; i--) base = sobre(camadas[i], base);
      return base;
    };
    const opacidade = (el: Element): number => {
      let o = 1;
      let atual: Element | null = el;
      while (atual) {
        o *= Number(getComputedStyle(atual).opacity);
        atual = atual.parentElement;
      }
      return o;
    };

    const contraste: ProblemaContraste[] = [];
    let contrasteIndeterminado = 0;
    const todos = Array.from(document.body.querySelectorAll("*")).slice(0, 6000);
    for (const el of todos) {
      if (el.closest("svg")) continue;
      // Só texto com letra ou número: emoji (ícone de conquista, medalha) não tem a cor
      // do CSS e não entra na regra de contraste de texto.
      const temTexto = Array.from(el.childNodes).some((n) => n.nodeType === 3 && /[\p{L}\p{N}]/u.test(n.textContent || ""));
      if (!temTexto || !visivel(el)) continue;
      if (el.closest('[disabled], [aria-disabled="true"]')) continue;
      const s = getComputedStyle(el);
      const cor = ler(s.color);
      if (!cor || cor.a === 0) continue;
      const fundo = fundoDe(el);
      if (!fundo) {
        contrasteIndeterminado++;
        continue;
      }
      const op = opacidade(el);
      // Ancestral transparente (seção recolhida, transição de entrada): o texto não
      // está visível; medir daria 1:1 e seria falso positivo.
      if (op < 0.1) continue;
      const efetiva = sobre({ ...cor, a: cor.a * op }, fundo);
      const l1 = lum(efetiva);
      const l2 = lum(fundo);
      const razao = (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
      const tamanho = parseFloat(s.fontSize);
      const peso = Number(s.fontWeight) || 400;
      const grande = tamanho >= 24 || (tamanho >= 18.66 && peso >= 700);
      const minimo = grande ? 3 : 4.5;
      if (razao + 0.005 < minimo) {
        const txt = Array.from(el.childNodes).filter((n) => n.nodeType === 3).map((n) => n.textContent || "").join(" ").replace(/\s+/g, " ").trim();
        contraste.push({ texto: txt.slice(0, 40), razao: Math.round(razao * 100) / 100, minimo, cor: hex(efetiva), fundo: hex(fundo), onde: descrever(el).slice(0, 80) });
      }
    }

    // ---- passa da borda direita sem um contêiner que role/corte ----
    const foraDaTela: string[] = [];
    const largura = window.innerWidth;
    for (const el of todos) {
      const r = el.getBoundingClientRect();
      if (r.right <= largura + 1 || r.width <= 1 || !visivel(el)) continue;
      let corta = false;
      let pai = el.parentElement;
      while (pai && pai !== document.body) {
        const ps = getComputedStyle(pai);
        if (ps.overflowX !== "visible" && pai.getBoundingClientRect().right <= largura + 1) {
          corta = true;
          break;
        }
        if (ps.position === "fixed") break;
        pai = pai.parentElement;
      }
      if (!corta) {
        foraDaTela.push(`${descrever(el)} (direita ${Math.round(r.right)} > ${largura})`);
        if (foraDaTela.length >= MAX) break;
      }
    }

    // ---- texto truncado (reticências) que o usuário não consegue ler inteiro ----
    let truncadoSemTitle = 0;
    const truncados: string[] = [];
    for (const el of todos) {
      const s = getComputedStyle(el);
      if (s.textOverflow !== "ellipsis" || !visivel(el)) continue;
      if ((el as HTMLElement).scrollWidth > (el as HTMLElement).clientWidth + 1 && !el.closest("[title]")) {
        truncadoSemTitle++;
        if (truncados.length < MAX) truncados.push(descrever(el));
      }
    }

    return { h1s, semNome, semRotulo, imgSemAlt, idsRepetidos, contraste: contraste.slice(0, 40), contrasteIndeterminado, foraDaTela, truncadoSemTitle, truncados };
  });
}

/** Percorre a página com Tab e devolve os controles focados SEM mudança visível
 *  (contorno, sombra/anel, fundo, borda ou sublinhado) no próprio elemento ou nos
 *  dois ancestrais mais próximos. Transições desligadas para comparar sem animação. */
export async function focoInvisivel(page: Page, passos = 25): Promise<{ testados: number; invisiveis: string[] }> {
  await page.addStyleTag({ content: "*,*::before,*::after{transition:none!important;animation:none!important}" });
  await page.evaluate(() => {
    (document.activeElement as HTMLElement | null)?.blur();
    window.scrollTo(0, 0);
  });
  const invisiveis: string[] = [];
  const vistos = new Set<string>();
  let testados = 0;
  for (let i = 0; i < passos; i++) {
    await page.keyboard.press("Tab");
    const r = await page.evaluate(() => {
      const el = document.activeElement as HTMLElement | null;
      if (!el || el === document.body) return null;
      const foto = (alvo: Element | null) => {
        if (!alvo) return "";
        const s = getComputedStyle(alvo);
        return [s.outlineStyle, s.outlineWidth, s.outlineColor, s.boxShadow, s.backgroundColor, s.borderColor, s.textDecorationLine, s.color].join("|");
      };
      const alvos = [el, el.parentElement, el.parentElement?.parentElement ?? null];
      const comFoco = alvos.map(foto);
      el.blur();
      const semFoco = alvos.map(foto);
      el.focus({ preventScroll: true });
      const cls = (el.getAttribute("class") || "").split(/\s+/).filter(Boolean).slice(0, 3).join(".");
      const nome = (el.getAttribute("aria-label") || el.textContent || "").replace(/\s+/g, " ").trim().slice(0, 40);
      return { chave: `${el.tagName}|${nome}|${cls}`, mudou: comFoco.some((v, k) => v !== semFoco[k]), desc: `${el.tagName.toLowerCase()}${cls ? "." + cls : ""} "${nome}"` };
    });
    if (!r || vistos.has(r.chave)) continue;
    vistos.add(r.chave);
    testados++;
    if (!r.mudou) invisiveis.push(r.desc);
  }
  return { testados, invisiveis };
}
