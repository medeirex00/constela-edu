/**
 * Ranking de TURMAS: a ORDEM e a POSIÇÃO vêm do backend
 * (`GET /escolas/{id}/ranking/turmas`) e a tela só exibe — nada é reordenado
 * nem renumerado no navegador (antes eram duas ordens: a do cliente, com
 * `localeCompare`, e a convenção do backend). A matéria e o turno global vão
 * na query; só o módulo contratado aparece; o selo diz de quando é o dado.
 */
import { describe, expect, it } from "vitest";

import { api } from "../lib/api";
import RankingTurmas from "../pages/RankingTurmas";
import type { Turma } from "../lib/types";
import { renderComApp, responder, screen, turmaFake, userEvent, usuarioFake, within } from "./utils";

const URL_TURMAS = "/escolas/1/turmas";
const URL_RANKING = "/escolas/1/ranking/turmas";

const turmas: Turma[] = [
  turmaFake({ id: 1, nome: "3º Ano A", ano_escolar: "3º Ano", turno: "manha" }),
  turmaFake({ id: 2, nome: "3º Ano B", ano_escolar: "3º Ano", turno: "tarde" }),
  turmaFake({ id: 3, nome: "4º Ano A", ano_escolar: "4º Ano", turno: "manha" }),
];

function bloco(over: Record<string, unknown> = {}) {
  return {
    plataforma: "elefante", contratada: true, estado: "em_dia",
    dado_mais_recente_em: "2026-10-19", dado_mais_antigo_em: "2026-10-19",
    dias_desde_dado: 1, alunos_com_dado: 30, alunos_com_dado_antigo: 0,
    ultima_sincronizacao_ok_em: "2026-10-19T06:10:00", dias_desde_sincronizacao_ok: 1,
    ...over,
  };
}

function frescor(leitura: Record<string, unknown> = {}, matematica: Record<string, unknown> = {}) {
  return {
    limite_dias: 7, hoje: "2026-10-20", estado: "em_dia",
    dimensoes: {
      leitura: bloco(leitura),
      matematica: bloco({ plataforma: "matific", ...matematica }),
    },
  };
}

function item(posicao: number, id: number, nome: string, over: Record<string, unknown> = {}) {
  return {
    posicao, turma_id: id, nome, ano_escolar: "3º Ano", turno: "manha",
    media: 70, n_aferidos: 10, total_alunos: 20, ...over,
  };
}

/** Nomes das turmas na ordem em que aparecem na tabela. */
function ordem(): string[] {
  return within(screen.getByRole("table")).getAllByRole("link").map((l) => l.textContent ?? "");
}

function chamadas(): string[] {
  return (api as unknown as { mock: { calls: unknown[][] } }).mock.calls
    .map((c) => String(c[0])).filter((u) => u.startsWith(URL_RANKING));
}

