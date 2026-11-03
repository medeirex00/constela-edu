/**
 * Inteligência Pedagógica — tabela "Índices por aluno" (revisão visual v2): a coluna
 * "Persistência (semanal)" sumia do cartão em 1024 px e saía cortada em 820 px, e o
 * chip da turma quebrava em três linhas. O rótulo agora quebra num ponto escolhido
 * (abaixo de xl) sem mudar o nome da coluna, e o chip fica numa linha.
 *
 * Celular (prontidão da demo): a tabela mostrava só Aluno, Turma e o começo de
 * "ENGAJAM…" — nenhum índice sem rolar de lado. A turma desceu para o chip sob o nome
 * (uma vez só no DOM), a barra sai abaixo de 640 px e o NÚMERO fica.
 */
import { describe, expect, it } from "vitest";

import Insights from "../pages/Insights";
import { renderComApp, responder, screen, within } from "./utils";

const RESPOSTA = {
  indices: [
    { aluno_id: 11, nome: "Gabriela Nunes Pereira", turma: "4º Ano A", engajamento: 46.7, evolucao: 53.3, persistencia: 100 },
  ],
  alertas: [],
};

describe("Insights — índices por aluno", () => {
  it("as colunas seguem com o nome inteiro; a turma vai sob o nome; a persistência quebra num ponto escolhido", async () => {
    responder("GET", "/escolas/1/insights", RESPOSTA);
    renderComApp(<Insights />);

    const th = await screen.findByRole("columnheader", { name: "Persistência (semanal)" });
    // "(semanal)" desce para a segunda linha só abaixo de xl.
    expect(within(th).getByText("(semanal)")).toHaveClass("block", "xl:inline");
    for (const nome of ["Aluno", "Engajamento", "Evolução"]) {
      expect(screen.getByRole("columnheader", { name: nome })).toBeInTheDocument();
    }
    // A turma deixou de ser coluna: está no chip sob o nome, na célula do aluno (uma vez só).
    expect(screen.queryByRole("columnheader", { name: "Turma" })).toBeNull();
    expect(screen.getAllByRole("columnheader")).toHaveLength(4);

    const linha = screen.getByRole("link", { name: /Gabriela Nunes Pereira/ }).closest("tr") as HTMLElement;
    const celulas = within(linha).getAllByRole("cell");
    expect(celulas).toHaveLength(4);
    expect(within(celulas[0]).getByText("4º Ano A")).toHaveClass("whitespace-nowrap");
    expect(screen.getAllByText("4º Ano A")).toHaveLength(1);
    // O nome não é mais cortado com reticências (pode quebrar em duas linhas).
    expect(within(linha).getByTitle("Gabriela Nunes Pereira")).not.toHaveClass("truncate");
    // Os três índices continuam com o número ao lado da barra.
    expect(within(linha).getByText("46,7")).toBeInTheDocument();
    expect(within(linha).getByText("53,3")).toBeInTheDocument();
    expect(within(linha).getByText("100,0")).toBeInTheDocument();
    // No celular a barra (decorativa) sai e o número fica.
    const numero = within(celulas[1]).getByText("46,7");
    expect(numero).not.toHaveClass("max-sm:hidden");
    const barra = numero.previousElementSibling as HTMLElement;
    expect(barra).toHaveAttribute("aria-hidden");
    expect(barra).toHaveClass("max-sm:hidden");
  });
});
