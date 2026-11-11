/**
 * "Como funciona?" dos Critérios de pontuação (/metricas, gestão): a linha de rodapé
 * mostrava o código interno da régua e a data do catálogo em ISO —
 * "Regra em uso nesta escola: elefante_dificuldade_v2. Catálogo de referência: 752
 * livros (2026-09-14)." O Suporte já traduzia o mesmo código; agora as duas telas usam
 * o mesmo mapa (lib/regraPontuacao) e a data sai como dd/mm/aaaa, cortada do texto
 * (é um dia, não um instante: passar por Date a mostraria um dia antes em Brasília).
 * O identificador técnico fica na dica (title), como no Suporte. Dados fictícios, no
 * formato real de GET /configuracoes/dificuldade-livro.
 *
 * O "Quer ver um exemplo?" (ExemploPontuacao) fica DENTRO do mesmo painel (e no
 * Suporte): a linha final do exemplo também dizia "Regra: elefante_dificuldade_v2 ·
 * catálogo 78ca392a0a48 (752 livros)", logo abaixo do rodapé já traduzido
 * (REV-MISC-1). Agora usa o mesmo mapa; o hash do catálogo fica na dica.
 */
import { describe, expect, it } from "vitest";

import ComoFuncionaPontuacao from "../components/ComoFuncionaPontuacao";
import { diaDoCatalogo, nomeDaVersaoDaRegra } from "../lib/regraPontuacao";
import { renderComApp, responder, screen, userEvent, usuarioFake, within } from "./utils";

function dificuldadeLivro(over: Record<string, unknown> = {}) {
  return {
    versao_vigente: "elefante_dificuldade_v2",
    regra_da_escola: "elefante_dificuldade_v2",
    parametros: {
      versao: "elefante_dificuldade_v2",
      calibracao: { n_livros: 752, catalogo_de: "2026-09-14", fonte: "catálogo" },
      posicoes_extra: { "Z+": 30, "A+": 4.5 },
      posicoes_faixa: { pre_leitor: 1.5, nivel_1: 5 },
      medianas_wordcount: { AA: 12, D: 139 },
      alpha: 0.35, razao_log: 3, piso: 0.8, teto: 1.35,
      fator_serie: { "1": 1.4, "2": 1.3, "3": 1.2, "4": 1.1, "5": 1.0 },
      fator_serie_padrao: 1.0,
    },
    catalogo: { n: 752 },
    ...over,
  };
}

