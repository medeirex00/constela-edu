/**
 * Sino de notificações quando a API falha (auditoria OBSERVABILIDADE-10).
 *
 * Antes: o GET /notificacoes falhando caía no mesmo estado da lista vazia e o
 * popover afirmava "Nenhuma novidade por enquanto." enquanto o contador dizia que
 * havia avisos não lidos (inclusive os críticos de coleta). E o POST
 * /notificacoes/marcar-lidas falhando era engolido e o contador zerava mesmo assim.
 */
import { describe, expect, it } from "vitest";

import Layout from "../components/Layout";
import { ImportacaoLoteProvider } from "../context/ImportacaoLoteContext";
import { api } from "../lib/api";
import {
  escolaFake, renderComApp, responder, responderErro, screen, userEvent, usuarioFake, waitFor,
} from "./utils";

function aviso(id: number, titulo: string) {
  return { id, tipo: "sync_falhou", severidade: "critico", titulo, rota: null, lida: false,
    autor: null, data: "2026-10-10T10:00:00" };
}

async function montar(naoLidas: number) {
  responder("GET", "/escolas/1/sync/onboarding", { lista_piloto_importada: true });
  responder("GET", "/notificacoes/contador", { nao_lidas: naoLidas });
  const usuario = usuarioFake({ cargo: "coordenador", nome: "Coordenadora Ficticia" });
  renderComApp(<ImportacaoLoteProvider><Layout /></ImportacaoLoteProvider>,
    { usuario, escolas: [escolaFake({ id: 1 })] });
  await screen.findAllByText(usuario.nome);
  await screen.findByRole("button", { name: `Notificações (${naoLidas} não lidas)` });
}

const listas = () => api.mock.calls.filter(([c]) => String(c) === "/notificacoes").length;

describe("Sino de notificações com a API falhando", () => {
  it("falha ao listar NÃO vira 'Nenhuma novidade': diz que não carregou, mantém o contador e tenta de novo", async () => {
    responderErro("GET", "/notificacoes", 500, "Erro interno. Tente novamente em instantes.");
    await montar(3);

    await userEvent.click(screen.getByRole("button", { name: /Notificações/ }));
    expect(await screen.findByText("Não foi possível carregar as notificações.")).toBeInTheDocument();
    expect(screen.queryByText("Nenhuma novidade por enquanto.")).toBeNull();
    // Ninguém viu nada: o contador continua dizendo que há 3 avisos.
    expect(screen.getByRole("button", { name: "Notificações (3 não lidas)" })).toBeInTheDocument();
    expect(api.mock.calls.some(([c]) => String(c) === "/notificacoes/marcar-lidas")).toBe(false);

    // A API voltou: "Tentar de novo" busca outra vez e mostra a lista.
    responder("GET", "/notificacoes", [aviso(1, "A coleta do Elefante falhou")]);
    responder("POST", "/notificacoes/marcar-lidas", {});
    const antes = listas();
    await userEvent.click(screen.getByRole("button", { name: "Tentar de novo" }));
    expect(await screen.findByText("A coleta do Elefante falhou")).toBeInTheDocument();
    expect(listas()).toBe(antes + 1);
    expect(screen.queryByText("Não foi possível carregar as notificações.")).toBeNull();
    await screen.findByRole("button", { name: "Notificações" });
  });

  it("marcar como lidas falhou: a lista aparece, mas o contador NÃO zera", async () => {
    responder("GET", "/notificacoes", [aviso(1, "A coleta do Matific falhou"), aviso(2, "Backup atrasado")]);
    responderErro("POST", "/notificacoes/marcar-lidas", 500, "Erro interno.");
    await montar(2);

    await userEvent.click(screen.getByRole("button", { name: /Notificações/ }));
    expect(await screen.findByText("A coleta do Matific falhou")).toBeInTheDocument();
    await waitFor(() => expect(
      api.mock.calls.some(([c]) => String(c) === "/notificacoes/marcar-lidas")).toBe(true));
    // O servidor não gravou a leitura: o sino continua avisando.
    expect(screen.getByRole("button", { name: "Notificações (2 não lidas)" })).toBeInTheDocument();
  });

  it("marcar como lidas deu certo: o contador zera (comportamento de sempre)", async () => {
    responder("GET", "/notificacoes", [aviso(1, "A coleta do Matific falhou")]);
    responder("POST", "/notificacoes/marcar-lidas", {});
    await montar(1);

    await userEvent.click(screen.getByRole("button", { name: /Notificações/ }));
    expect(await screen.findByText("A coleta do Matific falhou")).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Notificações" })).toBeInTheDocument();
  });
});
