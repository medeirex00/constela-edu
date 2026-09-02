/**
 * Carreira → "Conquistas de aprendizado": o aluno vê as conquistas REAIS
 * (leitura/matemática, vindas do backend /quest/conquistas) — desbloqueadas com
 * descrição + ✓, e em andamento com o critério legível ("Leia 100 livros", nunca
 * "ACH_007") e a barra de progresso (67/100). O backend é a fonte da verdade; o
 * app só lê (mock de minhasConquistas).
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@constela/quest-core", () => ({ minhasConquistas: vi.fn() }));
vi.mock("../estado/sessao", () => ({ useSessao: () => ({ perfil: PERFIL }) }));

import { minhasConquistas } from "@constela/quest-core";

import { Carreira } from "../carreira/Carreira";

const PERFIL = {
  nome: "Ana", nome_exibicao: "Ana", nivel: 2, xp_total: 100, moedas: 5,
  estrelas_total: 10, sequencia_dias: 3, dias_sem_jogar: 0,
  avatar: { rosto: "sorriso", chapeu: "nenhum", cor: "#FF4D9D", veiculo: "nenhum" },
  preferencias: {},
};

const mock = minhasConquistas as unknown as ReturnType<typeof vi.fn>;

function conquista(over: Record<string, unknown>) {
  return {
    codigo: "x", nome: "X", icone: "🏆", descricao: "d", criterio: "Faça algo",
    limite: 100, progresso: 0, pct: 0, faltam: 100, atingida: false, data: null,
    unidade: "livros", ...over,
  };
}

describe("Carreira — conquistas de aprendizado", () => {
  it("mostra desbloqueada (✓) e em andamento (critério legível + progresso)", async () => {
    mock.mockResolvedValue({
      aluno_id: 1, nivel: 2, xp: 100, conquistas: [
        conquista({ codigo: "grande_leitor", nome: "Grande Leitor", icone: "🐘",
                    descricao: "Leu 50 livros", limite: 50, progresso: 50, pct: 100,
                    faltam: 0, atingida: true, data: "2026-08-01T00:00:00" }),
        conquista({ codigo: "incansavel", nome: "Leitor Incansável",
                    criterio: "Leia 100 livros", limite: 100, progresso: 67, pct: 67,
                    faltam: 33, atingida: false }),
      ],
    });
    render(<Carreira />);

    // Desbloqueada: nome + status conquistado
    expect(await screen.findByText("Grande Leitor")).toBeInTheDocument();
    expect(screen.getByText(/Conquistada/)).toBeInTheDocument();
    // Em andamento: critério legível (não código) + progresso 67/100
    expect(screen.getByText("Leitor Incansável")).toBeInTheDocument();
    expect(screen.getByText("Leia 100 livros")).toBeInTheDocument();
    expect(screen.getByText("67 / 100")).toBeInTheDocument();
    // barra de progresso acessível
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "67");
  });

  it("sem conquistas → estado acolhedor (não inventa)", async () => {
    mock.mockResolvedValue({ aluno_id: 1, nivel: 1, xp: 0, conquistas: [] });
    render(<Carreira />);
    expect(await screen.findByText(/conquistas de leitura e matemática/i)).toBeInTheDocument();
  });
});
