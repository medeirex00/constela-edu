/**
 * Menu e trilha do Layout por perfil.
 *
 * O Layout aparece na tela ANTES de a sessão abrir: até o /auth/me responder, o
 * perfil é vazio (menu e trilha de quem não é gestor) e, até o /sync/onboarding
 * responder, a escola ainda não sabe se precisa do "Comece aqui". Cada teste espera
 * o ESTADO FINAL que vai conferir — com uma consulta por TEXTO, barata — e só então
 * faz as consultas por papel, uma vez cada.
 *
 * Por que não `findAllByRole` direto: com a suíte inteira em paralelo, cada
 * `*ByRole` sobre o menu inteiro custa de 30 a 130 ms (calcula a árvore de
 * acessibilidade, com getComputedStyle, elemento por elemento) e o `findBy*` refaz a
 * consulta a cada mutação do DOM — nas três renderizações seguidas do Layout, a
 * espera passava de 1 s (medido: 577–1129 ms com 3 suítes ao mesmo tempo, contra
 * 196–451 ms esperando pelo texto). E a trilha, achada no 1º render, era conferida
 * antes da sessão: com um /auth/me 30 ms mais lento, o Admin Global "via" Pontuação.
 */
import { useNavigate } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import Layout from "../components/Layout";
import { ImportacaoLoteProvider } from "../context/ImportacaoLoteContext";
import type { Usuario } from "../lib/types";
import { corDoAvatar } from "../components/ui";
import { act, autenticar, escolaFake, fireEvent, renderComApp, responder, screen, userEvent, usuarioFake, within } from "./utils";

/** O Layout real vive dentro do ImportacaoLoteProvider (App.tsx). */
function LayoutReal() {
  return (
    <ImportacaoLoteProvider>
      <Layout />
    </ImportacaoLoteProvider>
  );
}

/** A sessão abriu: o nome do usuário apareceu no menu do topo. */
async function sessaoAberta(usuario: Usuario) {
  await screen.findAllByText(usuario.nome);
}

/** Links do menu com este nome (uma consulta por papel, já no estado final). */
const links = (nome: string) => screen.queryAllByRole("link", { name: nome });

/** Os níveis da trilha, em ordem: Início › [contexto ›] página. */
const niveisDaTrilha = (trilha: HTMLElement) =>
  Array.from(trilha.querySelectorAll("a, span")).map((el) => el.textContent);

/** Monta o Layout com o /auth/me respondendo só depois de `ms` — a janela em que a
 *  tela já existe sem usuário fica determinística (não depende da carga da máquina). */
function montarComSessaoLenta(usuario: Usuario, rota: string, ms = 40) {
  autenticar(usuario, [escolaFake({ id: 1 })]);
  responder("GET", "/auth/me", () => new Promise((ok) => setTimeout(() => ok(usuario), ms)));
  renderComApp(<LayoutReal />, { rota, autenticado: false });
}

/** Escola selecionada AINDA não configurada (0 turmas → Lista Piloto não
 *  importada): é o estado em que o menu vira só "Comece aqui". */
function escolaNaoConfigurada(atrasoMs = 0) {
  const corpo = { lista_piloto_importada: false };
  responder("GET", "/escolas/1/sync/onboarding",
    atrasoMs ? () => new Promise((ok) => setTimeout(() => ok(corpo), atrasoMs)) : corpo);
}

