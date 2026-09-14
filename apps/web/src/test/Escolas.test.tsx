import { describe, expect, it } from "vitest";
import { MemoryRouter } from "react-router-dom";

import Escolas from "../pages/Escolas";
import { AppProvider } from "../context/AppContext";
import {
  api,
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
    responder("GET", "/escolas/9/usuarios", []);   // a seção Usuários da escola nova abre em seguida
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

  // --- P8: usuários da escola ANTES da Lista Piloto ---------------------------

  const ALPHA = escolaFake({ id: 1, nome: "Escola Alpha" });
  const NOVA = escolaFake({ id: 2, nome: "Escola Nova" });

  it("abre a seção Usuários de uma escola vazia (0 turmas, 0 alunos, sem Lista Piloto) com o estado vazio e o botão de adicionar", async () => {
    const u = userEvent.setup();
    // Nenhum handler de /sync/status ou /dashboard: se a seção dependesse do
    // estado de onboarding (turmas/alunos/Lista Piloto), a chamada cairia no
    // 404 do mock e o estado vazio abaixo não apareceria.
    responder("GET", "/escolas/2/usuarios", []);
    renderComApp(<Escolas />, { rota: "/escolas", usuario: ADMIN, escolas: [ALPHA, NOVA] });
    await screen.findByText("Escola Nova");

    await u.click(screen.getByRole("button", { name: "Usuários de Escola Nova" }));

    expect(await screen.findByRole("heading", { name: "Usuários de Escola Nova" })).toBeInTheDocument();
    expect(await screen.findByText("Esta escola ainda não possui usuários.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "+ Adicionar usuário" })).toBeInTheDocument();
    // A lista veio da escola ABERTA (id 2), não da escola do seletor do topo (id 1)…
    expect(api.mock.calls.some(([caminho]) => caminho === "/escolas/2/usuarios")).toBe(true);
    expect(api.mock.calls.some(([caminho]) => String(caminho).startsWith("/escolas/1/usuarios"))).toBe(false);
    // …e a seção não perguntou ao onboarding se a escola "está pronta".
    expect(api.mock.calls.some(([caminho]) => String(caminho).includes("/sync/status"))).toBe(false);
    expect(api.mock.calls.some(([caminho]) => String(caminho).includes("/dashboard"))).toBe(false);
  });

  it("cria um coordenador para a escola ABERTA (POST /escolas/{id}/usuarios), não para a escola do seletor do topo", async () => {
    const u = userEvent.setup();
    const lista: ReturnType<typeof usuarioFake>[] = [];
    responder("GET", "/escolas/2/usuarios", () => [...lista]);
    responder("POST", "/escolas/2/usuarios", (_caminho, opcoes) => {
      const corpo = JSON.parse(String((opcoes as RequestInit).body));
      const criado = usuarioFake({
        id: 7, nome: corpo.nome, email: corpo.email, cargo: corpo.cargo,
        username: corpo.username, escola_id: 2, is_global: false,
      });
      lista.push(criado);
      return criado;
    });
    // O seletor do topo está na escola 1 (sgpe_escola = 1ª da lista): a conta
    // tem de ir para a escola 2, a que foi aberta na tela.
    renderComApp(<Escolas />, { rota: "/escolas", usuario: ADMIN, escolas: [ALPHA, NOVA] });
    await screen.findByText("Escola Nova");
    await u.click(screen.getByRole("button", { name: "Usuários de Escola Nova" }));
    await screen.findByText("Esta escola ainda não possui usuários.");

    await u.click(screen.getByRole("button", { name: "+ Adicionar usuário" }));
    await u.type(screen.getByLabelText("Nome"), "Coordenadora Nova");
    await u.type(screen.getByLabelText("E-mail"), "coord@nova.escola.br");
    await u.type(screen.getByLabelText(/Senha inicial/), "Constela#Forte2026");
    // Cargo padrão da seção = Coordenador (o 1º acesso de uma escola).
    expect(screen.getByLabelText("Cargo")).toHaveValue("coordenador");
    await u.click(screen.getByRole("button", { name: "Criar usuário" }));

    expect(await screen.findByText(/criado como coordenador em Escola Nova/)).toBeInTheDocument();
    const chamadaPost = api.mock.calls.find(
      ([caminho, opcoes]) => caminho === "/escolas/2/usuarios" && (opcoes as RequestInit)?.method === "POST",
    );
    expect(chamadaPost).toBeDefined();
    const corpo = JSON.parse(String((chamadaPost![1] as RequestInit).body));
    expect(corpo).toMatchObject({ nome: "Coordenadora Nova", email: "coord@nova.escola.br", cargo: "coordenador" });
    expect(corpo).not.toHaveProperty("is_global");
    expect(corpo).not.toHaveProperty("escola_id");
    expect(api).not.toHaveBeenCalledWith("/escolas/1/usuarios", expect.objectContaining({ method: "POST" }));

    // A lista da seção mostra nome, e-mail, cargo, situação e a ação do global.
    expect(await screen.findByText("Coordenadora Nova")).toBeInTheDocument();
    expect(screen.getByText("coord@nova.escola.br")).toBeInTheDocument();
    expect(screen.getByText("Coordenador")).toBeInTheDocument();
    expect(screen.getByText("ativo")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Desativar Coordenadora Nova" })).toBeInTheDocument();
  });

  it("erro do backend ao criar (e-mail duplicado) fica visível no modal, sem confirmação falsa", async () => {
    const u = userEvent.setup();
    responder("GET", "/escolas/2/usuarios", [
      usuarioFake({ id: 3, nome: "Root Global", email: "root@constela.local", cargo: "admin", is_global: true, escola_id: 2 }),
    ]);
    responderErro("POST", "/escolas/2/usuarios", 409, "Já existe um usuário com este e-mail.");
    renderComApp(<Escolas />, { rota: "/escolas", usuario: ADMIN, escolas: [ALPHA, NOVA] });
    await screen.findByText("Escola Nova");
    await u.click(screen.getByRole("button", { name: "Usuários de Escola Nova" }));
    // conta global listada SEM ação de desativar (ações conforme permissão)
    expect(await screen.findByText("Root Global")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Desativar Root Global/ })).toBeNull();

    await u.click(screen.getByRole("button", { name: "+ Adicionar usuário" }));
    await u.type(screen.getByLabelText("Nome"), "Coordenadora Nova");
    await u.type(screen.getByLabelText("E-mail"), "coord@nova.escola.br");
    await u.type(screen.getByLabelText(/Senha inicial/), "Constela#Forte2026");
    await u.click(screen.getByRole("button", { name: "Criar usuário" }));

    expect(await screen.findByText("Já existe um usuário com este e-mail.")).toBeInTheDocument();
    expect(screen.queryByText(/criado como/)).toBeNull();
    // o modal continua aberto para corrigir
    expect(screen.getByRole("button", { name: "Criar usuário" })).toBeInTheDocument();
  });

  it("depois de cadastrar uma escola, já abre a seção Usuários dela (criar escola → criar coordenador)", async () => {
    const u = userEvent.setup();
    responder("POST", "/escolas", escolaFake({ id: 9, nome: "Escola Nova Teste" }));
    responder("GET", "/escolas/9/usuarios", []);
    renderComApp(<Escolas />, { rota: "/escolas", usuario: ADMIN, escolas: [ALPHA] });
    await screen.findByText("Escola Alpha");

    await u.click(screen.getByRole("button", { name: /nova escola/i }));
    await u.type(screen.getByLabelText("Nome da escola"), "Escola Nova Teste");
    await u.click(screen.getByRole("button", { name: "Criar escola" }));

    expect(await screen.findByRole("heading", { name: "Usuários de Escola Nova Teste" })).toBeInTheDocument();
    expect(await screen.findByText("Esta escola ainda não possui usuários.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "+ Adicionar usuário" })).toBeInTheDocument();
  });
});
