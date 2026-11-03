/**
 * Biblioteca de Conquistas (identidade visual v2): indicadores reais da API,
 * grade de medalhas com raridade, plataforma, XP e a barra do quanto da escola já
 * desbloqueou; filtros no cliente (com contagem e "Limpar filtros"); o detalhe em
 * janela acessível; esqueleto durante a carga e erro com "Tentar de novo".
 */
import { describe, expect, it } from "vitest";

import BibliotecaConquistas from "../pages/BibliotecaConquistas";
import { ApiError, renderComApp, responder, screen, userEvent, within } from "./utils";

const URL_BIB = "/escolas/1/gamificacao/biblioteca";

function conquista(over: Record<string, unknown>) {
  return {
    codigo: "c", nome: "C", icone: "🏅", descricao: "", objetivo: "", indicador: "livros_unicos",
    limite: 10, plataforma: "elefante", xp: 100, raridade: "comum", ordem: 1, ativa: true,
    criada_em: "2026-09-01", unidade: "livros", criterio: "Ler 10 livros diferentes",
    desbloqueios: 0, pct_desbloqueio: 0, ...over,
  };
}

function bibliotecaFake() {
  const leitura = conquista({
    codigo: "primeira_leitura", nome: "Primeira Leitura", icone: "📖", ordem: 1,
    descricao: "Leu o primeiro livro", criterio: "Ler 1 livro", limite: 1,
    desbloqueios: 40, pct_desbloqueio: 80,
  });
  const estrelas = conquista({
    codigo: "chuva_estrelas", nome: "Chuva de Estrelas", icone: "⭐", ordem: 2, plataforma: "matific",
    indicador: "estrelas", raridade: "epica", xp: 500, criterio: "Juntar 300 estrelas",
    objetivo: "Persistência na matemática", desbloqueios: 2, pct_desbloqueio: 4,
  });
  const antiga = conquista({
    codigo: "antiga", nome: "Conquista Antiga", icone: "🧩", ordem: 3, ativa: false,
    plataforma: "geral", raridade: "rara", xp: 50,
  });
  return {
    conquistas: [estrelas, antiga, leitura],
    estatisticas: {
      total: 3, ativas: 2, alunos: 50, total_desbloqueios: 42, pct_medio_conclusao: 42,
      mais_rara: { codigo: "chuva_estrelas", nome: "Chuva de Estrelas", icone: "⭐", xp: 500, desbloqueios: 2, pct_desbloqueio: 4 },
      mais_comum: { codigo: "primeira_leitura", nome: "Primeira Leitura", icone: "📖", xp: 100, desbloqueios: 40, pct_desbloqueio: 80 },
      maior_xp: { codigo: "chuva_estrelas", nome: "Chuva de Estrelas", icone: "⭐", xp: 500, desbloqueios: 2, pct_desbloqueio: 4 },
      ranking_desbloqueios: [
        { codigo: "primeira_leitura", nome: "Primeira Leitura", icone: "📖", xp: 100, desbloqueios: 40, pct_desbloqueio: 80 },
      ],
    },
    raridades: { comum: "Comum", rara: "Rara", epica: "Épica", lendaria: "Lendária" },
    indicadores: { livros_unicos: "Livros lidos", estrelas: "Estrelas" },
  };
}

/** Nomes dos cartões do catálogo, na ordem do DOM (botões que abrem o detalhe). */
function nomesNoCatalogo(): string[] {
  const nomes = ["Primeira Leitura", "Chuva de Estrelas", "Conquista Antiga"];
  return screen.getAllByRole("button")
    .filter((b) => b.getAttribute("aria-haspopup") === "dialog")
    .map((b) => nomes.find((n) => b.textContent?.includes(n)) ?? "?");
}

