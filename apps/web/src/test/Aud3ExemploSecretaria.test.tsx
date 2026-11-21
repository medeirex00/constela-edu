/**
 * REV3-PLAT-2 — "Quer ver um exemplo?" para a Secretaria: só por nível.
 *
 * O acervo da escola ficou com quem é da escola (S_G_GRUPO-2: GET /livros é 403 para
 * a Secretaria; REV3-PLAT-1: o exemplo com `livro_id` também). O componente aparece
 * para ela no Suporte e em Critérios (/metricas), e a busca no acervo chamava
 * `/escolas/{id}/livros` sem olhar o perfil: a tela mostrava "Não foi possível buscar
 * livros: A Secretaria ... não opera as escolas (importação, sincronização e
 * diagnóstico ...)" — um erro que não tem a ver com o que ela fez.
 *
 * Agora, para a Secretaria, o exemplo do Elefante começa e fica no modo "só o nível":
 * sem a busca no acervo e sem a opção de voltar a ela. A coordenação segue com a busca.
 */
import { describe, expect, it } from "vitest";

import ExemploPontuacao from "../components/ExemploPontuacao";
import { api, renderComApp, responder, screen, userEvent, usuarioFake } from "./utils";

const URL_ELEFANTE = "/escolas/1/configuracoes/pontuacao/exemplo/elefante";

function exemploPorNivel() {
  return {
    plataforma: "elefante",
    regra: "elefante_dificuldade_v2",
    regra_da_rede: "elefante_dificuldade_v2",
    catalogo: { versao: "78ca392a0a48", n_livros: 752 },
    entrada: { origem: "nivel", livro_id: null, elefante_id: null, titulo: null, nivel: "D", serie: 2 },
    serie: 2,
    valor: 1.5,
    valor_exibido: 1.5,
    personalizada: false,
    livro: { titulo: null, nivel: "D", palavras: null, palavras_status: "ausente", resolvido_por: null },
    calculo: {
      posicao_nivel: 7,
      posicao_descricao: "8º nível da escada, que começa no AA",
      base_nivel: 1.5,
      mediana_palavras_nivel: 120,
      fator_tamanho: 1,
      limite_tamanho: null,
      piso_tamanho: 0.8,
      teto_tamanho: 1.35,
      fator_serie: 1,
      valor: 1.5,
    },
    avisos: [],
  };
}

function chamouOAcervo(): boolean {
  return api.mock.calls.some(([url]) => String(url).includes("/livros"));
}

describe.each(["coordenador", "admin"])("Secretaria (cargo %s): exemplo só por nível", (cargo) => {
  it("não busca no acervo, pede só o nível e calcula pelo nível", async () => {
    responder("GET", URL_ELEFANTE, exemploPorNivel());
    renderComApp(<ExemploPontuacao escolaId={1} />, {
      usuario: usuarioFake({ cargo, rede_id: 7, escola_id: null }),
    });

    const nivel = await screen.findByLabelText("Nível");
    expect(screen.queryByLabelText("Livro do acervo")).toBeNull();
    expect(screen.queryByLabelText(/Informar só o nível/)).toBeNull();
    expect(screen.queryByText(/Escolha um livro do acervo/)).toBeNull();
    expect(screen.getByText(/Escolha o nível do livro e o ano escolar do aluno/)).toBeInTheDocument();

    const u = userEvent.setup();
    await u.selectOptions(nivel, "D");
    await u.selectOptions(screen.getByLabelText("Ano escolar do aluno"), "2");
    await u.click(screen.getByRole("button", { name: "Ver exemplo" }));

    expect(await screen.findByText("1,50 pontos")).toBeInTheDocument();
    expect(api).toHaveBeenCalledWith(`${URL_ELEFANTE}?nivel=D&serie=2`);
    expect(chamouOAcervo()).toBe(false);
    expect(screen.queryByText(/Não foi possível buscar livros/)).toBeNull();
  });
});

describe("Coordenação da escola: a busca no acervo continua", () => {
  it("digitar no campo busca os livros da escola", async () => {
    responder("GET", "/escolas/1/livros", { total: 0, pagina: 1, por_pagina: 8, itens: [] });
    renderComApp(<ExemploPontuacao escolaId={1} />);
    const u = userEvent.setup();
    await u.type(await screen.findByLabelText("Livro do acervo"), "Exem");
    expect(await screen.findByText(/Nenhum livro do acervo encontrado/)).toBeInTheDocument();
    expect(api).toHaveBeenCalledWith("/escolas/1/livros?busca=Exem&por_pagina=8", expect.anything());
    expect(screen.getByLabelText(/Informar só o nível/)).toBeInTheDocument();
  });
});
