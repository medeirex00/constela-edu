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
 *      cartaz padrão vira é decisão própria do dono (plano, item 8).
 */
import { describe, expect, it } from "vitest";

import type { RankingItem } from "../lib/types";
import RankingGeral from "../pages/RankingGeral";
import {
  api,
  apiDownload,
  rankingItemFake,
  renderComApp,
  responder,
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
});
