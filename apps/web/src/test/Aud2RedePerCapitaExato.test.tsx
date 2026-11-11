/**
 * G_ANALISE-4 — o per capita do cartão vem arredondado para EXIBIR (1 casa). O Top 5 do
 * Panorama da Rede e a comparação entre redes do Panorama Global reordenam no cliente:
 * ordenando pelo número arredondado, 12,24 e 12,2 livros por aluno empatavam e o
 * desempate (adoção) dava o 1º lugar à escola que lê menos. A ordem agora é a da conta
 * exata (livros de quem concorre ÷ alunos que concorrem), a mesma do Ranking da Rede.
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
import { escolaFake, renderComApp, responder, screen, userEvent, usuarioFake } from "./utils";

const admin = usuarioFake({ nome: "Admin Inventado", is_global: true, cargo: "admin", escola_id: null });

function cartao(over: Record<string, unknown> = {}) {
  return {
    escola_id: 1, nome: "EM Inventada Pi", cidade: "Cidade Inventada", status: "ativa",
    latitude: null, longitude: null, total_turmas: 2, total_professores: 2,
    total_alunos: 25, alunos_com_dados: 24, adocao: 96,
    media_geral: 60, media_matific: 60, media_elefante: 60,
    dimensoes_com_dados: ["leitura", "matematica"], alunos_com_nota_elefante: 24,
    alunos_com_nota_matific: 24, adocao_elefante: 96, adocao_matific: 96,
    livros: 306, tempo_leitura_min: 3060, atividades: 240, estrelas: 240,
    ativos_matific: 24, ativos_elefante: 24, livros_por_aluno: 12.8,
    // 306 ÷ 25 = 12,24 → exibido 12,2.
    livros_por_matricula: 12.2, estrelas_por_matricula: 9.6,
    atividades_por_matricula: 9.6, tempo_por_matricula_min: 122.4,
    alunos_premiaveis: 25, livros_premiaveis: 306, estrelas_premiaveis: 240,
    atividades_premiaveis: 240, tempo_premiaveis_min: 3060,
    pontuacao_leitura: 1000, pontuacao_matematica: 960, pontuacao_geral: 980,
    dimensoes_pontuadas: ["leitura", "matematica"], modulos: ["leitura", "matematica"],
    precisa_atencao: false, motivo_atencao: null, comparada: true, posicao: 2,
    ...over,
  };
}

// 122 ÷ 10 = 12,2 → exibido 12,2; adoção maior (100%), que decidia o empate.
const QUI = cartao({
  escola_id: 2, nome: "EM Inventada Qui", total_alunos: 10, alunos_com_dados: 10, adocao: 100,
  alunos_com_nota_elefante: 10, alunos_com_nota_matific: 10, adocao_elefante: 100,
  adocao_matific: 100, livros: 122, tempo_leitura_min: 1220, atividades: 100, estrelas: 100,
  ativos_matific: 10, ativos_elefante: 10, livros_por_aluno: 12.2,
  livros_por_matricula: 12.2, estrelas_por_matricula: 10, atividades_por_matricula: 10,
  tempo_por_matricula_min: 122, alunos_premiaveis: 10, livros_premiaveis: 122,
  estrelas_premiaveis: 100, atividades_premiaveis: 100, tempo_premiaveis_min: 1220,
  pontuacao_leitura: 996.7, pontuacao_matematica: 1000, pontuacao_geral: 998.4, posicao: 1,
});

function dashRede() {
  return {
    rede_id: 7,
    modulos: ["leitura", "matematica"],
    totais: {
      escolas: 2, escolas_ativas: 2, alunos: 35, turmas: 4, professores: 4,
      alunos_com_dados: 34, adocao: 97.1, media_geral: 60, media_matific: 60,
      media_elefante: 60, pontuacao_geral: 985.6, escolas_em_atencao: 0,
      livros: 428, tempo_leitura_min: 4280, atividades: 340, estrelas: 340,
      ativos_matific: 34, ativos_elefante: 34, livros_por_aluno: 12.6,
      melhor_escola: { nome: "EM Inventada Qui", pontuacao_geral: 998.4, media_geral: 60 },
    },
    equidade: {
      gap_indice: 18.4, escola_maior_indice: 998.4, escola_menor_indice: 980,
      escolas_abaixo_do_indice_medio: 1,
      gap_media: 0, escola_maior_media: 60, escola_menor_media: 60, escolas_abaixo_da_media: 0,
    },
    escolas: [QUI, cartao()],
    atencao: [],
  };
}

function linhas(titulo: string) {
  const card = screen.getByText(titulo).closest("div")!.parentElement!;
  return Array.from(card.querySelector("table")!.querySelectorAll("tbody tr"))
    .map((linha) => linha.textContent ?? "");
}

describe("Per capita: a ordem do cliente é a da conta exata", () => {
  it("Top 5 por Livros/aluno: 12,24 vem antes de 12,2, mesmo com os dois exibidos 12,2", async () => {
    responder("GET", "/redes/7/dashboard", dashRede());
    responder("GET", "/redes/7/metas", []);
    responder("GET", "/redes/7/publico", { ativo: false, token: null, url: null });
    renderComApp(<PanoramaDaRede redeId={7} />, { usuario: admin, escolas: [escolaFake()] });
    await screen.findByText("Top 5 escolas da rede");

    await userEvent.click(screen.getByRole("button", { name: "Livros/aluno" }));
    const top = linhas("Top 5 escolas da rede");
    expect(top[0]).toContain("EM Inventada Pi");
    expect(top[1]).toContain("EM Inventada Qui");
  });

  it("Comparação entre redes por Livros/aluno: pela conta exata dos totais da rede", async () => {
    const rede = (over: Record<string, unknown>) => ({
      rede_id: 1, nome: "Rede Inventada Pi", uf: "SP", status: "ativa", escolas: 1, alunos: 25,
      turmas: 2, professores: 2, alunos_com_dados: 24, adocao: 96, media_geral: 60,
      media_matific: 60, media_elefante: 60, livros: 306, atividades: 240, estrelas: 240,
      escolas_em_atencao: 0, livros_por_matricula: 12.2, estrelas_por_matricula: 9.6,
      alunos_premiaveis: 25, livros_premiaveis: 306, estrelas_premiaveis: 240,
      pontuacao_geral: 980, posicao: 2, ...over,
    });
    responder("GET", "/redes/panorama-global", {
      totais: {
        redes: 2, escolas: 2, alunos: 35, turmas: 4, professores: 4, livros: 428,
        atividades: 340, estrelas: 340, media_geral: 60, media_matific: 60,
        media_elefante: 60, escolas_em_atencao: 0,
      },
      redes: [
        rede({ rede_id: 2, nome: "Rede Inventada Qui", alunos: 10, adocao: 100, livros: 122,
          alunos_premiaveis: 10, livros_premiaveis: 122, estrelas_premiaveis: 100,
          estrelas_por_matricula: 10, pontuacao_geral: 998.4, posicao: 1 }),
        rede({}),
      ],
      top_escolas: [],
    });
    renderComApp(<Dashboard />, { usuario: admin });
    await screen.findByText("Comparação entre redes");

    await userEvent.click(screen.getByRole("button", { name: "Livros/aluno" }));
    const ordem = linhas("Comparação entre redes");
    expect(ordem[0]).toContain("Rede Inventada Pi");
    expect(ordem[1]).toContain("Rede Inventada Qui");
  });
});
