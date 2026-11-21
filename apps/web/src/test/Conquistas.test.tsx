/**
 * Conquistas e Mural (identidade visual v2): os destaques (Aluno do Dia, da
 * Semana e do Mês) têm estado de CARREGANDO e de FALHA próprios — antes diziam
 * "Sem destaque no período." enquanto o mural carregava ou quando ele falhava —,
 * o mural mostra o tempo relativo e o Ranking de XP segue a ordem da API, com
 * medalha 1º–3º (texto para leitor de tela) e "Mostrar mais".
 */
import { describe, expect, it } from "vitest";

import Conquistas from "../pages/Conquistas";
import { ApiError, escolaFake, renderComApp, responder, screen, userEvent, within } from "./utils";

const URL_MURAL = "/escolas/1/gamificacao/mural";
const URL_XP = "/escolas/1/gamificacao/ranking-xp";

const DUAS_HORAS = 2 * 60 * 60 * 1000;

function muralFake() {
  return {
    destaques: {
      dia: { aluno_id: 7, nome: "Ana Dia", turma: "3º Ano A", nota_evolucao: 12.5, ganhos: {} },
      semana: null,
      mes: { aluno_id: 8, nome: "Bruno Mes", turma: "4º Ano B", nota_evolucao: 30, ganhos: {} },
    },
    eventos: [
      {
        tipo: "conquista", icone: "📖",
        texto: "Ana Dia desbloqueou “Primeira Leitura”",
        data: new Date(Date.now() - DUAS_HORAS).toISOString(),
      },
    ],
  };
}

function xpFake(n: number) {
  return Array.from({ length: n }, (_, i) => ({
    posicao: i + 1, aluno_id: 100 + i, nome: `Aluno XP ${String(i + 1).padStart(2, "0")}`,
    turma: "3º Ano A", xp: 1000 - i * 10, nivel: 5, conquistas: 3,
  }));
}

