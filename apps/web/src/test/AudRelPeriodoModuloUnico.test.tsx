/**
 * Relatório por Período numa rede que contratou UM módulo só (achado RELATORIOS-5).
 *
 * O backend recusa o pedido INTEIRO com 403 quando uma das plataformas pedidas é de um
 * módulo fora do plano (`_relatorio_periodo_dados` → `svc_modulos.exigir`). A tela não
 * pode, então, abrir pedindo "Elefante + Matific" a uma rede que só tem a Leitura (ou
 * só a Matemática), nem oferecer no seletor a plataforma que a rede não assinou.
 * Escola, alunos e números INVENTADOS.
 */
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";

import { useApp } from "../context/AppContext";
import RelatorioPeriodo from "../pages/RelatorioPeriodo";
import { api, apiDownload, escolaFake, renderComApp, responder, screen, userEvent, usuarioFake } from "./utils";

function relatorioMinimo(plataformas: string[]) {
  return {
    escola: { id: 1, nome: "ESCOLA FICTICIA", ano_letivo: 2026 },
    periodo: {
      preset: "mes_anterior", rotulo: "setembro de 2026",
      inicio: "2026-09-01T00:00:00", fim: "2026-09-30T23:59:59.999999", inclusivo: true,
    },
    escopo: { tipo: "escola", turma_id: null, aluno_id: null, restrito_a_turmas: null },
    plataformas,
    plataformas_rotulo: plataformas.join(" + "),
    alunos: { considerados: 0, com_atividade: 0, sem_atividade: 0 },
    nao_suportado: [],
    por_aluno: [],
  };
}

/** Como no App (rota protegida): a tela só monta depois que a sessão abriu e os
 *  módulos da rede chegaram em `/auth/me`. */
function ComSessao({ children }: { children: ReactNode }) {
  const { usuario } = useApp();
  return usuario ? <>{children}</> : null;
}

function montar(modulos: string[]) {
  responder("GET", /\/escolas\/1\/turmas/, []);
  responder("GET", /\/escolas\/1\/alunos/, { itens: [], total: 0 });
  responder("GET", /\/escolas\/1\/relatorios\/periodo/, relatorioMinimo(
    modulos.length === 1 ? [modulos[0] === "leitura" ? "elefante" : "matific"] : ["elefante", "matific"]));
  return renderComApp(<ComSessao><RelatorioPeriodo /></ComSessao>, {
    rota: "/relatorios/periodo",
    usuario: usuarioFake({ modulos } as never),
    escolas: [escolaFake({ id: 1 })],
    escolaSelecionada: 1,
    periodo: { preset: "mes_anterior" },
  });
}

const pedidosDoRelatorio = () =>
  api.mock.calls.map((c) => String(c[0])).filter((u) => u.includes("/relatorios/periodo"));

const opcoesDaPlataforma = () =>
  Array.from((screen.getByLabelText("Plataforma") as HTMLSelectElement).options).map((o) => o.textContent);

describe("Relatório por Período: só o que a rede contratou", () => {
  it("rede só com a Leitura: pede só o Elefante e não oferece o Matific", async () => {
    montar(["leitura"]);
    await screen.findByText("setembro de 2026");
    const pedidos = pedidosDoRelatorio();
    expect(pedidos.length).toBeGreaterThan(0);
    for (const u of pedidos) {
      expect(u).toContain("plataformas=elefante");
      expect(u).not.toContain("plataformas=matific");
    }
    expect(opcoesDaPlataforma()).toEqual(["Somente Elefante Letrado"]);

    // O PDF segue o mesmo recorte da tela — também sem o Matific.
    await userEvent.click(screen.getByRole("button", { name: /Gerar PDF/ }));
    const pdf = (apiDownload as unknown as { mock: { calls: string[][] } }).mock.calls[0][0];
    expect(pdf).toContain("plataformas=elefante");
    expect(pdf).not.toContain("plataformas=matific");
  });

  it("rede só com a Matemática: pede só o Matific e não oferece o Elefante", async () => {
    montar(["matematica"]);
    await screen.findByText("setembro de 2026");
    const pedidos = pedidosDoRelatorio();
    expect(pedidos.length).toBeGreaterThan(0);
    for (const u of pedidos) {
      expect(u).toContain("plataformas=matific");
      expect(u).not.toContain("plataformas=elefante");
    }
    expect(opcoesDaPlataforma()).toEqual(["Somente Matific"]);
  });

  it("rede com os dois módulos: continua abrindo com as duas plataformas e as três opções", async () => {
    montar(["leitura", "matematica"]);
    await screen.findByText("setembro de 2026");
    const [primeiro] = pedidosDoRelatorio();
    expect(primeiro).toContain("plataformas=elefante");
    expect(primeiro).toContain("plataformas=matific");
    expect(opcoesDaPlataforma()).toEqual([
      "Elefante Letrado + Matific", "Somente Elefante Letrado", "Somente Matific",
    ]);
  });
});
