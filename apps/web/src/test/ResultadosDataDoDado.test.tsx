/**
 * Premiações e painel da escola dizem DE QUANDO é o dado (frente C, 22/10/2026).
 *
 * O selo de frescor (`SeloFrescor`) já estava nos rankings; a tela de
 * Premiações recebia o bloco `frescor` na própria resposta e não o mostrava, e o
 * painel inicial (médias e Top 5) não dizia a data em lugar nenhum. Nas escolas
 * com a coleta parada em 01–05/10 o pódio de "outubro" parecia completo. Dados
 * fictícios; nenhuma fórmula muda.
 */
import { describe, expect, it, vi } from "vitest";

// O painel da rede importa o mapa (Leaflet) no topo do módulo.
vi.mock("leaflet", () => ({ default: { divIcon: () => ({}) } }));
vi.mock("react-leaflet", () => ({
  MapContainer: ({ children }: { children?: React.ReactNode }) => <div>{children}</div>,
  TileLayer: () => null,
  Marker: ({ children }: { children?: React.ReactNode }) => <div>{children}</div>,
  Popup: ({ children }: { children?: React.ReactNode }) => <div>{children}</div>,
  useMap: () => ({ setView: () => undefined, fitBounds: () => undefined }),
}));

import type { Frescor } from "../components/SeloFrescor";
import Dashboard from "../pages/Dashboard";
import Premiacoes from "../pages/Premiacoes";
import {
  dashboardFake, escolaFake, renderComApp, responder, responderErro, screen, turmaFake, usuarioFake,
} from "./utils";

function frescor(estadoLeitura: "em_dia" | "desatualizado" = "em_dia"): Frescor {
  const bloco = (plataforma: string, dia: string, dias: number, estado: string) => ({
    plataforma, contratada: true, estado, dado_mais_recente_em: dia,
    dado_mais_antigo_em: dia, dias_desde_dado: dias, alunos_com_dado: 12,
    alunos_com_dado_antigo: 0, ultima_sincronizacao_ok_em: null,
    dias_desde_sincronizacao_ok: null,
  });
  return {
    limite_dias: 7, hoje: "2026-10-22", estado: estadoLeitura,
    dimensoes: {
      leitura: estadoLeitura === "em_dia"
        ? bloco("elefante", "2026-10-19", 3, "em_dia")
        : bloco("elefante", "2026-10-01", 21, "desatualizado"),
      matematica: bloco("matific", "2026-10-19", 3, "em_dia"),
    },
  } as Frescor;
}

function premiacoes(over: Record<string, unknown> = {}) {
  return {
    periodo: { chave: "mes", rotulo: "Este mês", inicio: null, fim: null },
    categorias: [{
      chave: "melhor_leitor", titulo: "Melhor Leitor", icone: "🏆", descricao: "d",
      unidade: "pontos", total: 1,
      podio: [{ posicao: 1, aluno_id: 1, nome: "Crianca Ficticia", turma: "3A", valor: 30 }],
    }],
    turnos: [],
    ...over,
  };
}

describe("Premiações — data do dado", () => {
  it("mostra o selo com a data que vem na própria resposta", async () => {
    responder("GET", "/escolas/1/turmas", [turmaFake({ id: 1, nome: "3º Ano A" })]);
    responder("GET", "/escolas/1/premiacoes", premiacoes({ frescor: frescor() }));
    responder("GET", "/escolas/1/ranking-evolucao", []);
    renderComApp(<Premiacoes />);

    expect(await screen.findByText("Leitura (Elefante Letrado): dados de 19/10/2026 (há 3 dias)"))
      .toBeInTheDocument();
    expect(screen.getByText("Matemática (Matific): dados de 19/10/2026 (há 3 dias)"))
      .toBeInTheDocument();
  });

  it("dado antigo: o selo avisa que o pódio pode não refletir a situação atual", async () => {
    responder("GET", "/escolas/1/turmas", [turmaFake({ id: 1, nome: "3º Ano A" })]);
    responder("GET", "/escolas/1/premiacoes", premiacoes({ frescor: frescor("desatualizado") }));
    responder("GET", "/escolas/1/ranking-evolucao", []);
    renderComApp(<Premiacoes />);

    expect(await screen.findByText(/Dado com mais de 7 dias: o mais recente é de/))
      .toBeInTheDocument();
    expect(screen.getByText("Melhor Leitor")).toBeInTheDocument();
  });

  it("resposta sem o bloco (API antiga): nenhum selo e nada quebra", async () => {
    responder("GET", "/escolas/1/turmas", [turmaFake({ id: 1, nome: "3º Ano A" })]);
    responder("GET", "/escolas/1/premiacoes", premiacoes());
    responder("GET", "/escolas/1/ranking-evolucao", []);
    renderComApp(<Premiacoes />);

    expect(await screen.findByText("Melhor Leitor")).toBeInTheDocument();
    expect(screen.queryByLabelText("Data dos dados")).not.toBeInTheDocument();
  });
});

