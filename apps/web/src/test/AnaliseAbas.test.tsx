/**
 * Análises avançadas (`/rede/analise`) — a área técnica da rede:
 *  - a faixa "Área técnica" e as 3 abas (os nomes dos itens do menu), com o Diagnóstico
 *    exploratório como padrão (`?ver=diagnostico` dos links de antes abre a mesma aba);
 *  - a troca pela URL e as leituras PREGUIÇOSAS (cada aba só pede à API o que mostra);
 *  - os LINKS ANTIGOS das abas que viraram páginas próprias redirecionam com `replace`,
 *    levando o `rede=` e, nos de indicador, os mesmos parâmetros (o voltar do navegador não
 *    cai de novo no redirecionamento);
 *  - os itens do menu continuam abas desta página (o filtro Escola anda com o menu lateral).
 *
 * Números, nomes e arquivos INVENTADOS (D13).
 */
import { Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { useApp } from "../context/AppContext";
import AnaliseEducacional, { destinoDoLinkAntigo } from "../pages/analise/AnaliseEducacional";
import type { RespostaAnaliseEscola, RespostaRelacao } from "../pages/analise/tipos";
import {
  admin, baseRede, diagnostico, evolucao, familia, plataformasRede, secretaria,
} from "./AnaliseFixturesDiagnostico";
import { api, renderComApp, responder, screen, userEvent, waitFor, within } from "./utils";

const ABAS = ["Diagnóstico exploratório", "Relação com as plataformas", "Análise detalhada por escola"];

const RELACAO: RespostaRelacao = {
  calculavel: false, motivos: ["periodo_sem_sobreposicao"],
  textos: ["Período sem sobreposição: a avaliação é de 2025 e as plataformas são de 2026 (sintético)."],
  criterios: { metodo: "Spearman", n_minimo: 8, k_minimo_alunos: 5, exige_mesmo_ano_letivo: true,
               exige_mesma_serie: true, so_oficial: true, mesma_escala: true },
  indicador: null, metrica: null, pares: [], n: 0, coeficiente: null, ic95: null,
  metodologia: "Unidade: a escola (texto sintético).",
};

const ESCOLA_3: RespostaAnaliseEscola = {
  escola: { id: 3, nome: "EMEF Sintética Beta", codigo_inep: "35990003", pendencia: null },
  rede: { id: 1, nome: "Rede Sintética Norte" }, indicadores: [], plataformas: null,
  comparacoes_indisponiveis: [], fontes: {},
};

function semearTudo() {
  responder("GET", "/redes/1/analise/indicadores", baseRede());
  responder("GET", "/redes/1/analise/plataformas", plataformasRede());
  responder("GET", "/redes/1/analise/plataformas/evolucao", evolucao());
  responder("GET", "/redes/1/analise/diagnostico", diagnostico());
  responder("GET", "/redes/1/analise/relacao", RELACAO);
  responder("GET", "/escolas/3/analise", ESCOLA_3);
}

/** As famílias de leitura pedidas até agora (sem as da sessão: /auth/me, /escolas). */
const familias = () => new Set(api.mock.calls.map(([c]) => familia(String(c))).filter(Boolean));

function Local() {
  const { pathname, search } = useLocation();
  return <p data-testid="local">{pathname}{search}</p>;
}
const busca = () => new URLSearchParams((screen.getByTestId("local").textContent ?? "").split("?")[1] ?? "");

describe("Análises avançadas — a área técnica e as abas", () => {
  it("o título, a faixa da área técnica e as 3 abas, com o Diagnóstico exploratório como padrão", async () => {
    semearTudo();
    renderComApp(<AnaliseEducacional />, { rota: "/rede/analise", usuario: secretaria });
    expect(await screen.findByRole("heading", { level: 1, name: "Análises avançadas" })).toBeInTheDocument();
    const faixa = screen.getByTestId("faixa-area-tecnica");
    expect(faixa).toHaveTextContent(
      "Área técnica: análises exploratórias e estatísticas para quem quer aprofundar. Não são conclusões sobre as escolas.");
    // Quem caiu aqui por engano volta às telas do dia a dia (a Secretaria: o Panorama em "/").
    expect(within(faixa).getByRole("link", { name: "Panorama da Rede" })).toHaveAttribute("href", "/");
    expect(within(faixa).getByRole("link", { name: "Avaliações externas" })).toHaveAttribute("href", "/rede/avaliacoes-externas");
    expect(within(faixa).getByRole("link", { name: "Escolas" })).toHaveAttribute("href", "/rede/escolas");

    const lista = screen.getByRole("tablist", { name: "Partes da análise" });
    expect(within(lista).getAllByRole("tab").map((t) => t.textContent)).toEqual(ABAS);
    expect(screen.getByRole("tab", { name: "Diagnóstico exploratório" })).toHaveAttribute("aria-selected", "true");
    // O painel é rotulado pela aba ativa e o diagnóstico (com o CSV) está nele.
    expect(screen.getByRole("tabpanel"))
      .toHaveAttribute("aria-labelledby", screen.getByRole("tab", { name: "Diagnóstico exploratório" }).id);
    expect(await screen.findByTestId("tabela-diagnostico")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Exportar diagnóstico \(CSV\)/ })).toBeInTheDocument();
    // Os filtros moram só aqui.
    expect(screen.getByTestId("filtros-compartilhados")).toBeInTheDocument();
  });

  it("admin global: a faixa leva à Visão da rede e às telas da rede ABERTA (rede=)", async () => {
    responder("GET", "/redes", [{ id: 1, nome: "Rede Sintética Norte" }]);
    semearTudo();
    renderComApp(<AnaliseEducacional />, { rota: "/rede/analise", usuario: admin });
    const faixa = await screen.findByTestId("faixa-area-tecnica");
    expect(within(faixa).getByRole("link", { name: "Visão da rede" })).toHaveAttribute("href", "/rede/visao?rede=1");
    expect(within(faixa).getByRole("link", { name: "Avaliações externas" }))
      .toHaveAttribute("href", "/rede/avaliacoes-externas?rede=1");
  });

  it("trocar de aba põe o ?ver= na URL (o Diagnóstico fica sem ?ver=)", async () => {
    semearTudo();
    renderComApp(<><Local /><AnaliseEducacional /></>, { rota: "/rede/analise", usuario: secretaria });
    await screen.findByTestId("tabela-diagnostico");
    for (const [i, chave] of ["relacao", "escola"].entries()) {
      await userEvent.click(screen.getByRole("tab", { name: ABAS[i + 1] }));
      expect(busca().get("ver")).toBe(chave);
      expect(screen.getByRole("tab", { name: ABAS[i + 1] })).toHaveAttribute("aria-selected", "true");
    }
    await userEvent.click(screen.getByRole("tab", { name: "Diagnóstico exploratório" }));
    expect(busca().has("ver")).toBe(false);
  });

  it("o ?ver=diagnostico dos links de antes abre o Diagnóstico exploratório (sem redirecionar)", async () => {
    semearTudo();
    renderComApp(<><Local /><AnaliseEducacional /></>, { rota: "/rede/analise?ver=diagnostico", usuario: secretaria });
    expect(await screen.findByTestId("tabela-diagnostico")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Diagnóstico exploratório" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByTestId("local")).toHaveTextContent("/rede/analise?ver=diagnostico");
  });

  // [aba, rota, o que esperar na tela, as leituras que a aba faz]
  const casos: [string, string, string, string[]][] = [
    ["Diagnóstico exploratório", "/rede/analise", "tabela-diagnostico", ["indicadores", "diagnostico"]],
    ["Relação com as plataformas", "/rede/analise?ver=relacao", "relacao-nao-calculavel", ["indicadores", "relacao"]],
    ["Análise detalhada por escola", "/rede/analise?ver=escola&escola=3", "por-escola-nome", ["indicadores", "escola"]],
  ];

  it.each(casos)("%s só lê o que mostra (leitura preguiçosa)", async (_nome, rota, testId, esperadas) => {
    semearTudo();
    renderComApp(<AnaliseEducacional />, { rota, usuario: secretaria });
    await screen.findByTestId(testId);
    await waitFor(() => expect([...familias()].sort()).toEqual([...esperadas].sort()));
    // E nada mais chega depois (sem leitura "de brinde" de outra aba).
    await new Promise((r) => setTimeout(r, 30));
    expect([...familias()].sort()).toEqual([...esperadas].sort());
  });
});

