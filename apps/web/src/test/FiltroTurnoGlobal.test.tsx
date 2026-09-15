/**
 * Filtro de TURNO global "lockado" (modelo: FiltroPeriodoGlobal): a escolha do
 * usuário (ex.: "Manhã") tem de ACOMPANHAR a navegação entre as abas de ranking
 * e as Premiações, e sobreviver ao reload — o turno vive no AppContext
 * (persistido em localStorage na chave `sgpe_turno`, SEPARADA da do período).
 * Trocar o período não mexe no turno, e vice-versa.
 */
import { describe, expect, it } from "vitest";

import Premiacoes from "../pages/Premiacoes";
import Rankings from "../pages/Rankings";
import type { CategoriaPremiacao, RankingItem, Turma } from "../lib/types";
import {
  api, rankingItemFake, renderComApp, responder, screen, turmaFake, userEvent, waitFor, within,
} from "./utils";

const URL_TURMAS = "/escolas/1/turmas";
const URL_GERAL = "/escolas/1/ranking";
const URL_NAO_AFERIDOS = "/escolas/1/nao-aferidos";
const URL_LEITURA = "/escolas/1/ranking/leitura";
const URL_TURNOS = "/escolas/1/ranking/leitura/turnos";
const URL_PREM = "/escolas/1/premiacoes";
const URL_EVOL = "/escolas/1/ranking-evolucao";

const turmas: Turma[] = [
  turmaFake({ id: 1, nome: "3º Ano A", turno: "manha" }),
  turmaFake({ id: 2, nome: "3º Ano B", turno: "tarde" }),
];

const turnoDe = (caminho: string) =>
  new URLSearchParams(caminho.split("?")[1] ?? "").get("turno");

/** Caminhos com que `prefixo` foi chamado (com ou sem query). */
const chamadas = (prefixo: string) =>
  api.mock.calls.map((c) => String(c[0])).filter((p) => p === prefixo || p.startsWith(`${prefixo}?`));

function mockarRankings() {
  responder("GET", URL_TURMAS, turmas);
  responder("GET", URL_GERAL, (caminho: string) =>
    turnoDe(caminho) === "manha"
      ? [rankingItemFake({ aluno_id: 20, nome: "Aluno Da Manha", n_aferidos: 1 })]
      : [rankingItemFake({ aluno_id: 10, nome: "Ana Beatriz Souza", n_aferidos: 2 })] as RankingItem[]);
  responder("GET", URL_NAO_AFERIDOS, {
    contratadas: ["leitura", "matematica"], total_alunos: 2, dimensoes: [], sem_nenhuma: [],
  });
  responder("GET", URL_LEITURA, []);
  responder("GET", URL_TURNOS, []);
}

function cat(chave: string, titulo: string, nome: string): CategoriaPremiacao {
  return {
    chave, titulo, icone: "🧮", descricao: "d", unidade: "nota",
    podio: [{ posicao: 1, aluno_id: 1, nome, turma: "3A", valor: 80 }],
  };
}
function mockarPremiacoes() {
  responder("GET", URL_TURMAS, turmas);
  responder("GET", URL_PREM, {
    periodo: { chave: "ano_letivo", rotulo: "Ano letivo", inicio: null, fim: null },
    categorias: [cat("melhor_matematica", "Melhor Matemática", "Mat Todos")],
    turnos: [
      { turno: "manha", turno_rotulo: "Manhã", total: 1,
        categorias: [cat("melhor_matematica", "Melhor Matemática", "Mat Manha")] },
      { turno: "tarde", turno_rotulo: "Tarde", total: 1,
        categorias: [cat("melhor_matematica", "Melhor Matemática", "Mat Tarde")] },
    ],
  });
  responder("GET", URL_EVOL, []);
}

async function escolherManha(u: ReturnType<typeof userEvent.setup>) {
  const seletor = await screen.findByLabelText("Turno");
  await within(seletor).findByRole("option", { name: "Manhã" });
  await u.selectOptions(seletor, "manha");
  expect(await screen.findByRole("link", { name: /Aluno Da Manha/ })).toBeInTheDocument();
}

