import { describe, expect, it } from "vitest";

import Elefante from "../pages/Elefante";
import {
  api,
  renderComApp,
  responder,
  responderErro,
  screen,
  userEvent,
  waitFor,
} from "./utils";

const URL_ELEFANTE = "/escolas/1/elefante";
const URL_DIFICULDADE = "/escolas/1/dificuldade";

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
    expect(screen.getByText("Vermelho (1 pt/livro)")).toBeInTheDocument();

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
