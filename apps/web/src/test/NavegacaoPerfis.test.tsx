/**
 * TRAVA da navegação lateral por perfil (desenho feat/navegacao-inteligencia, seção A,
 * rodada 2 — DESENHO2 §2.1 e §3 — e rodada 3 — DESENHO3 §1: a Secretaria em TRÊS áreas).
 *
 * Para cada perfil — Admin Global, Secretaria (com cargo coordenador, o caso real),
 * coordenação, administração da escola e professora — confere:
 *  - a ÁRVORE exata do menu: seções na ordem, grupos (acordeões), itens soltos, rótulos e
 *    endereços. Mudar a arrumação exige mudar este teste de propósito;
 *  - que nenhum endereço aparece duas vezes;
 *  - que TODO item abre para aquele perfil (`podeAbrirRota`, o espelho das guardas de
 *    App.tsx) — o menu nunca leva a um redirecionamento mudo para o início — e que as rotas
 *    da rede no menu ESTÃO no espelho (rota fora dele seria "sem guarda");
 *  - a Secretaria só com as três áreas (Panorama da Rede, Escolas, Avaliações externas), sem
 *    acordeão e sem nenhum item de premiação, usuários, configurações, relatórios ou análises;
 *  - o filtro de módulos (só Leitura / só Matemática) e o grupo de um item desenhado solto;
 *  - o item aceso em cada rota (as `filhas` de cada área da Secretaria, a ficha da escola, as
 *    rotas fora do menu dela sem item aceso; o Admin Global com a "Visão da rede" acesa nas
 *    telas que ele abre pelos links dela) — um único item marcado por vez;
 *  - o grupo `inicialAberto` aberto na 1ª visita, o grupo da rota atual aberto e a escolha
 *    do usuário guardada (chave `constela_menu_abertos_v3`);
 *  - a trilha em três níveis (Início › contexto › página);
 *  - a pesquisa pelos nomes antigos ("comparar" → Escolas, "vitrine" → Panorama da Rede...);
 *  - os atalhos Alt+1..3 da Secretaria e o cartão Contexto dela (escola → ficha);
 *  - a barra recolhida: as mesmas seções, ícones sem repetição e, no primeiro acesso, só
 *    o "Comece aqui".
 *
 * O jsdom não tem o CSS: um link dentro de um acordeão fechado continua na árvore de
 * acessibilidade. Por isso a árvore é lida pela ESTRUTURA (seção → botão do grupo →
 * painel que ele controla) e o aberto/fechado pelo `aria-expanded`. Nomes INVENTADOS.
 */
import { useLocation } from "react-router-dom";
import { describe, expect, it } from "vitest";

import Layout from "../components/Layout";
import { ImportacaoLoteProvider } from "../context/ImportacaoLoteContext";
import { useModulos } from "../hooks/useModulos";
import { usePerfil } from "../hooks/usePerfil";
import { destinosDoTeclado } from "../lib/atalhos";
import { podeAbrirRota, ROTAS_GUARDADAS, type PerfilDaRota } from "../lib/rotasGuardadas";
import type { Escola, Usuario } from "../lib/types";
import {
  escolaFake, fireEvent, renderComApp, responder, screen, userEvent, usuarioFake, waitFor, within,
} from "./utils";

function LayoutReal() {
  return (
    <ImportacaoLoteProvider>
      <Layout />
    </ImportacaoLoteProvider>
  );
}

const GLOBAL = usuarioFake({ id: 11, nome: "Raiz Sintética", cargo: "admin", is_global: true, escola_id: null });
const SECRETARIA = usuarioFake({ id: 12, nome: "Equipe Sintética da Rede", cargo: "coordenador", rede_id: 1, escola_id: null });
const COORDENACAO = usuarioFake({ id: 13, nome: "Coordenadora Sintética", cargo: "coordenador" });
const ADMIN_ESCOLA = usuarioFake({ id: 14, nome: "Administração Sintética", cargo: "admin" });
const PROFESSORA = usuarioFake({ id: 15, nome: "Professora Sintética", cargo: "professor" });

/** O que o próprio app calcula para o usuário (as mesmas fontes das guardas) e o endereço
 *  atual do roteador (rota + consulta). */
interface Espiao { perfil?: PerfilDaRota; tem?: (modulo: string) => boolean; endereco?: string }

async function montar(usuario: Usuario, {
  rota = "/", configurada = true, recolhido = false,
  escolas = [escolaFake({ id: 1 })] as Escola[], escolaSelecionada = undefined as number | undefined,
} = {}) {
  for (const escola of escolas) {
    responder("GET", `/escolas/${escola.id}/sync/onboarding`, { lista_piloto_importada: configurada });
  }
  if (recolhido) localStorage.setItem("constela_menu_recolhido", "1");
  const espiao: Espiao = {};
  function Espia() {
    espiao.perfil = usePerfil();
    espiao.tem = useModulos().tem;
    const local = useLocation();
    espiao.endereco = local.pathname + local.search;
    return null;
  }
  const tela = renderComApp(<><LayoutReal /><Espia /></>, { rota, usuario, escolas, escolaSelecionada });
  // Estado final: a sessão abriu (o nome no cartão do usuário — na barra recolhida, só no
  // title do avatar) e, sem a Lista Piloto, o status da escola chegou (o "Comece aqui" só
  // existe aí).
  if (recolhido) await screen.findAllByTitle(usuario.nome);
  else await screen.findAllByText(usuario.nome);
  if (!configurada) await screen.findAllByRole("link", { name: "Comece aqui" });
  return { tela, espiao };
}

const menu = () => screen.getByRole("navigation", { name: "Menu principal" });

const rotuloDoLink = (a: Element) =>
  `${a.querySelector("span")?.textContent ?? a.getAttribute("aria-label")} → ${a.getAttribute("href")}`;

type No = string | { grupo: string; itens: string[] };
interface SecaoLida { secao: string; itens: No[] }

/** A árvore do menu aberto, lida pela estrutura: seção (role=group, nomeada pelo título)
 *  → itens soltos (links) e grupos (botão do acordeão + os links do painel que ele controla). */
function arvoreDoMenu(): SecaoLida[] {
  return Array.from(menu().querySelectorAll<HTMLElement>('[role="group"]')).map((secao) => {
    const titulo = document.getElementById(secao.getAttribute("aria-labelledby") ?? "")?.textContent ?? "";
    const itens: No[] = [];
    for (const filho of Array.from((secao.lastElementChild as HTMLElement).children)) {
      if (filho.tagName === "A") itens.push(rotuloDoLink(filho));
      const botao = filho.tagName === "DIV" ? filho.querySelector("button[aria-expanded]") : null;
      if (botao) {
        const painel = document.getElementById(botao.getAttribute("aria-controls") ?? "") as HTMLElement;
        itens.push({ grupo: botao.textContent?.trim() ?? "", itens: Array.from(painel.querySelectorAll("a")).map(rotuloDoLink) });
      }
    }
    return { secao: titulo, itens };
  });
}

