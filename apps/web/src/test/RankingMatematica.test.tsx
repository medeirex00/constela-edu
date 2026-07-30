import { describe, expect, it } from "vitest";

import RankingMatematica from "../pages/RankingMatematica";
import {
  renderComApp,
  responder,
  responderErro,
  screen,
  turmaFake,
  userEvent,
} from "./utils";

// A escola atual é id=1 (sessão autenticada por padrão). A tela consulta o
// Placar do Matific AO VIVO — casa com qualquer query (?periodo=...).
const URL = "/escolas/1/sync/matific/placar-ao-vivo";
// Turmas da base — usadas só para mapear o NOME da turma (ao vivo) → série.
const URL_TURMAS = "/escolas/1/turmas";
const turmasBaseFake = [
  turmaFake({ id: 1, nome: "4º Ano B", ano_escolar: "4º Ano" }),
  turmaFake({ id: 2, nome: "5º Ano C", ano_escolar: "5º Ano" }),
];

function itemMat(over: Record<string, unknown> = {}) {
  return {
    posicao: 1,
    aluno_id: 21,
    nome: "Marina Duarte",
    turma: "4º Ano B",
    serie: "4",
    estrelas: 120,
    atividades: 34,
    pontuacao_media: 3.53,
    ...over,
  };
}

function placar(itens: Record<string, unknown>[], over: Record<string, unknown> = {}) {
  return {
    periodo: "Este mês",
    filtro: "start_date=2026-07-01&end_date=2026-07-14",
    atualizado_em: "2026-07-14T12:00:00Z",
    total: itens.length,
    com_link: itens.filter((i) => i.aluno_id).length,
    itens,
    ...over,
  };
}

const abrirTela = () =>
  renderComApp(<RankingMatematica />, { rota: "/ranking-matematica" });

describe("RankingMatematica (Matific ao vivo)", () => {
  it("mostra o ranking consultado do Matific no período", async () => {
    responder("GET", URL, placar([
      itemMat(),
      itemMat({ posicao: 2, aluno_id: 22, nome: "Rafael Nogueira" }),
    ]));

    abrirTela();

    expect(
      await screen.findByRole("heading", { name: /Premiar por período/ }),
    ).toBeInTheDocument();
    expect(screen.getByText("Estrelas")).toBeInTheDocument();
    expect(screen.getByText("Atividades")).toBeInTheDocument();
    expect(await screen.findByRole("link", { name: /Marina Duarte/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Rafael Nogueira/ })).toBeInTheDocument();
  });

  it("mostra o estado vazio quando ninguém pontuou no período", async () => {
    responder("GET", URL, placar([]));

    abrirTela();

    expect(
      await screen.findByText("Nenhuma atividade de matemática no período"),
    ).toBeInTheDocument();
  });

  it("mostra a falha quando o Matific recusa a consulta", async () => {
    responderErro("GET", URL, 502, "O Matific exibiu uma verificação de segurança (CAPTCHA).");

    abrirTela();

    expect(
      await screen.findByText("Não foi possível consultar o Matific"),
    ).toBeInTheDocument();
  });

  it("mostra sem link o aluno que não casou com um cadastro do Constela", async () => {
    responder("GET", URL, placar([itemMat({ aluno_id: null, nome: "Aluno Solto" })]));

    abrirTela();

    expect(await screen.findByText(/Aluno Solto/)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Aluno Solto/ })).not.toBeInTheDocument();
  });

  it("Ano letivo vem do banco local (não consulta o Matific ao vivo)", async () => {
    const u = userEvent.setup();
    // Ao vivo (padrão "Este mês")
    responder("GET", URL, placar([itemMat({ nome: "Marina AoVivo" })]));
    // Banco local (endpoint de snapshots) — retorna um ARRAY, não {itens}
    responder("GET", "/escolas/1/ranking/matematica", [
      { posicao: 1, aluno_id: 99, nome: "Ana Local", turma: "3º Ano A",
        estrelas: 900, atividades: 200, pontuacao_media: 4.5 },
    ]);

    abrirTela();
    expect(await screen.findByRole("link", { name: /Marina AoVivo/ })).toBeInTheDocument();

    await u.selectOptions(screen.getByLabelText("Período de análise"), "ano_letivo");

    expect(await screen.findByRole("link", { name: /Ana Local/ })).toBeInTheDocument();
    expect(screen.getByText(/Banco local/)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Marina AoVivo/ })).not.toBeInTheDocument();
  });

  it("filtra por turma no cliente (sem nova consulta ao Matific)", async () => {
    const u = userEvent.setup();
    responder("GET", URL_TURMAS, turmasBaseFake);
    responder("GET", URL, placar([
      itemMat({ aluno_id: 21, nome: "Marina Duarte", turma: "4º Ano B" }),
      itemMat({ posicao: 2, aluno_id: 40, nome: "Sofia Lima", turma: "5º Ano C" }),
    ]));

    abrirTela();

    expect(await screen.findByRole("link", { name: /Marina Duarte/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Sofia Lima/ })).toBeInTheDocument();

    await u.selectOptions(screen.getByLabelText("Filtrar por turma ou série"), "turma:5º Ano C");

    expect(screen.getByRole("link", { name: /Sofia Lima/ })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Marina Duarte/ })).not.toBeInTheDocument();
  });

  it("consolida por série no cliente (mapa turma→série da base)", async () => {
    const u = userEvent.setup();
    responder("GET", URL_TURMAS, turmasBaseFake);
    responder("GET", URL, placar([
      itemMat({ aluno_id: 21, nome: "Marina Duarte", turma: "4º Ano B" }),
      itemMat({ posicao: 2, aluno_id: 40, nome: "Sofia Lima", turma: "5º Ano C" }),
    ]));

    abrirTela();

    expect(await screen.findByRole("link", { name: /Sofia Lima/ })).toBeInTheDocument();
    // A opção de série só aparece depois que /turmas carrega (mapa turma→série).
    await screen.findByRole("option", { name: /5º Ano \(todas as turmas\)/ });

    await u.selectOptions(screen.getByLabelText("Filtrar por turma ou série"), "serie:5º Ano");

    expect(screen.getByRole("link", { name: /Sofia Lima/ })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Marina Duarte/ })).not.toBeInTheDocument();
  });
});
