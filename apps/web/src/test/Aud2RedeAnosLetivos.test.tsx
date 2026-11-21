/**
 * G_VIRADA-6 — na virada do ano, o Admin Global troca o ano escola por escola e a rede passa
 * dias com escolas em 2027 e outras ainda em 2026. Cada escola é medida no ano letivo DELA
 * (o backend manda `ano_letivo` em cada cartão e `anos_letivos` no `/dashboard`), e o Ranking
 * da Rede e o Painel da Rede comparavam as duas sem dizer nada — o cabeçalho afirmava "alunos
 * do ano letivo corrente", como se fosse um ano só. Agora as telas dizem que os anos são
 * diferentes e marcam o ano de cada escola. Com a rede num ano só, nada muda.
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

import RedeDashboard, { PanoramaDaRede } from "../pages/rede/RedeDashboard";
import RankingDaRede from "../pages/rede/RankingRede";
import { escolaFake, renderComApp, responder, screen, usuarioFake } from "./utils";

const secretaria = usuarioFake({ rede_id: 7, cargo: "coordenador", escola_id: null });
const admin = usuarioFake({ nome: "Admin Inventado", is_global: true, cargo: "admin", escola_id: null });

function cartao(over: Record<string, unknown> = {}) {
  return {
    escola_id: 1, nome: "EMEF Inventada Alfa", cidade: "Cidade Inventada", status: "ativa",
    latitude: null, longitude: null, total_turmas: 1, total_professores: 1,
    total_alunos: 4, alunos_com_dados: 4, adocao: 100,
    media_geral: 50, media_matific: 50, media_elefante: 50,
    dimensoes_com_dados: ["leitura", "matematica"], alunos_com_nota_elefante: 4,
    alunos_com_nota_matific: 4, adocao_elefante: 100, adocao_matific: 100,
    livros: 16, tempo_leitura_min: 160, atividades: 40, estrelas: 120,
    ativos_matific: 4, ativos_elefante: 4, livros_por_aluno: 4,
    livros_por_matricula: 4, estrelas_por_matricula: 30, atividades_por_matricula: 10,
    tempo_por_matricula_min: 40, alunos_premiaveis: 4,
    pontuacao_leitura: 1000, pontuacao_matematica: 1000, pontuacao_geral: 1000,
    dimensoes_pontuadas: ["leitura", "matematica"], modulos: ["leitura", "matematica"],
    precisa_atencao: false, motivo_atencao: null, comparada: true, posicao: 1,
    ano_letivo: 2026,
    ...over,
  };
}

const ALFA = cartao();
const BETA = cartao({ escola_id: 2, nome: "EMEF Inventada Beta", posicao: 2, ano_letivo: 2027 });

function dashRede(escolas: ReturnType<typeof cartao>[], anos: number[]) {
  return {
    rede_id: 7,
    modulos: ["leitura", "matematica"],
    anos_letivos: anos,
    totais: {
      escolas: escolas.length, escolas_ativas: escolas.length, alunos: 8, turmas: 2, professores: 2,
      alunos_com_dados: 8, adocao: 100, media_geral: 50, media_matific: 50, media_elefante: 50,
      pontuacao_geral: 1000, escolas_em_atencao: 0, livros: 32, tempo_leitura_min: 320,
      atividades: 80, estrelas: 240, ativos_matific: 8, ativos_elefante: 8, livros_por_aluno: 4,
      melhor_escola: { nome: "EMEF Inventada Alfa", pontuacao_geral: 1000, media_geral: 50 },
    },
    equidade: {
      gap_indice: 0, escola_maior_indice: 1000, escola_menor_indice: 1000,
      escolas_abaixo_do_indice_medio: 0,
      gap_media: 0, escola_maior_media: 50, escola_menor_media: 50, escolas_abaixo_da_media: 0,
    },
    escolas,
    atencao: [],
  };
}

function semear(escolas: ReturnType<typeof cartao>[], anos: number[]) {
  responder("GET", "/redes/7/dashboard", dashRede(escolas, anos));
  responder("GET", /^\/redes\/7\/ranking\?/, escolas.map((c, i) => ({ ...c, posicao: i + 1 })));
  responder("GET", "/redes/7/metas", []);
  responder("GET", "/redes/7/publico", { ativo: false, token: null, url: null });
}

const AVISO = /As escolas da rede estão em anos letivos diferentes \(2026, 2027\)/;

describe("Rede com escolas em anos letivos diferentes", () => {
  it("Ranking da Rede: avisa e marca o ano letivo de cada escola", async () => {
    semear([ALFA, BETA], [2026, 2027]);
    renderComApp(<RankingDaRede />, { usuario: secretaria });
    await screen.findByText("🏆 Ranking da Rede");
    await screen.findAllByText("EMEF Inventada Beta");

    expect(screen.getByTestId("aviso-anos-letivos")).toHaveTextContent(AVISO);
    // O cabeçalho não afirma mais "o ano letivo corrente", como se fosse um só.
    expect(screen.queryByText(/ano letivo corrente/)).not.toBeInTheDocument();
    const linhaBeta = screen.getByRole("button", { name: "EMEF Inventada Beta" }).closest("tr")!;
    expect(linhaBeta).toHaveTextContent("ano letivo 2027");
    const linhaAlfa = screen.getByRole("button", { name: "EMEF Inventada Alfa" }).closest("tr")!;
    expect(linhaAlfa).toHaveTextContent("ano letivo 2026");
  });

  it("Ranking da Rede com a rede num ano só: nem aviso nem marca", async () => {
    semear([ALFA, cartao({ escola_id: 2, nome: "EMEF Inventada Beta", posicao: 2 })], [2026]);
    renderComApp(<RankingDaRede />, { usuario: secretaria });
    await screen.findByText("🏆 Ranking da Rede");
    await screen.findAllByText("EMEF Inventada Beta");

    expect(screen.queryByTestId("aviso-anos-letivos")).not.toBeInTheDocument();
    expect(screen.queryByText(/ano letivo 2026/)).not.toBeInTheDocument();
    expect(screen.getAllByText(/ano letivo corrente/).length).toBeGreaterThan(0);
  });

  it("Painel da Rede (Secretaria): avisa e diz quem está em cada ano", async () => {
    semear([ALFA, BETA], [2026, 2027]);
    renderComApp(<RedeDashboard />, { rota: "/rede", usuario: secretaria });
    const aviso = await screen.findByTestId("aviso-anos-letivos");
    expect(aviso).toHaveTextContent(AVISO);
    expect(aviso).toHaveTextContent("Em 2026: EMEF Inventada Alfa.");
    expect(aviso).toHaveTextContent("Em 2027: EMEF Inventada Beta.");
  });

  it("Panorama de uma rede (Admin Global): o mesmo aviso", async () => {
    semear([ALFA, BETA], [2026, 2027]);
    renderComApp(<PanoramaDaRede redeId={7} />, { usuario: admin, escolas: [escolaFake()] });
    await screen.findByText("Comparativo entre escolas");
    expect(screen.getByTestId("aviso-anos-letivos")).toHaveTextContent(AVISO);
  });

  it("Painel da Rede num ano só (ou API anterior, sem os anos): sem aviso", async () => {
    const semAnos = { ...dashRede([ALFA], [2026]) } as Record<string, unknown>;
    delete semAnos.anos_letivos;
    responder("GET", "/redes/7/dashboard", semAnos);
    responder("GET", "/redes/7/metas", []);
    responder("GET", "/redes/7/publico", { ativo: false, token: null, url: null });
    renderComApp(<RedeDashboard />, { rota: "/rede", usuario: secretaria });
    await screen.findByTestId("comparar-as-escolas");
    expect(screen.queryByTestId("aviso-anos-letivos")).not.toBeInTheDocument();
  });
});
