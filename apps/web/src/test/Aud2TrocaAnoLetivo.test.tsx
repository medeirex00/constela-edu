/**
 * Troca do ano letivo ativo em Configurações (G_VIRADA-4): a troca muda o ano de notas,
 * rankings e premiações e, depois da Lista Piloto, só se desfaz com regra — então a tela
 * pede confirmação dizendo o que a troca faz, avisa quando o ano está mais de um ano à
 * frente do ano de hoje (erro de digitação: 2072 em vez de 2027) e, ao voltar o ano, diz
 * que as notas do ano desfeito são apagadas. Salvar sem mudar o ano não pergunta nada.
 */
import { describe, expect, it } from "vitest";

import Configuracoes from "../pages/configuracoes/Configuracoes";
import { hojeEmBrasilia } from "../lib/dataRelatorio";
import { api, renderComApp, responder, screen, userEvent, usuarioFake, within } from "./utils";

const URL_ESCOLA = "/escolas/1";
const global = usuarioFake({ is_global: true, cargo: "admin", nome: "Root" });
const ANO_HOJE = Number(hojeEmBrasilia().slice(0, 4));

function carregar() {
  responder("GET", "/escolas/1/configuracoes/pesos/geral",
    { namespace: "geral", valores: { matific: 60, elefante: 40 }, soma: 100 });
  responder("GET", "/escolas/1/aparencia", { cor_primaria: "#1B2A4A" });
  responder("PATCH", URL_ESCOLA, { id: 1, nome: "Escola Modelo Constela" });
}

function patches() {
  return api.mock.calls.filter(
    ([url, opcoes]) => url === URL_ESCOLA && (opcoes as RequestInit | undefined)?.method === "PATCH",
  );
}

async function trocarAno(u: ReturnType<typeof userEvent.setup>, ano: number) {
  // O formulário semeado com a escola atual (o ano em uso vem dela).
  await screen.findByDisplayValue("Escola Modelo Constela", undefined, { timeout: 3000 });
  const campo = screen.getByRole("spinbutton", { name: "Ano letivo ativo" });
  await u.clear(campo);
  await u.type(campo, String(ano));
  await u.click(screen.getByRole("button", { name: "Salvar dados da escola" }));
}

describe("Configurações — troca do ano letivo ativo", () => {
  it("avançar o ano pede confirmação e só então salva", async () => {
    const u = userEvent.setup();
    carregar();
    renderComApp(<Configuracoes />, { rota: "/configuracoes", usuario: global });

    await trocarAno(u, 2027);
    const dialogo = await screen.findByRole("dialog", { name: "Trocar o ano letivo ativo?" });
    expect(dialogo).toHaveTextContent("A escola passa do ano letivo 2026 para 2027.");
    expect(dialogo).toHaveTextContent(
      "Notas, rankings e premiações passam a ser do ano letivo 2027; as notas de 2026 ficam "
      + "guardadas como histórico.");
    expect(patches()).toHaveLength(0);

    await u.click(within(dialogo).getByRole("button", { name: "Trocar para 2027" }));
    expect(await screen.findByText("Dados da escola atualizados.")).toBeInTheDocument();
    expect(patches()).toHaveLength(1);
    expect(JSON.parse(String((patches()[0][1] as RequestInit).body)).ano_letivo_ativo).toBe(2027);
  });

  it("ano mais de um ano à frente de hoje traz o aviso de erro de digitação", async () => {
    const u = userEvent.setup();
    carregar();
    renderComApp(<Configuracoes />, { rota: "/configuracoes", usuario: global });

    const adiante = ANO_HOJE + 46;
    await trocarAno(u, adiante);
    const dialogo = await screen.findByRole("dialog", { name: "Trocar o ano letivo ativo?" });
    expect(dialogo).toHaveTextContent(
      `Atenção: ${adiante} está mais de um ano à frente de ${ANO_HOJE}. Confira se não houve `
      + "erro de digitação.");
  });

  it("voltar o ano diz que é para corrigir e que as notas do ano desfeito saem", async () => {
    const u = userEvent.setup();
    carregar();
    renderComApp(<Configuracoes />, { rota: "/configuracoes", usuario: global });

    await trocarAno(u, 2025);
    const dialogo = await screen.findByRole("dialog", { name: "Trocar o ano letivo ativo?" });
    expect(dialogo).toHaveTextContent(
      "Voltar o ano serve para corrigir um ano digitado errado: as notas já calculadas "
      + "depois de 2025 são apagadas e refeitas quando a escola chegar a esse ano. Não é "
      + "possível voltar para antes de um ano que já tem notas guardadas como histórico.");
    expect(dialogo).not.toHaveTextContent("Atenção:");
  });

  it("cancelar não salva nada", async () => {
    const u = userEvent.setup();
    carregar();
    renderComApp(<Configuracoes />, { rota: "/configuracoes", usuario: global });

    await trocarAno(u, 2027);
    const dialogo = await screen.findByRole("dialog", { name: "Trocar o ano letivo ativo?" });
    await u.click(within(dialogo).getByRole("button", { name: "Cancelar" }));
    expect(screen.queryByRole("dialog", { name: "Trocar o ano letivo ativo?" })).toBeNull();
    expect(patches()).toHaveLength(0);
  });

  it("salvar sem mudar o ano não pede confirmação", async () => {
    const u = userEvent.setup();
    carregar();
    renderComApp(<Configuracoes />, { rota: "/configuracoes", usuario: global });

    await screen.findByDisplayValue("Escola Modelo Constela");
    await u.click(screen.getByRole("button", { name: "Salvar dados da escola" }));
    expect(await screen.findByText("Dados da escola atualizados.")).toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "Trocar o ano letivo ativo?" })).toBeNull();
    expect(patches()).toHaveLength(1);
  });
});
