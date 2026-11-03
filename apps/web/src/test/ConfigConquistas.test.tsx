/**
 * Editar conquistas (identidade visual v2): linhas-cartão com o interruptor de
 * ativa (checkbox nativo "Ativar {nome}"), setas e ações com o NOME da conquista
 * no rótulo, remoção com confirmação, aviso de alteração pendente como STATUS (não
 * como erro) e o contrato do PUT inalterado: a lista INTEIRA, na ordem da tela,
 * com `codigo` vazio para a conquista nova e o XP sugerido ao trocar a raridade.
 */
import { describe, expect, it } from "vitest";

import ConfigConquistas from "../pages/configuracoes/ConfigConquistas";
import { api, renderComApp, responder, screen, userEvent, usuarioFake, waitFor, within } from "./utils";

const URL_DEF = "/escolas/1/gamificacao/conquistas/definicoes";

function definicao(over: Record<string, unknown>) {
  return {
    codigo: "c", nome: "C", icone: "🏅", descricao: "", objetivo: "", indicador: "livros_unicos",
    limite: 10, plataforma: "", xp: 100, raridade: "comum", ativa: true, criada_em: "2026-09-01",
    ...over,
  };
}

function definicoesFake() {
  return {
    conquistas: [
      definicao({ codigo: "primeira_leitura", nome: "Primeira Leitura", icone: "📖", limite: 1 }),
      definicao({ codigo: "chuva_estrelas", nome: "Chuva de Estrelas", icone: "⭐", indicador: "estrelas", limite: 300, xp: 500, raridade: "epica" }),
    ],
    indicadores: {
      livros_unicos: { rotulo: "Livros lidos", plataforma: "elefante", unidade: "livros" },
      estrelas: { rotulo: "Estrelas", plataforma: "matific", unidade: "estrelas" },
    },
    raridades: { comum: "Comum", rara: "Rara", epica: "Épica", lendaria: "Lendária" },
    xp_sugerido: { comum: 100, rara: 250, epica: 500, lendaria: 1000 },
  };
}

/** Responde o PUT devolvendo a lista recebida (como o backend) e guarda os corpos. */
function responderPut() {
  responder("PUT", URL_DEF, (_c: string, opcoes: RequestInit | FormData) => {
    const corpo = JSON.parse(String((opcoes as RequestInit).body));
    return { mensagem: "Conquistas atualizadas.", conquistas: corpo.conquistas };
  });
}

function corpoDoPut(): { conquistas: Array<Record<string, unknown>> } {
  const chamada = api.mock.calls.find(([caminho, opcoes]) =>
    caminho === URL_DEF && (opcoes as RequestInit | undefined)?.method === "PUT");
  expect(chamada).toBeDefined();
  return JSON.parse(String((chamada?.[1] as RequestInit).body));
}

