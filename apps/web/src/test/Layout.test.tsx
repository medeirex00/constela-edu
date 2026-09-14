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
