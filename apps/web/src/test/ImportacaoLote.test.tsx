import { describe, expect, it } from "vitest";

import { ImportacaoLoteProvider } from "../context/ImportacaoLoteContext";
import type { Analise } from "../lib/types";
import ImportacaoLote from "../pages/ImportacaoLote";
import {
  api,
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

// Relatório individual fictício já casado com um aluno existente (alta
// confiança): no lote ele vira "Pronto" e é importado sem intervenção.
function analiseFake(): Analise {
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
        correspondencia: {
          status: "exato",
          aluno_id: 10,
          aluno_nome: "Aluno Ficticio Teste",
          similaridade: 100,
          alternativas: [],
        },
      },
    ],
  } as unknown as Analise;
}

function montar() {
  return (
    <ImportacaoLoteProvider>
      <ImportacaoLote />
    </ImportacaoLoteProvider>
  );
}

async function importarUmArquivo() {
  const u = userEvent.setup();
  responder("GET", URL_TURMAS, [turmaFake()]);
  responder("UPLOAD", URL_ANALISAR, analiseFake());
  responder("POST", URL_CONFIRMAR, { mensagem: "ok", importacao_id: 1, qtd_alunos: 1, qtd_erros: 0, avisos: [] });
  const { container } = renderComApp(montar(), { rota: "/importacoes" });
  const input = await screen.findByText(/Arraste os relatórios em PDF aqui/)
    .then(() => container.querySelector('input[type="file"]') as HTMLInputElement);
  fireEvent.change(input, {
    target: { files: [new File(["%PDF-1.4"], "aluno-ficticio.pdf", { type: "application/pdf" })] },
  });
  await u.click(await screen.findByRole("button", { name: /Analisar 1 arquivo/ }));
  await u.click(await screen.findByRole("button", { name: /Importar todos \(1\)/ }));
  // "Importar todos" só abre a confirmação: nada é gravado antes dela.
  const confirmacao = await screen.findByRole("dialog", { name: "Gravar 1 arquivo(s)?" });
  expect(confirmacao).toHaveTextContent("1 arquivo(s) prontos entram na importação");
  expect(api.mock.calls.some(([caminho]) => caminho === URL_CONFIRMAR)).toBe(false);
  await u.click(within(confirmacao).getByRole("button", { name: "Gravar importação" }));
  return u;
}

describe("Importação em lote — recálculo final", () => {
  it("quando o /recalcular falha, o relatório diz que as notas não foram recalculadas e deixa refazer", async () => {
    responderErro("POST", URL_RECALCULAR, 500, "Erro interno ao recalcular");
    const u = await importarUmArquivo();

    expect(await screen.findByText("O recálculo das notas e dos rankings falhou.")).toBeInTheDocument();
    expect(screen.getByText("Importação em lote gravada, mas as notas não foram recalculadas")).toBeInTheDocument();
    expect(screen.queryByText("Importação em lote concluída")).toBeNull();
    expect(screen.getByText(/Detalhe: Erro interno ao recalcular/)).toBeInTheDocument();
    // O arquivo continua contado como importado (os dados estão gravados).
    expect(screen.getByText("Importados")).toBeInTheDocument();

    // Refazer: agora o recálculo responde e o aviso some.
    responder("POST", URL_RECALCULAR, { mensagem: "Notas recalculadas para 1 aluno(s).", alunos: 1 });
    await u.click(screen.getByRole("button", { name: /Recalcular agora/ }));
    expect(await screen.findByText(/Notas e rankings recalculados: Notas recalculadas para 1 aluno\(s\)\./))
      .toBeInTheDocument();
    expect(screen.queryByText("O recálculo das notas e dos rankings falhou.")).toBeNull();
    expect(screen.getByText("Importação em lote concluída")).toBeInTheDocument();
    const chamadas = api.mock.calls.filter(([caminho]) => caminho === URL_RECALCULAR);
    expect(chamadas).toHaveLength(2);
  });

  it("com o /recalcular respondendo, o relatório fica como concluído e diz que recalculou", async () => {
    responder("POST", URL_RECALCULAR, { mensagem: "Notas recalculadas para 1 aluno(s).", alunos: 1 });
    await importarUmArquivo();

    expect(await screen.findByText("Importação em lote concluída")).toBeInTheDocument();
    expect(screen.getByText(/Notas e rankings recalculados/)).toBeInTheDocument();
    expect(screen.queryByText(/O recálculo das notas e dos rankings falhou/)).toBeNull();
    expect(screen.queryByRole("button", { name: /Recalcular agora/ })).toBeNull();
  });
});

describe("Importação em lote — política de criação da escola", () => {
  async function conferir(analise: Analise) {
    const u = userEvent.setup();
    responder("GET", URL_TURMAS, [turmaFake()]);
    responder("UPLOAD", URL_ANALISAR, analise);
    const { container } = renderComApp(montar(), { rota: "/importacoes" });
    const input = await screen.findByText(/Arraste os relatórios em PDF aqui/)
      .then(() => container.querySelector('input[type="file"]') as HTMLInputElement);
    fireEvent.change(input, {
      target: { files: [new File(["%PDF-1.4"], "aluno-ficticio.pdf", { type: "application/pdf" })] },
    });
    await u.click(await screen.findByRole("button", { name: /Analisar 1 arquivo/ }));
    await screen.findByText("Conferência da importação");
  }

  it("com 'bloquear', a conferência avisa que aluno sem ficha não é criado", async () => {
    await conferir({ ...analiseFake(), criacao_bloqueada_por_politica: true });
    expect(screen.getByText(/A matrícula desta escola vem da Lista Piloto/)).toBeInTheDocument();
  });

  it("sem a política, a conferência não mostra o aviso", async () => {
    await conferir(analiseFake());
    expect(screen.queryByText(/A matrícula desta escola vem da Lista Piloto/)).toBeNull();
  });
});
