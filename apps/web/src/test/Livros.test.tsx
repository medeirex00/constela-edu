import { describe, expect, it, vi } from "vitest";

import Livros from "../pages/Livros";
import {
  api,
  renderComApp,
  responder,
  responderErro,
  screen,
  userEvent,
  usuarioFake,
  waitFor,
  within,
} from "./utils";

const URL_LIVROS = "/escolas/1/livros";
const ADMIN_GLOBAL = usuarioFake({ id: 99, nome: "Admin Constela", is_global: true, cargo: "admin" });

function livroFake(over = {}) {
  return {
    id: 7,
    titulo: "Laerte, o Gato Inerte",
    autor: null,
    nivel_codigo: "D",
    categoria: null,
    paginas: null,
    pontos: 1.2,
    leituras: 3,
    elefante_id: 8,
    nivel_fonte: "B",
    nivel_oficial: "B",
    word_count: 78,
    origem_nivel: "admin_global",
    atualizado_em: null,
    no_catalogo: true,
    divergente: true,
    editavel: false,
    vale_para_proximas_leituras: false,
    historico_preservado: true,
    leituras_atualizadas: 0,
    leituras_sem_nivel_congelado: 0,
    ...over,
  };
}

function paginaFake(itens: unknown[]) {
  return { total: itens.length, pagina: 1, por_pagina: 25, itens };
}

function chamadas(metodo: string, caminho: string) {
  return api.mock.calls.filter(
    ([c, opcoes]) => c === caminho && (opcoes as RequestInit | undefined)?.method === metodo,
  );
}

function corpoDoPatch() {
  return JSON.parse(String((chamadas("PATCH", `${URL_LIVROS}/7`)[0][1] as RequestInit).body));
}

/** Abre a edição do livro e troca o nível para B, informando o motivo. */
async function corrigirNivel(u: ReturnType<typeof userEvent.setup>) {
  await u.click(await screen.findByRole("button", { name: "Editar Laerte, o Gato Inerte" }));
  const dialogo = screen
    .getByText(/A correção vale para as próximas leituras/)
    .closest("div.space-y-3") as HTMLElement;
  await u.selectOptions(within(dialogo).getAllByRole("combobox")[0], "B");
  await u.type(
    screen.getByPlaceholderText("Ex.: nível conferido no catálogo oficial"),
    "Nível conferido no catálogo",
  );
  return dialogo;
}

