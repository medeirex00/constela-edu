import { describe, expect, it } from "vitest";

import Login from "../pages/Login";
import {
  ApiError,
  escolaFake,
  loginRequest,
  renderComApp,
  responder,
  responderErro,
  screen,
  userEvent,
  usuarioFake,
  waitFor,
} from "./utils";

describe("Login", () => {
  it("envia as credenciais digitadas para a API de login", async () => {
    // Após o token, o AppContext busca a sessão — respondemos para não falhar.
    responder("GET", "/auth/me", usuarioFake());
    responder("GET", "/escolas", [escolaFake()]);
    renderComApp(<Login />, { autenticado: false });
    const u = userEvent.setup();

    await u.type(await screen.findByLabelText(/mail ou nome de usu/i), "ana@escola.com");
    await u.type(screen.getByLabelText("Senha"), "segredo123");
    await u.click(screen.getByRole("button", { name: /entrar/i }));

    await waitFor(() =>
      expect(loginRequest).toHaveBeenCalledWith("ana@escola.com", "segredo123"),
    );
  });

  it("exibe a mensagem de erro quando as credenciais são inválidas", async () => {
    loginRequest.mockRejectedValueOnce(new ApiError(401, "E-mail ou senha inválidos."));
    renderComApp(<Login />, { autenticado: false });
    const u = userEvent.setup();

    await u.type(await screen.findByLabelText(/mail ou nome de usu/i), "x@x.com");
    await u.type(screen.getByLabelText("Senha"), "errado");
    await u.click(screen.getByRole("button", { name: /entrar/i }));

    expect(await screen.findByText("E-mail ou senha inválidos.")).toBeInTheDocument();
    // A senha continua na tela (não navegou para dentro do sistema).
    expect(screen.getByLabelText("Senha")).toBeInTheDocument();
  });

  it("mostra 'Entrando...' e desabilita o botão durante o envio", async () => {
    let liberar!: () => void;
    loginRequest.mockImplementationOnce(
      () => new Promise((resolve) => {
        liberar = () => resolve({ access_token: "t", token_type: "bearer" });
      }),
    );
    responderErro("GET", "/auth/me", 401); // irrelevante: seguramos no login
    renderComApp(<Login />, { autenticado: false });
    const u = userEvent.setup();

    await u.type(await screen.findByLabelText(/mail ou nome de usu/i), "ana@escola.com");
    await u.type(screen.getByLabelText("Senha"), "segredo123");
    await u.click(screen.getByRole("button", { name: /entrar/i }));

    const botao = await screen.findByRole("button", { name: /entrando/i });
    expect(botao).toBeDisabled();
    liberar();
  });
});
