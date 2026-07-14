import { useNavigate } from "react-router-dom";
import { describe, expect, it } from "vitest";

import Rankings from "../pages/Rankings";
import type { RankingItem, RankingLeituraItem, Turma } from "../lib/types";
import { rankingItemFake, renderComApp, responder, screen, turmaFake, userEvent } from "./utils";

const URL_TURMAS = "/escolas/1/turmas";
const URL_GERAL = "/escolas/1/ranking";
const URL_LEITURA = "/escolas/1/ranking/leitura";
const URL_MATEMATICA = "/escolas/1/ranking/matematica";

describe("Rankings (tela única com seletor)", () => {
  it("mostra o seletor e alterna o conteúdo sem trocar de página", async () => {
    responder("GET", URL_TURMAS, [turmaFake()] as Turma[]);
    // Geral (padrão, período "tudo") → endpoint /ranking
    responder("GET", URL_GERAL, [
      rankingItemFake({ aluno_id: 10, nome: "Ana Beatriz Souza" }),
    ] as RankingItem[]);
    // Leitura → endpoint /ranking/leitura
    responder("GET", URL_LEITURA, [
      {
        posicao: 1, aluno_id: 20, nome: "Carla Leitora Silva", turma: "3º Ano A",
        ano_escolar: "3º Ano", livros: 9, pontos: 210, tempo_leitura_min: 60,
      },
    ] as RankingLeituraItem[]);

    const u = userEvent.setup();
    renderComApp(<Rankings />, { rota: "/ranking" });

    // Cabeçalho único + os 4 tipos como abas do seletor.
    expect(await screen.findByText("Ranking Geral")).toBeInTheDocument();
    for (const rotulo of ["Geral", "Elefante Letrado", "Matific", "Evolução"]) {
      expect(screen.getByRole("tab", { name: rotulo })).toBeInTheDocument();
    }

    // Começa no Geral: mostra o aluno do /ranking e as colunas do consolidado
    // (usa "Leitura" — "Matific" agora também é o nome de uma aba, seria ambíguo).
    expect(await screen.findByRole("link", { name: /Ana Beatriz Souza/ })).toBeInTheDocument();
    expect(screen.getByText("Leitura")).toBeInTheDocument();

    // Troca para Elefante Letrado (leitura): só o CONTEÚDO muda (busca /ranking/leitura).
    await u.click(screen.getByRole("tab", { name: "Elefante Letrado" }));
    expect(await screen.findByRole("link", { name: /Carla Leitora Silva/ })).toBeInTheDocument();
    expect(screen.getByText("Livros")).toBeInTheDocument();
    // O cabeçalho da tela continua único (sem "voltar" para outra página).
    expect(screen.getByText("Ranking Geral")).toBeInTheDocument();
  });

  it("respeita o tipo vindo da URL (?ver=matematica) para deep-links/atalhos", async () => {
    responder("GET", URL_TURMAS, [turmaFake()] as Turma[]);
    responder("GET", URL_MATEMATICA, [
      {
        posicao: 1, aluno_id: 30, nome: "Davi Mat Souza", turma: "3º Ano A",
        ano_escolar: "3º Ano", estrelas: 40, atividades: 12, pontuacao_media: 80,
      },
    ]);

    renderComApp(<Rankings />, { rota: "/ranking?ver=matematica" });

    expect(screen.getByRole("tab", { name: "Matific" })).toHaveAttribute(
      "aria-selected", "true");
    expect(await screen.findByRole("link", { name: /Davi Mat Souza/ })).toBeInTheDocument();
    expect(screen.getByText("Estrelas")).toBeInTheDocument();
  });

  it("segue a URL quando ela muda com a tela JÁ montada (atalho Alt+3/nav)", async () => {
    // Regressão: mudar só a query (?ver=) não remonta a rota; a aba tem que
    // acompanhar a URL mesmo assim (o seletor deriva o tipo do ?ver=).
    responder("GET", URL_TURMAS, [turmaFake()] as Turma[]);
    responder("GET", URL_GERAL, [
      rankingItemFake({ aluno_id: 10, nome: "Ana Beatriz Souza" }),
    ] as RankingItem[]);
    responder("GET", "/escolas/1/ranking-evolucao", [
      {
        posicao: 1, aluno_id: 40, nome: "Eva Evolucao Lima", turma: "3º Ano A",
        nota_evolucao: 12,
        ganhos: { atividades: 3, estrelas: 1, livros: 2, tempo_leitura_min: 10, acertos: 4 },
      },
    ]);

    function Harness() {
      const nav = useNavigate();
      return (
        <>
          <button onClick={() => nav("/ranking?ver=evolucao")}>ir-evolucao</button>
          <Rankings />
        </>
      );
    }

    const u = userEvent.setup();
    renderComApp(<Harness />, { rota: "/ranking" });

    // Começa no Geral.
    expect(await screen.findByRole("link", { name: /Ana Beatriz Souza/ })).toBeInTheDocument();

    // Navegação EXTERNA muda só a query → a aba Evolução tem que assumir.
    await u.click(screen.getByRole("button", { name: "ir-evolucao" }));
    expect(await screen.findByRole("link", { name: /Eva Evolucao Lima/ })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Evolução" })).toHaveAttribute(
      "aria-selected", "true");
  });
});
