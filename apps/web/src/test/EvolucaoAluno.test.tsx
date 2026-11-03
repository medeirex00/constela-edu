/**
 * Evolução do aluno — honestidade do valor INICIAL (dados fictícios).
 *
 * Sem coleta anterior ao início do período, o backend manda `inicial` = 0 (um zero
 * que ninguém mediu). A API não diz se essa coleta existiu; a tela só afirma
 * "era X no início do período" e mostra a pílula de variação quando há PROVA de
 * uma coleta anterior (algum indicador da mesma plataforma com `inicial` ≠ 0).
 *
 * Celular (revisão das capturas, 31/10): os 7 cartões de variação ficam 2 por linha, e
 * os mini-gráficos desenham na largura real do contêiner (texto no tamanho nominal).
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { Route, Routes } from "react-router-dom";

import EvolucaoAluno from "../pages/EvolucaoAluno";
import { renderComApp, responder, screen, within } from "./utils";

const URL = /\/escolas\/1\/alunos\/10\/evolucao\?dias=30/;
const DIA = 864e5;

type Indicador = { indicador: string; inicial: number; atual: number; variacao: number; percentual: number | null };

function ind(indicador: string, inicial: number, atual: number): Indicador {
  const variacao = Math.round((atual - inicial) * 100) / 100;
  return {
    indicador, inicial, atual, variacao,
    percentual: inicial ? Math.round((variacao / inicial) * 1000) / 10 : null,
  };
}

function resposta({ matific, elefante, indicadores }: {
  matific: Array<Record<string, string | number>>;
  elefante: Array<Record<string, string | number>>;
  indicadores: Indicador[];
}) {
  return {
    aluno_id: 10, nome: "Ana Ficticia",
    linha_do_tempo: { matific, elefante },
    resumo: { dias: 30, indicadores },
  };
}

function montar() {
  renderComApp(
    <Routes>
      <Route path="/alunos/:id/evolucao" element={<EvolucaoAluno />} />
    </Routes>,
    { rota: "/alunos/10/evolucao" },
  );
}

/** O cartão de um indicador (pelo rótulo), dentro de "Variação no período". */
async function cartao(rotulo: string): Promise<HTMLElement> {
  const secao = await screen.findByRole("region", { name: /Variação no período/ });
  const titulo = within(secao).getByText(rotulo, { selector: "p" });
  return titulo.parentElement as HTMLElement;
}

describe("Evolução do aluno — valor inicial só com coleta comprovada", () => {
  it("sem coleta antes do período: não afirma 'era 0,0' nem mostra a pílula", async () => {
    // Primeira coleta 3 dias atrás (bem depois do início dos 30 dias).
    const recente = new Date(Date.now() - 3 * DIA).toISOString();
    responder("GET", URL, resposta({
      matific: [{ data: recente, atividades: 89, estrelas: 154, pontuacao_media: 56.1 }],
      elefante: [],
      indicadores: [
        ind("atividades", 0, 89), ind("estrelas", 0, 154), ind("pontuacao_media", 0, 56.1),
      ],
    }));
    montar();

    const atividades = await cartao("Atividades");
    expect(atividades).toHaveTextContent("89,0");
    expect(within(atividades).queryByText(/era 0,0/)).toBeNull();
    // A pílula (com o sentido "aumento de" para o leitor de tela) não aparece.
    expect(within(atividades).queryByText(/aumento de/)).toBeNull();
    expect(atividades).toHaveTextContent(/sem valor confirmado no início do período \(primeira coleta do período em \d{2}\/\d{2}\)/);
    // Em nenhum cartão.
    expect(screen.queryByText(/era 0,0 no início do período/)).toBeNull();
    // O aviso de "dados só a partir de" continua.
    expect(screen.getByText(/Este aluno tem dados a partir de/)).toBeInTheDocument();
  });

  it("com coleta comprovada antes do período: 'era X' e a pílula, inclusive o zero medido", async () => {
    const recente = new Date(Date.now() - 3 * DIA).toISOString();
    responder("GET", URL, resposta({
      matific: [{ data: recente, atividades: 89, estrelas: 154, pontuacao_media: 56.1 }],
      elefante: [],
      indicadores: [
        // Coleta anterior com 40 atividades e 0 estrelas: o 0 das estrelas é MEDIDO.
        ind("atividades", 40, 89), ind("estrelas", 0, 154), ind("pontuacao_media", 50, 56.1),
      ],
    }));
    montar();

    const atividades = await cartao("Atividades");
    expect(atividades).toHaveTextContent("era 40,0 no início do período");
    expect(within(atividades).getByText(/aumento de/)).toBeInTheDocument();
    const estrelas = await cartao("Estrelas");
    expect(estrelas).toHaveTextContent("era 0,0 no início do período");
    expect(within(estrelas).getByText(/aumento de/)).toBeInTheDocument();
    // Há histórico anterior comprovado: o aviso "não há histórico anterior" seria falso.
    expect(screen.queryByText(/Este aluno tem dados a partir de/)).toBeNull();
  });

  it("plataforma sem nenhuma coleta no período e sem base: '—' e 'sem coleta no período', nunca 0,0", async () => {
    const recente = new Date(Date.now() - 3 * DIA).toISOString();
    responder("GET", URL, resposta({
      matific: [{ data: recente, atividades: 12, estrelas: 30, pontuacao_media: 40 }],
      elefante: [],
      indicadores: [
        ind("atividades", 10, 12), ind("estrelas", 20, 30), ind("pontuacao_media", 35, 40),
        ind("livros_unicos", 0, 0), ind("tempo_leitura_min", 0, 0),
        ind("questoes_tentativas", 0, 0), ind("questoes_acertos", 0, 0),
      ],
    }));
    montar();

    const livros = await cartao("Livros únicos");
    expect(livros).toHaveTextContent("—");
    expect(livros).toHaveTextContent("sem coleta no período");
    expect(livros).not.toHaveTextContent("0,0");
    expect(within(livros).queryByText(/aumento de|queda de|sem variação/)).toBeNull();
    // A outra plataforma, com base comprovada, segue normal.
    expect(await cartao("Atividades")).toHaveTextContent("era 10,0 no início do período");
  });
});

