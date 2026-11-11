/**
 * Catálogo de Livros: trocar o título de um livro fora do catálogo que já tem
 * leituras (G_AJUSTE-5).
 *
 * A coleta reconhece esse livro pelo título que vem da plataforma; com outro título
 * ela criaria um segundo livro e contaria de novo as leituras. O servidor recusa
 * (409). O formulário avisa antes, no campo Título, e mostra a explicação do 409 se
 * a troca for tentada. Livro do catálogo, ou sem leituras, não recebe o aviso.
 * Dados fictícios.
 */
import { describe, expect, it } from "vitest";

import Livros from "../pages/Livros";
import { renderComApp, responder, responderErro, screen, userEvent, usuarioFake } from "./utils";

const ADMIN_GLOBAL = usuarioFake({ id: 99, nome: "Admin Fictício", is_global: true, cargo: "admin" });
const URL_LIVROS = "/escolas/1/livros";

function livroFake(over = {}) {
  return {
    id: 7, titulo: "Diario de Bordo Ficticio", autor: null, nivel_codigo: "C", categoria: null,
    paginas: null, pontos: 1, leituras: 3, elefante_id: null, nivel_fonte: "C",
    nivel_oficial: null, word_count: null, origem_nivel: "legado", atualizado_em: null,
    no_catalogo: false, divergente: false, editavel: true,
    ...over,
  };
}

async function abrirEdicao(livro: ReturnType<typeof livroFake>) {
  const u = userEvent.setup();
  responder("GET", URL_LIVROS, { total: 1, pagina: 1, por_pagina: 25, itens: [livro] });
  renderComApp(<Livros />, { rota: "/livros", usuario: ADMIN_GLOBAL });
  await u.click(await screen.findByRole("button", { name: `Editar ${livro.titulo}` }));
  return u;
}

describe("Catálogo: título de livro fora do catálogo com leituras", () => {
  it("avisa no campo Título que só acentos, maiúsculas e espaços podem mudar", async () => {
    await abrirEdicao(livroFake());
    expect(screen.getByText(/fora do catálogo oficial e tem 3 leituras/)).toBeInTheDocument();
    expect(screen.getByText(/a coleta reconhece o livro pelo título/)).toBeInTheDocument();
  });

  it("livro do catálogo oficial ou sem leituras não recebe o aviso", async () => {
    await abrirEdicao(livroFake({ no_catalogo: true, elefante_id: 8 }));
    expect(screen.queryByText(/a coleta reconhece o livro pelo título/)).toBeNull();
  });

  it("livro fora do catálogo sem leituras não recebe o aviso", async () => {
    await abrirEdicao(livroFake({ leituras: 0 }));
    expect(screen.queryByText(/a coleta reconhece o livro pelo título/)).toBeNull();
  });

  it("mostra a explicação do 409 quando a troca é tentada", async () => {
    const detalhe = "Não é possível trocar o título deste livro: ele está fora do catálogo oficial.";
    responderErro("PATCH", `${URL_LIVROS}/7`, 409, detalhe);
    const u = await abrirEdicao(livroFake());
    const titulo = screen.getByLabelText("Título");
    await u.clear(titulo);
    await u.type(titulo, "Outro Diário Fictício");
    await u.click(screen.getByRole("button", { name: "Salvar" }));
    expect(await screen.findByText(detalhe)).toBeInTheDocument();
  });
});
