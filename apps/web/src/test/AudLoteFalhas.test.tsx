/**
 * Auditoria (importação em lote): as falhas do servidor chegam a quem importa.
 *
 * OBSERVABILIDADE-3: o ``catch {}`` do /confirmar trocava a recusa do servidor por
 * "falhou" e o relatório final mostrava, como motivo, o texto da ANÁLISE ("Aluno novo —
 * será criado nesta turma."). E o ``catch`` do GET /turmas deixava a lista vazia em
 * silêncio: a conferência dizia "Aluno não encontrado" e o "Corrigir" abria sem turmas.
 *
 * REV-IMPWEB-3: o aviso da falha das turmas dizia que "os arquivos de aluno novo ficam
 * sem turma" — falso: o destino do aluno novo é a turma que a prévia do backend decidiu
 * (``correspondencia.turma_id``), com ou sem a lista de turmas. O teste que o sustentava
 * usava uma análise montada à mão com ``correspondencia: null``, que o /analisar nunca
 * devolve. Os testes da falha das turmas usam agora a prévia REAL de um aluno novo
 * (lote_turma_cadastrada_analise.json e lote_turmas.json, gravados por
 * backend/tests/test_aud_impweb_turma_da_previa.py). Dados fictícios.
 */
import { describe, expect, it } from "vitest";

import { ImportacaoLoteProvider } from "../context/ImportacaoLoteContext";
import type { Analise } from "../lib/types";
import ImportacaoLote from "../pages/ImportacaoLote";
import loteTurmaCadastrada from "./fixtures/importacoes/previa_da_tela/lote_turma_cadastrada_analise.json";
import loteTurmas from "./fixtures/importacoes/previa_da_tela/lote_turmas.json";
import {
  api,
  fireEvent,
  renderComApp,
  responder,
  responderErro,
  screen,
  turmaFake,
  userEvent,
  waitFor,
  within,
} from "./utils";

const URL_TURMAS = "/escolas/1/turmas";
const URL_ANALISAR = "/escolas/1/importacoes/analisar";
const URL_CONFIRMAR = "/escolas/1/importacoes/confirmar";
const URL_RECALCULAR = "/escolas/1/importacoes/recalcular";

/** Relatório individual de um aluno sem ficha, na turma "3º Ano A" (a do cadastro). */
function analiseAlunoNovo(): Analise {
  return {
    plataforma: "elefante",
    formato: "leituras",
    tipo: "Relatório individual",
    arquivo_token: "tok-lote-1",
    arquivo_nome: "aluno-ficticio.pdf",
    estrategia: "tabela",
    mensagem_deteccao: "Este arquivo pertence ao Elefante Letrado.",
    turma_detectada: "3º Ano A",
    origem_nome: "conteudo",
    total_alunos: 1,
    total_linhas: 1,
    total_erros: 0,
    total_avisos: 0,
    erros_gerais: [],
    linhas: [
      {
        numero: 1,
        nome: "Aluno Ficticio Teste",
        dados: { livro: "Livro Ficticio", data_leitura: "2026-10-01" },
        erros: [],
        avisos: [],
        correspondencia: null,
      },
    ],
  } as unknown as Analise;
}

async function analisarUmArquivo() {
  const u = userEvent.setup();
  const { container } = renderComApp(
    <ImportacaoLoteProvider><ImportacaoLote /></ImportacaoLoteProvider>, { rota: "/importacoes" });
  await screen.findByText(/Arraste os relatórios em PDF aqui/);
  const input = container.querySelector('input[type="file"]') as HTMLInputElement;
  fireEvent.change(input, {
    target: { files: [new File(["%PDF-1.4"], "aluno-ficticio.pdf", { type: "application/pdf" })] },
  });
  await u.click(await screen.findByRole("button", { name: /Analisar 1 arquivo/ }));
  await screen.findByText("Conferência da importação");
  return u;
}

async function gravar(u: ReturnType<typeof userEvent.setup>) {
  await u.click(screen.getByRole("button", { name: /Importar todos \(1\)/ }));
  const confirmacao = await screen.findByRole("dialog", { name: "Gravar 1 arquivo(s)?" });
  await u.click(within(confirmacao).getByRole("button", { name: "Gravar importação" }));
}

describe("Importação em lote — a recusa do servidor chega ao relatório", () => {
  it.each([
    [400, "Token de arquivo inválido."],
    [403, "O módulo Elefante Letrado não faz parte do plano desta rede."],
    [0, "Falha de conexão. Verifique a internet e tente de novo."],
  ])("recusa %s: o relatório mostra o motivo do servidor, não o texto da análise", async (status, motivo) => {
    responder("GET", URL_TURMAS, [turmaFake()]);
    responder("UPLOAD", URL_ANALISAR, analiseAlunoNovo());
    responderErro("POST", URL_CONFIRMAR, status, motivo);
    responder("POST", URL_RECALCULAR, { mensagem: "ok", alunos: 0 });
    const u = await analisarUmArquivo();
    await gravar(u);

    const titulo = await screen.findByText("1 arquivo(s) não foram importados:");
    const bloco = titulo.parentElement as HTMLElement;
    expect(bloco.textContent).toBe(`1 arquivo(s) não foram importados:aluno-ficticio.pdf — ${motivo}`);
    expect(bloco.textContent).not.toContain("será criado nesta turma");
  });
});