describe("Editar conquistas", () => {
  it("desativar marca alteração pendente como status (não erro) e o PUT leva a lista inteira", async () => {
    responder("GET", URL_DEF, definicoesFake());
    responderPut();
    const u = userEvent.setup();
    renderComApp(<ConfigConquistas />);

    const ativar = await screen.findByRole("checkbox", { name: "Ativar Chuva de Estrelas" });
    expect(ativar).toBeChecked();
    const salvar = screen.getByRole("button", { name: "Salvar alterações" });
    expect(salvar).toBeDisabled();

    await u.click(ativar);
    expect(ativar).not.toBeChecked();
    const pendente = screen.getByText("Há alterações não salvas — clique em “Salvar alterações” para aplicá-las.");
    expect(pendente.closest("[role=status]")).not.toBeNull();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();

    await u.click(salvar);
    expect(await screen.findByText("Conquistas atualizadas.")).toBeInTheDocument();
    const corpo = corpoDoPut();
    expect(corpo.conquistas.map((c) => c.codigo)).toEqual(["primeira_leitura", "chuva_estrelas"]);
    expect(corpo.conquistas[1].ativa).toBe(false);
    expect(screen.queryByText(/Há alterações não salvas/)).not.toBeInTheDocument();
  });

  it("cada linha mostra o critério e o XP; a descrição tem o texto completo na dica", async () => {
    const dados = definicoesFake();
    dados.conquistas[0] = { ...dados.conquistas[0], descricao: "Concluiu seu primeiro livro no Elefante Letrado." };
    responder("GET", URL_DEF, dados);
    renderComApp(<ConfigConquistas />);

    const linha = (await screen.findByRole("checkbox", { name: "Ativar Primeira Leitura" })).closest("li") as HTMLElement;
    expect(within(linha).getByText("Livros lidos ≥ 1")).toBeInTheDocument();
    expect(within(linha).getByText("100")).toBeInTheDocument();
    // A descrição pode ser cortada em 2 linhas: o texto completo fica na dica.
    expect(within(linha).getByText("Concluiu seu primeiro livro no Elefante Letrado."))
      .toHaveAttribute("title", "Concluiu seu primeiro livro no Elefante Letrado.");
    // Nenhuma ação some: editar, remover e o interruptor continuam em cada linha.
    expect(within(linha).getByRole("button", { name: "Editar Primeira Leitura" })).toBeInTheDocument();
    expect(within(linha).getByRole("button", { name: "Remover Primeira Leitura" })).toBeInTheDocument();
  });

  it("descer uma conquista muda a ordem enviada (a ordem é a de exibição)", async () => {
    responder("GET", URL_DEF, definicoesFake());
    responderPut();
    const u = userEvent.setup();
    renderComApp(<ConfigConquistas />);

    await u.click(await screen.findByRole("button", { name: "Descer Primeira Leitura" }));
    expect(screen.getByRole("button", { name: "Subir Primeira Leitura" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Subir Chuva de Estrelas" })).toBeDisabled();
    // No celular as setas têm 40 px (eram 28 px coladas: fácil tocar a errada).
    for (const nome of ["Subir Primeira Leitura", "Descer Primeira Leitura"]) {
      expect(screen.getByRole("button", { name: nome })).toHaveClass("h-7", "w-7", "max-sm:h-10", "max-sm:w-10");
    }
    expect(screen.getByRole("button", { name: "Subir Primeira Leitura" }).parentElement).toHaveClass("max-sm:gap-2");
    await u.click(screen.getByRole("button", { name: "Salvar alterações" }));
    await waitFor(() => expect(corpoDoPut().conquistas.map((c) => c.codigo))
      .toEqual(["chuva_estrelas", "primeira_leitura"]));
  });

  it("remover pede confirmação; cancelar mantém, confirmar tira da lista (só vale ao salvar)", async () => {
    responder("GET", URL_DEF, definicoesFake());
    responderPut();
    const u = userEvent.setup();
    renderComApp(<ConfigConquistas />);

    await u.click(await screen.findByRole("button", { name: "Remover Primeira Leitura" }));
    let dialogo = await screen.findByRole("dialog", { name: "Remover conquista?" });
    await u.click(within(dialogo).getByRole("button", { name: "Cancelar" }));
    expect(screen.getByRole("checkbox", { name: "Ativar Primeira Leitura" })).toBeInTheDocument();

    await u.click(screen.getByRole("button", { name: "Remover Primeira Leitura" }));
    dialogo = await screen.findByRole("dialog", { name: "Remover conquista?" });
    expect(dialogo).toHaveTextContent("“Primeira Leitura” sai da lista.");
    await u.click(within(dialogo).getByRole("button", { name: "Remover" }));
    expect(screen.queryByRole("checkbox", { name: "Ativar Primeira Leitura" })).not.toBeInTheDocument();
    // Nada foi gravado ainda: só com "Salvar alterações".
    expect(api.mock.calls.some(([, o]) => (o as RequestInit | undefined)?.method === "PUT")).toBe(false);

    await u.click(screen.getByRole("button", { name: "Salvar alterações" }));
    await waitFor(() => expect(corpoDoPut().conquistas.map((c) => c.codigo)).toEqual(["chuva_estrelas"]));
  });

  it("nova conquista: XP sugerido pela raridade, ícone por atalho e código vazio no PUT", async () => {
    responder("GET", URL_DEF, definicoesFake());
    responderPut();
    const u = userEvent.setup();
    renderComApp(<ConfigConquistas />);
    await screen.findByRole("checkbox", { name: "Ativar Primeira Leitura" });

    await u.click(screen.getByRole("button", { name: "Nova conquista" }));
    const dialogo = await screen.findByRole("dialog", { name: "Nova conquista" });
    const adicionar = within(dialogo).getByRole("button", { name: "Adicionar" });
    expect(adicionar).toBeDisabled();

    await u.type(within(dialogo).getByLabelText("Nome *"), "Leitor de Ouro");
    await u.selectOptions(within(dialogo).getByLabelText("Raridade"), "lendaria");
    expect(within(dialogo).getByLabelText("XP concedido")).toHaveValue(1000);
    await u.click(within(dialogo).getByRole("button", { name: "Usar o ícone 🚀" }));
    expect(within(dialogo).getByLabelText("Ícone (emoji)")).toHaveValue("🚀");
    expect(adicionar).toBeEnabled();
    await u.click(adicionar);

    expect(await screen.findByRole("checkbox", { name: "Ativar Leitor de Ouro" })).toBeChecked();
    await u.click(screen.getByRole("button", { name: "Salvar alterações" }));
    await waitFor(() => expect(corpoDoPut().conquistas).toHaveLength(3));
    const nova = corpoDoPut().conquistas[2];
    expect(nova).toMatchObject({ codigo: "", nome: "Leitor de Ouro", raridade: "lendaria", xp: 1000, icone: "🚀" });
  });

  it("volta para o grupo de onde veio: Critérios na coordenação, Configurações no administrador", async () => {
    // A coordenação chega por Gestão › Regras de pontuação (Critérios, Simulador,
    // Editar conquistas); o mural /conquistas fica em Escola › Reconhecimento, outro
    // grupo — voltar para ele a levava a uma seção por onde ela não passou.
    responder("GET", URL_DEF, definicoesFake());
    const { unmount } = renderComApp(<ConfigConquistas />);
    expect(await screen.findByRole("link", { name: "Critérios" })).toHaveAttribute("href", "/metricas");
    expect(screen.queryByRole("link", { name: "Conquistas" })).toBeNull();
    unmount();

    responder("GET", URL_DEF, definicoesFake());
    renderComApp(<ConfigConquistas />, { usuario: usuarioFake({ cargo: "admin" }) });
    expect(await screen.findByRole("link", { name: "Configurações" })).toHaveAttribute("href", "/configuracoes");
  });
});