describe("Ranking de Turmas", () => {
  it("exibe a ordem e a posição da API sem reordenar (empate decidido pelo backend)", async () => {
    responder("GET", URL_TURMAS, turmas);
    // Empate de média e de aferidos entre "Bosque" e "árvore": o backend decide
    // pelo nome em casefold ("bosque" antes de "árvore"); o `localeCompare` do
    // navegador inverteria. A tela tem de mostrar a ordem que recebeu.
    responder("GET", URL_RANKING, {
      dimensao: "leitura",
      itens: [
        item(1, 2, "Duna", { media: 95, n_aferidos: 1, total_alunos: 2, turno: "tarde" }),
        item(2, 4, "Bosque", { media: 80, n_aferidos: 1 }),
        item(3, 5, "árvore", { media: 80, n_aferidos: 1 }),
      ],
      frescor: frescor(),
    });
    renderComApp(<RankingTurmas />, { rota: "/ranking?ver=turmas" });

    expect(await screen.findByRole("link", { name: "Duna" })).toBeInTheDocument();
    expect(ordem()).toEqual(["Duna", "Bosque", "árvore"]);
    expect(screen.getByText("1º")).toBeInTheDocument();
    expect(screen.getByText("2º")).toBeInTheDocument();
    expect(screen.getByText("3º")).toBeInTheDocument();
    expect(screen.getByText("95,0")).toBeInTheDocument();
    for (const coluna of ["Posição", "Turma", "Série", "Turno", "Média de Leitura", "Alunos aferidos"]) {
      expect(screen.getByRole("columnheader", { name: coluna })).toBeInTheDocument();
    }
    expect(screen.getByText("1 de 2")).toBeInTheDocument();
    expect(within(screen.getByRole("table")).getByText("Tarde")).toBeInTheDocument();
    expect(screen.getAllByText(/média das notas oficiais/i).length).toBeGreaterThan(0);
    expect(chamadas()[0]).toBe(`${URL_RANKING}?dimensao=leitura`);
  });

  it("troca a matéria: pede a Matemática à API", async () => {
    responder("GET", URL_TURMAS, turmas);
    responder("GET", URL_RANKING, (caminho: string) => ({
      dimensao: caminho.includes("matematica") ? "matematica" : "leitura",
      itens: caminho.includes("matematica")
        ? [item(1, 3, "4º Ano A", { media: 90 }), item(2, 1, "3º Ano A", { media: 55 })]
        : [item(1, 2, "3º Ano B", { media: 85 }), item(2, 1, "3º Ano A")],
      frescor: frescor(),
    }));
    const u = userEvent.setup();
    renderComApp(<RankingTurmas />, { rota: "/ranking?ver=turmas" });

    await screen.findByRole("link", { name: "3º Ano B" });
    await u.selectOptions(screen.getByLabelText("Matéria"), "matematica");

    expect(await screen.findByRole("link", { name: "4º Ano A" })).toBeInTheDocument();
    expect(ordem()).toEqual(["4º Ano A", "3º Ano A"]);
    expect(screen.getByRole("columnheader", { name: "Média de Matemática" })).toBeInTheDocument();
    expect(chamadas()).toContain(`${URL_RANKING}?dimensao=matematica`);
  });

  it("manda o turno global para a API (que recorta e renumera)", async () => {
    responder("GET", URL_TURMAS, turmas);
    responder("GET", URL_RANKING, (caminho: string) => ({
      dimensao: "leitura",
      itens: caminho.includes("turno=tarde")
        ? [item(1, 2, "3º Ano B", { turno: "tarde" })]
        : [item(1, 1, "3º Ano A")],
      frescor: frescor(),
    }));
    const u = userEvent.setup();
    renderComApp(<RankingTurmas />, { rota: "/ranking?ver=turmas", turno: "manha" });

    expect(await screen.findByRole("link", { name: "3º Ano A" })).toBeInTheDocument();
    expect(chamadas()).toContain(`${URL_RANKING}?dimensao=leitura&turno=manha`);

    await u.selectOptions(screen.getByLabelText("Turno"), "tarde");
    expect(await screen.findByRole("link", { name: "3º Ano B" })).toBeInTheDocument();
    expect(ordem()).toEqual(["3º Ano B"]);
  });

  it("estado vazio quando nenhuma turma tem aluno aferido na matéria", async () => {
    responder("GET", URL_TURMAS, turmas);
    responder("GET", URL_RANKING, {
      dimensao: "leitura", itens: [], frescor: frescor({ estado: "sem_dados",
        dado_mais_recente_em: null, alunos_com_dado: 0 }),
    });
    renderComApp(<RankingTurmas />, { rota: "/ranking?ver=turmas" });

    expect(await screen.findByText("Nenhuma turma com alunos aferidos em Leitura")).toBeInTheDocument();
    // Sem dado é "sem dados" — nunca uma data inventada nem zero.
    expect(screen.getByText(/Leitura \(Elefante Letrado\): sem dados ainda/)).toBeInTheDocument();
  });

  it("rede só com Leitura: não há seletor de matéria", async () => {
    responder("GET", URL_TURMAS, turmas);
    responder("GET", URL_RANKING, {
      dimensao: "leitura", itens: [item(1, 2, "3º Ano B")], frescor: frescor(),
    });
    renderComApp(<RankingTurmas />, {
      rota: "/ranking?ver=turmas",
      usuario: usuarioFake({ modulos: ["leitura"] }),
    });

    expect(await screen.findByRole("link", { name: "3º Ano B" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Matéria")).not.toBeInTheDocument();
  });

  it("selo com a data do dado e aviso quando passou do limite", async () => {
    responder("GET", URL_TURMAS, turmas);
    responder("GET", URL_RANKING, {
      dimensao: "leitura", itens: [item(1, 1, "3º Ano A")],
      frescor: frescor({ estado: "desatualizado", dado_mais_recente_em: "2026-10-01",
        dias_desde_dado: 19 }),
    });
    renderComApp(<RankingTurmas />, { rota: "/ranking?ver=turmas" });

    expect(await screen.findByText(/Leitura \(Elefante Letrado\): dados de 01\/10\/2026/))
      .toBeInTheDocument();
    const aviso = screen.getByRole("status");
    // O limite vem da resposta e nomeia o aviso ("Dados desatualizados" é a
    // palavra da tela Integrações, com outra régua).
    expect(aviso).toHaveTextContent(/Dado com mais de 7 dias/);
    expect(aviso).toHaveTextContent(/há 19 dias/);
    expect(screen.queryByText(/Funcionando/i)).not.toBeInTheDocument();
  });

  it("turma, série e turno ficam numa linha só; a barra dos aferidos é neutra (o âmbar é da premiação)", async () => {
    responder("GET", URL_TURMAS, turmas);
    responder("GET", URL_RANKING, {
      dimensao: "leitura",
      itens: [item(1, 1, "3º Ano A", { turno: null, n_aferidos: 5, total_alunos: 5 })],
      frescor: frescor(),
    });
    renderComApp(<RankingTurmas />, { rota: "/ranking?ver=turmas" });

    const link = await screen.findByRole("link", { name: "3º Ano A" });
    const linha = link.closest("tr") as HTMLElement;
    expect(link.closest("td")).toHaveClass("whitespace-nowrap");
    expect(within(linha).getByText("3º Ano")).toHaveClass("whitespace-nowrap");
    expect(within(linha).getByText("Sem turno").closest("td")).toHaveClass("whitespace-nowrap");
    // O número continua ao lado da barra (a barra é só reforço visual).
    expect(within(linha).getByText("5 de 5")).toBeInTheDocument();
    expect(linha.querySelector(".bg-slate-500")).not.toBeNull();
    expect(linha.querySelector("[class*='from-ouro']")).toBeNull();
  });
});

describe("Ranking de Turmas — Secretaria", () => {
  const SECRETARIA = usuarioFake({ nome: "Secretaria", cargo: "coordenador", rede_id: 1, escola_id: null });
  const TEXTO = "Menos de 3 alunos com dado nesta matéria: para proteger as crianças, a média e os totais da turma não aparecem.";

  it("turma protegida fica fora da ordem, sem posição nem média, com o motivo; nome sem link", async () => {
    responder("GET", URL_TURMAS, turmas);
    responder("GET", URL_RANKING, {
      dimensao: "leitura",
      itens: [item(1, 1, "3º Ano A"), item(2, 2, "3º Ano B", { media: 60 })],
      ocultas: [{ turma_id: 3, nome: "4º Ano A", ano_escolar: "4º Ano", turno: "manha", media: null, posicao: null,
                  n_aferidos: 1, total_alunos: 20, grupo_pequeno: true, motivo: "grupo_pequeno", texto: TEXTO }],
      frescor: frescor(),
    });
    renderComApp(<RankingTurmas />, { rota: "/rede/ranking?ver=turmas", usuario: SECRETARIA, escolaSelecionada: 1 });

    expect(await screen.findByText("Fora do ranking para proteger as crianças")).toBeInTheDocument();
    const lista = screen.getByRole("list", { name: "Turmas protegidas" });
    expect(within(lista).getByText("4º Ano A")).toBeInTheDocument();
    expect(within(lista).getByText(new RegExp(TEXTO.slice(0, 30)))).toBeInTheDocument();
    // A turma protegida não está na tabela (nem com posição, nem com média).
    const tabela = screen.getByRole("table");
    expect(within(tabela).queryByText("4º Ano A")).toBeNull();
    // A Secretaria não abre o detalhe da turma: o nome não é link (era um link morto).
    expect(within(tabela).queryAllByRole("link")).toHaveLength(0);
    expect(within(tabela).getByText("3º Ano A")).toBeInTheDocument();
  });

  it("todas as turmas protegidas: diz por quê, sem o 'nenhuma turma com alunos aferidos'", async () => {
    responder("GET", URL_TURMAS, turmas);
    responder("GET", URL_RANKING, {
      dimensao: "leitura",
      itens: [],
      ocultas: [{ turma_id: 3, nome: "4º Ano A", ano_escolar: "4º Ano", turno: "manha", media: null, posicao: null,
                  n_aferidos: 2, total_alunos: 20, grupo_pequeno: true, motivo: "grupo_pequeno", texto: TEXTO }],
      frescor: frescor(),
    });
    renderComApp(<RankingTurmas />, { rota: "/rede/ranking?ver=turmas", usuario: SECRETARIA, escolaSelecionada: 1 });

    expect(await screen.findByText("Fora do ranking para proteger as crianças")).toBeInTheDocument();
    expect(screen.queryByText(/Nenhuma turma com alunos aferidos/)).toBeNull();
  });
});