// =============================================================================
// Links antigos → as páginas próprias (Navigate replace)
// =============================================================================

/** As rotas de destino (só para mostrar onde a navegação parou) e o "voltar". */
function Destinos() {
  const navegar = useNavigate();
  return (
    <>
      <Local />
      <button type="button" onClick={() => navegar(-1)}>voltar</button>
      <Routes>
        <Route path="/" element={<p>TELA:panorama</p>} />
        <Route path="/antes" element={<p>TELA:antes</p>} />
        <Route path="/rede/visao" element={<p>TELA:visao-da-rede</p>} />
        <Route path="/rede/avaliacoes-externas" element={<p>TELA:avaliacoes-externas</p>} />
        <Route path="/rede/plataformas" element={<p>TELA:plataformas</p>} />
        <Route path="/rede/relatorios" element={<p>TELA:relatorios</p>} />
        <Route path="/rede/analise" element={<AnaliseEducacional />} />
      </Routes>
    </>
  );
}

describe("Análises avançadas — os links antigos redirecionam", () => {
  it.each([
    ["visao (Secretaria → o Panorama em /)", "/rede/analise?ver=visao", "TELA:panorama", "/"],
    ["avaliacoes", "/rede/analise?ver=avaliacoes", "TELA:avaliacoes-externas", "/rede/avaliacoes-externas"],
    // A escola e a série (o recorte da evolução na página nova) vão junto; o resto, não.
    ["plataformas", "/rede/analise?ver=plataformas&escola=3&serie=5&indicador=ica", "TELA:plataformas",
     "/rede/plataformas?escola=3&serie=5"],
    ["relatorios", "/rede/analise?ver=relatorios", "TELA:relatorios", "/rede/relatorios"],
    // A série vale para a planilha das plataformas dos Relatórios; o indicador, não.
    ["relatorios com série", "/rede/analise?ver=relatorios&serie=4&indicador=ica", "TELA:relatorios",
     "/rede/relatorios?serie=4"],
  ])("?ver=%s", async (_nome, rota, tela, destino) => {
    semearTudo();
    renderComApp(<Destinos />, { rota, usuario: secretaria });
    expect(await screen.findByText(tela)).toBeInTheDocument();
    expect(screen.getByTestId("local").textContent).toBe(destino);
    // Nada da área técnica foi lido no caminho.
    expect(familias().size).toBe(0);
  });

  it("?ver=indicador leva a Avaliações externas com os MESMOS parâmetros do indicador", async () => {
    semearTudo();
    renderComApp(<Destinos />, {
      rota: "/rede/analise?ver=indicador&indicador=saresp&etapa=5_ano&componente=lp&visao=escolas&edicao=2025&de=2022&ate=2025&abrangencia=escola&escola=3&serie=2&metrica=livros_por_aluno",
      usuario: secretaria,
    });
    expect(await screen.findByText("TELA:avaliacoes-externas")).toBeInTheDocument();
    expect(screen.getByTestId("local").textContent?.split("?")[0]).toBe("/rede/avaliacoes-externas");
    expect(Object.fromEntries(busca())).toEqual({
      indicador: "saresp", etapa: "5_ano", componente: "lp", visao: "escolas", edicao: "2025", de: "2022",
      ate: "2025", abrangencia: "escola", escola: "3",
    });
  });

  it("admin global: ?ver=visao vai para a Visão da rede e o rede= vai junto", async () => {
    semearTudo();
    renderComApp(<Destinos />, { rota: "/rede/analise?ver=visao&rede=7", usuario: admin });
    expect(await screen.findByText("TELA:visao-da-rede")).toBeInTheDocument();
    expect(screen.getByTestId("local").textContent).toBe("/rede/visao?rede=7");
  });

  it.each([
    ["avaliacoes", "/rede/avaliacoes-externas?indicador=ica&rede=7"],
    ["plataformas", "/rede/plataformas?serie=2&rede=7"],
    ["relatorios", "/rede/relatorios?rede=7"],
  ])("admin global: ?ver=%s leva o rede=", (ver, destino) => {
    const params = new URLSearchParams(
      `ver=${ver}&rede=7${ver === "avaliacoes" ? "&indicador=ica" : ""}${ver === "plataformas" ? "&serie=2" : ""}`);
    expect(destinoDoLinkAntigo(params, true)).toBe(destino);
  });

  it("as abas que ficaram aqui não redirecionam", () => {
    for (const ver of [null, "diagnostico", "relacao", "escola", "qualquer"]) {
      const params = new URLSearchParams(ver ? `ver=${ver}&rede=7` : "rede=7");
      expect(destinoDoLinkAntigo(params, false)).toBeNull();
      expect(destinoDoLinkAntigo(params, true)).toBeNull();
    }
  });

  it("o redirecionamento SUBSTITUI a entrada: o voltar não cai de novo nele", async () => {
    semearTudo();
    function Ir() {
      const navegar = useNavigate();
      return <button type="button" onClick={() => navegar("/rede/analise?ver=plataformas")}>ir</button>;
    }
    renderComApp(<><Ir /><Destinos /></>, { rota: "/antes", usuario: secretaria });
    await userEvent.click(await screen.findByRole("button", { name: "ir" }));
    expect(await screen.findByText("TELA:plataformas")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "voltar" }));
    // Sem o replace, o voltar abriria /rede/analise?ver=plataformas e redirecionaria de novo.
    expect(await screen.findByText("TELA:antes")).toBeInTheDocument();
    expect(screen.getByTestId("local").textContent).toBe("/antes");
  });
});

