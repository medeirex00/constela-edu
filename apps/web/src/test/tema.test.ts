/**
 * Tema: login e páginas públicas sempre escuros; a preferência claro/escuro só nas
 * páginas internas, com sessão. Confere a regra (lib/tema.ts), o script do primeiro
 * desenho (public/tema-inicial.js, que precisa dar o MESMO resultado e estar no
 * index.html), o AppProvider e o botão de tema do Layout.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";

import Layout from "../components/Layout";
import { AppProvider, useApp } from "../context/AppContext";
import { ImportacaoLoteProvider } from "../context/ImportacaoLoteContext";
import { guardarToken } from "../lib/api";
import { htmlEscuro, telaSempreEscura, tokenVivo, type Tema } from "../lib/tema";
import { autenticar, escolaFake, renderComApp, responder, usuarioFake } from "./utils";

const html = document.documentElement;

/** JWT de mentira (a assinatura não importa para o tema): só o `exp` em segundos. */
function jwt(exp: number): string {
  const b64 = (o: object) => btoa(JSON.stringify(o)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  return `${b64({ alg: "HS256", typ: "JWT" })}.${b64({ sub: "1", exp })}.assinatura`;
}
const agoraS = () => Math.floor(Date.now() / 1000);
const TOKENS: Record<string, string | null> = {
  vivo: jwt(agoraS() + 8 * 3600),
  vencido: jwt(agoraS() - 60),
  ilegivel: "token-de-teste",
  ausente: null,
};

afterEach(() => {
  html.classList.remove("dark");
  window.history.replaceState({}, "", "/");
});

describe("regra do tema", () => {
  it("login, redefinição de senha, telão e vitrine são sempre escuros (também em maiúsculas)", () => {
    for (const c of ["/login", "/login/", "/LOGIN", "/redefinir-senha", "/p/abc", "/P/abc", "/p/abc/alunos/3", "/rede/p/xyz", "/Rede/P/xyz"]) {
      expect(telaSempreEscura(c), c).toBe(true);
      expect(htmlEscuro(c, "claro", true), c).toBe(true);
    }
    for (const c of ["/", "/rede", "/rede/escolas", "/minha-conta", "/loginx", "/painel-publico"]) {
      expect(telaSempreEscura(c), c).toBe(false);
    }
  });

  it("nas páginas internas vale a preferência de quem tem sessão; sem sessão, escuro", () => {
    expect(htmlEscuro("/", "claro", true)).toBe(false);
    expect(htmlEscuro("/", "escuro", true)).toBe(true);
    expect(htmlEscuro("/rede/escolas", "claro", false)).toBe(true);
  });

  it("só o token com o exp no futuro conta como sessão", () => {
    expect(tokenVivo(TOKENS.vivo)).toBe(true);
    expect(tokenVivo(TOKENS.vencido)).toBe(false);
    expect(tokenVivo(TOKENS.ilegivel)).toBe(false);
    expect(tokenVivo(null)).toBe(false);
    expect(tokenVivo("cabecalho.{nao-json}.assinatura")).toBe(false);
    expect(tokenVivo(`${btoa("{}")}.${btoa(JSON.stringify({ sub: "1" }))}.x`)).toBe(false); // sem exp
  });
});

describe("script do primeiro desenho (public/tema-inicial.js)", () => {
  const codigo = readFileSync(resolve(__dirname, "../../public/tema-inicial.js"), "utf8");

  it("o index.html carrega o script no <head>, antes do app e sem type=module", () => {
    const pagina = readFileSync(resolve(__dirname, "../../index.html"), "utf8");
    const tag = pagina.match(/<script[^>]*src="\/tema-inicial\.js"[^>]*>/);
    expect(tag, "falta o <script src=\"/tema-inicial.js\"> no index.html").not.toBeNull();
    expect(tag![0]).not.toMatch(/type=|defer|async/);
    expect(pagina.indexOf(tag![0])).toBeLessThan(pagina.indexOf("</head>"));
    expect(pagina.indexOf(tag![0])).toBeLessThan(pagina.indexOf("/src/main.tsx"));
  });

  const casos: [string, Tema, string][] = [];
  for (const caminho of ["/login", "/LOGIN", "/redefinir-senha", "/p/t", "/rede/p/t", "/", "/rede/escolas", "/minha-conta"]) {
    for (const tema of ["claro", "escuro"] as Tema[]) {
      for (const token of Object.keys(TOKENS)) casos.push([caminho, tema, token]);
    }
  }

  it.each(casos)("%s, preferência %s, token %s: igual à regra do app", (caminho, tema, token) => {
    window.history.replaceState({}, "", caminho);
    localStorage.setItem("sgpe_tema", tema);
    if (TOKENS[token]) localStorage.setItem("sgpe_token", TOKENS[token]!);
    const esperado = htmlEscuro(caminho, tema, tokenVivo(TOKENS[token]));
    html.classList.toggle("dark", !esperado); // começa no oposto
    new Function(codigo)();
    expect(html.classList.contains("dark")).toBe(esperado);
  });
});

describe("AppProvider aplica a regra", () => {
  /** Mostra "sessão aberta" quando o /auth/me respondeu: a classe só é conferida depois. */
  function Sonda() {
    const { usuario } = useApp();
    return usuario ? createElement("span", null, "sessão aberta") : null;
  }
  function montar(rota: string) {
    return render(createElement(MemoryRouter, { initialEntries: [rota] }, createElement(AppProvider, null, createElement(Sonda))));
  }

  it("login fica escuro com a preferência clara guardada (depois de sair, ao recarregar, direto)", async () => {
    localStorage.setItem("sgpe_tema", "claro");
    montar("/login");
    await waitFor(() => expect(html.classList.contains("dark")).toBe(true));
    expect(localStorage.getItem("sgpe_tema")).toBe("claro"); // a preferência não é apagada
  });

  it("vitrine pública fica escura com a preferência clara e sessão guardada", async () => {
    localStorage.setItem("sgpe_tema", "claro");
    autenticar();
    guardarToken(TOKENS.vivo!); // o mock da API guarda o token em memória
    montar("/rede/p/token");
    await waitFor(() => expect(html.classList.contains("dark")).toBe(true));
  });

  it("página interna: com a sessão aberta segue a preferência clara", async () => {
    localStorage.setItem("sgpe_tema", "claro");
    autenticar();
    html.classList.add("dark"); // começa no oposto: a troca tem de vir do provider
    montar("/");
    await screen.findByText("sessão aberta");
    expect(html.classList.contains("dark")).toBe(false);
  });

  it("página interna: com a sessão aberta segue a preferência escura", async () => {
    localStorage.setItem("sgpe_tema", "escuro");
    autenticar();
    montar("/");
    await screen.findByText("sessão aberta");
    expect(html.classList.contains("dark")).toBe(true);
  });

  it("página interna abrindo com token vivo já usa a preferência clara (sem piscar escuro)", () => {
    localStorage.setItem("sgpe_tema", "claro");
    autenticar();
    guardarToken(TOKENS.vivo!); // o mock da API guarda o token em memória
    html.classList.add("dark");
    montar("/");
    // Primeira renderização: o /auth/me ainda não respondeu.
    expect(screen.queryByText("sessão aberta")).toBeNull();
    expect(html.classList.contains("dark")).toBe(false);
  });

  it("página interna abrindo com token VENCIDO fica escura (vai para o login)", () => {
    localStorage.setItem("sgpe_tema", "claro");
    autenticar();
    guardarToken(TOKENS.vencido!);
    montar("/");
    expect(screen.queryByText("sessão aberta")).toBeNull();
    expect(html.classList.contains("dark")).toBe(true);
  });

  it("página interna sem sessão (vai para o login) fica escura", async () => {
    localStorage.setItem("sgpe_tema", "claro");
    montar("/rede/escolas");
    await waitFor(() => expect(html.classList.contains("dark")).toBe(true));
  });
});

describe("botão de tema do Layout", () => {
  it("troca o tema da página interna e guarda a preferência", async () => {
    localStorage.setItem("sgpe_tema", "claro");
    responder("GET", "/escolas/1/sync/onboarding", { lista_piloto_importada: true });
    renderComApp(createElement(ImportacaoLoteProvider, null, createElement(Layout)), {
      rota: "/", usuario: usuarioFake({ cargo: "coordenador", escola_id: 1 }), escolas: [escolaFake({ id: 1 })],
    });
    const escurecer = await screen.findByRole("button", { name: "Ativar modo escuro" });
    expect(html.classList.contains("dark")).toBe(false);
    await userEvent.click(escurecer);
    expect(html.classList.contains("dark")).toBe(true);
    expect(localStorage.getItem("sgpe_tema")).toBe("escuro");
    await userEvent.click(screen.getByRole("button", { name: "Ativar modo claro" }));
    expect(html.classList.contains("dark")).toBe(false);
    expect(localStorage.getItem("sgpe_tema")).toBe("claro");
  });
});
