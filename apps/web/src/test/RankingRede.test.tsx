/**
 * 🏆 Ranking da Rede (Secretaria) — a regra que a tela existe para garantir:
 * a comparação entre escolas é PER CAPITA. Uma escola GRANDE não pode ficar
 * à frente só por ter mais alunos; na Leitura o critério é livros ÷ alunos.
 *
 * A ORDEM e a POSIÇÃO vêm do backend (`/redes/{id}/ranking?metrica=`, coberto
 * em `backend/tests/test_ranking_rede.py`); a tela pede a métrica da aba e só
 * exibe. O mock abaixo devolve a ordem que o backend devolveria.
 *
 * Cobre também: troca de aba muda os indicadores mostrados, estado vazio, o
 * explicador "Como funciona o ranking?", o aviso de dado desatualizado e a "Diferença
 * entre escolas" (a equidade do índice, que veio do Panorama antigo da Secretaria).
 */
import { Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { ApiError, api } from "../lib/api";
import { tempoLeitura } from "../lib/formato";
import VisaoEscola from "../pages/VisaoEscola";
import RankingDaRede from "../pages/rede/RankingRede";
import { renderComApp, responder, screen, userEvent, usuarioFake, within } from "./utils";

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
      escola_id: 1, nome: "EMEF Fictícia Aurora", total_alunos: 200, alunos_com_dados: 200,
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

type Cartao = ReturnType<typeof cartao>;

/** `/redes/1/ranking?metrica=`: a ordem do backend por métrica (com a posição). */
function responderRanking(porMetrica: Record<string, Cartao[]>) {
  responder("GET", /^\/redes\/1\/ranking\?/, (caminho: string) => {
    const metrica = new URLSearchParams(caminho.split("?")[1]).get("metrica") ?? "geral";
    return (porMetrica[metrica] ?? []).map((c, i) => ({ ...c, posicao: i + 1 }));
  });
}

const [AURORA, PEQUENA] = DUAS_ESCOLAS.escolas;
/** A ordem que `rede.ranking_escolas` devolve para as duas escolas. */
const ORDEM_BACKEND = {
  indice_geral: [AURORA, PEQUENA],       // 937,5 > 750
  livros_aluno: [PEQUENA, AURORA],       // 200/aluno > 175/aluno
  estrelas_aluno: [AURORA, PEQUENA],     // 200/aluno > 100/aluno
  engajamento: [AURORA, PEQUENA],        // 100% = 100% → desempate do backend
};

function metricasPedidas(): string[] {
  return (api as unknown as { mock: { calls: unknown[][] } }).mock.calls
    .map((c) => String(c[0]))
    .filter((u) => u.startsWith("/redes/1/ranking?"))
    .map((u) => new URLSearchParams(u.split("?")[1]).get("metrica") ?? "");
}

function nomesNaOrdem(): string[] {
  // A 1ª coluna é a posição e a 2ª o nome (botão) — pega os nomes na ordem da tabela.
  return screen.getAllByRole("row")
    .slice(1)                                   // pula o cabeçalho
    .map((linha) => linha.querySelector("button")?.textContent?.trim() ?? "");
}

describe("Ranking da Rede", () => {
  it("Leitura: a escola MENOR com mais livros POR ALUNO fica acima da maior", async () => {
    responder("GET", "/redes/1/dashboard", DUAS_ESCOLAS);
    responderRanking(ORDEM_BACKEND);
    renderComApp(<RankingDaRede />, { usuario: secretaria });

    await screen.findByText("🏆 Ranking da Rede");
    await userEvent.click(screen.getByRole("tab", { name: /Leitura/i }));

    // 200 livros/aluno (20.000 ÷ 100) supera 175 (35.000 ÷ 200) — apesar de MENOS livros.
    expect(await screen.findByText("200,0")).toBeInTheDocument();
    expect(nomesNaOrdem()).toEqual(["Escola Pequena", "EMEF Fictícia Aurora"]);
    expect(metricasPedidas()).toContain("livros_aluno");
    expect(screen.getByText("200,0")).toBeInTheDocument();   // livros/aluno em destaque
    expect(screen.getByText("35.000")).toBeInTheDocument();  // o total bruto continua visível
  });

  it("Matemática ordena por estrelas/aluno — outra visão da MESMA base", async () => {
    responder("GET", "/redes/1/dashboard", DUAS_ESCOLAS);
    responderRanking(ORDEM_BACKEND);
    renderComApp(<RankingDaRede />, { usuario: secretaria });

    await screen.findByText("🏆 Ranking da Rede");
    await userEvent.click(screen.getByRole("tab", { name: /Matemática/i }));

    // 200 estrelas/aluno da Aurora supera 100 da Pequena → inverte a ordem.
    expect(await screen.findByText("200,0")).toBeInTheDocument();
    expect(metricasPedidas()).toContain("estrelas_aluno");
    expect(nomesNaOrdem()).toEqual(["EMEF Fictícia Aurora", "Escola Pequena"]);
  });

  it("Geral usa o índice combinado (0–1000) das duas dimensões", async () => {
    responder("GET", "/redes/1/dashboard", DUAS_ESCOLAS);
    responderRanking(ORDEM_BACKEND);
    renderComApp(<RankingDaRede />, { usuario: secretaria });

    await screen.findByText("🏆 Ranking da Rede");
    // A aba Geral é a inicial: 937,5 > 750 → Aurora primeiro.
    expect(await screen.findByText("938")).toBeInTheDocument();
    expect(nomesNaOrdem()).toEqual(["EMEF Fictícia Aurora", "Escola Pequena"]);
    expect(metricasPedidas()[0]).toBe("indice_geral");
    expect(screen.getByText("938")).toBeInTheDocument();     // índice arredondado
  });

  it("explica o critério do ranking quando o gestor pergunta", async () => {
    responder("GET", "/redes/1/dashboard", DUAS_ESCOLAS);
    responderRanking(ORDEM_BACKEND);
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
    responderRanking(ORDEM_BACKEND);
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
    responderRanking(ORDEM_BACKEND);
    renderComApp(<RankingDaRede />, { usuario: secretaria });
    await screen.findByText("🏆 Ranking da Rede");
    await userEvent.click(screen.getByRole("button", { name: /Como funciona o ranking/i }));

    // O exemplo usa 35.000 livros ÷ 200 alunos = 175 livros/aluno — o MESMO valor da
    // Aurora no payload, cuja pontuacao_leitura o backend calculou como 875
    // (melhor da rede = 200 livros/aluno ⇒ 175 ÷ 200 × 1000 = 875). Se a fórmula da
    // tela divergir do motor, este teste quebra.
    expect(screen.getByText(/175,0 ÷ 200,0 × 1000 =/)).toBeInTheDocument();
    expect(screen.getByText("875 pontos")).toBeInTheDocument();
    const aurora = DUAS_ESCOLAS.escolas.find((e) => e.nome.includes("Aurora"))!;
    expect(aurora.pontuacao_leitura).toBe(875);          // conferência contra o backend
  });

  it("explica as notas 0–100 e separa desempenho de adoção", async () => {
    responder("GET", "/redes/1/dashboard", DUAS_ESCOLAS);
    responderRanking(ORDEM_BACKEND);
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
    // R (percentil 90) e k definidos uma vez e citados de novo no bloco do Matific.
    expect(screen.getByRole("dialog")).toHaveTextContent(/percentil 90 dos alunos que usam/i);

    // A regra que corrige o teto de 50 (dimensão ausente NÃO vira zero).
    expect(screen.getByText(/média das notas dos alunos COM dado do Elefante/i)).toBeInTheDocument();
    expect(screen.getByText(/a ausência não vira zero/i)).toBeInTheDocument();

    // Exemplo do dono: 78 / 82 → 80, com adoção 75% e 80% ao lado.
    expect(screen.getByText(/Média Geral = \(78 \+ 82\) ÷ 2 = 80/i)).toBeInTheDocument();
    expect(screen.getByText(/Adoção Elefante = 150 ÷ 200 = 75%/i)).toBeInTheDocument();
  });

  // O Panorama da Rede não mostra mais as médias 0–100: o explicador aponta para onde elas
  // ficam — os totais da tela das plataformas (com o nome do menu) e a Visão da Escola.
  it("diz onde estão as notas 0–100 hoje (tela das plataformas e Visão da Escola), não o Panorama", async () => {
    responder("GET", "/redes/1/dashboard", DUAS_ESCOLAS);
    responderRanking(ORDEM_BACKEND);
    renderComApp(<RankingDaRede />, { usuario: secretaria });
    await screen.findByText("🏆 Ranking da Rede");
    await userEvent.click(screen.getByRole("button", { name: /Como funciona o ranking/i }));

    const modal = screen.getByRole("dialog");
    expect(modal).not.toHaveTextContent(/Panorama/);
    expect(modal).toHaveTextContent(
      "as médias de Leitura/Matemática da tela Elefante e Matific (nos totais, na linha “Média das notas”) e da Visão da Escola.",
    );
    expect(modal).toHaveTextContent("② Notas de desempenho (0–100) — as médias das plataformas");
  });

  it("rede só com o Matific: o explicador nomeia a tela como o menu dela (Matific)", async () => {
    responder("GET", "/redes/1/dashboard", { ...DUAS_ESCOLAS, modulos: ["matematica"] });
    responderRanking(ORDEM_BACKEND);
    renderComApp(<RankingDaRede />, { usuario: secretaria });
    await screen.findByText("🏆 Ranking da Rede");
    await userEvent.click(screen.getByRole("button", { name: /Como funciona o ranking/i }));

    expect(screen.getByRole("dialog")).toHaveTextContent("da tela Matific (nos totais");
  });

  // Revisão da rodada 2 (achado 12): R e k só eram definidos dentro do bloco da Leitura, e a
  // rede só com o Matific lia "Mesma normalização (P90…)" sem a definição na tela.
  it("rede só com o Matific: o explicador define R (percentil 90) e k (mediana) sem o bloco da Leitura", async () => {
    responder("GET", "/redes/1/dashboard", { ...DUAS_ESCOLAS, modulos: ["matematica"] });
    responderRanking(ORDEM_BACKEND);
    renderComApp(<RankingDaRede />, { usuario: secretaria });
    await screen.findByText("🏆 Ranking da Rede");
    await userEvent.click(screen.getByRole("button", { name: /Como funciona o ranking/i }));

    const modal = screen.getByRole("dialog");
    expect(modal).not.toHaveTextContent("Nota de Leitura (0–100)");     // o bloco da Leitura não existe
    expect(modal).toHaveTextContent(
      "R = referência da escola (o percentil 90 dos alunos que usam — escola pequena usa o maior valor). "
      + "k = a mediana, que dá “retornos decrescentes” ao volume",
    );
    expect(modal).toHaveTextContent(
      "A mesma normalização acima (R = percentil 90 da escola; k = mediana no volume), com os indicadores do Matific:",
    );
    expect(modal).not.toHaveTextContent("P90");
  });

  // Achado 5: a leitura do índice usa o contador VITALÍCIO do Elefante (só o Matific é cortado no
  // ano letivo); a tela dizia "ano letivo corrente" para o índice inteiro.
  it("cabeçalho diz o período real de cada plataforma (Elefante acumulado; Matific no ano letivo)", async () => {
    responder("GET", "/redes/1/dashboard", DUAS_ESCOLAS);
    responderRanking(ORDEM_BACKEND);
    renderComApp(<RankingDaRede />, { usuario: secretaria });

    expect(await screen.findByText(/2 escola\(s\)/)).toHaveTextContent(
      "2 escola(s) • alunos do ano letivo corrente (Elefante: acumulado desde o início da conta; "
      + "Matific: no ano letivo) • comparação proporcional ao tamanho da escola",
    );
  });

  it("cabeçalho segue os módulos: só Matific não cita o Elefante; só Elefante não cita o Matific", async () => {
    responder("GET", "/redes/1/dashboard", { ...DUAS_ESCOLAS, modulos: ["matematica"] });
    responderRanking(ORDEM_BACKEND);
    const { unmount } = renderComApp(<RankingDaRede />, { usuario: secretaria });
    const soMatific = await screen.findByText(/2 escola\(s\)/);
    expect(soMatific).toHaveTextContent("alunos do ano letivo corrente (Matific: no ano letivo)");
    expect(soMatific).not.toHaveTextContent("Elefante");
    unmount();

    responder("GET", "/redes/1/dashboard", { ...DUAS_ESCOLAS, modulos: ["leitura"] });
    renderComApp(<RankingDaRede />, { usuario: secretaria });
    const soElefante = await screen.findByText(/2 escola\(s\)/);
    expect(soElefante).toHaveTextContent("alunos do ano letivo corrente (Elefante: acumulado desde o início da conta)");
    expect(soElefante).not.toHaveTextContent("Matific");
  });

  it("aba Leitura: livros, horas e livros/aluno dizem que são o acumulado desde o início da conta no Elefante", async () => {
    responder("GET", "/redes/1/dashboard", DUAS_ESCOLAS);
    responderRanking(ORDEM_BACKEND);
    renderComApp(<RankingDaRede />, { usuario: secretaria });
    await screen.findByText("🏆 Ranking da Rede");
    await userEvent.click(screen.getByRole("tab", { name: /Leitura/i }));

    const acumulado = expect.stringContaining("acumulado desde o início da conta no Elefante");
    expect(await screen.findByRole("columnheader", { name: /Livros lidos/ })).toHaveAttribute("title", acumulado);
    expect(screen.getByRole("columnheader", { name: /Horas lidas/ })).toHaveAttribute("title", acumulado);
    expect(screen.getByRole("columnheader", { name: /Livros\/aluno/ })).toHaveAttribute("title", acumulado);
  });

  it("clicar numa escola abre a Visão da Escola com o Voltar para este ranking (com o que havia na URL)", async () => {
    responder("GET", "/redes/1/dashboard", DUAS_ESCOLAS);
    responderRanking(ORDEM_BACKEND);
    renderComApp(
      <Routes>
        <Route path="/rede/ranking" element={<RankingDaRede />} />
        <Route path="/escola" element={<VisaoEscola />} />
      </Routes>,
      { usuario: secretaria, rota: "/rede/ranking?rede=1" },
    );
    await screen.findByText("🏆 Ranking da Rede");
    const [aurora] = await screen.findAllByRole("button", { name: /EMEF Fictícia Aurora/ });
    await userEvent.click(aurora);

    const voltar = await screen.findByRole("link", { name: "Voltar ao Ranking da Rede" });
    expect(voltar).toHaveAttribute("href", "/rede/ranking?rede=1");
  });

  it("aba Engajamento mostra adoção por plataforma (não desempenho)", async () => {
    responder("GET", "/redes/1/dashboard", DUAS_ESCOLAS);
    responderRanking(ORDEM_BACKEND);
    renderComApp(<RankingDaRede />, { usuario: secretaria });
    await screen.findByText("🏆 Ranking da Rede");
    await userEvent.click(screen.getByRole("tab", { name: /Engajamento/i }));

    expect(screen.getByRole("columnheader", { name: /Adoção Elefante/i })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /Adoção Matific/i })).toBeInTheDocument();
  });

  // Achado 7: "Participação" aqui era adoção (qualquer dado de plataforma ÷ alunos da escola);
  // na tela Escolas, "Participação" é só quem leu ou fez atividade no período.
  it("aba Engajamento ordena por 'Adoção (alguma plataforma)', não por 'Participação' (a da tela Escolas)", async () => {
    responder("GET", "/redes/1/dashboard", DUAS_ESCOLAS);
    responderRanking(ORDEM_BACKEND);
    renderComApp(<RankingDaRede />, { usuario: secretaria });
    await screen.findByText("🏆 Ranking da Rede");
    await userEvent.click(screen.getByRole("tab", { name: /Engajamento/i }));

    const adocao = await screen.findByRole("columnheader", { name: /Adoção \(alguma plataforma\)/ });
    expect(adocao).toHaveTextContent("Adoção");                       // o rótulo curto (celular)
    expect(adocao).toHaveAttribute("title", expect.stringContaining("mesmo sem leitura ou atividade"));
    expect(screen.queryByRole("columnheader", { name: /Particip/ })).toBeNull();
    expect(screen.getByText(/Ordem desta aba/)).toHaveTextContent("Ordem desta aba: Adoção (alguma plataforma)");

    await userEvent.click(screen.getByRole("button", { name: /Como funciona o ranking/i }));
    const modal = screen.getByRole("dialog");
    expect(modal).toHaveTextContent(
      "Ordenado por ADOÇÃO (alunos com dado de alguma plataforma, mesmo sem leitura ou atividade, "
      + "÷ todos os alunos da escola, Fases incluídas).",
    );
    expect(modal).toHaveTextContent(
      "Não é a “Participação” da tela Escolas, que conta só quem leu ou fez atividade no período.",
    );
    expect(modal).not.toHaveTextContent("Comparar escolas");
    expect(modal).not.toHaveTextContent("PARTICIPAÇÃO");
    expect(modal).toHaveTextContent("75%/80% é adoção");              // o exemplo usa o mesmo nome
  });

  it("aba Engajamento numa rede só com o Elefante: a 'Participação' da tela Escolas é só quem leu", async () => {
    responder("GET", "/redes/1/dashboard", { ...DUAS_ESCOLAS, modulos: ["leitura"] });
    responderRanking(ORDEM_BACKEND);
    renderComApp(<RankingDaRede />, { usuario: secretaria });
    await screen.findByText("🏆 Ranking da Rede");
    await userEvent.click(screen.getByRole("tab", { name: /Engajamento/i }));
    await userEvent.click(screen.getByRole("button", { name: /Como funciona o ranking/i }));

    const modal = screen.getByRole("dialog");
    expect(modal).toHaveTextContent("Não é a “Participação” da tela Escolas, que conta só quem leu no período.");
    expect(modal).not.toHaveTextContent("fez atividade");
  });

  // Achado 12: o selo "Baixa" (vermelho) não dizia o corte em lugar nenhum.
  it("coluna Nível diz o critério (title) e a explicação da aba termina com ele", async () => {
    responder("GET", "/redes/1/dashboard", DUAS_ESCOLAS);
    responderRanking(ORDEM_BACKEND);
    renderComApp(<RankingDaRede />, { usuario: secretaria });
    await screen.findByText("🏆 Ranking da Rede");
    await userEvent.click(screen.getByRole("tab", { name: /Engajamento/i }));

    const criterio = "Nível (resumo da adoção): Alta a partir de 80%, Média de 40% a 79,9%, Baixa abaixo de 40%.";
    expect(await screen.findByRole("columnheader", { name: "Nível" })).toHaveAttribute("title", criterio);
    expect(screen.getByRole("columnheader", { name: /Livros\/aluno \(1º–5º\)/ }))
      .toHaveAttribute("title", expect.stringContaining("acumulado desde o início da conta no Elefante"));

    await userEvent.click(screen.getByRole("button", { name: /Como funciona o ranking/i }));
    const explicacao = within(screen.getByRole("dialog")).getByText(/Aba aberta \(Engajamento\)/).closest("p");
    expect(explicacao?.textContent?.endsWith(`cada uma pede uma ação diferente. ${criterio}`)).toBe(true);
  });

  it("estado vazio: rede sem dados não quebra a tela", async () => {
    responder("GET", "/redes/1/dashboard", { rede_id: 1, totais: {}, equidade: {}, atencao: [], escolas: [] });
    responderRanking({});
    renderComApp(<RankingDaRede />, { usuario: secretaria });

    expect(await screen.findByText("Sem dados ainda")).toBeInTheDocument();
  });

  it("a posição é a do backend: a tela não reordena nem desempata por conta própria", async () => {
    // Empate de índice: o backend desempata pela adoção da dimensão e pelo nome
    // em casefold. A tela antiga desempatava por adoção geral e `localeCompare`
    // — e poria "Árvore" antes de "Bosque". Ela tem de mostrar a ordem recebida.
    const bosque = cartao({ escola_id: 3, nome: "Bosque", alunos_com_dados: 10 });
    const arvore = cartao({ escola_id: 4, nome: "Árvore", alunos_com_dados: 10 });
    responder("GET", "/redes/1/dashboard", { ...DUAS_ESCOLAS, escolas: [arvore, bosque] });
    responderRanking({ indice_geral: [bosque, arvore] });
    renderComApp(<RankingDaRede />, { usuario: secretaria });

    await screen.findByText("🏆 Ranking da Rede");
    expect(await screen.findByRole("button", { name: "Bosque" })).toBeInTheDocument();
    expect(nomesNaOrdem()).toEqual(["Bosque", "Árvore"]);
  });

  it("avisa quando o dado de uma escola passou do limite", async () => {
    responder("GET", "/redes/1/dashboard", DUAS_ESCOLAS);
    responderRanking(ORDEM_BACKEND);
    const bloco = (over: Record<string, unknown>) => ({
      plataforma: "elefante", contratada: true, estado: "em_dia",
      dado_mais_recente_em: "2026-10-19", dado_mais_antigo_em: "2026-10-19",
      dias_desde_dado: 1, alunos_com_dado: 100, alunos_com_dado_antigo: 0,
      ultima_sincronizacao_ok_em: null, dias_desde_sincronizacao_ok: null, ...over,
    });
    responder("GET", "/redes/1/ranking/frescor", {
      limite_dias: 7, hoje: "2026-10-20",
      escolas: [
        { escola_id: 1, nome: "EMEF Fictícia Aurora", limite_dias: 7, hoje: "2026-10-20",
          estado: "desatualizado",
          dimensoes: {
            leitura: bloco({ estado: "desatualizado", dado_mais_recente_em: "2026-10-01",
              dias_desde_dado: 19 }),
            matematica: bloco({ plataforma: "matific" }),
          } },
        { escola_id: 2, nome: "Escola Pequena", limite_dias: 7, hoje: "2026-10-20",
          estado: "em_dia",
          dimensoes: { leitura: bloco({}), matematica: bloco({ plataforma: "matific" }) } },
      ],
    });
    renderComApp(<RankingDaRede />, { usuario: secretaria });

    await screen.findByText("🏆 Ranking da Rede");
    const aviso = await screen.findByRole("status");
    expect(aviso).toHaveTextContent(/1 escola\(s\) deste ranking com dado de mais de 7 dias/);
    expect(aviso).toHaveTextContent(/EMEF Fictícia Aurora \(dados de 01\/10\/2026\)/);
    expect(screen.getByText("dados de 01/10/2026")).toBeInTheDocument();
    // A escola em dia também diz de quando é o dado (sem o tom de alerta).
    expect(screen.getByText("dados de 19/10/2026")).toBeInTheDocument();

    // Na aba Matemática o dado das duas está em dia: sem aviso.
    await userEvent.click(screen.getByRole("tab", { name: /Matemática/i }));
    expect(await screen.findByText("200,0")).toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("per capita só de quem concorre: as colunas mostram alunos e livros do 1º ao 5º ano", async () => {
    // Patch A do backend: `*_premiaveis` = numerador e denominador do per capita
    // sem as Fases. A tela mostra ESSES números ao lado de livros/aluno, para a
    // conta conferir (16 ÷ 2 = 8,0), e não o total com a Educação Infantil.
    const comFase = cartao({
      escola_id: 9, nome: "Escola Com EMEI", total_alunos: 3, livros: 66,
      alunos_premiaveis: 2, livros_premiaveis: 16, livros_por_matricula: 8,
    });
    responder("GET", "/redes/1/dashboard", { ...DUAS_ESCOLAS, escolas: [comFase] });
    responderRanking({ livros_aluno: [comFase] });
    renderComApp(<RankingDaRede />, { usuario: secretaria });

    await screen.findByText("🏆 Ranking da Rede");
    await userEvent.click(screen.getByRole("tab", { name: /Leitura/i }));
    expect(await screen.findByText("8,0")).toBeInTheDocument();
    expect(screen.getByText("16")).toBeInTheDocument();
    expect(screen.queryByText("66")).not.toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /Alunos \(1º–5º\)/ })).toBeInTheDocument();
  });

  it("Horas lidas é da MESMA população de Alunos (1º–5º) e Livros lidos", async () => {
    // 700 min no total (com a Fase) e 200 só de quem concorre: a linha mostra 200.
    const comFase = cartao({
      escola_id: 9, nome: "Escola Com EMEI", total_alunos: 3, livros: 66,
      tempo_leitura_min: 700, alunos_premiaveis: 2, livros_premiaveis: 16,
      tempo_premiaveis_min: 200, livros_por_matricula: 8,
    });
    responder("GET", "/redes/1/dashboard", { ...DUAS_ESCOLAS, escolas: [comFase] });
    responderRanking({ livros_aluno: [comFase] });
    renderComApp(<RankingDaRede />, { usuario: secretaria });

    await screen.findByText("🏆 Ranking da Rede");
    await userEvent.click(screen.getByRole("tab", { name: /Leitura/i }));
    expect(await screen.findByText("8,0")).toBeInTheDocument();
    expect(screen.getByText(tempoLeitura(200))).toBeInTheDocument();
    expect(screen.queryByText(tempoLeitura(700))).not.toBeInTheDocument();
  });

  it("Engajamento: o livros/aluno diz o denominador (1º–5º), que não é a coluna Alunos", async () => {
    responder("GET", "/redes/1/dashboard", DUAS_ESCOLAS);
    responderRanking(ORDEM_BACKEND);
    renderComApp(<RankingDaRede />, { usuario: secretaria });
    await screen.findByText("🏆 Ranking da Rede");
    await userEvent.click(screen.getByRole("tab", { name: /Engajamento/i }));

    expect(await screen.findByRole("columnheader", { name: /Livros\/aluno \(1º–5º\)/ }))
      .toBeInTheDocument();
  });

  it("troca de aba: enquanto a nova ordem carrega, a ordem da aba anterior não aparece", async () => {
    responder("GET", "/redes/1/dashboard", DUAS_ESCOLAS);
    responder("GET", /^\/redes\/1\/ranking\?/, (caminho: string) => {
      const metrica = new URLSearchParams(caminho.split("?")[1]).get("metrica");
      if (metrica === "livros_aluno") return new Promise(() => {});      // não responde
      return ORDEM_BACKEND.indice_geral.map((c, i) => ({ ...c, posicao: i + 1 }));
    });
    renderComApp(<RankingDaRede />, { usuario: secretaria });

    expect(await screen.findByText("938")).toBeInTheDocument();           // Geral carregado
    await userEvent.click(screen.getByRole("tab", { name: /Leitura/i }));
    expect(await screen.findByText("Carregando o ranking da rede...")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.queryByText("938")).not.toBeInTheDocument();
  });

  it("troca de aba com falha: mostra o erro, nunca a ordem da aba anterior", async () => {
    responder("GET", "/redes/1/dashboard", DUAS_ESCOLAS);
    responder("GET", /^\/redes\/1\/ranking\?/, (caminho: string) => {
      const metrica = new URLSearchParams(caminho.split("?")[1]).get("metrica");
      if (metrica === "livros_aluno") throw new ApiError(500, "Falha de teste no ranking");
      return ORDEM_BACKEND.indice_geral.map((c, i) => ({ ...c, posicao: i + 1 }));
    });
    renderComApp(<RankingDaRede />, { usuario: secretaria });

    expect(await screen.findByText("938")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: /Leitura/i }));
    expect(await screen.findByText("Falha de teste no ranking", {}, { timeout: 3000 }))
      .toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();

    // De volta à Geral, a ordem dela reaparece (e o erro da Leitura some).
    await userEvent.click(screen.getByRole("tab", { name: /Geral/i }));
    expect(await screen.findByText("938")).toBeInTheDocument();
    expect(screen.queryByText("Falha de teste no ranking")).not.toBeInTheDocument();
  });

  it("aba Geral: a Leitura parada não some atrás da Matemática sem dados", async () => {
    // Rede com as duas dimensões contratadas; a escola só usa o Elefante, com a
    // última coleta há 19 dias, e não tem retrato do Matific. O pior estado da
    // aba é o ATRASO da Leitura — "sem dados" da Matemática não é atraso.
    responder("GET", "/redes/1/dashboard", DUAS_ESCOLAS);
    const soLeitura = { ...AURORA, dimensoes_pontuadas: ["leitura"] };
    responderRanking({ indice_geral: [soLeitura, PEQUENA] });
    const bloco = (over: Record<string, unknown>) => ({
      plataforma: "elefante", contratada: true, estado: "em_dia",
      dado_mais_recente_em: "2026-10-19", dado_mais_antigo_em: "2026-10-19",
      dias_desde_dado: 1, alunos_com_dado: 100, alunos_com_dado_antigo: 0,
      ultima_sincronizacao_ok_em: null, dias_desde_sincronizacao_ok: null, ...over,
    });
    responder("GET", "/redes/1/ranking/frescor", {
      limite_dias: 7, hoje: "2026-10-20",
      escolas: [
        { escola_id: 1, nome: "EMEF Fictícia Aurora", limite_dias: 7, hoje: "2026-10-20",
          estado: "sem_dados",
          dimensoes: {
            leitura: bloco({ estado: "desatualizado", dado_mais_recente_em: "2026-10-01",
              dias_desde_dado: 19 }),
            matematica: bloco({ plataforma: "matific", estado: "sem_dados",
              dado_mais_recente_em: null, dado_mais_antigo_em: null, dias_desde_dado: null,
              alunos_com_dado: 0 }),
          } },
        { escola_id: 2, nome: "Escola Pequena", limite_dias: 7, hoje: "2026-10-20",
          estado: "em_dia",
          dimensoes: { leitura: bloco({}), matematica: bloco({ plataforma: "matific" }) } },
      ],
    });
    renderComApp(<RankingDaRede />, { usuario: secretaria });

    await screen.findByText("🏆 Ranking da Rede");
    const aviso = await screen.findByRole("status");
    expect(aviso).toHaveTextContent(/EMEF Fictícia Aurora \(dados de 01\/10\/2026\)/);
    expect(screen.getByText("dados de 01/10/2026")).toBeInTheDocument();
  });
});

