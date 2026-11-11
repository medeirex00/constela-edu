/**
 * S_G_AUTOMACAO-1 — o socorro do "chunk obsoleto" (lib/atualizacao.ts) e o botão
 * "Recarregar" do LimiteErro não apagam o cache do PWA.
 *
 * O Cache Storage e o registro do service worker são da ORIGEM — de todas as abas do
 * navegador. O socorro apagava todos os caches: a outra aba que ainda rodava a versão
 * antiga (com o aviso "Nova versão disponível", esperando o clique) perdia os arquivos
 * dela e recarregava sozinha na próxima tela que abrisse; a aba que já estava na versão
 * nova perdia o app sem rede até o próximo deploy. Para a recarga desta aba vir da rede
 * basta desregistrar o service worker — é o que o plano B (pwaAtualizacao.ts) já faz.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LimiteErro } from "../components/LimiteErro";
import { recuperarDeChunkObsoleto } from "../lib/atualizacao";

const PRECACHE = "workbox-precache-v2-https://constela.exemplo.test/";

let apagados: string[];
let desregistrados: number;
let recarga: ReturnType<typeof vi.fn>;
const locationOriginal = window.location;
const swOriginal = Object.getOwnPropertyDescriptor(navigator, "serviceWorker");

beforeEach(() => {
  apagados = [];
  desregistrados = 0;
  recarga = vi.fn();
  sessionStorage.clear();
  vi.spyOn(console, "error").mockImplementation(() => undefined);
  vi.stubGlobal("caches", {
    keys: async () => [PRECACHE],
    delete: async (chave: string) => {
      apagados.push(chave);
      return true;
    },
  });
  Object.defineProperty(navigator, "serviceWorker", {
    configurable: true,
    value: {
      getRegistrations: async () => [{
        unregister: async () => {
          desregistrados += 1;
          return true;
        },
      }],
    },
  });
  Object.defineProperty(window, "location", {
    configurable: true,
    value: { ...locationOriginal, reload: recarga },
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  Object.defineProperty(window, "location", { configurable: true, value: locationOriginal });
  if (swOriginal) Object.defineProperty(navigator, "serviceWorker", swOriginal);
  else delete (navigator as unknown as Record<string, unknown>).serviceWorker;
  sessionStorage.clear();
});

describe("socorro do chunk obsoleto × cache das outras abas", () => {
  it("desregistra o service worker e recarrega UMA vez, sem apagar o cache que outra aba usa", async () => {
    recuperarDeChunkObsoleto();
    await waitFor(() => expect(recarga).toHaveBeenCalledTimes(1));
    expect(desregistrados).toBe(1);
    expect(apagados).toEqual([]);

    // Na mesma sessão não tenta de novo (o chunk pode estar quebrado de verdade).
    recuperarDeChunkObsoleto();
    await new Promise((fim) => setTimeout(fim, 0));
    expect(recarga).toHaveBeenCalledTimes(1);
  });

  it("o erro de chunk pego pelo LimiteErro também não apaga o cache", async () => {
    function TelaQueSumiu(): never {
      throw new TypeError("Failed to fetch dynamically imported module: /assets/Tela-antiga.js");
    }
    render(
      <LimiteErro>
        <TelaQueSumiu />
      </LimiteErro>,
    );
    await waitFor(() => expect(recarga).toHaveBeenCalledTimes(1));
    expect(apagados).toEqual([]);
  });

  it("o botão Recarregar da tela de erro recarrega sem apagar o cache das outras abas", async () => {
    function Bomba(): never {
      throw new Error("erro comum de tela");
    }
    render(
      <LimiteErro>
        <Bomba />
      </LimiteErro>,
    );
    expect(recarga).not.toHaveBeenCalled();     // erro comum: espera o clique
    fireEvent.click(screen.getByRole("button", { name: "Recarregar" }));
    await waitFor(() => expect(recarga).toHaveBeenCalledTimes(1));
    expect(apagados).toEqual([]);
  });
});