// =============================================================================
// Os itens do menu são abas desta página (o filtro Escola anda com o menu lateral)
// =============================================================================

/** Um item do menu lateral: o link é só `/rede/analise?ver=X` (sem `?escola=`), e a página
 *  continua montada; o topo mostra a escola do seletor de contexto. */
function MenuETopo() {
  const navegar = useNavigate();
  const { escolaId } = useApp();
  return (
    <div>
      <p data-testid="contexto-topo">{escolaId == null ? "toda a rede" : `escola ${escolaId}`}</p>
      <button type="button" onClick={() => navegar("/rede/analise?ver=relacao")}>menu: Relação com as plataformas</button>
    </div>
  );
}

describe("Análises avançadas — os itens do menu são abas desta página", () => {
  it("Secretaria: o link do menu (sem ?escola=) não solta o filtro da escola do topo", async () => {
    semearTudo();
    renderComApp(<><Local /><MenuETopo /><AnaliseEducacional /></>,
                 { rota: "/rede/analise?escola=3", usuario: secretaria });
    await waitFor(() => expect(screen.getByTestId("contexto-topo")).toHaveTextContent("escola 3"));
    await userEvent.click(screen.getByRole("button", { name: "menu: Relação com as plataformas" }));
    expect(screen.getByRole("tab", { name: "Relação com as plataformas" })).toHaveAttribute("aria-selected", "true");
    await waitFor(() => expect(busca().get("escola")).toBe("3"));
    expect(screen.getByLabelText("Escola")).toHaveValue("3");
    expect(screen.getByTestId("contexto-topo")).toHaveTextContent("escola 3");
    // Escolher "Toda a rede" aqui continua valendo (o topo vai junto e nada volta sozinho).
    await userEvent.selectOptions(screen.getByLabelText("Escola"), "");
    expect(screen.getByTestId("contexto-topo")).toHaveTextContent("toda a rede");
    await new Promise((r) => setTimeout(r, 30));
    expect(busca().has("escola")).toBe(false);
    expect(screen.getByLabelText("Escola")).toHaveValue("");
  });

  it("admin global: 'Toda a rede' com uma escola no topo é escolha dele — o link do menu não a troca", async () => {
    responder("GET", "/redes", [{ id: 1, nome: "Rede Sintética Norte" }]);
    semearTudo();
    renderComApp(<><Local /><MenuETopo /><AnaliseEducacional /></>,
                 { rota: "/rede/analise?escola=3", usuario: admin });
    await waitFor(() => expect(screen.getByTestId("contexto-topo")).toHaveTextContent("escola 3"));
    await userEvent.click(screen.getByRole("button", { name: "menu: Relação com as plataformas" }));
    await new Promise((r) => setTimeout(r, 30));
    expect(busca().has("escola")).toBe(false);
    expect(screen.getByLabelText("Escola")).toHaveValue("");
  });
});
