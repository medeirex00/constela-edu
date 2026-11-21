import { afterEach, describe, expect, it, vi } from "vitest";

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
  afterEach(() => vi.restoreAllMocks());

  it("o exemplo do campo de usuário é curto no celular (não sai cortado) e inteiro no desktop", async () => {
    // Desktop (o matchMedia do jsdom responde "não" a tudo): o exemplo de sempre.
    const { unmount } = renderComApp(<Login />, { autenticado: false });
    const campo = await screen.findByLabelText(/mail ou nome de usu/i);
    expect(campo).toHaveAttribute("placeholder", "voce@escola.com ou @seu.usuario");
    unmount();

    // Celular (< 640 px): o mesmo campo, com o exemplo curto.
    const original = window.matchMedia;
    vi.spyOn(window, "matchMedia").mockImplementation((consulta: string) => ({
      ...original(consulta),
      matches: consulta === "(max-width: 639.98px)",
    }));
    renderComApp(<Login />, { autenticado: false });
    const noCelular = await screen.findByLabelText(/mail ou nome de usu/i);
    expect(noCelular).toHaveAttribute("placeholder", "e-mail ou @usuario");
    expect(screen.getAllByLabelText(/mail ou nome de usu/i)).toHaveLength(1);
  });

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

  it("exibe a orientação de recuperação vinda da API", async () => {
    const mensagem = "Não foi possível entrar. Confira o e-mail ou usuário e a senha. " +
      "Se precisar, peça um link de redefinição à administração.";
    loginRequest.mockRejectedValueOnce(new ApiError(401, mensagem));
    renderComApp(<Login />, { autenticado: false });
    const u = userEvent.setup();

    await u.type(await screen.findByLabelText(/mail ou nome de usu/i), "x@x.com");
    await u.type(screen.getByLabelText("Senha"), "errado");
    await u.click(screen.getByRole("button", { name: /entrar/i }));

    expect(await screen.findByText(mensagem)).toBeInTheDocument();
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

  it("as estrelas do painel param em prefers-reduced-motion (o ! vence o CSS plano de index.css)", async () => {
    // A cintilação vem da classe .painel-estrela, definida FORA de @layer e sem
    // reduced-motion de propósito (o telão mantém o céu vivo — D10). Na tela de
    // entrada, que é de uso, a utilitária com ! a desliga.
    renderComApp(<Login />, { autenticado: false });
    await screen.findByLabelText(/mail ou nome de usu/i);
    const estrelas = Array.from(document.querySelectorAll(".painel-estrela"));
    expect(estrelas.length).toBeGreaterThan(0);
    for (const estrela of estrelas) expect(estrela).toHaveClass("motion-reduce:!animate-none");
  });
});
