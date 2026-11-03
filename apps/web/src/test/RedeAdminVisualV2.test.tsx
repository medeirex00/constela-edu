/**
 * Telas da rede e do Admin Global — achados da revisão visual v2 (frente "rede-admin").
 *
 *  - "/rede" tem UM nome: o h1 é "Painel da Rede", como a trilha do topo e o menu da
 *    Secretaria (antes: "Secretaria de Educação");
 *  - os textos que mandam a outra tela usam o nome que quem lê vê (nada de "aparece no
 *    Dashboard" nem "na aba Secretaria"); no Painel da Rede o progresso das metas fica na
 *    própria página, ao lado do cadastro;
 *  - o Painel da Rede não repete a ordem das escolas: os atalhos levam a Escolas e
 *    ao Ranking da Rede;
 *  - os alertas de uso (Painel da Rede) e "Escolas que precisam de atenção" (Panorama de uma
 *    rede, admin global) são recolhíveis (o h2 continua, com o selo da contagem dentro dele);
 *  - Visão Global sem rede: a comparação diz que não há rede (antes, só o cabeçalho);
 *  - Visão Global: a escola aberta pelas "Top escolas" volta para a Visão Global (antes, ao
 *    Painel da Rede, que abre a rede da conta ou a primeira da lista);
 *  - Importações e fontes sem rede: a mesma mensagem e ação das telas irmãs;
 *  - Escolas: a orientação aponta para o cartão "Escola" do menu lateral (o seletor
 *    saiu do topo) e os botões da linha mantêm nome e dica mesmo só com o ícone.
 *
 * Escolas, redes e números INVENTADOS.
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

import { Route, Routes, useLocation } from "react-router-dom";

import Escolas from "../pages/Escolas";
import VisaoEscola from "../pages/VisaoEscola";
import RedeAvaliacoes from "../pages/rede/RedeAvaliacoes";
import RedeDashboard, { PanoramaDaRede, PanoramaGlobal } from "../pages/rede/RedeDashboard";
import { api, escolaFake, renderComApp, responder, screen, userEvent, usuarioFake, within } from "./utils";

const secretaria = usuarioFake({ nome: "Secretaria Sintética", rede_id: 7, cargo: "coordenador", escola_id: null });
const admin = usuarioFake({ nome: "Admin Sintético", is_global: true, cargo: "admin", escola_id: null });

function Local() {
  const { pathname } = useLocation();
  return <p data-testid="local">{pathname}</p>;
}

function cartao(over: Record<string, unknown> = {}) {
  return {
    escola_id: 1, nome: "EMEF Sintética Constelação do Vale", cidade: "Cidade Sintética", status: "ativa",
    latitude: null, longitude: null, total_turmas: 2, total_professores: 2,
    total_alunos: 15, alunos_com_dados: 15, adocao: 100,
    media_geral: 60, media_matific: 60, media_elefante: 60,
    dimensoes_com_dados: ["leitura", "matematica"], alunos_com_nota_elefante: 15,
    alunos_com_nota_matific: 15, adocao_elefante: 100, adocao_matific: 100,
    livros: 30, tempo_leitura_min: 300, atividades: 30, estrelas: 60,
    ativos_matific: 15, ativos_elefante: 15, livros_por_aluno: 2,
    livros_por_matricula: 2, estrelas_por_matricula: 4,
    atividades_por_matricula: 2, tempo_por_matricula_min: 20,
    pontuacao_leitura: 1000, pontuacao_matematica: 1000, pontuacao_geral: 1000,
    dimensoes_pontuadas: ["leitura", "matematica"], modulos: ["leitura", "matematica"],
    precisa_atencao: false, motivo_atencao: null, comparada: true, posicao: 1,
    ...over,
  };
}

const EM_ATENCAO = cartao({
  escola_id: 2, nome: "EMEF Sintética Segunda", total_alunos: 0, alunos_com_dados: 0, adocao: 0,
  livros: 0, atividades: 0, estrelas: 0, comparada: false, posicao: null, dimensoes_pontuadas: [],
  precisa_atencao: true, motivo_atencao: "Sem alunos matriculados no ano letivo (sintético).",
});

function dashRede() {
  return {
    rede_id: 7,
    modulos: ["leitura", "matematica"],
    totais: {
      escolas: 2, escolas_ativas: 2, alunos: 15, turmas: 4, professores: 4,
      alunos_com_dados: 15, adocao: 100, media_geral: 60, media_matific: 60,
      media_elefante: 60, pontuacao_geral: 1000, escolas_em_atencao: 1,
      livros: 30, tempo_leitura_min: 300, atividades: 30, estrelas: 60,
      ativos_matific: 15, ativos_elefante: 15, livros_por_aluno: 2,
      melhor_escola: { nome: "EMEF Sintética Constelação do Vale", pontuacao_geral: 1000, media_geral: 60 },
    },
    equidade: {
      gap_indice: 0, escola_maior_indice: 1000, escola_menor_indice: 1000,
      escolas_abaixo_do_indice_medio: 0,
      gap_media: 0, escola_maior_media: 60, escola_menor_media: 60, escolas_abaixo_da_media: 0,
    },
    escolas: [cartao(), EM_ATENCAO],
    atencao: [EM_ATENCAO],
  };
}

function semearRede() {
  responder("GET", "/redes/7/dashboard", dashRede());
  responder("GET", "/redes/7/metas", []);
  responder("GET", "/redes/7/publico", { ativo: false, token: null, url: null });
}

// =============================================================================
// Painel da Rede (/rede)
// =============================================================================

describe("Painel da Rede (/rede) — um nome só e os destinos pelo nome do menu", () => {
  it("o h1 é 'Painel da Rede' (o nome da trilha e do menu da Secretaria)", async () => {
    semearRede();
    renderComApp(<RedeDashboard />, { rota: "/rede", usuario: secretaria });
    expect(await screen.findByRole("heading", { level: 1, name: "Painel da Rede" })).toBeInTheDocument();
    expect(screen.queryByText("Secretaria de Educação")).not.toBeInTheDocument();
  });

  it("Secretaria: as metas dizem que o progresso aparece nesta página — e salvar atualiza o progresso", async () => {
    const META = { id: 9, metrica: "pontuacao_geral", rotulo: "Índice da rede (0–1000)", sufixo: "", alvo: 800,
                   atual: 640, progresso: 80, atingida: false, descricao: null, comparavel: true,
                   escolas_atingiram: 0, escolas_total: 2 };
    let salvas: unknown[] = [];
    semearRede();
    responder("GET", "/redes/7/metas", () => salvas);
    responder("PUT", "/redes/7/metas", () => { salvas = [META]; return { ok: true }; });
    const u = userEvent.setup();
    renderComApp(<RedeDashboard />, { rota: "/rede", usuario: secretaria });
    expect(await screen.findByText(/Defina o alvo de cada indicador/))
      .toHaveTextContent("O progresso é calculado com o dado real e aparece em “Progresso das metas”, nesta página.");
    expect(screen.queryByText(/Dashboard/)).not.toBeInTheDocument();
    expect(await screen.findByText(/Nenhuma meta definida ainda/))
      .toHaveTextContent("Cadastre a primeira em “Metas da rede”, nesta página");

    await u.type(screen.getByLabelText("Valor-alvo da meta"), "800");
    await u.click(screen.getByRole("button", { name: "Salvar meta" }));
    expect(await screen.findByText("Meta salva. O progresso aparece em “Progresso das metas”, nesta página."))
      .toBeInTheDocument();
    // A MESMA chamada de antes.
    const put = api.mock.calls.find(([c, o]) => c === "/redes/7/metas" && (o as RequestInit)?.method === "PUT");
    expect(JSON.parse(String((put![1] as RequestInit).body))).toEqual({ metrica: "pontuacao_geral", alvo: 800 });
    // O progresso (a mesma leitura do cadastro) já mostra a meta nova, sem recarregar a página.
    expect(await screen.findByText("0 de 2 escolas atingiram")).toBeInTheDocument();
    expect(screen.getByTestId("resumo-metas")).toHaveTextContent("0 de 1 meta atingida");
  });

  it("Admin Global: o progresso aparece na Visão Global, ao abrir a rede", async () => {
    responder("GET", "/redes", [{ id: 7, nome: "Rede Sintética" }]);
    semearRede();
    renderComApp(<RedeDashboard />, { rota: "/rede", usuario: admin });
    expect(await screen.findByText(/Defina o alvo de cada indicador/))
      .toHaveTextContent("aparece em “Progresso das metas”, nesta página, e na Visão Global, ao abrir esta rede.");
  });

  it("a lista 'Ranking das escolas' saiu: os atalhos levam a Escolas e ao Ranking da Rede", async () => {
    semearRede();
    renderComApp(<RedeDashboard />, { rota: "/rede", usuario: secretaria });
    const atalhos = await screen.findByTestId("comparar-as-escolas");
    expect(screen.queryByText("Ranking das escolas")).not.toBeInTheDocument();
    expect(within(atalhos).getByRole("link", { name: /^Escolas/ })).toHaveAttribute("href", "/rede/escolas");
    expect(within(atalhos).getByRole("link", { name: /Ranking da Rede/ })).toHaveAttribute("href", "/rede/ranking");
  });

  it("Admin Global: os atalhos levam a rede mostrada junto", async () => {
    responder("GET", "/redes", [{ id: 7, nome: "Rede Sintética" }]);
    semearRede();
    renderComApp(<RedeDashboard />, { rota: "/rede", usuario: admin });
    const atalhos = await screen.findByTestId("comparar-as-escolas");
    expect(within(atalhos).getByRole("link", { name: /^Escolas/ })).toHaveAttribute("href", "/rede/escolas?rede=7");
    expect(within(atalhos).getByRole("link", { name: /Ranking da Rede/ })).toHaveAttribute("href", "/rede/ranking?rede=7");
  });
});

// =============================================================================
// Alertas de uso (Painel da Rede) e o Panorama de uma rede (admin global)
// =============================================================================

describe("Painel da Rede e Panorama de uma rede — metas e escolas com alerta", () => {
  it("Painel: o cartão de alertas diz a regra e a natureza e leva às Escolas em acompanhamento", async () => {
    semearRede();
    const u = userEvent.setup();
    renderComApp(<><Local /><RedeDashboard /></>, { rota: "/rede", usuario: secretaria });
    const titulo = await screen.findByRole("heading", { name: /Escolas com alerta de uso das plataformas/ });
    const cartao = titulo.parentElement as HTMLElement;
    const regra = within(cartao).getByTestId("regra-alerta-uso");
    expect(within(regra).getByText("Calculado pelo Constela")).toBeInTheDocument();
    expect(regra).toHaveTextContent("adoção abaixo de 40%");
    expect(regra).toHaveTextContent("Não é avaliação oficial.");
    const link = within(cartao).getByRole("link", { name: "Escolas em acompanhamento" });
    expect(link).toHaveAttribute("href", "/rede/acompanhamento");
    expect(link.closest("p")).toHaveTextContent(
      "Os sinais das avaliações externas e das plataformas, escola por escola, ficam em Escolas em acompanhamento.");
    // A lista continua a do painel da rede (a mesma escola, o mesmo motivo) — e abre a escola.
    expect(within(cartao).getAllByRole("listitem")).toHaveLength(1);
    await u.click(within(cartao).getByRole("button", { name: "EMEF Sintética Segunda" }));
    expect(screen.getByTestId("local")).toHaveTextContent("/escola");
  });

  it("Panorama (admin global): sem meta, manda definir pelo caminho do menu dele, não na 'aba Secretaria'", async () => {
    semearRede();
    renderComApp(<PanoramaDaRede redeId={7} />, { usuario: admin, escolas: [escolaFake()] });
    const convite = await screen.findByText(/Nenhuma meta definida ainda/);
    expect(convite).toHaveTextContent("Defina as metas da rede em Redes e municípios › Painel da Rede, no menu");
    expect(convite).not.toHaveTextContent(/aba Secretaria/);
  });

  it("'Escolas que precisam de atenção' é recolhível e o selo da contagem fica no título", async () => {
    semearRede();
    const u = userEvent.setup();
    renderComApp(<PanoramaDaRede redeId={7} />, { usuario: admin, escolas: [escolaFake()] });

    const titulo = await screen.findByRole("heading", { name: /Escolas que precisam de atenção/ });
    expect(within(titulo).getByText("1")).toBeInTheDocument();
    const alternar = within(titulo).getByRole("button");
    expect(alternar).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("button", { name: "EMEF Sintética Segunda" })).toBeVisible();
    expect(screen.getByText("Sem alunos matriculados no ano letivo (sintético).")).toBeVisible();

    await u.click(alternar);
    expect(alternar).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("button", { name: "EMEF Sintética Segunda" })).not.toBeInTheDocument();
    expect(screen.getByText("Sem alunos matriculados no ano letivo (sintético).")).not.toBeVisible();

    await u.click(alternar);
    expect(alternar).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("button", { name: "EMEF Sintética Segunda" })).toBeVisible();
  });

  it("Admin Global: o link de Escolas em acompanhamento leva a rede aberta junto — a regra do cartão não muda", async () => {
    semearRede();
    renderComApp(<PanoramaDaRede redeId={7} />, { usuario: admin, escolas: [escolaFake()] });
    const titulo = await screen.findByRole("heading", { name: /Escolas que precisam de atenção/ });
    const cartao = titulo.parentElement as HTMLElement;
    expect(within(cartao).getByRole("link", { name: "Escolas em acompanhamento" }))
      .toHaveAttribute("href", "/rede/acompanhamento?rede=7");
    expect(within(cartao).getAllByRole("listitem")).toHaveLength(1);
    // No Panorama de uma rede o título e a lista são os de sempre (sem a nota da regra do Painel).
    expect(within(cartao).queryByTestId("regra-alerta-uso")).not.toBeInTheDocument();
  });
});

// =============================================================================
// Visão Global (Admin Global)
// =============================================================================

function panoramaGlobal(redes: unknown[]) {
  return {
    totais: {
      redes: redes.length, escolas: 0, alunos: 0, turmas: 0, professores: 0,
      livros: 0, atividades: 0, estrelas: 0, media_geral: 0, media_matific: 0, media_elefante: 0,
      escolas_em_atencao: 0,
    },
    redes,
    top_escolas: [],
  };
}

describe("Visão Global — comparação entre redes", () => {
  it("sem rede nenhuma, diz que não há o que comparar (antes ficava só o cabeçalho da tabela)", async () => {
    responder("GET", "/redes/panorama-global", panoramaGlobal([]));
    const u = userEvent.setup();
    renderComApp(<><Local /><PanoramaGlobal /></>, { usuario: admin });

    expect(await screen.findByText("Nenhuma rede para comparar ainda.")).toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "Rede" })).not.toBeInTheDocument();
    await u.click(screen.getByRole("button", { name: /Gerenciar redes/ }));
    expect(screen.getByTestId("local")).toHaveTextContent("/rede/gerenciar");
  });

  it("a escola aberta pelas 'Top escolas' volta para a Visão Global, com esse nome", async () => {
    responder("GET", "/redes/panorama-global", {
      ...panoramaGlobal([]),
      top_escolas: [cartao({ escola_id: 2, nome: "EMEF Sintética da Rede B", rede_id: 9, rede_nome: "Rede Sintética B",
                             pontuacao_geral_global: 900 })],
    });
    responder("GET", /\/escolas\/\d+\/resumo-escola/, { escola: { id: 2, nome: "EMEF Sintética da Rede B" }, turmas: [] });
    const u = userEvent.setup();
    renderComApp(
      <Routes>
        <Route path="/" element={<PanoramaGlobal />} />
        <Route path="/escola" element={<VisaoEscola />} />
        <Route path="/rede" element={<p>TELA:painel-da-rede</p>} />
      </Routes>,
      { usuario: admin },
    );
    await u.click(await screen.findByRole("button", { name: /EMEF Sintética da Rede B/ }));
    const voltar = await screen.findByRole("link", { name: "Voltar para a Visão Global" });
    expect(voltar).toHaveAttribute("href", "/");
    expect(screen.queryByRole("link", { name: "Voltar ao Painel da Rede" })).not.toBeInTheDocument();
    await u.click(voltar);
    expect(await screen.findByText("Panorama Global — Todas as Redes")).toBeInTheDocument();
  });

  it("com rede, a tabela continua (o nome e a UF no mesmo botão, que abre a rede)", async () => {
    responder("GET", "/redes/panorama-global", panoramaGlobal([{
      rede_id: 3, nome: "Rede Municipal Sintética", uf: "SP", status: "ativa",
      escolas: 2, alunos: 15, turmas: 3, professores: 2, alunos_com_dados: 15,
      adocao: 100, media_geral: 70, media_matific: 70, media_elefante: 65,
      livros: 40, atividades: 500, estrelas: 2000, escolas_em_atencao: 0,
      livros_por_matricula: 2.7, estrelas_por_matricula: 133.3, pontuacao_geral: 1000, posicao: 1,
    }]));
    renderComApp(<PanoramaGlobal />, { usuario: admin });
    expect(await screen.findByRole("columnheader", { name: "Rede" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Rede Municipal Sintética · SP" })).toBeInTheDocument();
    expect(screen.queryByText("Nenhuma rede para comparar ainda.")).not.toBeInTheDocument();
  });
});

// =============================================================================
// Importações e fontes (/rede/avaliacoes) sem rede
// =============================================================================

describe("Importações e fontes — Admin Global sem rede", () => {
  it("a mesma mensagem e o 'Gerenciar redes' das telas irmãs, e a descrição no cabeçalho", async () => {
    responder("GET", "/redes", []);
    const u = userEvent.setup();
    renderComApp(<><Local /><RedeAvaliacoes /></>, { rota: "/rede/avaliacoes", usuario: admin });

    expect(await screen.findByRole("heading", { level: 1, name: "Importações e fontes" })).toBeInTheDocument();
    // A área de fontes e arquivos oficiais se diz o detalhe técnico.
    expect(screen.getByText(/Fontes e arquivos oficiais \(detalhe técnico\): cada indicador oficial \(ICA, SARESP, Ideb e Saeb\)/))
      .toBeInTheDocument();
    expect(screen.getByText(/Ainda não há redes cadastradas/)).toBeInTheDocument();
    expect(screen.queryByText(/não está vinculada a uma rede/)).not.toBeInTheDocument();
    await u.click(screen.getByRole("button", { name: /Gerenciar redes/ }));
    expect(screen.getByTestId("local")).toHaveTextContent("/rede/gerenciar");
  });
});

// =============================================================================
// Escolas (/escolas)
// =============================================================================

describe("Escolas — orientação e botões da linha", () => {
  it("a troca de escola aponta para o cartão 'Escola' do menu lateral (o seletor saiu do topo)", async () => {
    renderComApp(<Escolas />, { rota: "/escolas", usuario: admin, escolas: [escolaFake({ id: 1, nome: "Escola Alpha" })] });
    await screen.findByText("Escola Alpha");
    const descricao = screen.getByText(/Todas as escolas da rede/);
    expect(descricao).toHaveTextContent("Troque de escola a qualquer momento pelo cartão “Escola”, no fim do menu lateral.");
    expect(descricao).not.toHaveTextContent(/topo/);
  });

  it("os botões da linha mantêm o nome acessível, a dica e o texto (que só se esconde visualmente em tela estreita)", async () => {
    renderComApp(<Escolas />, { rota: "/escolas", usuario: admin, escolas: [escolaFake({ id: 1, nome: "Escola Alpha" })] });
    await screen.findByText("Escola Alpha");
    const usuarios = screen.getByRole("button", { name: "Usuários de Escola Alpha" });
    expect(usuarios).toHaveAttribute("title", "Usuários");
    expect(within(usuarios).getByText("Usuários")).toBeInTheDocument();
    const desativar = screen.getByRole("button", { name: "Desativar Escola Alpha" });
    expect(desativar).toHaveAttribute("title", "Desativar a escola");
    expect(within(desativar).getByText("Desativar")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Renomear Escola Alpha" })).toHaveAttribute("title", "Renomear");
  });
});

// =============================================================================
// Celular (375–414 px) — revisão das capturas da demo (frente "rede")
// =============================================================================

const REDE_GLOBAL = {
  rede_id: 3, nome: "Rede Municipal Sintética", uf: "SP", status: "ativa",
  escolas: 2, alunos: 15, turmas: 3, professores: 2, alunos_com_dados: 15,
  adocao: 100, media_geral: 70, media_matific: 70, media_elefante: 65,
  livros: 40, atividades: 500, estrelas: 2000, escolas_em_atencao: 0,
  livros_por_matricula: 2.7, estrelas_por_matricula: 133.3, pontuacao_geral: 1000, posicao: 1,
};

/** A grade que contém o StatCard do rótulo dado (rótulo → cartão → grade). */
function gradeDoStatCard(rotulo: string): HTMLElement {
  const cartao = screen.getByText(rotulo, { selector: "span" }).parentElement!;
  expect(cartao).toHaveClass("card");
  return cartao.parentElement!;
}

