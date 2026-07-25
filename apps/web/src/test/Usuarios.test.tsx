import { describe, expect, it } from "vitest";

import Usuarios from "../pages/Usuarios";
import {
  api,
  renderComApp,
  responder,
  responderErro,
  screen,
  turmaFake,
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

  // --- Vincular turmas ao professor ------------------------------------------

  const MARIA = usuarioFake({ id: 2, nome: "Maria Souza", email: "maria@escola.com", cargo: "professor" });

  /** Mocka a lista + os dois GET de turmas (default e ?todas=true, que casam o
   *  mesmo caminho no mock — por isso o matcher por função) + a atribuição. */
  function mocarModalTurmas(opts: {
    ativas: ReturnType<typeof turmaFake>[];
    todas?: ReturnType<typeof turmaFake>[];
    designadas: number[];
  }) {
    responder("GET", URL_LISTA, [MARIA]);
    responder(
      "GET",
      (c: string) => c.startsWith("/escolas/1/turmas"),
      (caminho: string) => (caminho.includes("todas=true") ? (opts.todas ?? opts.ativas) : opts.ativas),
    );
    responder("GET", "/escolas/1/usuarios/2/turmas", { turma_ids: opts.designadas });
  }

  async function abrirModalTurmas(u: ReturnType<typeof userEvent.setup>) {
    comoAdmin(<Usuarios />);
    await u.click(await screen.findByRole("button", { name: "Ações do usuário Maria Souza" }));
    await u.click(await screen.findByRole("menuitem", { name: "Vincular turmas" }));
  }

  it("não acusa transferência ao desmarcar a turma da própria professora, mas acusa a de outro", async () => {
    mocarModalTurmas({
      ativas: [
        turmaFake({ id: 10, nome: "4º Ano A", ano_escolar: "4º Ano", professor_id: 2, professor_nome: "Maria Souza" }),
        turmaFake({ id: 20, nome: "5º Ano B", ano_escolar: "5º Ano", professor_id: 7, professor_nome: "Bia Rocha" }),
      ],
      designadas: [10],
    });

    const u = userEvent.setup();
    await abrirModalTurmas(u);

    // Turma de OUTRA professora acusa a transferência; a dela mesma, não.
    expect(await screen.findByText(/hoje com Bia Rocha — marcar passa a turma para Maria Souza/)).toBeInTheDocument();
    expect(screen.queryByText(/hoje com Maria Souza/)).not.toBeInTheDocument();

    // Desmarcar a turma DELA não pode fazer surgir a dica auto-referente (o bug).
    await u.click(screen.getByRole("checkbox", { name: /4º Ano A/ }));
    expect(screen.queryByText(/hoje com Maria Souza/)).not.toBeInTheDocument();
  });

  it("mostra a turma arquivada/de outro ano que ela já tem, com etiqueta, e permite removê-la", async () => {
    mocarModalTurmas({
      ativas: [turmaFake({ id: 10, nome: "4º Ano A", ano_escolar: "4º Ano", professor_id: 2, professor_nome: "Maria Souza" })],
      // A 99 (2025, arquivada) só existe no ?todas=true — mas a professora ainda a titulariza.
      todas: [
        turmaFake({ id: 10, nome: "4º Ano A", ano_escolar: "4º Ano", professor_id: 2, professor_nome: "Maria Souza" }),
        turmaFake({ id: 99, nome: "3º Ano C", ano_escolar: "3º Ano", ano_letivo: 2025, status: "arquivada", professor_id: 2, professor_nome: "Maria Souza" }),
      ],
      designadas: [10, 99],
    });
    responder("PUT", "/escolas/1/usuarios/2/turmas", { mensagem: "1 turma(s) designada(s) a Maria Souza." });

    const u = userEvent.setup();
    await abrirModalTurmas(u);

    // A turma antiga aparece (não apareceria sem o ?todas=true) com a etiqueta do ano.
    const antiga = await screen.findByRole("checkbox", { name: /3º Ano C/ });
    expect(antiga).toBeInTheDocument();
    expect(screen.getByText(/2025 · arquivada/)).toBeInTheDocument();

    // Removê-la e salvar → o PUT vai SEM o id 99 (antes ele ficava preso, invisível).
    await u.click(antiga);
    await u.click(screen.getByRole("button", { name: /salvar turmas/i }));

    expect(await screen.findByText("1 turma(s) designada(s) a Maria Souza.")).toBeInTheDocument();
    expect(api).toHaveBeenCalledWith(
      "/escolas/1/usuarios/2/turmas",
      expect.objectContaining({ method: "PUT", body: JSON.stringify({ turma_ids: [10] }) }),
    );
  });

  it("vincula uma turma nova (PUT com o id marcado)", async () => {
    mocarModalTurmas({
      ativas: [turmaFake({ id: 30, nome: "2º Ano D", ano_escolar: "2º Ano", professor_id: null, professor_nome: null })],
      designadas: [],
    });
    responder("PUT", "/escolas/1/usuarios/2/turmas", { mensagem: "1 turma(s) designada(s) a Maria Souza." });

    const u = userEvent.setup();
    await abrirModalTurmas(u);

    await u.click(await screen.findByRole("checkbox", { name: /2º Ano D/ }));
    await u.click(screen.getByRole("button", { name: /salvar turmas/i }));

    expect(await screen.findByText("1 turma(s) designada(s) a Maria Souza.")).toBeInTheDocument();
    expect(api).toHaveBeenCalledWith(
      "/escolas/1/usuarios/2/turmas",
      expect.objectContaining({ method: "PUT", body: JSON.stringify({ turma_ids: [30] }) }),
    );
  });
});
