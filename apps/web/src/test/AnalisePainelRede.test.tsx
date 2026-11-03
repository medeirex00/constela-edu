/**
 * Painel da Rede (`/rede`, a área administrativa da Secretaria) depois da reorganização:
 *
 *  - CONCLUSÃO PRIMEIRO: o progresso das metas (que antes só aparecia no Panorama antigo)
 *    abre a página, ao lado do cadastro — "X de Y metas atingidas", a contagem de escolas só
 *    nas metas comparáveis, e salvar uma meta atualiza o progresso (uma leitura só);
 *  - a lista "Ranking das escolas" (duplicava o Ranking da Rede) virou atalhos: Comparar
 *    escolas e Ranking da Rede;
 *  - os textos que citavam "Análise educacional" apontam para as telas novas (Avaliações
 *    externas, Elefante e Matific, Comparar escolas) — o botão antigo saiu;
 *  - Vitrine pública, mapa, boletim e os alertas de uso (a regra do painel, com a natureza)
 *    continuam; nenhuma palavra de causa e efeito;
 *  - meta SEM dado medido (`medida: false`: ninguém aferido ou número protegido) não vira
 *    "0,0 / alvo" nem conta como não atingida;
 *  - o período real dos dados das plataformas (Elefante acumulado desde o início da conta,
 *    Matific no ano letivo — só o que a rede contratou), o vazio dos alertas preso à regra do
 *    cartão (sem "tudo certo") e a legenda do mapa (as faixas, com o corte do alerta: 300).
 *
 * Números e nomes INVENTADOS (D13).
 */
import { describe, expect, it, vi } from "vitest";
import { useLocation } from "react-router-dom";

vi.mock("leaflet", () => ({ default: { divIcon: () => ({}) } }));
vi.mock("react-leaflet", () => ({
  MapContainer: ({ children }: { children?: React.ReactNode }) => <div>{children}</div>,
  TileLayer: () => null,
  Marker: ({ children }: { children?: React.ReactNode }) => <div>{children}</div>,
  Popup: ({ children }: { children?: React.ReactNode }) => <div>{children}</div>,
  useMap: () => ({ setView: () => undefined, fitBounds: () => undefined }),
}));

import { corPorIndice } from "../lib/cores";
import RedeDashboard from "../pages/rede/RedeDashboard";
import { api, apiDownload, renderComApp, responder, screen, userEvent, usuarioFake, within } from "./utils";

const secretaria = usuarioFake({ nome: "Secretaria", cargo: "coordenador", rede_id: 7, escola_id: null });
const admin = usuarioFake({ nome: "Root", cargo: "admin", is_global: true, escola_id: null });

const EM_ATENCAO = {
  escola_id: 3, nome: "EMEF Sintética Atenção", cidade: "Cidade Sintética", status: "ativa",
  latitude: null, longitude: null, total_turmas: 2, total_professores: 2, total_alunos: 30, alunos_com_dados: 6,
  adocao: 20, media_geral: 40, media_matific: 40, media_elefante: 40, dimensoes_com_dados: ["leitura"],
  alunos_com_nota_elefante: 6, alunos_com_nota_matific: 0, adocao_elefante: 20, adocao_matific: 0,
  livros: 12, tempo_leitura_min: 100, atividades: 0, estrelas: 0, ativos_matific: 0, ativos_elefante: 6,
  livros_por_aluno: 2, livros_por_matricula: 0.4, estrelas_por_matricula: 0, atividades_por_matricula: 0,
  tempo_por_matricula_min: 3, pontuacao_leitura: 200, pontuacao_matematica: 0, pontuacao_geral: 200,
  dimensoes_pontuadas: ["leitura"], modulos: ["leitura", "matematica"], comparada: true, posicao: 1,
  precisa_atencao: true, motivo_atencao: "Baixa adoção: só 20% dos alunos têm dados (sintético).",
};

const DASH_REDE = {
  rede_id: 7,
  modulos: ["leitura", "matematica"],
  totais: {
    escolas: 1, escolas_ativas: 1, alunos: 30, turmas: 2, professores: 2, alunos_com_dados: 6, adocao: 20,
    media_geral: 40, media_matific: 40, media_elefante: 40, pontuacao_geral: 200, escolas_em_atencao: 1,
    livros: 12, tempo_leitura_min: 100, atividades: 0, estrelas: 0, ativos_matific: 0, ativos_elefante: 6,
    livros_por_aluno: 2, melhor_escola: null,
  },
  equidade: {
    gap_indice: 0, escola_maior_indice: 200, escola_menor_indice: 200, escolas_abaixo_do_indice_medio: 0,
    gap_media: 0, escola_maior_media: 40, escola_menor_media: 40, escolas_abaixo_da_media: 0,
  },
  escolas: [EM_ATENCAO],
  atencao: [EM_ATENCAO],
};

