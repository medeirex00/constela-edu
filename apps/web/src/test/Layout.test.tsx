import { describe, expect, it } from "vitest";

import Layout from "../components/Layout";
import { ImportacaoLoteProvider } from "../context/ImportacaoLoteContext";
import { escolaFake, renderComApp, responder, screen, usuarioFake } from "./utils";

/** O Layout real vive dentro do ImportacaoLoteProvider (App.tsx). */
function LayoutReal() {
  return (
    <ImportacaoLoteProvider>
      <Layout />
    </ImportacaoLoteProvider>
  );
}

/** Escola selecionada AINDA não configurada (0 turmas → Lista Piloto não
 *  importada): é o estado em que o menu vira só "Comece aqui". */
function escolaNaoConfigurada() {
  responder("GET", "/escolas/1/sync/status", {
    escola_id: 1, escola_nome: "Escola Modelo Constela", qtd_alunos: 0, qtd_turmas: 0,
    plataformas: [], lista_piloto_importada: false, integracao_configurada: false,
  });
}

describe("Layout — menu durante o primeiro acesso (P8)", () => {
  it("mantém Estrutura (Escolas e Usuários) para o Admin Global mesmo com a escola vazia", async () => {
    escolaNaoConfigurada();
    renderComApp(<LayoutReal />, {
      rota: "/",
      usuario: usuarioFake({ is_global: true, cargo: "admin", nome: "Root" }),
      escolas: [escolaFake({ id: 1 })],
    });

    // O gate do onboarding continua ("Comece aqui" aparece)…
    expect((await screen.findAllByRole("link", { name: "Comece aqui" })).length).toBeGreaterThan(0);
    // …mas a Estrutura do Admin Global NÃO some: é por ela que o primeiro
    // coordenador de uma escola recém-criada é cadastrado.
    expect((await screen.findAllByRole("link", { name: "Usuários" })).length).toBeGreaterThan(0);
    expect((await screen.findAllByRole("link", { name: "Escolas" })).length).toBeGreaterThan(0);
    expect((await screen.findAllByRole("link", { name: "Gerenciar Rede" })).length).toBeGreaterThan(0);
    // O resto do menu (Desempenho, Gestão Escolar…) continua escondido até a
    // escola ser configurada — a exceção é SÓ a Estrutura.
    expect(screen.queryAllByRole("link", { name: "Premiações" })).toHaveLength(0);
    expect(screen.queryAllByRole("link", { name: "Turmas" })).toHaveLength(0);
  });

  it("para o admin da escola, o primeiro acesso segue restrito ao Comece aqui", async () => {
    escolaNaoConfigurada();
    renderComApp(<LayoutReal />, {
      rota: "/",
      usuario: usuarioFake({ is_global: false, cargo: "admin", nome: "Admin Local" }),
      escolas: [escolaFake({ id: 1 })],
    });

    expect((await screen.findAllByRole("link", { name: "Comece aqui" })).length).toBeGreaterThan(0);
    expect(screen.queryAllByRole("link", { name: "Usuários" })).toHaveLength(0);
    expect(screen.queryAllByRole("link", { name: "Escolas" })).toHaveLength(0);
    expect(screen.queryAllByRole("link", { name: "Premiações" })).toHaveLength(0);
  });
});

/** Escola já configurada (Lista Piloto importada): menu completo do perfil. */
function escolaConfigurada() {
  responder("GET", "/escolas/1/sync/status", {
    escola_id: 1, escola_nome: "Escola Modelo Constela", qtd_alunos: 30, qtd_turmas: 3,
    plataformas: [], lista_piloto_importada: true, integracao_configurada: true,
  });
}

describe("Layout — limpeza do menu por perfil (escola usa, não administra a matemática)", () => {
  it("coordenador vê Integrações e Pontuação, mas não Importações, Diagnóstico Elefante nem Métricas", async () => {
    escolaConfigurada();
    renderComApp(<LayoutReal />, {
      rota: "/",
      usuario: usuarioFake({ is_global: false, cargo: "coordenador", nome: "Coordenadora" }),
      escolas: [escolaFake({ id: 1 })],
    });
    expect((await screen.findAllByRole("link", { name: "Integrações" })).length).toBeGreaterThan(0);
    expect((await screen.findAllByRole("link", { name: "Pontuação" })).length).toBeGreaterThan(0);
    // A fila de revisão de identidade é operação da escola: fica ao lado de Integrações.
    expect((await screen.findAllByRole("link", { name: "Revisões de identidade" })).length).toBeGreaterThan(0);
    expect(screen.queryAllByRole("link", { name: "Importações" })).toHaveLength(0);
    expect(screen.queryAllByRole("link", { name: "Diagnóstico Elefante" })).toHaveLength(0);
    expect(screen.queryAllByRole("link", { name: "Métricas" })).toHaveLength(0);
    expect(screen.queryAllByRole("link", { name: "Ranking da Rede" })).toHaveLength(0);
  });

  it("Admin Global mantém as ferramentas avançadas e ganha Ranking da Rede", async () => {
    escolaConfigurada();
    renderComApp(<LayoutReal />, {
      rota: "/",
      usuario: usuarioFake({ is_global: true, cargo: "admin", nome: "Root" }),
      escolas: [escolaFake({ id: 1 })],
    });
    for (const nome of ["Integrações", "Importações", "Revisões de identidade", "Diagnóstico Elefante", "Métricas", "Ranking da Rede", "Ranking Geral"]) {
      expect((await screen.findAllByRole("link", { name: nome })).length, nome).toBeGreaterThan(0);
    }
  });
});

describe("Layout — trilha do topo por perfil", () => {
  it("em /metricas a escola vê 'Pontuação' na trilha (o mesmo nome do menu), não 'Métricas'", async () => {
    escolaConfigurada();
    renderComApp(<LayoutReal />, {
      rota: "/metricas",
      usuario: usuarioFake({ is_global: false, cargo: "coordenador", nome: "Coordenadora" }),
      escolas: [escolaFake({ id: 1 })],
    });
    const trilha = await screen.findByRole("navigation", { name: "Trilha de navegação" });
    expect(trilha).toHaveTextContent("Pontuação");
    expect(trilha).not.toHaveTextContent("Métricas");
  });

  it("em /metricas o Admin Global vê 'Métricas' na trilha", async () => {
    escolaConfigurada();
    renderComApp(<LayoutReal />, {
      rota: "/metricas",
      usuario: usuarioFake({ is_global: true, cargo: "admin", nome: "Root" }),
      escolas: [escolaFake({ id: 1 })],
    });
    const trilha = await screen.findByRole("navigation", { name: "Trilha de navegação" });
    expect(trilha).toHaveTextContent("Métricas");
  });
});
