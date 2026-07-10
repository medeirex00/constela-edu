import { describe, expect, it } from "vitest";
import { MemoryRouter } from "react-router-dom";

import Escolas from "../pages/Escolas";
import { AppProvider } from "../context/AppContext";
import {
  autenticar,
  escolaFake,
  render,
  renderComApp,
  responder,
  responderErro,
  screen,
  userEvent,
  usuarioFake,
} from "./utils";

// A tela é exclusiva do administrador GLOBAL da rede.
const ADMIN = usuarioFake({ is_global: true });

describe("Escolas", () => {
  it("lista as escolas da rede, incluindo as inativas", async () => {
    const escolas = [
      escolaFake({ id: 1, nome: "Escola Alpha", status: "ativa" }),
      escolaFake({ id: 2, nome: "Escola Beta", status: "inativa" }),
    ];
    renderComApp(<Escolas />, { rota: "/escolas", usuario: ADMIN, escolas });

    expect(await screen.findByText("Escola Alpha")).toBeInTheDocument();
    expect(screen.getByText("Escola Beta")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Escolas" })).toBeInTheDocument();
  });

  it("mostra estado vazio quando não há escolas cadastradas", async () => {
    renderComApp(<Escolas />, { rota: "/escolas", usuario: ADMIN, escolas: [] });

    expect(await screen.findByText("Nenhuma escola")).toBeInTheDocument();
    expect(screen.getByText("Crie a primeira escola da rede.")).toBeInTheDocument();
  });

  it("cadastra uma nova escola (POST) e confirma a criação", async () => {
    const u = userEvent.setup();
    responder("POST", "/escolas", escolaFake({ id: 9, nome: "Escola Nova Teste" }));
    renderComApp(<Escolas />, {
      rota: "/escolas",
      usuario: ADMIN,
      escolas: [escolaFake({ id: 1, nome: "Escola Alpha" })],
    });

    // Espera a lista carregar antes de interagir.
    await screen.findByText("Escola Alpha");

    await u.click(screen.getByRole("button", { name: /nova escola/i }));
    await u.type(screen.getByLabelText("Nome da escola"), "Escola Nova Teste");
    await u.click(screen.getByRole("button", { name: "Criar escola" }));

    // Mensagem de sucesso: `Escola “...” criada.` (aspas tipográficas — casa por regex).
    expect(await screen.findByText(/criada\./)).toBeInTheDocument();
  });

  it("mostra falha quando a listagem da API erra", async () => {
    // A sessão (GET /escolas) precisa funcionar para o usuário global carregar;
    // só a listagem da tela (GET /escolas?incluir_inativas=true) falha.
    autenticar(ADMIN, [escolaFake({ id: 1, nome: "Escola Alpha" })]);
    responderErro("GET", /incluir_inativas/, 500, "Erro interno");
    render(
      <MemoryRouter initialEntries={["/escolas"]}>
        <AppProvider>
          <Escolas />
        </AppProvider>
      </MemoryRouter>,
    );

    expect(
      await screen.findByText("Não foi possível carregar as escolas"),
    ).toBeInTheDocument();
  });
});