describe("Conquistas e Mural", () => {
  it("enquanto o mural carrega, os destaques mostram o esqueleto (nunca 'Sem destaque')", async () => {
    // O mural não responde: a tela fica em carregamento.
    responder("GET", URL_MURAL, () => new Promise(() => undefined));
    responder("GET", URL_XP, []);
    renderComApp(<Conquistas />);

    expect(await screen.findAllByText("Carregando o destaque…")).toHaveLength(3);
    expect(screen.queryByText("Sem destaque no período.")).not.toBeInTheDocument();
    expect(screen.queryByText(/Destaque indisponível/)).not.toBeInTheDocument();
  });

  it("destaques com o aluno, a turma e a evolução; destaque vazio diz 'Sem destaque'", async () => {
    responder("GET", URL_MURAL, muralFake());
    responder("GET", URL_XP, []);
    renderComApp(<Conquistas />);

    const ana = await screen.findByRole("link", { name: "Ana Dia" });
    expect(ana).toHaveAttribute("href", "/alunos/7/evolucao");
    expect(screen.getByRole("link", { name: "Bruno Mes" })).toHaveAttribute("href", "/alunos/8/evolucao");
    expect(screen.getByText("evolução 12,5")).toBeInTheDocument();
    // A semana veio nula da API: aí sim, "sem destaque" (uma vez só).
    expect(screen.getAllByText("Sem destaque no período.")).toHaveLength(1);
    // Cada destaque diz de QUANDO é a evolução.
    expect(screen.getByText("Maior evolução nos últimos 7 dias")).toBeInTheDocument();
    // Mural com o tempo relativo e a data completa na dica.
    expect(screen.getByText("Ana Dia desbloqueou “Primeira Leitura”")).toBeInTheDocument();
    const quando = screen.getByText("há 2 h");
    expect(quando.tagName).toBe("TIME");
    expect(quando).toHaveAttribute("title");
  });

  it("mural com falha: os destaques dizem que estão indisponíveis e 'Tentar de novo' recarrega", async () => {
    let falhar = true;
    // 4xx: o useApi não repete sozinho, então o fluxo é determinístico.
    responder("GET", URL_MURAL, () => (falhar ? new ApiError(400, "Mural fora do ar") : muralFake()));
    responder("GET", URL_XP, []);
    const u = userEvent.setup();
    renderComApp(<Conquistas />);

    expect(await screen.findAllByText("Destaque indisponível: o mural não carregou.")).toHaveLength(3);
    expect(screen.queryByText("Sem destaque no período.")).not.toBeInTheDocument();
    const alerta = screen.getByRole("alert");
    expect(alerta).toHaveTextContent("Mural fora do ar");

    falhar = false;
    await u.click(within(alerta).getByRole("button", { name: "Tentar de novo" }));
    expect(await screen.findByRole("link", { name: "Ana Dia" })).toBeInTheDocument();
    expect(screen.queryByText(/Destaque indisponível/)).not.toBeInTheDocument();
  });

  it("Ranking de XP: ordem da API, medalha do 1º com texto, link para o aluno e 'Mostrar mais'", async () => {
    responder("GET", URL_MURAL, muralFake());
    responder("GET", URL_XP, xpFake(20));
    const u = userEvent.setup();
    renderComApp(<Conquistas />);

    const primeiro = await screen.findByRole("link", { name: "Aluno XP 01" });
    expect(primeiro).toHaveAttribute("href", "/alunos/100");
    const tabela = screen.getByRole("table");
    // Cabeçalho com texto (antes era só um ícone).
    expect(within(tabela).getByRole("columnheader", { name: "Conquistas" })).toBeInTheDocument();
    const linhas = within(tabela).getAllByRole("row").slice(1);
    expect(linhas).toHaveLength(15);
    expect(linhas[0]).toHaveTextContent("1º lugar");
    expect(linhas[0]).toHaveTextContent("Aluno XP 01");
    expect(linhas[3]).toHaveTextContent("4º lugar");
    expect(screen.getByText("Mostrando 15 de 20 alunos")).toBeInTheDocument();

    await u.click(screen.getByRole("button", { name: "Mostrar mais" }));
    expect(within(tabela).getAllByRole("row").slice(1)).toHaveLength(20);
    expect(screen.getByRole("link", { name: "Aluno XP 20" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Mostrar mais" })).not.toBeInTheDocument();
  });

  it.each([
    [2026, "Nível e conquistas de cada aluno — separado das notas"],
    [2027, "XP, nível e novas conquistas do ano letivo 2027"],
  ])("Ranking de XP informa a regra do ano letivo %i", async (ano_letivo_ativo, legenda) => {
    responder("GET", URL_MURAL, muralFake());
    responder("GET", URL_XP, xpFake(1));
    renderComApp(<Conquistas />, { escolas: [escolaFake({ ano_letivo_ativo })] });

    expect(await screen.findByText(legenda)).toBeInTheDocument();
  });

  it("mural: horário da COLETA (como na Visão geral) e 'Mostrar todos' expande a lista", async () => {
    const base = muralFake();
    const eventos = Array.from({ length: 10 }, (_, i) => ({
      ...base.eventos[0],
      texto: `Evento ${String(i + 1).padStart(2, "0")} desbloqueado`,
    }));
    responder("GET", URL_MURAL, { ...base, eventos });
    responder("GET", URL_XP, []);
    const u = userEvent.setup();
    renderComApp(<Conquistas />);

    expect(await screen.findByText("Evento 01 desbloqueado")).toBeInTheDocument();
    // O tempo relativo é o da coleta que registrou a conquista, dito por extenso.
    const quando = screen.getAllByText("há 2 h")[0];
    expect(quando.tagName).toBe("TIME");
    expect(quando.parentElement).toHaveTextContent("registrado há 2 h");
    expect(quando.getAttribute("title")).toMatch(/^Dado de /);
    expect(
      screen.getByText("A data é a do dado em que a conquista apareceu (numa coleta por período, o fim do período), não o momento exato na plataforma."),
    ).toBeInTheDocument();

    // 8 antes de "Mostrar todos"; o botão mostra o resto e some.
    expect(screen.queryByText("Evento 09 desbloqueado")).toBeNull();
    await u.click(screen.getByRole("button", { name: "Mostrar todos os 10 eventos" }));
    expect(screen.getByText("Evento 10 desbloqueado")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Mostrar todos/ })).toBeNull();
  });

  it("Ranking de XP: nome com dica do nome completo e contagem de conquistas na linha", async () => {
    responder("GET", URL_MURAL, muralFake());
    responder("GET", URL_XP, xpFake(3));
    renderComApp(<Conquistas />);

    const link = await screen.findByRole("link", { name: "Aluno XP 01" });
    expect(link).toHaveAttribute("title", "Aluno XP 01");
    const linha = link.closest("tr") as HTMLElement;
    const celulas = within(linha).getAllByRole("cell");
    // Posição, Aluno, Nível, XP e Conquistas — a contagem continua na última coluna.
    expect(celulas).toHaveLength(5);
    expect(celulas[2]).toHaveTextContent("Nv 5");
    expect(celulas[4]).toHaveTextContent("3");
  });

  it("Ranking de XP no celular: o XP fica preso à direita e a Posição continua nomeada", async () => {
    responder("GET", URL_MURAL, muralFake());
    responder("GET", URL_XP, xpFake(3));
    renderComApp(<Conquistas />);

    const link = await screen.findByRole("link", { name: "Aluno XP 01" });
    const tabela = screen.getByRole("table");
    // O XP é a coluna que não some no celular (presa-celular): cabeçalho e células.
    expect(within(tabela).getByRole("columnheader", { name: "XP" })).toHaveClass("presa-celular");
    const celulas = within(link.closest("tr") as HTMLElement).getAllByRole("cell");
    expect(celulas[3]).toHaveTextContent("1.000");
    expect(celulas[3]).toHaveClass("presa-celular");
    expect(celulas[4]).not.toHaveClass("presa-celular");
    // "Posição" sai da vista só no celular (a coluna fica do tamanho da medalha), mas
    // continua sendo o nome da coluna para o leitor de tela.
    const posicao = within(tabela).getByRole("columnheader", { name: "Posição" });
    expect(within(posicao).getByText("Posição")).toHaveClass("max-sm:sr-only");
  });

  it("sem XP e sem eventos: estados vazios com o texto de sempre", async () => {
    responder("GET", URL_MURAL, { destaques: { dia: null, semana: null, mes: null }, eventos: [] });
    responder("GET", URL_XP, []);
    renderComApp(<Conquistas />);

    expect(await screen.findByText("Nada por aqui ainda")).toBeInTheDocument();
    expect(screen.getByText("Nenhum aluno com XP")).toBeInTheDocument();
    expect(screen.getAllByText("Sem destaque no período.")).toHaveLength(3);
    expect(screen.getByRole("link", { name: "Biblioteca de Conquistas" })).toHaveAttribute("href", "/conquistas/biblioteca");
  });
});
