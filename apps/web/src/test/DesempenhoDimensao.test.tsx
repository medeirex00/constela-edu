/**
 * Classificação OFICIAL por matéria (`components/DesempenhoDimensao`), o topo
 * das abas Leitura e Matemática:
 *   1. quem ainda não foi aferido aparece numa lista de AÇÃO (link para o
 *      aluno), sem nota e sem posição — nunca como 0,0 no fim do ranking;
 *   2. as duas consultas (`/ranking?dimensao=` e `/nao-aferidos`) recebem o
 *      MESMO turno global;
 *   3. o cartaz da matéria (gestão) baixa `/ranking/cartaz?dimensao=...` e fica
 *      desabilitado, com o motivo, quando há filtro aplicado ou a lista está
 *      vazia; professor não vê o botão.
 */
import { describe, expect, it } from "vitest";

import { DesempenhoDimensao } from "../components/DesempenhoDimensao";
import type { NaoAferidos, RankingItem } from "../lib/types";
import RankingLeitura from "../pages/RankingLeitura";
import {
  api, apiDownload, rankingItemFake, renderComApp, responder, screen, turmaFake, userEvent,
  usuarioFake, waitFor, within,
} from "./utils";

const URL_TURMAS = "/escolas/1/turmas";
const URL_RANKING = "/escolas/1/ranking";
const URL_NAO_AFERIDOS = "/escolas/1/nao-aferidos";

const turnoDe = (caminho: string) =>
  new URLSearchParams(caminho.split("?")[1] ?? "").get("turno");
/** Caminhos com que `prefixo` foi chamado (com ou sem query, nunca sub-caminhos). */
const chamadas = (prefixo: string) =>
  api.mock.calls.map((c) => String(c[0])).filter((p) => p === prefixo || p.startsWith(`${prefixo}?`));

/** Item do ranking POR DIMENSÃO, como a API carimba. */
function itemDimensao(over: Partial<RankingItem> = {}): RankingItem {
  return {
    ...rankingItemFake({ posicao: 1, aluno_id: 10, nome: "Ana Leitora" }),
    dimensao: "leitura", nota: 91, aferido: true, n_aferidos: 2,
    dados: { livros_unicos: 12, atividades: 30 }, adocao: 100,
    ...over,
  };
}

function naoAferidos(dimensao: "leitura" | "matematica" = "leitura"): NaoAferidos {
  return {
    contratadas: ["leitura", "matematica"],
    total_alunos: 3,
    dimensoes: [{
      dimensao, plataforma: "Elefante Letrado", n_aferidos: 2, total: 3,
      alunos: [{ aluno_id: 77, nome: "Bruno Sem Leitura", turma: "3º Ano A", ano_escolar: "3º Ano" }],
    }],
    sem_nenhuma: [],
  };
}

const SEM_FILTRO = { turno: "todos" };