describe("Painel da escola — data do dado", () => {
  it("mostra o selo dos rankings ao lado dos indicadores", async () => {
    responder("GET", "/escolas/1/dashboard", dashboardFake());
    responder("GET", "/escolas/1/ranking/frescor", frescor());
    renderComApp(<Dashboard />);

    expect(await screen.findByText("Leitura (Elefante Letrado): dados de 19/10/2026 (há 3 dias)"))
      .toBeInTheDocument();
    expect(screen.getByText("Top 5 — Ranking Geral")).toBeInTheDocument();
  });

  it("falha ao buscar o frescor não derruba o painel nem inventa data", async () => {
    responder("GET", "/escolas/1/dashboard", dashboardFake());
    responderErro("GET", "/escolas/1/ranking/frescor", 500, "Erro interno");
    renderComApp(<Dashboard />);

    expect(await screen.findByText("Top 5 — Ranking Geral")).toBeInTheDocument();
    expect(screen.queryByLabelText("Data dos dados")).not.toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// Painel da REDE (Secretaria): as médias somam escolas com retratos de dias
// diferentes — o painel diz a faixa de datas e quais escolas estão paradas.
// ---------------------------------------------------------------------------
const secretaria = usuarioFake({ rede_id: 7, cargo: "coordenador" });
const ESCOLAS = [
  escolaFake({ id: 1, nome: "EMEF Ficticia Um" }),
  escolaFake({ id: 2, nome: "EMEF Ficticia Dois" }),
];

function cartao(over: Record<string, unknown> = {}) {
  return {
    escola_id: 1, nome: "EMEF Ficticia Um", cidade: "Cidade Ficticia", status: "ativa",
    latitude: null, longitude: null, total_turmas: 3, total_professores: 4,
    total_alunos: 15, alunos_com_dados: 15, adocao: 100, media_geral: 73.5,
    media_matific: 70, media_elefante: 65, livros: 40, tempo_leitura_min: 100,
    atividades: 500, estrelas: 2000, ativos_matific: 15, ativos_elefante: 15,
    livros_por_aluno: 2.7, precisa_atencao: false, motivo_atencao: null, posicao: 1,
    ...over,
  };
}

function semearRede() {
  responder("GET", "/redes/7/dashboard", {
    rede_id: 7,
    totais: {
      escolas: 2, escolas_ativas: 2, alunos: 17, turmas: 4, professores: 6,
      alunos_com_dados: 17, adocao: 100, media_geral: 71.9, media_matific: 68.5,
      media_elefante: 61.2, escolas_em_atencao: 0, livros: 67, tempo_leitura_min: 400,
      atividades: 915, estrelas: 4779, ativos_matific: 17, ativos_elefante: 17,
      livros_por_aluno: 3.9, melhor_escola: { nome: "EMEF Ficticia Um", media_geral: 73.5 },
    },
    equidade: { gap_media: 13.5, escola_maior_media: 73.5, escola_menor_media: 60,
      escolas_abaixo_da_media: 1 },
    escolas: [cartao(), cartao({ escola_id: 2, nome: "EMEF Ficticia Dois", total_alunos: 2 })],
    atencao: [],
  });
  responder("GET", "/redes/7/metas", []);
  const parada = frescor("desatualizado");
  responder("GET", "/redes/7/ranking/frescor", {
    limite_dias: 7, hoje: "2026-10-22",
    escolas: [
      { ...frescor(), escola_id: 1, nome: "EMEF Ficticia Um" },
      { ...parada, escola_id: 2, nome: "EMEF Ficticia Dois" },
    ],
  });
}

describe("Painel da rede — data do dado", () => {
  it("consolidado: faixa de datas por dimensão e as escolas paradas", async () => {
    semearRede();
    renderComApp(<Dashboard />, { usuario: secretaria, escolas: ESCOLAS });

    expect(await screen.findByText(/Leitura: dados das escolas de 01\/10\/2026 a 19\/10\/2026/))
      .toBeInTheDocument();
    expect(screen.getByText(/Matemática: dados das escolas de 19\/10\/2026/)).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(
      /1 escola\(s\) com dado de mais de 7 dias .*EMEF Ficticia Dois/);
  });

  it("com uma escola no contexto, '/' continua o Panorama da Rede, com a data do dado da rede (a da escola fica na ficha)", async () => {
    semearRede();
    renderComApp(<Dashboard />, { usuario: secretaria, escolas: ESCOLAS, escolaSelecionada: 2 });

    // DESENHO3 §1: o antigo "Panorama Geral da <escola>" saiu (a escola tem a ficha própria).
    expect(await screen.findByRole("heading", { level: 1, name: "Panorama da Rede" })).toBeInTheDocument();
    expect(await screen.findByText(/Leitura: dados das escolas de 01\/10\/2026 a 19\/10\/2026/)).toBeInTheDocument();
    expect(screen.queryByText("Panorama Geral da EMEF Ficticia Dois")).not.toBeInTheDocument();
  });

  it("falha ao buscar o frescor da rede não derruba o painel", async () => {
    semearRede();
    responderErro("GET", "/redes/7/ranking/frescor", 500, "Erro interno");
    renderComApp(<Dashboard />, { usuario: secretaria, escolas: ESCOLAS });

    // A tela inicial da Secretaria é o Panorama da Rede (DESENHO2 §2.3.1), com o selo no cabeçalho.
    expect(await screen.findByRole("heading", { level: 1, name: "Panorama da Rede" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Data dos dados")).not.toBeInTheDocument();
  });
});
