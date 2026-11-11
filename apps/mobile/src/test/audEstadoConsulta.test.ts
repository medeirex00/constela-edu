/**
 * Decisão única do estado de uma tela que lê uma consulta (auditoria MOBILE-4 e
 * OBSERVABILIDADE-5): erro do servidor é erro, não "sem dados" nem "sem internet".
 */
import { describe, expect, it } from "vitest";

import { ApiError } from "@constela/core";

import { estadoDaConsulta } from "../estadoConsulta";

const base = { data: undefined, isLoading: false, isError: false, error: null };

describe("estadoDaConsulta", () => {
  it("buscando pela primeira vez: carregando", () => {
    expect(estadoDaConsulta({ ...base, isLoading: true })).toEqual({ tipo: "carregando" });
  });

  it("erro sem nada salvo: erro com a mensagem do servidor", () => {
    const estado = estadoDaConsulta({ ...base, isError: true, error: new ApiError(403, "Sem acesso a esta escola.") });
    expect(estado).toEqual({ tipo: "erro", mensagem: "Sem acesso a esta escola." });
  });

  it("falha que não veio do cliente da API não mostra texto técnico", () => {
    const estado = estadoDaConsulta({ ...base, isError: true, error: new SyntaxError("Unexpected token <") });
    expect(estado.tipo).toBe("erro");
    expect(estado).not.toEqual(expect.objectContaining({ mensagem: expect.stringContaining("Unexpected") }));
  });

  it("nada salvo, sem erro e sem buscar (sem rede, consulta pausada): sem dados", () => {
    expect(estadoDaConsulta(base)).toEqual({ tipo: "semDados" });
  });

  it("com dados: mostra os dados; se a atualização falhou, com aviso", () => {
    expect(estadoDaConsulta({ ...base, data: [1] })).toEqual({ tipo: "dados", dados: [1], aviso: null });
    expect(estadoDaConsulta({ ...base, data: [1], isError: true, error: new ApiError(500, "Erro interno.") }))
      .toEqual({ tipo: "dados", dados: [1], aviso: "Erro interno." });
  });
});
