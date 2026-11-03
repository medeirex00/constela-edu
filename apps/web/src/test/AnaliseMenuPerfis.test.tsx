/**
 * Análises avançadas (antes "Análise educacional") por PERFIL — menu, rota e a área de
 * rastreabilidade:
 *
 *  - menu: a Secretaria NÃO tem mais as Análises avançadas no menu (DESENHO3 §1: só as três
 *    áreas — Panorama da Rede, Escolas e Avaliações externas); a rota continua abrindo para
 *    ela (link antigo, endereço digitado), sem item aceso, e os arquivos oficiais
 *    (/rede/avaliacoes) ficam "dentro" das Avaliações externas. O admin global tem, em
 *    "Redes e municípios", "Análises avançadas" e "Importações e fontes"; o coordenador e o
 *    professor não têm a análise da rede (lêem a da escola na Visão da Escola). A árvore
 *    inteira de cada perfil fica travada em NavegacaoPerfis.test.tsx;
 *  - rota /rede/analise: a Secretaria abre; o professor é mandado ao Dashboard (e a API da
 *    análise nem é chamada);
 *  - /rede/avaliacoes: a correlação (dispersão, evolução, Pearson) SAIU — fica um cartão
 *    que volta às Avaliações externas e, só para o admin global, leva à relação (Análises
 *    avançadas; a Secretaria não as tem no menu, então o cartão dela não aponta para lá); o
 *    resto (cartões, importação do global) continua.
 *
 * Números e nomes INVENTADOS (D13).
 */
import { describe, expect, it } from "vitest";

import App from "../App";
import Layout from "../components/Layout";
import { ImportacaoLoteProvider } from "../context/ImportacaoLoteContext";
import RedeAvaliacoes from "../pages/rede/RedeAvaliacoes";
import { diagnostico } from "./AnaliseFixturesDiagnostico";
import {
  api, escolaFake, renderComApp, responder, screen, usuarioFake, waitFor, within,
} from "./utils";

const secretaria = usuarioFake({ nome: "Secretaria", cargo: "coordenador", rede_id: 1, escola_id: null });
const coordenador = usuarioFake({ nome: "Coordenadora", cargo: "coordenador", escola_id: 1 });
const professor = usuarioFake({ nome: "Professora", cargo: "professor", escola_id: 1 });
const admin = usuarioFake({ nome: "Root", cargo: "admin", is_global: true, escola_id: null });

function LayoutReal() {
  return (
    <ImportacaoLoteProvider>
      <Layout />
    </ImportacaoLoteProvider>
  );
}

function escolaConfigurada() {
  responder("GET", "/escolas/1/sync/onboarding", { lista_piloto_importada: true });
}

const hrefs = () => screen.queryAllByRole("link").map((l) => l.getAttribute("href"));

/** Os links do painel que o botão do acordeão controla. */
function painelDoGrupo(nome: string): HTMLElement {
  const botao = screen.getByRole("button", { name: nome });
  return document.getElementById(botao.getAttribute("aria-controls") ?? "") as HTMLElement;
}

