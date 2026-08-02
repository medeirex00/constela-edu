import { describe, expect, it } from "vitest";

import Importacoes from "../pages/Importacoes";
import { ImportacaoLoteProvider } from "../context/ImportacaoLoteContext";
import type { Analise, Importacao, ResultadoImportacao } from "../lib/types";
import {
  renderComApp,
  responder,
  responderErro,
  screen,
  turmaFake,
  userEvent,
} from "./utils";

const URL_HIST = "/escolas/1/importacoes";
const URL_TURMAS = "/escolas/1/turmas";
const URL_ANALISAR = "/escolas/1/importacoes/analisar";
const URL_CONFIRMAR = "/escolas/1/importacoes/confirmar";

// A tela usa useImportacaoLote(), cujo Provider fica ACIMA do Layout no app real
// (não dentro do AppProvider). Como o harness só injeta AppProvider + Router,
// envolvemos a tela no provider aqui — o AppProvider externo (do renderComApp)
// continua acima, então useApp() dentro do provider funciona.
function montar() {
  return (
    <ImportacaoLoteProvider>
      <Importacoes />
    </ImportacaoLoteProvider>
  );
}

function importacaoFake(over: Partial<Importacao> = {}): Importacao {
  return {
    id: 1,
    plataforma: "matific",
    tipo: "Leaderboard mensal",
    arquivo_original: "relatorio.pdf",
    qtd_alunos: 37,
    qtd_erros: 0,
    tempo_ms: 1200,
    status: "ok",
    created_at: "2026-07-01T12:00:00Z",
    usuario_nome: "Prof. Mariana",
    ...over,
  };
}

// Prévia com um aluno de correspondência exata (formato de leaderboard, não
// "leituras"), suficiente para renderizar a tabela e habilitar a confirmação.
function analiseFake(): Analise {
  return {
    plataforma: "matific",
    formato: "leaderboard",
    tipo: "leaderboard",
    arquivo_token: "tok-123",
    arquivo_nome: "relatorio.pdf",
    estrategia: "tabela",
    mensagem_deteccao: "Este arquivo pertence ao Matific.",
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
        nome: "Ana Beatriz Souza",
        dados: { atividades: 42, pontuacao_media: 85, estrelas: 120 },
        erros: [],
        avisos: [],
        correspondencia: {
          status: "exato",
          aluno_id: 10,
          aluno_nome: "Ana Beatriz Souza",
          similaridade: 100,
          alternativas: [
            { aluno_id: 10, nome: "Ana Beatriz Souza", turma: "3º Ano A", similaridade: 100 },
          ],
        },
      },
    ],
  };
}

