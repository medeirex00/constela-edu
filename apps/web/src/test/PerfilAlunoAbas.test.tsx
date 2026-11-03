/**
 * Ficha do aluno na identidade visual v2 — dados fictícios.
 *
 * As abas são o componente acessível (tablist/tab/tabpanel); o professor continua
 * só com o Perfil (sem abas de gestão nem "Ver evolução"); a falha mostra o motivo
 * com "Tentar de novo"; e o modo de normalização saiu do topo para dentro de
 * "Como esta nota foi calculada" (nada foi removido).
 */
import { describe, expect, it } from "vitest";
import { Route, Routes } from "react-router-dom";

import PerfilAluno from "../pages/PerfilAluno";
import { api, renderComApp, responder, responderErro, screen, userEvent, usuarioFake, waitFor } from "./utils";

const ALUNO = {
  id: 10, nome: "Ana Beatriz Ficticia", turma: "3º Ano A", ano_escolar: "3º Ano",
  status: "ativo", foto_url: null, numero_chamada: 4,
};

function perfil() {
  return {
    aluno: ALUNO, posicao: 2, nota_matific: 80, nota_elefante: 70, nota_geral: 75,
    ficha: { ra: "000111222" },
    calculada_em: null,
    detalhes: {
      modo_normalizacao: "auto",
      matific: { indicadores: [], nota: 80 },
      elefante: { indicadores: [], questoes: null, nota: 70 },
      geral: { pesos: { matific: 50, elefante: 50 }, nota: 75 },
    },
  };
}

function montar(usuario = usuarioFake({ cargo: "coordenador" })) {
  renderComApp(
    <Routes>
      <Route path="/alunos/:id" element={<PerfilAluno />} />
    </Routes>,
    { rota: "/alunos/10", usuario },
  );
}

