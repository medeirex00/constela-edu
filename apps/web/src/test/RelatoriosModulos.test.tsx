/** Relatórios com um módulo só (achado de segurança #2): o Catálogo de Livros (Leitura) e
 *  o certificado da plataforma fora do plano não aparecem — antes o clique dava 403,
 *  enquanto o lote de certificados já os escondia. */
import { describe, expect, it } from "vitest";

import Relatorios from "../pages/Relatorios";
import { escolaFake, renderComApp, responder, screen, usuarioFake } from "./utils";

function montar(modulos: string[]) {
  responder("GET", /\/escolas\/1\/alunos/, { itens: [], total: 0, pagina: 1, por_pagina: 1000 });
  return renderComApp(<Relatorios />, {
    rota: "/relatorios",
    usuario: usuarioFake({ modulos }),
    escolas: [escolaFake({ id: 1 })],
    escolaSelecionada: 1,
  });
}

describe("Relatórios × módulos contratados", () => {
  it("só Matemática: sem Catálogo de Livros e sem o certificado do Elefante", async () => {
    montar(["matematica"]);
    expect(await screen.findByRole("button", { name: "Matific" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Elefante Letrado" })).not.toBeInTheDocument();
    expect(screen.queryByText("Catálogo de Livros")).not.toBeInTheDocument();
    expect(screen.getByText("Ranking Geral")).toBeInTheDocument();
  });

  it("só Leitura: sem o certificado do Matific; Catálogo de Livros aparece", async () => {
    montar(["leitura"]);
    expect(await screen.findByRole("button", { name: "Elefante Letrado" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Matific" })).not.toBeInTheDocument();
    expect(screen.getByText("Catálogo de Livros")).toBeInTheDocument();
  });

  it("os dois módulos: tudo como antes", async () => {
    montar(["leitura", "matematica"]);
    expect(await screen.findByRole("button", { name: "Matific" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Elefante Letrado" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Geral" })).toBeInTheDocument();
    expect(screen.getByText("Catálogo de Livros")).toBeInTheDocument();
  });
});
