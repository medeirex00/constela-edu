/**
 * Aba "Desempenho" do Ranking (o arquivo segue `RankingGeral.tsx`; antes a aba
 * se chamava "Geral" e mostrava a ORDEM ÚNICA pela nota geral).
 *
 * REGRA NOVA — Decisão 1 do dono (2026-10-12): transição da `nota_geral` para
 * as notas por disciplina. Os testes antigos desta tela travavam a ordem única
 * (coluna "Geral", contagem "Geral (Leitura + Matemática) · N aluno(s)…"); eles
 * foram reescritos porque a regra aprovada mudou, não para passar. Agora:
 *   1. a aba consulta SEMPRE `/ranking?dimensao=` (plano de retirada, item 1) —
 *      nenhuma chamada sem dimensão, e o valor legado nunca aparece na tela;
 *   2. o seletor de matéria só oferece o que a rede contratou;
 *   3. período ≠ ano letivo continua apontando para a aba Evolução;
 *   4. turma/série e turno chegam à consulta da matéria;
 *   5. o cartaz GERAL (ordem única) continua disponível à gestão — o que o
 *      cartaz padrão vira é decisão própria do dono (plano, item 8);
 *   6. as matérias seguem o contrato da ESCOLA aberta, também para o Admin
 *      Global (que tem o catálogo inteiro no /auth/me);
 *   7. CONTAGEM honesta no cabeçalho (a régua que a ordem única tinha, agora em
 *      `DesempenhoDimensao`): turma/série sem turno diz quantos o filtro mostra
 *      e que a posição é entre os aferidos da escola; com turno, o recorte.
 */
import { describe, expect, it } from "vitest";

