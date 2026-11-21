/**
 * IMPORTACAO-1 — a tela escolhia a turma do aluno novo pelo nome (`acharTurmaPorNome`),
 * e a letra da sala casava como pedaço de texto: o "a" de "1 ANO A" dentro de "ano",
 * "fase", "tarde". Sem a 1ºA no cadastro, a criança do "1 ANO A" nascia na "1º Ano B"
 * ou na "1ª Fase A". Agora a tela usa a turma que o backend decidiu na prévia
 * (`correspondencia.turma_id`/`turma_nova`), e `acharTurmaPorNome` casa série e letra
 * inteiras (a regra de `chave_turma_norm` do backend).
 *
 * As prévias são as respostas REAIS do /analisar e do /turmas, gravadas por
 * backend/tests/test_aud_impweb_turma_da_previa.py (que confere, do lado do backend, o
 * que o corpo abaixo faz: a criança nasce na 1ºA nova). Dados fictícios.
 */
import { describe, expect, it } from "vitest";

import { ImportacaoLoteProvider } from "../context/ImportacaoLoteContext";
import { acharTurmaPorNome } from "../lib/nomes";
import ImportacaoLote from "../pages/ImportacaoLote";
import Importacoes from "../pages/Importacoes";
import type { Analise, ResultadoImportacao, Turma } from "../lib/types";
import turmaNovaAnalise from "./fixtures/importacoes/previa_da_tela/turma_nova_analise.json";
import turmaNovaTurmas from "./fixtures/importacoes/previa_da_tela/turma_nova_turmas.json";
import faseAnalise from "./fixtures/importacoes/previa_da_tela/fase_analise.json";
import faseTurmas from "./fixtures/importacoes/previa_da_tela/fase_turmas.json";
import aplicarAnalise from "./fixtures/importacoes/previa_da_tela/aplicar_analise.json";
import aplicarTurmas from "./fixtures/importacoes/previa_da_tela/aplicar_turmas.json";
import loteTurmaNova from "./fixtures/importacoes/previa_da_tela/lote_turma_nova_analise.json";
import loteTurmaCadastrada from "./fixtures/importacoes/previa_da_tela/lote_turma_cadastrada_analise.json";
import loteTurmas from "./fixtures/importacoes/previa_da_tela/lote_turmas.json";
import {
  api,
  fireEvent,
  renderComApp,
  responder,
  screen,
  userEvent,
  within,
} from "./utils";

const URL_HIST = "/escolas/1/importacoes";
const URL_TURMAS = "/escolas/1/turmas";
const URL_ANALISAR = "/escolas/1/importacoes/analisar";
const URL_CONFIRMAR = "/escolas/1/importacoes/confirmar";

const copia = <T,>(x: unknown) => JSON.parse(JSON.stringify(x)) as T;
const idDe = (turmas: { id: number; nome: string }[], nome: string) =>
  turmas.find((t) => t.nome === nome)!.id;

async function previa(analise: unknown, turmas: unknown) {
  const u = userEvent.setup();
  responder("GET", URL_HIST, []);
  responder("GET", URL_TURMAS, copia<Turma[]>(turmas));
  responder("UPLOAD", URL_ANALISAR, copia<Analise>(analise));
  renderComApp(
    <ImportacaoLoteProvider><Importacoes /></ImportacaoLoteProvider>, { rota: "/importacoes" });
  await screen.findByText("Nenhuma importação ainda");
  await u.click(await screen.findByRole("button", { name: /Um por vez/ }));
  await u.type(screen.getByRole("textbox"), "placar");
  await u.click(screen.getByRole("button", { name: /Analisar e ver prévia/ }));
  await screen.findByText("Prévia da importação");
  const data = screen.queryByLabelText("Data do relatório (obrigatória)");
  if (data) fireEvent.change(data, { target: { value: "2026-08-14" } });
  return u;
}

async function corpoEnviado(u: ReturnType<typeof userEvent.setup>) {
  responder("POST", URL_CONFIRMAR, {
    mensagem: "ok", importacao_id: 1, qtd_alunos: 1, qtd_erros: 0, avisos: [],
  } satisfies ResultadoImportacao);
  await u.click(screen.getByRole("button", { name: "Sim, importar" }));
  const dialogo = await screen.findByRole("dialog", { name: "Gravar esta importação?" });
  await u.click(within(dialogo).getByRole("button", { name: "Gravar importação" }));
  const chamada = api.mock.calls.find(([caminho]) => caminho === URL_CONFIRMAR);
  return JSON.parse(String((chamada?.[1] as RequestInit).body));
}

const faixa = () => screen.getByText(/aluno\(s\) novo\(s\)/).closest("span")?.textContent;

describe("acharTurmaPorNome: série e letra inteiras, nunca pedaço de texto", () => {
  it.each([
    ["1 ANO A", [{ id: 7, nome: "1º Ano B" }], null],
    ["1 ANO A", [{ id: 7, nome: "1ª Fase A" }], null],
    ["1 ANO A TARDE", [{ id: 7, nome: "1º Ano B Tarde" }], null],
    ["1 ANO A TARDE ANUAL (300302821)", [{ id: 7, nome: "1ºA" }, { id: 8, nome: "1º Ano B" }], 7],
    ["1A", [{ id: 7, nome: "1ºA" }, { id: 8, nome: "1ºB" }], 7],
    ["3º Ano A", [{ id: 1, nome: "3º Ano A" }, { id: 2, nome: "4º Ano A" }], 1],
    ["5º Ano A", [{ id: 1, nome: "5º Ano A Manhã" }, { id: 2, nome: "5º Ano A Tarde" }], null],
    ["Maternal", [{ id: 1, nome: "Maternal" }, { id: 2, nome: "Maternal II" }], 1],
    ["", [{ id: 1, nome: "3º Ano A" }], null],
  ])("'%s' em %j → %s", (nome, turmas, esperado) => {
    expect(acharTurmaPorNome(turmas, nome)).toBe(esperado);
  });
});

