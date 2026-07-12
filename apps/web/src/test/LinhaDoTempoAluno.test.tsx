import { describe, expect, it } from "vitest";

import LinhaDoTempoAluno from "../components/LinhaDoTempoAluno";
import { renderComApp, responder, screen, userEvent } from "./utils";

const ESCOLA = 1;
const ALUNO = 5;
const URL_ESP = `/escolas/${ESCOLA}/alunos/${ALUNO}/espelho`;
const URL_TL = `/escolas/${ESCOLA}/alunos/${ALUNO}/linha-do-tempo`;

function evento(over: Record<string, unknown> = {}) {
  return {
    id: 1,
    plataforma: "elefante",
    tipo_evento: "leitura",
    ocorrido_em: "2026-07-02T09:15:00",
    conteudo_titulo: "A Casa Amarela",
    habilidade: null,
    nivel_codigo: "D",
    acertos: null,
    erros: null,
    tentativas: null,
    pontuacao: null,
    tempo_segundos: 495,
    dados: { genero: "Aventura" },
    ...over,
  };
}

function espelho(over: Record<string, unknown> = {}) {
  return {
    espelho: {
      total_eventos: 2,
      primeira_atividade: "2026-06-15T10:00:00",
      ultima_atividade: "2026-07-02T09:15:00",
      tempo_total_segundos: 900,
      por_tipo: { leitura: 2 },
      por_plataforma: { elefante: 2 },
      ...over,
    },
  };
}

describe("LinhaDoTempoAluno", () => {
  it("mostra o resumo e os eventos agrupados por dia", async () => {
    responder("GET", URL_ESP, espelho());
    responder("GET", URL_TL, {
      itens: [
        evento(),
        evento({ id: 2, ocorrido_em: "2026-07-01T10:00:00",
                 conteudo_titulo: "O Pequeno Livro Azul", nivel_codigo: "K" }),
      ],
      proximo_cursor: null,
    });

    renderComApp(<LinhaDoTempoAluno escolaId={ESCOLA} alunoId={ALUNO} />,
                 { rota: "/alunos/5" });

    expect(await screen.findByText("A Casa Amarela")).toBeInTheDocument();
    expect(screen.getByText("O Pequeno Livro Azul")).toBeInTheDocument();
    // um cabeçalho por dia
    expect(screen.getByText("02/07/2026")).toBeInTheDocument();
    expect(screen.getByText("01/07/2026")).toBeInTheDocument();
    // resumo no topo
    expect(screen.getByText("Atividades registradas")).toBeInTheDocument();
  });

  it("carrega mais anexando a próxima página (cursor)", async () => {
    responder("GET", URL_ESP, espelho({ por_plataforma: {}, por_tipo: {} }));
    responder("GET", URL_TL, (caminho: string) =>
      caminho.includes("cursor=")
        ? { itens: [evento({ id: 9, conteudo_titulo: "Livro Página 2",
                             ocorrido_em: "2026-06-30T08:00:00" })],
            proximo_cursor: null }
        : { itens: [evento()], proximo_cursor: "2026-07-02T09:15:00|1" });

    renderComApp(<LinhaDoTempoAluno escolaId={ESCOLA} alunoId={ALUNO} />,
                 { rota: "/alunos/5" });

    expect(await screen.findByText("A Casa Amarela")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /carregar mais/i }));
    expect(await screen.findByText("Livro Página 2")).toBeInTheDocument();
  });

  it("mostra estado vazio quando não há eventos", async () => {
    responder("GET", URL_ESP, espelho({
      total_eventos: 0, primeira_atividade: null, ultima_atividade: null,
      tempo_total_segundos: 0, por_tipo: {}, por_plataforma: {} }));
    responder("GET", URL_TL, { itens: [], proximo_cursor: null });

    renderComApp(<LinhaDoTempoAluno escolaId={ESCOLA} alunoId={ALUNO} />,
                 { rota: "/alunos/5" });

    expect(await screen.findByText(/Nenhuma atividade no período/i)).toBeInTheDocument();
  });
});
