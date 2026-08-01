/**
 * Dashboard da Secretaria segue o CONTEXTO (o seletor do topo controla o
 * escolaId): "Toda a Rede" (escolaId nulo) → consolidado da rede; uma escola →
 * "Panorama Geral da <Escola>" com os indicadores AGREGADOS daquela escola (sem
 * PII individual). O atalho "Toda a Rede Municipal" volta ao consolidado.
 *
 * Renderiza o Dashboard (o despachante) — o seletor do topo é só `<select>` →
 * selecionarEscola, coberto pelo tipo. Leaflet é mockado (o painel importa o
 * mapa no topo do módulo).
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
  escolaFake,
  renderComApp,
  responder,
  screen,
  userEvent,
  usuarioFake,
} from "./utils";

const secretaria = usuarioFake({ rede_id: 7, cargo: "coordenador" });
const escolas = [
  escolaFake({ id: 1, nome: "EMEF Prof. Jorge Passos" }),
  escolaFake({ id: 2, nome: "EMEF Escola B" }),
];

function cartao(over: Record<string, unknown> = {}) {
  return {
    escola_id: 1, nome: "EMEF Prof. Jorge Passos", cidade: "Caraguatatuba", status: "ativa",
    latitude: null, longitude: null, total_turmas: 3, total_professores: 4,
    total_alunos: 15, alunos_com_dados: 15, adocao: 100, media_geral: 73.5,
    media_matific: 70, media_elefante: 65, livros: 40, tempo_leitura_min: 100,
    atividades: 500, estrelas: 2000, ativos_matific: 15, ativos_elefante: 15,
    livros_por_aluno: 2.7, precisa_atencao: false, motivo_atencao: null, posicao: 1,
    ...over,
  };
}

const DASH_REDE = {
  rede_id: 7,
  totais: {
    escolas: 2, escolas_ativas: 2, alunos: 17, turmas: 4, professores: 6,
    alunos_com_dados: 17, adocao: 100, media_geral: 71.9, media_matific: 68.5,
    media_elefante: 61.2, escolas_em_atencao: 0, livros: 67, tempo_leitura_min: 400,
    atividades: 915, estrelas: 4779, ativos_matific: 17, ativos_elefante: 17,
    livros_por_aluno: 3.9, melhor_escola: { nome: "EMEF Prof. Jorge Passos", media_geral: 73.5 },
  },
  equidade: { gap_media: 13.5, escola_maior_media: 73.5, escola_menor_media: 60,
    escolas_abaixo_da_media: 1 },
  escolas: [
    cartao(),
    cartao({ escola_id: 2, nome: "EMEF Escola B", total_alunos: 2, media_geral: 60 }),
  ],
  atencao: [],
};

function semear() {
  responder("GET", "/redes/7/dashboard", DASH_REDE);
  responder("GET", "/redes/7/metas", []);
}

describe("Dashboard da Secretaria segue o contexto", () => {
  it("padrão 'Toda a Rede' mostra o consolidado da rede", async () => {
    semear();
    renderComApp(<Dashboard />, { usuario: secretaria, escolas });

    expect(await screen.findByText("Panorama Geral da Rede Municipal")).toBeInTheDocument();
    // Elementos EXCLUSIVOS do consolidado da rede (não aparecem no de 1 escola).
    expect(screen.getByText("Equidade da rede")).toBeInTheDocument();
    expect(screen.getByText("Melhor escola")).toBeInTheDocument();
  });

  it("com uma escola no contexto mostra só aquela escola e volta ao consolidado", async () => {
    semear();
    renderComApp(<Dashboard />, { usuario: secretaria, escolas, escolaSelecionada: 1 });

    // Panorama da ESCOLA (agregado — sem nome de criança).
    expect(await screen.findByText("Panorama Geral da EMEF Prof. Jorge Passos")).toBeInTheDocument();
    expect(screen.queryByText("Panorama Geral da Rede Municipal")).not.toBeInTheDocument();
    expect(screen.getByText("Leitura — Elefante Letrado")).toBeInTheDocument();
    expect(screen.getByText("Matemática — Matific")).toBeInTheDocument();

    // Atalho "Toda a Rede Municipal" volta ao consolidado.
    await userEvent.click(screen.getByRole("button", { name: /Toda a Rede Municipal/ }));
    expect(await screen.findByText("Panorama Geral da Rede Municipal")).toBeInTheDocument();
  });
});
