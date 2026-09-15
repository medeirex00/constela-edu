import { describe, expect, it } from "vitest";

import RankingMatematica from "../pages/RankingMatematica";
import {
  rankingItemFake,
  renderComApp,
  responder,
  responderErro,
  screen,
  turmaFake,
  userEvent,
  within,
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

// Estas telas exercitam o Matific AO VIVO, que só é consultado num SUB-período.
// O período global padrão agora é "ano_letivo" (banco local) — semeamos "mes"
// para cair no caminho ao vivo que os testes cobrem.
const abrirTela = () =>
  renderComApp(<RankingMatematica />, {
    rota: "/ranking-matematica", periodo: { preset: "mes" },
  });

describe("RankingMatematica (Matific ao vivo)", () => {
  it("mostra o ranking consultado do Matific no período", async () => {
    responder("GET", URL, placar([
      itemMat(),
      itemMat({ posicao: 2, aluno_id: 22, nome: "Rafael Nogueira" }),
    ]));

    abrirTela();

    expect(
      await screen.findByRole("heading", { name: /Placar Matific \(estrelas e atividades no período\)/ }),
    ).toBeInTheDocument();
    expect(screen.getByText("Estrelas")).toBeInTheDocument();
    expect(screen.getByText("Estrelas e atividades no período")).toBeInTheDocument();
    expect(await screen.findByRole("link", { name: /Marina Duarte/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Rafael Nogueira/ })).toBeInTheDocument();
    // A classificação OFICIAL de Matemática abre no topo (ranking do ano, só aferidos).
    expect(screen.getByText("Classificação oficial — Matemática")).toBeInTheDocument();
  });

  it("classificação oficial no topo: /ranking?dimensao=matematica com a lista de aferidos", async () => {
    responder("GET", URL, placar([itemMat()]));
    responder("GET", "/escolas/1/ranking", (caminho: string) =>
      caminho.includes("dimensao=matematica")
        ? [{ ...rankingItemFake({ posicao: 1, aluno_id: 50, nome: "Oficial Mat Silva", turma: "4º Ano B",
                                  ano_escolar: "4º Ano", nota_matific: 88, nota_elefante: 0 }),
             nota: 88, n_aferidos: 1, dados: { atividades: 40 }, adocao: 100 }]
        : []);

    abrirTela();

    expect(await screen.findByRole("link", { name: "Oficial Mat Silva" })).toBeInTheDocument();
    expect(screen.getByText("1 alunos aferidos em Matemática")).toBeInTheDocument();
    expect(screen.getByText("Nota de Matemática")).toBeInTheDocument();
  });

  it("turno global no placar AO VIVO: filtra no cliente pelo turno da turma (cadastro)", async () => {
    const u = userEvent.setup();
    responder("GET", URL_TURMAS, [
      turmaFake({ id: 1, nome: "4º Ano B", ano_escolar: "4º Ano", turno: "manha" }),
      turmaFake({ id: 2, nome: "5º Ano C", ano_escolar: "5º Ano", turno: "tarde" }),
    ]);
    // O placar ao vivo é consultado UMA vez; o turno não vai ao Matific.
    let consultas = 0;
    responder("GET", URL, () => {
      consultas += 1;
      return placar([
        itemMat({ aluno_id: 21, nome: "Marina Duarte", turma: "4º Ano B" }),
        itemMat({ posicao: 2, aluno_id: 40, nome: "Sofia Lima", turma: "5º Ano C" }),
        itemMat({ posicao: 3, aluno_id: null, nome: "Aluno Turma Fora", turma: "Turma X" }),
      ]);
    });

    abrirTela();

    expect(await screen.findByRole("link", { name: /Marina Duarte/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Sofia Lima/ })).toBeInTheDocument();
    expect(screen.getByText(/Aluno Turma Fora/)).toBeInTheDocument();

    const seletor = await screen.findByLabelText("Turno");
    await within(seletor).findByRole("option", { name: "Tarde" });
    await u.selectOptions(seletor, "tarde");

    expect(screen.getByRole("link", { name: /Sofia Lima/ })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Marina Duarte/ })).not.toBeInTheDocument();
    // Turma que não existe no cadastro não tem turno conhecido: sai do recorte.
    expect(screen.queryByText(/Aluno Turma Fora/)).not.toBeInTheDocument();
    expect(consultas).toBe(1);
  });

  it("turno no placar AO VIVO: turma com o MESMO nome em dois turnos fica fora do recorte e a tela avisa", async () => {
    const u = userEvent.setup();
    // "3º Ano A" existe na manhã E na tarde: o placar ao vivo só traz o nome,
    // então não dá para saber de qual turno é o aluno.
    responder("GET", URL_TURMAS, [
      turmaFake({ id: 1, nome: "3º Ano A", ano_escolar: "3º Ano", turno: "manha" }),
      turmaFake({ id: 2, nome: "3º Ano A", ano_escolar: "3º Ano", turno: "tarde" }),
      turmaFake({ id: 3, nome: "4º Ano B", ano_escolar: "4º Ano", turno: "manha" }),
    ]);
    responder("GET", URL, placar([
      itemMat({ aluno_id: 21, nome: "Marina Duarte", turma: "4º Ano B" }),
      itemMat({ posicao: 2, aluno_id: 40, nome: "Caio Homonimo", turma: "3º Ano A" }),
      itemMat({ posicao: 3, aluno_id: 41, nome: "Bia Homonima", turma: "3º Ano A" }),
    ]));

    abrirTela();

    // Todos os turnos: ninguém sai e não há aviso.
    expect(await screen.findByRole("link", { name: /Caio Homonimo/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Marina Duarte/ })).toBeInTheDocument();
    const seletor = await screen.findByLabelText("Turno");
    await within(seletor).findByRole("option", { name: "Manhã" });
    expect(screen.queryByText(/mesmo nome em turnos diferentes/)).not.toBeInTheDocument();

    // Manhã: a turma sem ambiguidade entra; as homônimas ficam FORA (não são
    // encaixadas no turno errado) e a tela diz quantos alunos saíram.
    await u.selectOptions(seletor, "manha");
    expect(screen.getByRole("link", { name: /Marina Duarte/ })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Caio Homonimo/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Bia Homonima/ })).not.toBeInTheDocument();
    expect(screen.getByText(
      "2 aluno(s) de turmas com o mesmo nome em turnos diferentes não entram no filtro de turno do placar ao vivo.",
    )).toBeInTheDocument();

    // Tarde: idem (as homônimas não aparecem na Tarde só porque a última
    // turma cadastrada com o nome é da Tarde).
    await u.selectOptions(seletor, "tarde");
    expect(screen.queryByRole("link", { name: /Caio Homonimo/ })).not.toBeInTheDocument();
    expect(screen.getByText("Nenhuma atividade de matemática no período")).toBeInTheDocument();
    expect(screen.getByText(/2 aluno\(s\) de turmas com o mesmo nome em turnos diferentes/)).toBeInTheDocument();
  });

  it("turno global no ANO LETIVO vai na query do banco local (turno=)", async () => {
    responder("GET", URL_TURMAS, [
      turmaFake({ id: 1, nome: "4º Ano B", turno: "manha" }),
      turmaFake({ id: 2, nome: "5º Ano C", turno: "tarde" }),
    ]);
    responder("GET", "/escolas/1/ranking/matematica", (caminho: string) =>
      caminho.includes("turno=tarde")
        ? [{ posicao: 1, aluno_id: 40, nome: "Sofia Local Tarde", turma: "5º Ano C",
             estrelas: 10, atividades: 5, pontuacao_media: 2 }]
        : [{ posicao: 1, aluno_id: 99, nome: "Ana Local", turma: "4º Ano B",
             estrelas: 900, atividades: 200, pontuacao_media: 4.5 }]);

    renderComApp(<RankingMatematica />, {
      rota: "/ranking-matematica", periodo: { preset: "ano_letivo" }, turno: "tarde",
    });

    expect(await screen.findByRole("link", { name: /Sofia Local Tarde/ })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Ana Local/ })).not.toBeInTheDocument();
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
