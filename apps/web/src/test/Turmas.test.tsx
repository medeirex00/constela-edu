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

  it("seleciona todas e exclui em massa junto com os alunos", async () => {
    let lista: Turma[] = [
      turmaFake({ id: 1, nome: "3º Ano A", total_alunos: 3 }),
      turmaFake({ id: 2, nome: "4º Ano B", total_alunos: 2 }),
    ];
    responder("GET", URL_TURMAS, () => lista);
    responder("GET", URL_PROFESSORES, []);
    let corpo: unknown = null;
    responder("POST", `${URL_TURMAS}/excluir`, (_caminho, opcoes) => {
      corpo = JSON.parse((opcoes as RequestInit).body as string);
      lista = [];
      return {
        mensagem: "2 turma(s) excluída(s); 5 aluno(s) e todos os dados removidos.",
        excluidas: 2, bloqueadas: 0, alunos_excluidos: 5,
      };
    });

    const u = userEvent.setup();
    renderComApp(<Turmas />, OPCOES);

    // Marca TODAS pelo checkbox do cabeçalho → surge a barra de ação em massa.
    await u.click(await screen.findByRole("checkbox", { name: /Selecionar todas/i }));
    await u.click(await screen.findByRole("button", { name: /Excluir selecionadas/i }));

    // O caminho destrutivo (apagar alunos) fica travado até confirmar o checkbox.
    const botaoDados = await screen.findByRole("button", {
      name: /Excluir turmas \+ alunos e dados/i,
    });
    expect(botaoDados).toBeDisabled();
    await u.click(screen.getByRole("checkbox", { name: /Entendo que/i }));
    expect(botaoDados).toBeEnabled();
    await u.click(botaoDados);

    expect(corpo).toEqual({ turma_ids: [1, 2], com_alunos: true });
    expect(
      await screen.findByText(/5 aluno\(s\) e todos os dados removidos/i),
    ).toBeInTheDocument();
  });

  it("exclui uma turma com alunos junto com os dados (com_alunos=true)", async () => {
    let lista: Turma[] = [turmaFake({ id: 1, nome: "3º Ano A", total_alunos: 3 })];
    responder("GET", URL_TURMAS, () => lista);
    responder("GET", URL_PROFESSORES, []);
    let caminhoDelete = "";
    responder("DELETE", /\/escolas\/1\/turmas\/1/, (caminho) => {
      caminhoDelete = caminho;
      lista = [];
      return {
        mensagem: "Turma “3º Ano A” excluída com 3 aluno(s) e todos os dados.",
        excluidas: 1, bloqueadas: 0, alunos_excluidos: 3,
      };
    });

    const u = userEvent.setup();
    renderComApp(<Turmas />, OPCOES);

    await u.click(await screen.findByRole("button", { name: /Excluir turma 3º Ano A/i }));

    // "Excluir só a turma" indisponível (tem alunos); destrutivo trava até confirmar.
    expect(screen.getByRole("button", { name: /Excluir só a turma/i })).toBeDisabled();
    const botaoDados = screen.getByRole("button", {
      name: /Excluir turma \+ alunos e dados/i,
    });
    expect(botaoDados).toBeDisabled();
    await u.click(screen.getByRole("checkbox", { name: /Entendo que/i }));
    await u.click(botaoDados);

    expect(caminhoDelete).toContain("com_alunos=true");
    expect(await screen.findByText(/3 aluno\(s\) e todos os dados/i)).toBeInTheDocument();
  });

  it("turma com só matrículas arquivadas não é tratada como vazia (exige confirmação)", async () => {
    // total_alunos=0 (ativos filtrados) MAS total_matriculas=2 (cruas): a UI
    // deve oferecer o caminho destrutivo com confirmação, não um "Sim, excluir".
    let lista: Turma[] = [
      turmaFake({ id: 1, nome: "3º Ano A", total_alunos: 0, total_matriculas: 2 }),
    ];
    responder("GET", URL_TURMAS, () => lista);
    responder("GET", URL_PROFESSORES, []);
    let caminhoDelete = "";
    responder("DELETE", /\/escolas\/1\/turmas\/1/, (caminho) => {
      caminhoDelete = caminho;
      lista = [];
      return {
        mensagem: "Turma “3º Ano A” excluída com 2 aluno(s) e todos os dados.",
        excluidas: 1, bloqueadas: 0, alunos_excluidos: 2, alunos_desvinculados: 0,
      };
    });

    const u = userEvent.setup();
    renderComApp(<Turmas />, OPCOES);

    await u.click(await screen.findByRole("button", { name: /Excluir turma 3º Ano A/i }));

    // NÃO deve dizer que está vazia; deve exigir a confirmação destrutiva.
    expect(screen.queryByText(/não tem alunos matriculados/i)).not.toBeInTheDocument();
    const botaoDados = screen.getByRole("button", {
      name: /Excluir turma \+ alunos e dados/i,
    });
    expect(botaoDados).toBeDisabled();
    await u.click(screen.getByRole("checkbox", { name: /Entendo que/i }));
    await u.click(botaoDados);

    expect(caminhoDelete).toContain("com_alunos=true");
  });
});
