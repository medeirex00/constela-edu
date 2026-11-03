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
  usuarioFake,
  within,
} from "./utils";

const URL_TURMAS = "/escolas/1/turmas";
const URL_PROFESSORES = "/escolas/1/professores";
const OPCOES = { rota: "/turmas" };
// Excluir turma JUNTO com os alunos é exclusivo do Admin Global (D19).
const OPCOES_GLOBAL = { rota: "/turmas", usuario: usuarioFake({ is_global: true }) };

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

  it("turmas só arquivadas/de outro ano: não diz 'nenhuma cadastrada' e oferece ver todas", async () => {
    responder("GET", URL_TURMAS, [
      turmaFake({ id: 7, nome: "2º Ano A", ano_letivo: 2025 }),
    ]);
    responder("GET", URL_PROFESSORES, []);
    const u = userEvent.setup();
    renderComApp(<Turmas />, OPCOES);

    expect(await screen.findByText("Nenhuma turma ativa em 2026")).toBeInTheDocument();
    expect(screen.queryByText("Nenhuma turma cadastrada")).toBeNull();
    await u.click(screen.getByRole("button", { name: "Ver arquivadas e de outros anos" }));
    expect(await screen.findByRole("link", { name: "2º Ano A" })).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: /Mostrar turmas arquivadas e de outros anos/ }))
      .toHaveAttribute("aria-checked", "true");
  });

  it("indicadores do topo contam as turmas ativas do ano, os alunos e as sem titular", async () => {
    responder("GET", URL_TURMAS, [
      turmaFake({ id: 1, nome: "3º Ano A", total_alunos: 20, professor_id: 4, professor_nome: "Prof. Marina" }),
      turmaFake({ id: 2, nome: "4º Ano B", total_alunos: 5, professor_id: null }),
      turmaFake({ id: 3, nome: "1º Ano C", total_alunos: 9, status: "arquivada" }),
    ]);
    responder("GET", URL_PROFESSORES, []);
    renderComApp(<Turmas />, OPCOES);

    // O valor é o número exato do cartão (o rótulo "… em 2026" não pode valer como acerto).
    const cartao = async (rotulo: string) => within((await screen.findByText(rotulo)).parentElement as HTMLElement);
    expect((await cartao("Turmas ativas em 2026")).getByText("2", { exact: true })).toBeInTheDocument();
    expect((await cartao("Alunos nessas turmas")).getByText("25", { exact: true })).toBeInTheDocument();
    expect((await cartao("Sem professor titular")).getByText("1", { exact: true })).toBeInTheDocument();
  });

  it("coluna 'Ano letivo' a partir de sm: separa duas '5º A' de anos diferentes com as arquivadas à mostra", async () => {
    // Em xl:table-cell ela sumia de 640 a 1279 px e as duas linhas ficavam idênticas.
    responder("GET", URL_TURMAS, [
      turmaFake({ id: 1, nome: "5º A", ano_escolar: "5º Ano", ano_letivo: 2026 }),
      turmaFake({ id: 2, nome: "5º A", ano_escolar: "5º Ano", ano_letivo: 2025, status: "arquivada" }),
    ]);
    responder("GET", URL_PROFESSORES, []);
    const u = userEvent.setup();
    renderComApp(<Turmas />, OPCOES);

    await screen.findByRole("link", { name: "5º A" });
    await u.click(screen.getByRole("switch", { name: /Mostrar turmas arquivadas e de outros anos/ }));
    const linhas = (await screen.findAllByRole("link", { name: "5º A" })).map((l) => l.closest("tr") as HTMLElement);
    expect(linhas).toHaveLength(2);

    const th = screen.getByRole("columnheader", { name: "Ano letivo" });
    expect(th).toHaveClass("hidden", "sm:table-cell");
    expect(th).not.toHaveClass("xl:table-cell");
    const coluna = Array.from((th.parentElement as HTMLElement).children).indexOf(th);
    const celulas = linhas.map((tr) => tr.children[coluna] as HTMLElement);
    expect(celulas.map((td) => td.textContent).sort()).toEqual(["2025", "2026"]);
    for (const td of celulas) {
      expect(td).toHaveClass("hidden", "sm:table-cell");
      expect(td).not.toHaveClass("xl:table-cell");
    }
  });

  it("o turno vem uma vez só, sob o nome; 'Ano letivo' encurta e as três ações seguem em toda linha", async () => {
    // Revisão visual v2: em 820/768 px a coluna Ações (excluir) saía cortada do cartão.
    responder("GET", URL_TURMAS, [
      turmaFake({ id: 1, nome: "2º Ano A", ano_escolar: "2º Ano", turno: "manha" }),
      turmaFake({ id: 2, nome: "4º Ano B", ano_escolar: "4º Ano", turno: null }),
    ]);
    responder("GET", URL_PROFESSORES, []);
    renderComApp(<Turmas />, OPCOES);

    const link = await screen.findByRole("link", { name: "2º Ano A" });
    // Nome e chip de série numa linha só (antes: "2º / Ano A").
    expect(link).toHaveClass("whitespace-nowrap");
    const linha = link.closest("tr") as HTMLElement;
    expect(within(linha).getByText("2º Ano")).toHaveClass("whitespace-nowrap");

    // Sem coluna Turno: o turno fica sob o nome em todas as larguras e aparece uma
    // vez só no DOM (sem render duplo responsivo — regra da v2, §3).
    expect(screen.queryByRole("columnheader", { name: "Turno" })).toBeNull();
    const celulaNome = link.closest("td") as HTMLElement;
    expect(within(celulaNome).getByText("Manhã")).toBeInTheDocument();
    expect(within(linha).getAllByText("Manhã")).toHaveLength(1);
    // Turma sem turno: nada inventado sob o nome.
    const celulaSemTurno = screen.getByRole("link", { name: "4º Ano B" }).closest("td") as HTMLElement;
    expect(celulaSemTurno.textContent).toBe("4º Ano B");

    // "Ano letivo": rótulo visível curto, nome completo no leitor de tela e no title.
    const thAno = screen.getByRole("columnheader", { name: "Ano letivo" });
    expect(thAno).toHaveAttribute("title", "Ano letivo");
    expect(within(thAno).getByText("letivo")).toHaveClass("sr-only", "xl:not-sr-only");

    // Nenhuma ação some: editar, arquivar e excluir em cada linha.
    expect(screen.getByRole("columnheader", { name: "Ações" })).toBeInTheDocument();
    for (const nome of ["2º Ano A", "4º Ano B"]) {
      expect(screen.getByRole("button", { name: `Editar turma ${nome}` })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: `Arquivar turma ${nome}` })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: `Excluir turma ${nome}` })).toBeInTheDocument();
    }
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

  it("arquivar turma com alunos ativos: o botão avisa e a recusa da API (409) aparece", async () => {
    responder("GET", URL_TURMAS, [turmaFake({ id: 1, nome: "3º Ano A", total_alunos: 3 })]);
    responder("GET", URL_PROFESSORES, []);
    const detalhe =
      "A turma “3º Ano A” não pode ser arquivada: tem 3 aluno(s) ativo(s) matriculado(s) " +
      "nela a partir do ano letivo 2026. Antes de arquivar, abra a turma e use " +
      "“Transferir de turma”.";
    responderErro("PUT", /\/escolas\/1\/turmas\/1$/, 409, detalhe);

    const u = userEvent.setup();
    renderComApp(<Turmas />, OPCOES);

    const botao = await screen.findByRole("button", { name: /Arquivar turma 3º Ano A/i });
    // O título já diz o que fazer antes de tentar (D17).
    expect(botao).toHaveAttribute(
      "title",
      expect.stringMatching(/transfira os 3 aluno\(s\) ativo\(s\)/i),
    );
    await u.click(botao);

    expect(await screen.findByText(/não pode ser arquivada/i)).toBeInTheDocument();
    expect(screen.getByText(/Transferir de turma/i)).toBeInTheDocument();
    // A turma continua ativa na tela.
    expect(screen.getByText("Ativa")).toBeInTheDocument();
  });

  it("turma sem alunos ativos mostra só “Arquivar” no botão", async () => {
    responder("GET", URL_TURMAS, [
      turmaFake({ id: 1, nome: "3º Ano A", total_alunos: 0 }),
    ]);
    responder("GET", URL_PROFESSORES, []);
    renderComApp(<Turmas />, OPCOES);

    const botao = await screen.findByRole("button", { name: /Arquivar turma 3º Ano A/i });
    expect(botao).toHaveAttribute("title", "Arquivar");
  });

  it("Admin Global seleciona todas e exclui em massa junto com os alunos", async () => {
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
    renderComApp(<Turmas />, OPCOES_GLOBAL);

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

  it("Admin Global exclui uma turma com alunos junto com os dados (com_alunos=true)", async () => {
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
    renderComApp(<Turmas />, OPCOES_GLOBAL);

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
    // total_alunos=0 (conta só os ativos) MAS total_matriculas=2 (cruas): a UI
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
    renderComApp(<Turmas />, OPCOES_GLOBAL);

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
  it("admin da escola não vê “turma + alunos e dados” e é orientado a transferir (D19)", async () => {
    responder("GET", URL_TURMAS, [turmaFake({ id: 1, nome: "3º Ano A", total_alunos: 3 })]);
    responder("GET", URL_PROFESSORES, []);

    const u = userEvent.setup();
    renderComApp(<Turmas />, OPCOES);

    await u.click(await screen.findByRole("button", { name: /Excluir turma 3º Ano A/i }));

    expect(screen.getByRole("button", { name: /Excluir só a turma/i })).toBeDisabled();
    expect(
      screen.queryByRole("button", { name: /Excluir turma \+ alunos e dados/i }),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: /Entendo que/i })).not.toBeInTheDocument();
    expect(
      screen.getByText(/Apagar os alunos junto com a turma é exclusivo do Admin Global/i),
    ).toBeInTheDocument();
  });

  it("admin da escola na exclusão em massa só tem “Excluir só as turmas” (D19)", async () => {
    responder("GET", URL_TURMAS, [
      turmaFake({ id: 1, nome: "3º Ano A", total_alunos: 3 }),
      turmaFake({ id: 2, nome: "4º Ano B", total_alunos: 0 }),
    ]);
    responder("GET", URL_PROFESSORES, []);
    let corpo: unknown = null;
    responder("POST", `${URL_TURMAS}/excluir`, (_caminho, opcoes) => {
      corpo = JSON.parse((opcoes as RequestInit).body as string);
      return {
        mensagem: "1 turma(s) excluída(s); 1 com alunos foram mantida(s) — mova os alunos antes.",
        excluidas: 1, bloqueadas: 1, alunos_excluidos: 0,
      };
    });

    const u = userEvent.setup();
    renderComApp(<Turmas />, OPCOES);

    await u.click(await screen.findByRole("checkbox", { name: /Selecionar todas/i }));
    await u.click(await screen.findByRole("button", { name: /Excluir selecionadas/i }));

    expect(
      await screen.findByText(/Apagar os alunos junto com as turmas é exclusivo do Admin Global/i),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Excluir turmas \+ alunos e dados/i }),
    ).not.toBeInTheDocument();
    await u.click(screen.getByRole("button", { name: /Excluir só as turmas/i }));
    expect(corpo).toEqual({ turma_ids: [1, 2], com_alunos: false });
  });
});
