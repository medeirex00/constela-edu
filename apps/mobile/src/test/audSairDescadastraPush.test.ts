// @vitest-environment jsdom
/**
 * "Sair" e sessão expirada tiram o aparelho do push (auditoria MOBILE-3, parte do
 * app, e AUTH-3).
 *
 * Antes: o token do push só existia na memória (`tokenPush`, preenchido no refresh
 * da rede do boot ou do login); `removerRegistroPush` fazia UMA chamada autenticada
 * ao /remover, engolia o erro, e o JWT era apagado logo depois. Abrir o app sem rede
 * deixava o token nulo pela sessão inteira (o "Sair" nem chamava a API); "Sair" sem
 * rede não tentava de novo; o 401 nem tentava. O aparelho seguia cadastrado para a
 * conta e recebendo, na tela bloqueada, o primeiro nome de criança.
 *
 * Código real de Autenticacao.tsx, api.ts, notificacoes.ts, filaOffline.ts, cifra,
 * sessão e do cliente do core; só os módulos nativos e o `fetch` (o servidor) são
 * dublês. Dados fictícios.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const estado = vi.hoisted(() => ({
  cofre: new Map<string, string>(), // SecureStore
  disco: new Map<string, string>(), // AsyncStorage
  chamadas: [] as string[],
  corpos: [] as { chave: string; corpo: unknown }[],
  semRede: false,
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
  let semente = 0x2468ace;
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
  getExpoPushTokenAsync: async () => ({ data: TOKEN }),
}));

const TOKEN = "ExponentPushToken[ficticio-0001]";
const USUARIO = { id: 9, nome: "Prof Ficticia", email: "prof@ficticio.local", cargo: "professor",
  is_global: false, escola_id: 1 };
const ESCOLAS = [{ id: 1, nome: "EM FICTICIA", cidade: null, estado: null }];

function responder(corpo: unknown, status = 200) {
  return new Response(JSON.stringify(corpo), { status, headers: { "Content-Type": "application/json" } });
}

let sessaoRevogada = false;
let statusDescadastro = 200;

async function servidorFalso(url: string, init?: RequestInit): Promise<Response> {
  const caminho = url.replace(/^.*\/api\/v1/, "");
  const chave = `${init?.method ?? "GET"} ${caminho}`;
  estado.chamadas.push(chave);
  if (caminho.startsWith("/escolas/") && init?.body) {
    estado.corpos.push({ chave, corpo: JSON.parse(String(init.body)) });
  }
  if (estado.semRede) throw new TypeError("Network request failed");
  if (caminho === "/auth/login") return responder({ access_token: "tok-ficticio", usuario: USUARIO });
  if (sessaoRevogada && caminho === "/auth/me") {
    return responder({ detail: "Sessão expirada. Entre novamente." }, 401);
  }
  if (caminho === "/auth/me") return responder(USUARIO);
  if (caminho === "/escolas") return responder(ESCOLAS);
  if (caminho === "/escolas/1/dispositivos") return responder({ id: 1, plataforma: "android" });
  if (caminho === "/escolas/1/dispositivos/descadastrar" && statusDescadastro !== 200) {
    return responder({ detail: "recusado" }, statusDescadastro);
  }
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
const descadastros = () =>
  estado.corpos.filter((c) => /\/dispositivos\/(remover|descadastrar)$/.test(c.chave));

function montar() {
  render(React.createElement(ProvedorAutenticacao, null, React.createElement(Sonda)));
}

/** "Sair" e o tempo de a tentativa em segundo plano chegar ao servidor falso. */
async function sairEEsperar() {
  await act(async () => {
    await ctx.sair();
    await esperar(30);
  });
}

async function entrarComoProfessora() {
  montar();
  await waitFor(() => expect(ctx.carregando).toBe(false));
  await act(async () => {
    await ctx.entrar("prof@ficticio.local", "senha-ficticia");
  });
  // o registro do push roda em segundo plano depois do login
  await waitFor(() => expect(estado.chamadas).toContain("POST /escolas/1/dispositivos"));
  await act(async () => {
    await esperar(20);
  });
}

beforeEach(() => {
  estado.cofre.clear();
  estado.disco.clear();
  estado.chamadas.length = 0;
  estado.corpos.length = 0;
  estado.semRede = false;
  sessaoRevogada = false;
  statusDescadastro = 200;
  onlineManager.setOnline(true);
  vi.stubGlobal("fetch", vi.fn(servidorFalso));
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Sair com rede boa (controle)", () => {
  it("tira o aparelho do push, o token e a sessão", async () => {
    await entrarComoProfessora();
    await sairEEsperar();
    expect(ctx.usuario).toBeNull();
    expect(estado.cofre.has("sgpe_token")).toBe(false);
    expect(descadastros().map((d) => d.corpo)).toEqual([{ token_push: TOKEN }]);
  });
});

