import { describe, expect, it } from "vitest";

import Elefante from "../pages/Elefante";
import {
  api,
  renderComApp,
  responder,
  responderErro,
  screen,
  userEvent,
  usuarioFake,
  waitFor,
} from "./utils";

const URL_ELEFANTE = "/escolas/1/elefante";
const URL_DIFICULDADE = "/escolas/1/configuracoes/dificuldade";

function alunoFake(over = {}) {
  return {
    aluno_id: 5,
    nome: "Ana Beatriz Souza",
    turma: "3º Ano A",
    ano_escolar: "3º Ano",
    livros_unicos: 12,
    tempo_leitura_min: 90,
    questoes_tentativas: 20,
    questoes_acertos: 15,
    livros_por_nivel: { AA: 2, D: 1 },
    data_referencia: "2026-06-01T10:00:00Z",
    ...over,
  };
}

function niveisFake() {
  return {
    niveis: [
      { id: 1, nome: "Vermelho", codigo: "AA", codigos: ["AA"], pontos_padrao: 1, ordem: 1 },
      { id: 2, nome: "Azul", codigo: "D", codigos: ["D"], pontos_padrao: 2, ordem: 2 },
    ],
  };
}

describe("Elefante", () => {
  it("carrega e mostra os alunos do Elefante Letrado", async () => {
    responder("GET", URL_ELEFANTE, [
      alunoFake(),
      alunoFake({ aluno_id: 6, nome: "João Pedro Barbosa", livros_unicos: 7 }),
    ]);
    responder("GET", URL_DIFICULDADE, niveisFake());
    renderComApp(<Elefante />, { rota: "/elefante" });

    // Título da página e cabeçalho da tabela.
    expect(await screen.findByText("Elefante Letrado")).toBeInTheDocument();
    expect(screen.getByText("Aluno")).toBeInTheDocument();

    // Alunos viram links para a ficha individual.
    expect(
      await screen.findByRole("link", { name: "Ana Beatriz Souza" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "João Pedro Barbosa" })).toBeInTheDocument();

    // Livros únicos como inteiro.
    expect(screen.getByText("12")).toBeInTheDocument();
    expect(screen.getByText("7")).toBeInTheDocument();
  });

  it("coordenadora não vê as sub-abas de configuração da dificuldade", async () => {
    // A escola usa o Constela e não administra a régua: "Níveis de dificuldade"
    // e "Dificuldade por turma" são exclusivas do Admin Global. Com só "Alunos"
    // restando, a barra de sub-abas some e a lista é o conteúdo da página.
    responder("GET", URL_ELEFANTE, [alunoFake()]);
    responder("GET", URL_DIFICULDADE, niveisFake());
    renderComApp(<Elefante />, { rota: "/elefante" });

    expect(await screen.findByRole("link", { name: "Ana Beatriz Souza" })).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Níveis de dificuldade" })).toBeNull();
    expect(screen.queryByRole("tab", { name: "Dificuldade por turma" })).toBeNull();
    expect(screen.queryByRole("tablist")).toBeNull();
  });

  it("Admin Global vê as sub-abas de configuração da dificuldade", async () => {
    responder("GET", URL_ELEFANTE, [alunoFake()]);
    responder("GET", URL_DIFICULDADE, niveisFake());
    renderComApp(<Elefante />, {
      rota: "/elefante",
      usuario: usuarioFake({ id: 99, nome: "Admin Constela", is_global: true, cargo: "admin" }),
    });

    expect(await screen.findByRole("tab", { name: "Níveis de dificuldade" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Dificuldade por turma" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Alunos" })).toBeInTheDocument();
    expect(await screen.findByRole("link", { name: "Ana Beatriz Souza" })).toBeInTheDocument();
  });

  it("coordenadora sem níveis: aviso simples para falar com o suporte, sem citar níveis nem pontuação", async () => {
    responder("GET", URL_ELEFANTE, [alunoFake()]);
    responder("GET", URL_DIFICULDADE, { niveis: [] });
    renderComApp(<Elefante />, { rota: "/elefante" });

    const u = userEvent.setup();
    await u.click(
      await screen.findByRole("button", { name: "Informar livros por nível de Ana Beatriz Souza" }),
    );

    expect(
      await screen.findByText("A régua desta escola ainda não foi preparada pela Constela. Fale com o suporte."),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Nenhum/)).toBeNull();
    expect(screen.queryByText(/pontuação por turma/)).toBeNull();
    expect(screen.queryByText(/Pré-Leitor/)).toBeNull();
    expect(screen.queryByRole("button", { name: /Usar níveis padrão/ })).toBeNull();
    expect(screen.queryByText(/Níveis de dificuldade/)).toBeNull();
  });

  it("Admin Global sem níveis mantém a explicação e o atalho dos níveis padrão", async () => {
    responder("GET", URL_ELEFANTE, [alunoFake()]);
    responder("GET", URL_DIFICULDADE, { niveis: [] });
    renderComApp(<Elefante />, {
      rota: "/elefante",
      usuario: usuarioFake({ id: 99, nome: "Admin Constela", is_global: true, cargo: "admin" }),
    });

    const u = userEvent.setup();
    await u.click(
      await screen.findByRole("button", { name: "Informar livros por nível de Ana Beatriz Souza" }),
    );

    expect(await screen.findByText(/definem quantos pontos cada livro vale/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Usar níveis padrão do Elefante Letrado" })).toBeInTheDocument();
    expect(screen.queryByText(/ainda não foi preparada pela Constela/)).toBeNull();
  });

  it("mostra estado vazio quando não há alunos", async () => {
    responder("GET", URL_ELEFANTE, []);
    responder("GET", URL_DIFICULDADE, niveisFake());
    renderComApp(<Elefante />, { rota: "/elefante" });

    expect(await screen.findByText("Nenhum aluno ativo")).toBeInTheDocument();
    expect(
      screen.getByText("Cadastre alunos ou importe um relatório do Elefante Letrado."),
    ).toBeInTheDocument();
  });

  it("mostra falha quando a API dos alunos erra", async () => {
    responderErro("GET", URL_ELEFANTE, 500, "Erro interno");
    responder("GET", URL_DIFICULDADE, niveisFake());
    renderComApp(<Elefante />, { rota: "/elefante" });

    expect(await screen.findByText("Não foi possível carregar")).toBeInTheDocument();
  });

  it("edita tempo/questões de um aluno e envia PUT", async () => {
    responder("GET", URL_ELEFANTE, [alunoFake()]);
    responder("GET", URL_DIFICULDADE, niveisFake());
    responder("PUT", `${URL_ELEFANTE}/5`, {});
    renderComApp(<Elefante />, { rota: "/elefante" });

    const u = userEvent.setup();
    await u.click(
      await screen.findByRole("button", { name: "Editar dados de Ana Beatriz Souza" }),
    );

    // O modal de edição abre.
    expect(
      await screen.findByRole("heading", { name: /Editar Elefante Letrado/ }),
    ).toBeInTheDocument();

    await u.click(screen.getByRole("button", { name: "Salvar e recalcular" }));

    // O PUT foi disparado para o endpoint do aluno.
    await waitFor(() =>
      expect(api).toHaveBeenCalledWith(
        `${URL_ELEFANTE}/5`,
        expect.objectContaining({ method: "PUT" }),
      ),
    );

    // E o modal fecha após salvar.
    await waitFor(() =>
      expect(
        screen.queryByRole("heading", { name: /Editar Elefante Letrado/ }),
      ).not.toBeInTheDocument(),
    );
  });

  it("informa livros por nível e envia PUT de níveis", async () => {
    responder("GET", URL_ELEFANTE, [alunoFake()]);
    responder("GET", URL_DIFICULDADE, niveisFake());
    responder("PUT", `${URL_ELEFANTE}/5/niveis`, {});
    renderComApp(<Elefante />, { rota: "/elefante" });

    const u = userEvent.setup();
    await u.click(
      await screen.findByRole("button", {
        name: "Informar livros por nível de Ana Beatriz Souza",
      }),
    );

    // O modal de faixas abre com os níveis configurados.
    expect(
      await screen.findByRole("heading", { name: /Livros por nível/ }),
    ).toBeInTheDocument();
    // O rótulo é só o nome da faixa: os pontos vêm da régua Constela, não de
    // um "pt/livro" configurado na escola.
    expect(screen.getByText("Vermelho")).toBeInTheDocument();
    expect(screen.queryByText(/pt\/livro/)).toBeNull();
    expect(
      screen.getByText(/calculados automaticamente pela régua Constela/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/pesos configurados em Métricas/)).toBeNull();

    await u.click(screen.getByRole("button", { name: "Salvar e recalcular" }));

    await waitFor(() =>
      expect(api).toHaveBeenCalledWith(
        `${URL_ELEFANTE}/5/niveis`,
        expect.objectContaining({ method: "PUT" }),
      ),
    );

    await waitFor(() =>
      expect(
        screen.queryByRole("heading", { name: /Livros por nível/ }),
      ).not.toBeInTheDocument(),
    );
  });
});