describe("Importacoes", () => {
  it("mostra o histórico de importações da escola", async () => {
    responder("GET", URL_HIST, [
      importacaoFake(),
      importacaoFake({ id: 2, plataforma: "elefante", tipo: "Relatório individual", qtd_alunos: 12, qtd_erros: 2, usuario_nome: "Coord. Ana" }),
    ]);
    responder("GET", URL_TURMAS, [turmaFake()]);

    renderComApp(montar(), { rota: "/importacoes" });

    expect(await screen.findByText("Leaderboard mensal")).toBeInTheDocument();
    expect(screen.getByText("Relatório individual")).toBeInTheDocument();
    expect(screen.getByText("Prof. Mariana")).toBeInTheDocument();
    expect(screen.getByText("37")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Histórico" })).toBeInTheDocument();
  });

  it("mostra o estado vazio quando não há importações", async () => {
    responder("GET", URL_HIST, []);
    responder("GET", URL_TURMAS, [turmaFake()]);

    renderComApp(montar(), { rota: "/importacoes" });

    expect(await screen.findByText("Nenhuma importação ainda")).toBeInTheDocument();
    expect(
      screen.getByText("O histórico aparecerá aqui após a primeira importação."),
    ).toBeInTheDocument();
  });

  it("mostra a falha quando o histórico não carrega", async () => {
    responderErro("GET", URL_HIST, 500, "Erro interno");
    responder("GET", URL_TURMAS, [turmaFake()]);

    renderComApp(montar(), { rota: "/importacoes" });

    expect(await screen.findByText("Não foi possível carregar")).toBeInTheDocument();
    expect(screen.getByText("Erro interno")).toBeInTheDocument();
  });

  it("analisa o texto colado, mostra a prévia e confirma a importação", async () => {
    const u = userEvent.setup();
    responder("GET", URL_HIST, []);
    responder("GET", URL_TURMAS, [turmaFake()]);
    responder("UPLOAD", URL_ANALISAR, analiseFake());
    const resultado: ResultadoImportacao = {
      mensagem: "Importação concluída com sucesso.",
      importacao_id: 99,
      qtd_alunos: 1,
      qtd_erros: 0,
      avisos: [],
    };
    responder("POST", URL_CONFIRMAR, resultado);

    renderComApp(montar(), { rota: "/importacoes" });

    // Espera a tela terminar de carregar (histórico vazio) antes de interagir.
    await screen.findByText("Nenhuma importação ainda");

    // A página abre por padrão em "Matrículas da escola"; este teste é do envio
    // individual, então troca para a aba "Um por vez" primeiro.
    await u.click(await screen.findByRole("button", { name: /Um por vez/ }));

    // A área de texto é o único textbox do formulário de envio individual.
    await u.type(screen.getByRole("textbox"), "Ana Beatriz Souza 42");
    await u.click(screen.getByRole("button", { name: /Analisar e ver prévia/ }));

    // Prévia renderizada com o aluno e a correspondência encontrada.
    expect(await screen.findByText("Prévia da importação")).toBeInTheDocument();
    expect(screen.getByText("Ana Beatriz Souza")).toBeInTheDocument();
    expect(screen.getByText("Vinculado automaticamente")).toBeInTheDocument();

    // Confirma e vê a mensagem de sucesso da gravação.
    await u.click(screen.getByRole("button", { name: "Sim, importar" }));
    expect(
      await screen.findByText("Importação concluída com sucesso."),
    ).toBeInTheDocument();
  });

  async function previaComCorrespondencia(corr: Analise["linhas"][number]["correspondencia"]) {
    const u = userEvent.setup();
    responder("GET", URL_HIST, []);
    responder("GET", URL_TURMAS, [turmaFake()]);
    const analise = analiseFake();
    analise.linhas[0].correspondencia = corr;
    responder("UPLOAD", URL_ANALISAR, analise);
    renderComApp(montar(), { rota: "/importacoes" });
    await screen.findByText("Nenhuma importação ainda");
    await u.click(await screen.findByRole("button", { name: /Um por vez/ }));
    await u.type(screen.getByRole("textbox"), "Ana B 42");
    await u.click(screen.getByRole("button", { name: /Analisar e ver prévia/ }));
    await screen.findByText("Prévia da importação");
    return u;
  }

  it("'possível duplicata' (revisar) NÃO vem pré-selecionada como vínculo", async () => {
    await previaComCorrespondencia({
      status: "revisar", aluno_id: 10, aluno_nome: "Ana Beatriz Souza",
      similaridade: 90, motivo: "typo",
      alternativas: [{ aluno_id: 10, nome: "Ana Beatriz Souza",
                       turma: "3º Ano A", similaridade: 90 }],
    });
    expect(screen.getByText("Possível duplicata — requer revisão")).toBeInTheDocument();
    // Segurança: o destino NÃO vem no aluno (grafia parecida nunca vira vínculo por
    // 1 clique) — fica em "Criar aluno novo…" até o gestor escolher.
    const destino = screen.getByRole("combobox",
      { name: /Destino de/ }) as HTMLSelectElement;
    expect(destino.value).toBe("criar");
  });

  it("'bloqueado por conflito' aparece com o rótulo certo", async () => {
    await previaComCorrespondencia({
      status: "bloqueado", aluno_id: null, aluno_nome: null,
      similaridade: null, alternativas: [],
    });
    expect(
      screen.getByText("Bloqueado por conflito de identidade"),
    ).toBeInTheDocument();
  });
});