describe("app aberto SEM rede, depois 'Sair' com rede (AUTH-3)", () => {
  it("tira o aparelho do push com o token registrado na sessão anterior", async () => {
    await entrarComoProfessora(); // sessão anterior, com rede: registrou o aparelho
    cleanup(); // fecha o app sem sair
    estado.chamadas.length = 0;
    estado.corpos.length = 0;

    estado.semRede = true; // abre de novo sem sinal
    montar();
    await waitFor(() => expect(ctx.carregando).toBe(false));
    expect(ctx.usuario?.email).toBe("prof@ficticio.local"); // sessão salva restaurada
    estado.semRede = false; // a rede volta

    await sairEEsperar();
    expect(descadastros().map((d) => d.corpo)).toEqual([{ token_push: TOKEN }]);
  });
});

describe("'Sair' sem rede (MOBILE-3)", () => {
  it("o descadastro fica pendente e é feito quando a rede volta", async () => {
    await entrarComoProfessora();
    estado.semRede = true;
    await sairEEsperar();
    expect(ctx.usuario).toBeNull(); // a sessão local acabou
    expect(estado.cofre.has("sgpe_token")).toBe(false);
    const antes = descadastros().length;

    estado.semRede = false; // a rede volta
    await act(async () => {
      onlineManager.setOnline(false);
      onlineManager.setOnline(true);
      await esperar(30);
    });
    const depois = estado.corpos.filter((c) => c.chave === "POST /escolas/1/dispositivos/descadastrar");
    expect(descadastros().length).toBeGreaterThan(antes);
    expect(depois.map((d) => d.corpo)).toContainEqual({ token_push: TOKEN });

    // feito uma vez, não repete
    const total = descadastros().length;
    await act(async () => {
      onlineManager.setOnline(false);
      onlineManager.setOnline(true);
      await esperar(30);
    });
    expect(descadastros().length).toBe(total);
  });

  it("se o app fechar antes de a rede voltar, o descadastro sai na próxima abertura", async () => {
    await entrarComoProfessora();
    estado.semRede = true;
    await sairEEsperar();
    cleanup(); // fecha o app
    estado.semRede = false;
    estado.corpos.length = 0;
    montar(); // abre de novo (na tela de entrar)
    await waitFor(() => expect(ctx.carregando).toBe(false));
    await act(async () => {
      await esperar(30);
    });
    expect(ctx.usuario).toBeNull();
    expect(descadastros().map((d) => d.corpo)).toEqual([{ token_push: TOKEN }]);
  });

  it("entrar de novo no aparelho cancela o descadastro pendente da saída anterior", async () => {
    await entrarComoProfessora();
    estado.semRede = true;
    await sairEEsperar();
    estado.semRede = false;
    estado.corpos.length = 0;
    await act(async () => {
      await ctx.entrar("prof@ficticio.local", "senha-ficticia");
    });
    await waitFor(() => expect(estado.chamadas).toContain("POST /escolas/1/dispositivos"));
    await act(async () => {
      onlineManager.setOnline(false);
      onlineManager.setOnline(true);
      await esperar(30);
    });
    // O aparelho ficou registrado para quem entrou: nada depois do novo registro o tira.
    const ordem = estado.corpos.map((c) => c.chave);
    const ultimoRegistro = ordem.lastIndexOf("POST /escolas/1/dispositivos");
    expect(ordem.slice(ultimoRegistro + 1).filter((c) => /dispositivos\//.test(c))).toEqual([]);
  });
});

describe("resposta do servidor ao descadastro", () => {
  async function reconectar() {
    await act(async () => {
      onlineManager.setOnline(false);
      onlineManager.setOnline(true);
      await esperar(30);
    });
  }

  it("429 (muitas tentativas) ou 503: continua pendente e sai depois", async () => {
    await entrarComoProfessora();
    statusDescadastro = 429;
    await sairEEsperar();
    statusDescadastro = 503;
    await reconectar();
    statusDescadastro = 200;
    estado.corpos.length = 0;
    await reconectar();
    expect(descadastros().map((d) => d.corpo)).toEqual([{ token_push: TOKEN }]);
  });

  it("recusa definitiva (422): não fica repetindo para sempre", async () => {
    await entrarComoProfessora();
    statusDescadastro = 422;
    await sairEEsperar();
    expect(descadastros()).toHaveLength(1);
    await reconectar();
    expect(descadastros()).toHaveLength(1);
  });
});

describe("sessão expirada ou revogada (401)", () => {
  it("o app sai da conta e tira o aparelho do push", async () => {
    await entrarComoProfessora();
    cleanup();
    estado.corpos.length = 0;
    sessaoRevogada = true;
    montar(); // o refresh do boot leva 401
    await waitFor(() => expect(ctx.carregando).toBe(false));
    await act(async () => {
      await esperar(50);
    });
    expect(ctx.usuario).toBeNull();
    expect(descadastros().map((d) => d.corpo)).toEqual([{ token_push: TOKEN }]);
  });
});

describe("salvarSessao", () => {
  it("continua sendo o que o boot offline lê (arnês)", async () => {
    estado.cofre.set("sgpe_token", "tok-ficticio");
    await salvarSessao({ usuario: USUARIO as never, escolas: ESCOLAS as never, escolaId: 1 });
    estado.semRede = true;
    montar();
    await waitFor(() => expect(ctx.carregando).toBe(false));
    expect(ctx.usuario?.email).toBe("prof@ficticio.local");
  });
});