describe("Evolução do aluno — celular", () => {
  afterEach(() => vi.restoreAllMocks());

  function semear() {
    const dias = [5, 4, 3, 2, 1].map((n) => new Date(Date.now() - n * DIA).toISOString());
    responder("GET", URL, resposta({
      matific: dias.map((data, i) => ({ data, atividades: 80 + i, estrelas: 150 + i, pontuacao_media: 55 + i })),
      elefante: dias.map((data, i) => ({ data, livros_unicos: 10 + i, questoes_acertos: 30 + i, tempo_leitura_min: 400 + i })),
      indicadores: [
        ind("atividades", 70, 84), ind("estrelas", 140, 154), ind("pontuacao_media", 50, 59),
        ind("livros_unicos", 8, 14), ind("tempo_leitura_min", 380, 404),
        ind("questoes_tentativas", 40, 50), ind("questoes_acertos", 28, 34),
      ],
    }));
    montar();
  }

  it("os cartões de variação ficam 2 por linha (o 7º ocupa a linha), compactos só abaixo de sm", async () => {
    semear();
    const grade = await screen.findByTestId("variacao-no-periodo");
    expect(grade).toHaveClass("grid-cols-2", "gap-3", "sm:gap-5", "xl:grid-cols-4");
    expect(grade).not.toHaveClass("grid-cols-1");
    expect(grade.className).toContain("max-sm:[&>*:last-child:nth-child(odd)]:col-span-2");
    expect(grade.children).toHaveLength(7);
    expect(grade.children[0]).toHaveClass("p-4", "sm:p-5");
  });

  it("sem medida (jsdom/desktop) os mini-gráficos ficam no desenho de sempre (viewBox 500)", async () => {
    semear();
    const grafico = await screen.findByRole("img", { name: "Matific: Atividades ao longo do tempo" });
    expect(grafico).toHaveAttribute("viewBox", "0 0 500 185");
  });

  it("contêiner de celular: cada mini-gráfico desenha na largura real (1:1)", async () => {
    vi.spyOn(Element.prototype, "clientWidth", "get").mockReturnValue(279);
    semear();
    for (const nome of ["Matific: Atividades ao longo do tempo", "Elefante Letrado: Tempo (min) ao longo do tempo"]) {
      expect(await screen.findByRole("img", { name: nome })).toHaveAttribute("viewBox", "0 0 279 185");
    }
  });

  it("contêiner de desktop medido (duas colunas, ~424 px): o desenho de sempre", async () => {
    vi.spyOn(Element.prototype, "clientWidth", "get").mockReturnValue(424);
    semear();
    expect(await screen.findByRole("img", { name: "Matific: Estrelas ao longo do tempo" }))
      .toHaveAttribute("viewBox", "0 0 500 185");
  });
});
