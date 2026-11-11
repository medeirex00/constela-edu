// G_LGPD-1 (prévia): a linha que a confirmação IGNORA (conta de aluno excluído
// permanentemente, conta aposentada) chega da prévia com status "ignorado". Antes o
// backend a devolvia como "nao_encontrado" e a tela mostrava "Novo aluno" — "a
// confirmação cria a ficha" —, mas a confirmação a ignorava. Agora a tela diz que a
// linha será ignorada, não oferece destino e não a manda ao /confirmar; o lote a traz
// já ignorada. Dados fictícios.
import { describe, expect, it } from "vitest";

import { ImportacaoLoteProvider } from "../context/ImportacaoLoteContext";
import type { Analise } from "../lib/types";
import ImportacaoLote from "../pages/ImportacaoLote";
import Importacoes from "../pages/Importacoes";
import { fireEvent, renderComApp, responder, screen, turmaFake, userEvent, within } from "./utils";

const URL_HIST = "/escolas/1/importacoes";
const URL_TURMAS = "/escolas/1/turmas";
const URL_ANALISAR = "/escolas/1/importacoes/analisar";

function linha(numero: number, nome: string, correspondencia: Analise["linhas"][number]["correspondencia"]) {
  return { numero, nome, dados: { atividades: 6, pontuacao_media: 71, estrelas: 12 }, erros: [],
           avisos: [], correspondencia };
}

function analise(): Analise {
  return {
    plataforma: "matific", formato: "leaderboard", tipo: "leaderboard",
    arquivo_token: "tok-ign", arquivo_nome: "relatorio.pdf", estrategia: "tabela",
    mensagem_deteccao: "Este arquivo pertence ao Matific.", turma_detectada: "3º Ano A",
    origem_nome: "conteudo", total_alunos: 3, total_linhas: 3, total_erros: 0, total_avisos: 0,
    erros_gerais: [],
    linhas: [
      linha(1, "Ana Beatriz Souza", {
        status: "exato", aluno_id: 10, aluno_nome: "Ana Beatriz Souza", similaridade: 100,
        alternativas: [{ aluno_id: 10, nome: "Ana Beatriz Souza", turma: "3º Ano A", similaridade: 100 }],
      }),
      linha(2, "Crianca Ficticia Esquecida", {
        status: "ignorado", motivo: "conta_esquecida", aluno_id: null, aluno_nome: null,
        similaridade: null, alternativas: [],
      }),
      linha(3, "Crianca Ficticia Conta Velha", {
        status: "ignorado", motivo: "identidade_aposentada", aluno_id: null, aluno_nome: null,
        similaridade: null, alternativas: [],
      }),
    ],
  } as unknown as Analise;
}

describe("prévia: linha que a confirmação ignora", () => {
  it("diz por que será ignorada, sem destino, e fica fora da importação", async () => {
    const u = userEvent.setup();
    responder("GET", URL_HIST, []);
    responder("GET", URL_TURMAS, [turmaFake()]);
    responder("UPLOAD", URL_ANALISAR, analise());
    renderComApp(<ImportacaoLoteProvider><Importacoes /></ImportacaoLoteProvider>,
                 { rota: "/importacoes" });
    await screen.findByText("Nenhuma importação ainda");
    await u.click(await screen.findByRole("button", { name: /Um por vez/ }));
    await u.type(screen.getByRole("textbox"), "relatorio ficticio");
    await u.click(screen.getByRole("button", { name: /Analisar e ver prévia/ }));
    await screen.findByText("Prévia da importação");

    expect(screen.getByText("Conta de aluno excluído permanentemente: será ignorada")).toBeInTheDocument();
    expect(screen.getByText("Conta aposentada: será ignorada")).toBeInTheDocument();
    expect(screen.getByText(/peça o encerramento lá/)).toBeInTheDocument();
    expect(screen.queryByText("Novo aluno")).toBeNull();
    // Nenhum destino a escolher nas duas: só a linha do vínculo tem o seletor.
    expect(screen.queryByRole("combobox", { name: "Destino de Crianca Ficticia Esquecida" })).toBeNull();
    expect(screen.queryByRole("combobox", { name: "Destino de Crianca Ficticia Conta Velha" })).toBeNull();
    expect(screen.getByRole("combobox", { name: "Destino de Ana Beatriz Souza" })).toBeInTheDocument();

    await u.click(screen.getByRole("button", { name: "Sim, importar" }));
    const confirmacao = await screen.findByRole("dialog", { name: "Gravar esta importação?" });
    expect(confirmacao).toHaveTextContent("1 vinculado(s) a um aluno já cadastrado");
    expect(confirmacao).not.toHaveTextContent(/aluno\(s\) novo/);
    expect(within(confirmacao).queryByText(/criad/)).toBeNull();
  });
});

describe("lote: arquivo que a confirmação ignora", () => {
  it("vem ignorado, com o porquê, e não como aluno novo", async () => {
    const u = userEvent.setup();
    const individual = {
      ...analise(), formato: "leituras", plataforma: "elefante",
      linhas: [{ numero: 1, nome: "Crianca Ficticia Esquecida",
                 dados: { livro: "Livro Ficticio", data_leitura: "2026-10-01" }, erros: [], avisos: [],
                 correspondencia: { status: "ignorado", motivo: "conta_esquecida", aluno_id: null,
                                    aluno_nome: null, similaridade: null, alternativas: [] } }],
    } as unknown as Analise;
    responder("GET", URL_TURMAS, [turmaFake()]);
    responder("UPLOAD", URL_ANALISAR, individual);
    const { container } = renderComApp(<ImportacaoLoteProvider><ImportacaoLote /></ImportacaoLoteProvider>,
                                       { rota: "/importacoes" });
    const input = await screen.findByText(/Arraste os relatórios em PDF aqui/)
      .then(() => container.querySelector('input[type="file"]') as HTMLInputElement);
    fireEvent.change(input, {
      target: { files: [new File(["%PDF-1.4"], "aluno-ficticio.pdf", { type: "application/pdf" })] },
    });
    await u.click(await screen.findByRole("button", { name: /Analisar 1 arquivo/ }));
    await screen.findByText("Conferência da importação");
    expect(screen.getByText(/Conta de aluno excluído permanentemente: será ignorada/)).toBeInTheDocument();
    expect(screen.queryByText(/Aluno novo — será criado nesta turma/)).toBeNull();
    expect(screen.queryByRole("button", { name: /Importar todos \(1\)/ })).toBeNull();
  });
});