describe("Perfil do aluno (v2)", () => {
  it("gestão: abas acessíveis; trocar de aba mostra o painel e busca o histórico", async () => {
    responder("GET", "/escolas/1/alunos/10/perfil", perfil());
    responder("GET", "/escolas/1/gamificacao/alunos/10", null);
    responder("GET", /\/escolas\/1\/alunos\/10\/leituras/, {
      periodo: { chave: "tudo", rotulo: "Todo o período", inicio: null, fim: null },
      resumo: { total_livros: 0, pontos: 0, tempo_total_min: 0 },
      itens: [],
    });
    montar();

    const lista = await screen.findByRole("tablist", { name: "Seções do perfil do aluno" });
    expect(lista).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: "Ana Beatriz Ficticia" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Perfil" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tabpanel", { name: "Perfil" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Ver evolução/ })).toHaveAttribute("href", "/alunos/10/evolucao");
    expect(screen.getByText("2º no ranking")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("tab", { name: "Histórico de Leituras" }));
    expect(screen.getByRole("tab", { name: "Histórico de Leituras" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tabpanel", { name: "Histórico de Leituras" })).toBeInTheDocument();
    await waitFor(() =>
      expect(api.mock.calls.some(([c]) => String(c).startsWith("/escolas/1/alunos/10/leituras"))).toBe(true));
    expect(await screen.findByText("Nenhuma leitura no período")).toBeInTheDocument();
  });

  it("professor: só o Perfil, sem abas de gestão nem 'Ver evolução'", async () => {
    responder("GET", "/escolas/1/alunos/10/perfil", perfil());
    responder("GET", "/escolas/1/gamificacao/alunos/10", null);
    montar(usuarioFake({ cargo: "professor" }));

    expect(await screen.findByText("Como esta nota foi calculada")).toBeInTheDocument();
    expect(screen.queryByRole("tablist")).toBeNull();
    expect(screen.queryByRole("tab", { name: "Histórico de Leituras" })).toBeNull();
    expect(screen.queryByRole("link", { name: /Ver evolução/ })).toBeNull();
  });

  it("o modo de normalização aparece no cálculo da nota, não mais como selo no topo", async () => {
    responder("GET", "/escolas/1/alunos/10/perfil", perfil());
    responder("GET", "/escolas/1/gamificacao/alunos/10", null);
    montar();

    const texto = await screen.findByText(/Normalização dos indicadores:/);
    expect(texto).toHaveTextContent("Normalização dos indicadores: automática.");
    expect(screen.queryByText(/^Normalização: /)).toBeNull();
    // A ficha minimizada continua só com o RA.
    expect(screen.getByText("000111222")).toBeInTheDocument();
  });

  it("Leitura por nível ocupa a largura toda quando não há ficha para mostrar", async () => {
    const leituraNiveis = {
      faixas: [{ codigo: "pre", nome: "Pré-Leitor", quantidade: 2, pontos_por_livro: 1.5, pontos: 3, percentual: 100 }],
      total_livros: 2, pontos_dificuldade: 3, faixa_predominante: "Pré-Leitor",
    };
    // Sem ficha: o cartão não reserva a 3ª coluna (antes ficava um buraco ao lado).
    responder("GET", "/escolas/1/alunos/10/perfil", { ...perfil(), ficha: {}, leitura_niveis: leituraNiveis });
    responder("GET", "/escolas/1/gamificacao/alunos/10", null);
    montar();
    const titulo = await screen.findByRole("heading", { name: "Leitura por nível" });
    expect(titulo.closest("[class~='lg:col-span-3']")).not.toBeNull();
    expect(screen.queryByRole("heading", { name: "Ficha cadastral" })).toBeNull();
  });

  it("com ficha, Leitura por nível divide a linha com a Ficha cadastral", async () => {
    const leituraNiveis = {
      faixas: [{ codigo: "pre", nome: "Pré-Leitor", quantidade: 2, pontos_por_livro: 1.5, pontos: 3, percentual: 100 }],
      total_livros: 2, pontos_dificuldade: 3, faixa_predominante: "Pré-Leitor",
    };
    responder("GET", "/escolas/1/alunos/10/perfil", { ...perfil(), leitura_niveis: leituraNiveis });
    responder("GET", "/escolas/1/gamificacao/alunos/10", null);
    montar();
    const titulo = await screen.findByRole("heading", { name: "Leitura por nível" });
    expect(titulo.closest("[class~='lg:col-span-2']")).not.toBeNull();
    expect(screen.getByRole("heading", { name: "Ficha cadastral" })).toBeInTheDocument();
  });

  it("conquistas: concordância da sequência e nome das próximas com dica completa", async () => {
    const conquista = (codigo: string, nome: string, atingida: boolean, progresso: number) => ({
      codigo, nome, icone: "🎯", descricao: `Descrição de ${nome}`, criterio: "acertos",
      unidade: "questões", xp: 100, raridade: "comum", limite: 10, progresso,
      pct: progresso * 10, faltam: 10 - progresso, atingida,
    });
    responder("GET", "/escolas/1/alunos/10/perfil", perfil());
    responder("GET", "/escolas/1/gamificacao/alunos/10", {
      xp: 300, xp_conquistas: 100, nivel: 3, xp_para_proximo: 40, sequencia_semanas: 1,
      total_conquistas: 1,
      conquistas: [
        conquista("a", "Primeira Leitura", true, 10),
        conquista("b", "Craque das Questões", false, 6),
      ],
    });
    montar();

    // "1 semana seguida", não "1 semana seguidas".
    expect(await screen.findByText("1 semana")).toBeInTheDocument();
    expect(screen.getByText("seguida com atividade")).toBeInTheDocument();
    expect(screen.queryByText("seguidas com atividade")).toBeNull();
    // Próxima conquista: o nome completo também na dica (antes era cortado sem dica).
    expect(screen.getByTitle("Craque das Questões")).toHaveTextContent("Craque das Questões");
    // O XP de cada conquista continua ao lado (ou logo abaixo) do nome.
    expect(screen.getAllByText("+100 XP")).toHaveLength(2);
  });

  it("conquistas: sequência de várias semanas no plural", async () => {
    responder("GET", "/escolas/1/alunos/10/perfil", perfil());
    responder("GET", "/escolas/1/gamificacao/alunos/10", {
      xp: 0, xp_conquistas: 0, nivel: 1, xp_para_proximo: 100, sequencia_semanas: 3,
      total_conquistas: 0, conquistas: [],
    });
    montar();
    expect(await screen.findByText("3 semanas")).toBeInTheDocument();
    expect(screen.getByText("seguidas com atividade")).toBeInTheDocument();
  });

  it("falha ao carregar o perfil: mostra o motivo e tenta de novo", async () => {
    responderErro("GET", "/escolas/1/alunos/10/perfil", 500, "Banco indisponível");
    responder("GET", "/escolas/1/gamificacao/alunos/10", null);
    montar();

    expect(await screen.findByText("Banco indisponível", undefined, { timeout: 4000 })).toBeInTheDocument();
    responder("GET", "/escolas/1/alunos/10/perfil", perfil());
    await userEvent.click(screen.getByRole("button", { name: "Tentar de novo" }));
    expect(await screen.findByRole("heading", { level: 1, name: "Ana Beatriz Ficticia" })).toBeInTheDocument();
  });
});
