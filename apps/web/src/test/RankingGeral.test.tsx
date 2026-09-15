import { describe, expect, it } from "vitest";

import RankingGeral from "../pages/RankingGeral";
import {
  api,
  rankingItemFake,
  renderComApp,
  responder,
  responderErro,
  screen,
  turmaFake,
  userEvent,
  usuarioFake,
  waitFor,
} from "./utils";

const URL_TURMAS = "/escolas/1/turmas";
const URL_RANKING = "/escolas/1/ranking";

const opcoes = { rota: "/ranking" };

/** Caminhos com que `/ranking` foi chamado (para inspecionar a query string). */
const chamadasRanking = () =>
  api.mock.calls.map((c) => String(c[0])).filter((p) => p.startsWith(`${URL_RANKING}?`) || p === URL_RANKING);

describe("RankingGeral", () => {
  it("carrega e mostra a ordem única do ano (Geral = Leitura + Matemática)", async () => {
    responder("GET", URL_TURMAS, [turmaFake()]);
    responder("GET", URL_RANKING, [
      rankingItemFake({ posicao: 1, aluno_id: 10, nome: "Ana Beatriz Souza", n_aferidos: 2 }),
      rankingItemFake({ posicao: 2, aluno_id: 11, nome: "João Pedro Barbosa", n_aferidos: 2 }),
    ]);

    renderComApp(<RankingGeral />, opcoes);

    // Nome dos alunos vira link para o perfil.
    expect(
      await screen.findByRole("link", { name: "Ana Beatriz Souza" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "João Pedro Barbosa" }),
    ).toBeInTheDocument();

    // Colunas da ordem única + o nome dela e o denominador vindo da API. As
    // colunas se chamam pela MATÉRIA (Leitura / Matemática), não pelo produto:
    // o mandato fixa esse vocabulário para a escola (antes: "Matific").
    expect(screen.getByRole("columnheader", { name: "Matemática" })).toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "Matific" })).not.toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Leitura" })).toBeInTheDocument();
    expect(
      screen.getByText(/Geral \(Leitura \+ Matemática\) · 2 aluno\(s\) na classificação/),
    ).toBeInTheDocument();
    // A visão por matéria (sub-abas) saiu daqui: vive nas abas Leitura/Matemática.
    expect(screen.queryByRole("tab", { name: /Desempenho em/ })).not.toBeInTheDocument();
  });

  it("mostra o estado vazio quando não há nenhuma nota calculada", async () => {
    responder("GET", URL_TURMAS, []);
    responder("GET", URL_RANKING, []);

    renderComApp(<RankingGeral />, opcoes);

    expect(
      await screen.findByText("Nenhuma nota calculada ainda"),
    ).toBeInTheDocument();
  });

  it("mostra a mensagem de falha quando a API do ranking erra", async () => {
    responder("GET", URL_TURMAS, []);
    responderErro("GET", URL_RANKING, 500, "Erro interno");

    renderComApp(<RankingGeral />, opcoes);

    expect(
      await screen.findByText("Não foi possível carregar"),
    ).toBeInTheDocument();
  });

  it("ao escolher um período, mantém a ordem do ano e aponta para a aba Evolução", async () => {
    // Decisão registrada: a classificação por período fica só na aba Evolução:
    // a aba Geral chamava o mesmo endpoint com os mesmos parâmetros —
    // docs/limpeza-ux-2026-09.md
    responder("GET", URL_TURMAS, [turmaFake()]);
    responder("GET", URL_RANKING, [
      rankingItemFake({ nome: "Ana Beatriz Souza" }),
    ]);

    const u = userEvent.setup();
    renderComApp(<RankingGeral />, opcoes);

    // Estado inicial: ordem única do ano, sem aviso.
    await screen.findByRole("link", { name: "Ana Beatriz Souza" });
    expect(screen.queryByText(/A classificação por período fica na aba Evolução/)).not.toBeInTheDocument();

    await u.selectOptions(
      screen.getByLabelText("Período de análise"),
      "hoje",
    );

    // O Ranking Geral NÃO vira a tabela do período (era a mesma da aba
    // Evolução): avisa e oferece o caminho, mantendo a ordem do ano na tela.
    expect(
      await screen.findByText(/A classificação por período fica na aba Evolução/),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Ver a aba Evolução/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Ana Beatriz Souza" })).toBeInTheDocument();
    // E o /ranking-evolucao NÃO é consultado aqui.
    expect(api.mock.calls.some((c) => String(c[0]).includes("/ranking-evolucao"))).toBe(false);
  });

  it("filtra por turma e refaz a busca do ranking com turma_id", async () => {
    responder("GET", URL_TURMAS, [turmaFake({ id: 1, nome: "3º Ano A" })]);
    responder("GET", URL_RANKING, (caminho: string) =>
      caminho.includes("turma_id=1")
        ? [rankingItemFake({ aluno_id: 20, nome: "Aluno Da Turma A" })]
        : [rankingItemFake({ aluno_id: 10, nome: "Ana Beatriz Souza" })],
    );

    const u = userEvent.setup();
    renderComApp(<RankingGeral />, opcoes);

    await screen.findByRole("link", { name: "Ana Beatriz Souza" });

    await u.selectOptions(screen.getByLabelText("Filtrar por turma ou série"), "turma:1");

    expect(
      await screen.findByRole("link", { name: "Aluno Da Turma A" }),
    ).toBeInTheDocument();
  });

  it("com turma e sem turno: conta quantos o filtro mostra e avisa que a posição é a da escola inteira", async () => {
    responder("GET", URL_TURMAS, [turmaFake({ id: 1, nome: "3º Ano A", turno: "manha" })]);
    responder("GET", URL_RANKING, (caminho: string) =>
      caminho.includes("turma_id=1")
        // Sem turno, a gestão recebe a posição CARIMBADA da escola (7º, 12º):
        // o número ao lado não pode se passar pelo denominador dessas posições.
        ? [rankingItemFake({ posicao: 7, aluno_id: 20, nome: "Aluno Da Turma A", n_aferidos: 40 }),
           rankingItemFake({ posicao: 12, aluno_id: 21, nome: "Outro Da Turma A", n_aferidos: 40 })]
        : [rankingItemFake({ aluno_id: 10, nome: "Ana Beatriz Souza", n_aferidos: 40 })],
    );

    const u = userEvent.setup();
    renderComApp(<RankingGeral />, opcoes);

    await screen.findByRole("link", { name: "Ana Beatriz Souza" });
    expect(screen.getByText(/40 aluno\(s\) na classificação/)).toBeInTheDocument();

    await u.selectOptions(screen.getByLabelText("Filtrar por turma ou série"), "turma:1");

    expect(await screen.findByRole("link", { name: "Aluno Da Turma A" })).toBeInTheDocument();
    expect(screen.getByText("7º")).toBeInTheDocument();
    expect(
      screen.getByText(/Geral \(Leitura \+ Matemática\) · 2 aluno\(s\) neste filtro · posição na escola inteira/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/na classificação/)).not.toBeInTheDocument();
    expect(screen.queryByText(/40 aluno/)).not.toBeInTheDocument();
  });

  it("professor com turma: a lista já vem renumerada nas turmas dele, sem o sufixo da escola inteira", async () => {
    responder("GET", URL_TURMAS, [turmaFake({ id: 1, nome: "3º Ano A", turno: "manha" })]);
    responder("GET", URL_RANKING, (caminho: string) =>
      caminho.includes("turma_id=1")
        ? [rankingItemFake({ posicao: 1, aluno_id: 20, nome: "Aluno Da Turma A" }),
           rankingItemFake({ posicao: 2, aluno_id: 21, nome: "Outro Da Turma A" })]
        : [rankingItemFake({ aluno_id: 10, nome: "Ana Beatriz Souza" })],
    );

    const u = userEvent.setup();
    renderComApp(<RankingGeral />, { ...opcoes, usuario: usuarioFake({ cargo: "professor" }) });

    await screen.findByRole("link", { name: "Ana Beatriz Souza" });
    await u.selectOptions(screen.getByLabelText("Filtrar por turma ou série"), "turma:1");

    expect(await screen.findByRole("link", { name: "Aluno Da Turma A" })).toBeInTheDocument();
    expect(screen.getByText(/· 2 aluno\(s\) neste filtro$/)).toBeInTheDocument();
    expect(screen.queryByText(/posição na escola inteira/)).not.toBeInTheDocument();
  });

  it("consolida por série e busca o ranking com ano_escolar", async () => {
    responder("GET", URL_TURMAS, [
      turmaFake({ id: 1, nome: "1º Ano A", ano_escolar: "1º Ano" }),
      turmaFake({ id: 2, nome: "1º Ano B", ano_escolar: "1º Ano" }),
    ]);
    responder("GET", URL_RANKING, (caminho: string) =>
      caminho.includes("ano_escolar=1%C2%BA+Ano") || caminho.includes("ano_escolar=1%C2%BA%20Ano")
        ? [rankingItemFake({ aluno_id: 30, nome: "Aluno Da Serie" })]
        : [rankingItemFake({ aluno_id: 10, nome: "Ana Beatriz Souza" })],
    );

    const u = userEvent.setup();
    renderComApp(<RankingGeral />, opcoes);

    await screen.findByRole("link", { name: "Ana Beatriz Souza" });

    await u.selectOptions(
      screen.getByLabelText("Filtrar por turma ou série"),
      "serie:1º Ano",
    );

    expect(
      await screen.findByRole("link", { name: "Aluno Da Serie" }),
    ).toBeInTheDocument();
  });

  it("turno: as opções vêm das turmas da escola e a escolha refaz /ranking com turno=", async () => {
    responder("GET", URL_TURMAS, [
      turmaFake({ id: 1, nome: "3º Ano A", turno: "manha" }),
      turmaFake({ id: 2, nome: "3º Ano B", turno: "tarde" }),
      turmaFake({ id: 3, nome: "3º Ano C", turno: null }),
    ]);
    responder("GET", URL_RANKING, (caminho: string) => {
      const turno = new URLSearchParams(caminho.split("?")[1] ?? "").get("turno");
      if (turno === "tarde") return [rankingItemFake({ aluno_id: 20, nome: "Aluno Da Tarde", n_aferidos: 1 })];
      if (turno === "") return [rankingItemFake({ aluno_id: 30, nome: "Aluno Sem Turno", n_aferidos: 1 })];
      return [rankingItemFake({ aluno_id: 10, nome: "Ana Beatriz Souza", n_aferidos: 3 })];
    });

    const u = userEvent.setup();
    renderComApp(<RankingGeral />, opcoes);

    // Sem turno escolhido: o parâmetro NÃO vai na query.
    await screen.findByRole("link", { name: "Ana Beatriz Souza" });
    expect(chamadasRanking().some((p) => p.includes("turno="))).toBe(false);
    expect(screen.getByText(/3 aluno\(s\) na classificação/)).toBeInTheDocument();

    // Opções derivadas de Turma.turno: Manhã, Tarde e "Sem turno" (há turma nula).
    const seletor = await screen.findByLabelText("Turno");
    expect(seletor).toHaveTextContent("Todos os turnos");
    expect(seletor).toHaveTextContent("Manhã");
    expect(seletor).toHaveTextContent("Tarde");
    expect(seletor).toHaveTextContent("Sem turno");
    expect(seletor).not.toHaveTextContent("Noite");

    await u.selectOptions(seletor, "tarde");
    expect(await screen.findByRole("link", { name: "Aluno Da Tarde" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Ana Beatriz Souza" })).not.toBeInTheDocument();
    // Denominador do conjunto filtrado (carimbado pela API) com o NOME do
    // recorte: as posições foram renumeradas dentro do turno.
    expect(screen.getByText(/1 aluno\(s\) no turno Tarde/)).toBeInTheDocument();
    expect(screen.queryByText(/na classificação/)).not.toBeInTheDocument();
    await waitFor(() => expect(chamadasRanking().some((p) => p.includes("turno=tarde"))).toBe(true));

    // "Sem turno" vai como turno= (vazio) — e não vira "no turno Sem turno".
    await u.selectOptions(seletor, "");
    expect(await screen.findByRole("link", { name: "Aluno Sem Turno" })).toBeInTheDocument();
    await waitFor(() => expect(chamadasRanking().some((p) => /[?&]turno=(&|$)/.test(p))).toBe(true));
    expect(screen.getByText(/1 aluno\(s\) em turmas sem turno/)).toBeInTheDocument();

    // Turno + turma: a contagem é do recorte inteiro (a turma dentro do turno).
    await u.selectOptions(screen.getByLabelText("Filtrar por turma ou série"), "turma:3");
    expect(await screen.findByText(/1 aluno\(s\) neste filtro, em turmas sem turno/)).toBeInTheDocument();
  });
});