describe("Biblioteca de Conquistas", () => {
  it("mostra os indicadores reais e o catálogo na ordem padrão (campo `ordem`)", async () => {
    responder("GET", URL_BIB, bibliotecaFake());
    renderComApp(<BibliotecaConquistas />);

    expect(await screen.findByText("conclusão média 42% · 50 alunos na escola")).toBeInTheDocument();
    expect(screen.getByText("2 ativas")).toBeInTheDocument();
    expect(screen.getByText("Mais rara")).toBeInTheDocument();
    expect(screen.getByText("+500 XP", { selector: "p" })).toBeInTheDocument();
    expect(nomesNoCatalogo()).toEqual(["Primeira Leitura", "Chuva de Estrelas", "Conquista Antiga"]);
    // Barra de desbloqueio com o número em texto ao lado (não só a cor).
    expect(screen.getAllByText("40 alunos · 80%").length).toBeGreaterThan(0);
    // Inativa: selo em texto (não só a opacidade).
    expect(screen.getByText("Desativada")).toBeInTheDocument();
  });

  it("filtrar por plataforma mostra a contagem e 'Limpar filtros' volta tudo", async () => {
    responder("GET", URL_BIB, bibliotecaFake());
    const u = userEvent.setup();
    renderComApp(<BibliotecaConquistas />);
    await screen.findByText("3 conquistas");

    await u.selectOptions(screen.getByLabelText("Filtrar por plataforma"), "matific");
    expect(nomesNoCatalogo()).toEqual(["Chuva de Estrelas"]);
    expect(screen.getByText("1 conquista")).toBeInTheDocument();

    await u.selectOptions(screen.getByLabelText("Filtrar por raridade"), "comum");
    expect(screen.getByText("Nenhuma conquista com esses filtros")).toBeInTheDocument();

    // Dois "Limpar filtros" (barra e estado vazio): qualquer um zera tudo.
    await u.click(screen.getAllByRole("button", { name: "Limpar filtros" })[0]);
    expect(nomesNoCatalogo()).toHaveLength(3);
    expect(screen.queryByRole("button", { name: "Limpar filtros" })).not.toBeInTheDocument();
  });

  it("ordenar por 'Mais raras primeiro' reordena só a exibição", async () => {
    responder("GET", URL_BIB, bibliotecaFake());
    const u = userEvent.setup();
    renderComApp(<BibliotecaConquistas />);
    await screen.findByText("3 conquistas");

    await u.selectOptions(screen.getByLabelText("Ordenar"), "mais_raras");
    expect(nomesNoCatalogo()).toEqual(["Conquista Antiga", "Chuva de Estrelas", "Primeira Leitura"]);
  });

  it("clicar numa conquista abre o detalhe com o critério de desbloqueio", async () => {
    responder("GET", URL_BIB, bibliotecaFake());
    const u = userEvent.setup();
    renderComApp(<BibliotecaConquistas />);
    await screen.findByText("3 conquistas");

    const cartao = screen.getAllByRole("button").find((b) => b.textContent?.includes("Chuva de Estrelas"));
    await u.click(cartao as HTMLElement);
    const dialogo = await screen.findByRole("dialog", { name: "Chuva de Estrelas" });
    expect(within(dialogo).getByText("Juntar 300 estrelas")).toBeInTheDocument();
    expect(within(dialogo).getByText("Persistência na matemática")).toBeInTheDocument();
    expect(within(dialogo).getByText("2 (4% da escola)")).toBeInTheDocument();
    expect(within(dialogo).getByText("01/09/2026")).toBeInTheDocument();
  });

  it("carregando: esqueleto, sem estado vazio falso; erro: 'Tentar de novo' busca de novo", async () => {
    let falhar = true;
    responder("GET", URL_BIB, () => (falhar ? new ApiError(400, "Biblioteca indisponível") : bibliotecaFake()));
    const u = userEvent.setup();
    renderComApp(<BibliotecaConquistas />);

    // Durante a carga não aparece "Nenhuma conquista..." (não é verdade ainda).
    expect(screen.queryByText(/Nenhuma conquista/)).not.toBeInTheDocument();
    const alerta = await screen.findByRole("alert");
    expect(alerta).toHaveTextContent("Biblioteca indisponível");

    falhar = false;
    await u.click(within(alerta).getByRole("button", { name: "Tentar de novo" }));
    expect(await screen.findByText("3 conquistas")).toBeInTheDocument();
  });
});
