import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ApiError, MENSAGEM_SEM_REDE, api, apiBlob, apiUpload, configurarApi, guardarToken,
} from "./cliente";

describe("cliente HTTP: falha de rede vira ApiError(0) em pt-BR", () => {
  const fetchOriginal = globalThis.fetch;
  afterEach(() => {
    globalThis.fetch = fetchOriginal;
    vi.restoreAllMocks();
  });

  it("rejeição do fetch (rede/DNS/offline) → ApiError(0) com mensagem pt-BR, nunca 'Failed to fetch'", async () => {
    globalThis.fetch = vi.fn(() =>
      Promise.reject(new TypeError("Failed to fetch")),
    ) as unknown as typeof fetch;

    const erro = (await api("/qualquer").catch((e) => e)) as ApiError;
    expect(erro).toBeInstanceOf(ApiError);
    expect(erro.status).toBe(0);
    expect(erro.message).toBe(MENSAGEM_SEM_REDE);
    expect(erro.message).not.toMatch(/failed to fetch/i);
  });

  it("resposta HTTP de erro preserva o status do servidor (não é tratada como rede)", async () => {
    globalThis.fetch = vi.fn(() =>
      Promise.resolve(
        new Response(JSON.stringify({ detail: "Requisição inválida." }), {
          status: 400,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    ) as unknown as typeof fetch;

    const erro = (await api("/qualquer").catch((e) => e)) as ApiError;
    expect(erro).toBeInstanceOf(ApiError);
    expect(erro.status).toBe(400);
  });

  it("422 de validação (detail em LISTA, Pydantic) vira mensagem legível, sem o prefixo 'Value error'", async () => {
    globalThis.fetch = vi.fn(() =>
      Promise.resolve(
        new Response(JSON.stringify({ detail: [
          { type: "value_error", loc: ["body", "senha"], msg: "Value error, Senha muito comum. Escolha outra.", input: "12345678" },
          { type: "value_error", loc: ["body", "senha"], msg: "Value error, Senha muito comum. Escolha outra.", input: "12345678" },
          { type: "missing", loc: ["body", "nome"], msg: "Field required", input: {} },
        ] }), { status: 422, headers: { "Content-Type": "application/json" } }),
      ),
    ) as unknown as typeof fetch;

    const erro = (await api("/qualquer", { method: "POST" }).catch((e) => e)) as ApiError;
    expect(erro.status).toBe(422);
    expect(erro.message).toBe("Senha muito comum. Escolha outra. Field required");
    expect(erro.message).not.toMatch(/value error/i);
    expect(erro.message).not.toBe("Não foi possível completar a operação.");
  });
});

describe("401 e troca de sessão", () => {
  afterEach(() => vi.unstubAllGlobals());

  function simular401() {
    let responder!: (response: Response) => void;
    const fetchFalso = vi.fn(() => new Promise<Response>((resolve) => { responder = resolve; }));
    vi.stubGlobal("fetch", fetchFalso);
    return { fetchFalso, recusar: () => responder(new Response(null, { status: 401 })) };
  }

  const chamadas = [
    { nome: "JSON", enviar: () => api("/recurso") },
    { nome: "upload", enviar: () => apiUpload("/recurso", new FormData()) },
    { nome: "download", enviar: () => apiBlob("/recurso") },
  ];

  it.each(chamadas)("$nome preserva o token da conta que entrou após a requisição", async ({ enviar }) => {
    let token: string | null = "token-anterior";
    const remover = vi.fn(async () => { token = null; });
    const expirar = vi.fn();
    configurarApi({
      armazenamento: { obter: async () => token, guardar: async (valor) => { token = valor; }, remover },
      aoExpirarSessao: expirar,
    });
    const { fetchFalso, recusar } = simular401();
    const resultado = enviar();
    await vi.waitFor(() => expect(fetchFalso).toHaveBeenCalledWith(
      "/api/v1/recurso", expect.objectContaining({ headers: expect.objectContaining({
        Authorization: "Bearer token-anterior",
      }) }),
    ));

    await guardarToken("token-novo");
    recusar();

    await expect(resultado).rejects.toMatchObject({ status: 401 });
    expect(token).toBe("token-novo");
    expect(remover).not.toHaveBeenCalled();
    expect(expirar).not.toHaveBeenCalled();
  });

  it("remove o token que recebeu a recusa e avisa uma vez quando há dois 401", async () => {
    let token: string | null = "token-atual";
    const remover = vi.fn(async () => { token = null; });
    const expirar = vi.fn();
    configurarApi({
      armazenamento: { obter: async () => token, guardar: () => undefined, remover },
      aoExpirarSessao: expirar,
    });
    vi.stubGlobal("fetch", vi.fn(async () => new Response(null, { status: 401 })));

    const resultados = await Promise.allSettled([api("/recurso"), api("/outro")]);

    expect(resultados).toEqual([
      expect.objectContaining({ reason: expect.objectContaining({ status: 401 }) }),
      expect.objectContaining({ reason: expect.objectContaining({ status: 401 }) }),
    ]);
    expect(token).toBeNull();
    expect(remover).toHaveBeenCalledTimes(1);
    expect(expirar).toHaveBeenCalledTimes(1);
  });
});
