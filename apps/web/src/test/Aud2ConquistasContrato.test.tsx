/**
 * G_MODULOS-1 (web) — conquistas e contrato de módulos da rede.
 *
 * Editar conquistas: a conquista de um módulo fora do plano da rede
 * (`plataformas_fora_do_plano` no GET) não aparece nem é oferecida no editor,
 * mas continua no PUT — senão salvar a apagaria, e ela não voltaria quando a rede
 * contratasse o módulo. As setas de ordem pulam as guardadas.
 *
 * Biblioteca: o filtro de plataforma não oferece o produto que a rede não tem.
 */
import { describe, expect, it } from "vitest";

import BibliotecaConquistas from "../pages/BibliotecaConquistas";
import ConfigConquistas from "../pages/configuracoes/ConfigConquistas";
import { api, renderComApp, responder, screen, userEvent, usuarioFake, waitFor, within } from "./utils";

const URL_DEF = "/escolas/1/gamificacao/conquistas/definicoes";

function definicao(over: Record<string, unknown>) {
  return {
    codigo: "c", nome: "C", icone: "🏅", descricao: "", objetivo: "", indicador: "livros_unicos",
    limite: 10, plataforma: "elefante", xp: 100, raridade: "comum", ativa: true, criada_em: "2026-09-01",
    ...over,
  };
}

function definicoesSoLeitura(fora: string[] | null = ["matific"]) {
  return {
    conquistas: [
      definicao({ codigo: "primeira_leitura", nome: "Primeira Leitura", limite: 1 }),
      definicao({ codigo: "chuva_estrelas", nome: "Chuva de Estrelas", indicador: "estrelas", plataforma: "matific", limite: 500 }),
      definicao({ codigo: "leitor_bronze", nome: "Leitor Bronze" }),
    ],
    indicadores: {
      livros_unicos: { rotulo: "Livros lidos", plataforma: "elefante", unidade: "livros" },
      estrelas: { rotulo: "Estrelas", plataforma: "matific", unidade: "estrelas" },
    },
    ...(fora ? { plataformas_fora_do_plano: fora } : {}),
    raridades: { comum: "Comum", rara: "Rara", epica: "Épica", lendaria: "Lendária" },
    xp_sugerido: { comum: 100, rara: 250, epica: 500, lendaria: 1000 },
  };
}

function responderPut() {
  responder("PUT", URL_DEF, (_c: string, opcoes: RequestInit | FormData) => {
    const corpo = JSON.parse(String((opcoes as RequestInit).body));
    return { mensagem: "Conquistas atualizadas.", conquistas: corpo.conquistas };
  });
}

function codigosDoPut(): string[] {
  const chamada = api.mock.calls.find(([caminho, opcoes]) =>
    caminho === URL_DEF && (opcoes as RequestInit | undefined)?.method === "PUT");
  expect(chamada).toBeDefined();
  const corpo = JSON.parse(String((chamada?.[1] as RequestInit).body));
  return corpo.conquistas.map((c: { codigo: string }) => c.codigo);
}

describe("Editar conquistas numa rede só com Leitura", () => {
  it("esconde a conquista do Matific, avisa que ela fica guardada e a devolve no PUT", async () => {
    responder("GET", URL_DEF, definicoesSoLeitura());
    responderPut();
    const u = userEvent.setup();
    renderComApp(<ConfigConquistas />);

    await screen.findByRole("checkbox", { name: "Ativar Primeira Leitura" });
    expect(screen.queryByText("Chuva de Estrelas")).not.toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: "Ativar Chuva de Estrelas" })).not.toBeInTheDocument();
    expect(screen.getByText(/1 conquista de um módulo que não faz parte do plano da rede fica guardada/))
      .toBeInTheDocument();

    await u.click(screen.getByRole("checkbox", { name: "Ativar Primeira Leitura" }));
    await u.click(screen.getByRole("button", { name: "Salvar alterações" }));
    await waitFor(() => expect(codigosDoPut())
      .toEqual(["primeira_leitura", "chuva_estrelas", "leitor_bronze"]));
  });

  it("o editor não oferece critério do Matific", async () => {
    responder("GET", URL_DEF, definicoesSoLeitura());
    const u = userEvent.setup();
    renderComApp(<ConfigConquistas />);

    await u.click(await screen.findByRole("button", { name: "Nova conquista" }));
    const dialogo = await screen.findByRole("dialog");
    const criterio = within(dialogo).getByRole("combobox", { name: /Critério/ });
    const opcoes = within(criterio).getAllByRole("option").map((o) => o.textContent);
    expect(opcoes).toEqual(["Livros lidos"]);
  });

  it("as setas trocam com a vizinha VISÍVEL (a guardada não conta)", async () => {
    responder("GET", URL_DEF, definicoesSoLeitura());
    responderPut();
    const u = userEvent.setup();
    renderComApp(<ConfigConquistas />);

    expect(await screen.findByRole("button", { name: "Descer Leitor Bronze" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Subir Primeira Leitura" })).toBeDisabled();
    await u.click(screen.getByRole("button", { name: "Descer Primeira Leitura" }));
    expect(screen.getByRole("button", { name: "Subir Leitor Bronze" })).toBeDisabled();
    await u.click(screen.getByRole("button", { name: "Salvar alterações" }));
    await waitFor(() => expect(codigosDoPut())
      .toEqual(["leitor_bronze", "chuva_estrelas", "primeira_leitura"]));
  });

  it("API antiga (sem o campo) segue mostrando tudo", async () => {
    responder("GET", URL_DEF, definicoesSoLeitura(null));
    renderComApp(<ConfigConquistas />);
    expect(await screen.findByRole("checkbox", { name: "Ativar Chuva de Estrelas" })).toBeInTheDocument();
    expect(screen.queryByText(/fica guardada/)).not.toBeInTheDocument();
  });
});

describe("Biblioteca de Conquistas e o contrato", () => {
  const biblioteca = {
    conquistas: [],
    estatisticas: {
      total: 0, ativas: 0, alunos: 0, total_desbloqueios: 0, pct_medio_conclusao: 0,
      mais_rara: null, mais_comum: null, maior_xp: null, ranking_desbloqueios: [],
    },
    raridades: { comum: "Comum" },
    indicadores: { livros_unicos: "Livros lidos" },
  };

  it("rede só com Leitura: o filtro de plataforma não oferece o Matific", async () => {
    responder("GET", "/escolas/1/gamificacao/biblioteca", biblioteca);
    renderComApp(<BibliotecaConquistas />, { usuario: usuarioFake({ modulos: ["leitura"] }) });
    const filtro = await screen.findByRole("combobox", { name: "Filtrar por plataforma" });
    const opcoes = within(filtro).getAllByRole("option").map((o) => o.textContent);
    expect(opcoes).toEqual(["Todas as plataformas", "Elefante Letrado", "Geral"]);
  });

  it("rede só com Matemática: o filtro não oferece o Elefante", async () => {
    responder("GET", "/escolas/1/gamificacao/biblioteca", biblioteca);
    renderComApp(<BibliotecaConquistas />, { usuario: usuarioFake({ modulos: ["matematica"] }) });
    const filtro = await screen.findByRole("combobox", { name: "Filtrar por plataforma" });
    const opcoes = within(filtro).getAllByRole("option").map((o) => o.textContent);
    expect(opcoes).toEqual(["Todas as plataformas", "Matific", "Geral"]);
  });
});
