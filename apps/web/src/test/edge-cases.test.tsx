/**
 * Casos de borda que protegem contra regressões nos fluxos já cobertos:
 *   - Permissões (RBAC negativo): o papel MENOS privilegiado NÃO vê ações
 *     administrativas — o teste "feliz" usa o papel permissivo, então sem isto
 *     um vazamento de permissão passaria despercebido.
 *   - Entradas inválidas: a validação client-side (botão desabilitado até o
 *     formulário ficar válido) é fácil de quebrar numa refatoração.
 *   - Respostas incompletas/inesperadas da API: campos opcionais nulos e listas
 *     nulas não podem derrubar a tela.
 */
import { describe, expect, it } from "vitest";

import Escolas from "../pages/Escolas";
import Matific from "../pages/Matific";
import RankingGeral from "../pages/RankingGeral";
import Usuarios from "../pages/Usuarios";
import {
  rankingItemFake,
  renderComApp,
  responder,
  screen,
  userEvent,
  usuarioFake,
} from "./utils";

// --- Permissões (RBAC negativo) ----------------------------------------------

describe("Permissões — o papel restrito não vê ações administrativas", () => {
  it("Usuários: um professor não vê 'Novo usuário' (só admin/global cria)", async () => {
    responder("GET", "/escolas/1/usuarios", [
      usuarioFake({ id: 2, nome: "Maria Souza", cargo: "professor" }),
    ]);
    renderComApp(<Usuarios />, {
      rota: "/usuarios",
      usuario: usuarioFake({ cargo: "professor", is_global: false }),
    });

    // A tela carrega e mostra a lista...
    expect(await screen.findByText("Maria Souza")).toBeInTheDocument();
    // ...mas a ação administrativa NÃO aparece para o professor.
    expect(screen.queryByRole("button", { name: /novo usuário/i })).not.toBeInTheDocument();
    expect(screen.queryByText("Mostrar usuários excluídos")).not.toBeInTheDocument();
  });

  it("Matific: um professor vê os dados mas não os botões de edição", async () => {
    responder("GET", "/escolas/1/matific", [
      {
        aluno_id: 10, nome: "Ana Beatriz Souza", turma: "3º Ano A", ano_escolar: "3º Ano",
        atividades: 42, estrelas: 120, pontuacao_media: 85, data_referencia: null,
      },
    ]);
    renderComApp(<Matific />, {
      rota: "/matific",
      usuario: usuarioFake({ cargo: "professor", is_global: false }),
    });

    expect(await screen.findByRole("link", { name: "Ana Beatriz Souza" })).toBeInTheDocument();
    // Edição é privilégio de admin/coordenador/global — o professor não a vê.
    expect(
      screen.queryByRole("button", { name: "Editar dados de Ana Beatriz Souza" }),
    ).not.toBeInTheDocument();
  });

  it("Escolas: um usuário não-global é bloqueado da gestão da rede", async () => {
    renderComApp(<Escolas />, {
      rota: "/escolas",
      usuario: usuarioFake({ cargo: "admin", is_global: false }),
    });

    expect(await screen.findByText("Somente o administrador global")).toBeInTheDocument();
    // Sem botão de cadastrar escola para quem não é global.
    expect(screen.queryByRole("button", { name: /nova escola/i })).not.toBeInTheDocument();
  });
});

// --- Entradas inválidas (validação de formulário) ----------------------------

describe("Entradas inválidas — o cadastro só habilita com dados válidos", () => {
  it("Usuários: 'Criar usuário' fica desabilitado com e-mail/senha inválidos", async () => {
    responder("GET", "/escolas/1/usuarios", []);
    const u = userEvent.setup();
    renderComApp(<Usuarios />, {
      rota: "/usuarios",
      usuario: usuarioFake({ cargo: "admin" }),
    });

    await u.click(await screen.findByRole("button", { name: /novo usuário/i }));
    const criar = screen.getByRole("button", { name: /criar usuário/i });

    // Vazio → desabilitado.
    expect(criar).toBeDisabled();

    // Nome ok, mas e-mail sem "@" e senha curta → ainda desabilitado.
    await u.type(screen.getByLabelText("Nome"), "Novo Professor");
    await u.type(screen.getByLabelText("E-mail"), "email-invalido");
    await u.type(screen.getByLabelText(/senha/i), "curta");
    expect(criar).toBeDisabled();

    // Corrige e-mail e senha (>= 8) → habilita.
    await u.clear(screen.getByLabelText("E-mail"));
    await u.type(screen.getByLabelText("E-mail"), "novo@escola.com");
    await u.clear(screen.getByLabelText(/senha/i));
    await u.type(screen.getByLabelText(/senha/i), "senha1234");
    expect(criar).toBeEnabled();
  });
});

// --- Respostas incompletas / inesperadas da API ------------------------------

describe("Respostas incompletas da API — a tela não pode quebrar", () => {
  it("Ranking: renderiza alunos com turma nula sem estourar", async () => {
    responder("GET", "/escolas/1/turmas", []);
    responder("GET", "/escolas/1/ranking", [
      rankingItemFake({ posicao: 1, aluno_id: 7, nome: "Aluno Sem Turma", turma: null, ano_escolar: null }),
    ]);
    renderComApp(<RankingGeral />, { rota: "/ranking" });

    // O nome aparece como link mesmo sem turma (célula de turma fica vazia).
    expect(await screen.findByRole("link", { name: "Aluno Sem Turma" })).toBeInTheDocument();
  });

  it("Ranking: uma lista nula da API cai no estado vazio, não em erro", async () => {
    responder("GET", "/escolas/1/turmas", []);
    responder("GET", "/escolas/1/ranking", null);
    renderComApp(<RankingGeral />, { rota: "/ranking" });

    expect(await screen.findByText("Nenhuma nota calculada ainda")).toBeInTheDocument();
  });
});