const hrefsDoMenu = () => Array.from(menu().querySelectorAll("a")).map((a) => a.getAttribute("href") ?? "");
const marcados = () => Array.from(menu().querySelectorAll('a[aria-current="page"]')).map((a) => a.getAttribute("href"));
const gruposAbertos = () => Object.fromEntries(
  Array.from(menu().querySelectorAll("button[aria-expanded]")).map((b) => [b.textContent?.trim(), b.getAttribute("aria-expanded") === "true"]),
);
const niveisDaTrilha = () =>
  Array.from(screen.getByRole("navigation", { name: "Trilha de navegação" }).querySelectorAll("a, span")).map((el) => el.textContent);

// ── Árvores esperadas ───────────────────────────────────────────────────────

const ACOMPANHAMENTO = [
  "Elefante Letrado → /elefante", "Catálogo de Livros → /livros", "Matific → /matific",
  "Insights → /insights", "Comparador → /comparador", "Assistente → /assistente",
];
const RECONHECIMENTO = [
  "Ranking Geral → /ranking", "Premiações → /premiacoes", "Conquistas → /conquistas",
  "Biblioteca de Conquistas → /conquistas/biblioteca", "Painel Público → /painel-publico",
];
// "Gestão escolar" do Admin Global: sem Usuários (o dele fica solto em Administração).
const ESCOLA = [
  "Visão da Escola → /escola", "Turmas → /turmas", "Alunos → /alunos", "Professores → /professores",
  "Relatórios → /relatorios",
];
// "Minha Escola" da coordenação e da administração da escola: com as contas de acesso.
const MINHA_ESCOLA = [
  "Visão da Escola → /escola", "Turmas → /turmas", "Alunos → /alunos", "Professores → /professores",
  "Usuários → /usuarios", "Relatórios → /relatorios",
];
// As três áreas da Secretaria (DESENHO3 §1), nesta ordem.
const TRES_AREAS = [
  "Panorama da Rede → /", "Escolas → /rede/escolas", "Avaliações externas → /rede/avaliacoes-externas",
];

const ARVORE: Record<string, SecaoLida[]> = {
  global: [
    { secao: "Administração", itens: [
      "Visão Global → /",
      { grupo: "Redes e municípios", itens: [
        "Painel da Rede → /rede", "Visão da rede → /rede/visao", "Ranking da Rede → /rede/ranking",
        "Análises avançadas → /rede/analise", "Importações e fontes → /rede/avaliacoes", "Gerenciar Rede → /rede/gerenciar",
      ] },
      "Escolas → /escolas",
      "Usuários → /usuarios",
      { grupo: "Integrações e dados", itens: [
        "Integrações → /sincronizacao", "Importações → /importacoes",
        "Revisões de identidade → /revisoes-identidade", "Diagnóstico Elefante → /diagnostico-elefante",
      ] },
      { grupo: "Configurações", itens: ["Critérios → /metricas", "Simulador → /simulador", "Configurações Gerais → /configuracoes"] },
      // Monitoramento tem UM item: desenhado solto.
      "Sessões Ativas → /sessoes",
    ] },
    { secao: "Escola selecionada", itens: [
      { grupo: "Gestão escolar", itens: ESCOLA },
      { grupo: "Acompanhamento", itens: ACOMPANHAMENTO },
      { grupo: "Reconhecimento", itens: RECONHECIMENTO },
    ] },
  ],
  // Uma seção, três áreas soltas, sem acordeão (DESENHO3 §1).
  secretaria: [{ secao: "Rede municipal", itens: TRES_AREAS }],
  coordenacao: [
    { secao: "Escola", itens: [
      "Visão geral → /",
      { grupo: "Minha Escola", itens: MINHA_ESCOLA },
      { grupo: "Acompanhamento", itens: ACOMPANHAMENTO },
      { grupo: "Reconhecimento", itens: RECONHECIMENTO },
    ] },
    { secao: "Gestão", itens: [
      { grupo: "Dados e integrações", itens: ["Integrações → /sincronizacao", "Revisões de identidade → /revisoes-identidade"] },
      { grupo: "Regras de pontuação", itens: [
        "Critérios → /metricas", "Simulador → /simulador", "Editar conquistas → /configuracoes/conquistas",
      ] },
    ] },
  ],
  adminEscola: [
    { secao: "Escola", itens: [
      "Visão geral → /",
      { grupo: "Minha Escola", itens: MINHA_ESCOLA },
      { grupo: "Acompanhamento", itens: ACOMPANHAMENTO },
      { grupo: "Reconhecimento", itens: RECONHECIMENTO },
    ] },
    { secao: "Gestão", itens: [
      { grupo: "Dados e integrações", itens: ["Integrações → /sincronizacao", "Revisões de identidade → /revisoes-identidade"] },
      // Sem "Editar conquistas": o admin chega nele pelo cartão de Configurações Gerais.
      { grupo: "Regras de pontuação", itens: ["Critérios → /metricas", "Simulador → /simulador"] },
      // Solto (só do administrador): a coordenação não tem.
      "Configurações Gerais → /configuracoes",
    ] },
  ],
  professora: [
    { secao: "Minhas turmas", itens: ["Visão geral → /", "Meus Alunos → /alunos", "Insights → /insights", "Meus Relatórios → /relatorios"] },
    { secao: "Reconhecimento", itens: ["Ranking → /ranking", "Premiações → /premiacoes", "Biblioteca de Conquistas → /conquistas/biblioteca"] },
  ],
};

const PERFIS: [string, Usuario][] = [
  ["global", GLOBAL],
  ["secretaria", SECRETARIA],
  ["coordenacao", COORDENACAO],
  ["adminEscola", ADMIN_ESCOLA],
  ["professora", PROFESSORA],
];