describe("Ranking da Rede — Secretaria com escola protegida (grupo pequeno)", () => {
  const TEXTO = "Menos de 3 alunos com dado nesta matéria na escola: para proteger as crianças, a média e os totais não aparecem.";
  // Leitura escondida (1 aluno com dado), Matemática visível: a escola segue no Geral pela
  // matemática, mas a coluna Leitura mostra "—" e ela sai da aba Leitura.
  const PROTEGIDA = cartao({
    escola_id: 3, nome: "EMEF Fictícia Protegida", total_alunos: 40,
    media_elefante: null, livros: null, tempo_leitura_min: null, livros_por_aluno: null,
    livros_por_matricula: null, tempo_por_matricula_min: null, pontuacao_leitura: null,
    estrelas: 3000, estrelas_por_matricula: 75, atividades: 6000, pontuacao_matematica: 375, pontuacao_geral: 375,
    dimensoes_pontuadas: ["matematica"],
    grupo_pequeno: true, oculto: { leitura: { motivo: "grupo_pequeno", texto: TEXTO, parcial: false }, matematica: null },
  });
  const DASH = {
    ...DUAS_ESCOLAS,
    escolas: [...DUAS_ESCOLAS.escolas, PROTEGIDA],
    ocultas: [{ escola_id: 3, nome: "EMEF Fictícia Protegida", grupo_pequeno: true, oculto: PROTEGIDA.oculto }],
  };

  it("Geral: a matéria escondida aparece como '—' (nunca 0)", async () => {
    responder("GET", "/redes/1/dashboard", DASH);
    responderRanking({ ...ORDEM_BACKEND, indice_geral: [AURORA, PEQUENA, PROTEGIDA] });
    renderComApp(<RankingDaRede />, { usuario: secretaria });

    const nome = await screen.findByRole("button", { name: "EMEF Fictícia Protegida" });
    const linha = nome.closest("tr") as HTMLElement;
    const celulas = [...linha.querySelectorAll("td")].map((td) => td.textContent?.trim());
    expect(celulas).toContain("—");       // Leitura
    expect(celulas).toContain("375");     // Matemática e Índice Geral continuam
    expect(celulas).not.toContain("0");
    // Está no Geral: nada de aviso "fora deste ranking" nesta aba.
    expect(screen.queryByText(/Fora deste ranking para proteger as crianças/)).toBeNull();
  });

  it("Leitura: a escola sai da ordem e o aviso diz quem e por quê", async () => {
    responder("GET", "/redes/1/dashboard", DASH);
    responderRanking(ORDEM_BACKEND);  // livros_aluno sem a protegida, como o backend devolve
    renderComApp(<RankingDaRede />, { usuario: secretaria });

    await screen.findByText("🏆 Ranking da Rede");
    await userEvent.click(screen.getByRole("tab", { name: /Leitura/i }));
    expect(await screen.findByText(/Fora deste ranking para proteger as crianças/)).toHaveTextContent("EMEF Fictícia Protegida");
    expect(nomesNaOrdem()).toEqual(["Escola Pequena", "EMEF Fictícia Aurora"]);
    // A protegida não é "fora da comparação": não aparece nas duas notas.
    expect(screen.queryByText(/Fora da comparação/)).toBeNull();
  });
});

