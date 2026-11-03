/**
 * Panorama de uma rede (o admin global, na Visão Global) — UMA régua só para o que COMPARA
 * escolas. O Painel da Rede (`/rede`) não repete mais a ordem das escolas: a lista "Ranking
 * das escolas" saiu (duplicava o Ranking da Rede), e a escola fora da comparação é nomeada no
 * Ranking da Rede (RankingRede.test).
 *
 * O backend tirou da equidade, do índice e do Ranking da Rede a escola em que só
 * a Educação Infantil usa a plataforma (nenhum aluno do 1º–5º ano com dado), e
 * marca cada cartão do `/dashboard` com `comparada`. O painel, porém, filtrava o
 * Top 5 e o Comparativo por `alunos_com_dados > 0` — cobertura, que conta as
 * Fases: a escola entrava no Comparativo com índice 0, logo acima do cartão de
 * Equidade que já a deixava de fora, e no Top 5 "Engajamento" em 1º lugar, com
 * uma posição que o ranking completo (para onde o atalho leva) não tem.
 *
 * Escolas e números INVENTADOS.
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
import { escolaFake, renderComApp, responder, screen, userEvent, usuarioFake } from "./utils";

const secretaria = usuarioFake({ rede_id: 7, cargo: "coordenador", escola_id: null });
const admin = usuarioFake({ nome: "Admin Sintético", is_global: true, cargo: "admin", escola_id: null });

function cartao(over: Record<string, unknown> = {}) {
  return {
    escola_id: 1, nome: "EM Fundamental Testelli", cidade: "Cidade Ficticia", status: "ativa",
    latitude: null, longitude: null, total_turmas: 2, total_professores: 2,
    total_alunos: 10, alunos_com_dados: 5, adocao: 50,
    media_geral: 60, media_matific: 60, media_elefante: 60,
    dimensoes_com_dados: ["leitura", "matematica"], alunos_com_nota_elefante: 5,
    alunos_com_nota_matific: 5, adocao_elefante: 50, adocao_matific: 50,
    livros: 25, tempo_leitura_min: 250, atividades: 25, estrelas: 50,
    ativos_matific: 5, ativos_elefante: 5, livros_por_aluno: 5,
    livros_por_matricula: 2.5, estrelas_por_matricula: 5,
    atividades_por_matricula: 2.5, tempo_por_matricula_min: 25,
    pontuacao_leitura: 1000, pontuacao_matematica: 1000, pontuacao_geral: 1000,
    dimensoes_pontuadas: ["leitura", "matematica"], modulos: ["leitura", "matematica"],
    precisa_atencao: false, motivo_atencao: null,
    comparada: true, posicao: 1,
    ...over,
  };
}

// Só a Fase usa a plataforma: adoção 100% (cobertura real), nada a comparar.
const SO_FASE = cartao({
  escola_id: 2, nome: "EM So Fase Ficticio", total_alunos: 4, alunos_com_dados: 4, adocao: 100,
  media_geral: 0, media_matific: 0, media_elefante: 0, dimensoes_com_dados: [],
  alunos_com_nota_elefante: 0, alunos_com_nota_matific: 0, adocao_elefante: 100, adocao_matific: 100,
  livros: 40, estrelas: 80, ativos_elefante: 4, ativos_matific: 4,
  livros_por_matricula: 0, estrelas_por_matricula: 0, atividades_por_matricula: 0,
  tempo_por_matricula_min: 0,
  pontuacao_leitura: 0, pontuacao_matematica: 0, pontuacao_geral: 0, dimensoes_pontuadas: [],
  comparada: false, posicao: null,
});

function dashRede(escolas: unknown[]) {
  return {
    rede_id: 7,
    modulos: ["leitura", "matematica"],
    totais: {
      escolas: 2, escolas_ativas: 2, alunos: 14, turmas: 4, professores: 4,
      alunos_com_dados: 9, adocao: 64.3, media_geral: 60, media_matific: 60,
      media_elefante: 60, pontuacao_geral: 1000, escolas_em_atencao: 0,
      livros: 65, tempo_leitura_min: 650, atividades: 25, estrelas: 130,
      ativos_matific: 9, ativos_elefante: 9, livros_por_aluno: 7.2,
      melhor_escola: { nome: "EM Fundamental Testelli", pontuacao_geral: 1000, media_geral: 60 },
    },
    // Uma só escola comparada: não há distância entre escolas a medir.
    equidade: {
      gap_indice: 0, escola_maior_indice: 1000, escola_menor_indice: 1000,
      escolas_abaixo_do_indice_medio: 0,
      gap_media: 0, escola_maior_media: 60, escola_menor_media: 60, escolas_abaixo_da_media: 0,
    },
    escolas,
    atencao: [],
  };
}

/** Cópia do cartão sem as chaves pedidas (o formato de uma API anterior). */
function semChaves(obj: Record<string, unknown>, ...chaves: string[]) {
  const copia = { ...obj };
  for (const chave of chaves) delete copia[chave];
  return copia;
}

