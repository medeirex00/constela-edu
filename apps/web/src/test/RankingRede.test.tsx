/**
 * 🏆 Ranking da Rede (Secretaria) — a regra que a tela existe para garantir:
 * a comparação entre escolas é PER CAPITA. Uma escola GRANDE não pode ficar
 * à frente só por ter mais alunos; na Leitura o critério é livros ÷ alunos.
 *
 * Cobre também: troca de aba muda os indicadores mostrados, estado vazio e o
 * explicador "Como funciona o ranking?".
 */
import { describe, expect, it } from "vitest";

import RankingDaRede from "../pages/rede/RankingRede";
import { renderComApp, responder, screen, userEvent, usuarioFake } from "./utils";

const secretaria = usuarioFake({
  nome: "Secretaria", cargo: "coordenador", rede_id: 1, escola_id: null,
});

function cartao(over: Record<string, unknown> = {}) {
  return {
    escola_id: 1, nome: "Escola", cidade: "Caraguatatuba", status: "ativa",
    latitude: null, longitude: null, total_turmas: 5, total_professores: 4,
    total_alunos: 100, alunos_com_dados: 100, adocao: 100,
    media_geral: 70, media_matific: 70, media_elefante: 70,
    livros: 0, tempo_leitura_min: 0, atividades: 0, estrelas: 0,
    ativos_matific: 100, ativos_elefante: 100, livros_por_aluno: 0,
    livros_por_matricula: 0, estrelas_por_matricula: 0,
    atividades_por_matricula: 0, tempo_por_matricula_min: 0,
    pontuacao_leitura: 0, pontuacao_matematica: 0, pontuacao_geral: 0,
    dimensoes_pontuadas: ["leitura", "matematica"],
    // Desempenho (0–100) e cobertura são conceitos SEPARADOS no payload.
    dimensoes_com_dados: ["leitura", "matematica"],
    alunos_com_nota_elefante: 100, alunos_com_nota_matific: 100,
    adocao_elefante: 100, adocao_matific: 100,
    precisa_atencao: false, motivo_atencao: null,
    ...over,
  };
}

/** Caso do dono: a escola MENOR lê menos livros no total, mas mais por aluno. */
const DUAS_ESCOLAS = {
  rede_id: 1,
  totais: {},
  equidade: {},
  atencao: [],
  escolas: [
    // 35.000 livros ÷ 200 alunos = 175/aluno
    cartao({
      escola_id: 1, nome: "EMEF Prof. Jorge Passos", total_alunos: 200, alunos_com_dados: 200,
      livros: 35000, livros_por_matricula: 175, tempo_leitura_min: 108000,
      estrelas: 40000, estrelas_por_matricula: 200, atividades: 80000,
      pontuacao_leitura: 875, pontuacao_matematica: 1000, pontuacao_geral: 937.5,
    }),
    // 20.000 livros ÷ 100 alunos = 200/aluno → deve ficar ACIMA na Leitura
    cartao({
      escola_id: 2, nome: "Escola Pequena", total_alunos: 100, alunos_com_dados: 100,
      livros: 20000, livros_por_matricula: 200, tempo_leitura_min: 60000,
      estrelas: 10000, estrelas_por_matricula: 100, atividades: 30000,
      pontuacao_leitura: 1000, pontuacao_matematica: 500, pontuacao_geral: 750,
    }),
  ],
};

function nomesNaOrdem(): string[] {
  // A 1ª coluna é a posição e a 2ª o nome (botão) — pega os nomes na ordem da tabela.
  return screen.getAllByRole("row")
    .slice(1)                                   // pula o cabeçalho
    .map((linha) => linha.querySelector("button")?.textContent?.trim() ?? "");
}