describe("Navegação — a árvore de cada perfil", () => {
  it.each(PERFIS)("%s: seções, grupos, itens e endereços exatos", async (chave, usuario) => {
    await montar(usuario);
    expect(arvoreDoMenu()).toEqual(ARVORE[chave]);
  });

  it.each(PERFIS)("%s: nenhum endereço repetido e TODO item abre para o perfil (podeAbrirRota)", async (_chave, usuario) => {
    const { espiao } = await montar(usuario);
    const hrefs = hrefsDoMenu();
    // A Secretaria tem três itens; os demais perfis, mais.
    expect(hrefs.length).toBeGreaterThanOrEqual(3);
    expect(new Set(hrefs).size, `repetidos: ${hrefs.join(", ")}`).toBe(hrefs.length);
    const barrados = hrefs.filter((h) => !podeAbrirRota(h, espiao.perfil!, espiao.tem!));
    expect(barrados).toEqual([]);
  });

  // `podeAbrirRota` devolve `true` para rota FORA do espelho (rota sem guarda): sem esta
  // conferência, uma tela nova da rede criada em App.tsx sem entrar em lib/rotasGuardadas.ts
  // passaria acima por acaso. As telas da Secretaria usam a MESMA guarda de /rede/analise.
  it.each([["secretaria", SECRETARIA, 2], ["global", GLOBAL, 6]] as const)(
    "%s: toda rota da rede no menu está no espelho das guardas de App.tsx", async (_chave, usuario, minimo) => {
      await montar(usuario);
      const daRede = [...new Set(hrefsDoMenu().filter((h) => h.startsWith("/rede")).map((h) => h.split("?")[0]))];
      expect(daRede.length).toBeGreaterThanOrEqual(minimo);
      expect(daRede.filter((rota) => !ROTAS_GUARDADAS.some((r) => r.caminho === rota))).toEqual([]);
    });

  it("as telas da Secretaria têm a guarda RotaRede: abrem para a Secretaria e o global, não para a escola", () => {
    const perfil = (p: Partial<PerfilDaRota>): PerfilDaRota =>
      ({ global: false, secretaria: false, rede: false, gestor: false, admin: false, ...p });
    const secretaria = perfil({ secretaria: true, rede: true, gestor: true });
    const global = perfil({ global: true, rede: true, gestor: true, admin: true });
    const coordenacao = perfil({ gestor: true });
    const professora = perfil({});
    const todos = () => true;
    // As que saíram do menu dela continuam existindo, com a mesma guarda (DESENHO3 §1).
    for (const rota of ["/rede/visao", "/rede/acompanhamento", "/rede/escolas", "/rede/avaliacoes-externas",
      "/rede/plataformas", "/rede/relatorios", "/rede", "/rede/ranking", "/rede/analise", "/rede/avaliacoes"]) {
      expect(ROTAS_GUARDADAS.find((r) => r.caminho === rota)?.guardas, rota).toEqual(["RotaRede"]);
      expect(podeAbrirRota(rota, secretaria, todos), rota).toBe(true);
      expect(podeAbrirRota(rota, global, todos), rota).toBe(true);
      expect(podeAbrirRota(rota, coordenacao, todos), rota).toBe(false);
      expect(podeAbrirRota(rota, professora, todos), rota).toBe(false);
    }
  });

  it("a Secretaria (cargo coordenador, logo gestor para as guardas) não ganha nenhuma tela de escola", async () => {
    await montar(SECRETARIA);
    const hrefs = hrefsDoMenu();
    for (const rota of ["/escola", "/turmas", "/alunos", "/professores", "/metricas", "/conquistas", "/usuarios", "/sincronizacao"]) {
      expect(hrefs, rota).not.toContain(rota);
    }
    // Só telas da rede (e a página inicial).
    expect(hrefs.filter((h) => h !== "/" && !h.startsWith("/rede"))).toEqual([]);
  });

  it("a Secretaria só tem as três áreas: nada de premiação, usuários, configurações, relatórios ou análises", async () => {
    await montar(SECRETARIA);
    const hrefs = hrefsDoMenu().map((h) => h.split("?")[0]);
    expect(hrefs).toEqual(["/", "/rede/escolas", "/rede/avaliacoes-externas"]);
    for (const rota of ["/premiacoes", "/conquistas", "/painel-publico", "/usuarios", "/configuracoes", "/relatorios",
      "/rede/relatorios", "/rede/analise", "/rede/acompanhamento", "/rede", "/rede/ranking", "/rede/plataformas",
      "/rede/avaliacoes", "/rede/visao"]) {
      expect(hrefs, rota).not.toContain(rota);
    }
    // Sem acordeão nenhum (nada de "Análises avançadas") e sem as seções antigas.
    expect(menu().querySelectorAll("button[aria-expanded]")).toHaveLength(0);
    for (const nome of ["Resultados", "Relatórios e gestão", "Aprofundar"]) {
      expect(screen.queryByRole("group", { name: nome }), nome).toBeNull();
    }
    // Ícones distintos (a barra recolhida mostra só o ícone).
    const icones = Array.from(menu().querySelectorAll("a svg")).map((svg) =>
      Array.from(svg.classList).find((c) => c.startsWith("lucide-")));
    expect(new Set(icones).size).toBe(3);
  });

  it("coordenação: Importações, Diagnóstico Elefante, Configurações Gerais e Ranking da Rede continuam fora", async () => {
    await montar(COORDENACAO);
    const hrefs = hrefsDoMenu();
    for (const rota of ["/importacoes", "/diagnostico-elefante", "/configuracoes", "/rede/ranking", "/rede", "/escolas", "/sessoes"]) {
      expect(hrefs, rota).not.toContain(rota);
    }
  });
});

