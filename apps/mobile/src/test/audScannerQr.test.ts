// @vitest-environment jsdom
/**
 * Scanner de QR (auditoria MOBILE-7): o app só abre sozinho o endereço do Painel
 * Público do produto. Antes, qualquer texto que começasse com http(s):// era aberto
 * com "Abrindo painel...", inclusive sem TLS e de qualquer domínio (um adesivo com
 * outro QR por cima do cartaz da escola levava a uma página de terceiros aberta pelo
 * app). Tela real; câmera, Linking e o diálogo nativo são dublês. Dados fictícios.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { abrir, leitor } = vi.hoisted(() => ({
  abrir: vi.fn(async () => undefined),
  leitor: { aoLer: null as null | ((evento: { data: string }) => Promise<void>) },
}));

vi.mock("react", async () => {
  const { createRequire } = await import("node:module");
  const path = await import("node:path");
  const exigir = createRequire(import.meta.url);
  const dirReactDom = path.dirname(exigir.resolve("react-dom/package.json"));
  return exigir(exigir.resolve("react", { paths: [dirReactDom] }));
});
vi.mock("react-native", async () => (await import("./_rnFalso")).reactNativeFalso);
vi.mock("expo-linking", () => ({ openURL: abrir }));
vi.mock("expo-camera", () => ({
  useCameraPermissions: () => [{ granted: true }, async () => ({ granted: true })],
  CameraView: ({ onBarcodeScanned }: { onBarcodeScanned: (e: { data: string }) => Promise<void> }) => {
    leitor.aoLer = onBarcodeScanned;
    return null;
  },
}));

import * as React from "react";
import { act, cleanup, render } from "@testing-library/react";

import { alertas } from "./_rnFalso";
import Scanner from "../telas/Scanner";

(globalThis as { React?: unknown }).React = React;

async function ler(texto: string) {
  const tela = render(React.createElement(Scanner));
  await act(async () => {
    await leitor.aoLer!({ data: texto });
  });
  return tela;
}

describe("Scanner de QR do Painel Público", () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["setTimeout"] });
    alertas.length = 0;
  });
  afterEach(() => {
    cleanup();
    abrir.mockClear();
    vi.useRealTimers();
  });

  it.each([
    "https://www.constelaedu.com/p/AbC123_-xYz9",
    "https://constelaedu.com/p/AbC123_-xYz9",
    "HTTPS://WWW.CONSTELAEDU.COM/p/AbC123_-xYz9",
  ])("abre direto o painel do produto: %s", async (url) => {
    const tela = await ler(url);
    expect(abrir).toHaveBeenCalledTimes(1);
    expect(alertas).toHaveLength(0);
    expect(tela.container.textContent).toContain("Painel aberto no navegador");
  });

  it.each([
    "https://constela-edu-entrar.example/login?escola=1",
    "http://192.0.2.10/painel",
    "http://www.constelaedu.com/p/AbC123_-xYz9", // sem TLS
    "https://www.constelaedu.com.example/p/AbC123_-xYz9",
    "https://www.constelaedu.com@outro.example/p/AbC123_-xYz9",
    "https://www.constelaedu.com:8443/p/AbC123_-xYz9",
    "https://www.constelaedu.com/login",
  ])("não abre sozinho o que não é o painel do produto: %s", async (url) => {
    const tela = await ler(url);
    expect(abrir).not.toHaveBeenCalled();
    expect(tela.container.textContent).not.toContain("Abrindo painel");
    // Mostra o endereço e deixa a pessoa decidir.
    expect(alertas).toHaveLength(1);
    expect(alertas[0].mensagem).toContain(url);
  });

  it("endereço de fora: só abre se a pessoa confirmar", async () => {
    const url = "http://192.0.2.10:8040/p/AbC123_-xYz9"; // demonstração local
    const tela = await ler(url);
    // Pode ser o painel de uma instalação própria do Constela (PUBLIC_BASE_URL no IP
    // da rede): o app só sabe que não reconhece o endereço (REV-MOBILE-3).
    expect(tela.container.textContent).toContain(
      "O app não reconhece este endereço como o painel do Constela Edu.",
    );
    expect(tela.container.textContent).not.toContain("não é do painel");
    expect(alertas[0].titulo).toBe("Endereço não reconhecido");
    expect(alertas[0].mensagem).toBe(`Ele leva para:\n\n${url}\n\nSó abra se você confia neste endereço.`);
    const botoes = alertas[0].botoes;
    expect(botoes.map((b) => b.text)).toEqual(["Cancelar", "Abrir mesmo assim"]);
    await act(async () => {
      botoes[1].onPress!();
    });
    expect(abrir).toHaveBeenCalledWith(url);
  });

  it("com o aviso aberto, a câmera não repete o aviso; depois de Cancelar, volta a ler", async () => {
    const url = "https://constela-edu-entrar.example/login";
    await ler(url);
    expect(alertas).toHaveLength(1);
    await act(async () => {
      vi.advanceTimersByTime(10_000); // a câmera segue vendo o mesmo QR
      await leitor.aoLer!({ data: url });
    });
    expect(alertas).toHaveLength(1);
    await act(async () => {
      alertas[0].botoes[0].onPress!(); // Cancelar
      vi.advanceTimersByTime(2_500);
      await leitor.aoLer!({ data: url });
    });
    expect(alertas).toHaveLength(2);
    expect(abrir).not.toHaveBeenCalled();
  });

  it("texto que não é endereço continua ignorado", async () => {
    const tela = await ler("javascript:alert(1)");
    expect(abrir).not.toHaveBeenCalled();
    expect(alertas).toHaveLength(0);
    expect(tela.container.textContent).toContain("QR code não reconhecido");
  });
});
