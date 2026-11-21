/**
 * PEND-58 (REV-IMPWEB-3, resto no "Corrigir"/"Alterar aluno") — quando o GET /turmas
 * falha, o seletor "1. Selecione a turma" dizia "Nenhuma turma cadastrada", e isso é
 * falso: a escola tem turmas, elas só não carregaram. Agora ele diz "As turmas não
 * carregaram". Escola sem turma nenhuma continua com "Nenhuma turma cadastrada".
 *
 * Vale para a importação em lote (prévia REAL de um aluno novo, gravada por
 * backend/tests/test_aud_impweb_turma_da_previa.py) e para a de um arquivo por vez.
 * Dados fictícios.
 */
import { describe, expect, it } from "vitest";

import { ImportacaoLoteProvider } from "../context/ImportacaoLoteContext";
import type { Analise } from "../lib/types";
import ImportacaoLote from "../pages/ImportacaoLote";
import Importacoes from "../pages/Importacoes";
import loteTurmaCadastrada from "./fixtures/importacoes/previa_da_tela/lote_turma_cadastrada_analise.json";
import {
  fireEvent,
  renderComApp,
  responder,
  responderErro,
  screen,
  userEvent,
  waitFor,
  within,
} from "./utils";

const ERRO_TURMAS = "Erro interno. Tente novamente em instantes.";

function opcoesDaTurma(painel: HTMLElement): string[] {
  const select = within(painel).getByRole("combobox", { name: "1. Selecione a turma" }) as HTMLSelectElement;
  return Array.from(select.options).map((o) => o.textContent ?? "");
}

async function corrigirNoLote(): Promise<HTMLElement> {
  const u = userEvent.setup();
  responder("UPLOAD", "/escolas/1/importacoes/analisar",
    JSON.parse(JSON.stringify(loteTurmaCadastrada)) as Analise);
  responder("GET", "/escolas/1/alunos", { itens: [], total: 0, pagina: 1, por_pagina: 100 });
  const { container } = renderComApp(
    <ImportacaoLoteProvider><ImportacaoLote /></ImportacaoLoteProvider>, { rota: "/importacoes" });
  await screen.findByText(/Arraste os relatórios em PDF aqui/);
  const input = container.querySelector('input[type="file"]') as HTMLInputElement;
  fireEvent.change(input, {
    target: { files: [new File(["%PDF-1.4"], "aluno-ficticio.pdf", { type: "application/pdf" })] },
  });
  await u.click(await screen.findByRole("button", { name: /Analisar 1 arquivo/ }));
  await screen.findByText("Conferência da importação");
  await u.click(screen.getByRole("button", { name: /Corrigir/ }));
  return screen.findByRole("dialog", { name: "Alterar aluno" });
}

/** Relatório individual (uma linha por livro) de uma criança, para o "Alterar aluno". */
function analiseIndividual(): Analise {
  return {
    plataforma: "elefante",
    formato: "leituras",
    tipo: "texto",
    arquivo_token: null,
    arquivo_nome: null,
    estrategia: "tabela",
    mensagem_deteccao: "Este arquivo pertence ao Elefante Letrado.",
    turma_detectada: "3º Ano A",
    origem_nome: "conteudo",
    total_alunos: 1,
    total_linhas: 1,
    total_erros: 0,
    total_avisos: 0,
    erros_gerais: [],
    linhas: [{
      numero: 1,
      nome: "Crianca Ficticia Leitora",
      dados: { livro: "Livro Ficticio", nivel: "D", data: "2026-08-01T10:00:00" },
      erros: [],
      avisos: [],
      correspondencia: { status: "nao_encontrado", aluno_id: null, aluno_nome: null,
        alternativas: [], turma_id: 1, turma_nome: "3º Ano A" },
    }],
  } as unknown as Analise;
}

async function alterarAlunoNoUmPorVez(): Promise<HTMLElement> {
  const u = userEvent.setup();
  responder("GET", "/escolas/1/importacoes", []);
  responder("UPLOAD", "/escolas/1/importacoes/analisar", analiseIndividual());
  responder("GET", "/escolas/1/alunos", { itens: [], total: 0, pagina: 1, por_pagina: 100 });
  renderComApp(
    <ImportacaoLoteProvider><Importacoes /></ImportacaoLoteProvider>, { rota: "/importacoes" });
  await screen.findByText("Nenhuma importação ainda");
  await u.click(await screen.findByRole("button", { name: /Um por vez/ }));
  await u.type(screen.getByRole("textbox"), "relatorio");
  await u.click(screen.getByRole("button", { name: /Analisar e ver prévia/ }));
  await screen.findByText("Prévia da importação");
  await u.click(screen.getByRole("button", { name: /Alterar aluno/ }));
  return screen.findByRole("dialog", { name: "Alterar aluno" });
}

describe("'Corrigir' da importação em lote — turmas que não carregaram", () => {
  it("diz que as turmas não carregaram, não que a escola não tem turma", async () => {
    responderErro("GET", "/escolas/1/turmas", 500, ERRO_TURMAS);
    const painel = await corrigirNoLote();
    expect(opcoesDaTurma(painel)).toEqual(["As turmas não carregaram"]);
  });

  it("escola sem turma nenhuma continua com 'Nenhuma turma cadastrada'", async () => {
    responder("GET", "/escolas/1/turmas", []);
    const painel = await corrigirNoLote();
    expect(opcoesDaTurma(painel)).toEqual(["Nenhuma turma cadastrada"]);
  });
});

describe("'Alterar aluno' da importação de um arquivo — turmas que não carregaram", () => {
  it("diz que as turmas não carregaram", async () => {
    responderErro("GET", "/escolas/1/turmas", 500, ERRO_TURMAS);
    const painel = await alterarAlunoNoUmPorVez();
    // O 500 é transitório: o useApi tenta de novo (300 ms) antes de dar o erro.
    await waitFor(() => expect(opcoesDaTurma(painel)).toEqual(["As turmas não carregaram"]));
  });

  it("escola sem turma nenhuma continua com 'Nenhuma turma cadastrada'", async () => {
    responder("GET", "/escolas/1/turmas", []);
    const painel = await alterarAlunoNoUmPorVez();
    expect(opcoesDaTurma(painel)).toEqual(["Nenhuma turma cadastrada"]);
  });
});