describe("Layout — menu durante o primeiro acesso (P8)", () => {
  it("mantém Gerenciar Rede, Escolas e Usuários para o Admin Global mesmo com a escola vazia", async () => {
    escolaNaoConfigurada();
    renderComApp(<LayoutReal />, {
      rota: "/",
      usuario: usuarioFake({ is_global: true, cargo: "admin", nome: "Root" }),
      escolas: [escolaFake({ id: 1 })],
    });

    // Estado final: sessão aberta E status da escola lido ("Comece aqui" só existe aí).
    await screen.findAllByText("Comece aqui");
    expect(links("Comece aqui").length).toBeGreaterThan(0);
    // …mas os cadastros do Admin Global NÃO somem: é por eles que o primeiro
    // coordenador de uma escola recém-criada é cadastrado.
    expect(links("Usuários").length).toBeGreaterThan(0);
    expect(links("Escolas").length).toBeGreaterThan(0);
    expect(links("Gerenciar Rede").length).toBeGreaterThan(0);
    // O resto do menu (Reconhecimento, Gestão escolar…) continua escondido até a
    // escola ser configurada — a exceção é SÓ Gerenciar Rede, Escolas e Usuários.
    expect(links("Premiações")).toHaveLength(0);
    expect(links("Turmas")).toHaveLength(0);
  });

  it("para o admin da escola, o primeiro acesso segue restrito ao Comece aqui", async () => {
    escolaNaoConfigurada();
    renderComApp(<LayoutReal />, {
      rota: "/",
      usuario: usuarioFake({ is_global: false, cargo: "admin", nome: "Admin Local" }),
      escolas: [escolaFake({ id: 1 })],
    });

    await screen.findAllByText("Comece aqui");
    expect(links("Comece aqui").length).toBeGreaterThan(0);
    expect(links("Usuários")).toHaveLength(0);
    expect(links("Escolas")).toHaveLength(0);
    expect(links("Premiações")).toHaveLength(0);
  });

  it("sessão e status lentos: o menu só vira 'Comece aqui' quando os dois chegam", async () => {
    // As duas respostas atrasadas (rede real): antes delas o Layout já está na tela
    // e o teste não pode concluir nada; depois, o mesmo estado do 1º teste.
    escolaNaoConfigurada(40);
    montarComSessaoLenta(usuarioFake({ is_global: true, cargo: "admin", nome: "Root" }), "/");
    expect(links("Comece aqui")).toHaveLength(0);
    await screen.findAllByText("Comece aqui");
    expect(links("Usuários").length).toBeGreaterThan(0);
    expect(links("Premiações")).toHaveLength(0);
  });
});

/** Escola já configurada (Lista Piloto importada): menu completo do perfil. */
function escolaConfigurada() {
  responder("GET", "/escolas/1/sync/onboarding", { lista_piloto_importada: true });
}

describe("Layout — limpeza do menu por perfil (escola usa, não administra a matemática)", () => {
  // D4 (identidade v2): "Pontuação" (escola) e "Métricas" (global) passaram a "Critérios"
  // no menu — a rota /metricas é a mesma; os nomes antigos não aparecem mais.
  it("coordenador vê Integrações e Critérios, mas não Importações, Diagnóstico Elefante nem Métricas", async () => {
    escolaConfigurada();
    const coordenadora = usuarioFake({ is_global: false, cargo: "coordenador", nome: "Coordenadora" });
    renderComApp(<LayoutReal />, { rota: "/", usuario: coordenadora, escolas: [escolaFake({ id: 1 })] });
    await sessaoAberta(coordenadora);
    expect(links("Integrações").length).toBeGreaterThan(0);
    expect(links("Critérios").length).toBeGreaterThan(0);
    expect(links("Critérios")[0]).toHaveAttribute("href", "/metricas");
    expect(links("Pontuação")).toHaveLength(0);
    // A fila de revisão de identidade é operação da escola: fica ao lado de Integrações.
    expect(links("Revisões de identidade").length).toBeGreaterThan(0);
    expect(links("Importações")).toHaveLength(0);
    expect(links("Diagnóstico Elefante")).toHaveLength(0);
    expect(links("Métricas")).toHaveLength(0);
    expect(links("Ranking da Rede")).toHaveLength(0);
  });

  it("Admin Global mantém as ferramentas avançadas e ganha Ranking da Rede", async () => {
    escolaConfigurada();
    const root = usuarioFake({ is_global: true, cargo: "admin", nome: "Root" });
    renderComApp(<LayoutReal />, { rota: "/", usuario: root, escolas: [escolaFake({ id: 1 })] });
    await sessaoAberta(root);
    for (const nome of ["Integrações", "Importações", "Revisões de identidade", "Diagnóstico Elefante", "Critérios", "Ranking da Rede", "Ranking Geral"]) {
      expect(links(nome).length, nome).toBeGreaterThan(0);
    }
    expect(links("Critérios")[0]).toHaveAttribute("href", "/metricas");
    expect(links("Métricas")).toHaveLength(0);
  });
});

