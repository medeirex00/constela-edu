/**
 * Filtro de PERÍODO global "lockado": a escolha do usuário (ex.: personalizado
 * 01/08 → 20/08) tem de ACOMPANHAR a navegação entre as abas de ranking e
 * sobreviver ao reload — antes cada página tinha seu próprio estado e o filtro
 * "resetava" para ano_letivo/mês ao trocar de aba. O período agora vive no
 * AppContext (persistido em localStorage). NÃO confundir com TURNO, que é outro
 * eixo (ver Competição de leitura por turno).
 */
import { fireEvent } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import Rankings from "../pages/Rankings";
import RankingLeitura from "../pages/RankingLeitura";
import type { RankingItem, RankingLeituraItem, RankingTurno, Turma } from "../lib/types";
import { rankingItemFake, renderComApp, responder, screen, turmaFake, userEvent } from "./utils";

const URL_TURMAS = "/escolas/1/turmas";
const URL_GERAL = "/escolas/1/ranking";
const URL_LEITURA = "/escolas/1/ranking/leitura";
const URL_TURNOS = "/escolas/1/ranking/leitura/turnos";

function mockarRankings() {
  responder("GET", URL_TURMAS, [turmaFake()] as Turma[]);
  responder("GET", URL_GERAL, [rankingItemFake({ aluno_id: 10, nome: "Ana Beatriz Souza" })] as RankingItem[]);
  responder("GET", URL_LEITURA, [{
    posicao: 1, aluno_id: 20, nome: "Carla Leitora Silva", turma: "3º Ano A",
    ano_escolar: "3º Ano", livros: 9, pontos: 210, tempo_leitura_min: 60,
  }] as RankingLeituraItem[]);
}

async function escolherPersonalizado(u: ReturnType<typeof userEvent.setup>) {
  const seletor = await screen.findByLabelText("Período de análise");
  await u.selectOptions(seletor, "personalizado");
  fireEvent.change(screen.getByLabelText("Data inicial"), { target: { value: "2026-08-01" } });
  fireEvent.change(screen.getByLabelText("Data final"), { target: { value: "2026-08-20" } });
}

describe("Filtro de período global (lockado)", () => {
  it("mantém o período personalizado ao TROCAR DE ABA (Geral → Leitura)", async () => {
    mockarRankings();
    const u = userEvent.setup();
    renderComApp(<Rankings />, { rota: "/ranking" });

    // A aba Geral abre no padrão global (ano_letivo) e o usuário escolhe um
    // intervalo personalizado.
    expect(await screen.findByRole("link", { name: /Ana Beatriz Souza/ })).toBeInTheDocument();
    await escolherPersonalizado(u);

    // Troca para a aba Elefante Letrado: o SELETOR da nova aba já vem com o
    // MESMO período (não resetou para ano_letivo).
    await u.click(screen.getByRole("tab", { name: "Elefante Letrado" }));
    expect(await screen.findByRole("link", { name: /Carla Leitora Silva/ })).toBeInTheDocument();
    const seletorLeitura = await screen.findByLabelText("Período de análise");
    expect((seletorLeitura as HTMLSelectElement).value).toBe("personalizado");
    expect((screen.getByLabelText("Data inicial") as HTMLInputElement).value).toBe("2026-08-01");
    expect((screen.getByLabelText("Data final") as HTMLInputElement).value).toBe("2026-08-20");
  });

  it("persiste no localStorage e SOBREVIVE AO RELOAD (nova montagem lê o período salvo)", async () => {
    mockarRankings();
    const u = userEvent.setup();
    const { unmount } = renderComApp(<Rankings />, { rota: "/ranking" });
    await screen.findByRole("link", { name: /Ana Beatriz Souza/ });
    await escolherPersonalizado(u);

    // Gravado em localStorage (o eixo de persistência que sobrevive ao reload).
    const salvo = JSON.parse(localStorage.getItem("sgpe_periodo") ?? "{}");
    expect(salvo).toMatchObject({ preset: "personalizado", inicio: "2026-08-01", fim: "2026-08-20" });

    // "Reload": desmonta e monta de novo SEM semear período — o contexto lê o
    // valor salvo e reabre no personalizado.
    unmount();
    renderComApp(<Rankings />, { rota: "/ranking" });
    const seletor = await screen.findByLabelText("Período de análise");
    expect((seletor as HTMLSelectElement).value).toBe("personalizado");
    expect((screen.getByLabelText("Data inicial") as HTMLInputElement).value).toBe("2026-08-01");
  });

  it("TURNO é independente do período: mudar o período não mexe nas abas de turno", async () => {
    responder("GET", URL_TURMAS, [turmaFake()] as Turma[]);
    responder("GET", URL_LEITURA, [] as RankingLeituraItem[]);
    // As ABAS de turno vêm dos grupos (não dos alunos) — alunos vazios bastam.
    const grupos: RankingTurno[] = [
      { turno: "manha", turno_rotulo: "Manhã", total: 1, alunos: [] },
      { turno: "tarde", turno_rotulo: "Tarde", total: 1, alunos: [] },
    ];
    responder("GET", URL_TURNOS, grupos);
    const u = userEvent.setup();
    renderComApp(<RankingLeitura />, { periodo: { preset: "personalizado", inicio: "2026-08-01", fim: "2026-08-20" } });

    // As abas de turno vêm de Turma.turno (outro endpoint), não do período.
    expect(await screen.findByRole("tab", { name: /Manhã/ })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Tarde/ })).toBeInTheDocument();

    // Mudar o período (personalizado → ano letivo) NÃO remove nem troca as abas
    // de turno — os dois eixos são ortogonais.
    await u.selectOptions(screen.getByLabelText("Período de análise"), "ano_letivo");
    expect(screen.getByRole("tab", { name: /Manhã/ })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Tarde/ })).toBeInTheDocument();
  });
});
