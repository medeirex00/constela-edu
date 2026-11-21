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
import { describe, expect, it, vi } from "vitest";

import { baixarCsv } from "../lib/csvRanking";
import RankingEvolucao from "../pages/RankingEvolucao";
import { escolaFake, renderComApp, responder, screen, userEvent, usuarioFake } from "./utils";

vi.mock("../lib/csvRanking", async (importarReal) => ({
  ...(await importarReal<typeof import("../lib/csvRanking")>()),
  baixarCsv: vi.fn(),
}));

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

  it("Admin Global numa escola só de Leitura vê e exporta apenas ganhos do plano", async () => {
    const aluno = item(31, "Criança Inventada", 1, 12.5);
    aluno.ganhos = { atividades: 30, estrelas: 120, livros: 2, tempo_leitura_min: 12, acertos: 4 };
    responder("GET", "/escolas/1/turmas", []);
    responder("GET", "/escolas/1/ranking-evolucao", [aluno]);
    renderComApp(<RankingEvolucao />, {
      usuario: usuarioFake({ is_global: true, modulos: ["leitura", "matematica"] }),
      escolas: [escolaFake({ modulos: ["leitura"] })],
    });

    const podio = await screen.findByRole("region", { name: PODIO });
    const tabela = screen.getByRole("table");
    expect(podio).toHaveTextContent(/\+2\s*livros|livros\s*\+2/);
    expect(tabela).toHaveTextContent(/\+2 livros/);
    expect(podio).not.toHaveTextContent(/atividades|estrelas/);
    expect(tabela).not.toHaveTextContent(/atividades|estrelas/);

    await userEvent.click(screen.getByRole("button", { name: "Exportar lista (CSV)" }));
    expect(baixarCsv).toHaveBeenCalledWith(expect.objectContaining({
      cabecalho: ["Posição", "Aluno", "Turma", "Livros (+)", "Acertos (+)", "Evolução"],
      linhas: [[1, "Criança Inventada", "3º Ano A", 2, 4, "12,5"]],
    }));
  });
});