const META_COMPARAVEL = {
  id: 1, metrica: "pontuacao_geral", rotulo: "Índice da rede (0–1000)", sufixo: "", alvo: 500, atual: 200,
  progresso: 40, atingida: false, descricao: null, comparavel: true, escolas_atingiram: 0, escolas_total: 1,
};
const META_INTERNA = {
  id: 2, metrica: "media_geral", rotulo: "Média geral da rede", sufixo: "", alvo: 30, atual: 40, progresso: 100,
  atingida: true, descricao: null, comparavel: false, escolas_atingiram: null, escolas_total: null,
};

function semear(metas: unknown[] = [META_COMPARAVEL, META_INTERNA]) {
  responder("GET", "/redes/7/dashboard", DASH_REDE);
  responder("GET", "/redes/7/metas", metas);
  responder("GET", "/redes/7/publico", { ativo: false, token: null, url: null });
}

function Local() {
  const { pathname } = useLocation();
  return <p data-testid="local">{pathname}</p>;
}

describe("Painel da Rede (Secretaria) — o progresso das metas abre a página", () => {
  it("'Progresso das metas' vem antes do cadastro, com a conclusão e a contagem só nas metas comparáveis", async () => {
    semear();
    renderComApp(<RedeDashboard />, { rota: "/rede", usuario: secretaria });
    const progresso = await screen.findByRole("heading", { name: "Progresso das metas" });
    const cadastro = screen.getByRole("heading", { name: "Metas da rede" });
    // Conclusão primeiro: o progresso está ANTES do cadastro na página.
    expect(progresso.compareDocumentPosition(cadastro) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(await screen.findByTestId("resumo-metas"))
      .toHaveTextContent("1 de 2 metas atingidas — progresso calculado com o dado real.");
    const cartao = progresso.parentElement as HTMLElement;
    expect(cartao).toHaveTextContent("0 de 1 escolas atingiram");
    // A média 0–100 é régua interna de cada escola: sem contagem de escolas, dizendo por quê.
    expect(cartao).toHaveTextContent("progresso da rede · não comparável entre escolas");
    expect(cartao).toHaveTextContent("✓ atingida");
    // O cadastro continua (com o remover de cada meta).
    expect(screen.getByRole("button", { name: "Remover a meta Média geral da rede" })).toBeInTheDocument();
  });

  it("sem meta, o progresso convida a cadastrar NESTA página (dado real, sem número fictício)", async () => {
    semear([]);
    renderComApp(<RedeDashboard />, { rota: "/rede", usuario: secretaria });
    expect(await screen.findByText(/Nenhuma meta definida ainda/))
      .toHaveTextContent("Cadastre a primeira em “Metas da rede”, nesta página — o progresso (dado real, sem número fictício) aparece aqui.");
    expect(screen.queryByTestId("resumo-metas")).not.toBeInTheDocument();
  });

  it("o progresso e o cadastro usam UMA leitura das metas (não duas chamadas iguais)", async () => {
    semear();
    renderComApp(<RedeDashboard />, { rota: "/rede", usuario: secretaria });
    await screen.findByTestId("resumo-metas");
    expect(api.mock.calls.filter(([c]) => c === "/redes/7/metas")).toHaveLength(1);
  });
});

describe("Painel da Rede (Secretaria) — as comparações e as telas novas", () => {
  it("a descrição aponta para as telas novas; o botão 'Análise educacional' saiu; o boletim continua", async () => {
    semear();
    renderComApp(<RedeDashboard />, { rota: "/rede", usuario: secretaria });
    expect(await screen.findByRole("heading", { level: 1, name: "Painel da Rede" })).toBeInTheDocument();
    const descricao = screen.getByText(/Área administrativa da rede/);
    expect(descricao).toHaveTextContent(
      "Área administrativa da rede: metas, vitrine pública, boletim e mapa das escolas. Os resultados das escolas ficam em "
      + "Avaliações externas, em Elefante e Matific e em Escolas.");
    expect(descricao).not.toHaveTextContent(/Análise educacional/);
    expect(within(descricao).getByRole("link", { name: "Avaliações externas" })).toHaveAttribute("href", "/rede/avaliacoes-externas");
    expect(within(descricao).getByRole("link", { name: "Elefante e Matific" })).toHaveAttribute("href", "/rede/plataformas");
    expect(within(descricao).getByRole("link", { name: "Escolas" })).toHaveAttribute("href", "/rede/escolas");
    expect(screen.queryByRole("button", { name: /Análise educacional/ })).not.toBeInTheDocument();
    expect(screen.queryByText(/Análise educacional/)).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /Baixar boletim \(PDF\)/ }));
    expect(apiDownload).toHaveBeenCalledWith("/redes/7/boletim");
  });

  it("a rede com um módulo só: o link das plataformas tem o nome do que foi contratado", async () => {
    semear();
    responder("GET", "/redes/7/dashboard", { ...DASH_REDE, modulos: ["leitura"] });
    renderComApp(<RedeDashboard />, { rota: "/rede", usuario: secretaria });
    const descricao = await screen.findByText(/Área administrativa da rede/);
    expect(await within(descricao).findByRole("link", { name: "Elefante Letrado" })).toHaveAttribute("href", "/rede/plataformas");
    // O atalho de Escolas também só cita o que a rede contratou.
    const atalhos = screen.getByTestId("comparar-as-escolas");
    expect(atalhos).toHaveTextContent("Todas as escolas, o uso do Elefante Letrado lado a lado e a ficha de cada uma");
    expect(atalhos).not.toHaveTextContent("Matific");
  });

  it("a lista 'Ranking das escolas' virou os atalhos Escolas e Ranking da Rede", async () => {
    semear();
    renderComApp(<RedeDashboard />, { rota: "/rede", usuario: secretaria });
    expect(await screen.findByRole("heading", { name: "Comparar as escolas" })).toBeInTheDocument();
    expect(screen.queryByText("Ranking das escolas")).not.toBeInTheDocument();
    const atalhos = screen.getByTestId("comparar-as-escolas");
    expect(within(atalhos).getByRole("link", { name: /^Escolas/ })).toHaveAttribute("href", "/rede/escolas");
    expect(within(atalhos).getByRole("link", { name: /Ranking da Rede/ })).toHaveAttribute("href", "/rede/ranking");
    // A equidade não mora aqui: está no Ranking da Rede ("Diferença entre escolas").
    expect(screen.queryByText(/Equidade da rede/)).not.toBeInTheDocument();
  });

  it("admin global: os atalhos e a descrição levam a rede mostrada junto", async () => {
    responder("GET", "/redes", [{ id: 7, nome: "Rede Sintética" }]);
    semear();
    renderComApp(<RedeDashboard />, { rota: "/rede", usuario: admin });
    const descricao = await screen.findByText(/Área administrativa da rede/);
    expect(within(descricao).getByRole("link", { name: "Avaliações externas" }))
      .toHaveAttribute("href", "/rede/avaliacoes-externas?rede=7");
    expect(within(screen.getByTestId("comparar-as-escolas")).getByRole("link", { name: /Ranking da Rede/ }))
      .toHaveAttribute("href", "/rede/ranking?rede=7");
  });

  it("Vitrine pública, mapa e os alertas de uso continuam; a escola com alerta abre a Visão da Escola", async () => {
    semear();
    const u = userEvent.setup();
    renderComApp(<><Local /><RedeDashboard /></>, { rota: "/rede", usuario: secretaria });
    expect(await screen.findByRole("heading", { name: /Vitrine pública/ })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Distribuição geográfica" })).toBeInTheDocument();
    const alerta = screen.getByRole("heading", { name: /Escolas com alerta de uso das plataformas/ });
    const cartao = alerta.parentElement as HTMLElement;
    expect(cartao).toHaveTextContent("Baixa adoção: só 20% dos alunos têm dados (sintético).");
    expect(within(cartao).getByRole("link", { name: "Escolas em acompanhamento" })).toHaveAttribute("href", "/rede/acompanhamento");
    await u.click(within(cartao).getByRole("button", { name: "EMEF Sintética Atenção" }));
    expect(screen.getByTestId("local")).toHaveTextContent("/escola");
  });

  it("nenhuma palavra de causa e efeito no painel", async () => {
    semear();
    const { container } = renderComApp(<RedeDashboard />, { rota: "/rede", usuario: secretaria });
    await screen.findByTestId("resumo-metas");
    const texto = (container.textContent ?? "").toLowerCase();
    for (const palavra of [/\bcausa\b/, /por causa/, /\befeito\b/, /\bimpacto\b/, /\bgraças\b/]) {
      expect(texto).not.toMatch(palavra);
    }
  });
});