describe("Livros", () => {
  it("coordenadora vê o catálogo oficial somente leitura, sem criar, editar nem ver divergência", async () => {
    responder("GET", URL_LIVROS, paginaFake([livroFake()]));
    renderComApp(<Livros />, { rota: "/livros" });

    expect(await screen.findByText("Laerte, o Gato Inerte")).toBeInTheDocument();
    expect(screen.getByText(/Catálogo oficial — somente leitura/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Novo livro/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Editar Laerte, o Gato Inerte" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Excluir Laerte, o Gato Inerte" })).toBeNull();
    expect(screen.queryByText("Divergente")).toBeNull();
    expect(screen.queryByText("Nível oficial")).toBeNull();
  });

  it("Admin Global vê o nível oficial e a divergência", async () => {
    responder("GET", URL_LIVROS, paginaFake([livroFake({ editavel: true })]));
    renderComApp(<Livros />, { rota: "/livros", usuario: ADMIN_GLOBAL });

    const linha = (await screen.findByText("Laerte, o Gato Inerte")).closest("tr") as HTMLElement;
    expect(within(linha).getByText("Divergente")).toBeInTheDocument();
    expect(within(linha).getByText("B")).toBeInTheDocument();          // nível oficial
    expect(screen.getByText("Nível oficial")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Novo livro/ })).toBeInTheDocument();
    expect(screen.queryByText(/somente leitura/)).toBeNull();
  });

  it("livro fora do catálogo mostra o nível do RELATÓRIO como relatório, não como oficial", async () => {
    // O nível de um livro fora do catálogo veio do relatório que a escola
    // enviou. A coluna "Nível oficial" não pode exibi-lo como se fosse do
    // Elefante — seria a escola escrevendo na tela que o Admin Global usa
    // para decidir a correção.
    responder(
      "GET",
      URL_LIVROS,
      paginaFake([livroFake({
        editavel: true, elefante_id: null, no_catalogo: false,
        nivel_oficial: null, nivel_fonte: "Z", divergente: true,
      })]),
    );
    renderComApp(<Livros />, { rota: "/livros", usuario: ADMIN_GLOBAL });

    const linha = (await screen.findByText("Laerte, o Gato Inerte")).closest("tr") as HTMLElement;
    expect(within(linha).getByText(/fora do catálogo/)).toBeInTheDocument();
    expect(within(linha).getByText(/relatório: Z/)).toBeInTheDocument();
    expect(within(linha).getByText("Divergente")).toBeInTheDocument();

    // E a edição não afirma um "nível oficial" que não existe.
    await userEvent.setup().click(screen.getByRole("button", { name: "Editar Laerte, o Gato Inerte" }));
    expect(await screen.findByText(/A correção vale para as próximas leituras/)).toBeInTheDocument();
    expect(screen.queryByText(/Nível oficial do Elefante/)).toBeNull();
  });

  it("a correção exige motivo e vale para as PRÓXIMAS leituras — sem prometer recálculo", async () => {
    // O nível congelado da leitura já existe: corrigir o catálogo não reescreve
    // o passado. A tela diz exatamente isso, com o texto do servidor, e não
    // oferece recálculo nenhum (não há o que realinhar).
    const aviso =
      "Correção registrada — ela vale para as PRÓXIMAS leituras. As leituras já registradas " +
      "guardam o nível que valia quando o aluno leu o livro.";
    responder("GET", URL_LIVROS, paginaFake([livroFake({ editavel: true })]));
    responder(
      "PATCH",
      `${URL_LIVROS}/7`,
      livroFake({
        nivel_codigo: "B", divergente: false, editavel: true,
        vale_para_proximas_leituras: true, aviso_correcao: aviso,
      }),
    );
    renderComApp(<Livros />, { rota: "/livros", usuario: ADMIN_GLOBAL });

    const u = userEvent.setup();
    await u.click(await screen.findByRole("button", { name: "Editar Laerte, o Gato Inerte" }));
    expect(await screen.findByText(/Nível oficial do Elefante: B/)).toBeInTheDocument();
    const dialogo = screen
      .getByText(/A correção vale para as próximas leituras/)
      .closest("div.space-y-3") as HTMLElement;
    await u.selectOptions(within(dialogo).getAllByRole("combobox")[0], "B");

    // Sem motivo: erro na tela e nada é enviado.
    await u.click(screen.getByRole("button", { name: "Salvar" }));
    expect(await screen.findByText(/Informe o motivo da correção de nível/)).toBeInTheDocument();
    expect(chamadas("PATCH", `${URL_LIVROS}/7`)).toHaveLength(0);

    await u.type(screen.getByPlaceholderText("Ex.: nível conferido no catálogo oficial"), "Nível conferido no catálogo");
    await u.click(screen.getByRole("button", { name: "Salvar" }));
    await waitFor(() => expect(chamadas("PATCH", `${URL_LIVROS}/7`)).toHaveLength(1));
    expect(corpoDoPatch()).toMatchObject({
      nivel_codigo: "B", motivo: "Nível conferido no catálogo", aplicar_ao_historico: false,
    });

    // A mensagem exibida é a do SERVIDOR (fonte única), não um texto paralelo.
    expect(await screen.findByText(new RegExp("PRÓXIMAS leituras"))).toBeInTheDocument();
    expect(screen.queryByText(/Recálculo pendente/)).toBeNull();
    expect(screen.queryByRole("button", { name: "Recalcular a escola agora" })).toBeNull();
  });

  it("só quando há leitura ANTIGA sem nível congelado a tela oferece o recálculo", async () => {
    // Leitura anterior ao congelamento segue o nível ATUAL do livro: é a única
    // que a correção ainda move — e a única razão para recalcular a escola.
    responder("GET", URL_LIVROS, paginaFake([livroFake({ editavel: true })]));
    responder("PATCH", `${URL_LIVROS}/7`, livroFake({
      nivel_codigo: "B", editavel: true, vale_para_proximas_leituras: true,
      leituras_sem_nivel_congelado: 2,
      aviso_correcao: "Correção registrada. 2 leitura(s) são anteriores ao congelamento do nível.",
    }));
    responder("POST", "/escolas/1/recalcular", { mensagem: "Notas recalculadas para 3 alunos." });
    renderComApp(<Livros />, { rota: "/livros", usuario: ADMIN_GLOBAL });

    const u = userEvent.setup();
    await corrigirNivel(u);
    await u.click(screen.getByRole("button", { name: "Salvar" }));

    expect(await screen.findByText(/anteriores ao congelamento/)).toBeInTheDocument();
    await u.click(screen.getByRole("button", { name: "Recalcular a escola agora" }));
    await waitFor(() => expect(chamadas("POST", "/escolas/1/recalcular")).toHaveLength(1));
    expect(await screen.findByText("Notas recalculadas para 3 alunos.")).toBeInTheDocument();
  });

  it("aplicar ao histórico é opt-in do Admin Global e pede confirmação antes de enviar", async () => {
    responder("GET", URL_LIVROS, paginaFake([livroFake({ editavel: true })]));
    responder("PATCH", `${URL_LIVROS}/7`, livroFake({
      nivel_codigo: "B", editavel: true, vale_para_proximas_leituras: true,
      historico_preservado: false, leituras_atualizadas: 3,
      aviso_correcao: "Correção aplicada também ao HISTÓRICO: 3 leitura(s) passaram a valer o nível B.",
    }));
    renderComApp(<Livros />, { rota: "/livros", usuario: ADMIN_GLOBAL });

    const u = userEvent.setup();
    await corrigirNivel(u);
    await u.click(screen.getByRole("checkbox", { name: /Aplicar também ao histórico/ }));

    // Recusar a confirmação não envia nada — o passado não muda por engano.
    const recusa = vi.spyOn(window, "confirm").mockReturnValue(false);
    await u.click(screen.getByRole("button", { name: "Salvar" }));
    expect(recusa).toHaveBeenCalled();
    expect(chamadas("PATCH", `${URL_LIVROS}/7`)).toHaveLength(0);
    recusa.mockRestore();

    const aceite = vi.spyOn(window, "confirm").mockReturnValue(true);
    await u.click(screen.getByRole("button", { name: "Salvar" }));
    await waitFor(() => expect(chamadas("PATCH", `${URL_LIVROS}/7`)).toHaveLength(1));
    expect(corpoDoPatch()).toMatchObject({ nivel_codigo: "B", aplicar_ao_historico: true });
    expect(await screen.findByText(/aplicada também ao HISTÓRICO/)).toBeInTheDocument();
    // Depois de aplicar ao histórico a escola já foi recalculada pelo servidor.
    expect(screen.queryByRole("button", { name: "Recalcular a escola agora" })).toBeNull();
    aceite.mockRestore();
  });

  it("mostra em texto o erro do servidor ao salvar", async () => {
    responder("GET", URL_LIVROS, paginaFake([livroFake({ editavel: true })]));
    responderErro("PATCH", `${URL_LIVROS}/7`, 409, "Já existe um livro com este título no catálogo.");
    renderComApp(<Livros />, { rota: "/livros", usuario: ADMIN_GLOBAL });

    const u = userEvent.setup();
    await u.click(await screen.findByRole("button", { name: "Editar Laerte, o Gato Inerte" }));
    const titulo = screen.getByDisplayValue("Laerte, o Gato Inerte");
    await u.clear(titulo);
    await u.type(titulo, "O Mapa Perdido");
    await u.click(screen.getByRole("button", { name: "Salvar" }));

    expect(await screen.findByText("Já existe um livro com este título no catálogo.")).toBeInTheDocument();
  });
});
