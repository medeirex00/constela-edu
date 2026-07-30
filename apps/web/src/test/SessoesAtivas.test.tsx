import { describe, expect, it } from "vitest";

import SessoesAtivas from "../pages/SessoesAtivas";
import { renderComApp, responder, screen, userEvent } from "./utils";

const URL = "/presenca/sessoes";

function corpo(over: Record<string, unknown> = {}) {
  return {
    agora: "2026-07-30T18:00:00+00:00",
    limiar_online_seg: 90,
    total: 2,
    online: 1,
    sessoes: [
      {
        id: 1, nome: "Chefe Global", email: "global@constela.com",
        cargo: "admin", is_global: true, rede_id: null,
        escola_id: null, escola_nome: null, status: "ativo",
        online: true, visto_em: "2026-07-30T17:59:30+00:00",
        ultimo_acesso: "2026-07-30T12:00:00+00:00",
      },
      {
        id: 2, nome: "Professora Marta", email: "marta@escola.com",
        cargo: "professor", is_global: false, rede_id: null,
        escola_id: 1, escola_nome: "Escola Modelo", status: "ativo",
        online: false, visto_em: "2026-07-30T15:00:00+00:00",
        ultimo_acesso: "2026-07-30T15:00:00+00:00",
      },
    ],
    ...over,
  };
}

describe("SessoesAtivas (monitor de presença)", () => {
  it("lista usuários com status, papel e última atividade", async () => {
    responder("GET", URL, corpo());
    renderComApp(<SessoesAtivas />, { rota: "/sessoes" });

    expect(await screen.findByText("Chefe Global")).toBeInTheDocument();
    expect(screen.getByText("Professora Marta")).toBeInTheDocument();
    // Status de presença.
    expect(screen.getByText("Online")).toBeInTheDocument();
    expect(screen.getByText("Offline")).toBeInTheDocument();
    // Papel legível (aparece na coluna Cargo e no fallback mobile → getAll).
    expect(screen.getAllByText("Admin Global").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Professor").length).toBeGreaterThan(0);
    // Escola do usuário (join) e tempo relativo contra o relógio do servidor.
    expect(screen.getByText("Escola Modelo")).toBeInTheDocument();
    expect(screen.getByText("agora mesmo")).toBeInTheDocument();
    expect(screen.getByText("há 3 h")).toBeInTheDocument();
  });

  it("filtra por 'Apenas online'", async () => {
    responder("GET", URL, corpo());
    const u = userEvent.setup();
    renderComApp(<SessoesAtivas />, { rota: "/sessoes" });
    await screen.findByText("Professora Marta");

    await u.click(screen.getByRole("tab", { name: "Apenas online" }));

    expect(screen.getByText("Chefe Global")).toBeInTheDocument();
    expect(screen.queryByText("Professora Marta")).not.toBeInTheDocument();
  });

  it("busca por nome (sem acento)", async () => {
    responder("GET", URL, corpo());
    const u = userEvent.setup();
    renderComApp(<SessoesAtivas />, { rota: "/sessoes" });
    await screen.findByText("Chefe Global");

    await u.type(screen.getByLabelText("Buscar por nome"), "marta");

    expect(screen.getByText("Professora Marta")).toBeInTheDocument();
    expect(screen.queryByText("Chefe Global")).not.toBeInTheDocument();
  });
});
