/**
 * Admin Global → Dashboard multirrede (jornada de FRONTEND que o teste de
 * backend não cobre): consolidação de todas as redes → seleciona uma rede
 * (drill-down) → volta para a visão consolidada. Exercita o estado real do
 * componente (PanoramaGlobal.redeSel + botão "Voltar"), não só o endpoint.
 *
 * Leaflet é mockado: o RedeDashboard importa o mapa no topo do módulo, mas o
 * jsdom não roda Leaflet e o mapa não é o que este teste valida.
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
import {
  renderComApp,
  responder,
  screen,
  userEvent,
  usuarioFake,
} from "./utils";

const admin = usuarioFake({ is_global: true, cargo: "admin", escola_id: null });

function escolaCartao(over: Record<string, unknown> = {}) {
  return {
    escola_id: 1, nome: "EM JORGE PASSOS", cidade: "Caraguatatuba", status: "ativa",
    latitude: null, longitude: null, total_turmas: 3, total_professores: 2,
    total_alunos: 15, alunos_com_dados: 15, adocao: 100, media_geral: 73.5,
    media_matific: 70, media_elefante: 65, livros: 40, tempo_leitura_min: 100,
    atividades: 500, estrelas: 2000, ativos_matific: 15, ativos_elefante: 15,
    livros_por_aluno: 2.7, precisa_atencao: false, motivo_atencao: null, posicao: 1,
    ...over,
  };
}

function redeCartao(over: Record<string, unknown> = {}) {
  return {
    rede_id: 1, nome: "Rede Municipal de Caraguatatuba", uf: "SP", status: "ativa",
    escolas: 1, alunos: 15, turmas: 3, professores: 2, alunos_com_dados: 15,
    adocao: 100, media_geral: 73.5, media_matific: 70, media_elefante: 65,
    livros: 40, atividades: 500, estrelas: 2000, escolas_em_atencao: 0, posicao: 1,
    ...over,
  };
}

const GLOBAL = {
  totais: {
    redes: 2, escolas: 2, alunos: 17, turmas: 4, professores: 2,
    livros: 67, atividades: 915, estrelas: 4779,
    media_geral: 71.9, media_matific: 68.5, media_elefante: 61.2, escolas_em_atencao: 0,
  },
  redes: [
    redeCartao({ rede_id: 1, nome: "Rede Municipal de Caraguatatuba" }),
    redeCartao({ rede_id: 2, nome: "Rede Municipal de Ubatuba", escolas: 1, alunos: 2,
      media_geral: 60, posicao: 2 }),
  ],
  top_escolas: [
    escolaCartao({ escola_id: 1, nome: "EM JORGE PASSOS",
      rede_id: 1, rede_nome: "Rede Municipal de Caraguatatuba" }),
    escolaCartao({ escola_id: 2, nome: "EM UBATUBA CENTRO", total_alunos: 2, media_geral: 60,
      rede_id: 2, rede_nome: "Rede Municipal de Ubatuba" }),
  ],
};

const REDE_1 = {
  rede_id: 1,
  totais: {
    escolas: 1, escolas_ativas: 1, alunos: 15, turmas: 3, professores: 2,
    alunos_com_dados: 15, adocao: 100, media_geral: 73.5, media_matific: 70,
    media_elefante: 65, escolas_em_atencao: 0, livros: 40, tempo_leitura_min: 100,
    atividades: 500, estrelas: 2000, ativos_matific: 15, ativos_elefante: 15,
    livros_por_aluno: 2.7, melhor_escola: { nome: "EM JORGE PASSOS", media_geral: 73.5 },
  },
  equidade: { gap_media: 0, escola_maior_media: 73.5, escola_menor_media: 73.5,
    escolas_abaixo_da_media: 0 },
  escolas: [escolaCartao()],
  atencao: [],
};

describe("Admin Global — Dashboard multirrede", () => {
  it("consolida as redes, aprofunda numa rede e volta para a visão consolidada", async () => {
    responder("GET", "/redes/panorama-global", GLOBAL);
    responder("GET", "/redes/1/dashboard", REDE_1);
    renderComApp(<Dashboard />, { usuario: admin });

    // (a) Visão CONSOLIDADA: título global + as duas redes + KPIs somados.
    expect(await screen.findByText("Panorama Global — Todas as Redes")).toBeInTheDocument();
    expect(screen.getAllByText("Rede Municipal de Caraguatatuba").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Rede Municipal de Ubatuba").length).toBeGreaterThan(0);
    expect(screen.getByText("17")).toBeInTheDocument();          // alunos consolidados
    // Ainda NÃO estamos dentro de uma rede.
    expect(screen.queryByText("Panorama Geral da Rede Municipal")).not.toBeInTheDocument();

    // (b) DRILL-DOWN: seleciona uma rede no seletor → painel daquela rede.
    await userEvent.selectOptions(screen.getByLabelText("Selecionar rede"), "1");
    expect(await screen.findByText("Panorama Geral da Rede Municipal")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Voltar para todas as redes/ })).toBeInTheDocument();
    // Saiu da visão consolidada.
    expect(screen.queryByText("Panorama Global — Todas as Redes")).not.toBeInTheDocument();

    // (c) VOLTA: o botão devolve a visão consolidada (estado redeSel → null).
    await userEvent.click(screen.getByRole("button", { name: /Voltar para todas as redes/ }));
    expect(await screen.findByText("Panorama Global — Todas as Redes")).toBeInTheDocument();
    expect(screen.queryByText("Panorama Geral da Rede Municipal")).not.toBeInTheDocument();
  });
});
