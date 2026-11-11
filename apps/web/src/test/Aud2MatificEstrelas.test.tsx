/**
 * Ajuste manual do Matific: no máximo 5 estrelas por atividade (G_AJUSTE-2).
 *
 * O servidor recusa (422) estrelas acima de 5 × atividades — a mesma regra do teto
 * das Premiações. A tela barra antes, em português, sem chamar a API, e diz qual é o
 * máximo para as atividades digitadas. Dados fictícios.
 */
import { describe, expect, it } from "vitest";

import type { MatificAluno } from "../lib/types";
import Matific from "../pages/Matific";
import { api, renderComApp, responder, screen, userEvent, waitFor } from "./utils";

const URL_MATIFIC = "/escolas/1/matific";
const URL_PUT = "/escolas/1/matific/10";

const LINHA: MatificAluno = {
  aluno_id: 10,
  nome: "Lia Fictícia Rocha",
  turma: "3º Ano A",
  ano_escolar: "3º Ano",
  atividades: 10,
  estrelas: 40,
  pontuacao_media: 4,
  data_referencia: "2026-06-01T10:00:00Z",
};

function chamadasPut() {
  return api.mock.calls.filter(
    ([caminho, opcoes]) => caminho === URL_PUT && (opcoes as RequestInit | undefined)?.method === "PUT",
  );
}

async function editarEstrelas(valor: string) {
  const u = userEvent.setup();
  responder("GET", URL_MATIFIC, [LINHA]);
  responder("PUT", URL_PUT, LINHA);
  renderComApp(<Matific />, { rota: "/matific" });
  await u.click(await screen.findByRole("button", { name: "Editar dados de Lia Fictícia Rocha" }));
  const estrelas = await screen.findByLabelText("Estrelas");
  await u.clear(estrelas);
  await u.type(estrelas, valor);
  await u.type(screen.getByLabelText(/Motivo da edição/), "correção do relatório");
  await u.click(screen.getByRole("button", { name: "Salvar e recalcular" }));
}

describe("Ajuste manual do Matific: teto de estrelas", () => {
  it("estrelas acima de 5 por atividade são barradas no cliente, sem chamar a API", async () => {
    await editarEstrelas("5000");
    expect(await screen.findByText(/no máximo 5 estrelas por atividade/)).toBeInTheDocument();
    expect(screen.getByText(/com 10 atividades, são no máximo 50 estrelas/)).toBeInTheDocument();
    expect(chamadasPut()).toHaveLength(0);
  });

  it("no teto (5 por atividade) salva normalmente", async () => {
    await editarEstrelas("50");
    await waitFor(() => expect(chamadasPut()).toHaveLength(1));
    const corpo = JSON.parse(String((chamadasPut()[0][1] as RequestInit).body));
    expect(corpo.estrelas).toBe(50);
  });
});