describe("Painel da Rede (Secretaria) — meta sem dado medido", () => {
  // O backend manda `atual` 0 quando ninguém foi aferido ou o número está protegido da
  // Secretaria (grupo pequeno) — e diz isso em `medida: false`.
  const META_SEM_DADO = {
    id: 3, metrica: "media_elefante", rotulo: "Leitura (Elefante Letrado)", sufixo: "", alvo: 70, atual: 0,
    progresso: 0, atingida: false, descricao: null, comparavel: false, escolas_atingiram: null, escolas_total: null,
    medida: false,
  };

  it("não mostra '0,0 / alvo', barra nem '0,0%': diz 'sem dado medido' e tira a meta da conta", async () => {
    semear([META_INTERNA, META_SEM_DADO]);
    renderComApp(<RedeDashboard />, { rota: "/rede", usuario: secretaria });
    expect(await screen.findByTestId("resumo-metas"))
      .toHaveTextContent("1 de 1 meta atingida · 1 sem dado — progresso calculado com o dado real.");
    const meta = screen.getByTestId("meta-sem-dado");
    expect(meta).toHaveTextContent("Leitura (Elefante Letrado)");
    expect(meta).toHaveTextContent("sem dado medido / 70,0");
    expect(meta).toHaveTextContent("Sem aluno aferido ou número protegido (grupo pequeno).");
    expect(meta).not.toHaveTextContent("0,0 /");
    expect(meta).not.toHaveTextContent("0,0%");
    // Nenhuma barra com largura (a trilha fica vazia, neutra).
    expect(meta.querySelector("[style*='width']")).toBeNull();
    // A meta medida continua como antes.
    const cartao = screen.getByRole("heading", { name: "Progresso das metas" }).parentElement as HTMLElement;
    expect(cartao).toHaveTextContent("40,0 / 30,0");
  });

  it("todas sem dado: o resumo diz isso (nada de '0 de 0 metas atingidas')", async () => {
    semear([META_SEM_DADO]);
    renderComApp(<RedeDashboard />, { rota: "/rede", usuario: secretaria });
    const resumo = await screen.findByTestId("resumo-metas");
    expect(resumo).toHaveTextContent("1 meta sem dado medido ainda.");
    expect(resumo).not.toHaveTextContent(/0 de 0/);
  });

  it("sem o campo `medida` (API anterior), a meta segue medida como antes", async () => {
    semear([META_COMPARAVEL]);
    renderComApp(<RedeDashboard />, { rota: "/rede", usuario: secretaria });
    expect(await screen.findByTestId("resumo-metas")).toHaveTextContent("0 de 1 meta atingida — progresso");
    expect(screen.queryByTestId("meta-sem-dado")).not.toBeInTheDocument();
    expect(screen.getByText("40,0%")).toBeInTheDocument();
  });
});

