/**
 * PERIODOS-7 / REV-PER-1 nas telas de ranking: o calendário dos bimestres vem do BACKEND.
 *
 * O Ranking de Matemática já lia o calendário da rota
 * (GET /escolas/{id}/configuracoes/calendario-bimestres?ano=); o de Leitura, o de Evolução
 * e o cabeçalho da tela Ranking chamavam `rotuloDoPeriodo` e `bimestreDoPeriodo` sem ele,
 * e a web só conhece 2026 sozinha. De 2027 em diante:
 *   - "Este bimestre" ficava sem número no cabeçalho e no subtítulo;
 *   - o lote de certificados de uma lista de "Bimestre passado" recebia `undefined` e abria
 *     no bimestre de HOJE "pelo calendário oficial" — um à frente do pódio (dois no recesso).
 * Datas de 2027 FICTÍCIAS (as do exemplo de backend/app/services/bimestres.py).
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import type { CalendarioDoAno } from "../lib/calendarioBimestres";
import RankingEvolucao from "../pages/RankingEvolucao";
import RankingLeitura from "../pages/RankingLeitura";
import Rankings from "../pages/Rankings";
import { renderComApp, responder, screen, userEvent, usuarioFake, waitFor } from "./utils";

const CAL_2027: CalendarioDoAno = {
  ano: 2027,
  bimestres: [
    { numero: 1, inicio: "2027-02-01", fim: "2027-04-23" },
    { numero: 2, inicio: "2027-04-26", fim: "2027-07-09" },
    { numero: 3, inicio: "2027-07-26", fim: "2027-10-01" },
    { numero: 4, inicio: "2027-10-04", fim: "2027-12-17" },
  ],
};
const ROTA_CAL = "/escolas/1/configuracoes/calendario-bimestres";
const EM_15_10_2027 = new Date(2027, 9, 15, 12, 0, 0);
// Recesso entre o 2º e o 3º: o "Bimestre passado" do backend é o 2º; o "de hoje", o 3º.
const RECESSO_JULHO_2027 = new Date(2027, 6, 15, 12, 0, 0);
const DICA_DA_LISTA = "Abre no bimestre do período desta lista; vale o que você escolher.";
const DICA_OFICIAL = "Abre no bimestre de hoje pelo calendário oficial; vale o que você escolher.";
const USUARIO = usuarioFake({ modulos: ["leitura", "matematica"] });

function relogioEm(data: Date) {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(data);
}

afterEach(() => {
  vi.useRealTimers();
});

const leitor = (aluno_id: number, nome: string, posicao: number) => ({
  posicao, aluno_id, nome, turma: "3º Ano A", ano_escolar: "3º Ano",
  livros: 5, pontos: 120 - posicao, tempo_leitura_min: 40,
});

const evoluiu = (aluno_id: number, nome: string, posicao: number, nota_evolucao: number) => ({
  posicao, aluno_id, nome, turma: "3º Ano A", ano_escolar: "3º Ano", nota_evolucao,
  ganhos: { atividades: 4, estrelas: 0, livros: 1, tempo_leitura_min: 10, acertos: 0 },
});

function respostasComuns() {
  responder("GET", ROTA_CAL, CAL_2027);
  responder("GET", "/escolas/1/turmas", []);
  responder("GET", "/escolas/1/ranking/leitura", [leitor(101, "Ana Beatriz Souza", 1)]);
  responder("GET", "/escolas/1/ranking-evolucao", [evoluiu(101, "Ana Beatriz Souza", 1, 9.5)]);
}

async function seletorDoLote(u: ReturnType<typeof userEvent.setup>) {
  await u.click(await screen.findByRole("button", { name: "Gerar certificados" }));
  return (await screen.findByLabelText("Bimestre impresso")) as HTMLSelectElement;
}

describe("Ranking de Leitura com o calendário de 2027 no backend", () => {
  it("'Este bimestre' ganha o número (4º) no subtítulo da lista", async () => {
    relogioEm(EM_15_10_2027);
    respostasComuns();
    renderComApp(<RankingLeitura />, { usuario: USUARIO, periodo: { preset: "bimestre" } });
    expect(await screen.findByText(/^4º bimestre · 1 aluno\(s\) com leitura/)).toBeInTheDocument();
    expect(screen.queryByText(/^Este bimestre · /)).toBeNull();
  });

  it("lote de 'Bimestre passado' em 15/10/2027 abre no 3º, o bimestre da lista", async () => {
    relogioEm(EM_15_10_2027);
    respostasComuns();
    renderComApp(<RankingLeitura />, { usuario: USUARIO, periodo: { preset: "bimestre_anterior" } });
    await screen.findAllByText("Ana Beatriz Souza");
    const seletor = await seletorDoLote(userEvent.setup());
    await waitFor(() => expect(seletor.value).toBe("3"));
    expect(screen.getByText(DICA_DA_LISTA)).toBeInTheDocument();
    expect(screen.queryByText(DICA_OFICIAL)).toBeNull();
  });

  it("no recesso de julho de 2027, o lote de 'Bimestre passado' abre no 2º (não no 3º de hoje)", async () => {
    relogioEm(RECESSO_JULHO_2027);
    respostasComuns();
    renderComApp(<RankingLeitura />, { usuario: USUARIO, periodo: { preset: "bimestre_anterior" } });
    await screen.findAllByText("Ana Beatriz Souza");
    const seletor = await seletorDoLote(userEvent.setup());
    await waitFor(() => expect(seletor.value).toBe("2"));
    expect(screen.getByText(DICA_DA_LISTA)).toBeInTheDocument();
  });
});

describe("Ranking de Evolução com o calendário de 2027 no backend", () => {
  it("'Este bimestre' ganha o número (4º) no subtítulo do cartão", async () => {
    relogioEm(EM_15_10_2027);
    respostasComuns();
    renderComApp(<RankingEvolucao />, { usuario: USUARIO, periodo: { preset: "bimestre" } });
    expect(await screen.findByText("4º bimestre · independente da nota acumulada")).toBeInTheDocument();
    expect(screen.queryByText("Este bimestre · independente da nota acumulada")).toBeNull();
  });

  it("trocando o Geral pela arte do Elefante, o lote de 'Bimestre passado' abre no 3º", async () => {
    relogioEm(EM_15_10_2027);
    respostasComuns();
    renderComApp(<RankingEvolucao />, { usuario: USUARIO, periodo: { preset: "bimestre_anterior" } });
    await screen.findAllByText("Ana Beatriz Souza");
    const u = userEvent.setup();
    const seletor = await seletorDoLote(u);
    await u.click(screen.getByRole("radio", { name: /Elefante Letrado/ }));
    await waitFor(() => expect(seletor.value).toBe("3"));
    expect(screen.getByText(DICA_DA_LISTA)).toBeInTheDocument();
    expect(screen.queryByText(DICA_OFICIAL)).toBeNull();
  });
});

describe("tela Ranking: cabeçalho com o calendário de 2027 no backend", () => {
  it("na aba Evolução, o período do cabeçalho é '4º bimestre', não 'Este bimestre'", async () => {
    relogioEm(EM_15_10_2027);
    respostasComuns();
    responder("GET", "/escolas/1/ranking/frescor", {});
    renderComApp(<Rankings />, {
      rota: "/ranking?ver=evolucao", usuario: USUARIO, periodo: { preset: "bimestre" },
    });
    expect(await screen.findByText("Ranking Geral")).toBeInTheDocument();
    // O período do cabeçalho é o <span> em negrito da descrição (as opções do seletor de
    // período também se chamam "Este bimestre" e "4º bimestre", mas são <option>).
    expect(await screen.findByText("4º bimestre", { selector: "span" })).toBeInTheDocument();
    expect(screen.queryByText("Este bimestre", { selector: "span" })).toBeNull();
  });
});
