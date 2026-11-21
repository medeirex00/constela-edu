/**
 * G_ANALISE-6 — a média 0–100 de uma plataforma CONTRATADA que ninguém da escola (ou da
 * rede) usa não aparece como "0,0". O backend manda `media_<plataforma>` = 0 quando
 * `alunos_com_nota_<plataforma>` = 0 (ausência); o Comparativo entre escolas, a "Média
 * geral" e a "Média" do Matific do Panorama da Rede e a comparação entre redes do Panorama
 * Global mostravam "0,0", lido como nota zero. Agora: "sem dado", como na tela das
 * plataformas. O valor escondido (grupo pequeno) continua "— protegido".
 *
 * Redes, escolas e números INVENTADOS.
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

import Dashboard from "../pages/Dashboard";
import { PanoramaDaRede } from "../pages/rede/RedeDashboard";
import { escolaFake, renderComApp, responder, screen, usuarioFake } from "./utils";

const admin = usuarioFake({ nome: "Admin Inventado", is_global: true, cargo: "admin", escola_id: null });

function cartao(over: Record<string, unknown> = {}) {
  return {
    escola_id: 1, nome: "EM Inventada Lambda", cidade: "Cidade Inventada", status: "ativa",
    latitude: null, longitude: null, total_turmas: 1, total_professores: 1,
    total_alunos: 6, alunos_com_dados: 6, adocao: 100,
    // Só Elefante: a média do Matific vem 0 por ausência (nenhum aluno com nota dele).
    media_geral: 31.2, media_matific: 0, media_elefante: 31.2,
    dimensoes_com_dados: ["leitura"], alunos_com_nota_elefante: 6, alunos_com_nota_matific: 0,
    adocao_elefante: 100, adocao_matific: 0,
    livros: 45, tempo_leitura_min: 300, atividades: 0, estrelas: 0,
    ativos_matific: 0, ativos_elefante: 6, livros_por_aluno: 7.5,
    livros_por_matricula: 7.5, estrelas_por_matricula: 0, atividades_por_matricula: 0,
    tempo_por_matricula_min: 50,
    pontuacao_leitura: 1000, pontuacao_matematica: 0, pontuacao_geral: 1000,
    dimensoes_pontuadas: ["leitura"], modulos: ["leitura", "matematica"],
    precisa_atencao: false, motivo_atencao: null, comparada: true, posicao: 1,
    ...over,
  };
}

// Só Matific: a média do Elefante vem 0 por ausência.
const MU = cartao({
  escola_id: 2, nome: "EM Inventada Mu", media_geral: 56.5, media_matific: 56.5, media_elefante: 0,
  dimensoes_com_dados: ["matematica"], alunos_com_nota_elefante: 0, alunos_com_nota_matific: 6,
  adocao_elefante: 0, adocao_matific: 100, livros: 0, tempo_leitura_min: 0, atividades: 75,
  estrelas: 195, ativos_matific: 6, ativos_elefante: 0, livros_por_aluno: 0,
  livros_por_matricula: 0, estrelas_por_matricula: 32.5, atividades_por_matricula: 12.5,
  tempo_por_matricula_min: 0, pontuacao_leitura: 0, pontuacao_matematica: 1000,
  dimensoes_pontuadas: ["matematica"], posicao: 2,
});

function dashRede(escolas: unknown[], totais: Record<string, unknown> = {}) {
  return {
    rede_id: 7,
    modulos: ["leitura", "matematica"],
    totais: {
      escolas: escolas.length, escolas_ativas: escolas.length, alunos: 12, turmas: 2, professores: 2,
      alunos_com_dados: 12, adocao: 100, media_geral: 43.9, media_matific: 56.5,
      media_elefante: 31.2, pontuacao_geral: 1000, escolas_em_atencao: 0,
      livros: 45, tempo_leitura_min: 300, atividades: 75, estrelas: 195,
      ativos_matific: 6, ativos_elefante: 6, livros_por_aluno: 7.5,
      melhor_escola: { nome: "EM Inventada Lambda", pontuacao_geral: 1000, media_geral: 31.2 },
      ...totais,
    },
    equidade: {
      gap_indice: 0, escola_maior_indice: 1000, escola_menor_indice: 1000,
      escolas_abaixo_do_indice_medio: 0,
      gap_media: 25.3, escola_maior_media: 56.5, escola_menor_media: 31.2, escolas_abaixo_da_media: 1,
    },
    escolas,
    atencao: [],
  };
}

function semear(dash: unknown) {
  responder("GET", "/redes/7/dashboard", dash);
  responder("GET", "/redes/7/metas", []);
  responder("GET", "/redes/7/publico", { ativo: false, token: null, url: null });
}

function linhasDe(titulo: string) {
  const card = screen.getByText(titulo).closest("div")!;
  return Array.from(card.querySelector("table")!.querySelectorAll("tbody tr"));
}

function celulas(linha: Element) {
  return Array.from(linha.querySelectorAll("td")).map((td) => td.textContent ?? "");
}

describe("Média de plataforma sem ninguém medido: 'sem dado', nunca 0,0", () => {
  it("Comparativo entre escolas: a plataforma que a escola não usa sai 'sem dado'", async () => {
    semear(dashRede([cartao(), MU]));
    renderComApp(<PanoramaDaRede redeId={7} />, { usuario: admin, escolas: [escolaFake()] });
    await screen.findByText("Comparativo entre escolas");

    // Colunas: Escola, Índice, Geral, Leitura, Matific, Engaj.
    const [lambda, mu] = linhasDe("Comparativo entre escolas").map(celulas);
    expect(lambda[0]).toContain("EM Inventada Lambda");
    expect(lambda.slice(2, 5)).toEqual(["31,2", "31,2", "sem dado"]);
    expect(mu[0]).toContain("EM Inventada Mu");
    expect(mu.slice(2, 5)).toEqual(["56,5", "sem dado", "56,5"]);
  });

  it("rede sem nenhuma nota ainda: a Média geral e a Média do Matific dizem 'sem dado'", async () => {
    const semNota = cartao({ media_geral: 0, media_elefante: 0, alunos_com_nota_elefante: 0,
      dimensoes_com_dados: [] });
    semear(dashRede([semNota], { media_geral: 0, media_matific: 0, media_elefante: 0 }));
    renderComApp(<PanoramaDaRede redeId={7} />, { usuario: admin, escolas: [escolaFake()] });
    await screen.findByText("Comparativo entre escolas");

    const media = screen.getByText("Média geral").closest("div")!;
    expect(media).toHaveTextContent("sem dado");
    expect(media).toHaveTextContent("Matific sem dado · Elefante sem dado");
    expect(media).not.toHaveTextContent("0,0");
    const secao = screen.getByText("Matemática — Matific").closest("div")!.parentElement!;
    expect(secao).toHaveTextContent("sem dadoMédia");
    expect(celulas(linhasDe("Comparativo entre escolas")[0]).slice(2, 5))
      .toEqual(["sem dado", "sem dado", "sem dado"]);
  });

  it("Panorama Global: a rede sem aluno com nota do Elefante sai 'sem dado' na Leitura", async () => {
    const rede = (over: Record<string, unknown>) => ({
      rede_id: 1, nome: "Rede Inventada Lambda", uf: "SP", status: "ativa", escolas: 1, alunos: 6,
      turmas: 1, professores: 1, alunos_com_dados: 6, adocao: 100, media_geral: 31.2,
      media_matific: 0, media_elefante: 31.2, alunos_com_nota_elefante: 6, alunos_com_nota_matific: 0,
      livros: 45, atividades: 0, estrelas: 0, escolas_em_atencao: 0,
      livros_por_matricula: 7.5, estrelas_por_matricula: 0, pontuacao_geral: 1000, posicao: 1, ...over,
    });
    responder("GET", "/redes/panorama-global", {
      totais: {
        redes: 2, escolas: 2, alunos: 12, turmas: 2, professores: 2, livros: 45,
        atividades: 75, estrelas: 195, media_geral: 43.9, media_matific: 56.5,
        media_elefante: 31.2, escolas_em_atencao: 0,
      },
      redes: [
        rede({}),
        rede({ rede_id: 2, nome: "Rede Inventada Mu", media_geral: 56.5, media_matific: 56.5,
          media_elefante: 0, alunos_com_nota_elefante: 0, alunos_com_nota_matific: 6,
          pontuacao_geral: 1000, posicao: 2 }),
      ],
      top_escolas: [],
    });
    renderComApp(<Dashboard />, { usuario: admin });
    await screen.findByText("Comparação entre redes");

    // Colunas: #, Rede, Escolas, Alunos, critério, Leitura, Matific, Engaj.
    const linhas = Array.from(screen.getByText("Comparação entre redes").closest("div")!
      .parentElement!.querySelector("table")!.querySelectorAll("tbody tr")).map(celulas);
    const lambda = linhas.find((l) => l[1].includes("Rede Inventada Lambda"))!;
    const mu = linhas.find((l) => l[1].includes("Rede Inventada Mu"))!;
    expect(lambda.slice(5, 7)).toEqual(["31,2", "sem dado"]);
    expect(mu.slice(5, 7)).toEqual(["sem dado", "56,5"]);
  });
});
