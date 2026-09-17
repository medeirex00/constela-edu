import { describe, expect, it } from "vitest";

import Comecar from "../pages/Comecar";
import Escolas from "../pages/Escolas";
import VisaoEscola from "../pages/VisaoEscola";
import {
  api,
  escolaFake,
  renderComApp,
  responder,
  screen,
  userEvent,
  usuarioFake,
  within,
} from "./utils";

// P8 — Escola → Usuários pelo DETALHE da escola, antes da Lista Piloto.
//
// O Admin Global abre uma escola por duas páginas dela: "Comece aqui" (a única
// que o menu oferece enquanto a escola não tem turmas) e "Visão da Escola". Nas
// duas tem de existir o caminho para cadastrar o primeiro coordenador, sem
// depender de turmas, alunos, Lista Piloto ou integrações. A conta nasce na
// escola SELECIONADA — a mesma cujo detalhe está aberto.

const GLOBAL = usuarioFake({ is_global: true, cargo: "admin", escola_id: null });
const COORDENADOR = usuarioFake({ is_global: false, cargo: "coordenador", escola_id: 2 });
const PROFESSOR = usuarioFake({ is_global: false, cargo: "professor", escola_id: 2 });
const ALPHA = escolaFake({ id: 1, nome: "Escola Alpha" });
const NOVA = escolaFake({ id: 2, nome: "Escola Nova" });

/** Escola recém-criada: nada acadêmico, nenhuma integração. */
const STATUS_VAZIA = {
  escola_id: 2, escola_nome: "Escola Nova", qtd_alunos: 0, qtd_turmas: 0,
  plataformas: [], lista_piloto_importada: false, integracao_configurada: false,
};
const RESUMO_VAZIO = { escola: { id: 2, nome: "Escola Nova" }, turmas: [] };

/** GET/POST de /escolas/2/usuarios com a lista em memória. */
function apiDeUsuarios() {
  const lista: ReturnType<typeof usuarioFake>[] = [];
  responder("GET", "/escolas/2/usuarios", () => [...lista]);
  responder("POST", "/escolas/2/usuarios", (_caminho, opcoes) => {
    const corpo = JSON.parse(String((opcoes as RequestInit).body));
    const criado = usuarioFake({
      id: 70, nome: corpo.nome, email: corpo.email, cargo: corpo.cargo,
      escola_id: 2, is_global: false,
    });
    lista.push(criado);
    return criado;
  });
}

async function adicionarCoordenador(u: ReturnType<typeof userEvent.setup>) {
  await u.click(await screen.findByRole("button", { name: "Usuários" }));
  expect(await screen.findByRole("heading", { name: "Usuários de Escola Nova" })).toBeInTheDocument();
  expect(await screen.findByText("Esta escola ainda não possui usuários.")).toBeInTheDocument();

  await u.click(screen.getByRole("button", { name: "+ Adicionar usuário" }));
  await u.type(screen.getByLabelText("Nome"), "Coordenadora Nova");
  await u.type(screen.getByLabelText("E-mail"), "coord@nova.escola.br");
  await u.type(screen.getByLabelText(/Senha inicial/), "Constela#Forte2026");
  expect(screen.getByLabelText("Cargo")).toHaveValue("coordenador");
  await u.click(screen.getByRole("button", { name: "Criar usuário" }));

  expect(await screen.findByText(/criado como coordenador em Escola Nova/)).toBeInTheDocument();
  const post = api.mock.calls.find(
    ([caminho, opcoes]) => caminho === "/escolas/2/usuarios" && (opcoes as RequestInit)?.method === "POST",
  );
  expect(post).toBeDefined();
  const corpo = JSON.parse(String((post![1] as RequestInit).body));
  expect(corpo).toMatchObject({ nome: "Coordenadora Nova", email: "coord@nova.escola.br", cargo: "coordenador" });
  expect(corpo).not.toHaveProperty("escola_id");
  expect(corpo).not.toHaveProperty("is_global");
  expect(await screen.findByText("Coordenadora Nova")).toBeInTheDocument();
}

describe("Escola → Usuários pelo detalhe da escola (Admin Global, antes da Lista Piloto)", () => {
  it("Comece aqui de uma escola SEM Lista Piloto, turmas, alunos ou integrações: Usuários → adicionar coordenador", async () => {
    const u = userEvent.setup();
    responder("GET", "/escolas/2/sync/status", STATUS_VAZIA);
    apiDeUsuarios();
    renderComApp(<Comecar />, { rota: "/comecar", usuario: GLOBAL, escolas: [ALPHA, NOVA], escolaSelecionada: 2 });
    expect(await screen.findByText(/0 turma\(s\) · 0 aluno\(s\)/)).toBeInTheDocument();

    await adicionarCoordenador(u);

    // A conta foi para a escola aberta (2), nunca para outra.
    expect(api).not.toHaveBeenCalledWith("/escolas/1/usuarios", expect.objectContaining({ method: "POST" }));
  });

  it("Visão da Escola de uma escola sem turmas: Usuários → adicionar coordenador", async () => {
    const u = userEvent.setup();
    responder("GET", "/escolas/2/resumo-escola", RESUMO_VAZIO);
    apiDeUsuarios();
    renderComApp(<VisaoEscola />, { rota: "/escola", usuario: GLOBAL, escolas: [ALPHA, NOVA], escolaSelecionada: 2 });
    expect(await screen.findByText("Nenhuma turma no ano letivo ativo")).toBeInTheDocument();

    await adicionarCoordenador(u);

    // O caminho não depende do estado de onboarding da escola.
    expect(api.mock.calls.some(([caminho]) => String(caminho).includes("/sync/status"))).toBe(false);
  });

  it.each([
    ["coordenador", COORDENADOR],
    ["professor", PROFESSOR],
  ])("%s da escola NÃO ganha a gestão de usuários no detalhe da escola", async (_cargo, usuario) => {
    responder("GET", "/escolas/2/sync/status", STATUS_VAZIA);
    responder("GET", "/escolas/2/resumo-escola", RESUMO_VAZIO);
    const { unmount } = renderComApp(<VisaoEscola />, { rota: "/escola", usuario, escolas: [NOVA] });
    expect(await screen.findByText("Nenhuma turma no ano letivo ativo")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Usuários" })).toBeNull();
    unmount();

    renderComApp(<Comecar />, { rota: "/comecar", usuario, escolas: [NOVA] });
    await screen.findByText(/Em poucos passos|Somente administradores/);
    expect(screen.queryByRole("button", { name: "Usuários" })).toBeNull();
    expect(api.mock.calls.some(([caminho]) => String(caminho).includes("/usuarios"))).toBe(false);
  });

  it("na lista de Escolas, o acesso a Usuários de cada escola é visível (texto, não só ícone)", async () => {
    renderComApp(<Escolas />, { rota: "/escolas", usuario: GLOBAL, escolas: [ALPHA, NOVA] });
    const linha = (await screen.findByText("Escola Nova")).closest("tr") as HTMLElement;
    const botao = within(linha).getByRole("button", { name: "Usuários de Escola Nova" });
    expect(botao).toHaveTextContent("Usuários");
  });
});