async function abrirRodape(resposta: unknown) {
  responder("GET", "/escolas/1/configuracoes/dificuldade-livro", resposta);
  responder("GET", /^\/escolas\/1\/configuracoes\/pontuacao\/exemplo\//, {});
  responder("GET", /^\/escolas\/1\/livros/, { itens: [], total: 0 });
  responder("GET", /^\/escolas\/1\/turmas/, []);
  const u = userEvent.setup();
  renderComApp(<ComoFuncionaPontuacao modo="institucional" />, { rota: "/metricas" });
  await u.click(await screen.findByRole("button", { name: /Como funciona\?/ }));
  return screen.findByText(/Regra em uso nesta escola/);
}

describe("Como funciona a pontuação: o rodapé em linguagem da escola", () => {
  it("diz a régua pelo nome e a data do catálogo em dd/mm/aaaa", async () => {
    const rodape = await abrirRodape(dificuldadeLivro());
    const texto = rodape.textContent?.replace(/\s+/g, " ") ?? "";

    expect(texto).not.toMatch(/elefante_dificuldade_v\d|\d{4}-\d{2}-\d{2}/);
    expect(texto).toContain(
      "Regra em uso nesta escola: régua de dificuldade dos livros da rede, versão 2.");
    expect(texto).toContain("Catálogo de referência: 752 livros (14/09/2026).");
    // O identificador técnico continua à mão, na dica.
    expect(screen.getByTitle("Identificador da versão: elefante_dificuldade_v2")).toBeInTheDocument();
  });

  it("escola com régua própria: as duas regras pelo nome", async () => {
    const rodape = await abrirRodape(dificuldadeLivro({ regra_da_escola: "escola_legada_v0" }));
    const texto = rodape.textContent?.replace(/\s+/g, " ") ?? "";

    expect(texto).not.toMatch(/escola_legada_v0|elefante_dificuldade_v\d/);
    expect(texto).toContain("régua própria da escola, por faixa de nível");
    expect(texto).toContain("(regra da rede: régua de dificuldade dos livros da rede, versão 2)");
  });
});

/** Resposta de GET /configuracoes/pontuacao/exemplo/elefante, no formato real. */
function exemploLivro(over: Record<string, unknown> = {}) {
  return {
    plataforma: "elefante",
    regra: "elefante_dificuldade_v2",
    regra_da_rede: "elefante_dificuldade_v2",
    catalogo: { versao: "78ca392a0a48", n_livros: 752 },
    entrada: { origem: "acervo", livro_id: 42, elefante_id: 9, titulo: "Livro de Exemplo", nivel: "B", serie: 3 },
    serie: 3, valor: 1.9728, valor_exibido: 1.97, personalizada: false,
    livro: {
      titulo: "Livro de Exemplo", nivel: "B", palavras: 70, palavras_status: "catalogo",
      resolvido_por: "elefante_id", encontrado_no_catalogo: true, elefante_id: 9,
      titulo_no_catalogo: "Livro de Exemplo", nivel_no_catalogo: "B",
    },
    calculo: {
      posicao_nivel: 5, posicao_descricao: "6º nível da escada, que começa no AA",
      base_nivel: 1.673639, mediana_palavras_nivel: 74, fator_tamanho: 0.982296,
      limite_tamanho: null, piso_tamanho: 0.8, teto_tamanho: 1.35, fator_serie: 1.2, valor: 1.9728,
    },
    avisos: [],
    ...over,
  };
}

async function pedirExemploNoPainel(exemplo: unknown) {
  responder("GET", "/escolas/1/configuracoes/dificuldade-livro", dificuldadeLivro());
  responder("GET", /^\/escolas\/1\/livros/, {
    total: 1, pagina: 1, por_pagina: 8,
    itens: [{ id: 42, titulo: "Livro de Exemplo", autor: null, nivel_codigo: "B", categoria: null,
      paginas: null, pontos: 1.64, leituras: 0 }],
  });
  responder("GET", /^\/escolas\/1\/configuracoes\/pontuacao\/exemplo\/elefante/, exemplo);
  responder("GET", /^\/escolas\/1\/turmas/, []);
  const u = userEvent.setup();
  renderComApp(<ComoFuncionaPontuacao modo="institucional" />, {
    rota: "/metricas", usuario: usuarioFake({ modulos: ["leitura"] }),
  });
  await u.click(await screen.findByRole("button", { name: /Como funciona\?/ }));
  await screen.findByText(/Regra em uso nesta escola/);
  await u.type(await screen.findByLabelText("Livro do acervo"), "Exem");
  await u.click(await screen.findByRole("button", { name: /Livro de Exemplo/ }));
  await u.selectOptions(screen.getByLabelText("Ano escolar do aluno"), "3");
  await u.click(screen.getByRole("button", { name: "Ver exemplo" }));
  await screen.findByText("1,97 pontos");
  return screen.getByText(/^Regra:/);
}

describe("Como funciona a pontuação: o exemplo do mesmo painel também fala a língua da escola", () => {
  it("a linha da regra do exemplo diz a régua pelo nome; código e hash do catálogo só na dica", async () => {
    const linha = await pedirExemploNoPainel(exemploLivro());
    const texto = linha.textContent?.replace(/\s+/g, " ") ?? "";

    expect(texto).not.toMatch(/elefante_dificuldade_v\d|78ca392a0a48/);
    expect(texto).toBe("Regra: régua de dificuldade dos livros da rede, versão 2 · catálogo de 752 livros");
    expect(within(linha).getByTitle("Identificador da versão: elefante_dificuldade_v2")).toBeInTheDocument();
    expect(within(linha).getByTitle("Versão do catálogo: 78ca392a0a48")).toBeInTheDocument();
  });

  it("régua própria da escola pelo nome; sem catálogo, a linha não fala de catálogo", async () => {
    const linha = await pedirExemploNoPainel(exemploLivro({
      regra: "escola_legada_v0", catalogo: { versao: null, n_livros: 0 },
    }));
    const texto = linha.textContent?.replace(/\s+/g, " ") ?? "";

    expect(texto).toBe("Regra: régua própria da escola, por faixa de nível");
    expect(within(linha).getByTitle("Identificador da versão: escola_legada_v0")).toBeInTheDocument();
  });
});

describe("lib/regraPontuacao", () => {
  it("nome da versão: conhecido em linguagem comum; desconhecido, o próprio identificador", () => {
    expect(nomeDaVersaoDaRegra("por_dimensao_v1")).toBe(
      "a ordem oficial é por matéria (Leitura e Matemática)");
    expect(nomeDaVersaoDaRegra("elefante_dificuldade_v1")).toBe(
      "régua de dificuldade dos livros da rede, versão 1");
    expect(nomeDaVersaoDaRegra("regra_nova_v9")).toBe("regra_nova_v9");
  });

  it("dia do catálogo: corta o texto, sem fuso; ilegível ou vazio não aparece", () => {
    expect(diaDoCatalogo("2026-09-14")).toBe("14/09/2026");
    // Com horário (UTC), o dia é o do texto: nada de virar 13/09 em Brasília.
    expect(diaDoCatalogo("2026-09-14T01:30:00Z")).toBe("14/09/2026");
    expect(diaDoCatalogo("setembro")).toBeNull();
    expect(diaDoCatalogo(undefined)).toBeNull();
    expect(diaDoCatalogo("")).toBeNull();
  });
});