describe("Navegação — módulos contratados", () => {
  it("só Leitura: Matific some; Elefante e Catálogo ficam (e tudo continua abrindo)", async () => {
    const { espiao } = await montar({ ...COORDENACAO, modulos: ["leitura"] });
    const acompanhamento = arvoreDoMenu()[0].itens.find((n) => typeof n !== "string" && n.grupo === "Acompanhamento");
    expect(acompanhamento).toEqual({ grupo: "Acompanhamento", itens: [
      "Elefante Letrado → /elefante", "Catálogo de Livros → /livros",
      "Insights → /insights", "Comparador → /comparador", "Assistente → /assistente",
    ] });
    expect(hrefsDoMenu()).not.toContain("/matific");
    expect(hrefsDoMenu().filter((h) => !podeAbrirRota(h, espiao.perfil!, espiao.tem!))).toEqual([]);
  });

  it("só Matemática: Elefante e Catálogo somem; Matific fica", async () => {
    const { espiao } = await montar({ ...ADMIN_ESCOLA, modulos: ["matematica"] });
    const acompanhamento = arvoreDoMenu()[0].itens.find((n) => typeof n !== "string" && n.grupo === "Acompanhamento");
    expect(acompanhamento).toEqual({ grupo: "Acompanhamento", itens: [
      "Matific → /matific", "Insights → /insights", "Comparador → /comparador", "Assistente → /assistente",
    ] });
    expect(hrefsDoMenu()).not.toContain("/elefante");
    expect(hrefsDoMenu()).not.toContain("/livros");
    expect(hrefsDoMenu().filter((h) => !podeAbrirRota(h, espiao.perfil!, espiao.tem!))).toEqual([]);
  });

  it("Admin Global com só Matemática: o filtro vale em todos os grupos (Diagnóstico Elefante sai de Integrações e dados)", async () => {
    const { espiao } = await montar({ ...GLOBAL, modulos: ["matematica"] });
    const integracoes = arvoreDoMenu()[0].itens.find((n) => typeof n !== "string" && n.grupo === "Integrações e dados");
    expect(integracoes).toEqual({ grupo: "Integrações e dados", itens: [
      "Integrações → /sincronizacao", "Importações → /importacoes", "Revisões de identidade → /revisoes-identidade",
    ] });
    for (const rota of ["/diagnostico-elefante", "/elefante", "/livros"]) expect(hrefsDoMenu(), rota).not.toContain(rota);
    expect(hrefsDoMenu()).toContain("/matific");
    expect(hrefsDoMenu().filter((h) => !podeAbrirRota(h, espiao.perfil!, espiao.tem!))).toEqual([]);
  });

  // A tela do uso das plataformas saiu do menu dela (é o detalhe do Panorama): a trilha diz o
  // nome das plataformas que a rede TEM, o mesmo do h1 da tela.
  it("Secretaria com um módulo só: as mesmas três áreas, e a trilha da tela das plataformas leva o nome do que a rede contratou", async () => {
    await montar({ ...SECRETARIA, modulos: ["leitura"] }, { rota: "/rede/plataformas" });
    expect(arvoreDoMenu()).toEqual(ARVORE.secretaria);
    expect(niveisDaTrilha()).toEqual(["Panorama da Rede", "Rede municipal", "Elefante Letrado"]);
    expect(marcados()).toEqual(["/"]);
  });

  it("…e com só Matemática, 'Matific' — e a pesquisa não acha nada pelo Elefante nem pela leitura", async () => {
    await montar({ ...SECRETARIA, modulos: ["matematica"] }, { rota: "/rede/plataformas" });
    expect(niveisDaTrilha()).toEqual(["Panorama da Rede", "Rede municipal", "Matific"]);
    const caixa = screen.getByRole("textbox", { name: /Pesquisar páginas/ });
    for (const termo of ["elefante", "leitura"]) {
      await userEvent.clear(caixa);
      await userEvent.type(caixa, termo);
      expect(await screen.findByText("Nada encontrado."), termo).toBeInTheDocument();
    }
    for (const termo of ["matific", "matemática"]) {
      await userEvent.clear(caixa);
      await userEvent.type(caixa, termo);
      expect(await screen.findByRole("button", { name: /^Escolas/ }), termo).toHaveTextContent("Página");
    }
  });

  it("coordenação e admin da escola: Usuários fica em Minha Escola (não mais em Gestão)", async () => {
    for (const usuario of [COORDENACAO, ADMIN_ESCOLA]) {
      const { tela } = await montar(usuario);
      const minhaEscola = screen.getByRole("button", { name: "Minha Escola" });
      const painel = document.getElementById(minhaEscola.getAttribute("aria-controls") ?? "") as HTMLElement;
      expect(within(painel).getByRole("link", { name: "Usuários" })).toHaveAttribute("href", "/usuarios");
      expect(within(screen.getByRole("group", { name: "Gestão" })).queryByRole("link", { name: "Usuários" })).toBeNull();
      // O acordeão "Configurações" (Usuários + Configurações Gerais) saiu.
      expect(screen.queryByRole("button", { name: "Configurações" })).toBeNull();
      tela.unmount();
    }
  });

  it("admin da escola: Configurações Gerais solto em Gestão; a coordenação não o tem", async () => {
    const { tela } = await montar(ADMIN_ESCOLA);
    expect(within(screen.getByRole("group", { name: "Gestão" })).getByRole("link", { name: "Configurações Gerais" }))
      .toHaveAttribute("href", "/configuracoes");
    tela.unmount();
    await montar(COORDENACAO);
    expect(within(menu()).queryByRole("link", { name: "Configurações Gerais" })).toBeNull();
  });

  it("grupo com UM item vira item solto — no Admin Global (Monitoramento › Sessões Ativas)", async () => {
    await montar(GLOBAL);
    expect(screen.queryByRole("button", { name: "Monitoramento" })).toBeNull();
    expect(within(screen.getByRole("group", { name: "Administração" })).getByRole("link", { name: "Sessões Ativas" }))
      .toHaveAttribute("href", "/sessoes");
  });
});

describe("Navegação — item ativo (regra única, entende a aba ?ver=)", () => {
  it.each([
    ["/", "/"],
    // Panorama da Rede: o detalhe do uso das plataformas é aberto por ele.
    ["/rede/plataformas", "/"],
    // Escolas: a lista, a comparação pela URL, a ficha de cada escola (sub-rota), o Ranking da
    // Rede e a Visão da Escola (as turmas de uma escola).
    ["/rede/escolas", "/rede/escolas"],
    ["/rede/escolas?comparar=1,2,3", "/rede/escolas"],
    ["/rede/escolas/3", "/rede/escolas"],
    ["/rede/ranking", "/rede/escolas"],
    ["/escola", "/rede/escolas"],
    // Avaliações externas: os parâmetros do indicador não apagam o destaque; os arquivos
    // oficiais de cada número (/rede/avaliacoes) são o detalhe dela.
    ["/rede/avaliacoes-externas", "/rede/avaliacoes-externas"],
    ["/rede/avaliacoes-externas?indicador=saresp&etapa=anos_iniciais&edicao=2025", "/rede/avaliacoes-externas"],
    ["/rede/avaliacoes", "/rede/avaliacoes-externas"],
  ])("Secretaria em %s: só %s fica marcado", async (rota, esperado) => {
    await montar(SECRETARIA, { rota });
    expect(marcados()).toEqual([esperado]);
  });

  // As rotas que saíram do menu dela continuam abrindo (link antigo, endereço digitado), mas
  // nenhuma das três áreas acende nelas.
  it.each([
    "/rede/acompanhamento", "/rede/relatorios", "/rede", "/rede/visao", "/rede/analise", "/rede/analise?ver=relacao",
    "/turmas", "/conquistas", "/painel-publico", "/ranking", "/suporte", "/minha-conta",
  ])("Secretaria em %s (fora do menu dela): nenhum item aceso", async (rota) => {
    await montar(SECRETARIA, { rota });
    expect(marcados()).toEqual([]);
  });

  it.each([
    ["coordenação", "/configuracoes/conquistas", "/configuracoes/conquistas", COORDENACAO],
    // O admin não tem o item: a página é parte de Configurações Gerais.
    ["admin da escola", "/configuracoes/conquistas", "/configuracoes", ADMIN_ESCOLA],
    ["coordenação", "/conquistas/biblioteca", "/conquistas/biblioteca", COORDENACAO],
    ["coordenação", "/alunos/12", "/alunos", COORDENACAO],
    ["coordenação", "/relatorios/periodo", "/relatorios", COORDENACAO],
    ["coordenação", "/usuarios", "/usuarios", COORDENACAO],
    ["coordenação", "/escola", "/escola", COORDENACAO],
    ["admin da escola", "/usuarios", "/usuarios", ADMIN_ESCOLA],
    ["Admin Global", "/rede/analise?ver=relacao", "/rede/analise", GLOBAL],
    ["Admin Global", "/rede", "/rede", GLOBAL],
    ["Admin Global", "/rede/visao", "/rede/visao", GLOBAL],
    ["Admin Global", "/rede/ranking", "/rede/ranking", GLOBAL],
    ["Admin Global", "/escola", "/escola", GLOBAL],
    // As telas da Secretaria que o global abre pelos links da Visão da rede acendem ela —
    // a ficha de cada escola também.
    ["Admin Global", "/rede/escolas", "/rede/visao", GLOBAL],
    ["Admin Global", "/rede/escolas/3", "/rede/visao", GLOBAL],
    ["Admin Global", "/rede/acompanhamento", "/rede/visao", GLOBAL],
    // (com a rede escolhida na URL, o link do item leva a rede junto — `destinoDoItem`)
    ["Admin Global", "/rede/avaliacoes-externas?indicador=ideb&rede=2", "/rede/visao?rede=2", GLOBAL],
    ["Admin Global", "/rede/escolas/3?rede=2", "/rede/visao?rede=2", GLOBAL],
    ["Admin Global", "/rede/plataformas", "/rede/visao", GLOBAL],
    ["Admin Global", "/rede/relatorios", "/rede/visao", GLOBAL],
  ] as const)("%s em %s: só %s fica marcado", async (_rotulo, rota, esperado, usuario) => {
    await montar(usuario, { rota });
    expect(marcados()).toEqual([esperado]);
  });

  it("a pesquisa acha a tela pelo assunto e leva a ela", async () => {
    await montar(SECRETARIA);
    await userEvent.type(screen.getByRole("textbox", { name: /Pesquisar páginas/ }), "saresp");
    expect(await screen.findByRole("button", { name: /Avaliações externas/ })).toHaveTextContent("Página");
    await userEvent.click(screen.getByRole("button", { name: /Avaliações externas/ }));
    expect(marcados()).toEqual(["/rede/avaliacoes-externas"]);
  });
});

