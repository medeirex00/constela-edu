/**
 * G_MODULOS-7 — Gestão de redes: "Salvar vínculos" (PUT /redes/{id}/escolas) grava o vínculo e
 * recalcula as escolas cujo plano mudou; a resposta traz `recalculo.falhas`. A tela ignorava a
 * resposta e dizia sempre "Escolas da rede atualizadas." — mesmo com o recálculo da escola
 * movida tendo falhado (as notas dela seguiam o plano antigo no ranking, no certificado e no
 * telão) — e reenviar o mesmo vínculo não refaz o recálculo (nada mudou). Agora a tela diz
 * quais escolas ficaram sem recálculo e oferece "Recalcular as notas" (o recálculo de cada
 * escola, que não duplica nada).
 *
 * Redes e escolas FICTÍCIAS.
 */
import { describe, expect, it } from "vitest";

import { ApiError } from "../lib/api";
import RedeGestao from "../pages/rede/RedeGestao";
import { api, renderComApp, responder, screen, userEvent, usuarioFake } from "./utils";

const adminGlobal = usuarioFake({ nome: "Admin Inventado", cargo: "admin", is_global: true, escola_id: null });

function escola(id: number, nome: string, rede_id: number | null) {
  return { id, nome, cidade: null, estado: null, bairro: null, status: "ativa", rede_id,
           latitude: null, longitude: null, codigo_inep: null };
}

function semear(falhas: { escola_id: number; nome: string; erro: string }[]) {
  responder("GET", "/redes/gerenciar", {
    redes: [{ id: 1, nome: "Rede Inventada Só Leitura", uf: "SP", codigo_ibge: null, status: "ativa" },
            { id: 2, nome: "Rede Inventada Completa", uf: "SP", codigo_ibge: null, status: "ativa" }],
    escolas: [escola(11, "EMEF Inventada Alfa", 1), escola(12, "EMEF Inventada Beta", 2)],
    usuarios: [],
  });
  responder("GET", "/redes/1/modulos", []);
  responder("PUT", "/redes/1/escolas", {
    rede_id: 1, escola_ids: [11, 12],
    recalculo: { escolas: 1, alunos: falhas.length ? 0 : 30,
                 recalculadas: falhas.length ? [] : [{ escola_id: 12, nome: "EMEF Inventada Beta", alunos: 30 }],
                 falhas },
  });
}

const FALHA_BETA = [{ escola_id: 12, nome: "EMEF Inventada Beta", erro: "deadlock detected" }];

function chamadas(metodo: string, caminho: string) {
  return (api as unknown as { mock: { calls: unknown[][] } }).mock.calls
    .filter((c) => c[0] === caminho && (c[1] as { method?: string } | undefined)?.method === metodo);
}

async function moverBeta() {
  const u = userEvent.setup();
  renderComApp(<RedeGestao />, { usuario: adminGlobal });
  await screen.findByText("Escolas da rede");
  await u.click(screen.getByRole("checkbox", { name: /EMEF Inventada Beta/ }));
  await u.click(screen.getByRole("button", { name: /Salvar vínculos/ }));
  return u;
}

describe("Salvar vínculos com o recálculo da escola movida", () => {
  it("o recálculo que falhou aparece, com a escola, e não diz 'atualizadas'", async () => {
    semear(FALHA_BETA);
    await moverBeta();
    const aviso = await screen.findByText(/não foram recalculadas/);
    expect(aviso).toHaveTextContent("Vínculos salvos");
    expect(aviso).toHaveTextContent("EMEF Inventada Beta");
    expect(screen.queryByText("Escolas da rede atualizadas.")).not.toBeInTheDocument();
  });

  it("'Recalcular as notas' pede o recálculo da escola que ficou para trás", async () => {
    semear(FALHA_BETA);
    responder("POST", "/escolas/12/recalcular", { mensagem: "Notas recalculadas para 30 alunos." });
    const u = await moverBeta();
    await u.click(await screen.findByRole("button", { name: "Recalcular as notas" }));
    expect(chamadas("POST", "/escolas/12/recalcular")).toHaveLength(1);
    expect(await screen.findByText(/Notas recalculadas: EMEF Inventada Beta\./)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Recalcular as notas" })).not.toBeInTheDocument();
  });

  it("se o recálculo falhar de novo, a escola continua com a ação e o motivo", async () => {
    semear(FALHA_BETA);
    responder("POST", "/escolas/12/recalcular", () => {
      throw new ApiError(503, "O servidor está ocupado. Tente de novo.");
    });
    const u = await moverBeta();
    await u.click(await screen.findByRole("button", { name: "Recalcular as notas" }));
    expect(await screen.findByText(/ainda não foram recalculadas/)).toHaveTextContent("EMEF Inventada Beta");
    expect(screen.getByTestId("aviso-detalhes")).toHaveTextContent("O servidor está ocupado");
    expect(screen.getByRole("button", { name: "Recalcular as notas" })).toBeInTheDocument();
  });

  it("sem falha, a mensagem de sempre", async () => {
    semear([]);
    await moverBeta();
    expect(await screen.findByText("Escolas da rede atualizadas.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Recalcular as notas" })).not.toBeInTheDocument();
  });
});
