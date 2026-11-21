/**
 * Limites do ajuste manual e do catálogo no cliente (G_AJUSTE-7).
 *
 * No PostgreSQL, um número que não cabe na coluna (dígitos a mais) ou um texto maior
 * que a coluna virava "Erro interno" sem dizer o campo. O servidor agora recusa com
 * 422; a tela barra antes, em português, dizendo qual campo e qual o limite — e os
 * campos de texto do livro não deixam passar do tamanho da coluna. Dados fictícios.
 */
import { describe, expect, it } from "vitest";

import Elefante from "../pages/Elefante";
import Livros from "../pages/Livros";
import Matific from "../pages/Matific";
import { api, renderComApp, responder, screen, userEvent, usuarioFake } from "./utils";

const ADMIN_GLOBAL = usuarioFake({ id: 99, nome: "Admin Fictício", is_global: true, cargo: "admin" });

function chamadas(metodo: string, caminho: string) {
  return api.mock.calls.filter(
    ([c, opcoes]) => c === caminho && (opcoes as RequestInit | undefined)?.method === metodo,
  );
}

describe("Limites no cliente: ajuste manual e catálogo", () => {
  it("Matific: atividades com dígitos a mais são barradas em português, sem chamar a API", async () => {
    const u = userEvent.setup();
    responder("GET", "/escolas/1/matific", [{
      aluno_id: 10, nome: "Lia Fictícia Rocha", turma: "3º Ano A", ano_escolar: "3º Ano",
      atividades: 10, estrelas: 40, pontuacao_media: 4, data_referencia: null,
    }]);
    renderComApp(<Matific />, { rota: "/matific" });
    await u.click(await screen.findByRole("button", { name: "Editar dados de Lia Fictícia Rocha" }));
    const atividades = await screen.findByLabelText("Atividades finalizadas");
    await u.clear(atividades);
    await u.type(atividades, "3000000000");
    await u.type(screen.getByLabelText(/Motivo da edição/), "correção do relatório");
    await u.click(screen.getByRole("button", { name: "Salvar e recalcular" }));

    expect(await screen.findByText(/O número de atividades é grande demais/)).toBeInTheDocument();
    expect(chamadas("PUT", "/escolas/1/matific/10")).toHaveLength(0);
  });

  it("Elefante: tempo de leitura com dígitos a mais é barrado em português, sem chamar a API", async () => {
    const u = userEvent.setup();
    responder("GET", "/escolas/1/elefante", [{
      aluno_id: 5, nome: "Téo Fictício Lima", turma: "3º Ano A", ano_escolar: "3º Ano",
      livros_unicos: 3, tempo_leitura_min: 90, questoes_tentativas: 20, questoes_acertos: 15,
      livros_por_nivel: { AA: 2, D: 1 }, data_referencia: null,
    }]);
    responder("GET", "/escolas/1/configuracoes/dificuldade", { niveis: [] });
    renderComApp(<Elefante />, { rota: "/elefante" });
    await u.click(await screen.findByRole("button", { name: "Editar dados de Téo Fictício Lima" }));
    const tempo = await screen.findByLabelText("Tempo de leitura (minutos)");
    await u.clear(tempo);
    await u.type(tempo, "3000000000");
    await u.type(screen.getByLabelText(/Motivo da edição/), "correção do relatório");
    await u.click(screen.getByRole("button", { name: "Salvar e recalcular" }));

    expect(await screen.findByText(/O tempo de leitura é grande demais/)).toBeInTheDocument();
    expect(chamadas("PUT", "/escolas/1/elefante/5")).toHaveLength(0);
  });

  it("Livros: páginas acima de 100.000 são barradas e autor/categoria têm o tamanho da coluna", async () => {
    const u = userEvent.setup();
    responder("GET", "/escolas/1/livros", { total: 0, pagina: 1, por_pagina: 25, itens: [] });
    renderComApp(<Livros />, { rota: "/livros", usuario: ADMIN_GLOBAL });
    await u.click(await screen.findByRole("button", { name: /Novo livro/ }));

    expect(screen.getByLabelText("Autor")).toHaveAttribute("maxLength", "200");
    expect(screen.getByLabelText("Categoria (opcional)")).toHaveAttribute("maxLength", "100");

    await u.type(screen.getByLabelText("Título"), "Livro Fictício do Teste");
    await u.selectOptions(screen.getByLabelText("Nível"), "C");
    await u.type(screen.getByLabelText("Páginas (opcional)"), "100001");
    await u.click(screen.getByRole("button", { name: "Salvar" }));

    expect(await screen.findByText(/As páginas vão de 1 a 100\.000/)).toBeInTheDocument();
    expect(chamadas("POST", "/escolas/1/livros")).toHaveLength(0);
  });
});
