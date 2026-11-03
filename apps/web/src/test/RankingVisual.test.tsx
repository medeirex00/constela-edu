/**
 * Ranking na identidade visual v2 — o que a nova casca trava:
 *   - PÓDIO: só as posições 1–3 de verdade (item.posicao, nunca o índice), sem link
 *     (o link para a ficha fica só na tabela: um por aluno); com filtro de turma a
 *     gestão recebe a posição da escola inteira e não há pódio no recorte;
 *   - AÇÕES no cabeçalho da tela: "Exportar lista (CSV)" (a lista exibida, gerada
 *     no navegador) e "Gerar certificados" com a lista da aba e o modelo pela aba
 *     (D7: Geral → certificado Geral, Leitura → Elefante, Matemática → Matific);
 *     escondido da Secretaria, visível para o professor;
 *   - um único título de página com "Ranking Geral" (o E2E procura o heading);
 *   - seções secundárias recolhíveis (classificação oficial, competição por turno);
 *   - subtítulo com o período e a data do dado vinda do backend (sem inventar hora).
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import { itensDoPodio } from "../components/PodioRanking";
import { textoFrescorCabecalho } from "../components/RankingUi";
import type { Frescor } from "../components/SeloFrescor";
import { conteudoCsv, nomeArquivoCsv } from "../lib/csvRanking";
import RankingEvolucao from "../pages/RankingEvolucao";
import RankingGeral from "../pages/RankingGeral";
import RankingLeitura from "../pages/RankingLeitura";
import RankingMatematica from "../pages/RankingMatematica";
import Rankings from "../pages/Rankings";
import type { RankingItem, RankingLeituraItem, Turma } from "../lib/types";
import {
  rankingItemFake, renderComApp, responder, screen, turmaFake, userEvent, usuarioFake, within,
} from "./utils";

const URL_TURMAS = "/escolas/1/turmas";
const URL_GERAL = "/escolas/1/ranking";
const URL_LEITURA = "/escolas/1/ranking/leitura";
const URL_MATEMATICA = "/escolas/1/sync/matific/placar-ao-vivo";

const QUATRO: RankingItem[] = [
  rankingItemFake({ posicao: 1, aluno_id: 10, nome: "Ana Beatriz Souza", n_aferidos: 4 }),
  rankingItemFake({ posicao: 2, aluno_id: 11, nome: "Bruno Lima", n_aferidos: 4, nota_geral: 80 }),
  rankingItemFake({ posicao: 3, aluno_id: 12, nome: "Carla Mendes", n_aferidos: 4, nota_geral: 75 }),
  rankingItemFake({ posicao: 4, aluno_id: 13, nome: "Davi Rocha", n_aferidos: 4, nota_geral: 70 }),
];

const LEITURA: RankingLeituraItem[] = [
  { posicao: 1, aluno_id: 20, nome: "Leitora Um", turma: "3º Ano A", ano_escolar: "3º Ano",
    livros: 9, pontos: 210, tempo_leitura_min: 60 },
  { posicao: 2, aluno_id: 21, nome: "Leitor Dois", turma: "3º Ano A", ano_escolar: "3º Ano",
    livros: 7, pontos: 150, tempo_leitura_min: 45 },
];

function placarMatific() {
  return {
    periodo: "Este mês", filtro: "x", atualizado_em: "2026-07-14T12:00:00Z", total: 1, com_link: 1,
    itens: [{ posicao: 1, aluno_id: 30, nome: "Davi Mat Souza", turma: "3º Ano A", serie: "3",
              estrelas: 40, atividades: 12, pontuacao_media: 3.33 }],
  };
}

function podio(): HTMLElement {
  return screen.getByRole("region", { name: /^Pódio/ });
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("Pódio do ranking", () => {
  it("Geral: os 3 primeiros em cartões, sem link; a tabela segue com um link por aluno", async () => {
    responder("GET", URL_TURMAS, [turmaFake()] as Turma[]);
    responder("GET", URL_GERAL, QUATRO);
    renderComApp(<Rankings />, { rota: "/ranking" });

    expect(await screen.findByRole("link", { name: "Ana Beatriz Souza" })).toBeInTheDocument();
    const cartoes = within(podio()).getAllByRole("listitem");
    // Ordem do DOM = 1º, 2º, 3º (no estreito, empilhados nessa ordem; o centro é só CSS).
    expect(cartoes.map((c) => c.textContent)).toEqual([
      expect.stringContaining("Ana Beatriz Souza"),
      expect.stringContaining("Bruno Lima"),
      expect.stringContaining("Carla Mendes"),
    ]);
    expect(within(cartoes[0]).getByText("1º lugar:")).toBeInTheDocument();
    expect(within(cartoes[0]).getByText("nota geral")).toBeInTheDocument();
    expect(within(podio()).queryByText("Davi Rocha")).not.toBeInTheDocument();
    // Sem link no pódio: cada aluno tem UM link (na tabela).
    expect(within(podio()).queryAllByRole("link")).toHaveLength(0);
    for (const nome of ["Ana Beatriz Souza", "Bruno Lima", "Carla Mendes", "Davi Rocha"]) {
      expect(screen.getAllByRole("link", { name: nome })).toHaveLength(1);
    }
    // Um só título com "Ranking Geral" (o E2E procura o heading por esse nome).
    expect(screen.getAllByRole("heading", { name: /ranking geral/i })).toHaveLength(1);
    // Sem coluna de variação de posição (não há histórico de posição no sistema).
    expect(screen.queryByRole("columnheader", { name: /varia/i })).not.toBeInTheDocument();
  });

  it("com turma e sem turno (posição da escola inteira: 7º, 12º) não há pódio no recorte", async () => {
    responder("GET", URL_TURMAS, [turmaFake({ id: 1, nome: "3º Ano A" })] as Turma[]);
    responder("GET", URL_GERAL, (caminho: string) =>
      caminho.includes("turma_id=1")
        ? [rankingItemFake({ posicao: 7, aluno_id: 20, nome: "Aluno Da Turma A", n_aferidos: 40 }),
           rankingItemFake({ posicao: 12, aluno_id: 21, nome: "Outro Da Turma A", n_aferidos: 40 })]
        : QUATRO);
    const u = userEvent.setup();
    renderComApp(<RankingGeral />, { rota: "/ranking" });

    await screen.findByRole("link", { name: "Ana Beatriz Souza" });
    expect(podio()).toBeInTheDocument();

    await u.selectOptions(screen.getByLabelText("Filtrar por turma ou série"), "turma:1");
    expect(await screen.findByRole("link", { name: "Aluno Da Turma A" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: /^Pódio/ })).not.toBeInTheDocument();
    expect(screen.getByText("7º")).toBeInTheDocument();
  });

  it("itensDoPodio usa a posição da API, em sequência a partir do 1º", () => {
    const p = (...posicoes: number[]) => posicoes.map((posicao) => ({ posicao }));
    expect(itensDoPodio(p(1, 2, 3, 4))).toEqual(p(1, 2, 3));
    expect(itensDoPodio(p(1, 2))).toEqual(p(1, 2));
    expect(itensDoPodio(p(7, 12, 15))).toEqual([]);
    expect(itensDoPodio(p(1, 3, 4))).toEqual(p(1));
    expect(itensDoPodio([])).toEqual([]);
  });
});

describe("Ações do cabeçalho: Exportar lista e Gerar certificados", () => {
  it("o lote abre com a lista da aba e o modelo pela aba (Geral → Geral, Leitura → Elefante, Matemática → Matific)", async () => {
    responder("GET", URL_TURMAS, [turmaFake()] as Turma[]);
    responder("GET", URL_GERAL, QUATRO);
    responder("GET", URL_LEITURA, LEITURA);
    responder("GET", URL_MATEMATICA, placarMatific());
    const u = userEvent.setup();
    renderComApp(<Rankings />, { rota: "/ranking", periodo: { preset: "mes" } });

    await screen.findByRole("link", { name: "Ana Beatriz Souza" });
    expect(screen.getByRole("button", { name: "Exportar lista (CSV)" })).toBeEnabled();

    // Geral → certificado Geral, com os 3 primeiros da lista exibida.
    await u.click(screen.getByRole("button", { name: "Gerar certificados" }));
    let dialogo = screen.getByRole("dialog", { name: "Gerar certificados" });
    expect(within(dialogo).getByRole("radio", { name: "Geral" })).toBeChecked();
    expect(within(dialogo).getByText(/Ranking Geral \(Leitura \+ Matemática\) · ano letivo/)).toBeInTheDocument();
    const lote = within(dialogo).getByRole("list", { name: "Alunos do lote" });
    expect(within(lote).getAllByRole("listitem").map((li) => li.textContent)).toEqual([
      expect.stringContaining("Ana Beatriz Souza"),
      expect.stringContaining("Bruno Lima"),
      expect.stringContaining("Carla Mendes"),
    ]);
    await u.click(within(dialogo).getByRole("button", { name: "Fechar" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    // Leitura → arte do Elefante, com a lista do período.
    await u.click(screen.getByRole("tab", { name: "Leitura" }));
    await screen.findByRole("link", { name: "Leitora Um" });
    await u.click(screen.getByRole("button", { name: "Gerar certificados" }));
    dialogo = screen.getByRole("dialog", { name: "Gerar certificados" });
    expect(within(dialogo).getByRole("radio", { name: "Elefante Letrado" })).toBeChecked();
    expect(within(dialogo).getByText(/Leitura no período \(pontos\) · Este mês/)).toBeInTheDocument();
    expect(within(dialogo).getByText("Leitora Um")).toBeInTheDocument();
    await u.click(within(dialogo).getByRole("button", { name: "Fechar" }));

    // Matemática → arte do Matific, com o placar do período.
    await u.click(screen.getByRole("tab", { name: "Matemática" }));
    await screen.findByRole("link", { name: "Davi Mat Souza" });
    await u.click(screen.getByRole("button", { name: "Gerar certificados" }));
    dialogo = screen.getByRole("dialog", { name: "Gerar certificados" });
    expect(within(dialogo).getByRole("radio", { name: "Matific" })).toBeChecked();
    expect(within(dialogo).getByText("Davi Mat Souza")).toBeInTheDocument();
  });

  it("Secretaria (com escola escolhida) não vê o lote de certificados; o professor vê", async () => {
    responder("GET", URL_TURMAS, [turmaFake()] as Turma[]);
    responder("GET", URL_GERAL, QUATRO);
    const { unmount } = renderComApp(<RankingGeral />, {
      rota: "/ranking",
      usuario: usuarioFake({ nome: "Secretaria", cargo: "coordenador", rede_id: 1, escola_id: null }),
      escolaSelecionada: 1,
    });
    await screen.findByRole("link", { name: "Ana Beatriz Souza" });
    expect(screen.getByRole("button", { name: "Exportar lista (CSV)" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Gerar certificados" })).not.toBeInTheDocument();
    unmount();

    renderComApp(<RankingGeral />, { rota: "/ranking", usuario: usuarioFake({ cargo: "professor" }) });
    await screen.findByRole("link", { name: "Ana Beatriz Souza" });
    expect(screen.getByRole("button", { name: "Gerar certificados" })).toBeEnabled();
    // O cartaz é de gestão: o professor não vê.
    expect(screen.queryByRole("button", { name: /Baixar cartaz/ })).not.toBeInTheDocument();
  });

  it("Exportar lista (CSV) baixa a lista exibida, sem nova consulta", async () => {
    responder("GET", URL_TURMAS, [turmaFake()] as Turma[]);
    responder("GET", URL_GERAL, QUATRO);
    const criar = vi.fn((_blob: Blob) => "blob:ranking");
    const revogar = vi.fn();
    Object.assign(URL, { createObjectURL: criar, revokeObjectURL: revogar });
    const clique = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    const u = userEvent.setup();
    renderComApp(<RankingGeral />, { rota: "/ranking" });

    await screen.findByRole("link", { name: "Ana Beatriz Souza" });
    await u.click(screen.getByRole("button", { name: "Exportar lista (CSV)" }));

    expect(criar).toHaveBeenCalledTimes(1);
    expect(criar.mock.calls[0][0]).toBeInstanceOf(Blob);
    expect(criar.mock.calls[0][0].type).toBe("text/csv;charset=utf-8");
    expect(clique).toHaveBeenCalledTimes(1);
    const link = clique.mock.contexts[0] as unknown as HTMLAnchorElement;
    expect(link.download).toMatch(/^ranking-geral_\d{4}-\d{2}-\d{2}\.csv$/);
  });

  it("conteúdo do CSV: ';', BOM, números em pt-BR e proteção contra fórmula", () => {
    const texto = conteudoCsv({
      cabecalho: ["Posição", "Aluno", "Nota"],
      linhas: [[1, "Ana; \"Bia\"", "85,5"], [2, "=SOMA(A1)", 1234.5], [3, null, undefined]],
    });
    expect(texto.startsWith("﻿")).toBe(true);
    expect(texto.split("\r\n")).toEqual([
      "﻿Posição;Aluno;Nota",
      "1;\"Ana; \"\"Bia\"\"\";85,5",
      "2;'=SOMA(A1);1.234,5",
      "3;;",
      "",
    ]);
    expect(nomeArquivoCsv("ranking-leitura-4º bimestre-Manhã", new Date(2026, 9, 31)))
      .toBe("ranking-leitura-4o-bimestre-manha_2026-10-31.csv");
  });
});

describe("Lote do Ranking: bimestre impresso pelo período da aba", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("período '3º bimestre' em 31/10: Leitura e Matemática abrem o lote no 3º, não no 4º", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date(2026, 9, 31, 12, 0, 0));
    responder("GET", URL_TURMAS, [turmaFake()] as Turma[]);
    responder("GET", URL_GERAL, QUATRO);
    responder("GET", URL_LEITURA, LEITURA);
    responder("GET", URL_MATEMATICA, placarMatific());
    const u = userEvent.setup();
    renderComApp(<Rankings />, { rota: "/ranking", periodo: { preset: "bimestre_3" } });
    await screen.findByRole("link", { name: "Ana Beatriz Souza" });

    await u.click(screen.getByRole("tab", { name: "Leitura" }));
    await screen.findByRole("link", { name: "Leitora Um" });
    await u.click(screen.getByRole("button", { name: "Gerar certificados" }));
    let dialogo = screen.getByRole("dialog", { name: "Gerar certificados" });
    expect(within(dialogo).getByLabelText("Bimestre impresso")).toHaveValue("3");
    await u.click(within(dialogo).getByRole("button", { name: "Fechar" }));

    await u.click(screen.getByRole("tab", { name: "Matemática" }));
    await screen.findByRole("link", { name: "Davi Mat Souza" });
    await u.click(screen.getByRole("button", { name: "Gerar certificados" }));
    dialogo = screen.getByRole("dialog", { name: "Gerar certificados" });
    expect(within(dialogo).getByLabelText("Bimestre impresso")).toHaveValue("3");
  });
});

describe("Abas do Ranking: contraste", () => {
  it("na aba primária ATIVA, o detalhe da plataforma é branco (indigo-100 dava 3,92:1)", async () => {
    responder("GET", URL_TURMAS, [turmaFake()] as Turma[]);
    responder("GET", URL_GERAL, QUATRO);
    responder("GET", URL_LEITURA, LEITURA);
    const u = userEvent.setup();
    renderComApp(<Rankings />, { rota: "/ranking" });
    await screen.findByRole("link", { name: "Ana Beatriz Souza" });

    await u.click(screen.getByRole("tab", { name: "Leitura" }));
    const ativa = screen.getByRole("tab", { name: "Leitura" });
    expect(ativa).toHaveAttribute("aria-selected", "true");
    const detalhe = within(ativa).getByText("· Elefante Letrado");
    expect(detalhe).toHaveClass("text-white");
    expect(detalhe).not.toHaveClass("text-indigo-100");
    // Inativa: o cinza de sempre (sobre o fundo branco da barra de abas).
    const inativa = within(screen.getByRole("tab", { name: "Matemática" })).getByText("· Matific");
    expect(inativa).toHaveClass("text-zinc-500");
  });
});

describe("Leitura: bloco principal e seções secundárias", () => {
  it("classificação oficial e competição por turno começam recolhidas e abrem no clique", async () => {
    responder("GET", URL_TURMAS, [turmaFake()] as Turma[]);
    responder("GET", URL_LEITURA, LEITURA);
    const u = userEvent.setup();
    renderComApp(<RankingLeitura />, { rota: "/ranking-leitura" });

    expect(await screen.findByRole("link", { name: "Leitora Um" })).toBeInTheDocument();
    const oficial = screen.getByRole("button", { name: "Classificação oficial — Leitura" });
    const competicao = screen.getByRole("button", { name: "Competição por turno" });
    expect(oficial).toHaveAttribute("aria-expanded", "false");
    expect(competicao).toHaveAttribute("aria-expanded", "false");
    // Fechada, a seção continua montada (consultas e avisos valem) e fica inerte.
    const conteudo = document.getElementById(oficial.getAttribute("aria-controls") ?? "");
    expect(conteudo).toHaveAttribute("inert");

    await u.click(oficial);
    expect(oficial).toHaveAttribute("aria-expanded", "true");
    expect(conteudo).not.toHaveAttribute("inert");
    // O pódio da leitura no período mostra os pontos e as métricas do MESMO período.
    expect(within(podio()).getAllByText("pontos")).toHaveLength(2);
    expect(within(podio()).getAllByText("livros")).toHaveLength(2);
  });
});

describe("Subtítulo: período e data do dado", () => {
  function frescor(leitura: Record<string, unknown> = {}, matematica: Record<string, unknown> = {}): Frescor {
    const bloco = (over: Record<string, unknown>) => ({
      plataforma: "elefante", contratada: true, estado: "em_dia",
      dado_mais_recente_em: "2026-10-19", dado_mais_antigo_em: "2026-10-19",
      dias_desde_dado: 1, alunos_com_dado: 40, alunos_com_dado_antigo: 0,
      // UTC sem fuso (como a API grava): 06:10 UTC = 03:10 em Brasília, mesmo dia.
      ultima_sincronizacao_ok_em: "2026-10-19T06:10:00", dias_desde_sincronizacao_ok: 1,
      ...over,
    });
    return {
      limite_dias: 7, hoje: "2026-10-20", estado: "em_dia",
      dimensoes: { leitura: bloco(leitura), matematica: bloco({ plataforma: "matific", ...matematica }) },
    } as Frescor;
  }

  it("data e hora só quando a sincronização é do mesmo dia do dado; datas diferentes viram faixa", () => {
    expect(textoFrescorCabecalho(frescor(), ["leitura", "matematica"])).toBe("dados de 19/10 às 03:10");
    expect(textoFrescorCabecalho(frescor({ dado_mais_recente_em: "2026-10-05" }), ["leitura", "matematica"]))
      .toBe("dados de 05/10 a 19/10");
    // Sincronização de outro dia (o Elefante mede o dia anterior): sem hora.
    expect(textoFrescorCabecalho(frescor({ ultima_sincronizacao_ok_em: "2026-10-20T03:30:00" }), ["leitura"]))
      .toBe("dados de 19/10");
    // Sem dado: nada (nunca uma data inventada).
    expect(textoFrescorCabecalho(frescor({ estado: "sem_dados", dado_mais_recente_em: null }), ["leitura"]))
      .toBeNull();
  });

  it("o cabeçalho do Ranking mostra o período da aba e a data do dado do backend", async () => {
    responder("GET", URL_TURMAS, [turmaFake()] as Turma[]);
    responder("GET", URL_GERAL, QUATRO);
    responder("GET", "/escolas/1/ranking/frescor", frescor());
    renderComApp(<Rankings />, { rota: "/ranking" });

    expect(await screen.findByText(/· dados de 19\/10 às 03:10/)).toBeInTheDocument();
    expect(screen.getByText("Ano letivo · classificação acumulada")).toBeInTheDocument();
  });
});

describe("Revisão visual v2: cor do lote, concordância e larguras estreitas", () => {
  it("'Gerar certificados' do cabeçalho é âmbar (a cor da premiação, como na Visão geral e em Premiações)", async () => {
    responder("GET", URL_TURMAS, [turmaFake()] as Turma[]);
    responder("GET", URL_GERAL, QUATRO);
    renderComApp(<Rankings />, { rota: "/ranking" });
    await screen.findByRole("link", { name: "Ana Beatriz Souza" });

    const botao = screen.getByRole("button", { name: "Gerar certificados" });
    expect(botao).toHaveClass("bg-ouro-400", "text-marinho-900", "shadow-ambar");
    expect(botao).not.toHaveClass("bg-indigo-600");
  });

  it("Evolução: ganho de 1 vai no singular ('+1 livro'), os demais no plural, na tabela e no pódio", async () => {
    responder("GET", URL_TURMAS, [turmaFake()] as Turma[]);
    responder("GET", "/escolas/1/ranking-evolucao", [
      { posicao: 1, aluno_id: 40, nome: "Eva Evolucao Lima", turma: "3º Ano A", ano_escolar: "3º Ano",
        nota_evolucao: 12, ganhos: { atividades: 1, estrelas: 2, livros: 1, tempo_leitura_min: 0, acertos: 1 } },
      { posicao: 2, aluno_id: 41, nome: "Caio Evolucao Reis", turma: "3º Ano A", ano_escolar: "3º Ano",
        nota_evolucao: 10, ganhos: { atividades: 3, estrelas: 1, livros: 2, tempo_leitura_min: 0, acertos: 4 } },
    ]);
    renderComApp(<RankingEvolucao />, { rota: "/evolucao" });

    await screen.findByRole("link", { name: "Eva Evolucao Lima" });
    const tabela = screen.getByRole("table");
    const linha = (nome: string) => within(tabela).getByRole("link", { name: nome }).closest("tr") as HTMLElement;
    const eva = linha("Eva Evolucao Lima");
    for (const texto of ["+1 atividade", "+1 livro", "+2 estrelas", "+1 acerto"]) {
      expect(within(eva).getByText(texto)).toBeInTheDocument();
    }
    const caio = linha("Caio Evolucao Reis");
    for (const texto of ["+3 atividades", "+2 livros", "+1 estrela", "+4 acertos"]) {
      expect(within(caio).getByText(texto)).toBeInTheDocument();
    }
    expect(within(tabela).queryByText(/^\+1 (livros|atividades|estrelas|acertos)$/)).not.toBeInTheDocument();
    // Pódio (até 3 ganhos por cartão): o rótulo acompanha o número.
    const [primeiro] = within(podio()).getAllByRole("listitem");
    expect(within(primeiro).getByText("livro")).toBeInTheDocument();
    expect(within(primeiro).getByText("atividade")).toBeInTheDocument();
    expect(within(primeiro).getByText("estrelas")).toBeInTheDocument();
  });

  it("Matemática: o cabeçalho da média quebra em duas linhas sem mudar o nome da coluna; turma numa linha só", async () => {
    responder("GET", URL_TURMAS, [turmaFake()] as Turma[]);
    responder("GET", URL_MATEMATICA, placarMatific());
    renderComApp(<RankingMatematica />, { rota: "/ranking-matematica", periodo: { preset: "mes" } });

    await screen.findByRole("link", { name: "Davi Mat Souza" });
    const tabela = screen.getByRole("table");
    const cabecalho = within(tabela).getByRole("columnheader", { name: "Pontuação média (no período)" });
    expect(within(cabecalho).getByText("(no período)")).toHaveClass("block");
    // O chip da turma não quebra ("3º Ano A", não "3º / Ano / A").
    expect(within(tabela).getByText("3º Ano A").closest("td")).toHaveClass("whitespace-nowrap");
    // O filtro de turma usa o mesmo ícone (pessoas) das abas irmãs.
    const filtro = screen.getByLabelText("Filtrar por turma ou série");
    expect(filtro.parentElement?.querySelector("svg.lucide-users")).not.toBeNull();
  });
});
