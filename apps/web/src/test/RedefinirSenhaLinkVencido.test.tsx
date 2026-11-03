/** Link de redefinição vencido: o texto não manda a Secretaria "pedir à escola" (a conta
 *  dela só recebe link do Administrador Global; a escola não tem acesso a ela). */
import { describe, expect, it } from "vitest";

import RedefinirSenha from "../pages/RedefinirSenha";
import { renderComApp, responder, screen } from "./utils";

describe("Redefinir senha — link vencido", () => {
  it("diz a quem pedir um novo link conforme a conta (escola ou Secretaria)", async () => {
    responder("GET", "/auth/redefinir-senha/abc123", { valido: false });
    renderComApp(<RedefinirSenha />, { rota: "/redefinir-senha?token=abc123", autenticado: false });

    const aviso = await screen.findByText(/Este link é inválido ou expirou/);
    expect(aviso).toHaveTextContent("quem administra a sua conta");
    expect(aviso).toHaveTextContent("na Secretaria, o Administrador Global da plataforma");
    expect(screen.queryByText("Link de uso único, enviado pela escola.")).not.toBeInTheDocument();
  });
});
