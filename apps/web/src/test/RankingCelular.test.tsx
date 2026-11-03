/**
 * Ranking no CELULAR (< 640 px) — o que a revisão das capturas de celular cobrou e
 * fica travado aqui. O jsdom não aplica CSS, então se trava a classe que produz o
 * efeito (e que nada do desktop saiu do DOM):
 *   - a coluna da nota QUE ORDENA (Geral, Pontos, Estrelas, Evolução, nota oficial,
 *     média da turma e a métrica da rede) leva `presa-celular` (index.css): fica
 *     presa à direita da tabela que rola, e posição, nome e nota aparecem em toda linha;
 *   - a tabela só tem largura mínima do sm em diante (`sm:min-w-[...]`);
 *   - nenhuma coluna do desktop some: Turma continua coluna; Série só sai no celular
 *     quando TODA turma já traz a série no nome;
 *   - cabeçalho: botões numa coluna de mesma largura; abas em grade de colunas iguais;
 *     seções recolhíveis com o chevron sempre na borda direita.
 */
import { describe, expect, it } from "vitest";

import { CompeticaoLeituraTurno } from "../components/CompeticaoLeituraTurno";
import { DesempenhoDimensao } from "../components/DesempenhoDimensao";
import type { NaoAferidos, RankingItem, RankingLeituraItem, RankingTurno, Turma } from "../lib/types";
import RankingEvolucao from "../pages/RankingEvolucao";
import RankingGeral from "../pages/RankingGeral";
import RankingLeitura from "../pages/RankingLeitura";
import RankingMatematica from "../pages/RankingMatematica";
import Rankings from "../pages/Rankings";
import RankingTurmas from "../pages/RankingTurmas";
import RankingDaRede from "../pages/rede/RankingRede";
import {
  rankingItemFake, renderComApp, responder, screen, turmaFake, userEvent, usuarioFake, within,
} from "./utils";

const URL_TURMAS = "/escolas/1/turmas";
const URL_GERAL = "/escolas/1/ranking";
const URL_LEITURA = "/escolas/1/ranking/leitura";