describe("Celular — Painel da Rede, Panorama de uma rede e Visão Global", () => {
  it("Metas: o indicador ocupa a linha toda no celular (a escala não é cortada); do sm para cima, a linha única", async () => {
    semearRede();
    renderComApp(<RedeDashboard />, { rota: "/rede", usuario: secretaria });
    const indicador = await screen.findByLabelText("Indicador da meta");
    expect(indicador).toHaveClass("max-sm:basis-full", "flex-1", "min-w-[11rem]");
    expect(screen.getByLabelText("Valor-alvo da meta")).toHaveClass("max-sm:flex-1", "basis-28");
    expect(within(indicador).getByRole("option", { name: "Índice da rede (0–1000)" })).toBeInTheDocument();
  });

  it("Visão Global: os quatro indicadores ficam dois por linha, a faixa secundária também, e os chips têm 40 px", async () => {
    responder("GET", "/redes/panorama-global", panoramaGlobal([REDE_GLOBAL]));
    renderComApp(<PanoramaGlobal />, { usuario: admin });
    await screen.findByRole("columnheader", { name: "Rede" });

    const grade = gradeDoStatCard("Professores");
    expect(grade).toHaveClass("grid", "grid-cols-2", "lg:grid-cols-4");
    expect(grade).not.toHaveClass("grid-cols-1");
    for (const rotulo of ["Redes", "Escolas", "Alunos", "Professores"]) {
      expect(gradeDoStatCard(rotulo)).toBe(grade);
    }

    const media = screen.getByText("Média geral").parentElement!;
    expect(media).toHaveClass("col-span-2", "sm:col-span-1");
    expect(media.parentElement).toHaveClass("grid-cols-2", "sm:grid-cols-3");

    const chips = within(screen.getByRole("group", { name: "Critério da comparação" })).getAllByRole("button");
    expect(chips).toHaveLength(4);
    for (const chip of chips) expect(chip).toHaveClass("max-sm:min-h-10");
  });

  it("Panorama de uma rede: os indicadores principais ficam dois por linha no celular", async () => {
    semearRede();
    renderComApp(<PanoramaDaRede redeId={7} />, { usuario: admin, escolas: [escolaFake()] });
    await screen.findByText("Top 5 escolas da rede");

    const grade = gradeDoStatCard("Melhor escola");
    expect(grade).toHaveClass("grid", "grid-cols-2", "lg:grid-cols-4");
    expect(grade).not.toHaveClass("grid-cols-1");
    for (const chip of within(screen.getByRole("group", { name: "Critério do Top 5" })).getAllByRole("button")) {
      expect(chip).toHaveClass("max-sm:min-h-10");
    }
  });
});
