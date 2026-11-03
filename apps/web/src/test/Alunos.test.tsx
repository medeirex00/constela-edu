/**
 * Lista de Alunos na identidade visual v2 — dados fictícios.
 *
 * O que a tela tem de continuar garantindo depois do novo visual: o nome é o link
 * do perfil (sem render duplo), a turma aparece em chip, a busca tem nome
 * acessível, a falha mostra o motivo com "Tentar de novo", e "escola sem alunos"
 * não se confunde com "pesquisa sem resultado". Professor não vê gestão.
 */
import { describe, expect, it } from "vitest";

import Alunos from "../pages/Alunos";
import {
  api, renderComApp, responder, responderErro, screen, turmaFake, userEvent, usuarioFake, waitFor, within,
} from "./utils";

const URL_ALUNOS = "/escolas/1/alunos";
const URL_TURMAS = "/escolas/1/turmas";

function aluno(id: number, nome: string, turma = "3º Ano A") {
  return {
    id, nome, foto_url: null, numero_chamada: id, status: "ativo", turma, ano_escolar: "3º Ano",
  };
}

function pagina(itens: unknown[], total = itens.length) {
  return { total, pagina: 1, por_pagina: 25, itens };
}

const buscasDaLista = () =>
  api.mock.calls.filter(([c]) => String(c).startsWith(`${URL_ALUNOS}?`)).length;

describe("Alunos", () => {
  it("lista os alunos com o nome como link do perfil, turma em chip e o total", async () => {
    responder("GET", URL_TURMAS, [turmaFake()]);
    responder("GET", URL_ALUNOS, pagina([aluno(10, "Ana Beatriz Ficticia"), aluno(11, "Bruno Ficticio")]));
    renderComApp(<Alunos />, { rota: "/alunos" });

    const link = await screen.findByRole("link", { name: "Ana Beatriz Ficticia" });
    expect(link).toHaveAttribute("href", "/alunos/10");
    // Um só elemento com o nome (o avatar é decorativo, só iniciais).
    expect(screen.getAllByText("Ana Beatriz Ficticia")).toHaveLength(1);
    // A turma de cada aluno, em chip, dentro da tabela (o <option> do filtro fica fora).
    expect(within(screen.getByRole("table")).getAllByText("3º Ano A")).toHaveLength(2);
    expect(screen.getByText("2 alunos")).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Pesquisar aluno pelo nome" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Filtrar por turma" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: "Alunos" })).toBeInTheDocument();
  });

  it("falha ao carregar: mostra o motivo e 'Tentar de novo' busca outra vez", async () => {
    responder("GET", URL_TURMAS, []);
    responderErro("GET", URL_ALUNOS, 500, "Banco indisponível");
    renderComApp(<Alunos />, { rota: "/alunos" });

    expect(await screen.findByText("Banco indisponível", undefined, { timeout: 4000 })).toBeInTheDocument();
    expect(screen.getByText("Não foi possível carregar")).toBeInTheDocument();
    const antes = buscasDaLista();
    responder("GET", URL_ALUNOS, pagina([aluno(10, "Ana Beatriz Ficticia")]));
    await userEvent.click(screen.getByRole("button", { name: "Tentar de novo" }));
    expect(await screen.findByRole("link", { name: "Ana Beatriz Ficticia" })).toBeInTheDocument();
    expect(buscasDaLista()).toBeGreaterThan(antes);
  });

  it("escola sem alunos e filtro sem resultado têm mensagens diferentes", async () => {
    responder("GET", URL_TURMAS, [turmaFake({ id: 3, nome: "4º Ano B" })]);
    responder("GET", URL_ALUNOS, pagina([]));
    renderComApp(<Alunos />, { rota: "/alunos" });

    expect(await screen.findByText("Nenhum aluno ativo nesta escola")).toBeInTheDocument();
    expect(screen.queryByText("Nenhum aluno encontrado")).toBeNull();

    await userEvent.selectOptions(await screen.findByRole("combobox", { name: "Filtrar por turma" }), "3");
    await waitFor(() =>
      expect(api.mock.calls.some(([c]) => String(c).includes("turma_id=3"))).toBe(true));
    expect(await screen.findByText("Nenhum aluno encontrado")).toBeInTheDocument();
    expect(screen.getByText("Ajuste a pesquisa ou os filtros.")).toBeInTheDocument();
  });

  it("professor vê a lista, mas sem os botões de gestão nem o menu de ações", async () => {
    responder("GET", URL_TURMAS, [turmaFake()]);
    responder("GET", URL_ALUNOS, pagina([aluno(10, "Ana Beatriz Ficticia")]));
    renderComApp(<Alunos />, { rota: "/alunos", usuario: usuarioFake({ cargo: "professor" }) });

    expect(await screen.findByRole("link", { name: "Ana Beatriz Ficticia" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Adicionar aluno/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Fundir duplicatas/ })).toBeNull();
    expect(screen.queryByLabelText("Ações de Ana Beatriz Ficticia")).toBeNull();
  });
});