describe("Layout — trilha do topo por perfil", () => {
  it("em /metricas a escola vê 'Visão geral › Regras de pontuação › Critérios' (o mesmo nome do menu)", async () => {
    escolaConfigurada();
    const coordenadora = usuarioFake({ is_global: false, cargo: "coordenador", nome: "Coordenadora" });
    renderComApp(<LayoutReal />, { rota: "/metricas", usuario: coordenadora, escolas: [escolaFake({ id: 1 })] });
    await sessaoAberta(coordenadora);
    const trilha = screen.getByRole("navigation", { name: "Trilha de navegação" });
    // A PÁGINA se chama "Critérios" (D4); "Regras de pontuação" é o grupo do menu
    // (nível do meio) — o nome antigo da página ("Pontuação") não volta.
    expect(niveisDaTrilha(trilha)).toEqual(["Visão geral", "Regras de pontuação", "Critérios"]);
    expect(within(trilha).queryByText("Pontuação")).toBeNull();
    expect(trilha).not.toHaveTextContent("Métricas");
  });

  it("em /metricas o Admin Global vê 'Visão Global › Configurações › Critérios' na trilha", async () => {
    escolaConfigurada();
    const root = usuarioFake({ is_global: true, cargo: "admin", nome: "Root" });
    renderComApp(<LayoutReal />, { rota: "/metricas", usuario: root, escolas: [escolaFake({ id: 1 })] });
    await sessaoAberta(root);
    const trilha = screen.getByRole("navigation", { name: "Trilha de navegação" });
    expect(niveisDaTrilha(trilha)).toEqual(["Visão Global", "Configurações", "Critérios"]);
    expect(trilha).not.toHaveTextContent("Métricas");
  });

  it("com o /auth/me lento, a trilha do Admin Global ainda termina em 'Importações e fontes'", async () => {
    // A corrida que a carga da máquina revelava, agora fixa: a trilha existe desde o
    // 1º render e só muda quando a sessão abre. Com a D4, /metricas tem o mesmo nome
    // para os dois perfis; a rota cujo nome na trilha DEPENDE do perfil é
    // /rede/avaliacoes ("Fontes dos indicadores" × "Importações e fontes" do global).
    escolaConfigurada();
    const root = usuarioFake({ is_global: true, cargo: "admin", nome: "Root" });
    montarComSessaoLenta(root, "/rede/avaliacoes");
    const trilha = screen.getByRole("navigation", { name: "Trilha de navegação" });
    expect(trilha).not.toHaveTextContent("Importações e fontes");
    expect(trilha).not.toHaveTextContent("Visão Global");
    await sessaoAberta(root);
    expect(trilha).toHaveTextContent("Importações e fontes");
    expect(trilha).toHaveTextContent("Visão Global");
  });
});