import type { RankingItem } from "../lib/types";
import RankingGeral from "../pages/RankingGeral";
import {
  ApiError,
  api,
  apiDownload,
  escolaComContrato,
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
const URL_NAO_AFERIDOS = "/escolas/1/nao-aferidos";

const opcoes = { rota: "/ranking" };

const parametros = (caminho: string) => new URLSearchParams(caminho.split("?")[1] ?? "");
/** Caminhos com que `/ranking` foi chamado (com ou sem query; nunca sub-rotas). */
const chamadasRanking = () =>
  api.mock.calls.map((c) => String(c[0]))
    .filter((p) => p === URL_RANKING || p.startsWith(`${URL_RANKING}?`));

/** Item do ranking POR DIMENSÃO, como a API carimba — com o legado da ordem
 *  única presente e DIFERENTE da nota da matéria, para provar que a tela não o
 *  lê (o valor vem da fábrica `rankingItemFake`, que ainda o exige no tipo). */
function itemDimensao(over: Partial<RankingItem> = {}): RankingItem {
  return {
    ...rankingItemFake({ posicao: 1, aluno_id: 10, nome: "Ana Leitora" }),
    dimensao: "leitura", nota: 91, aferido: true, n_aferidos: 2,
    dados: { livros_unicos: 12, atividades: 30 }, adocao: 100,
    ...over,
  };
}

/** `/ranking` responde pela dimensão pedida (e por turma/turno, se vierem). */
function mockarRanking() {
  responder("GET", URL_TURMAS, [
    turmaFake({ id: 1, nome: "3º Ano A", turno: "manha" }),
    turmaFake({ id: 2, nome: "3º Ano B", turno: "tarde" }),
  ]);
  responder("GET", URL_RANKING, (caminho: string) => {
    const q = parametros(caminho);
    if (q.get("dimensao") === "matematica") {
      return [itemDimensao({ aluno_id: 30, nome: "Davi Contas", dimensao: "matematica", nota: 88,
                             n_aferidos: 1 })];
    }
    if (q.get("turma_id") === "1") return [itemDimensao({ aluno_id: 20, nome: "Aluna Da Turma A" })];
    if (q.get("turno") === "tarde") return [itemDimensao({ aluno_id: 21, nome: "Aluno Da Tarde" })];
    return [itemDimensao(), itemDimensao({ posicao: 2, aluno_id: 11, nome: "Caio Leitor", nota: 74 })];
  });
  responder("GET", URL_NAO_AFERIDOS, {
    contratadas: ["leitura", "matematica"], total_alunos: 3,
    dimensoes: [{
      dimensao: "leitura", plataforma: "Elefante Letrado", n_aferidos: 2, total: 3,
      alunos: [{ aluno_id: 77, nome: "Bruno Sem Leitura", turma: "3º Ano A", ano_escolar: "3º Ano" }],
    }],
    sem_nenhuma: [],
  });
}

describe("RankingGeral (aba Desempenho — classificação oficial por matéria)", () => {
  it("abre na Leitura, só consulta /ranking COM dimensão e não mostra a nota geral", async () => {
    mockarRanking();
    renderComApp(<RankingGeral />, opcoes);

    expect(await screen.findByRole("link", { name: "Ana Leitora" })).toBeInTheDocument();
    expect(screen.getByText("Classificação oficial — Leitura")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Nota de Leitura" })).toBeInTheDocument();
    expect(screen.getByText("91,0")).toBeInTheDocument();
    expect(screen.getByText("2 alunos aferidos em Leitura")).toBeInTheDocument();
    // A ordem única saiu desta aba: nem coluna "Geral", nem o valor legado
    // (85 na fábrica do item), nem o rótulo da ordem única.
    expect(screen.queryByRole("columnheader", { name: "Geral" })).not.toBeInTheDocument();
    expect(screen.queryByText("85,0")).not.toBeInTheDocument();
    expect(screen.queryByText(/Geral \(Leitura \+ Matemática\)/)).not.toBeInTheDocument();
    // Quem não tem dado aparece na lista de ação, sem nota — não como 0,0.
    expect(await screen.findByRole("link", { name: "Bruno Sem Leitura" })).toBeInTheDocument();
    // Toda consulta ao /ranking leva `dimensao` (item 1 do plano de retirada).
    await waitFor(() => expect(chamadasRanking().length).toBeGreaterThan(0));
    expect(chamadasRanking().every((p) => parametros(p).get("dimensao") === "leitura")).toBe(true);
  });

  it("o seletor de Matéria troca para Matemática e consulta ?dimensao=matematica", async () => {
    mockarRanking();
    const u = userEvent.setup();
    renderComApp(<RankingGeral />, opcoes);
    await screen.findByRole("link", { name: "Ana Leitora" });

    const seletor = screen.getByLabelText("Matéria");
    expect(seletor).toHaveTextContent("Leitura");
    expect(seletor).toHaveTextContent("Matemática");
    await u.selectOptions(seletor, "matematica");

    expect(await screen.findByRole("link", { name: "Davi Contas" })).toBeInTheDocument();
    expect(screen.getByText("Classificação oficial — Matemática")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Ana Leitora" })).not.toBeInTheDocument();
    expect(chamadasRanking().some((p) => parametros(p).get("dimensao") === "matematica")).toBe(true);
    expect(chamadasRanking().every((p) => parametros(p).has("dimensao"))).toBe(true);
  });

  it("?materia=matematica (deep-link do painel) abre direto na Matemática", async () => {
    mockarRanking();
    renderComApp(<RankingGeral />, { rota: "/ranking?materia=matematica" });

    expect(await screen.findByRole("link", { name: "Davi Contas" })).toBeInTheDocument();
    expect((screen.getByLabelText("Matéria") as HTMLSelectElement).value).toBe("matematica");
  });

  it("rede só com Leitura: sem seletor de matéria, e o deep-link de Matemática cai na Leitura", async () => {
    mockarRanking();
    renderComApp(<RankingGeral />, {
      rota: "/ranking?materia=matematica",
      usuario: usuarioFake({ modulos: ["leitura"] }),
    });

    expect(await screen.findByRole("link", { name: "Ana Leitora" })).toBeInTheDocument();
    expect(screen.getByText("Classificação oficial — Leitura")).toBeInTheDocument();
    expect(screen.queryByLabelText("Matéria")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Davi Contas" })).not.toBeInTheDocument();
    // Este teste monta a tela SEM a guarda de sessão do App: há um render antes
    // de /auth/me responder em que os módulos ainda não são conhecidos (o hook
    // assume todos). No app, a guarda só renderiza a rota com o usuário
    // carregado; o que se afirma aqui é o estado FINAL — a consulta que vale (a
    // última) é a da Leitura.
    await waitFor(() => {
      const chamadas = chamadasRanking();
      expect(parametros(chamadas[chamadas.length - 1]).get("dimensao")).toBe("leitura");
    });
  });

  it("ao escolher um período, mantém a classificação do ano e aponta para a aba Evolução", async () => {
    mockarRanking();
    const u = userEvent.setup();
    renderComApp(<RankingGeral />, opcoes);

    await screen.findByRole("link", { name: "Ana Leitora" });
    expect(screen.queryByText(/A classificação por período fica na aba Evolução/)).not.toBeInTheDocument();

    await u.selectOptions(screen.getByLabelText("Período de análise"), "hoje");

    expect(await screen.findByText(/A classificação por período fica na aba Evolução/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Ver a aba Evolução/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Ana Leitora" })).toBeInTheDocument();
    expect(api.mock.calls.some((c) => String(c[0]).includes("/ranking-evolucao"))).toBe(false);
  });

  it("turma e turno vão para a consulta da matéria (com a dimensão junto)", async () => {
    mockarRanking();
    const u = userEvent.setup();
    renderComApp(<RankingGeral />, opcoes);
    await screen.findByRole("link", { name: "Ana Leitora" });

    await u.selectOptions(screen.getByLabelText("Filtrar por turma ou série"), "turma:1");
    expect(await screen.findByRole("link", { name: "Aluna Da Turma A" })).toBeInTheDocument();
    expect(chamadasRanking().some((p) =>
      parametros(p).get("turma_id") === "1" && parametros(p).get("dimensao") === "leitura")).toBe(true);

    await u.selectOptions(screen.getByLabelText("Filtrar por turma ou série"), "");
    const turno = await screen.findByLabelText("Turno");
    await u.selectOptions(turno, "tarde");
    expect(await screen.findByRole("link", { name: "Aluno Da Tarde" })).toBeInTheDocument();
    expect(chamadasRanking().some((p) =>
      parametros(p).get("turno") === "tarde" && parametros(p).get("dimensao") === "leitura")).toBe(true);
  });

  it("gestão: o cartaz GERAL continua baixando /ranking/cartaz; professor não vê o botão", async () => {
    mockarRanking();
    const u = userEvent.setup();
    const { unmount } = renderComApp(<RankingGeral />, opcoes);
    await screen.findByRole("link", { name: "Ana Leitora" });

    await u.click(screen.getByRole("button", { name: "Baixar cartaz geral" }));
    expect(apiDownload).toHaveBeenCalledWith("/escolas/1/ranking/cartaz");
    unmount();

    mockarRanking();
    renderComApp(<RankingGeral />, { ...opcoes, usuario: usuarioFake({ cargo: "professor" }) });
    await screen.findByRole("link", { name: "Ana Leitora" });
    expect(screen.queryByRole("button", { name: /Baixar cartaz/ })).not.toBeInTheDocument();
  });

  it("Admin Global numa escola cuja rede só contratou Matemática: abre na Matemática, sem o 403 da Leitura", async () => {
    // O /auth/me do global traz o catálogo inteiro; a escola, só Matemática. A
    // API recusa a Leitura dessa escola com 403 (como `_exigir_dimensao`).
    responder("GET", URL_TURMAS, [turmaFake()]);
    responder("GET", URL_RANKING, (caminho: string) =>
      parametros(caminho).get("dimensao") === "matematica"
        ? [itemDimensao({ aluno_id: 30, nome: "Davi Contas", dimensao: "matematica", nota: 88, n_aferidos: 1 })]
        : new ApiError(403, "O módulo Leitura não faz parte do plano desta rede."));
    responder("GET", URL_NAO_AFERIDOS, {
      contratadas: ["matematica"], total_alunos: 1, dimensoes: [], sem_nenhuma: [],
    });
    renderComApp(<RankingGeral />, {
      ...opcoes,
      usuario: usuarioFake({ cargo: "admin", is_global: true, escola_id: null,
                             modulos: ["leitura", "matematica"] }),
      escolas: [escolaComContrato(["matematica"])],
    });

    expect(await screen.findByRole("link", { name: "Davi Contas" })).toBeInTheDocument();
    expect(screen.getByText("Classificação oficial — Matemática")).toBeInTheDocument();
    // Uma matéria só no plano da escola: não há o que escolher.
    expect(screen.queryByLabelText("Matéria")).not.toBeInTheDocument();
    expect(screen.queryByText("Não foi possível carregar a classificação oficial")).not.toBeInTheDocument();
    // Estado final: a consulta que vale é a da Matemática (há um render antes
    // da sessão abrir, sem a guarda do App — ver o teste "rede só com Leitura").
    await waitFor(() => {
      const chamadas = chamadasRanking();
      expect(parametros(chamadas[chamadas.length - 1]).get("dimensao")).toBe("matematica");
    });
  });

  it("gestão com turma e sem turno: conta quantos o filtro mostra e diz que a posição é entre os aferidos da escola", async () => {
    responder("GET", URL_TURMAS, [turmaFake({ id: 1, nome: "3º Ano A", turno: "manha" })]);
    responder("GET", URL_RANKING, (caminho: string) =>
      parametros(caminho).get("turma_id") === "1"
        // Sem turno, a gestão recebe a posição CARIMBADA da escola (7º, 12º) e o
        // denominador da escola inteira (40): o "40" não pode se passar pelo
        // tamanho desta lista.
        ? [itemDimensao({ posicao: 7, aluno_id: 20, nome: "Aluno Da Turma A", n_aferidos: 40 }),
           itemDimensao({ posicao: 12, aluno_id: 21, nome: "Outro Da Turma A", n_aferidos: 40 })]
        : [itemDimensao({ n_aferidos: 40 })]);
    responder("GET", URL_NAO_AFERIDOS, { contratadas: ["leitura"], total_alunos: 40, dimensoes: [], sem_nenhuma: [] });
    const u = userEvent.setup();
    renderComApp(<RankingGeral />, opcoes);

    await screen.findByRole("link", { name: "Ana Leitora" });
    expect(screen.getByText("40 alunos aferidos em Leitura")).toBeInTheDocument();

    await u.selectOptions(screen.getByLabelText("Filtrar por turma ou série"), "turma:1");
    expect(await screen.findByRole("link", { name: "Aluno Da Turma A" })).toBeInTheDocument();
    expect(screen.getByText("7º")).toBeInTheDocument();
    expect(screen.getByText(
      "2 alunos aferidos em Leitura neste filtro · posição entre os 40 aferidos da escola",
    )).toBeInTheDocument();
    expect(screen.queryByText("40 alunos aferidos em Leitura")).not.toBeInTheDocument();
  });

  it("professor com turma: a lista já vem renumerada nas turmas dele, sem o sufixo da escola", async () => {
    responder("GET", URL_TURMAS, [turmaFake({ id: 1, nome: "3º Ano A", turno: "manha" })]);
    responder("GET", URL_RANKING, (caminho: string) =>
      parametros(caminho).get("turma_id") === "1"
        ? [itemDimensao({ posicao: 1, aluno_id: 20, nome: "Aluno Da Turma A", n_aferidos: 2 }),
           itemDimensao({ posicao: 2, aluno_id: 21, nome: "Outro Da Turma A", n_aferidos: 2 })]
        : [itemDimensao({ n_aferidos: 1 })]);
    responder("GET", URL_NAO_AFERIDOS, { contratadas: ["leitura"], total_alunos: 2, dimensoes: [], sem_nenhuma: [] });
    const u = userEvent.setup();
    renderComApp(<RankingGeral />, { ...opcoes, usuario: usuarioFake({ cargo: "professor" }) });

    await screen.findByRole("link", { name: "Ana Leitora" });
    await u.selectOptions(screen.getByLabelText("Filtrar por turma ou série"), "turma:1");
    expect(await screen.findByRole("link", { name: "Aluno Da Turma A" })).toBeInTheDocument();
    expect(screen.getByText("2 alunos aferidos em Leitura neste filtro")).toBeInTheDocument();
    expect(screen.queryByText(/posição entre/)).not.toBeInTheDocument();
  });

  it("série: ano_escolar vai para as duas consultas da matéria, e a contagem é a do filtro", async () => {
    responder("GET", URL_TURMAS, [
      turmaFake({ id: 1, nome: "1º Ano A", ano_escolar: "1º Ano" }),
      turmaFake({ id: 2, nome: "1º Ano B", ano_escolar: "1º Ano" }),
    ]);
    responder("GET", URL_RANKING, (caminho: string) =>
      parametros(caminho).get("ano_escolar") === "1º Ano"
        ? [itemDimensao({ posicao: 3, aluno_id: 30, nome: "Aluno Da Serie", n_aferidos: 9 })]
        : [itemDimensao({ n_aferidos: 9 })]);
    responder("GET", URL_NAO_AFERIDOS, { contratadas: ["leitura"], total_alunos: 9, dimensoes: [], sem_nenhuma: [] });
    const u = userEvent.setup();
    renderComApp(<RankingGeral />, opcoes);

    await screen.findByRole("link", { name: "Ana Leitora" });
    await u.selectOptions(screen.getByLabelText("Filtrar por turma ou série"), "serie:1º Ano");

    expect(await screen.findByRole("link", { name: "Aluno Da Serie" })).toBeInTheDocument();
    expect(chamadasRanking().some((p) =>
      parametros(p).get("ano_escolar") === "1º Ano" && parametros(p).get("dimensao") === "leitura")).toBe(true);
    const naoAferidos = api.mock.calls.map((c) => String(c[0]))
      .filter((p) => p.startsWith(`${URL_NAO_AFERIDOS}?`));
    expect(naoAferidos.some((p) => parametros(p).get("ano_escolar") === "1º Ano")).toBe(true);
    expect(screen.getByText(
      "1 aluno aferido em Leitura neste filtro · posição entre os 9 aferidos da escola",
    )).toBeInTheDocument();
  });

  it("turno: Tarde e 'Sem turno' (turno= vazio) vão para a consulta e a contagem diz o recorte", async () => {
    responder("GET", URL_TURMAS, [
      turmaFake({ id: 1, nome: "3º Ano A", turno: "manha" }),
      turmaFake({ id: 2, nome: "3º Ano B", turno: "tarde" }),
      turmaFake({ id: 3, nome: "3º Ano C", turno: null }),
    ]);
    responder("GET", URL_RANKING, (caminho: string) => {
      const q = parametros(caminho);
      if (q.get("turno") === "tarde") return [itemDimensao({ aluno_id: 20, nome: "Aluno Da Tarde", n_aferidos: 1 })];
      if (q.get("turno") === "") return [itemDimensao({ aluno_id: 30, nome: "Aluno Sem Turno", n_aferidos: 1 })];
      return [itemDimensao({ n_aferidos: 3 })];
    });
    responder("GET", URL_NAO_AFERIDOS, { contratadas: ["leitura"], total_alunos: 3, dimensoes: [], sem_nenhuma: [] });
    const u = userEvent.setup();
    renderComApp(<RankingGeral />, opcoes);

    await screen.findByRole("link", { name: "Ana Leitora" });
    expect(chamadasRanking().some((p) => parametros(p).has("turno"))).toBe(false);
    expect(screen.getByText("3 alunos aferidos em Leitura")).toBeInTheDocument();

    const seletor = await screen.findByLabelText("Turno");
    await u.selectOptions(seletor, "tarde");
    expect(await screen.findByRole("link", { name: "Aluno Da Tarde" })).toBeInTheDocument();
    expect(screen.getByText("1 aluno aferido em Leitura no turno Tarde")).toBeInTheDocument();

    // "Sem turno" vai como turno= (vazio) — e não vira "no turno Sem turno".
    await u.selectOptions(seletor, "");
    expect(await screen.findByRole("link", { name: "Aluno Sem Turno" })).toBeInTheDocument();
    await waitFor(() => expect(chamadasRanking().some((p) =>
      parametros(p).get("turno") === "" && parametros(p).get("dimensao") === "leitura")).toBe(true));
    expect(screen.getByText("1 aluno aferido em Leitura em turmas sem turno")).toBeInTheDocument();

    // Turno + turma: a contagem é do recorte inteiro (a turma dentro do turno).
    await u.selectOptions(screen.getByLabelText("Filtrar por turma ou série"), "turma:3");
    expect(await screen.findByText("1 aluno aferido em Leitura neste filtro, em turmas sem turno"))
      .toBeInTheDocument();
  });

  it("falha da classificação: mostra o erro e 'Tentar de novo' refaz a consulta", async () => {
    responder("GET", URL_TURMAS, [turmaFake()]);
    responderErro("GET", URL_RANKING, 500, "Erro interno");
    responder("GET", URL_NAO_AFERIDOS, { contratadas: ["leitura"], total_alunos: 0, dimensoes: [], sem_nenhuma: [] });
    const u = userEvent.setup();
    renderComApp(<RankingGeral />, opcoes);

    expect(await screen.findByText("Não foi possível carregar a classificação oficial")).toBeInTheDocument();
    expect(screen.getByText("Erro interno")).toBeInTheDocument();

    responder("GET", URL_RANKING, [itemDimensao()]);
    await u.click(screen.getByRole("button", { name: "Tentar de novo" }));
    expect(await screen.findByRole("link", { name: "Ana Leitora" })).toBeInTheDocument();
  });
});