describe("DesempenhoDimensao (classificação oficial por matéria)", () => {
  it("quem ainda não foi aferido aparece no bloco de ação, com link e sem nota nem posição", async () => {
    responder("GET", URL_RANKING, [
      itemDimensao(),
      itemDimensao({ posicao: 2, aluno_id: 11, nome: "Caio Leitor", nota: 74 }),
    ]);
    responder("GET", URL_NAO_AFERIDOS, naoAferidos());
    renderComApp(<DesempenhoDimensao dimensao="leitura" filtros={SEM_FILTRO} />);

    const titulo = await screen.findByRole("heading", { name: "Ainda não aferidos em Leitura (1)" });
    const bloco = titulo.closest(".card") as HTMLElement;
    const link = within(bloco).getByRole("link", { name: "Bruno Sem Leitura" });
    expect(link).toHaveAttribute("href", "/alunos/77");
    // Sem nota (nada de "0,0") e sem posição ("1º", "3º"...).
    expect(within(bloco).queryByText(/^\d+,\d$/)).not.toBeInTheDocument();
    expect(within(bloco).queryByText(/^\d+º$/)).not.toBeInTheDocument();
    // E fora da classificação: a tabela só tem os aferidos, com o denominador.
    const tabela = screen.getByRole("table");
    expect(within(tabela).queryByText("Bruno Sem Leitura")).not.toBeInTheDocument();
    expect(within(tabela).getByRole("link", { name: "Caio Leitor" })).toBeInTheDocument();
    expect(screen.getByText("2 alunos aferidos em Leitura")).toBeInTheDocument();
  });

  it("com o turno 'manha' guardado, /ranking?dimensao=leitura e /nao-aferidos vão com turno=manha", async () => {
    responder("GET", URL_TURMAS, [
      turmaFake({ id: 1, nome: "3º Ano A", turno: "manha" }),
      turmaFake({ id: 2, nome: "3º Ano B", turno: "tarde" }),
    ]);
    responder("GET", URL_RANKING, [itemDimensao()]);
    responder("GET", URL_NAO_AFERIDOS, naoAferidos());
    responder("GET", "/escolas/1/ranking/leitura", []);
    responder("GET", "/escolas/1/ranking/leitura/turnos", []);
    // A tela dona (Leitura) resolve o turno global e repassa por props.
    renderComApp(<RankingLeitura />, { rota: "/ranking-leitura", turno: "manha" });

    expect(await screen.findByRole("link", { name: "Ana Leitora" })).toBeInTheDocument();
    await waitFor(() => {
      expect(chamadas(URL_RANKING).some((p) =>
        p.includes("dimensao=leitura") && turnoDe(p) === "manha")).toBe(true);
      expect(chamadas(URL_NAO_AFERIDOS).some((p) => turnoDe(p) === "manha")).toBe(true);
    });
    // As duas metades do MESMO recorte: nenhuma consulta sem o turno.
    expect(chamadas(URL_RANKING).every((p) => turnoDe(p) === "manha")).toBe(true);
    expect(chamadas(URL_NAO_AFERIDOS).every((p) => turnoDe(p) === "manha")).toBe(true);
    // Com turno aplicado, o cartaz (escola inteira) fica desabilitado e diz por quê.
    const botao = screen.getByRole("button", { name: "Baixar cartaz de Leitura" });
    expect(botao).toBeDisabled();
    expect(botao).toHaveAttribute("title", expect.stringContaining("escola inteira"));
  });

  it("gestor: 'Baixar cartaz de Leitura' baixa o cartaz DA MATÉRIA (?dimensao=leitura)", async () => {
    responder("GET", URL_RANKING, [itemDimensao()]);
    responder("GET", URL_NAO_AFERIDOS, naoAferidos());
    const u = userEvent.setup();
    renderComApp(<DesempenhoDimensao dimensao="leitura" filtros={SEM_FILTRO} />);

    await screen.findByRole("link", { name: "Ana Leitora" });
    const botao = screen.getByRole("button", { name: "Baixar cartaz de Leitura" });
    expect(botao).toBeEnabled();
    await u.click(botao);
    expect(apiDownload).toHaveBeenCalledWith("/escolas/1/ranking/cartaz?dimensao=leitura");
  });

  it("cartaz desabilitado com turma aplicada: o cartaz é da escola inteira", async () => {
    responder("GET", URL_RANKING, [itemDimensao({ dimensao: "matematica", nome: "Davi Mat", nota: 88 })]);
    responder("GET", URL_NAO_AFERIDOS, naoAferidos("matematica"));
    renderComApp(<DesempenhoDimensao dimensao="matematica" filtros={{ turma_id: "1", turno: "todos" }} />);

    expect(await screen.findByRole("link", { name: "Davi Mat" })).toBeInTheDocument();
    const botao = screen.getByRole("button", { name: "Baixar cartaz de Matemática" });
    expect(botao).toBeDisabled();
    expect(botao).toHaveAttribute("title", expect.stringContaining("escola inteira"));
    expect(apiDownload).not.toHaveBeenCalled();
  });

  it("lista vazia desabilita o cartaz, com o motivo", async () => {
    responder("GET", URL_RANKING, []);
    responder("GET", URL_NAO_AFERIDOS, naoAferidos());
    renderComApp(<DesempenhoDimensao dimensao="leitura" filtros={SEM_FILTRO} />);

    expect(await screen.findByText("Nenhum aluno aferido em Leitura ainda")).toBeInTheDocument();
    const botao = screen.getByRole("button", { name: "Baixar cartaz de Leitura" });
    expect(botao).toBeDisabled();
    expect(botao).toHaveAttribute("title", "Ainda não há alunos aferidos em Leitura para o cartaz.");
  });

  it("professor não vê o botão do cartaz (documento de vitrine da gestão)", async () => {
    responder("GET", URL_RANKING, [itemDimensao()]);
    responder("GET", URL_NAO_AFERIDOS, naoAferidos());
    renderComApp(<DesempenhoDimensao dimensao="leitura" filtros={SEM_FILTRO} />, {
      usuario: usuarioFake({ cargo: "professor" }),
    });

    expect(await screen.findByRole("link", { name: "Ana Leitora" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Baixar cartaz/ })).not.toBeInTheDocument();
  });
});