describe("Painel da Rede (Secretaria) — o período real, os alertas vazios e a legenda do mapa", () => {
  it("o atalho do Ranking e a regra dos alertas dizem o período de cada plataforma (não 'no ano letivo')", async () => {
    semear();
    renderComApp(<RedeDashboard />, { rota: "/rede", usuario: secretaria });
    const ranking = within(await screen.findByTestId("comparar-as-escolas")).getByRole("link", { name: /Ranking da Rede/ });
    expect(ranking).toHaveTextContent(
      "A pontuação do Constela, calculada a partir das plataformas (Elefante: livros acumulados desde o início da "
      + "conta de cada aluno; Matific: no ano letivo), com a diferença entre as escolas.");
    const regra = screen.getByTestId("regra-alerta-uso");
    expect(regra).toHaveTextContent(
      "Regra do painel, com os dados das plataformas (Elefante: livros acumulados desde o início da conta de cada "
      + "aluno; Matific: no ano letivo): escola sem alunos, sem dado, com adoção abaixo de 40% ou com índice abaixo "
      + "de 300 (de 0 a 1000; 1000 = melhor escola da rede). Não é avaliação oficial.");
    expect(regra).not.toHaveTextContent("dados das plataformas no ano letivo");
  });

  it("rede só com o Matific: o período cita só o Matific", async () => {
    semear();
    responder("GET", "/redes/7/dashboard", { ...DASH_REDE, modulos: ["matematica"] });
    renderComApp(<RedeDashboard />, { rota: "/rede", usuario: secretaria });
    const atalhos = await screen.findByTestId("comparar-as-escolas");
    expect(atalhos).toHaveTextContent("calculada a partir das plataformas (Matific: no ano letivo)");
    expect(atalhos).not.toHaveTextContent("Elefante");
    const regra = screen.getByTestId("regra-alerta-uso");
    expect(regra).toHaveTextContent("com os dados das plataformas (Matific: no ano letivo):");
    expect(regra).not.toHaveTextContent("Elefante");
  });

  it("sem escola com alerta: texto neutro preso à regra do cartão — sem 'acompanhamento' nem tom de 'tudo certo'", async () => {
    semear();
    responder("GET", "/redes/7/dashboard", { ...DASH_REDE, atencao: [] });
    renderComApp(<RedeDashboard />, { rota: "/rede", usuario: secretaria });
    const vazio = await screen.findByTestId("alerta-vazio");
    expect(vazio).toHaveTextContent("Nenhuma escola com alerta pela regra deste cartão agora.");
    expect(vazio).not.toHaveTextContent(/acompanhamento/i);
    expect(vazio.className).not.toMatch(/emerald/);
    expect(vazio.querySelector("svg")).toBeNull();
    expect(screen.queryByText(/sinalizada para acompanhamento/)).not.toBeInTheDocument();
  });

  it("o mapa tem legenda: a natureza, o que a cor mede (com o período) e as faixas com a bolinha da cor", async () => {
    semear();
    const comCoordenada = { ...EM_ATENCAO, latitude: -23.6, longitude: -45.4 };
    responder("GET", "/redes/7/dashboard", { ...DASH_REDE, escolas: [comCoordenada], atencao: [comCoordenada] });
    renderComApp(<RedeDashboard />, { rota: "/rede", usuario: secretaria });
    const legenda = await screen.findByTestId("legenda-mapa");
    // A legenda fica no cartão do mapa.
    const cartaoMapa = screen.getByRole("heading", { name: "Distribuição geográfica" }).parentElement as HTMLElement;
    expect(cartaoMapa).toContainElement(legenda);
    expect(within(legenda).getByText("Calculado pelo Constela")).toBeInTheDocument();
    expect(legenda).toHaveTextContent(
      "Cor do marcador = índice do Constela da escola (0 a 1000; 1000 = melhor escola da rede), pelos dados das "
      + "plataformas (Elefante: livros acumulados desde o início da conta de cada aluno; Matific: no ano letivo).");
    const faixas = within(legenda).getAllByRole("listitem");
    expect(faixas.map((f) => f.textContent)).toEqual([
      "verde: 660 ou mais", "âmbar: de 300 a 659", "vermelho: abaixo de 300",
      "cinza: fora da comparação (sem aluno do 1º ao 5º ano com dado)",
    ]);
    // Cada faixa com a bolinha da cor do marcador.
    const cores = faixas.map((f) => (f.querySelector("span[aria-hidden]") as HTMLElement).style.background);
    expect(cores).toEqual(["rgb(5, 150, 105)", "rgb(217, 119, 6)", "rgb(220, 38, 38)", "rgb(138, 142, 169)"]);
  });

  it("sem escola com localização, sem legenda (o mapa mostra o vazio)", async () => {
    semear();
    renderComApp(<RedeDashboard />, { rota: "/rede", usuario: secretaria });
    expect(await screen.findByText("Nenhuma escola tem localização cadastrada ainda.")).toBeInTheDocument();
    expect(screen.queryByTestId("legenda-mapa")).not.toBeInTheDocument();
  });

  it("a cor do índice corta no MESMO 300 do alerta (INDICE_BAIXO); verde a partir de 660", () => {
    expect(corPorIndice(1000)).toBe("#059669");
    expect(corPorIndice(660)).toBe("#059669");
    expect(corPorIndice(659.9)).toBe("#D97706");
    expect(corPorIndice(315)).toBe("#D97706"); // com o corte antigo (330) saía vermelha, fora dos alertas
    expect(corPorIndice(300)).toBe("#D97706");
    expect(corPorIndice(299.9)).toBe("#DC2626");
    expect(corPorIndice(0)).toBe("#DC2626");
  });
});
