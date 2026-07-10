import { describe, expect, it } from "vitest";

import type { MatificAluno } from "../lib/types";
import Matific from "../pages/Matific";
import { api, renderComApp, responder, responderErro, screen, userEvent, waitFor } from "./utils";

const URL_MATIFIC = "/escolas/1/matific";

function matificFake(over: Partial<MatificAluno> = {}): MatificAluno {
  return {
    aluno_id: 10,
    nome: "Ana Beatriz Souza",
    turma: "3º Ano A",
    ano_escolar: "3º Ano",
    atividades: 42,
    estrelas: 15,
    pontuacao_media: 87.5,
    data_referencia: "2026-06-01T10:00:00Z",
    ...over,
  };
}

const LINHAS = [
  matificFake(),
  matificFake({ aluno_id: 11, nome: "João Pedro Barbosa", atividades: 30, estrelas: 8 }),
];

describe("Matific", () => {
  it("lista o estado atual dos alunos na plataforma", async () => {
    responder("GET", URL_MATIFIC, LINHAS);
    renderComApp(<Matific />, { rota: "/matific" });

    expect(await screen.findByRole("link", { name: "Ana Beatriz Souza" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "João Pedro Barbosa" })).toBeInTheDocument();
    // Atividades da primeira linha (inteiro, sem formatação decimal frágil).
    expect(screen.getByText("42")).toBeInTheDocument();
  });

  it("mostra o estado vazio quando nenhum aluno está ativo", async () => {
    responder("GET", URL_MATIFIC, []);
    renderComApp(<Matific />, { rota: "/matific" });

    expect(await screen.findByText("Nenhum aluno ativo")).toBeInTheDocument();
    expect(
      screen.getByText("Cadastre alunos ou importe um relatório da Matific."),
    ).toBeInTheDocument();
  });

  it("mostra falha quando a API erra", async () => {
    responderErro("GET", URL_MATIFIC, 500, "Erro interno");
    renderComApp(<Matific />, { rota: "/matific" });

    expect(await screen.findByText("Não foi possível carregar")).toBeInTheDocument();
  });

  it("abre a edição e salva os dados via PUT", async () => {
    const u = userEvent.setup();
    responder("GET", URL_MATIFIC, LINHAS);
    responder("PUT", "/escolas/1/matific/10", (_caminho, corpo) => {
      const dados = JSON.parse((corpo as RequestInit).body as string);
      return matificFake({ ...dados });
    });
    renderComApp(<Matific />, { rota: "/matific" });

    // Abre o modal de edição da primeira aluna.
    await u.click(await screen.findByRole("button", { name: "Editar dados de Ana Beatriz Souza" }));
    expect(await screen.findByText("Editar Matific — Ana Beatriz Souza")).toBeInTheDocument();

    // Ajusta um campo auditável e salva.
    const motivo = screen.getByLabelText(/Motivo da edição/);
    await u.type(motivo, "correção do relatório");
    await u.click(screen.getByRole("button", { name: "Salvar e recalcular" }));

    // O PUT foi disparado no endpoint da aluna editada.
    await waitFor(() =>
      expect(api).toHaveBeenCalledWith(
        "/escolas/1/matific/10",
        expect.objectContaining({ method: "PUT" }),
      ),
    );
    // E o modal fecha após salvar com sucesso.
    await waitFor(() =>
      expect(screen.queryByText("Editar Matific — Ana Beatriz Souza")).not.toBeInTheDocument(),
    );
  });
});