describe("Filtro de turno global (lockado)", () => {
  it("escolher Manhã no Ranking Geral refaz /ranking com turno=manha; a aba Leitura consulta /ranking e /nao-aferidos com o mesmo turno", async () => {
    mockarRankings();
    const u = userEvent.setup();
    renderComApp(<Rankings />, { rota: "/ranking" });

    // Sem turno: o parâmetro não vai.
    expect(await screen.findByRole("link", { name: /Ana Beatriz Souza/ })).toBeInTheDocument();
    expect(chamadas(URL_GERAL).every((p) => turnoDe(p) === null)).toBe(true);

    await escolherManha(u);
    expect(chamadas(URL_GERAL).some((p) => turnoDe(p) === "manha")).toBe(true);
    expect(screen.queryByRole("link", { name: /Ana Beatriz Souza/ })).not.toBeInTheDocument();

    // A aba Leitura (classificação oficial) herda o turno nas DUAS consultas.
    await u.click(screen.getByRole("tab", { name: "Leitura" }));
    await waitFor(() => {
      expect(chamadas(URL_GERAL).some((p) =>
        p.includes("dimensao=leitura") && turnoDe(p) === "manha")).toBe(true);
      expect(chamadas(URL_NAO_AFERIDOS).some((p) => turnoDe(p) === "manha")).toBe(true);
    });
    // E o ranking do período de leitura também.
    await waitFor(() => expect(chamadas(URL_LEITURA).some((p) => turnoDe(p) === "manha")).toBe(true));
    // O seletor da nova aba já vem com "Manhã".
    expect((screen.getByLabelText("Turno") as HTMLSelectElement).value).toBe("manha");
  });

  it("a aba Evolução herda 'Manhã': /ranking-evolucao com turno=manha e o seletor já em 'manha'", async () => {
    mockarRankings();
    responder("GET", URL_EVOL, []);
    const u = userEvent.setup();
    renderComApp(<Rankings />, { rota: "/ranking" });
    await screen.findByRole("link", { name: /Ana Beatriz Souza/ });
    await escolherManha(u);

    await u.click(screen.getByRole("tab", { name: "Evolução" }));
    await waitFor(() => expect(chamadas(URL_EVOL).some((p) => turnoDe(p) === "manha")).toBe(true));
    // Nenhuma consulta da Evolução sai sem o turno escolhido.
    expect(chamadas(URL_EVOL).every((p) => turnoDe(p) === "manha")).toBe(true);
    expect((screen.getByLabelText("Turno") as HTMLSelectElement).value).toBe("manha");
  });

  it("navegar para Premiações mantém 'Manhã' (mesmo contexto, sem re-escolher)", async () => {
    mockarRankings();
    const u = userEvent.setup();
    const { unmount } = renderComApp(<Rankings />, { rota: "/ranking" });
    await screen.findByRole("link", { name: /Ana Beatriz Souza/ });
    await escolherManha(u);
    unmount();

    // Outra tela, nova montagem do contexto: lê o turno guardado.
    mockarPremiacoes();
    renderComApp(<Premiacoes />, { rota: "/premiacoes" });
    expect(await screen.findByText("Mat Manha")).toBeInTheDocument();
    expect(screen.queryByText("Mat Todos")).not.toBeInTheDocument();
    const seletor = screen.getByLabelText("Turno");
    await waitFor(() => expect((seletor as HTMLSelectElement).value).toBe("manha"));
  });

  it("persiste no localStorage (sgpe_turno) e SOBREVIVE AO RELOAD", async () => {
    mockarRankings();
    const u = userEvent.setup();
    const { unmount } = renderComApp(<Rankings />, { rota: "/ranking" });
    await screen.findByRole("link", { name: /Ana Beatriz Souza/ });
    await escolherManha(u);

    // Chave PRÓPRIA do turno — o período tem a dele.
    expect(localStorage.getItem("sgpe_turno")).toBe("manha");

    // "Reload": desmonta e monta de novo SEM semear turno — o contexto lê o
    // valor salvo e já consulta com turno=manha.
    unmount();
    api.mockClear();
    renderComApp(<Rankings />, { rota: "/ranking" });
    expect(await screen.findByRole("link", { name: /Aluno Da Manha/ })).toBeInTheDocument();
    expect(chamadas(URL_GERAL).some((p) => turnoDe(p) === "manha")).toBe(true);
    const seletor = screen.getByLabelText("Turno");
    await waitFor(() => expect((seletor as HTMLSelectElement).value).toBe("manha"));
  });

  it("trocar o período não zera o turno, e trocar o turno não zera o período", async () => {
    mockarRankings();
    const u = userEvent.setup();
    renderComApp(<Rankings />, { rota: "/ranking" });
    await screen.findByRole("link", { name: /Ana Beatriz Souza/ });
    await escolherManha(u);

    // Período → "Este mês": o turno continua "Manhã" (e guardado).
    await u.selectOptions(screen.getByLabelText("Período de análise"), "mes");
    expect(await screen.findByText(/A classificação por período fica na aba Evolução/)).toBeInTheDocument();
    expect((screen.getByLabelText("Turno") as HTMLSelectElement).value).toBe("manha");
    expect(localStorage.getItem("sgpe_turno")).toBe("manha");
    expect(JSON.parse(localStorage.getItem("sgpe_periodo") ?? "{}")).toMatchObject({ preset: "mes" });

    // Turno → "Todos": o período continua "Este mês".
    await u.selectOptions(screen.getByLabelText("Turno"), "todos");
    expect(await screen.findByRole("link", { name: /Ana Beatriz Souza/ })).toBeInTheDocument();
    expect((screen.getByLabelText("Período de análise") as HTMLSelectElement).value).toBe("mes");
    expect(JSON.parse(localStorage.getItem("sgpe_periodo") ?? "{}")).toMatchObject({ preset: "mes" });
    expect(localStorage.getItem("sgpe_turno")).toBe("todos");
  });

  it("turno guardado que não existe nesta escola conta como 'Todos' na consulta, sem apagar a escolha", async () => {
    mockarRankings();
    renderComApp(<Rankings />, { rota: "/ranking", turno: "noite" });

    // Consulta como "todos" (a escola não tem turno da noite): assim que as
    // turmas chegam, a consulta vai SEM o parâmetro e o seletor mostra "Todos".
    expect(await screen.findByRole("link", { name: /Ana Beatriz Souza/ })).toBeInTheDocument();
    const seletor = screen.getByLabelText("Turno");
    await within(seletor).findByRole("option", { name: "Tarde" });
    await waitFor(() => expect(chamadas(URL_GERAL).some((p) => turnoDe(p) === null)).toBe(true));
    await waitFor(() => expect((seletor as HTMLSelectElement).value).toBe("todos"));
    expect(within(seletor).queryByRole("option", { name: "Noite" })).not.toBeInTheDocument();
    // ...mas o que está guardado NÃO foi sobrescrito.
    expect(localStorage.getItem("sgpe_turno")).toBe("noite");
  });
});
