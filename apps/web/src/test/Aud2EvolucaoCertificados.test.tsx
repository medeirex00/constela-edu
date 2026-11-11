/**
 * Ranking de Evolução: o "Gerar certificados" premia só quem CRESCEU no período.
 *
 * O pódio da aba já seguia a regra do telão e das Premiações (só `nota_evolucao > 0`),
 * mas o lote de certificados recebia a lista INTEIRA: num período em que só um aluno
 * cresceu, o Top 3 saía com dois certificados de "evolução" para quem ficou em 0,0 (a
 * ordem entre eles é só o desempate alfabético). Achados RANKINGS-4 / DEC-20 (decisão
 * técnica: mesmo critério do pódio). A tabela continua com todos. Dados fictícios.
 */
import { describe, expect, it } from "vitest";

import RankingEvolucao from "../pages/RankingEvolucao";
import { renderComApp, responder, screen, userEvent, within } from "./utils";

const item = (aluno_id: number, nome: string, posicao: number, nota_evolucao: number) => ({
  posicao, aluno_id, nome, turma: "3º Ano A", ano_escolar: "3º Ano", nota_evolucao,
  ganhos: { atividades: nota_evolucao > 0 ? 4 : 0, estrelas: 0, livros: 0, tempo_leitura_min: 0, acertos: 0 },
});

function lista(...itens: ReturnType<typeof item>[]) {
  responder("GET", "/escolas/1/turmas", []);
  responder("GET", "/escolas/1/ranking-evolucao", itens);
}

describe("Ranking de Evolução: lote de certificados", () => {
  it("só um cresceu: o Top 3 do lote tem só ele, e a tabela continua com os três", async () => {
    lista(
      item(3, "Sofia Almeida Duarte", 1, 12.5), item(1, "Ana Beatriz Souza", 2, 0),
      item(2, "João Pedro Barbosa", 3, 0),
    );
    renderComApp(<RankingEvolucao />);
    const tabela = await screen.findByRole("table");
    for (const nome of ["Sofia Almeida Duarte", "Ana Beatriz Souza", "João Pedro Barbosa"]) {
      expect(tabela).toHaveTextContent(nome);
    }

    await userEvent.setup().click(screen.getByRole("button", { name: "Gerar certificados" }));
    const lote = await screen.findByRole("list", { name: "Alunos do lote" });
    expect(lote).toHaveTextContent("Sofia Almeida Duarte");
    expect(lote, "certificado de evolução para quem ficou em 0,0").not.toHaveTextContent("Ana Beatriz Souza");
    expect(lote).not.toHaveTextContent("João Pedro Barbosa");
    expect(within(lote).getAllByRole("listitem")).toHaveLength(1);
    // O contexto do lote diz de onde a lista vem: só quem cresceu.
    expect(screen.getByText(/^Ranking de Evolução · quem cresceu · /)).toBeInTheDocument();
  });

  it("ninguém cresceu: não há a quem dar certificado de evolução", async () => {
    lista(item(1, "Ana Beatriz Souza", 1, 0), item(2, "João Pedro Barbosa", 2, 0));
    renderComApp(<RankingEvolucao />);
    await screen.findByRole("table");
    const botao = screen.getByRole("button", { name: "Gerar certificados" });
    expect(botao).toBeDisabled();
    // A dica não diz "Não há alunos nesta lista" com a tabela cheia ao lado (DEC-20).
    expect(botao).toHaveAttribute(
      "title", "Ninguém cresceu no período: não há certificado de evolução a gerar.");
  });
});
