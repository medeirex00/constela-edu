import { describe, expect, it } from "vitest";

import Usuarios from "../pages/Usuarios";
import {
  api,
  renderComApp,
  responder,
  responderErro,
  screen,
  userEvent,
  usuarioFake,
} from "./utils";

const URL_LISTA = "/escolas/1/usuarios";

/** Loga como administrador — é o cargo que libera "Novo usuário", o menu de
 *  ações de gestão e o filtro de excluídos na tela. */
const ADMIN = usuarioFake({ id: 1, nome: "Admin Geral", email: "admin@escola.com", cargo: "admin" });

function comoAdmin(ui: React.ReactElement) {
  return renderComApp(ui, { rota: "/usuarios", usuario: ADMIN });
}

describe("Usuarios", () => {
  it("lista os usuários da escola com nome e cargo", async () => {
    responder("GET", URL_LISTA, [
      usuarioFake({ id: 2, nome: "Maria Souza", email: "maria@escola.com", cargo: "professor", username: "maria.souza" }),
      usuarioFake({ id: 3, nome: "Carlos Lima", email: "carlos@escola.com", cargo: "coordenador", username: null }),
    ]);

    comoAdmin(<Usuarios />);

    expect(await screen.findByText("Maria Souza")).toBeInTheDocument();
    expect(screen.getByText("Carlos Lima")).toBeInTheDocument();
    // Cargos legíveis (rotuloCargo) viram badges na tabela.
    expect(screen.getByText("Professor")).toBeInTheDocument();
    expect(screen.getByText("Coordenador")).toBeInTheDocument();
    // Ação de gestão disponível para admin.
    expect(screen.getByRole("button", { name: /novo usuário/i })).toBeInTheDocument();
  });

  it("mostra estado vazio quando não há usuários", async () => {
    responder("GET", URL_LISTA, []);

    comoAdmin(<Usuarios />);

    expect(await screen.findByText("Sem acesso ou nenhum usuário")).toBeInTheDocument();
  });

  it("mostra a falha quando a API erra", async () => {
    responderErro("GET", URL_LISTA, 500, "Falha no servidor");

    comoAdmin(<Usuarios />);

    // A tela cai no bloco Vazio e mostra a mensagem do erro como descrição.
    expect(await screen.findByText("Falha no servidor")).toBeInTheDocument();
    expect(screen.getByText("Sem acesso ou nenhum usuário")).toBeInTheDocument();
  });

  it("cria um usuário pelo modal (POST) e mostra a confirmação", async () => {
    responder("GET", URL_LISTA, [
      usuarioFake({ id: 2, nome: "Maria Souza", email: "maria@escola.com", cargo: "professor" }),
    ]);
    responder("POST", URL_LISTA, {});

    const u = userEvent.setup();
    comoAdmin(<Usuarios />);

    await u.click(await screen.findByRole("button", { name: /novo usuário/i }));

    // Modal aberto: preenche os campos mínimos para habilitar o botão.
    await u.type(screen.getByLabelText("Nome"), "Novo Professor");
    await u.type(screen.getByLabelText("E-mail"), "novo@escola.com");
    await u.type(screen.getByLabelText(/Senha/), "senha1234");

    await u.click(screen.getByRole("button", { name: /criar usuário/i }));

    expect(await screen.findByText("Usuário criado.")).toBeInTheDocument();
    expect(api).toHaveBeenCalledWith(URL_LISTA, expect.objectContaining({ method: "POST" }));
  });

  it("desativa um usuário pelo menu de ações (PATCH)", async () => {
    responder("GET", URL_LISTA, [
      usuarioFake({ id: 2, nome: "Maria Souza", email: "maria@escola.com", cargo: "professor", status: "ativo" }),
    ]);
    responder("PATCH", "/escolas/1/usuarios/2", {});

    const u = userEvent.setup();
    comoAdmin(<Usuarios />);

    await u.click(await screen.findByRole("button", { name: "Ações do usuário Maria Souza" }));
    await u.click(await screen.findByRole("menuitem", { name: "Desativar" }));

    // Modal de confirmação.
    await u.click(await screen.findByRole("button", { name: "Confirmar" }));

    expect(await screen.findByText("Usuário desativado.")).toBeInTheDocument();
    expect(api).toHaveBeenCalledWith(
      "/escolas/1/usuarios/2",
      expect.objectContaining({ method: "PATCH" }),
    );
  });
});
