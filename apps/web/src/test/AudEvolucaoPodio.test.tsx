/**
 * Ranking de Evolução: o pódio só celebra quem CRESCEU no período.
 *
 * `itensDoPodio` pegava os 3 primeiros da lista sem olhar o valor: num período
 * em que ninguém cresceu, a aba montava ouro/prata/bronze com "0,0 de evolução"
 * (em ordem alfabética, o desempate). A regra é a do telão
 * (`publico._dados_publicos`: só `nota_evolucao > 0`). A tabela continua com
 * todos — 0,0 de quem tem dado e não cresceu é zero legítimo. Achado RANKINGS-4.
 * Dados fictícios.
 */
import { describe, expect, it } from "vitest";

import RankingEvolucao from "../pages/RankingEvolucao";
import { renderComApp, responder, screen } from "./utils";

const PODIO = "Pódio da evolução no período";

const item = (aluno_id: number, nome: string, posicao: number, nota_evolucao: number) => ({
  posicao, aluno_id, nome, turma: "3º Ano A", ano_escolar: "3º Ano",
  nota_evolucao,
  ganhos: { atividades: nota_evolucao > 0 ? 4 : 0, estrelas: 0, livros: 0, tempo_leitura_min: 0, acertos: 0 },
  dimensao: null, nota: null, n_aferidos: null,
  dimensoes: {
    leitura: { plataforma: "elefante", contratada: true, aferido: false, nota: null, posicao: null, n_aferidos: 0 },
    matematica: { plataforma: "matific", contratada: true, aferido: true, nota: nota_evolucao, posicao, n_aferidos: 3 },
  },
});

describe("Ranking de Evolução: pódio", () => {
  it("ninguém cresceu: sem pódio, e a tabela continua com todos", async () => {
    responder("GET", "/escolas/1/turmas", []);
    responder("GET", "/escolas/1/ranking-evolucao", [
      item(1, "Ana Beatriz Souza", 1, 0), item(2, "João Pedro Barbosa", 2, 0),
      item(3, "Sofia Almeida Duarte", 3, 0),
    ]);
    renderComApp(<RankingEvolucao />);
    await screen.findAllByText("Sofia Almeida Duarte");
    expect(screen.queryByRole("region", { name: PODIO }),
      "pódio com medalha para 0,0 de evolução").toBeNull();
    // A tabela segue com as três (0,0 de quem tem dado é zero legítimo).
    const tabela = screen.getByRole("table");
    for (const nome of ["Ana Beatriz Souza", "João Pedro Barbosa", "Sofia Almeida Duarte"]) {
      expect(tabela).toHaveTextContent(nome);
    }
  });

  it("só um cresceu: o pódio tem só ele", async () => {
    responder("GET", "/escolas/1/turmas", []);
    responder("GET", "/escolas/1/ranking-evolucao", [
      item(3, "Sofia Almeida Duarte", 1, 12.5), item(1, "Ana Beatriz Souza", 2, 0),
      item(2, "João Pedro Barbosa", 3, 0),
    ]);
    renderComApp(<RankingEvolucao />);
    const podio = await screen.findByRole("region", { name: PODIO });
    expect(podio).toHaveTextContent("Sofia Almeida Duarte");
    expect(podio).not.toHaveTextContent("Ana Beatriz Souza");
    expect(podio).not.toHaveTextContent("João Pedro Barbosa");
    expect(podio).not.toHaveTextContent("0,0 de evolução");
  });
});