describe("Layout — teclado e leitor de tela", () => {
  async function montarCoordenacao() {
    escolaConfigurada();
    const coordenadora = usuarioFake({ is_global: false, cargo: "coordenador", nome: "Coordenadora" });
    renderComApp(<LayoutReal />, { rota: "/", usuario: coordenadora, escolas: [escolaFake({ id: 1 })] });
    await sessaoAberta(coordenadora);
  }

  it("o 1º Tab é o 'Pular para o conteúdo', que leva o foco ao <main> sem mudar o endereço", async () => {
    await montarCoordenacao();
    const user = userEvent.setup();
    await user.tab();
    const pular = screen.getByRole("link", { name: "Pular para o conteúdo" });
    expect(pular).toHaveFocus();
    await user.click(pular);
    const main = screen.getByRole("main");
    expect(main).toHaveAttribute("id", "conteudo");
    expect(main).toHaveFocus();
    expect(window.location.hash).toBe("");
  });

  it("grupo fechado fica fora do Tab (invisible) e o botão aponta para o painel dele", async () => {
    await montarCoordenacao();
    const botao = screen.getByRole("button", { name: "Acompanhamento" });
    expect(botao).toHaveAttribute("aria-expanded", "false");
    const painel = document.getElementById(botao.getAttribute("aria-controls") ?? "");
    expect(painel).not.toBeNull();
    // Sem o CSS no jsdom, a classe é a prova; no navegador o e2e da análise confere o Tab.
    expect(painel).toHaveClass("invisible");
    // As plataformas ficam no acompanhamento pedagógico (Integrações é de "Dados e integrações").
    expect(painel).toContainElement(screen.getAllByRole("link", { name: "Matific" })[0]);
    await userEvent.click(botao);
    expect(botao).toHaveAttribute("aria-expanded", "true");
    expect(painel).not.toHaveClass("invisible");
  });

  it("gaveta do celular: diálogo modal, foco dentro, Tab preso e Esc devolve o foco", async () => {
    await montarCoordenacao();
    const user = userEvent.setup();
    const abrir = screen.getByRole("button", { name: "Abrir menu" });
    expect(abrir).toHaveAttribute("aria-expanded", "false");
    await user.click(abrir);
    const dialogo = screen.getByRole("dialog", { name: "Menu de navegação" });
    expect(dialogo).toHaveAttribute("aria-modal", "true");
    expect(dialogo).toContainElement(document.activeElement as HTMLElement);
    // Um só "Fechar menu" acessível (o véu de fundo saiu do Tab e da árvore).
    expect(screen.getAllByRole("button", { name: "Fechar menu" })).toHaveLength(1);
    // Shift+Tab no 1º elemento volta para o último DA GAVETA (não para o topo da página).
    await user.tab({ shift: true });
    expect(dialogo).toContainElement(document.activeElement as HTMLElement);
    await user.tab();
    expect(dialogo).toContainElement(document.activeElement as HTMLElement);
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(abrir).toHaveFocus();
  });

  it("menu do usuário aberto DENTRO da gaveta: o 1º Esc fecha só o menu, o 2º fecha a gaveta", async () => {
    // Os dois ouvintes ficam no document; sem a captura + preventDefault do menu, o
    // Esc fechava a gaveta inteira junto (e o foco ia parar no "Abrir menu").
    await montarCoordenacao();
    const user = userEvent.setup();
    const abrir = screen.getByRole("button", { name: "Abrir menu" });
    await user.click(abrir);
    const dialogo = screen.getByRole("dialog", { name: "Menu de navegação" });
    const menu = within(dialogo).getByRole("button", { name: "Menu do usuário" });
    await user.click(menu);
    expect(menu).toHaveAttribute("aria-expanded", "true");
    expect(within(dialogo).getByRole("menuitem", { name: "Sair" })).toBeInTheDocument();

    await user.keyboard("{Escape}");
    expect(within(dialogo).queryByRole("menuitem", { name: "Sair" })).toBeNull();
    expect(screen.getByRole("dialog", { name: "Menu de navegação" })).toBe(dialogo);
    expect(menu).toHaveFocus();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(abrir).toHaveFocus();
  });

  it("gaveta aberta e a rota muda por fora dos links do menu ('Minha conta', atalho Alt+N): a gaveta fecha", async () => {
    // Só os links do menu fechavam a gaveta (`aoNavegar`): "Minha conta", no menu do
    // usuário, trocava a página com o diálogo modal ainda por cima — rolagem do fundo
    // travada e Tab preso nele até um "Fechar menu" ou Esc.
    await montarCoordenacao();
    const user = userEvent.setup();
    const abrir = screen.getByRole("button", { name: "Abrir menu" });
    const trilha = () => screen.getByRole("navigation", { name: "Trilha de navegação" });
    await user.click(abrir);
    const dialogo = screen.getByRole("dialog", { name: "Menu de navegação" });
    await user.click(within(dialogo).getByRole("button", { name: "Menu do usuário" }));
    await user.click(within(dialogo).getByRole("menuitem", { name: "Minha conta" }));
    expect(niveisDaTrilha(trilha())).toEqual(["Visão geral", "Minha conta"]);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.body.style.overflow).toBe("");
    expect(abrir).toHaveFocus();                          // o mesmo destino do foco de qualquer fechamento

    // Atalho de teclado com a gaveta aberta mudando SÓ a consulta (/ranking → ?ver=evolucao).
    await user.keyboard("{Alt>}2{/Alt}");
    expect(niveisDaTrilha(trilha())).toEqual(["Visão geral", "Reconhecimento", "Ranking Geral"]);
    await user.click(abrir);
    expect(screen.getByRole("dialog", { name: "Menu de navegação" })).toBeInTheDocument();
    await user.keyboard("{Alt>}3{/Alt}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.body.style.overflow).toBe("");
  });

  it("a própria página reescrevendo a consulta (navegação REPLACE) não fecha a gaveta que a pessoa abriu", async () => {
    // Ex.: a análise grava `?escola=` quando os dados chegam — a pessoa não foi a lugar
    // nenhum; fechar a gaveta que ela acabou de abrir seria um "pisca" sem motivo.
    function ReescreveConsulta() {
      const navegar = useNavigate();
      return <button type="button" onClick={() => navegar("/?escola=1", { replace: true })}>reescrever-consulta</button>;
    }
    escolaConfigurada();
    const coordenadora = usuarioFake({ is_global: false, cargo: "coordenador", nome: "Coordenadora" });
    renderComApp(<><LayoutReal /><ReescreveConsulta /></>, { rota: "/", usuario: coordenadora, escolas: [escolaFake({ id: 1 })] });
    await sessaoAberta(coordenadora);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Abrir menu" }));
    fireEvent.click(screen.getByText("reescrever-consulta"));
    expect(screen.getByRole("dialog", { name: "Menu de navegação" })).toBeInTheDocument();
  });

  it("gaveta aberta e a tela passa a 1280 px (alargar a janela): a gaveta fecha e solta o Tab e a rolagem", async () => {
    // A barra lateral fixa só existe a partir de 1280 px (`xl`); entre 1024 e 1279 a
    // navegação fica na gaveta. No navegador a gaveta vira display:none (`xl:hidden`)
    // nessa largura; aberta, a trava do Tab mandava o foco para links invisíveis e
    // nenhum Tab andava.
    const original = window.matchMedia;
    const ouvintes = new Set<() => void>();
    let desktop = false;
    window.matchMedia = ((consulta: string) => (consulta === "(min-width: 1280px)"
      ? {
        get matches() { return desktop; },
        media: consulta,
        addEventListener: (_t: string, fn: () => void) => { ouvintes.add(fn); },
        removeEventListener: (_t: string, fn: () => void) => { ouvintes.delete(fn); },
      }
      : original(consulta))) as typeof window.matchMedia;
    try {
      await montarCoordenacao();
      const user = userEvent.setup();
      await user.click(screen.getByRole("button", { name: "Abrir menu" }));
      expect(screen.getByRole("dialog", { name: "Menu de navegação" })).toBeInTheDocument();
      expect(document.body.style.overflow).toBe("hidden");
      desktop = true;
      act(() => { for (const fn of [...ouvintes]) fn(); });
      expect(screen.queryByRole("dialog")).toBeNull();
      expect(document.body.style.overflow).toBe("");
      expect(ouvintes.size).toBe(0);                      // parou de ouvir a largura
      // O Tab volta a andar pela página (antes: preventDefault + foco num link escondido).
      const antes = document.activeElement;
      await user.tab();
      expect(document.activeElement).not.toBe(antes);
    } finally {
      window.matchMedia = original;
    }
  });

  it("nenhum botão só com ícone fica sem nome acessível", async () => {
    await montarCoordenacao();
    const semNome = screen.queryAllByRole("button", { name: (nome) => nome.trim() === "" });
    expect(semNome.map((b) => b.outerHTML.slice(0, 80))).toEqual([]);
    expect(screen.getByRole("button", { name: "Notificações" })).toHaveAttribute("aria-expanded", "false");
  });
});

