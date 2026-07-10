import { describe, expect, it } from "vitest";

import Turmas from "../pages/Turmas";
import type { Turma } from "../lib/types";
import {
  renderComApp,
  responder,
  responderErro,
  screen,
  turmaFake,
  userEvent,
} from "./utils";

const URL_TURMAS = "/escolas/1/turmas";
const URL_PROFESSORES = "/escolas/1/professores";
const OPCOES = { rota: "/turmas" };

describe("Turmas", () => {
  it("lista as turmas da escola", async () => {
    responder("GET", URL_TURMAS, [
      turmaFake(),
      turmaFake({
        id: 2,
        nome: "4º Ano B",
        ano_escolar: "4º Ano",
        professor_nome: "Prof. Marina",
        total_alunos: 25,
      }),
    ]);
    responder("GET", URL_PROFESSORES, []);
    renderComApp(<Turmas />, OPCOES);

    expect(await screen.findByRole("link", { name: "3º Ano A" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "4º Ano B" })).toBeInTheDocument();
    expect(screen.getByText("Prof. Marina")).toBeInTheDocument();
  });

  it("mostra estado vazio quando não há turmas", async () => {
    responder("GET", URL_TURMAS, []);
    responder("GET", URL_PROFESSORES, []);
    renderComApp(<Turmas />, OPCOES);

    expect(await screen.findByText("Nenhuma turma cadastrada")).toBeInTheDocument();
  });

  it("mostra falha quando a API erra", async () => {
    responderErro("GET", URL_TURMAS, 500, "Erro interno");
    responder("GET", URL_PROFESSORES, []);
    renderComApp(<Turmas />, OPCOES);

    expect(
      await screen.findByText("Não foi possível carregar", undefined, { timeout: 4000 }),
    ).toBeInTheDocument();
  });

  it("cria uma turma pelo modal (POST) e ela aparece na lista", async () => {
    const lista: Turma[] = [];
    responder("GET", URL_TURMAS, () => lista);
    responder("GET", URL_PROFESSORES, []);
    responder("POST", URL_TURMAS, (_caminho, corpo) => {
      const body = JSON.parse((corpo as RequestInit).body as string);
      const nova = turmaFake({
        id: 99,
        nome: body.nome,
        ano_escolar: body.ano_escolar,
        ano_letivo: body.ano_letivo,
        turno: body.turno,
        total_alunos: 0,
      });
      lista.push(nova);
      return nova;
    });

    const u = userEvent.setup();
    renderComApp(<Turmas />, OPCOES);

    // Começa vazio.
    expect(await screen.findByText("Nenhuma turma cadastrada")).toBeInTheDocument();

    // Abre o modal de cadastro.
    await u.click(screen.getByRole("button", { name: /adicionar turma/i }));
    expect(await screen.findByText("Adicionar turma")).toBeInTheDocument();

    // Preenche os campos obrigatórios e submete.
    await u.type(screen.getByLabelText(/Nome da turma/i), "Turma Piloto B");
    await u.type(screen.getByLabelText(/Série \/ Ano escolar/i), "5o Ano");
    await u.selectOptions(screen.getByLabelText(/Turno \*/i), "manha");
    await u.click(screen.getByRole("button", { name: /criar turma/i }));

    // A turma criada aparece na lista recarregada e há aviso de sucesso.
    expect(await screen.findByRole("link", { name: "Turma Piloto B" })).toBeInTheDocument();
    expect(screen.getByText(/criada com sucesso/i)).toBeInTheDocument();
  });
});
