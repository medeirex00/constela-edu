/**
 * O descadastro do push tem tempo-limite (auditoria MOBILE-2).
 *
 * Sem tempo-limite no fetch do React Native, um pedido que não responde ficava
 * preso para sempre — e, na fila de passos do push, segurava o próximo registro ou
 * descadastro. Com o limite, o pedido é cancelado, o descadastro continua pendente
 * e sai na próxima tentativa. notificacoes.ts real; `api`, SecureStore e o
 * onlineManager são dublês. Dados fictícios.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { cofre, apiMock } = vi.hoisted(() => ({
  cofre: new Map<string, string>(),
  apiMock: vi.fn(),
}));

vi.mock("@constela/core", async (real) => ({
  ...(await real<typeof import("@constela/core")>()),
  api: apiMock,
}));
vi.mock("@tanstack/react-query", () => ({
  onlineManager: { isOnline: () => true, subscribe: () => () => undefined },
}));
vi.mock("expo-secure-store", () => ({
  getItemAsync: async (k: string) => cofre.get(k) ?? null,
  setItemAsync: async (k: string, v: string) => void cofre.set(k, v),
  deleteItemAsync: async (k: string) => void cofre.delete(k),
}));
vi.mock("expo-constants", () => ({ default: { expoConfig: { extra: {} } } }));
vi.mock("expo-device", () => ({ isDevice: true }));
vi.mock("expo-notifications", () => ({ setNotificationHandler: () => undefined }));
vi.mock("react-native", () => ({ Platform: { OS: "android" } }));
vi.mock("../filaOffline", () => ({ enviarOuEnfileirar: async () => undefined }));

import { descadastrarPendente, removerRegistroPush } from "../notificacoes";

const REGISTRO = JSON.stringify({ escolaId: 1, token: "ExponentPushToken[ficticio-0003]" });

describe("descadastro do push com a rede pendurada", () => {
  beforeEach(() => {
    cofre.clear();
    apiMock.mockReset();
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("cancela o pedido depois do tempo-limite e deixa o descadastro pendente", async () => {
    cofre.set("constela_push_registro_v1", REGISTRO);
    let sinal: AbortSignal | undefined;
    apiMock.mockImplementation((_caminho: string, opcoes: RequestInit) => {
      sinal = opcoes.signal ?? undefined;
      return new Promise((_resolver, rejeitar) => {
        opcoes.signal?.addEventListener("abort", () =>
          rejeitar(Object.assign(new Error("Aborted"), { name: "AbortError" })));
      });
    });

    await removerRegistroPush(); // volta sem esperar o servidor
    expect(cofre.get("constela_push_descadastro_v1")).toBe(REGISTRO);
    await vi.advanceTimersByTimeAsync(0); // a tentativa em segundo plano sai
    expect(apiMock).toHaveBeenCalledTimes(1);
    expect(sinal).toBeDefined();
    expect(sinal!.aborted).toBe(false);

    await vi.advanceTimersByTimeAsync(8_000);
    expect(sinal!.aborted).toBe(true);
    expect(cofre.get("constela_push_descadastro_v1")).toBe(REGISTRO); // continua pendente

    // a próxima tentativa (rede de volta) acontece e conclui
    apiMock.mockReset();
    apiMock.mockResolvedValue({ mensagem: "Dispositivo removido." });
    await descadastrarPendente();
    expect(apiMock).toHaveBeenCalledWith(
      "/escolas/1/dispositivos/descadastrar",
      expect.objectContaining({ method: "POST" }),
    );
    expect(cofre.has("constela_push_descadastro_v1")).toBe(false);
  });
});
