/**
 * Relatórios oficiais (identidade v2) — o que a tela nova acrescenta sem trocar o
 * fluxo dos certificados individuais:
 *
 *  - o seletor de alunos pede até 1000 por página (há escola com mais de 500 ativos;
 *    antes os nomes depois do 500º sumiam em silêncio);
 *  - a busca pelo nome só estreita a lista (o aluno escolhido continua no seletor);
 *  - o erro do certificado (409/422 com o motivo do backend) aparece DENTRO do cartão
 *    de certificados, perto do botão — e não no topo da página.
 */
import { describe, expect, it } from "vitest";

import Relatorios from "../pages/Relatorios";
import {
  ApiError, api, apiDownload, escolaFake, renderComApp, responder, screen, userEvent, usuarioFake, within,
} from "./utils";

function alunoFake(id: number, nome: string, ano_escolar = "3º Ano") {
  return { id, nome, foto_url: null, numero_chamada: null, status: "ativo", turma: "3º Ano A", ano_escolar };
}

function montar() {
  responder("GET", /\/escolas\/1\/alunos/, {
    total: 3, pagina: 1, por_pagina: 1000,
    itens: [alunoFake(1, "Ana Beatriz Souza"), alunoFake(2, "João Pedro Barbosa"), alunoFake(3, "Lia Infantil", "Fase 2")],
  });
  return renderComApp(<Relatorios />, {
    rota: "/relatorios", usuario: usuarioFake(), escolas: [escolaFake({ id: 1 })], escolaSelecionada: 1,
  });
}

const opcoesDoAluno = () =>
  within(screen.getByRole("combobox", { name: "Aluno" })).getAllByRole("option").map((o) => o.textContent);

describe("Relatórios oficiais", () => {
  it("o cabeçalho descreve as exportações sem mostrar a pasta do servidor", async () => {
    montar();
    await screen.findByRole("option", { name: "Ana Beatriz Souza" });
    expect(screen.getByText(
      "Exportações e certificados com a identidade visual da escola.",
    )).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("/exports");
  });

  it("pede até 1000 alunos e a busca só estreita a lista", async () => {
    montar();
    await screen.findByRole("option", { name: "Ana Beatriz Souza" });
    expect(api.mock.calls.some(([c]) => String(c).includes("/escolas/1/alunos?por_pagina=1000"))).toBe(true);
    // Educação Infantil fora da premiação: não entra no seletor e a tela diz por quê.
    expect(opcoesDoAluno()).toEqual(["Selecione…", "Ana Beatriz Souza", "João Pedro Barbosa"]);
    expect(screen.getByText(/1 aluno de Educação Infantil não aparece na lista/)).toBeInTheDocument();

    const u = userEvent.setup();
    await u.selectOptions(screen.getByRole("combobox", { name: "Aluno" }), "1");
    await u.type(screen.getByRole("searchbox", { name: "Buscar pelo nome" }), "joao");
    // O escolhido (Ana) continua; o filtro acha João sem acento.
    expect(opcoesDoAluno()).toEqual(["Selecione…", "Ana Beatriz Souza", "João Pedro Barbosa"]);
    await u.clear(screen.getByRole("searchbox", { name: "Buscar pelo nome" }));
    await u.selectOptions(screen.getByRole("combobox", { name: "Aluno" }), "");
    await u.type(screen.getByRole("searchbox", { name: "Buscar pelo nome" }), "zzz");
    expect(opcoesDoAluno()).toEqual(["Nenhum nome encontrado"]);
  });

  it("o erro do certificado aparece no cartão de certificados (perto do botão)", async () => {
    apiDownload.mockRejectedValueOnce(new ApiError(409, "Aluno fora da Lista Piloto."));
    montar();
    await screen.findByRole("option", { name: "Ana Beatriz Souza" });
    const u = userEvent.setup();
    await u.selectOptions(screen.getByRole("combobox", { name: "Aluno" }), "1");
    await u.click(screen.getByRole("button", { name: "Elefante Letrado" }));
    expect(apiDownload).toHaveBeenCalledWith(expect.stringContaining("/escolas/1/certificados/1?modelo=elefante&bimestre="));
    const certificados = screen.getByRole("region", { name: "Certificados" });
    expect(await within(certificados).findByText("Aluno fora da Lista Piloto.")).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "Exportações" })).queryByRole("alert")).toBeNull();
  });

  it("Aluno e Bimestre: selects nativos com a seta da v2 (sem a seta do navegador)", async () => {
    montar();
    await screen.findByRole("option", { name: "Ana Beatriz Souza" });
    for (const nome of ["Aluno", "Bimestre"]) {
      const select = screen.getByRole("combobox", { name: nome });
      expect(select.tagName).toBe("SELECT");
      expect(select).toHaveClass("appearance-none", "pr-10");
      // A seta decorativa fica ao lado, fora do nome acessível do campo.
      const seta = select.nextElementSibling as Element;
      expect(seta.tagName.toLowerCase()).toBe("svg");
      expect(seta).toHaveAttribute("aria-hidden", "true");
    }
  });

  it("modelos de certificado só liberam com um aluno escolhido", async () => {
    montar();
    await screen.findByRole("option", { name: "Ana Beatriz Souza" });
    for (const nome of ["Geral", "Elefante Letrado", "Matific"]) {
      expect(screen.getByRole("button", { name: nome })).toBeDisabled();
    }
    await userEvent.setup().selectOptions(screen.getByRole("combobox", { name: "Aluno" }), "2");
    for (const nome of ["Geral", "Elefante Letrado", "Matific"]) {
      expect(screen.getByRole("button", { name: nome })).toBeEnabled();
    }
  });
});
