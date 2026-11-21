/**
 * NAOCORR-11 / RELATORIOS-5 — Relatório por Período aberto pelo ADMIN GLOBAL numa escola
 * de rede com um módulo só.
 *
 * O admin global recebe em `/auth/me` o catálogo inteiro (ele administra todas as redes),
 * e a tela escolhia as plataformas pelo `useModulos()` do usuário: numa escola de rede só
 * com a Leitura, pedia "Elefante + Matific" e o backend respondia 403 (o pedido inteiro é
 * recusado quando uma plataforma é de módulo fora do plano). O item de GET /escolas traz o
 * plano da escola (`modulos`, f2fdb935): a tela passa a usá-lo, como a tela de Relatórios.
 * Escola, alunos e números INVENTADOS.
 */
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";

import { useApp } from "../context/AppContext";
import RelatorioPeriodo from "../pages/RelatorioPeriodo";
import { api, escolaFake, renderComApp, responder, screen, usuarioFake } from "./utils";

function relatorio(plataformas: string[]) {
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

function ComSessao({ children }: { children: ReactNode }) {
  const { usuario } = useApp();
  return usuario ? <>{children}</> : null;
}

function montar(planoDaEscola: string[] | undefined) {
  responder("GET", /\/escolas\/1\/turmas/, []);
  responder("GET", /\/escolas\/1\/alunos/, { itens: [], total: 0 });
  responder("GET", /\/escolas\/1\/relatorios\/periodo/, relatorio(["elefante"]));
  return renderComApp(<ComSessao><RelatorioPeriodo /></ComSessao>, {
    rota: "/relatorios/periodo",
    usuario: usuarioFake({ is_global: true, cargo: "admin", modulos: ["leitura", "matematica"] } as never),
    escolas: [escolaFake({ id: 1, ...(planoDaEscola ? { modulos: planoDaEscola } : {}) } as never)],
    escolaSelecionada: 1,
    periodo: { preset: "mes_anterior" },
  });
}

const pedidos = () =>
  api.mock.calls.map((c) => String(c[0])).filter((u) => u.includes("/relatorios/periodo"));

const opcoes = () =>
  Array.from((screen.getByLabelText("Plataforma") as HTMLSelectElement).options).map((o) => o.textContent);

describe("Relatório por Período do admin global: o plano da escola selecionada", () => {
  it("escola de rede só com a Leitura: pede só o Elefante e não oferece o Matific", async () => {
    montar(["leitura"]);
    await screen.findByText("setembro de 2026");
    expect(pedidos().length).toBeGreaterThan(0);
    for (const u of pedidos()) {
      expect(u).toContain("plataformas=elefante");
      expect(u).not.toContain("plataformas=matific");
    }
    expect(opcoes()).toEqual(["Somente Elefante Letrado"]);
  });

  it("API antiga (sem o plano no item da escola): o catálogo do usuário, como antes", async () => {
    montar(undefined);
    await screen.findByText("setembro de 2026");
    expect(opcoes().length).toBeGreaterThan(1);
  });
});
