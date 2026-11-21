/**
 * Relatórios do admin global numa escola de rede com um módulo só (resíduo do RELATORIOS-5).
 *
 * O admin global recebe em /auth/me o catálogo inteiro de módulos; os da escola SELECIONADA
 * vêm no item de /escolas (`modulos`). A tela de Relatórios segue o plano da escola: não
 * oferece o Catálogo de Livros nem o certificado da plataforma que a rede da escola não
 * contratou (o backend responderia 403). Sem o campo (API antiga), vale o que vinha do
 * usuário. Escola e nomes INVENTADOS.
 */
import { describe, expect, it } from "vitest";

import Relatorios from "../pages/Relatorios";
import type { Escola } from "../lib/types";
import { escolaFake, renderComApp, responder, screen, usuarioFake } from "./utils";

const global = usuarioFake({ is_global: true, cargo: "admin", modulos: ["leitura", "matematica"] });

function montar(modulosDaEscola?: string[]) {
  responder("GET", /\/escolas\/1\/alunos/, { itens: [], total: 0, pagina: 1, por_pagina: 1000 });
  const escola = { ...escolaFake({ id: 1 }), ...(modulosDaEscola ? { modulos: modulosDaEscola } : {}) };
  return renderComApp(<Relatorios />, {
    rota: "/relatorios",
    usuario: global,
    escolas: [escola as Escola],
    escolaSelecionada: 1,
  });
}

describe("Relatórios do admin global × plano da escola selecionada", () => {
  it("escola de rede só com a Matemática: sem Catálogo de Livros e sem o certificado do Elefante", async () => {
    montar(["matematica"]);
    expect(await screen.findByRole("button", { name: "Matific" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Elefante Letrado" })).not.toBeInTheDocument();
    expect(screen.queryByText("Catálogo de Livros")).not.toBeInTheDocument();
  });

  it("escola de rede só com a Leitura: sem o certificado do Matific", async () => {
    montar(["leitura"]);
    expect(await screen.findByRole("button", { name: "Elefante Letrado" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Matific" })).not.toBeInTheDocument();
    expect(screen.getByText("Catálogo de Livros")).toBeInTheDocument();
  });

  it("sem o plano da escola na resposta (API antiga): vale o do usuário", async () => {
    montar();
    expect(await screen.findByRole("button", { name: "Matific" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Elefante Letrado" })).toBeInTheDocument();
    expect(screen.getByText("Catálogo de Livros")).toBeInTheDocument();
  });
});
