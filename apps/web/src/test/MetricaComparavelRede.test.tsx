/**
 * C-02 — o que COMPARA escolas é governado pela métrica COMPARÁVEL: no Panorama de uma rede
 * (o admin global, na Visão Global), no Ranking da Rede ("Diferença entre escolas", que
 * substituiu a Equidade do Panorama antigo da Secretaria) e nas metas do Painel da Rede.
 *
 * `media_geral` (0–100) é normalizada contra o P90 da PRÓPRIA escola: mede a
 * homogeneidade interna, não o nível. Com ela na tela, a escola cujos alunos
 * mais leem por aluno aparecia como "abaixo" e a que quase não lê virava
 * "melhor escola". Quem governa agora é `pontuacao_geral` (índice per capita
 * 0–1000, régua = melhor escola da rede) — e as médias continuam visíveis,
 * rotuladas como desempenho INTERNO.
 *
 * O cenário destes testes é o do defeito: a escola de MAIOR média interna é a
 * de MENOR índice.
 */
import { describe, expect, it, vi } from "vitest";

vi.mock("leaflet", () => ({ default: { divIcon: () => ({}) } }));
vi.mock("react-leaflet", () => ({
  MapContainer: ({ children }: { children?: React.ReactNode }) => <div>{children}</div>,
  TileLayer: () => null,
  Marker: ({ children }: { children?: React.ReactNode }) => <div>{children}</div>,
  Popup: ({ children }: { children?: React.ReactNode }) => <div>{children}</div>,
  useMap: () => ({ setView: () => undefined, fitBounds: () => undefined }),
}));

import RankingDaRede from "../pages/rede/RankingRede";
import RedeDashboard, { PanoramaDaRede } from "../pages/rede/RedeDashboard";
import { escolaFake, renderComApp, responder, screen, usuarioFake, within } from "./utils";

const secretaria = usuarioFake({ rede_id: 7, cargo: "coordenador", escola_id: null });
const admin = usuarioFake({ nome: "Admin Sintético", is_global: true, cargo: "admin", escola_id: null });

function cartao(over: Record<string, unknown> = {}) {
  return {
    escola_id: 1, nome: "EM Pequena Homogenea", cidade: "Caraguatatuba", status: "ativa",
    latitude: null, longitude: null, total_turmas: 2, total_professores: 2,
    total_alunos: 30, alunos_com_dados: 30, adocao: 100,
    media_geral: 100, media_matific: 100, media_elefante: 100,
    dimensoes_com_dados: ["leitura"], alunos_com_nota_elefante: 30,
    alunos_com_nota_matific: 0, adocao_elefante: 100, adocao_matific: 0,
    livros: 60, tempo_leitura_min: 600, atividades: 0, estrelas: 0,
    ativos_matific: 0, ativos_elefante: 30, livros_por_aluno: 2,
    livros_por_matricula: 2, estrelas_por_matricula: 0,
    atividades_por_matricula: 0, tempo_por_matricula_min: 20,
    pontuacao_leitura: 50, pontuacao_matematica: 0, pontuacao_geral: 50,
    dimensoes_pontuadas: ["leitura"], modulos: ["leitura", "matematica"],
    precisa_atencao: true,
    motivo_atencao: "Índice do Constela baixo frente à rede: 50 de 1000 (pelo uso das plataformas; 1000 = maior índice da rede).",
    posicao: 2,
    ...over,
  };
}

// A LEITORA é a que a rede deve premiar: 40 livros por aluno (índice 1000),
// apesar da média interna mais BAIXA (distribuição dispersa).
const LEITORA = cartao({
  escola_id: 2, nome: "EM Grande Leitora", total_alunos: 40, alunos_com_dados: 40,
  media_geral: 25.8, media_matific: 0, media_elefante: 25.8,
  alunos_com_nota_elefante: 40, ativos_elefante: 40, livros: 1632,
  livros_por_aluno: 40.8, livros_por_matricula: 40.8,
  pontuacao_leitura: 1000, pontuacao_geral: 1000,
  precisa_atencao: false, motivo_atencao: null, posicao: 1,
});

const DASH_REDE = {
  rede_id: 7,
  modulos: ["leitura", "matematica"],
  totais: {
    escolas: 2, escolas_ativas: 2, alunos: 70, turmas: 4, professores: 4,
    alunos_com_dados: 70, adocao: 100, media_geral: 57.6, media_matific: 0,
    media_elefante: 57.6, pontuacao_geral: 592.9, escolas_em_atencao: 1,
    livros: 1692, tempo_leitura_min: 1200, atividades: 0, estrelas: 0,
    ativos_matific: 0, ativos_elefante: 70, livros_por_aluno: 24.2,
    // O KPI "Melhor escola" segue o índice, não a média.
    melhor_escola: { nome: "EM Grande Leitora", pontuacao_geral: 1000, media_geral: 25.8 },
  },
  equidade: {
    gap_indice: 950, escola_maior_indice: 1000, escola_menor_indice: 50,
    escolas_abaixo_do_indice_medio: 1,
    gap_media: 74.2, escola_maior_media: 100, escola_menor_media: 25.8,
    escolas_abaixo_da_media: 1,
  },
  // Já ordenado pelo backend: a leitora em 1º.
  escolas: [LEITORA, cartao()],
  atencao: [cartao()],
};

function semear(metas: unknown[] = []) {
  responder("GET", "/redes/7/dashboard", DASH_REDE);
  responder("GET", "/redes/7/metas", metas);
}