describe("Menu — análises avançadas por perfil", () => {
  it("a Secretaria: nada das Análises avançadas nem das fontes no menu — as Avaliações externas são a área dela", async () => {
    escolaConfigurada();
    renderComApp(<LayoutReal />, { rota: "/", usuario: secretaria, escolas: [escolaFake({ id: 1 })] });
    const rede = await screen.findByRole("group", { name: "Rede municipal" });
    await within(rede).findByRole("link", { name: "Avaliações externas" });
    expect(hrefs().filter((h) => h?.startsWith("/rede/analise"))).toEqual([]);
    expect(hrefs()).not.toContain("/rede/avaliacoes");
    expect(screen.queryAllByRole("button", { name: "Análises avançadas" })).toHaveLength(0);
    expect(screen.queryAllByRole("link", { name: "Análises avançadas" })).toHaveLength(0);
    expect(screen.queryAllByRole("link", { name: "Fontes e arquivos oficiais" })).toHaveLength(0);
    expect(screen.queryAllByRole("link", { name: "Fontes dos indicadores" })).toHaveLength(0);
    expect(screen.queryAllByRole("link", { name: "Painel da Rede" })).toHaveLength(0);
    expect(screen.queryByRole("group", { name: "Aprofundar" })).toBeNull();
    // "Avaliações externas" é uma das três áreas — e só ela tem esse nome.
    expect(screen.queryAllByRole("link", { name: /^Avaliações externas$/i }).map((l) => l.getAttribute("href")))
      .toEqual(["/rede/avaliacoes-externas"]);
  });

  it("o admin global: Visão da rede, Análises avançadas e Importações e fontes (grupo Redes e municípios)", async () => {
    escolaConfigurada();
    renderComApp(<LayoutReal />, { rota: "/", usuario: admin, escolas: [escolaFake({ id: 1 })] });
    const analise = await screen.findAllByRole("link", { name: "Análises avançadas" });
    expect(analise[0]).toHaveAttribute("href", "/rede/analise");
    const painel = painelDoGrupo("Redes e municípios");
    expect(within(painel).getByRole("link", { name: "Visão da rede" })).toHaveAttribute("href", "/rede/visao");
    expect(within(painel).getByRole("link", { name: "Análises avançadas" })).toHaveAttribute("href", "/rede/analise");
    expect(within(painel).getByRole("link", { name: "Importações e fontes" })).toHaveAttribute("href", "/rede/avaliacoes");
    expect(screen.queryAllByRole("link", { name: "Análise educacional" })).toHaveLength(0);
  });

  it.each([["coordenador", coordenador], ["professor", professor]])(
    "o %s não tem /rede/analise nem /rede/avaliacoes no menu", async (_nome, usuario) => {
      escolaConfigurada();
      renderComApp(<LayoutReal />, { rota: "/", usuario, escolas: [escolaFake({ id: 1 })] });
      // A sessão abriu (nome no cartão do usuário) e o menu do perfil está montado: a
      // página inicial agora se chama "Visão geral" (D4, era "Dashboard"/"Meu Dashboard").
      await screen.findAllByText(usuario.nome);
      await screen.findAllByRole("link", { name: "Visão geral" });
      expect(hrefs()).not.toContain("/rede/analise");
      expect(hrefs()).not.toContain("/rede/avaliacoes");
      // Nem as abas da análise (/rede/analise?ver=…) nem as telas da Secretaria.
      expect(hrefs().filter((h) => h?.startsWith("/rede/"))).toEqual([]);
      expect(screen.queryAllByRole("link", { name: "Análises avançadas" })).toHaveLength(0);
      expect(screen.queryAllByRole("button", { name: "Análises avançadas" })).toHaveLength(0);
    });

  it("a Secretaria em /rede/analise (fora do menu dela): a trilha é só o início e o nome da tela, sem item aceso", async () => {
    escolaConfigurada();
    renderComApp(<LayoutReal />, { rota: "/rede/analise?ver=relacao", usuario: secretaria, escolas: [escolaFake({ id: 1 })] });
    await screen.findAllByText(secretaria.nome);
    const trilha = screen.getByRole("navigation", { name: "Trilha de navegação" });
    expect(Array.from(trilha.querySelectorAll("a, span")).map((el) => el.textContent))
      .toEqual(["Panorama da Rede", "Análises avançadas"]);
    // Cortado numa tela estreita, o título inteiro continua no title.
    expect(within(trilha).getByText("Análises avançadas")).toHaveAttribute("title", "Análises avançadas");
    const menu = screen.getByRole("navigation", { name: "Menu principal" });
    expect(menu.querySelectorAll("a[aria-current]")).toHaveLength(0);
    expect(screen.queryAllByRole("button", { name: "Análises avançadas" })).toHaveLength(0);
  });

  it("a Secretaria nos arquivos oficiais (/rede/avaliacoes): a área Avaliações externas fica acesa", async () => {
    escolaConfigurada();
    renderComApp(<LayoutReal />, { rota: "/rede/avaliacoes", usuario: secretaria, escolas: [escolaFake({ id: 1 })] });
    await screen.findAllByText(secretaria.nome);
    const trilha = screen.getByRole("navigation", { name: "Trilha de navegação" });
    expect(Array.from(trilha.querySelectorAll("a, span")).map((el) => el.textContent))
      .toEqual(["Panorama da Rede", "Rede municipal", "Fontes dos indicadores"]);
    const menu = screen.getByRole("navigation", { name: "Menu principal" });
    expect(Array.from(menu.querySelectorAll("a[aria-current]")).map((a) => a.getAttribute("href")))
      .toEqual(["/rede/avaliacoes-externas"]);
  });

  it("para o admin global a mesma rota é 'Redes e municípios › Análises avançadas'", async () => {
    escolaConfigurada();
    renderComApp(<LayoutReal />, { rota: "/rede/analise?ver=relacao", usuario: admin, escolas: [escolaFake({ id: 1 })] });
    await screen.findAllByText(admin.nome);
    const trilha = screen.getByRole("navigation", { name: "Trilha de navegação" });
    expect(within(trilha).getByText("Redes e municípios")).toHaveAttribute("title", "Redes e municípios");
    expect(within(trilha).getByText("Análises avançadas")).toHaveAttribute("title", "Análises avançadas");
  });
});