function semear(escolas: unknown[] = [cartao(), SO_FASE]) {
  responder("GET", "/redes/7/dashboard", dashRede(escolas));
  responder("GET", "/redes/7/metas", []);
  responder("GET", "/redes/7/publico", { ativo: false, token: null, url: null });
}

function nomesDaTabela(titulo: string, porCard = false) {
  const h2 = screen.getByText(titulo);
  // O título do Top 5 fica num cabeçalho com os botões; o do Comparativo é filho direto do card.
  const card = porCard ? h2.closest("div")!.parentElement! : h2.closest("div")!;
  return Array.from(card.querySelector("table")!.querySelectorAll("tbody tr"))
    .map((linha) => linha.textContent ?? "");
}

describe("Panorama de uma rede — quem é comparado é decisão do backend", () => {
  it("o Comparativo entre escolas não lista a escola só com a Fase", async () => {
    semear();
    renderComApp(<PanoramaDaRede redeId={7} />, { usuario: admin, escolas: [escolaFake()] });
    await screen.findByText("Comparativo entre escolas");

    const linhas = nomesDaTabela("Comparativo entre escolas");
    expect(linhas).toHaveLength(1);
    expect(linhas[0]).toContain("EM Fundamental Testelli");
    // E o cartão de Equidade, logo abaixo, mede as MESMAS escolas.
    expect(screen.getByText("Equidade da rede").closest("div")!.textContent).toContain("1.000 → 1.000");
  });

  it("o Top 5 usa a entrada do Ranking da Rede no critério padrão e no Engajamento", async () => {
    semear();
    renderComApp(<PanoramaDaRede redeId={7} />, { usuario: admin, escolas: [escolaFake()] });
    await screen.findByText("Top 5 escolas da rede");

    expect(nomesDaTabela("Top 5 escolas da rede", true)).toEqual([
      expect.stringContaining("EM Fundamental Testelli"),
    ]);
    // Engajamento: a só-Fase (100%) passava à frente da outra (50%) — e o ranking
    // completo, para onde o atalho leva, nem a lista.
    await userEvent.click(screen.getByRole("button", { name: "Engajamento" }));
    const engajamento = nomesDaTabela("Top 5 escolas da rede", true);
    expect(engajamento).toHaveLength(1);
    expect(engajamento[0]).toContain("EM Fundamental Testelli");
    expect(engajamento[0]).not.toContain("EM So Fase Ficticio");
  });

  it("sem a marca (API anterior pelo cache do PWA), cai na mesma regra do backend", async () => {
    // Sem `comparada`: quem decide é `dimensoes_pontuadas`, o que o backend testa.
    semear([semChaves(cartao(), "comparada"), semChaves(SO_FASE, "comparada", "posicao")]);
    renderComApp(<PanoramaDaRede redeId={7} />, { usuario: admin, escolas: [escolaFake()] });
    await screen.findByText("Comparativo entre escolas");

    expect(nomesDaTabela("Comparativo entre escolas")).toEqual([
      expect.stringContaining("EM Fundamental Testelli"),
    ]);
  });

  it("o Painel da Rede (Secretaria) não repete a ordem das escolas: nem posição nem índice, só os atalhos", async () => {
    semear();
    renderComApp(<RedeDashboard />, { rota: "/rede", usuario: secretaria });
    const atalhos = await screen.findByTestId("comparar-as-escolas");
    expect(screen.queryByText("Ranking das escolas")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Filtrar escola")).not.toBeInTheDocument();
    // Nenhum índice de escola (o 1.000 da Testelli) nem posição aparece no painel.
    expect(screen.queryByText("1.000")).not.toBeInTheDocument();
    expect(atalhos).toHaveTextContent("Escolas");
    expect(atalhos).toHaveTextContent("Ranking da Rede");
  });
});

/* O `oculto` (grupo pequeno) só vem para a Secretaria, que não abre mais este panorama; a
 * proteção dela vive no Ranking da Rede (RankingRede.test). Aqui fica a DEFESA do panorama:
 * se a API mandar um valor escondido, ele nunca vira 0 nem entra no Top 5. */
describe("Panorama de uma rede — valor escondido pela API (grupo pequeno) nunca vira 0", () => {
  const TEXTO = "Menos de 3 alunos com dado nesta matéria na escola: para proteger as crianças, a média e os totais não aparecem.";
  // Leitura escondida (2 alunos com dado), Matemática visível.
  const PROTEGIDA = cartao({
    escola_id: 3, nome: "EM Protegida Ficticia", total_alunos: 30,
    media_elefante: null, livros: null, tempo_leitura_min: null, livros_por_aluno: null,
    livros_por_matricula: null, tempo_por_matricula_min: null, pontuacao_leitura: null,
    media_geral: 55, pontuacao_geral: 800, pontuacao_matematica: 800,
    dimensoes_pontuadas: ["matematica"], posicao: 2,
    grupo_pequeno: true, oculto: { leitura: { motivo: "grupo_pequeno", texto: TEXTO, parcial: false }, matematica: null },
  });

  function semearProtegida() {
    const dash = dashRede([cartao(), PROTEGIDA]) as ReturnType<typeof dashRede> & Record<string, unknown>;
    dash.totais = {
      ...dash.totais,
      grupo_pequeno: { leitura: 1, matematica: 0, texto: "Os totais de Leitura deixam de fora 1 escola com menos de 3 alunos com dado." },
    } as typeof dash.totais;
    dash.ocultas = [{ escola_id: 3, nome: "EM Protegida Ficticia", grupo_pequeno: true, oculto: PROTEGIDA.oculto }];
    responder("GET", "/redes/7/dashboard", dash);
    responder("GET", "/redes/7/metas", []);
    responder("GET", "/redes/7/publico", { ativo: false, token: null, url: null });
  }

  it("totais declaram a escola de fora; o Comparativo mostra '— protegido' na Leitura", async () => {
    semearProtegida();
    renderComApp(<PanoramaDaRede redeId={7} />, { usuario: admin, escolas: [escolaFake()] });
    await screen.findByText("Comparativo entre escolas");

    expect(screen.getByText("Os totais de Leitura deixam de fora 1 escola com menos de 3 alunos com dado.")).toBeInTheDocument();
    const linhas = nomesDaTabela("Comparativo entre escolas");
    const protegida = linhas.find((l) => l.includes("EM Protegida Ficticia"))!;
    expect(protegida).toContain("— protegido");
    expect(protegida).toContain(TEXTO);  // motivo para o leitor de tela
  });

  it("Top 5 por Livros/aluno: a escola com a leitura escondida não entra (nunca com 0)", async () => {
    semearProtegida();
    renderComApp(<PanoramaDaRede redeId={7} />, { usuario: admin, escolas: [escolaFake()] });
    await screen.findByText("Top 5 escolas da rede");

    expect(nomesDaTabela("Top 5 escolas da rede", true).some((l) => l.includes("EM Protegida Ficticia"))).toBe(true);
    await userEvent.click(screen.getByRole("button", { name: "Livros/aluno" }));
    const porLivros = nomesDaTabela("Top 5 escolas da rede", true);
    expect(porLivros.some((l) => l.includes("EM Protegida Ficticia"))).toBe(false);
    expect(porLivros[0]).toContain("EM Fundamental Testelli");
  });
});