describe("Ranking da Rede — escola fora da comparação", () => {
  // Revisão de prontidão (01/11): o cabeçalho dizia "3 escola(s)" sobre uma ordem de 2, e
  // a escola fora da comparação sumia sem explicação. O critério é o do backend
  // (`comparada` do cartão: algum aluno do 1º ao 5º ano com dado), igual nas 4 abas.
  const SEM_DADO = cartao({
    escola_id: 9, nome: "EMEF Fictícia Sem Dado", total_alunos: 30, alunos_com_dados: 0,
    adocao: 0, dimensoes_pontuadas: [], comparada: false,
  });
  // Só a 1ª Fase usa as plataformas: tem adoção, mas não concorre.
  const SO_FASE = cartao({
    escola_id: 10, nome: "EMEF Fictícia Só Fase", total_alunos: 4, alunos_com_dados: 4,
    adocao: 100, dimensoes_pontuadas: [], comparada: false,
  });

  it("a escola fora da comparação é nomeada abaixo do ranking, com o critério real", async () => {
    responder("GET", "/redes/1/dashboard", { ...DUAS_ESCOLAS, escolas: [...DUAS_ESCOLAS.escolas, SEM_DADO] });
    responderRanking(ORDEM_BACKEND);
    renderComApp(<RankingDaRede />, { usuario: secretaria });

    const nota = await screen.findByText(/Fora da comparação/);
    expect(nota).toHaveTextContent("nenhum aluno do 1º ao 5º ano com dado das plataformas contratadas");
    // "alunos do ano letivo", não "dado no ano letivo": o contador do Elefante é vitalício.
    expect(nota).toHaveTextContent("entre os alunos do ano letivo corrente");
    expect(nota).toHaveTextContent("EMEF Fictícia Sem Dado");
    expect(screen.getByText(/3 escola\(s\)/)).toBeInTheDocument();
    expect(nomesNaOrdem()).toEqual(["EMEF Fictícia Aurora", "Escola Pequena"]);
  });

  it("aba Engajamento: a escola com adoção só da Fase é 'fora da comparação', nunca 'sem dado'", async () => {
    responder("GET", "/redes/1/dashboard", { ...DUAS_ESCOLAS, escolas: [...DUAS_ESCOLAS.escolas, SO_FASE] });
    responderRanking(ORDEM_BACKEND);
    renderComApp(<RankingDaRede />, { usuario: secretaria });

    await screen.findByText("🏆 Ranking da Rede");
    await userEvent.click(screen.getByRole("tab", { name: /Engajamento/i }));
    expect(await screen.findByText(/Fora da comparação/)).toHaveTextContent("EMEF Fictícia Só Fase");
    expect(screen.queryByText(/[Ss]em dado/)).toBeNull();
  });

  it("fora da ordem mas COMPARADA (ex.: cartão desatualizado): não se afirma nada", async () => {
    responder("GET", "/redes/1/dashboard", {
      ...DUAS_ESCOLAS, escolas: [...DUAS_ESCOLAS.escolas, cartao({ escola_id: 11, nome: "EMEF Fictícia Nova", comparada: true })],
    });
    responderRanking(ORDEM_BACKEND);
    renderComApp(<RankingDaRede />, { usuario: secretaria });

    await screen.findByRole("button", { name: "Escola Pequena" });
    expect(screen.queryByText(/Fora da comparação/)).toBeNull();
  });

  it("todas na ordem: nenhuma nota", async () => {
    responder("GET", "/redes/1/dashboard", DUAS_ESCOLAS);
    responderRanking(ORDEM_BACKEND);
    renderComApp(<RankingDaRede />, { usuario: secretaria });

    await screen.findByRole("button", { name: "Escola Pequena" });
    expect(screen.queryByText(/Fora da comparação/)).toBeNull();
  });

  it("enquanto a ordem da aba carrega, nenhuma escola é nomeada", async () => {
    responder("GET", "/redes/1/dashboard", {
      ...DUAS_ESCOLAS, escolas: [...DUAS_ESCOLAS.escolas, SEM_DADO],
      ocultas: [{ escola_id: 9, nome: "EMEF Fictícia Sem Dado", grupo_pequeno: true,
                  oculto: { leitura: { motivo: "grupo_pequeno", texto: "x", parcial: false }, matematica: null } }],
    });
    responder("GET", /^\/redes\/1\/ranking\?/, () => new Promise(() => undefined));
    renderComApp(<RankingDaRede />, { usuario: secretaria });

    await screen.findByText("🏆 Ranking da Rede");
    expect(screen.getByText("Carregando o ranking da rede...")).toBeInTheDocument();
    expect(screen.queryByText(/Fora da comparação/)).toBeNull();
    expect(screen.queryByText(/Fora deste ranking/)).toBeNull();
  });

  it("ordem no teto (200): quem falta pode ser só o corte — nenhuma escola é nomeada", async () => {
    const MUITAS = Array.from({ length: 200 }, (_, i) => cartao({ escola_id: 100 + i, nome: `EMEF Fictícia ${i + 1}` }));
    responder("GET", "/redes/1/dashboard", { ...DUAS_ESCOLAS, escolas: [...MUITAS, SEM_DADO] });
    responderRanking({ indice_geral: MUITAS });
    renderComApp(<RankingDaRede />, { usuario: secretaria });

    await screen.findByRole("button", { name: "EMEF Fictícia 200" });
    expect(screen.queryByText(/Fora da comparação/)).toBeNull();
  });

  it("pede a ordem com o teto que a tela usa para não confundir corte com ausência", async () => {
    responder("GET", "/redes/1/dashboard", DUAS_ESCOLAS);
    responderRanking(ORDEM_BACKEND);
    renderComApp(<RankingDaRede />, { usuario: secretaria });

    await screen.findByRole("button", { name: "Escola Pequena" });
    const urls = (api as unknown as { mock: { calls: unknown[][] } }).mock.calls
      .map((c) => String(c[0])).filter((u) => u.startsWith("/redes/1/ranking?"));
    expect(urls.length).toBeGreaterThan(0);
    expect(urls.every((u) => u.includes("limite=200"))).toBe(true);
  });

  it("aba Matemática: escola só com a Leitura escondida não ganha o aviso de proteção", async () => {
    const SO_LEITURA_OCULTA = { escola_id: 12, nome: "EMEF Fictícia Leitura Oculta", grupo_pequeno: true,
      oculto: { leitura: { motivo: "grupo_pequeno", texto: "x", parcial: false }, matematica: null } };
    responder("GET", "/redes/1/dashboard", {
      ...DUAS_ESCOLAS,
      escolas: [...DUAS_ESCOLAS.escolas, cartao({ escola_id: 12, nome: "EMEF Fictícia Leitura Oculta", comparada: true })],
      ocultas: [SO_LEITURA_OCULTA],
    });
    responderRanking(ORDEM_BACKEND);
    renderComApp(<RankingDaRede />, { usuario: secretaria });

    await screen.findByText("🏆 Ranking da Rede");
    await userEvent.click(screen.getByRole("tab", { name: /Matemática/i }));
    await screen.findByRole("button", { name: "Escola Pequena" });
    expect(screen.queryByText(/Fora deste ranking para proteger/)).toBeNull();
    await userEvent.click(screen.getByRole("tab", { name: /Leitura/i }));
    expect(await screen.findByText(/Fora deste ranking para proteger/)).toHaveTextContent("EMEF Fictícia Leitura Oculta");
  });
});

