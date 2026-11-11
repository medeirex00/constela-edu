/**
 * Auditoria (importação em lote): as falhas do servidor chegam a quem importa.
 *
 * OBSERVABILIDADE-3: o ``catch {}`` do /confirmar trocava a recusa do servidor por
 * "falhou" e o relatório final mostrava, como motivo, o texto da ANÁLISE ("Aluno novo —
 * será criado nesta turma."). E o ``catch`` do GET /turmas deixava a lista vazia em
 * silêncio: a conferência dizia "Aluno não encontrado" e o "Corrigir" abria sem turmas.
 * Dados fictícios.
 */
import { describe, expect, it } from "vitest";

import { ImportacaoLoteProvider } from "../context/ImportacaoLoteContext";
import type { Analise } from "../lib/types";
import ImportacaoLote from "../pages/ImportacaoLote";
import {
  fireEvent,
  renderComApp,
  responder,
  responderErro,
  screen,
  turmaFake,
  userEvent,
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

describe("Importação em lote — falha ao carregar as turmas", () => {
  it("a conferência avisa, com o motivo, e 'Tentar de novo' rebusca as turmas e refaz os destinos", async () => {
    responderErro("GET", URL_TURMAS, 500, "Erro interno. Tente novamente em instantes.");
    responder("UPLOAD", URL_ANALISAR, analiseAlunoNovo());
    const u = await analisarUmArquivo();

    const aviso = screen.getByRole("alert");
    expect(aviso).toHaveTextContent("Não foi possível carregar as turmas da escola.");
    expect(aviso).toHaveTextContent("Erro interno. Tente novamente em instantes.");
    // Sem turmas, o arquivo fica sem destino (e o aviso diz por quê).
    expect(screen.getByRole("button", { name: /Importar todos \(0\)/ })).toBeDisabled();

    responder("GET", URL_TURMAS, [turmaFake()]);
    await u.click(within(aviso).getByRole("button", { name: "Tentar de novo" }));

    expect(await screen.findByText("· Turma: 3º Ano A")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByRole("button", { name: /Importar todos \(1\)/ })).toBeEnabled();
  });

  it("'Tentar de novo' que falha de novo mantém o aviso, com o motivo novo", async () => {
    responderErro("GET", URL_TURMAS, 500, "Erro interno. Tente novamente em instantes.");
    responder("UPLOAD", URL_ANALISAR, analiseAlunoNovo());
    const u = await analisarUmArquivo();

    responderErro("GET", URL_TURMAS, 0, "Falha de conexão. Verifique a internet e tente de novo.");
    await u.click(within(screen.getByRole("alert")).getByRole("button", { name: "Tentar de novo" }));
    expect(await screen.findByText(/Falha de conexão\. Verifique a internet/)).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Não foi possível carregar as turmas da escola.");
  });

  it("com as turmas carregadas, não há aviso", async () => {
    responder("GET", URL_TURMAS, [turmaFake()]);
    responder("UPLOAD", URL_ANALISAR, analiseAlunoNovo());
    await analisarUmArquivo();
    expect(screen.queryByText(/Não foi possível carregar as turmas/)).toBeNull();
  });
});