describe("Importações (um por vez): a turma do aluno novo é a da prévia", () => {
  it("sem a 1ºA no cadastro, a criança do '1 ANO A' vai para a turma do relatório (nova), não para a '1º Ano B'", async () => {
    const corr = (turmaNovaAnalise as unknown as Analise).linhas[0].correspondencia!;
    expect([corr.status, corr.turma_id, corr.turma_nova]).toEqual(["nao_encontrado", null, "1ºA"]);
    const u = await previa(turmaNovaAnalise, turmaNovaTurmas);
    const destino = screen.getByRole("combobox", { name: /^Destino de Crianca Ficticia Umbelina/ }) as HTMLSelectElement;
    expect(destino.value).toBe("criar_nova");
    expect(destino.options[destino.selectedIndex].textContent).toBe("Criar na turma do relatório (1 ANO A)");
    expect(faixa()).toBe("1 aluno(s) novo(s) — a turma “1ºA” será criada automaticamente ao importar.");
    const corpo = await corpoEnviado(u);
    expect(corpo.linhas).toMatchObject([
      { aluno_id: null, criar_em_turma_id: null, criar_em_turma_nome: "1 ANO A" }]);
    expect(corpo.linhas[0].criar_em_turma_id).not.toBe(idDe(turmaNovaTurmas, "1º Ano B"));
  });

  it("escola só com a '1ª Fase A': a criança do '1 ANO A' não vai para a turma da Educação Infantil", async () => {
    const u = await previa(faseAnalise, faseTurmas);
    const destino = screen.getByRole("combobox", { name: /^Destino de Crianca Ficticia Primeiro Ano/ }) as HTMLSelectElement;
    expect(destino.value).toBe("criar_nova");
    const corpo = await corpoEnviado(u);
    expect(corpo.linhas[0].criar_em_turma_id).not.toBe(idDe(faseTurmas, "1ª Fase A"));
    expect(corpo.linhas).toMatchObject([{ criar_em_turma_id: null, criar_em_turma_nome: "1 ANO A" }]);
  });

  it("Placar da escola (turma por aluno): cada criança nova já vem na turma cadastrada que o backend disse", async () => {
    const u = await previa(aplicarAnalise, aplicarTurmas);
    const t4b = idDe(aplicarTurmas, "4º Ano B");
    for (const nome of ["Crianca Ficticia Quarto Um", "Crianca Ficticia Quarto Dois"]) {
      expect((screen.getByRole("combobox", { name: `Destino de ${nome}` }) as HTMLSelectElement).value).toBe("criar");
      expect((screen.getByRole("combobox", { name: `Turma para ${nome}` }) as HTMLSelectElement).value).toBe(String(t4b));
    }
    const corpo = await corpoEnviado(u);
    expect(corpo.linhas.map((l: { criar_em_turma_id: number }) => l.criar_em_turma_id)).toEqual([t4b, t4b]);
  });
});

describe("Importação em lote: a turma do aluno novo é a da prévia", () => {
  async function conferencia(analise: unknown) {
    const u = userEvent.setup();
    responder("GET", URL_TURMAS, copia<Turma[]>(loteTurmas));
    responder("UPLOAD", URL_ANALISAR, copia<Analise>(analise));
    const { container } = renderComApp(
      <ImportacaoLoteProvider><ImportacaoLote /></ImportacaoLoteProvider>, { rota: "/importacoes" });
    await screen.findByText(/Arraste os relatórios em PDF aqui/);
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, {
      target: { files: [new File(["%PDF-1.4"], "relatorio-ficticio.pdf", { type: "application/pdf" })] },
    });
    await u.click(await screen.findByRole("button", { name: /Analisar 1 arquivo/ }));
    await screen.findByText("Conferência da importação");
    return u;
  }

  it("sem a 1ºA no cadastro: o lote não marca 'será criado' na '1º Ano B'", async () => {
    const corr = (loteTurmaNova as unknown as Analise).linhas[0].correspondencia!;
    expect([corr.status, corr.turma_id, corr.turma_nova]).toEqual(["nao_encontrado", null, "1ºA"]);
    await conferencia(loteTurmaNova);
    expect(screen.queryByText(/Turma: 1º Ano B/)).toBeNull();
    expect(screen.queryByText("Aluno novo — será criado nesta turma.")).toBeNull();
    // Fica para o gestor (como quando a turma não existe): nada é criado sem ele.
    expect(screen.getByText("Aluno não encontrado. Escolha a turma e o aluno em “Corrigir”.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Importar todos \(0\)/ })).toBeDisabled();
  });

  it("com a turma da sala cadastrada: o lote cria na turma que o backend disse", async () => {
    await conferencia(loteTurmaCadastrada);
    expect(screen.getByText("· Turma: 3º Ano A")).toBeInTheDocument();
    expect(screen.getByText("Aluno novo — será criado nesta turma.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Importar todos \(1\)/ })).toBeEnabled();
  });
});