describe("Navegação — a pesquisa acha as telas pelos nomes antigos", () => {
  const pesquisar = async (termo: string) => {
    const caixa = screen.getByRole("textbox", { name: /Pesquisar páginas/ });
    await userEvent.clear(caixa);
    await userEvent.type(caixa, termo);
  };
  const paginasAchadas = () => screen.queryAllByRole("button")
    .filter((b) => b.textContent?.endsWith("Página"))
    .map((b) => b.textContent?.replace(/Página$/, ""));

  it.each([
    // Escolas: a comparação, a ficha e o Ranking da Rede (que ela abre).
    ["comparar", "Escolas"],
    ["comparar escolas", "Escolas"],
    ["ficha da escola", "Escolas"],
    ["ranking", "Escolas"],
    ["evolução", "Escolas"],
    ["elefante", "Escolas"],
    ["matific", "Escolas"],
    ["leitura", "Escolas"],
    ["matemática", "Escolas"],
    // Avaliações externas: os indicadores e os arquivos oficiais de cada número.
    ["saresp", "Avaliações externas"],
    ["ideb", "Avaliações externas"],
    ["saeb", "Avaliações externas"],
    ["fontes dos indicadores", "Avaliações externas"],
    ["série histórica", "Avaliações externas"],
    // Panorama da Rede: a vitrine e as metas (do antigo Painel da Rede), o uso e as escolas.
    ["vitrine", "Panorama da Rede"],
    ["metas", "Panorama da Rede"],
    ["painel da rede", "Panorama da Rede"],
    ["destaques", "Panorama da Rede"],
    ["cadastradas", "Panorama da Rede"],
    ["participação", "Panorama da Rede"],
    ["situação de uso", "Panorama da Rede"],
    ["visão geral", "Panorama da Rede"],
  ])("Secretaria: '%s' acha '%s'", async (termo, pagina) => {
    await montar(SECRETARIA);
    await pesquisar(termo);
    await screen.findAllByText("Página");
    expect(paginasAchadas()).toContain(pagina);
  });

  // O que saiu do menu dela não volta pela pesquisa (a pesquisa só abre itens do menu). Os
  // sinais de atenção da antiga "Escolas em acompanhamento" não estão no Panorama novo
  // (DESENHO3 §2): "acompanhamento" e "atenção" não levam a uma tela sem aquele conteúdo.
  it.each(["boletim", "premiações", "usuários", "configurações", "análise educacional", "diagnóstico",
    "acompanhamento", "atenção"])(
    "Secretaria: '%s' não acha nenhuma página", async (termo) => {
      await montar(SECRETARIA);
      await pesquisar(termo);
      expect(await screen.findByText("Nada encontrado.")).toBeInTheDocument();
      expect(paginasAchadas()).toEqual([]);
    });

  it("Secretaria: a página achada abre e acende o item dela", async () => {
    const { espiao } = await montar(SECRETARIA, { rota: "/rede/avaliacoes-externas" });
    await pesquisar("vitrine");
    await userEvent.click(await screen.findByRole("button", { name: /Panorama da Rede/ }));
    expect(espiao.endereco).toBe("/");
    expect(marcados()).toEqual(["/"]);
  });

  it.each([
    ["análise educacional", "Análises avançadas"],
    ["panorama da rede", "Visão da rede"],
  ])("Admin Global: '%s' acha '%s'", async (termo, pagina) => {
    await montar(GLOBAL);
    await pesquisar(termo);
    await screen.findAllByText("Página");
    expect(paginasAchadas()).toContain(pagina);
  });
});