describe("Ranking da Rede — Diferença entre escolas (calculado pelo Constela) e a outra medida", () => {
  const EQUIDADE = {
    gap_indice: 187.5, escola_maior_indice: 937.5, escola_menor_indice: 750, escolas_abaixo_do_indice_medio: 1,
    gap_media: 12.3, escola_maior_media: 80, escola_menor_media: 67.7, escolas_abaixo_da_media: 1,
  };

  it("embaixo da tabela: a distância no índice entre a maior e a menor escola, com o selo e sem a média interna", async () => {
    responder("GET", "/redes/1/dashboard", { ...DUAS_ESCOLAS, equidade: EQUIDADE });
    responderRanking(ORDEM_BACKEND);
    renderComApp(<RankingDaRede />, { usuario: secretaria });
    const nota = await screen.findByTestId("diferenca-entre-escolas");
    expect(within(nota).getByRole("heading", { name: "Diferença entre escolas" })).toBeInTheDocument();
    expect(within(nota).getByText("Calculado pelo Constela")).toBeInTheDocument();
    expect(nota).toHaveTextContent("Entre a escola de maior e a de menor índice há 188 pontos de índice (750 → 938 de 1000)");
    expect(nota).toHaveTextContent("1 escola(s) abaixo do índice médio da rede");
    expect(nota).not.toHaveTextContent("12,3");   // o gap das médias internas não compara escolas
    // O período real de cada plataforma (achado 5), não "ano letivo" para o índice inteiro.
    expect(nota).toHaveTextContent(
      "Período: alunos do ano letivo corrente (Elefante: acumulado desde o início da conta; Matific: no ano letivo).",
    );
    expect(nota).not.toHaveTextContent("1000, no ano letivo");
    // A tabela vem antes da nota (a ordem é o principal; a diferença, o resumo dela).
    const tabela = await screen.findByRole("table");
    expect(tabela.compareDocumentPosition(nota) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("sem o campo (API anterior), nenhuma nota; com uma escola comparada só, diz que não há diferença (nunca um 0 solto)", async () => {
    responder("GET", "/redes/1/dashboard", DUAS_ESCOLAS);     // equidade: {}
    responderRanking(ORDEM_BACKEND);
    const { unmount } = renderComApp(<RankingDaRede />, { usuario: secretaria });
    await screen.findByRole("button", { name: "Escola Pequena" });
    expect(screen.queryByTestId("diferenca-entre-escolas")).not.toBeInTheDocument();
    unmount();

    const [AURORA_SO] = DUAS_ESCOLAS.escolas;
    responder("GET", "/redes/1/dashboard", {
      ...DUAS_ESCOLAS, escolas: [AURORA_SO, { ...DUAS_ESCOLAS.escolas[1], comparada: false }],
      equidade: { ...EQUIDADE, gap_indice: 0, escola_menor_indice: 937.5 },
    });
    renderComApp(<RankingDaRede />, { usuario: secretaria });
    const nota = await screen.findByTestId("diferenca-entre-escolas");
    expect(nota).toHaveTextContent("Com menos de duas escolas comparadas, não há diferença a medir.");
    expect(nota).not.toHaveTextContent("pontos de índice");
  });

  it("o ranking diz que é a pontuação do Constela: o uso por escola em Escolas; as avaliações externas, na área delas", async () => {
    responder("GET", "/redes/1/dashboard", DUAS_ESCOLAS);
    responderRanking(ORDEM_BACKEND);
    renderComApp(<RankingDaRede />, { usuario: secretaria });
    const texto = await screen.findByTestId("ranking-outra-medida");
    expect(texto).toHaveTextContent("O ranking ordena pela pontuação do Constela, calculada com o Elefante e o Matific.");
    expect(texto).toHaveTextContent("O uso das plataformas, escola por escola, fica em Escolas; os resultados das "
      + "avaliações externas, em Avaliações externas e na ficha de cada escola.");
    expect(within(texto).getByRole("link", { name: "Escolas" })).toHaveAttribute("href", "/rede/escolas");
    expect(within(texto).getByRole("link", { name: "Avaliações externas" }))
      .toHaveAttribute("href", "/rede/avaliacoes-externas");
    expect(texto).not.toHaveTextContent("Comparar escolas");
  });

  it("admin global: os links de Escolas e de Avaliações externas levam o ?rede= da rede aberta", async () => {
    const global = usuarioFake({ nome: "Root", cargo: "admin", is_global: true, escola_id: null, rede_id: null });
    responder("GET", "/redes", [{ id: 1, nome: "Rede Sintética" }]);
    responder("GET", "/redes/1/dashboard", DUAS_ESCOLAS);
    responderRanking(ORDEM_BACKEND);
    renderComApp(<RankingDaRede />, { usuario: global });
    const texto = await screen.findByTestId("ranking-outra-medida");
    expect(within(texto).getByRole("link", { name: "Escolas" })).toHaveAttribute("href", "/rede/escolas?rede=1");
    expect(within(texto).getByRole("link", { name: "Avaliações externas" }))
      .toHaveAttribute("href", "/rede/avaliacoes-externas?rede=1");
  });

  it("rede só com o Matific: o texto não cita o Elefante (produto não contratado)", async () => {
    responder("GET", "/redes/1/dashboard", { ...DUAS_ESCOLAS, modulos: ["matematica"] });
    responderRanking(ORDEM_BACKEND);
    renderComApp(<RankingDaRede />, { usuario: secretaria });
    const texto = await screen.findByTestId("ranking-outra-medida");
    expect(texto).toHaveTextContent("O ranking ordena pela pontuação do Constela, calculada com o Matific.");
    expect(texto).not.toHaveTextContent("Elefante");
  });
});
