/**
 * Panorama de uma rede (admin global): o módulo que a rede NÃO contratou não aparece no
 * "Comparativo entre escolas" nem no detalhe da "Média geral" — uma coluna "Matific" com
 * 0,0 em todas as escolas seria lida como nota zero em matemática, e o Boletim da Rede
 * (PDF) já tira essa coluna. Achado RELATORIOS-3. Escolas e números INVENTADOS.
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

import { PanoramaDaRede } from "../pages/rede/RedeDashboard";
import { escolaFake, renderComApp, responder, screen, usuarioFake } from "./utils";

const admin = usuarioFake({ nome: "Admin Sintético", is_global: true, cargo: "admin", escola_id: null });

function cartao(modulos: string[]) {
  return {
    escola_id: 1, nome: "EM Leitora Ficticia", cidade: "Cidade Ficticia", status: "ativa",
    latitude: null, longitude: null, total_turmas: 2, total_professores: 2,
    total_alunos: 10, alunos_com_dados: 5, adocao: 50,
    media_geral: 61, media_matific: 0, media_elefante: 72,
    dimensoes_com_dados: modulos, alunos_com_nota_elefante: 5,
    alunos_com_nota_matific: 0, adocao_elefante: 50, adocao_matific: 0,
    livros: 25, tempo_leitura_min: 250, atividades: 0, estrelas: 0,
    ativos_matific: 0, ativos_elefante: 5, livros_por_aluno: 5,
    livros_por_matricula: 2.5, estrelas_por_matricula: 0,
    atividades_por_matricula: 0, tempo_por_matricula_min: 25,
    pontuacao_leitura: 1000, pontuacao_matematica: 0, pontuacao_geral: 1000,
    dimensoes_pontuadas: modulos, modulos,
    precisa_atencao: false, motivo_atencao: null,
    comparada: true, posicao: 1,
  };
}

function semear(modulos: string[]) {
  responder("GET", "/redes/7/dashboard", {
    rede_id: 7,
    modulos,
    totais: {
      escolas: 1, escolas_ativas: 1, alunos: 10, turmas: 2, professores: 2,
      alunos_com_dados: 5, adocao: 50, media_geral: 61, media_matific: 0,
      media_elefante: 72, pontuacao_geral: 1000, escolas_em_atencao: 0,
      livros: 25, tempo_leitura_min: 250, atividades: 0, estrelas: 0,
      ativos_matific: 0, ativos_elefante: 5, livros_por_aluno: 5,
      melhor_escola: { nome: "EM Leitora Ficticia", pontuacao_geral: 1000, media_geral: 61 },
    },
    equidade: {
      gap_indice: 0, escola_maior_indice: 1000, escola_menor_indice: 1000,
      escolas_abaixo_do_indice_medio: 0,
      gap_media: 0, escola_maior_media: 61, escola_menor_media: 61, escolas_abaixo_da_media: 0,
    },
    escolas: [cartao(modulos)],
    atencao: [],
  });
  responder("GET", "/redes/7/metas", []);
  responder("GET", "/redes/7/publico", { ativo: false, token: null, url: null });
}

function cartaoComparativo() {
  return screen.getByText("Comparativo entre escolas").closest("div")!;
}

describe("Panorama de uma rede — só os módulos contratados", () => {
  it("rede só com a Leitura: sem coluna nem rodapé do Matific, e a Média geral não cita o Matific", async () => {
    semear(["leitura"]);
    renderComApp(<PanoramaDaRede redeId={7} />, { usuario: admin, escolas: [escolaFake()] });
    await screen.findByText("Comparativo entre escolas");

    const card = cartaoComparativo();
    const colunas = Array.from(card.querySelectorAll("thead th")).map((th) => th.textContent);
    expect(colunas).toEqual(["Escola", "Índice", "Geral", "Leitura", "Engaj."]);
    expect(card.textContent).not.toContain("Matific");
    expect(card.textContent).toContain("Geral · Leitura (0–100)");
    expect(card.querySelectorAll("tbody tr td")).toHaveLength(5);

    const media = screen.getByText("Média geral").parentElement!;
    expect(media.textContent).not.toContain("Matific");
    expect(media.textContent).toContain("Elefante 72,0");
  });

  it("rede só com a Matemática: sem a coluna Leitura", async () => {
    semear(["matematica"]);
    renderComApp(<PanoramaDaRede redeId={7} />, { usuario: admin, escolas: [escolaFake()] });
    await screen.findByText("Comparativo entre escolas");

    const card = cartaoComparativo();
    const colunas = Array.from(card.querySelectorAll("thead th")).map((th) => th.textContent);
    expect(colunas).toEqual(["Escola", "Índice", "Geral", "Matific", "Engaj."]);
    expect(card.textContent).toContain("Geral · Matific (0–100)");
    const media = screen.getByText("Média geral").parentElement!;
    expect(media.textContent).not.toContain("Elefante");
  });

  it("rede com os dois módulos: as colunas de sempre", async () => {
    semear(["leitura", "matematica"]);
    renderComApp(<PanoramaDaRede redeId={7} />, { usuario: admin, escolas: [escolaFake()] });
    await screen.findByText("Comparativo entre escolas");

    const card = cartaoComparativo();
    const colunas = Array.from(card.querySelectorAll("thead th")).map((th) => th.textContent);
    expect(colunas).toEqual(["Escola", "Índice", "Geral", "Leitura", "Matific", "Engaj."]);
    expect(card.textContent).toContain("Geral · Leitura · Matific (0–100)");
    const media = screen.getByText("Média geral").parentElement!;
    expect(media.textContent).toContain("Matific 0,0 · Elefante 72,0");
  });
});