describe("Navegação — os links do menu levam os filtros compartilhados", () => {
  // Já em /rede/analise, o item do menu do global é uma ABA da página: leva Série, Escola e a
  // rede escolhida — como a aba da própria página (`trocarAba`). Os parâmetros de uma aba
  // (indicador, etapa, edição, período, métrica...) não passam para outra.
  const ROTA_COM_FILTROS =
    "/rede/analise?ver=relacao&indicador=saresp&etapa=anos_iniciais&componente=lp&visao=escolas"
    + "&edicao=2025&serie=3&escola=1&de=2026-02-01&ate=2026-04-30&metrica=uso";
  const linkDoMenu = (nome: string) => within(menu()).getByRole("link", { name: nome });

  it("Secretaria em /rede/analise (fora do menu dela): as três áreas levam ao caminho delas, sem os filtros da análise", async () => {
    await montar(SECRETARIA, { rota: ROTA_COM_FILTROS });
    expect(linkDoMenu("Panorama da Rede")).toHaveAttribute("href", "/");
    expect(linkDoMenu("Escolas")).toHaveAttribute("href", "/rede/escolas");
    expect(linkDoMenu("Avaliações externas")).toHaveAttribute("href", "/rede/avaliacoes-externas");
    expect(marcados()).toEqual([]);
  });

  it("Secretaria: as telas dela não têm `rede=` e os itens ficam com o caminho de sempre", async () => {
    await montar(SECRETARIA, { rota: "/rede/escolas/3?periodo=ano" });
    expect(linkDoMenu("Panorama da Rede")).toHaveAttribute("href", "/");
    expect(linkDoMenu("Escolas")).toHaveAttribute("href", "/rede/escolas");
    expect(linkDoMenu("Avaliações externas")).toHaveAttribute("href", "/rede/avaliacoes-externas");
  });

  it("barra recolhida (Admin Global): a mesma regra nos ícones", async () => {
    await montar(GLOBAL, { rota: "/rede/analise?ver=relacao&rede=2&serie=4&indicador=ica", recolhido: true });
    expect(linkDoMenu("Análises avançadas")).toHaveAttribute("href", "/rede/analise?serie=4&rede=2");
    expect(linkDoMenu("Visão da rede")).toHaveAttribute("href", "/rede/visao?rede=2");
    expect(linkDoMenu("Importações e fontes")).toHaveAttribute("href", "/rede/avaliacoes");
    expect(marcados()).toEqual(["/rede/analise?serie=4&rede=2"]);
  });

  it("Admin Global: o item único da análise mantém a rede escolhida e a série", async () => {
    await montar(GLOBAL, { rota: "/rede/analise?ver=relacao&rede=2&serie=4&edicao=2025" });
    expect(linkDoMenu("Análises avançadas")).toHaveAttribute("href", "/rede/analise?serie=4&rede=2");
    expect(marcados()).toEqual(["/rede/analise?serie=4&rede=2"]);
    // E a Visão da rede (que também lê `?rede=`) leva só a rede — nada da análise.
    expect(linkDoMenu("Visão da rede")).toHaveAttribute("href", "/rede/visao?rede=2");
  });

  // O global escolhe a rede na Visão da rede e segue pelos links dela (que levam `rede=`);
  // pelo menu, voltava à primeira rede sem aviso. Entre as páginas que leem `?rede=`, o
  // item leva só a rede; o Painel da Rede e as Importações e fontes escolhem a rede de
  // outro jeito e ficam com o caminho deles.
  it("Admin Global: entre as telas da rede o menu mantém a rede escolhida (e só ela)", async () => {
    const { espiao } = await montar(GLOBAL, { rota: "/rede/escolas?rede=2&aba=plataformas&serie=3&escola=7" });
    expect(linkDoMenu("Visão da rede")).toHaveAttribute("href", "/rede/visao?rede=2");
    expect(linkDoMenu("Análises avançadas")).toHaveAttribute("href", "/rede/analise?rede=2");
    expect(linkDoMenu("Painel da Rede")).toHaveAttribute("href", "/rede");
    expect(linkDoMenu("Importações e fontes")).toHaveAttribute("href", "/rede/avaliacoes");
    expect(linkDoMenu("Ranking da Rede")).toHaveAttribute("href", "/rede/ranking");
    await userEvent.click(linkDoMenu("Análises avançadas"));
    expect(espiao.endereco).toBe("/rede/analise?rede=2");
    expect(marcados()).toEqual(["/rede/analise?rede=2"]);
  });

  it("Admin Global na ficha de uma escola (/rede/escolas/:id): o menu também mantém a rede escolhida", async () => {
    await montar(GLOBAL, { rota: "/rede/escolas/3?rede=2&periodo=ano" });
    expect(linkDoMenu("Visão da rede")).toHaveAttribute("href", "/rede/visao?rede=2");
    expect(linkDoMenu("Análises avançadas")).toHaveAttribute("href", "/rede/analise?rede=2");
    expect(linkDoMenu("Painel da Rede")).toHaveAttribute("href", "/rede");
  });
});

describe("Navegação — grupos abertos", () => {
  it("coordenação, 1ª visita: só 'Minha Escola' (inicialAberto) nasce aberta", async () => {
    await montar(COORDENACAO);
    expect(gruposAbertos()).toEqual({
      "Minha Escola": true,
      "Acompanhamento": false,
      "Reconhecimento": false,
      "Dados e integrações": false,
      "Regras de pontuação": false,
    });
  });

  it("Admin Global, 1ª visita: só 'Redes e municípios' nasce aberto", async () => {
    await montar(GLOBAL);
    expect(gruposAbertos()).toEqual({
      "Redes e municípios": true,
      "Integrações e dados": false,
      "Configurações": false,
      "Gestão escolar": false,
      "Acompanhamento": false,
      "Reconhecimento": false,
    });
  });

  // Sem acordeão: nada para abrir ou fechar, em rota nenhuma — nem com a escolha guardada da
  // arrumação anterior (o acordeão "Análises avançadas", chave `avancadas`).
  it.each(["/", "/rede/escolas", "/rede/avaliacoes", "/rede/analise", "/rede/analise?ver=relacao", "/rede"])(
    "Secretaria em %s: nenhum acordeão", async (rota) => {
      localStorage.setItem("constela_menu_abertos_v3", JSON.stringify({ avancadas: true }));
      await montar(SECRETARIA, { rota });
      expect(gruposAbertos()).toEqual({});
      expect(arvoreDoMenu()).toEqual(ARVORE.secretaria);
    });

  it("o grupo da rota atual abre sozinho (e o ponto de partida continua aberto)", async () => {
    await montar(COORDENACAO, { rota: "/premiacoes" });
    expect(gruposAbertos()).toMatchObject({ "Reconhecimento": true, "Minha Escola": true, "Regras de pontuação": false });
    expect(marcados()).toEqual(["/premiacoes"]);
  });

  it("a escolha do usuário fica guardada (chave v3) e vale na próxima visita", async () => {
    const { tela } = await montar(COORDENACAO);
    await userEvent.click(screen.getByRole("button", { name: "Minha Escola" }));
    await userEvent.click(screen.getByRole("button", { name: "Reconhecimento" }));
    expect(JSON.parse(localStorage.getItem("constela_menu_abertos_v3") ?? "{}"))
      .toEqual({ "minha-escola": false, "reconhecimento": true });
    tela.unmount();
    await montar(COORDENACAO);
    expect(gruposAbertos()).toMatchObject({ "Minha Escola": false, "Reconhecimento": true });
  });

  it("a chave antiga (outra arrumação) não vale mais", async () => {
    localStorage.setItem("constela_menu_abertos", JSON.stringify(["reconhecimento", "plataformas"]));
    await montar(COORDENACAO);
    expect(gruposAbertos()).toMatchObject({ "Minha Escola": true, "Reconhecimento": false });
  });
});