// =============================================================================
// Rota /rede/analise (RotaRede)
// =============================================================================

const BASE_VAZIA = {
  rede: { id: 1, nome: "Rede Sintética Norte", codigo_ibge: null }, indicadores: [], destaques: [],
  estimativas: [], escolas: [], alertas: [],
};

describe("Rota /rede/analise", () => {
  it("a Secretaria abre as Análises avançadas da rede", async () => {
    responder("GET", "/redes/1/analise/indicadores", BASE_VAZIA);
    responder("GET", "/redes/1/analise/plataformas", {
      janela: { inicio: "2026-01-01", fim: "2026-12-31", rotulo: "Ano letivo de 2026" },
      modulos: { elefante: true, matific: true }, k_minimo: 5,
      rede: { alunos: null, elefante: null, matific: null }, escolas: [],
      cobertura: { ultima_coleta: { elefante: null, matific: null }, escolas_sem_coleta: [],
                   primeiro_evento_elefante: null, dias_desde_ultima_coleta: null },
      limitacoes: [],
    });
    // A aba padrão agora é o Diagnóstico exploratório (DESENHO2 §2.4).
    responder("GET", /\/redes\/1\/analise\/diagnostico/, diagnostico());
    renderComApp(<App />, { rota: "/rede/analise", usuario: secretaria, escolas: [escolaFake({ id: 1 })] });
    expect(await screen.findByRole("heading", { name: "Análises avançadas" }, { timeout: 4000 })).toBeInTheDocument();
    // A página diz o que ela é (área técnica, não conclusão) e abre na aba padrão, que lê o
    // diagnóstico da rede DELA — não uma tela vazia nem a rede de outra pessoa.
    const faixa = await screen.findByTestId("faixa-area-tecnica");
    expect(faixa).toHaveTextContent(/Área técnica/);
    expect(faixa).toHaveTextContent(/Não são conclusões/);
    await waitFor(() => expect(api.mock.calls.some(([c]) => String(c).startsWith("/redes/1/analise/diagnostico"))).toBe(true));
    expect(api.mock.calls.some(([c]) => /\/redes\/(?!1\/)\d+\//.test(String(c)))).toBe(false);
  });

  it.each([["professor", professor], ["coordenador", coordenador]])(
    "o %s é mandado ao Dashboard e a API da análise nem é chamada", async (_nome, usuario) => {
      escolaConfigurada();
      renderComApp(<App />, { rota: "/rede/analise", usuario, escolas: [escolaFake({ id: 1 })] });
      await waitFor(() => expect(api.mock.calls.some(([c]) => String(c).startsWith("/escolas/1/dashboard"))).toBe(true),
                    { timeout: 4000 });
      expect(api.mock.calls.some(([c]) => String(c).includes("/analise"))).toBe(false);
      expect(screen.queryByRole("heading", { name: /Análises avançadas|Análise educacional/ })).not.toBeInTheDocument();
    });
});

// =============================================================================
// /rede/avaliacoes — sem correlação
// =============================================================================

function semearRede(opcoes: unknown[] = []) {
  responder("GET", "/redes", [{ id: 1, nome: "Rede Sintética" }]);
  responder("GET", "/redes/1/avaliacoes/opcoes", opcoes);
  responder("GET", "/avaliacoes", [{ chave: "ideb", nome: "IDEB", tipo: "indicador", orgao: "INEP", descricao: null }]);
  responder("GET", "/avaliacoes/presets-import", []);
  responder("GET", "/avaliacoes/fontes", []);
}

const OPCAO = { avaliacao: "ideb", nome: "IDEB", tipo: "indicador", indicador: "ideb",
                etapa: "anos_iniciais", componente: null, edicoes: [2023] };

describe("Fontes dos indicadores — a correlação saiu", () => {
  it("a Secretaria não vê dispersão, evolução nem Pearson; o cartão volta às Avaliações externas (sem Análises avançadas)", async () => {
    semearRede([OPCAO]);
    const { container } = renderComApp(<RedeAvaliacoes />, { usuario: secretaria });
    expect(await screen.findByRole("heading", { name: "Fontes dos indicadores" })).toBeInTheDocument();
    // Esta tela é o detalhe técnico: o cartão do topo leva de volta ao resumo em linguagem
    // simples (Avaliações externas). As Análises avançadas saíram do menu dela (DESENHO3 §1,
    // §5): nenhum link nem menção a elas no cartão.
    expect(await screen.findByRole("link", { name: /Voltar para Avaliações externas/ }))
      .toHaveAttribute("href", "/rede/avaliacoes-externas");
    expect(screen.queryByRole("link", { name: "Análises avançadas" })).not.toBeInTheDocument();
    expect(screen.getByTestId("cartao-avaliacoes-externas")).not.toHaveTextContent(/Análises avançadas/);
    expect(Array.from(container.querySelectorAll("a")).map((a) => a.getAttribute("href") ?? "")
      .filter((h) => h.startsWith("/rede/analise"))).toEqual([]);
    await waitFor(() => expect(api.mock.calls.some(([c]) => String(c) === "/redes/1/avaliacoes/opcoes")).toBe(true));
    expect(screen.queryByText(/Dispersão por escola/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Evolução da rede/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Pearson/)).not.toBeInTheDocument();
    expect(screen.queryByRole("img", { name: /Dispersão/ })).not.toBeInTheDocument();
    expect(api.mock.calls.some(([c]) => String(c).includes("/avaliacoes/correlacao"))).toBe(false);
  });

  it("o admin global continua com a importação e o 'Remover edição' (sem a correlação)", async () => {
    semearRede([OPCAO]);
    renderComApp(<RedeAvaliacoes />, { usuario: admin });
    expect(await screen.findByRole("heading", { name: "Importações e fontes" })).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: /Remover edição 2023/ })).toBeInTheDocument();
    // O cartão do topo leva a rede mostrada junto (o global escolhe a rede).
    expect(screen.getByTestId("cartao-avaliacoes-externas")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Voltar para Avaliações externas/ }))
      .toHaveAttribute("href", "/rede/avaliacoes-externas?rede=1");
    expect(screen.getByRole("link", { name: "Análises avançadas" })).toHaveAttribute("href", "/rede/analise?ver=relacao&rede=1");
    expect(screen.queryByText(/Dispersão por escola/)).not.toBeInTheDocument();
    expect(api.mock.calls.some(([c]) => String(c).includes("/avaliacoes/correlacao"))).toBe(false);
  });
});