const QUATRO: RankingItem[] = [
  rankingItemFake({ posicao: 1, aluno_id: 10, nome: "Otávio Fernandes Cruz", n_aferidos: 4 }),
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

/** As células (td) de uma coluna, linha a linha, achada pelo cabeçalho. */
function celulasDaColuna(tabela: HTMLElement, cabecalho: HTMLElement): HTMLElement[] {
  const indice = within(tabela).getAllByRole("columnheader").indexOf(cabecalho);
  expect(indice).toBeGreaterThanOrEqual(0);
  return within(tabela).getAllByRole("row").slice(1)
    .map((linha) => within(linha).getAllByRole("cell")[indice]);
}

/** A coluna inteira (cabeçalho e toda célula) fica presa à direita no celular. */
function esperarColunaPresa(tabela: HTMLElement, cabecalho: HTMLElement) {
  expect(cabecalho).toHaveClass("presa-celular");
  const celulas = celulasDaColuna(tabela, cabecalho);
  expect(celulas.length).toBeGreaterThan(0);
  for (const celula of celulas) {
    expect(celula).toHaveClass("presa-celular");
    expect(celula.textContent).toMatch(/\d/);
  }
}

describe("Ranking no celular: a nota que ordena fica à vista em toda linha", () => {
  it("Geral: a nota geral fica presa; as outras colunas continuam na tabela (desktop igual)", async () => {
    responder("GET", URL_TURMAS, [turmaFake()] as Turma[]);
    responder("GET", URL_GERAL, QUATRO);
    renderComApp(<RankingGeral />, { rota: "/ranking" });

    const link = await screen.findByRole("link", { name: "Davi Rocha" });
    const tabela = screen.getByRole("table");
    // Largura mínima só do sm em diante: no celular a tabela tem o tamanho do conteúdo.
    expect(tabela).toHaveClass("sm:min-w-[600px]");
    expect(tabela).not.toHaveClass("min-w-[600px]");
    esperarColunaPresa(tabela, within(tabela).getByRole("columnheader", { name: "Geral" }));
    // Só a nota que ordena fica presa; as demais seguem na rolagem, todas no DOM.
    for (const coluna of ["#", "Aluno", "Turma", "Matemática", "Leitura"]) {
      const th = within(tabela).getByRole("columnheader", { name: coluna });
      expect(th).not.toHaveClass("presa-celular");
      expect(th).not.toHaveClass("max-sm:hidden");
    }
    // O nome guarda largura no celular (não quebra uma palavra por linha).
    expect(link.parentElement).toHaveClass("max-sm:min-w-[10.5rem]");
    // Filtros: um por linha, com a largura do cartão.
    const barra = screen.getByLabelText("Filtrar por turma ou série").closest(".card");
    expect(barra).toHaveClass("max-sm:grid-cols-1", "max-sm:[&_select]:w-full");
  });

  it("Leitura no período: os PONTOS ficam presos", async () => {
    responder("GET", URL_TURMAS, [turmaFake()] as Turma[]);
    responder("GET", URL_LEITURA, LEITURA);
    renderComApp(<RankingLeitura />, { rota: "/ranking?ver=leitura", periodo: { preset: "mes" } });

    await screen.findByRole("link", { name: "Leitor Dois" });
    const [tabela] = screen.getAllByRole("table");
    esperarColunaPresa(tabela, within(tabela).getByRole("columnheader", { name: "Pontos" }));
    expect(within(tabela).getByRole("columnheader", { name: "Livros" })).not.toHaveClass("presa-celular");
  });

  it("Matemática: as ESTRELAS ficam presas", async () => {
    responder("GET", URL_TURMAS, [turmaFake()] as Turma[]);
    responder("GET", "/escolas/1/sync/matific/placar-ao-vivo", {
      periodo: "Este mês", atualizado_em: "2026-07-14T12:00:00Z", total: 1,
      itens: [{ posicao: 1, aluno_id: 30, nome: "Davi Mat Souza", turma: "3º Ano A", serie: "3",
                estrelas: 40, atividades: 12, pontuacao_media: 3.33 }],
    });
    renderComApp(<RankingMatematica />, { rota: "/ranking-matematica", periodo: { preset: "mes" } });

    await screen.findByRole("link", { name: "Davi Mat Souza" });
    const [tabela] = screen.getAllByRole("table");
    esperarColunaPresa(tabela, within(tabela).getByRole("columnheader", { name: "Estrelas" }));
    expect(within(tabela).getByRole("columnheader", { name: "Atividades" })).not.toHaveClass("presa-celular");
  });

  it("Evolução: a nota de EVOLUÇÃO fica presa", async () => {
    responder("GET", URL_TURMAS, [turmaFake()] as Turma[]);
    responder("GET", "/escolas/1/ranking-evolucao", [
      { posicao: 1, aluno_id: 40, nome: "Eva Evolucao Lima", turma: "3º Ano A", ano_escolar: "3º Ano",
        nota_evolucao: 12, ganhos: { atividades: 1, estrelas: 2, livros: 1, tempo_leitura_min: 0, acertos: 1 } },
    ]);
    renderComApp(<RankingEvolucao />, { rota: "/evolucao" });

    await screen.findByRole("link", { name: "Eva Evolucao Lima" });
    const tabela = screen.getByRole("table");
    esperarColunaPresa(tabela, within(tabela).getByRole("columnheader", { name: "Evolução" }));
    expect(within(tabela).getByRole("columnheader", { name: "Ganhos no período" }))
      .not.toHaveClass("presa-celular");
  });

  it("Classificação oficial e competição por turno: a nota fica presa e o cabeçalho dela quebra linha", async () => {
    const naoAferidos: NaoAferidos = {
      contratadas: ["leitura", "matematica"], total_alunos: 1, dimensoes: [], sem_nenhuma: [],
    };
    responder("GET", URL_GERAL, [{
      ...rankingItemFake({ posicao: 1, aluno_id: 10, nome: "Ana Leitora" }),
      dimensao: "leitura", nota: 91, aferido: true, n_aferidos: 1,
      dados: { livros_unicos: 12, atividades: 30 }, adocao: 100,
    }]);
    responder("GET", "/escolas/1/nao-aferidos", naoAferidos);
    renderComApp(<DesempenhoDimensao dimensao="leitura" filtros={{ turno: "todos" }} />);

    await screen.findByRole("link", { name: "Ana Leitora" });
    const tabela = screen.getByRole("table");
    const nota = within(tabela).getByRole("columnheader", { name: "Nota de Leitura" });
    esperarColunaPresa(tabela, nota);
    expect(nota).toHaveClass("max-sm:whitespace-normal");
  });

  it("Competição por turno: nota presa e abas de turno em grade de colunas iguais", async () => {
    const aluno = (over: Partial<RankingItem>): RankingItem => ({
      posicao: 1, aluno_id: 1, nome: "X", turma: "1A", ano_escolar: "1º Ano",
      nota_matific: 0, nota_elefante: 80, nota_geral: 0, ...over,
    });
    const grupos: RankingTurno[] = [
      { turno: "manha", turno_rotulo: "Manhã", total: 1, alunos: [aluno({ aluno_id: 1, nome: "Cinco Alto" })] },
      { turno: "tarde", turno_rotulo: "Tarde", total: 1, alunos: [aluno({ aluno_id: 3, nome: "Tres Tarde" })] },
    ];
    responder("GET", "/escolas/1/ranking/leitura/turnos", grupos);
    renderComApp(<CompeticaoLeituraTurno />, { usuario: usuarioFake({ cargo: "coordenador" }) });

    await screen.findByRole("link", { name: "Cinco Alto" });
    const tabela = screen.getByRole("table");
    esperarColunaPresa(tabela, within(tabela).getByRole("columnheader", { name: "Nota de Leitura" }));
    const abas = screen.getByRole("tablist", { name: "Turno da competição" });
    expect(abas).toHaveClass("max-sm:grid", "max-sm:grid-cols-2");
    for (const aba of within(abas).getAllByRole("tab")) expect(aba).toHaveClass("max-sm:min-h-10");
  });
});

describe("Ranking de Turmas no celular", () => {
  const frescor = { limite_dias: 7, hoje: "2026-10-20", estado: "em_dia", dimensoes: {} };
  const turma = (posicao: number, id: number, nome: string) => ({
    posicao, turma_id: id, nome, ano_escolar: "3º Ano", turno: "manha",
    media: 70, n_aferidos: 10, total_alunos: 20,
  });

  it("a MÉDIA fica presa (sem a barra) e a Série sai só no celular quando já está no nome", async () => {
    responder("GET", URL_TURMAS, [turmaFake()] as Turma[]);
    responder("GET", "/escolas/1/ranking/turmas", {
      dimensao: "leitura", itens: [turma(1, 1, "3º Ano A"), turma(2, 2, "3º ANO B")], frescor,
    });
    renderComApp(<RankingTurmas />, { rota: "/ranking?ver=turmas" });

    await screen.findByRole("link", { name: "3º ANO B" });
    const tabela = screen.getByRole("table");
    expect(tabela).toHaveClass("sm:min-w-[680px]");
    expect(tabela).not.toHaveClass("min-w-[680px]");
    const media = within(tabela).getByRole("columnheader", { name: "Média de Leitura" });
    esperarColunaPresa(tabela, media);
    expect(media).toHaveClass("max-sm:whitespace-normal");
    // A barra da média é reforço visual: sai no celular; o número fica.
    for (const celula of celulasDaColuna(tabela, media)) {
      expect(celula.querySelector(".bg-gradient-to-r")?.parentElement).toHaveClass("max-sm:hidden");
    }
    // Série repetida no nome de toda turma: some só no celular, continua no DOM.
    const serie = within(tabela).getByRole("columnheader", { name: "Série" });
    expect(serie).toHaveClass("max-sm:hidden");
    for (const celula of celulasDaColuna(tabela, serie)) expect(celula).toHaveClass("max-sm:hidden");
  });

  it("basta uma turma sem a série no nome para a coluna Série ficar também no celular", async () => {
    responder("GET", URL_TURMAS, [turmaFake()] as Turma[]);
    responder("GET", "/escolas/1/ranking/turmas", {
      dimensao: "leitura", itens: [turma(1, 1, "3º Ano A"), turma(2, 2, "Turma Azul")], frescor,
    });
    renderComApp(<RankingTurmas />, { rota: "/ranking?ver=turmas" });

    await screen.findByRole("link", { name: "Turma Azul" });
    const tabela = screen.getByRole("table");
    const serie = within(tabela).getByRole("columnheader", { name: "Série" });
    expect(serie).not.toHaveClass("max-sm:hidden");
    for (const celula of celulasDaColuna(tabela, serie)) expect(celula).not.toHaveClass("max-sm:hidden");
  });
});

it("série como palavra inteira: \"1º Ano\" não conta como presente em \"11º Ano A\"", async () => {
  responder("GET", URL_TURMAS, [turmaFake()] as Turma[]);
  responder("GET", "/escolas/1/ranking/turmas", {
    dimensao: "leitura",
    itens: [{ posicao: 1, turma_id: 1, nome: "11º Ano A", ano_escolar: "1º Ano", turno: "manha", media: 70, n_aferidos: 10, total_alunos: 20 }],
    frescor: { limite_dias: 7, hoje: "2026-10-20", estado: "em_dia", dimensoes: {} },
  });
  renderComApp(<RankingTurmas />, { rota: "/ranking?ver=turmas" });

  await screen.findByRole("link", { name: "11º Ano A" });
  const serie = within(screen.getByRole("table")).getByRole("columnheader", { name: "Série" });
  expect(serie).not.toHaveClass("max-sm:hidden");
});

describe("Cabeçalho do ranking no celular", () => {
  it("botões numa coluna de mesma largura; abas de tipo em 2 × 2 e de categoria numa linha", async () => {
    responder("GET", URL_TURMAS, [turmaFake()] as Turma[]);
    responder("GET", URL_GERAL, QUATRO);
    renderComApp(<Rankings />, { rota: "/ranking" });

    await screen.findByRole("link", { name: "Davi Rocha" });
    const exportar = screen.getByRole("button", { name: /Exportar lista/ });
    const acoes = exportar.parentElement as HTMLElement;
    expect(acoes).toHaveClass("acoes-celular", "max-sm:grid", "max-sm:grid-cols-1", "max-sm:[&>*]:w-full");
    // Os três botões da aba Geral estão na MESMA coluna.
    expect(within(acoes).getByRole("button", { name: /Baixar cartaz/ })).toBeInTheDocument();
    expect(within(acoes).getByRole("button", { name: /Gerar certificados/ })).toBeInTheDocument();
    // A caixa de ações do PageHeader ocupa a linha toda no celular.
    expect(acoes.parentElement).toHaveClass("max-sm:w-full");

    const tipos = screen.getByRole("tablist", { name: "Tipo de ranking" });
    expect(tipos).toHaveClass("max-sm:grid", "max-sm:grid-cols-2");
    for (const aba of within(tipos).getAllByRole("tab")) {
      expect(aba).toHaveClass("max-sm:min-h-10", "max-sm:justify-center");
    }
    const categorias = screen.getAllByRole("tablist", { name: "Categoria do ranking" })[0];
    expect(categorias).toHaveClass("max-sm:grid", "max-sm:grid-flow-col", "max-sm:auto-cols-fr");
  });

  it("seções recolhíveis: o chevron fica na borda direita nas duas (alinhadas entre si)", async () => {
    responder("GET", URL_TURMAS, [turmaFake()] as Turma[]);
    responder("GET", URL_LEITURA, LEITURA);
    renderComApp(<RankingLeitura />, { rota: "/ranking?ver=leitura" });

    await screen.findByRole("link", { name: "Leitor Dois" });
    for (const nome of [/Classificação oficial — Leitura/, /Competição por turno/]) {
      const botao = screen.getByRole("button", { name: nome });
      expect(botao).toHaveAttribute("aria-expanded", "false");
      expect(botao).toHaveClass("max-sm:flex", "max-sm:w-full", "max-sm:justify-between", "max-sm:min-h-10");
      expect(botao.lastElementChild?.tagName.toLowerCase()).toBe("svg");
    }
  });
});

describe("Ranking da Rede no celular", () => {
  const secretaria = usuarioFake({ nome: "Secretaria", cargo: "coordenador", rede_id: 1, escola_id: null });
  const cartao = (escola_id: number, nome: string, pontuacao_geral: number) => ({
    escola_id, nome, cidade: "Jacareí", status: "ativa", latitude: null, longitude: null,
    total_turmas: 5, total_professores: 4, total_alunos: 100, alunos_com_dados: 100, adocao: 100,
    media_geral: 70, media_matific: 70, media_elefante: 70, livros: 0, tempo_leitura_min: 0,
    atividades: 0, estrelas: 0, ativos_matific: 100, ativos_elefante: 100, livros_por_aluno: 0,
    livros_por_matricula: 0, estrelas_por_matricula: 0, atividades_por_matricula: 0,
    tempo_por_matricula_min: 0, pontuacao_leitura: 0, pontuacao_matematica: 0, pontuacao_geral,
    dimensoes_pontuadas: ["leitura", "matematica"], dimensoes_com_dados: ["leitura", "matematica"],
    alunos_com_nota_elefante: 100, alunos_com_nota_matific: 100, adocao_elefante: 100,
    adocao_matific: 100, precisa_atencao: false, motivo_atencao: null,
  });

  it("o ÍNDICE GERAL fica preso (com a faixa dourada do 1º), sem largura mínima no celular", async () => {
    const escolas = [cartao(1, "EMEF Fictícia Vila Constelação", 1000), cartao(2, "Escola Pequena", 750)];
    responder("GET", "/redes/1/dashboard", { rede_id: 1, totais: {}, equidade: {}, atencao: [], escolas });
    responder("GET", /^\/redes\/1\/ranking\?/, escolas.map((e, i) => ({ ...e, posicao: i + 1 })));
    renderComApp(<RankingDaRede />, { usuario: secretaria });

    await screen.findByRole("button", { name: "Escola Pequena" });
    const tabela = screen.getByRole("table");
    expect(tabela).toHaveClass("sm:min-w-[560px]");
    expect(tabela).not.toHaveClass("min-w-[560px]");
    const indice = within(tabela).getByRole("columnheader", { name: /Índice Geral/ });
    esperarColunaPresa(tabela, indice);
    const [primeira, segunda] = celulasDaColuna(tabela, indice);
    expect(primeira).toHaveClass("max-sm:bg-[#fffcf3]");
    expect(segunda).not.toHaveClass("max-sm:bg-[#fffcf3]");

    // Ações do cabeçalho: uma coluna de mesma largura no celular; no desktop o
    // contêiner é `contents` (os botões seguem filhos diretos da caixa de ações).
    const acoes = screen.getByRole("button", { name: /Como funciona o ranking/ }).parentElement as HTMLElement;
    expect(acoes).toHaveClass("contents", "acoes-celular", "max-sm:grid", "max-sm:grid-cols-1");
    expect(within(acoes).getByRole("button", { name: /Exportar lista/ })).toBeInTheDocument();
    expect(acoes.parentElement).toHaveClass("max-sm:w-full"); // caixa de ações do PageHeader

    const abas = screen.getByRole("tablist", { name: "Categoria do ranking" });
    expect(abas).toHaveClass("max-sm:grid", "max-sm:grid-cols-2");
    // Trocar de aba mantém a métrica da aba presa.
    await userEvent.click(within(abas).getByRole("tab", { name: /Leitura/ }));
    const livros = await screen.findByRole("columnheader", { name: /Livros\/aluno/ });
    expect(livros).toHaveClass("presa-celular");
    expect(screen.getByRole("columnheader", { name: /Livros lidos/ })).not.toHaveClass("presa-celular");
  });
});