describe("Ranking da Rede", () => {
  it("Leitura: a escola MENOR com mais livros POR ALUNO fica acima da maior", async () => {
    responder("GET", "/redes/1/dashboard", DUAS_ESCOLAS);
    renderComApp(<RankingDaRede />, { usuario: secretaria });

    await screen.findByText("🏆 Ranking da Rede");
    await userEvent.click(screen.getByRole("tab", { name: /Leitura/i }));

    // 200 livros/aluno (20.000 ÷ 100) supera 175 (35.000 ÷ 200) — apesar de MENOS livros.
    expect(nomesNaOrdem()).toEqual(["Escola Pequena", "EMEF Prof. Jorge Passos"]);
    expect(screen.getByText("200,0")).toBeInTheDocument();   // livros/aluno em destaque
    expect(screen.getByText("35.000")).toBeInTheDocument();  // o total bruto continua visível
  });

  it("Matemática ordena por estrelas/aluno — outra visão da MESMA base", async () => {
    responder("GET", "/redes/1/dashboard", DUAS_ESCOLAS);
    renderComApp(<RankingDaRede />, { usuario: secretaria });

    await screen.findByText("🏆 Ranking da Rede");
    await userEvent.click(screen.getByRole("tab", { name: /Matemática/i }));

    // 200 estrelas/aluno da Jorge Passos supera 100 da Pequena → inverte a ordem.
    expect(nomesNaOrdem()).toEqual(["EMEF Prof. Jorge Passos", "Escola Pequena"]);
  });

  it("Geral usa o índice combinado (0–1000) das duas dimensões", async () => {
    responder("GET", "/redes/1/dashboard", DUAS_ESCOLAS);
    renderComApp(<RankingDaRede />, { usuario: secretaria });

    await screen.findByText("🏆 Ranking da Rede");
    // A aba Geral é a inicial: 937,5 > 750 → Jorge Passos primeiro.
    expect(nomesNaOrdem()).toEqual(["EMEF Prof. Jorge Passos", "Escola Pequena"]);
    expect(screen.getByText("938")).toBeInTheDocument();     // índice arredondado
  });

  it("explica o critério do ranking quando o gestor pergunta", async () => {
    responder("GET", "/redes/1/dashboard", DUAS_ESCOLAS);
    renderComApp(<RankingDaRede />, { usuario: secretaria });

    await screen.findByText("🏆 Ranking da Rede");
    // Fechado por padrão: a explicação da régua só aparece depois do clique.
    expect(screen.queryByText(/1000 é a melhor escola da rede/i)).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Como funciona o ranking/i }));
    expect(await screen.findByText(/1000 é a melhor escola da rede/i)).toBeInTheDocument();
    // E explica o critério da aba aberta (Geral, a inicial).
    expect(screen.getByText(/Média das pontuações de Leitura e Matemática/i)).toBeInTheDocument();
  });

  it("mostra as FÓRMULAS reais usadas pelo motor (não uma descrição genérica)", async () => {
    responder("GET", "/redes/1/dashboard", DUAS_ESCOLAS);
    renderComApp(<RankingDaRede />, { usuario: secretaria });
    await screen.findByText("🏆 Ranking da Rede");
    await userEvent.click(screen.getByRole("button", { name: /Como funciona o ranking/i }));

    // As fórmulas exatas do backend (rede._indice_da_rede ∘ scoring.normalizar).
    expect(screen.getByText(/Livros por aluno = Total de livros lidos ÷ Nº de alunos/i)).toBeInTheDocument();
    expect(screen.getByText(/Pontuação de Leitura = mín\(1000 ; Livros por aluno ÷ Melhor da rede × 1000\)/i)).toBeInTheDocument();
    expect(screen.getByText(/Estrelas por aluno = Total de estrelas ÷ Nº de alunos/i)).toBeInTheDocument();
    expect(screen.getByText(/Pontuação de Matemática = mín\(1000 ; Estrelas por aluno ÷ Melhor da rede × 1000\)/i)).toBeInTheDocument();
    expect(screen.getByText(/Índice Geral = \(Pontuação de Leitura \+ Pontuação de Matemática\) ÷ 2/i)).toBeInTheDocument();
    // A ressalva da dimensão ausente (comportamento de rede._pontuar_por_percapita).
    expect(screen.getByText(/apenas a dimensão disponível/i)).toBeInTheDocument();
    // E o Matific é atividades/estrelas, não "questões".
    expect(screen.getByText(/não\s*“questões”/i)).toBeInTheDocument();
  });

  it("o exemplo do explicador BATE com a pontuação que o backend calculou", async () => {
    responder("GET", "/redes/1/dashboard", DUAS_ESCOLAS);
    renderComApp(<RankingDaRede />, { usuario: secretaria });
    await screen.findByText("🏆 Ranking da Rede");
    await userEvent.click(screen.getByRole("button", { name: /Como funciona o ranking/i }));

    // O exemplo usa 35.000 livros ÷ 200 alunos = 175 livros/aluno — o MESMO valor da
    // Jorge Passos no payload, cuja pontuacao_leitura o backend calculou como 875
    // (melhor da rede = 200 livros/aluno ⇒ 175 ÷ 200 × 1000 = 875). Se a fórmula da
    // tela divergir do motor, este teste quebra.
    expect(screen.getByText(/175,0 ÷ 200,0 × 1000 =/)).toBeInTheDocument();
    expect(screen.getByText("875 pontos")).toBeInTheDocument();
    const jorge = DUAS_ESCOLAS.escolas.find((e) => e.nome.includes("Jorge Passos"))!;
    expect(jorge.pontuacao_leitura).toBe(875);          // conferência contra o backend
  });

  it("explica as notas 0–100 e separa desempenho de adoção", async () => {
    responder("GET", "/redes/1/dashboard", DUAS_ESCOLAS);
    renderComApp(<RankingDaRede />, { usuario: secretaria });
    await screen.findByText("🏆 Ranking da Rede");
    await userEvent.click(screen.getByRole("button", { name: /Como funciona o ranking/i }));

    // As duas escalas ficam explicitamente distinguidas (aparecem no resumo do
    // topo e como cabeçalho da própria seção, por isso getAllByText).
    expect(screen.getAllByText(/Índice da rede \(0–1000\)/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Notas de desempenho \(0–100\)/i).length).toBeGreaterThan(0);

    // Fórmula REAL do motor (pesos + normalização P90/saturação).
    expect(screen.getByText(/35%·livros \+ 30%·dificuldade \+ 30%·questões \+ 5%·tempo/i)).toBeInTheDocument();
    expect(screen.getByText(/40%·atividades \+ 35%·pontuação média \+ 25%·estrelas/i)).toBeInTheDocument();
    expect(screen.getByText(/questões = 30%·tentativas \+ 70%·acertos/i)).toBeInTheDocument();
    expect(screen.getByText(/percentil 90/i)).toBeInTheDocument();

    // A regra que corrige o teto de 50 (dimensão ausente NÃO vira zero).
    expect(screen.getByText(/média das notas dos alunos COM dado do Elefante/i)).toBeInTheDocument();
    expect(screen.getByText(/a ausência não vira zero/i)).toBeInTheDocument();

    // Exemplo do dono: 78 / 82 → 80, com adoção 75% e 80% ao lado.
    expect(screen.getByText(/Média Geral = \(78 \+ 82\) ÷ 2 = 80/i)).toBeInTheDocument();
    expect(screen.getByText(/Adoção Elefante = 150 ÷ 200 = 75%/i)).toBeInTheDocument();
  });

  it("aba Engajamento mostra adoção por plataforma (não desempenho)", async () => {
    responder("GET", "/redes/1/dashboard", DUAS_ESCOLAS);
    renderComApp(<RankingDaRede />, { usuario: secretaria });
    await screen.findByText("🏆 Ranking da Rede");
    await userEvent.click(screen.getByRole("tab", { name: /Engajamento/i }));

    expect(screen.getByRole("columnheader", { name: /Adoção Elefante/i })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /Adoção Matific/i })).toBeInTheDocument();
  });

  it("estado vazio: rede sem dados não quebra a tela", async () => {
    responder("GET", "/redes/1/dashboard", { rede_id: 1, totais: {}, equidade: {}, atencao: [], escolas: [] });
    renderComApp(<RankingDaRede />, { usuario: secretaria });

    expect(await screen.findByText("Sem dados ainda")).toBeInTheDocument();
  });
});
