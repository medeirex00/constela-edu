// @vitest-environment jsdom
/**
 * Rede PENDURADA no boot e no "Sair" (auditoria MOBILE-2).
 *
 * O React Native no Android cria o OkHttp sem tempo-limite (connect/read/write 0) e
 * o cliente do core não tem um: uma conexão que não responde (sinal fraco, rede que
 * descarta pacotes, servidor travado) deixa o fetch pendente por minutos. Antes:
 *   - o boot já aplicava a sessão salva, mas só saía de "Abrindo o Constela Edu..."
 *     depois do refresh da rede (/auth/me e /escolas);
 *   - o "Sair" esperava a remoção do push na rede ANTES de apagar o token e a sessão:
 *     nada acontecia, e os dados das crianças seguiam no aparelho e na tela.
 * Código real do contexto, api, notificacoes, fila, cifra e sessão; só os módulos
 * nativos e o `fetch` são dublês ("pendurar" = a promessa nunca resolve, a não ser
 * que o pedido seja cancelado). Dados fictícios.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const estado = vi.hoisted(() => ({
  cofre: new Map<string, string>(),
  disco: new Map<string, string>(),
  chamadas: [] as string[],
  pendurar: new Set<string>(),
  liberar: new Map<string, () => void>(),
}));

vi.mock("react", async () => {
  const { createRequire } = await import("node:module");
  const path = await import("node:path");
  const exigir = createRequire(import.meta.url);
  const dirReactDom = path.dirname(exigir.resolve("react-dom/package.json"));
  return exigir(exigir.resolve("react", { paths: [dirReactDom] }));
});
vi.mock("react-native", async () => (await import("./_rnFalso")).reactNativeFalso);
vi.mock("expo-secure-store", () => ({
  getItemAsync: async (k: string) => estado.cofre.get(k) ?? null,
  setItemAsync: async (k: string, v: string) => void estado.cofre.set(k, v),
  deleteItemAsync: async (k: string) => void estado.cofre.delete(k),
}));
vi.mock("@react-native-async-storage/async-storage", () => ({
  default: {
    getItem: async (k: string) => estado.disco.get(k) ?? null,
    setItem: async (k: string, v: string) => void estado.disco.set(k, v),
    removeItem: async (k: string) => void estado.disco.delete(k),
  },
}));
vi.mock("expo-crypto", () => {
  let semente = 0x13579bd;
  return {
    getRandomBytesAsync: async (n: number) => {
      const bytes = new Uint8Array(n);
      for (let i = 0; i < n; i++) {
        semente = (semente * 1664525 + 1013904223) >>> 0;
        bytes[i] = semente >>> 24;
      }
      return bytes;
    },
  };
});
vi.mock("expo-constants", () => ({ default: { expoConfig: { extra: {} } } }));
vi.mock("expo-device", () => ({ isDevice: true }));
vi.mock("expo-notifications", () => ({
  setNotificationHandler: () => undefined,
  getPermissionsAsync: async () => ({ status: "granted" }),
  requestPermissionsAsync: async () => ({ status: "granted" }),
  setNotificationChannelAsync: async () => undefined,
  AndroidImportance: { DEFAULT: 3 },
  getExpoPushTokenAsync: async () => ({ data: "ExponentPushToken[ficticio-0002]" }),
}));

const USUARIO = { id: 9, nome: "Prof Ficticia", email: "prof@ficticio.local", cargo: "professor",
  is_global: false, escola_id: 1 };
const ESCOLAS = [{ id: 1, nome: "EM FICTICIA", cidade: null, estado: null }];

function responder(corpo: unknown, status = 200) {
  return new Response(JSON.stringify(corpo), { status, headers: { "Content-Type": "application/json" } });
}

async function servidorFalso(url: string, init?: RequestInit): Promise<Response> {
  const caminho = url.replace(/^.*\/api\/v1/, "");
  estado.chamadas.push(`${init?.method ?? "GET"} ${caminho}`);
  if (estado.pendurar.has(caminho)) {
    // Como o fetch do React Native sem tempo-limite: só termina se for cancelado
    // (ou se o teste "liberar" a resposta).
    return new Promise<Response>((resolver, rejeitar) => {
      estado.liberar.set(caminho, () => resolver(servidorNormal(caminho)));
      init?.signal?.addEventListener("abort", () => {
        rejeitar(Object.assign(new Error("Aborted"), { name: "AbortError" }));
      });
    });
  }
  return servidorNormal(caminho);
}

function servidorNormal(caminho: string): Response {
  if (caminho === "/auth/login") return responder({ access_token: "tok-ficticio", usuario: USUARIO });
  if (caminho === "/auth/me") return responder(USUARIO);
  if (caminho === "/escolas") return responder(ESCOLAS);
  if (caminho === "/escolas/1/dispositivos") return responder({ id: 1, plataforma: "android" });
  if (caminho.startsWith("/escolas/1/dispositivos/")) return responder({ mensagem: "Dispositivo removido." });
  return responder({ detail: "não simulado" }, 404);
}

import * as React from "react";
import { onlineManager } from "@tanstack/react-query";
import { act, cleanup, render, waitFor } from "@testing-library/react";

import { salvarSessao } from "../armazenamento/sessao";
import { ProvedorAutenticacao, useAutenticacao } from "../contexto/Autenticacao";

(globalThis as { React?: unknown }).React = React;

let ctx: ReturnType<typeof useAutenticacao>;
function Sonda() {
  ctx = useAutenticacao();
  return null;
}
const esperar = (ms: number) => new Promise((r) => setTimeout(r, ms));

function montar() {
  render(React.createElement(ProvedorAutenticacao, null, React.createElement(Sonda)));
}

async function entrarComoProfessora() {
  montar();
  await waitFor(() => expect(ctx.carregando).toBe(false));
  await act(async () => {
    await ctx.entrar("prof@ficticio.local", "senha-ficticia");
  });
  await waitFor(() => expect(estado.chamadas).toContain("POST /escolas/1/dispositivos"));
  await act(async () => {
    await esperar(20);
  });
}

beforeEach(() => {
  estado.cofre.clear();
  estado.disco.clear();
  estado.chamadas.length = 0;
  estado.pendurar.clear();
  estado.liberar.clear();
  onlineManager.setOnline(true);
  vi.stubGlobal("fetch", vi.fn(servidorFalso));
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("boot com a sessão salva e a rede pendurada", () => {
  it("abre na hora com os dados salvos (não fica em 'Abrindo o Constela Edu...')", async () => {
    estado.cofre.set("sgpe_token", "tok-ficticio");
    await salvarSessao({ usuario: USUARIO as never, escolas: ESCOLAS as never, escolaId: 1 });
    estado.pendurar.add("/auth/me");
    estado.pendurar.add("/escolas");
    montar();
    await act(async () => {
      await esperar(100);
    });
    expect(ctx.usuario?.email).toBe("prof@ficticio.local");
    expect(ctx.carregando).toBe(false);
  });

  it("controle: sem sessão salva (e com token) continua esperando a rede", async () => {
    estado.cofre.set("sgpe_token", "tok-ficticio");
    estado.pendurar.add("/auth/me");
    estado.pendurar.add("/escolas");
    montar();
    await act(async () => {
      await esperar(100);
    });
    expect(ctx.carregando).toBe(true);
  });

  it("se a pessoa sair enquanto o refresh do boot está pendurado, a resposta atrasada não a põe de volta", async () => {
    estado.cofre.set("sgpe_token", "tok-ficticio");
    await salvarSessao({ usuario: USUARIO as never, escolas: ESCOLAS as never, escolaId: 1 });
    estado.pendurar.add("/auth/me");
    estado.pendurar.add("/escolas");
    montar();
    await waitFor(() => expect(ctx.carregando).toBe(false));
    await act(async () => {
      await ctx.sair();
    });
    expect(ctx.usuario).toBeNull();
    await act(async () => {
      estado.liberar.get("/auth/me")?.();
      estado.liberar.get("/escolas")?.();
      await esperar(50);
    });
    expect(ctx.usuario).toBeNull();
    expect(estado.disco.has("constela_sessao_v1")).toBe(false);
  });
});

describe("'Sair da conta' com a rede pendurada", () => {
  it("encerra a sessão local na hora: usuário, token e sessão salva", async () => {
    await entrarComoProfessora();
    estado.pendurar.add("/escolas/1/dispositivos/descadastrar");
    let terminou = false;
    await act(async () => {
      void ctx.sair().then(() => {
        terminou = true;
      });
      await esperar(100);
    });
    expect(terminou).toBe(true);
    expect(ctx.usuario).toBeNull();
    expect(estado.cofre.has("sgpe_token")).toBe(false);
    expect(estado.disco.has("constela_sessao_v1")).toBe(false);
    // o pedido ao servidor continua em segundo plano e fica pendente se não chegar
    expect(estado.chamadas).toContain("POST /escolas/1/dispositivos/descadastrar");
    expect(estado.cofre.has("constela_push_descadastro_v1")).toBe(true);
  });
});
