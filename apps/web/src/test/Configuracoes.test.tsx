import { describe, expect, it } from "vitest";

import Configuracoes from "../pages/configuracoes/Configuracoes";
import { api, renderComApp, responder, responderErro, screen, userEvent } from "./utils";

// Endpoints disparados no carregamento pela coordenadora (usuário padrão, não-admin):
// - PesosEditor (namespace "geral") -> GET pesos
// - Aparência -> GET aparencia
// Backup e Assistente de IA são só-admin: não renderizam com o usuário padrão.
const URL_PESOS = "/escolas/1/configuracoes/pesos/geral";
const URL_APARENCIA = "/escolas/1/aparencia";
const URL_ESCOLA = "/escolas/1";

/** Registra as respostas de sucesso que a tela busca ao montar. */
function carregarSucesso() {
  responder("GET", URL_PESOS, {
    namespace: "geral",
    valores: { matific: 60, elefante: 40 },
    soma: 100,
  });
  responder("GET", URL_APARENCIA, { cor_primaria: "#1B2A4A" });
}

describe("Configurações", () => {
  it("carrega e mostra os dados da escola e os pesos do Ranking Geral", async () => {
    carregarSucesso();
    renderComApp(<Configuracoes />, { rota: "/configuracoes" });

    expect(
      await screen.findByRole("heading", { name: "Configurações", level: 1 }),
    ).toBeInTheDocument();
    // Formulário da escola semeado a partir da escola atual (id=1).
    expect(await screen.findByDisplayValue("Escola Modelo Constela")).toBeInTheDocument();
    // Pesos do Ranking Geral: rótulos vindos do PesosEditor.
    expect(await screen.findByText("Matific")).toBeInTheDocument();
    expect(screen.getByText("Elefante Letrado")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Salvar dados da escola" })).toBeInTheDocument();
  });

  it("edita o nome e salva os dados da escola (PATCH)", async () => {
    const u = userEvent.setup();
    carregarSucesso();
    responder("PATCH", URL_ESCOLA, { id: 1, nome: "Escola Renovada" });
    renderComApp(<Configuracoes />, { rota: "/configuracoes" });

    const nome = await screen.findByDisplayValue("Escola Modelo Constela");
    await u.clear(nome);
    await u.type(nome, "Escola Renovada");
    await u.click(screen.getByRole("button", { name: "Salvar dados da escola" }));

    expect(await screen.findByText("Dados da escola atualizados.")).toBeInTheDocument();
    expect(api).toHaveBeenCalledWith(
      URL_ESCOLA,
      expect.objectContaining({ method: "PATCH" }),
    );
  });

  it("salva os pesos do Ranking Geral (PUT)", async () => {
    const u = userEvent.setup();
    carregarSucesso();
    responder("PUT", URL_PESOS, { namespace: "geral", valores: { matific: 60, elefante: 40 }, soma: 100 });
    renderComApp(<Configuracoes />, { rota: "/configuracoes" });

    const botaoPesos = await screen.findByRole("button", { name: "Salvar pesos" });
    await u.click(botaoPesos);

    expect(
      await screen.findByText("Pesos salvos. Todas as notas foram recalculadas."),
    ).toBeInTheDocument();
  });

  it("mostra mensagem de falha quando salvar a escola erra", async () => {
    const u = userEvent.setup();
    carregarSucesso();
    responderErro("PATCH", URL_ESCOLA, 500, "Erro ao salvar no servidor");
    renderComApp(<Configuracoes />, { rota: "/configuracoes" });

    const nome = await screen.findByDisplayValue("Escola Modelo Constela");
    await u.clear(nome);
    await u.type(nome, "Nova");
    await u.click(screen.getByRole("button", { name: "Salvar dados da escola" }));

    expect(await screen.findByText("Erro ao salvar no servidor")).toBeInTheDocument();
  });

  it("mostra o erro quando os pesos não carregam", async () => {
    // Aparência ok; pesos falham -> PesosEditor renderiza a mensagem de erro.
    responder("GET", URL_APARENCIA, { cor_primaria: "#1B2A4A" });
    responderErro("GET", URL_PESOS, 500, "Falha ao carregar pesos");
    renderComApp(<Configuracoes />, { rota: "/configuracoes" });

    expect(await screen.findByText("Falha ao carregar pesos")).toBeInTheDocument();
  });
});