describe("Navegação — trilha em três níveis", () => {
  it.each([
    ["coordenação", "/turmas", ["Visão geral", "Minha Escola", "Turmas"], COORDENACAO],
    // Detalhe herda o contexto do item pai.
    ["coordenação", "/alunos/12", ["Visão geral", "Minha Escola", "Perfil do aluno"], COORDENACAO],
    ["coordenação", "/turmas/3", ["Visão geral", "Minha Escola", "Detalhe da turma"], COORDENACAO],
    // Usuários agora mora em Minha Escola (coordenação e admin da escola).
    ["coordenação", "/usuarios", ["Visão geral", "Minha Escola", "Usuários"], COORDENACAO],
    ["admin da escola", "/usuarios", ["Visão geral", "Minha Escola", "Usuários"], ADMIN_ESCOLA],
    // Item solto: o contexto é a SEÇÃO (Configurações Gerais solto em Gestão).
    ["admin da escola", "/configuracoes", ["Visão geral", "Gestão", "Configurações Gerais"], ADMIN_ESCOLA],
    ["admin da escola", "/configuracoes/conquistas", ["Visão geral", "Gestão", "Editar conquistas"], ADMIN_ESCOLA],
    // Fora do menu (a escola chega por Integrações): sem contexto, com o nome de sempre.
    ["coordenação", "/importacoes", ["Visão geral", "Importações (avançado)"], COORDENACAO],
    ["professora", "/alunos", ["Visão geral", "Minhas turmas", "Meus Alunos"], PROFESSORA],
    ["professora", "/ranking", ["Visão geral", "Reconhecimento", "Ranking"], PROFESSORA],
    ["Admin Global", "/sessoes", ["Visão Global", "Administração", "Sessões Ativas"], GLOBAL],
    ["Admin Global", "/rede/avaliacoes", ["Visão Global", "Redes e municípios", "Importações e fontes"], GLOBAL],
    ["Admin Global", "/rede/visao", ["Visão Global", "Redes e municípios", "Visão da rede"], GLOBAL],
    ["Admin Global", "/rede/analise", ["Visão Global", "Redes e municípios", "Análises avançadas"], GLOBAL],
    // Telas da Secretaria abertas pelos links da Visão da rede: o grupo dela e o nome da tela.
    ["Admin Global", "/rede/escolas", ["Visão Global", "Redes e municípios", "Escolas"], GLOBAL],
    ["Admin Global", "/rede/escolas/3", ["Visão Global", "Redes e municípios", "Ficha da escola"], GLOBAL],
    ["Admin Global", "/rede/avaliacoes-externas", ["Visão Global", "Redes e municípios", "Avaliações externas"], GLOBAL],
    // Secretaria: as três áreas (e o que fica dentro delas) → a seção "Rede municipal".
    ["Secretaria", "/rede/escolas", ["Panorama da Rede", "Rede municipal", "Escolas"], SECRETARIA],
    ["Secretaria", "/rede/escolas?comparar=1,2", ["Panorama da Rede", "Rede municipal", "Escolas"], SECRETARIA],
    ["Secretaria", "/rede/escolas/3", ["Panorama da Rede", "Rede municipal", "Ficha da escola"], SECRETARIA],
    ["Secretaria", "/rede/ranking", ["Panorama da Rede", "Rede municipal", "Ranking da Rede"], SECRETARIA],
    ["Secretaria", "/escola", ["Panorama da Rede", "Rede municipal", "Visão da Escola"], SECRETARIA],
    ["Secretaria", "/rede/avaliacoes-externas?indicador=ideb", ["Panorama da Rede", "Rede municipal", "Avaliações externas"], SECRETARIA],
    ["Secretaria", "/rede/avaliacoes", ["Panorama da Rede", "Rede municipal", "Fontes dos indicadores"], SECRETARIA],
    ["Secretaria", "/rede/plataformas", ["Panorama da Rede", "Rede municipal", "Elefante e Matific"], SECRETARIA],
    // Fora do menu dela: só o início e o nome da tela.
    ["Secretaria", "/rede/acompanhamento", ["Panorama da Rede", "Escolas em acompanhamento"], SECRETARIA],
    ["Secretaria", "/rede/relatorios", ["Panorama da Rede", "Relatórios e exportações"], SECRETARIA],
    ["Secretaria", "/rede", ["Panorama da Rede", "Painel da Rede"], SECRETARIA],
    ["Secretaria", "/rede/analise?ver=relacao", ["Panorama da Rede", "Análises avançadas"], SECRETARIA],
    ["Secretaria", "/turmas", ["Panorama da Rede", "Turmas"], SECRETARIA],
    ["Secretaria", "/suporte", ["Panorama da Rede", "Suporte"], SECRETARIA],
    // O global não tem "Editar conquistas" no menu: o contexto é o do item pai
    // (Configurações Gerais) e a página guarda o nome dela.
    ["Admin Global", "/configuracoes/conquistas", ["Visão Global", "Configurações", "Editar conquistas"], GLOBAL],
  ] as const)("%s em %s → %j", async (_rotulo, rota, niveis, usuario) => {
    await montar(usuario, { rota });
    expect(niveisDaTrilha()).toEqual(niveis);
  });

  it("na página inicial a trilha é só o início", async () => {
    await montar(COORDENACAO);
    expect(niveisDaTrilha()).toEqual(["Visão geral"]);
  });

  it("Secretaria na página inicial: só 'Panorama da Rede'", async () => {
    await montar(SECRETARIA);
    expect(niveisDaTrilha()).toEqual(["Panorama da Rede"]);
  });
});

describe("Navegação — atalhos de teclado (Alt+1..0)", () => {
  const teclar = (tecla: string) => fireEvent.keyDown(window, { key: tecla, altKey: true });

  it("Secretaria: Alt+1, Alt+2 e Alt+3 abrem as três áreas, na ordem do menu", async () => {
    const { espiao } = await montar(SECRETARIA, { rota: "/suporte" });
    teclar("2");
    expect(espiao.endereco).toBe("/rede/escolas");
    teclar("3");
    expect(espiao.endereco).toBe("/rede/avaliacoes-externas");
    teclar("1");
    expect(espiao.endereco).toBe("/");
  });

  it("Secretaria: as demais teclas não navegam (antes abriam Ranking, Conquistas, Assistente...)", async () => {
    const { espiao } = await montar(SECRETARIA, { rota: "/rede/escolas" });
    for (const tecla of ["4", "5", "6", "7", "8", "9", "0"]) {
      teclar(tecla);
      expect(espiao.endereco, `Alt+${tecla}`).toBe("/rede/escolas");
    }
  });

  it("coordenação: os atalhos de sempre (Alt+2 no Ranking Geral, Alt+6 nas Conquistas)", async () => {
    const { espiao } = await montar(COORDENACAO, { rota: "/turmas" });
    teclar("2");
    expect(espiao.endereco).toBe("/ranking");
    teclar("6");
    expect(espiao.endereco).toBe("/conquistas");
  });

  it("destinosDoTeclado: a Secretaria só tem as três áreas; os outros perfis, os destinos de sempre", () => {
    const AREAS = { "1": "/", "2": "/rede/escolas", "3": "/rede/avaliacoes-externas" };
    expect(destinosDoTeclado(false, true)).toEqual(AREAS);
    // Nem um cargo de administrador dá Configurações Gerais à Secretaria (RotaAdmin a barra).
    expect(destinosDoTeclado(true, true)).toEqual(AREAS);
    expect(destinosDoTeclado(false)).toMatchObject({ "1": "/", "2": "/ranking", "6": "/conquistas", "8": "/assistente" });
    expect(destinosDoTeclado(false)["0"]).toBeUndefined();
    expect(destinosDoTeclado(true)["0"]).toBe("/configuracoes");
  });
});