/** A prévia REAL de um aluno novo cuja turma o backend decidiu ("3º Ano A", id 1). */
const previaAlunoNovo = () => JSON.parse(JSON.stringify(loteTurmaCadastrada)) as Analise;
const TURMA_DA_PREVIA = previaAlunoNovo().linhas[0].correspondencia!.turma_id!;
const ERRO_TURMAS = "Erro interno. Tente novamente em instantes.";

/** As turmas que o "Corrigir" oferece para escolher o aluno. */
async function turmasDoCorrigir(u: ReturnType<typeof userEvent.setup>) {
  await u.click(screen.getByRole("button", { name: /Corrigir/ }));
  const painel = await screen.findByRole("dialog", { name: "Alterar aluno" });
  const select = within(painel).getByRole("combobox", { name: "1. Selecione a turma" }) as HTMLSelectElement;
  return Array.from(select.options).filter((o) => o.value).map((o) => o.textContent);
}

describe("Importação em lote — falha ao carregar as turmas", () => {
  it("o aviso diz o efeito real; o arquivo do aluno novo segue com a turma da prévia", async () => {
    const corr = previaAlunoNovo().linhas[0].correspondencia!;
    expect([corr.status, corr.turma_id, corr.turma_nome]).toEqual(["nao_encontrado", 1, "3º Ano A"]);
    responderErro("GET", URL_TURMAS, 500, ERRO_TURMAS);
    responder("UPLOAD", URL_ANALISAR, previaAlunoNovo());
    responder("POST", URL_CONFIRMAR, { mensagem: "ok", importacao_id: 1, qtd_alunos: 1, qtd_erros: 0, avisos: [] });
    responder("POST", URL_RECALCULAR, { mensagem: "ok", alunos: 0 });
    const u = await analisarUmArquivo();

    const aviso = screen.getByRole("alert");
    expect(aviso).toHaveTextContent("Não foi possível carregar as turmas da escola.");
    expect(within(aviso).getByText(/^Sem elas/).textContent).toBe(
      `Sem elas, “Corrigir” não mostra as turmas para escolher o aluno. Detalhe: ${ERRO_TURMAS}`);
    // O arquivo mantém a turma que a prévia decidiu e vai com ela.
    expect(screen.getByText("· Turma: 3º Ano A")).toBeInTheDocument();
    expect(screen.getByText("Aluno novo — será criado nesta turma.")).toBeInTheDocument();
    await gravar(u);
    const chamada = api.mock.calls.find(([caminho]) => caminho === URL_CONFIRMAR);
    const corpo = JSON.parse(String((chamada?.[1] as RequestInit).body));
    expect(corpo.linhas.map((l: { criar_em_turma_id: number | null }) => l.criar_em_turma_id))
      .toEqual([TURMA_DA_PREVIA, TURMA_DA_PREVIA]);
  });

  it("'Tentar de novo' devolve as turmas ao 'Corrigir' e tira o aviso", async () => {
    responderErro("GET", URL_TURMAS, 500, ERRO_TURMAS);
    responder("UPLOAD", URL_ANALISAR, previaAlunoNovo());
    responder("GET", "/escolas/1/alunos", { itens: [], total: 0, pagina: 1, por_pagina: 100 });
    const u = await analisarUmArquivo();

    // Sem as turmas, o "Corrigir" não tem turma para escolher.
    expect(await turmasDoCorrigir(u)).toEqual([]);
    await u.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Alterar aluno" })).toBeNull());

    responder("GET", URL_TURMAS, JSON.parse(JSON.stringify(loteTurmas)));
    await u.click(within(screen.getByRole("alert")).getByRole("button", { name: "Tentar de novo" }));
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());

    expect(await turmasDoCorrigir(u)).toEqual(["1º Ano B", "3º Ano A"]);
    // O arquivo continua com a turma da prévia.
    expect(screen.getByText("· Turma: 3º Ano A")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Importar todos \(1\)/ })).toBeEnabled();
  });

  it("'Tentar de novo' que falha de novo mantém o aviso, com o motivo novo", async () => {
    responderErro("GET", URL_TURMAS, 500, ERRO_TURMAS);
    responder("UPLOAD", URL_ANALISAR, previaAlunoNovo());
    const u = await analisarUmArquivo();

    responderErro("GET", URL_TURMAS, 0, "Falha de conexão. Verifique a internet e tente de novo.");
    await u.click(within(screen.getByRole("alert")).getByRole("button", { name: "Tentar de novo" }));
    expect(await screen.findByText(/Falha de conexão\. Verifique a internet/)).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Não foi possível carregar as turmas da escola.");
  });

  it("com as turmas carregadas, não há aviso", async () => {
    responder("GET", URL_TURMAS, JSON.parse(JSON.stringify(loteTurmas)));
    responder("UPLOAD", URL_ANALISAR, previaAlunoNovo());
    await analisarUmArquivo();
    expect(screen.queryByText(/Não foi possível carregar as turmas/)).toBeNull();
  });
});