describe("Layout — identidade v2: seções, rótulos, selo e rodapé da barra", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("coordenação: seções Escola e Gestão, 'Visão geral' no topo, Usuários em Minha Escola e Critérios em Gestão", async () => {
    escolaConfigurada();
    const coordenadora = usuarioFake({ is_global: false, cargo: "coordenador", nome: "Coordenadora" });
    renderComApp(<LayoutReal />, { rota: "/", usuario: coordenadora, escolas: [escolaFake({ id: 1 })] });
    await sessaoAberta(coordenadora);
    const escola = screen.getByRole("group", { name: "Escola" });
    const gestao = screen.getByRole("group", { name: "Gestão" });
    expect(within(escola).getByRole("link", { name: "Visão geral" })).toHaveAttribute("href", "/");
    expect(within(escola).getByRole("link", { name: "Premiações" })).toHaveAttribute("href", "/premiacoes");
    expect(within(escola).getByRole("link", { name: "Usuários" })).toHaveAttribute("href", "/usuarios");
    expect(within(gestao).queryByRole("link", { name: "Usuários" })).toBeNull();
    expect(within(gestao).getByRole("link", { name: "Critérios" })).toHaveAttribute("href", "/metricas");
    expect(within(gestao).getByRole("link", { name: "Integrações" })).toHaveAttribute("href", "/sincronizacao");
    expect(within(gestao).getByRole("button", { name: "Dados e integrações" })).toBeInTheDocument();
    // "Projeto" (a seção fixa antiga) não existe mais para ninguém.
    expect(screen.queryByRole("group", { name: "Projeto" })).toBeNull();
    // O nome antigo da página inicial saiu do menu e da trilha.
    expect(screen.queryAllByRole("link", { name: /Dashboard/ })).toHaveLength(0);
  });

  it("professor: seções Minhas turmas e Reconhecimento, com 'Visão geral' (era 'Meu Dashboard')", async () => {
    escolaConfigurada();
    const professora = usuarioFake({ is_global: false, cargo: "professor", nome: "Professora" });
    renderComApp(<LayoutReal />, { rota: "/", usuario: professora, escolas: [escolaFake({ id: 1 })] });
    await sessaoAberta(professora);
    const turmas = screen.getByRole("group", { name: "Minhas turmas" });
    expect(within(turmas).getByRole("link", { name: "Visão geral" })).toHaveAttribute("href", "/");
    expect(within(turmas).getByRole("link", { name: "Meus Relatórios" })).toBeInTheDocument();
    expect(within(screen.getByRole("group", { name: "Reconhecimento" })).getByRole("link", { name: "Ranking" }))
      .toHaveAttribute("href", "/ranking");
    expect(screen.queryByRole("group", { name: "Gestão" })).toBeNull();
    expect(links("Critérios")).toHaveLength(0);
  });

  it("Admin Global continua com 'Visão Global' (não vira 'Visão geral')", async () => {
    escolaConfigurada();
    const root = usuarioFake({ is_global: true, cargo: "admin", nome: "Root" });
    renderComApp(<LayoutReal />, { rota: "/", usuario: root, escolas: [escolaFake({ id: 1 })] });
    await sessaoAberta(root);
    expect(links("Visão Global")[0]).toHaveAttribute("href", "/");
    expect(links("Visão geral")).toHaveLength(0);
  });

  it("a Secretaria continua com 'Panorama da Rede', sem a seção Gestão e com o contexto da rede", async () => {
    escolaConfigurada();
    const secretaria = usuarioFake({ nome: "Equipe SEDUC", cargo: "coordenador", rede_id: 1, escola_id: null });
    renderComApp(<LayoutReal />, { rota: "/", usuario: secretaria, escolas: [escolaFake({ id: 1 })] });
    await sessaoAberta(secretaria);
    expect(links("Panorama da Rede")[0]).toHaveAttribute("href", "/");
    expect(screen.queryByRole("group", { name: "Gestão" })).toBeNull();
    // Uma seção só, com as três áreas soltas (DESENHO3 §1) — sem acordeão nenhum.
    expect(screen.getAllByRole("group").map((g) => g.getAttribute("aria-labelledby"))
      .map((id) => document.getElementById(id ?? "")?.textContent))
      .toEqual(["Rede municipal"]);
    const rede = screen.getByRole("group", { name: "Rede municipal" });
    expect(within(rede).getAllByRole("link").map((l) => l.textContent))
      .toEqual(["Panorama da Rede", "Escolas", "Avaliações externas"]);
    expect(screen.queryByRole("button", { name: "Análises avançadas" })).toBeNull();
    expect(screen.queryByRole("group", { name: "Inteligência pedagógica" })).toBeNull();
    // O seletor de contexto da Secretaria (no cartão do rodapé) mantém a rede inteira.
    const contexto = screen.getByRole("combobox", { name: "Contexto de visualização" });
    expect(within(contexto).getByRole("option", { name: /Toda a Rede Municipal/ })).toBeInTheDocument();
  });

  it("selo de Premiações: dias até o fim do bimestre como DESCRIÇÃO, sem mudar o nome do link", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date(2026, 9, 31, 10));          // 4º bimestre: 05/10 a 31/12
    escolaConfigurada();
    const coordenadora = usuarioFake({ is_global: false, cargo: "coordenador", nome: "Coordenadora" });
    renderComApp(<LayoutReal />, { rota: "/", usuario: coordenadora, escolas: [escolaFake({ id: 1 })] });
    await sessaoAberta(coordenadora);
    const premiacoes = screen.getByRole("link", { name: "Premiações" });
    expect(premiacoes).toHaveAccessibleDescription("Fim do 4º bimestre em 61 dias");
    expect(premiacoes).toHaveTextContent("61d");
  });

  it("fora do calendário de bimestres não há selo (nunca um número inventado)", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date(2027, 0, 15, 10));          // ano sem calendário cadastrado
    escolaConfigurada();
    const coordenadora = usuarioFake({ is_global: false, cargo: "coordenador", nome: "Coordenadora" });
    renderComApp(<LayoutReal />, { rota: "/", usuario: coordenadora, escolas: [escolaFake({ id: 1 })] });
    await sessaoAberta(coordenadora);
    const premiacoes = screen.getByRole("link", { name: "Premiações" });
    expect(premiacoes).not.toHaveAttribute("aria-describedby");
    expect(premiacoes).toHaveTextContent(/^Premiações$/);
  });

  it("rodapé da barra: cartão da escola (mesmo select) e cartão do usuário que abre o menu com Sair", async () => {
    escolaConfigurada();
    const coordenadora = usuarioFake({ is_global: false, cargo: "coordenador", nome: "Coordenadora" });
    renderComApp(<LayoutReal />, {
      rota: "/",
      usuario: coordenadora,
      escolas: [escolaFake({ id: 1, nome: "EMEF Sintética Alfa" }), escolaFake({ id: 2, nome: "EMEF Sintética Beta" })],
    });
    await sessaoAberta(coordenadora);
    const escola = screen.getByRole("combobox", { name: "Escola selecionada" });
    expect(within(escola).getAllByRole("option").map((o) => o.textContent)).toEqual([
      "EMEF Sintética Alfa", "EMEF Sintética Beta",
    ]);
    const menu = screen.getByRole("button", { name: "Menu do usuário" });
    expect(menu).toHaveTextContent("Coordenação");
    expect(menu).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(menu);
    expect(menu).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("menuitem", { name: "Sair" })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "Minha conta" })).toHaveAttribute("href", "/minha-conta");
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("menuitem", { name: "Sair" })).toBeNull();
    expect(menu).toHaveFocus();
  });

  it("a pesquisa global acha a página renomeada também pelo nome antigo", async () => {
    escolaConfigurada();
    const coordenadora = usuarioFake({ is_global: false, cargo: "coordenador", nome: "Coordenadora" });
    renderComApp(<LayoutReal />, { rota: "/", usuario: coordenadora, escolas: [escolaFake({ id: 1 })] });
    await sessaoAberta(coordenadora);
    await userEvent.type(screen.getByRole("textbox", { name: /Pesquisar páginas/ }), "pontua");
    const opcao = await screen.findByRole("button", { name: /Critérios/ });
    expect(opcao).toHaveTextContent("Página");
  });
});

