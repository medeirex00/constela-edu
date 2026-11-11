/**
 * Ajuste manual do Matific (G_AJUSTE-1): mesma régua do Elefante.
 *
 * O servidor passou a exigir o motivo (422) e a recusar o ajuste da escola que já
 * recebe o Matific da plataforma (403, o ajuste fica com o Admin Global). A tela:
 *  - barra o salvamento sem motivo, em português, sem chamar a API;
 *  - envia o motivo sem espaços nas pontas;
 *  - explica de antemão que o ajuste vale enquanto o dado não vem da plataforma;
 *  - mostra a explicação do 403 dentro do modal.
 * Dados fictícios.
 */
import { describe, expect, it } from "vitest";

import type { MatificAluno } from "../lib/types";
import Matific from "../pages/Matific";
import { api, renderComApp, responder, responderErro, screen, userEvent, waitFor } from "./utils";

const URL_MATIFIC = "/escolas/1/matific";
const URL_PUT = "/escolas/1/matific/10";

const LINHA: MatificAluno = {
  aluno_id: 10,
  nome: "Lia Fictícia Rocha",
  turma: "3º Ano A",
  ano_escolar: "3º Ano",
  atividades: 42,
  estrelas: 150,
  pontuacao_media: 4.2,
  data_referencia: "2026-06-01T10:00:00Z",
};

function chamadasPut() {
  return api.mock.calls.filter(
    ([caminho, opcoes]) => caminho === URL_PUT && (opcoes as RequestInit | undefined)?.method === "PUT",
  );
}

async function abrirEdicao() {
  const u = userEvent.setup();
  renderComApp(<Matific />, { rota: "/matific" });
  await u.click(await screen.findByRole("button", { name: "Editar dados de Lia Fictícia Rocha" }));
  await screen.findByText("Editar Matific — Lia Fictícia Rocha");
  return u;
}

describe("Ajuste manual do Matific: motivo e governança", () => {
  it("sem motivo (ou com menos de 5 letras) não salva e explica em português", async () => {
    responder("GET", URL_MATIFIC, [LINHA]);
    responder("PUT", URL_PUT, LINHA);
    const u = await abrirEdicao();

    expect(screen.getByLabelText(/Motivo da edição \(obrigatório/)).toBeInTheDocument();
    await u.click(screen.getByRole("button", { name: "Salvar e recalcular" }));
    expect(await screen.findByText(/Informe o motivo do ajuste \(pelo menos 5 caracteres\)/))
      .toBeInTheDocument();

    await u.type(screen.getByLabelText(/Motivo da edição/), "  ok  ");
    await u.click(screen.getByRole("button", { name: "Salvar e recalcular" }));
    expect(screen.getByText(/Informe o motivo do ajuste/)).toBeInTheDocument();
    expect(chamadasPut()).toHaveLength(0);
  });

  it("com motivo, envia o texto sem espaços nas pontas", async () => {
    responder("GET", URL_MATIFIC, [LINHA]);
    responder("PUT", URL_PUT, LINHA);
    const u = await abrirEdicao();

    await u.type(screen.getByLabelText(/Motivo da edição/), "  correção do relatório  ");
    await u.click(screen.getByRole("button", { name: "Salvar e recalcular" }));

    await waitFor(() => expect(chamadasPut()).toHaveLength(1));
    const corpo = JSON.parse(String((chamadasPut()[0][1] as RequestInit).body));
    expect(corpo.motivo).toBe("correção do relatório");
  });

  it("avisa que o ajuste é da escola só enquanto o Matific não vem da plataforma", async () => {
    responder("GET", URL_MATIFIC, [LINHA]);
    await abrirEdicao();
    expect(screen.getByText(/enquanto a escola não recebe o Matific da plataforma/)).toBeInTheDocument();
    expect(screen.getByText(/passa a ser do Admin Global/)).toBeInTheDocument();
  });

  it("mostra no modal a explicação do 403 (dado já recebido da plataforma)", async () => {
    const detalhe =
      "Esta escola já recebeu dados do Matific vindos da plataforma: o ajuste manual de " +
      "atividades e estrelas fica com o Admin Global da Constela.";
    responder("GET", URL_MATIFIC, [LINHA]);
    responderErro("PUT", URL_PUT, 403, detalhe);
    const u = await abrirEdicao();

    await u.type(screen.getByLabelText(/Motivo da edição/), "correção do relatório");
    await u.click(screen.getByRole("button", { name: "Salvar e recalcular" }));

    expect(await screen.findByText(detalhe)).toBeInTheDocument();
    // O modal continua aberto: nada foi salvo.
    expect(screen.getByText("Editar Matific — Lia Fictícia Rocha")).toBeInTheDocument();
  });
});