describe("Navegação — o cartão Contexto da Secretaria", () => {
  const ESCOLAS = [escolaFake({ id: 1, nome: "EMEF Sintética Alfa" }), escolaFake({ id: 2, nome: "EMEF Sintética Beta" })];
  const contexto = () => screen.getByRole("combobox", { name: "Contexto de visualização" });

  it("escolher uma escola leva à ficha dela e grava o contexto (as telas de escola leem dele)", async () => {
    const { espiao } = await montar(SECRETARIA, { rota: "/rede/avaliacoes-externas", escolas: ESCOLAS });
    await userEvent.selectOptions(contexto(), "2");
    expect(espiao.endereco).toBe("/rede/escolas/2");
    expect(localStorage.getItem("sgpe_escola")).toBe("2");
    expect(screen.getByTestId("cartao-escola-nome")).toHaveTextContent("EMEF Sintética Beta");
    expect(marcados()).toEqual(["/rede/escolas"]);
  });

  it.each(["/escola", "/turmas", "/turmas/7", "/professores", "/metricas", "/livros", "/simulador"])(
    "'Toda a Rede Municipal' numa tela de escola (%s) volta ao Panorama da Rede", async (rota) => {
      const { espiao } = await montar(SECRETARIA, { rota, escolas: ESCOLAS, escolaSelecionada: 1 });
      await userEvent.selectOptions(contexto(), "");
      expect(espiao.endereco).toBe("/");
      expect(localStorage.getItem("sgpe_escola")).toBeNull();
    });

  it.each(["/rede/escolas/1", "/rede/escolas", "/rede/avaliacoes-externas", "/suporte"])(
    "'Toda a Rede Municipal' fora das telas de escola (%s): fica onde está", async (rota) => {
      const { espiao } = await montar(SECRETARIA, { rota, escolas: ESCOLAS, escolaSelecionada: 1 });
      await userEvent.selectOptions(contexto(), "");
      expect(espiao.endereco).toBe(rota);
      expect(screen.getByTestId("cartao-escola-nome")).toHaveTextContent("Toda a Rede Municipal");
    });

  // O Suporte LÊ o contexto no lugar (a regra da nota da escola escolhida): escolher a escola lá
  // não leva à ficha — antes, a pessoa saía do Suporte e precisava voltar.
  it("escolher uma escola em /suporte fica no Suporte e grava o contexto", async () => {
    const { espiao } = await montar(SECRETARIA, { rota: "/suporte", escolas: ESCOLAS });
    await userEvent.selectOptions(contexto(), "2");
    expect(espiao.endereco).toBe("/suporte");
    expect(localStorage.getItem("sgpe_escola")).toBe("2");
    expect(screen.getByTestId("cartao-escola-nome")).toHaveTextContent("EMEF Sintética Beta");
  });

  // Uma escola no contexto que não está na lista do /escolas (ex.: inativa, aberta pela ficha):
  // o cartão diz que há uma escola escolhida (nunca "Toda a Rede Municipal") e voltar à rede
  // dispara a troca (antes, a opção da rede já parecia escolhida e nada acontecia).
  it("escola no contexto fora da lista: o cartão diz qual é, e 'Toda a Rede Municipal' volta ao Panorama", async () => {
    const { espiao } = await montar(SECRETARIA, { rota: "/escola", escolas: ESCOLAS, escolaSelecionada: 9 });
    await waitFor(() => expect(screen.getByTestId("cartao-escola-nome")).toHaveTextContent("Escola nº 9 (fora da lista)"));
    expect(screen.getByTestId("cartao-escola-nome")).not.toHaveTextContent("Toda a Rede Municipal");
    expect(contexto()).toHaveValue("9");
    await userEvent.selectOptions(contexto(), "");
    expect(espiao.endereco).toBe("/");
    expect(localStorage.getItem("sgpe_escola")).toBeNull();
    expect(screen.getByTestId("cartao-escola-nome")).toHaveTextContent("Toda a Rede Municipal");
    // Fora do contexto, a opção própria some (só as escolas da lista e a rede).
    expect(within(contexto()).queryByRole("option", { name: /fora da lista/ })).toBeNull();
  });

  it("coordenação: trocar de escola continua só trocando a escola (não muda de tela)", async () => {
    const { espiao } = await montar(COORDENACAO, { rota: "/turmas", escolas: ESCOLAS });
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Escola selecionada" }), "2");
    expect(espiao.endereco).toBe("/turmas");
    expect(localStorage.getItem("sgpe_escola")).toBe("2");
  });
});

describe("Navegação — barra recolhida", () => {
  const icones = () => Array.from(menu().querySelectorAll("a")).map((a) => ({
    nome: a.getAttribute("aria-label"),
    href: a.getAttribute("href"),
    icone: Array.from(a.querySelector("svg")?.classList ?? []).find((c) => c.startsWith("lucide-")),
  }));

  it.each(PERFIS)("%s: as mesmas seções do menu (um fio entre elas) e nenhum ícone repetido", async (chave, usuario) => {
    await montar(usuario, { recolhido: true });
    const lista = icones();
    const esperado = ARVORE[chave].flatMap((s) => s.itens.flatMap((n) => (typeof n === "string" ? [n] : n.itens)));
    expect(lista.map((i) => `${i.nome} → ${i.href}`)).toEqual(esperado);
    expect(menu().querySelectorAll('[data-divisoria="secao"]')).toHaveLength(ARVORE[chave].length - 1);
    const nomesDosIcones = lista.map((i) => i.icone);
    expect(nomesDosIcones.every(Boolean)).toBe(true);
    expect(new Set(nomesDosIcones).size, `ícones: ${nomesDosIcones.join(", ")}`).toBe(nomesDosIcones.length);
  });

  it("Secretaria: na ficha da escola, o ícone 'Escolas' é o único marcado", async () => {
    await montar(SECRETARIA, { rota: "/rede/escolas/3", recolhido: true });
    expect(marcados()).toEqual(["/rede/escolas"]);
  });

  it("Secretaria: no detalhe do uso das plataformas, o 'Panorama da Rede' fica marcado", async () => {
    await montar(SECRETARIA, { rota: "/rede/plataformas", recolhido: true });
    expect(icones().map((i) => i.nome)).toEqual(["Panorama da Rede", "Escolas", "Avaliações externas"]);
    expect(marcados()).toEqual(["/"]);
  });

  it("primeiro acesso da escola: só o 'Comece aqui' (antes mostrava o menu inteiro)", async () => {
    await montar(COORDENACAO, { configurada: false, recolhido: true });
    expect(icones().map((i) => i.nome)).toEqual(["Comece aqui"]);
    expect(screen.getByRole("button", { name: "Expandir menu" })).toBeInTheDocument();
  });

  it("primeiro acesso do Admin Global: 'Comece aqui' e os cadastros que não dependem da escola", async () => {
    await montar(GLOBAL, { configurada: false, recolhido: true });
    expect(icones().map((i) => i.nome)).toEqual(["Comece aqui", "Gerenciar Rede", "Escolas", "Usuários"]);
    expect(menu().querySelectorAll('[data-divisoria="secao"]')).toHaveLength(1);
  });

  it.each([
    ["admin da escola", ADMIN_ESCOLA, ["/comecar"]],
    ["coordenação", COORDENACAO, ["/comecar"]],
    ["Admin Global", GLOBAL, ["/comecar", "/rede/gerenciar", "/escolas", "/usuarios"]],
  ] as const)("primeiro acesso no menu aberto (%s): as mesmas listas da barra recolhida", async (_rotulo, usuario, esperado) => {
    await montar(usuario, { configurada: false });
    expect(hrefsDoMenu()).toEqual(esperado);
  });
});