describe("Panorama de uma rede (admin global) é governado pelo índice comparável", () => {
  it("'Melhor escola' é a que mais lê por aluno, com o índice no cartão", async () => {
    semear();
    renderComApp(<PanoramaDaRede redeId={7} />, { usuario: admin, escolas: [escolaFake()] });

    const cartaoMelhor = (await screen.findByText("Melhor escola")).closest("div")!
      .parentElement!;
    expect(within(cartaoMelhor).getByText("EM Grande Leitora")).toBeInTheDocument();
    // 1.000 (índice), não 25,8 (média interna) nem 100 (a da escola homogênea).
    expect(within(cartaoMelhor).getByText("1.000")).toBeInTheDocument();
  });

  it("equidade mede a distância no índice, não nas médias internas", async () => {
    semear();
    renderComApp(<PanoramaDaRede redeId={7} />, { usuario: admin, escolas: [escolaFake()] });

    const equidade = (await screen.findByText("Equidade da rede")).closest("div")!;
    expect(equidade.textContent).toContain("950");            // 1000 - 50
    expect(equidade.textContent).toContain("de 1000");
    expect(equidade.textContent).not.toContain("74,2");       // o gap das médias
  });

  it("comparativo entre escolas ordena pelo índice e explica as duas réguas", async () => {
    semear();
    renderComApp(<PanoramaDaRede redeId={7} />, { usuario: admin, escolas: [escolaFake()] });

    const tabela = (await screen.findByText("Comparativo entre escolas"))
      .closest("div")!.querySelector("table")!;
    const nomes = Array.from(tabela.querySelectorAll("tbody tr td:first-child"))
      .map((c) => c.textContent);
    expect(nomes).toEqual(["EM Grande Leitora", "EM Pequena Homogenea"]);
    // A régua não comparável continua visível, mas nomeada.
    expect(screen.getByText(/desempenho interno de cada escola/i)).toBeInTheDocument();
  });

  it("escola em atenção é a que pouco lê, com o motivo no índice", async () => {
    semear();
    renderComApp(<PanoramaDaRede redeId={7} />, { usuario: admin, escolas: [escolaFake()] });

    expect(await screen.findByText(/Escolas que precisam de aten/)).toBeInTheDocument();
    expect(screen.getByText(/Índice do Constela baixo frente à rede: 50 de 1000/)).toBeInTheDocument();
    expect(screen.queryByText("EM Grande Leitora · atenção")).not.toBeInTheDocument();
  });

  it("meta não comparável não publica contagem de escolas; a comparável publica", async () => {
    semear([
      { id: 1, metrica: "media_geral", rotulo: "Média geral da rede", sufixo: "",
        alvo: 50, atual: 57.6, progresso: 100, atingida: true, descricao: null,
        comparavel: false, escolas_atingiram: null, escolas_total: null },
      { id: 2, metrica: "pontuacao_geral", rotulo: "Índice da rede (0–1000)", sufixo: "",
        alvo: 500, atual: 592.9, progresso: 100, atingida: true, descricao: null,
        comparavel: true, escolas_atingiram: 1, escolas_total: 2 },
    ]);
    renderComApp(<PanoramaDaRede redeId={7} />, { usuario: admin, escolas: [escolaFake()] });

    expect(await screen.findByText("1 de 2 escolas atingiram")).toBeInTheDocument();
    expect(screen.getByText(/não comparável entre escolas/i)).toBeInTheDocument();
  });
});

describe("Secretaria: o que compara escolas segue o índice (Ranking da Rede e Painel da Rede)", () => {
  it("Ranking da Rede: a 'Diferença entre escolas' mede a distância no índice, não nas médias internas", async () => {
    semear();
    responder("GET", /^\/redes\/7\/ranking\?/, () => DASH_REDE.escolas.map((c, i) => ({ ...c, posicao: i + 1 })));
    responder("GET", "/redes/7/ranking/frescor", { limite_dias: 7, hoje: "2026-10-20", escolas: [] });
    renderComApp(<RankingDaRede />, { usuario: secretaria });
    const nota = await screen.findByTestId("diferenca-entre-escolas");
    expect(nota).toHaveTextContent("Diferença entre escolas");
    expect(within(nota).getByText("Calculado pelo Constela")).toBeInTheDocument();
    expect(nota).toHaveTextContent("Entre a escola de maior e a de menor índice há 950 pontos de índice (50 → 1.000 de 1000)");
    expect(nota).toHaveTextContent("1 escola(s) abaixo do índice médio da rede");
    expect(nota).not.toHaveTextContent("74,2");       // o gap das médias internas
    expect(nota).toHaveTextContent("não uma avaliação oficial");
  });

  it("Painel da Rede: o progresso das metas não publica contagem de escolas na meta não comparável", async () => {
    semear([
      { id: 1, metrica: "media_geral", rotulo: "Média geral da rede", sufixo: "",
        alvo: 50, atual: 57.6, progresso: 100, atingida: true, descricao: null,
        comparavel: false, escolas_atingiram: null, escolas_total: null },
      { id: 2, metrica: "pontuacao_geral", rotulo: "Índice da rede (0–1000)", sufixo: "",
        alvo: 500, atual: 592.9, progresso: 100, atingida: true, descricao: null,
        comparavel: true, escolas_atingiram: 1, escolas_total: 2 },
    ]);
    responder("GET", "/redes/7/publico", { ativo: false, token: null, url: null });
    renderComApp(<RedeDashboard />, { rota: "/rede", usuario: secretaria });
    expect(await screen.findByText("1 de 2 escolas atingiram")).toBeInTheDocument();
    expect(screen.getByText(/não comparável entre escolas/i)).toBeInTheDocument();
    // E a escola com alerta de uso traz o motivo pelo índice (a regra do painel).
    expect(screen.getByText(/Índice do Constela baixo frente à rede: 50 de 1000/)).toBeInTheDocument();
  });
});