describe("Layout — casca: rolagem do menu, trilha, cartão da escola e avatar", () => {
  /** Simula a lista do menu com `altura` px visíveis de `total` px, rolada em `topo`. */
  function rolarLista(lista: HTMLElement, { total, altura, topo }: { total: number; altura: number; topo: number }) {
    Object.defineProperty(lista, "scrollHeight", { configurable: true, value: total });
    Object.defineProperty(lista, "clientHeight", { configurable: true, value: altura });
    lista.scrollTop = topo;
    fireEvent.scroll(lista);
  }

  it("esmaecidos do menu só aparecem do lado em que há itens escondidos", async () => {
    escolaConfigurada();
    const coordenadora = usuarioFake({ is_global: false, cargo: "coordenador", nome: "Coordenadora" });
    renderComApp(<LayoutReal />, { rota: "/", usuario: coordenadora, escolas: [escolaFake({ id: 1 })] });
    await sessaoAberta(coordenadora);
    const lista = screen.getByRole("navigation", { name: "Menu principal" });
    const topo = lista.querySelector('[data-degrade="topo"]');
    const base = lista.querySelector('[data-degrade="base"]');
    expect(topo).toHaveAttribute("aria-hidden", "true");
    expect(base).toHaveAttribute("aria-hidden", "true");
    // Tudo cabe: nenhum esmaecido.
    expect(topo).toHaveAttribute("data-visivel", "nao");
    expect(base).toHaveAttribute("data-visivel", "nao");

    act(() => rolarLista(lista, { total: 900, altura: 600, topo: 0 }));     // há mais abaixo
    expect(topo).toHaveAttribute("data-visivel", "nao");
    expect(base).toHaveAttribute("data-visivel", "sim");

    act(() => rolarLista(lista, { total: 900, altura: 600, topo: 150 }));   // no meio
    expect(topo).toHaveAttribute("data-visivel", "sim");
    expect(base).toHaveAttribute("data-visivel", "sim");

    act(() => rolarLista(lista, { total: 900, altura: 600, topo: 300 }));   // no fim
    expect(topo).toHaveAttribute("data-visivel", "sim");
    expect(base).toHaveAttribute("data-visivel", "nao");
  });

  it("trilha: os três níveis (início, contexto e página) levam o texto inteiro no title", async () => {
    escolaConfigurada();
    const secretaria = usuarioFake({ nome: "Equipe SEDUC", cargo: "coordenador", rede_id: 1, escola_id: null });
    renderComApp(<LayoutReal />, { rota: "/rede/escolas/3", usuario: secretaria, escolas: [escolaFake({ id: 1 })] });
    await sessaoAberta(secretaria);
    const trilha = screen.getByRole("navigation", { name: "Trilha de navegação" });
    expect(within(trilha).getByRole("link", { name: "Panorama da Rede" })).toHaveAttribute("title", "Panorama da Rede");
    // A ficha de uma escola: dentro da área "Escolas", na seção "Rede municipal".
    expect(within(trilha).getByText("Rede municipal")).toHaveAttribute("title", "Rede municipal");
    expect(within(trilha).getByText("Ficha da escola")).toHaveAttribute("title", "Ficha da escola");
  });

  it("cartão da Secretaria: 'Toda a Rede Municipal' sem emoji no texto, nome à vista e no title", async () => {
    escolaConfigurada();
    const secretaria = usuarioFake({ nome: "Equipe SEDUC", cargo: "coordenador", rede_id: 1, escola_id: null });
    renderComApp(<LayoutReal />, { rota: "/", usuario: secretaria, escolas: [escolaFake({ id: 1 })] });
    await sessaoAberta(secretaria);
    const contexto = screen.getByRole("combobox", { name: "Contexto de visualização" });
    expect(within(contexto).getByRole("option", { name: "Toda a Rede Municipal" })).toHaveTextContent(/^Toda a Rede Municipal$/);
    expect(contexto).toHaveAttribute("title", "Toda a Rede Municipal");
    expect(screen.getByTestId("cartao-escola-nome")).toHaveTextContent(/^Toda a Rede Municipal$/);
  });

  it("cartão da escola: o nome inteiro aparece (até 2 linhas) e o select continua o mesmo controle", async () => {
    escolaConfigurada();
    const coordenadora = usuarioFake({ is_global: false, cargo: "coordenador", nome: "Coordenadora" });
    const nomeLongo = "EMEF Sintética Professora Maria Aparecida de Souza";
    renderComApp(<LayoutReal />, {
      rota: "/", usuario: coordenadora,
      escolas: [escolaFake({ id: 1, nome: nomeLongo }), escolaFake({ id: 2, nome: "EMEF Sintética Beta" })],
    });
    await sessaoAberta(coordenadora);
    const escola = screen.getByRole("combobox", { name: "Escola selecionada" });
    expect(escola).toHaveValue("1");
    expect(escola).toHaveAttribute("title", nomeLongo);
    expect(screen.getByTestId("cartao-escola-nome")).toHaveTextContent(nomeLongo);
  });

  it("avatar do cartão do usuário usa a cor da chave = id (a mesma de Minha conta, Usuários e Sessões)", async () => {
    escolaConfigurada();
    const coordenadora = usuarioFake({ id: 42, is_global: false, cargo: "coordenador", nome: "Coordenadora Teste" });
    renderComApp(<LayoutReal />, { rota: "/", usuario: coordenadora, escolas: [escolaFake({ id: 1 })] });
    await sessaoAberta(coordenadora);
    const menu = screen.getByRole("button", { name: "Menu do usuário" });
    expect(within(menu).getByText("CT")).toHaveClass(corDoAvatar(42));
  });
});
