/**
 * "Quer ver um exemplo?" — abas por módulo, busca no acervo e a conta vinda da
 * API (a tela não calcula nada; só exibe o que o backend devolveu).
 */
import { describe, expect, it } from "vitest";

import ExemploPontuacao from "../components/ExemploPontuacao";
import {
  api,
  renderComApp,
  responder,
  responderErro,
  screen,
  userEvent,
  usuarioFake,
} from "./utils";

const URL_LIVROS = "/escolas/1/livros";
const URL_ELEFANTE = "/escolas/1/configuracoes/pontuacao/exemplo/elefante";
const URL_MATIFIC = "/escolas/1/configuracoes/pontuacao/exemplo/matific";

function livroFake(over: Record<string, unknown> = {}) {
  return {
    id: 42,
    titulo: "Livro de Exemplo",
    autor: null,
    nivel_codigo: "B",
    categoria: null,
    paginas: null,
    pontos: 1.64,
    leituras: 0,
    ...over,
  };
}

/** Resposta no formato real do backend. Os números são os da API — de
 *  propósito, o teste confere que a tela mostra ESTES, sem refazer a conta. */
function exemploElefanteFake(over: Record<string, unknown> = {}) {
  return {
    plataforma: "elefante",
    regra: "elefante_dificuldade_v2",
    regra_da_rede: "elefante_dificuldade_v2",
    catalogo: { versao: "78ca392a0a48", n_livros: 752 },
    entrada: { origem: "acervo", livro_id: 42, elefante_id: 9, titulo: "Livro de Exemplo", nivel: "B", serie: 3 },
    serie: 3,
    valor: 1.9728,
    valor_exibido: 1.97,
    personalizada: false,
    livro: {
      titulo: "Livro de Exemplo",
      nivel: "B",
      palavras: 70,
      palavras_status: "catalogo",
      resolvido_por: "elefante_id",
      encontrado_no_catalogo: true,
      elefante_id: 9,
      titulo_no_catalogo: "Livro de Exemplo",
      nivel_no_catalogo: "B",
    },
    calculo: {
      posicao_nivel: 5,
      posicao_descricao: "6º nível da escada, que começa no AA",
      base_nivel: 1.673639,
      mediana_palavras_nivel: 74,
      fator_tamanho: 0.982296,
      limite_tamanho: null,
      piso_tamanho: 0.8,
      teto_tamanho: 1.35,
      fator_serie: 1.2,
      valor: 1.9728,
    },
    avisos: [],
    ...over,
  };
}

function exemploMatificFake(over: Record<string, unknown> = {}) {
  return {
    plataforma: "matific",
    premiacao: "Melhor Matemática",
    entrada: { atividades: 8, estrelas: 60 },
    estrelas_consideradas: 40,
    teto_estrelas_por_atividade: 5,
    regua: {
      modo: "periodo",
      ano_letivo: 2026,
      inicio_efetivo: "2026-01-01T00:00:00",
      fim_efetivo: "2026-12-31T23:59:59.999999",
      alunos_com_atividade: 6,
      minimo_alunos: 5,
      fracao_zeros_extras: 0.2,
      k_mediana_atividades: 32.5,
      zeros_extras: 6.5,
    },
    referencia_disponivel: true,
    motivo: null,
    mensagem: null,
    calculo: {
      zeros_extras: 6.5,
      denominador: 14.5,
      indice_sem_teto: 2.7586206896551726,
      indice: 2.7586206896551726,
      indice_exibido: 2.76,
      teto_indice: 5,
      teto_aplicado: false,
    },
    avisos: ["Foram informadas 60 estrelas, mas cada atividade dá no máximo 5: contam 40."],
    periodo: { chave: "ano_letivo", rotulo: "Ano letivo 2026", inicio: "2026-01-01T00:00:00", fim: "2026-12-31T23:59:59.999999" },
    ...over,
  };
}

describe("Exemplo de pontuação — abas por módulo", () => {
  it("com os dois módulos, mostra as abas Elefante Letrado e Matific", async () => {
    renderComApp(<ExemploPontuacao escolaId={1} />, {
      usuario: usuarioFake({ modulos: ["leitura", "matematica"] }),
    });
    expect(await screen.findByText("Quer ver um exemplo?")).toBeInTheDocument();
    const lista = screen.getByRole("tablist", { name: "Exemplo por plataforma" });
    expect(lista).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Elefante Letrado" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "Matific" })).toHaveAttribute("aria-selected", "false");
    expect(screen.getByLabelText("Livro do acervo")).toBeInTheDocument();

    const u = userEvent.setup();
    await u.click(screen.getByRole("tab", { name: "Matific" }));
    expect(screen.getByText("Premiação Melhor Matemática")).toBeInTheDocument();
    expect(screen.getByRole("tabpanel")).toHaveAttribute(
      "aria-labelledby", screen.getByRole("tab", { name: "Matific" }).id);
  });

  it("rede sem Leitura: só a aba Matific (a área não some)", async () => {
    renderComApp(<ExemploPontuacao escolaId={1} />, { usuario: usuarioFake({ modulos: ["matematica"] }) });
    expect(await screen.findByRole("tab", { name: "Matific" })).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Elefante Letrado" })).toBeNull();
    expect(screen.getByText("Premiação Melhor Matemática")).toBeInTheDocument();
  });

  it("rede sem Matemática: só a aba Elefante Letrado", async () => {
    renderComApp(<ExemploPontuacao escolaId={1} />, { usuario: usuarioFake({ modulos: ["leitura"] }) });
    expect(await screen.findByRole("tab", { name: "Elefante Letrado" })).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Matific" })).toBeNull();
  });
});

describe("Exemplo de pontuação — Elefante Letrado", () => {
  it("busca no acervo, escolhe o livro e mostra a conta devolvida pela API", async () => {
    responder("GET", URL_LIVROS, { total: 1, pagina: 1, por_pagina: 8, itens: [livroFake()] });
    responder("GET", URL_ELEFANTE, exemploElefanteFake());
    renderComApp(<ExemploPontuacao escolaId={1} />);

    const u = userEvent.setup();
    await u.type(await screen.findByLabelText("Livro do acervo"), "Exem");
    const opcao = await screen.findByRole("button", { name: /Livro de Exemplo/ });
    expect(api).toHaveBeenCalledWith(`${URL_LIVROS}?busca=Exem&por_pagina=8`, expect.anything());
    await u.click(opcao);
    expect(screen.getByText("Livro escolhido")).toBeInTheDocument();
    await u.selectOptions(screen.getByLabelText("Ano escolar do aluno"), "3");
    await u.click(screen.getByRole("button", { name: "Ver exemplo" }));

    expect(await screen.findByText("1,97 pontos")).toBeInTheDocument();
    expect(api).toHaveBeenCalledWith(`${URL_ELEFANTE}?livro_id=42&serie=3`);
    // Do livro × Calculado pelo Constela.
    expect(screen.getByText("Do livro")).toBeInTheDocument();
    expect(screen.getByText("Calculado pelo Constela")).toBeInTheDocument();
    expect(screen.getByText("catálogo oficial do Elefante, pelo código do livro")).toBeInTheDocument();
    expect(screen.getByText("74 palavras")).toBeInTheDocument();
    // A posição vem em palavras (a interna começa em zero: B = 5).
    expect(screen.getByText("(6º nível da escada, que começa no AA)")).toBeInTheDocument();
    expect(screen.queryByText(/degrau/)).toBeNull();
    // A conta fecha com os fatores com todas as casas da API.
    expect(screen.getByTestId("conta-elefante")).toHaveTextContent(
      "1,673639 (nível) × 0,982296 (tamanho) × 1,20 (série) = 1,9728 pontos");
    expect(screen.getByText(/catálogo 78ca392a0a48/)).toBeInTheDocument();
  });

  it("mostra exatamente os números da API, sem refazer a conta", async () => {
    responder("GET", URL_LIVROS, { total: 1, pagina: 1, por_pagina: 8, itens: [livroFake()] });
    // Números que NÃO fecham com a fórmula: se a tela calculasse, mostraria outros.
    responder("GET", URL_ELEFANTE, exemploElefanteFake({
      valor: 9.8765, valor_exibido: 9.88,
      calculo: { ...exemploElefanteFake().calculo, base_nivel: 3.333333, valor: 9.8765 },
    }));
    renderComApp(<ExemploPontuacao escolaId={1} />);
    const u = userEvent.setup();
    await u.type(await screen.findByLabelText("Livro do acervo"), "Exem");
    await u.click(await screen.findByRole("button", { name: /Livro de Exemplo/ }));
    await u.selectOptions(screen.getByLabelText("Ano escolar do aluno"), "3");
    await u.click(screen.getByRole("button", { name: "Ver exemplo" }));

    expect(await screen.findByText("9,88 pontos")).toBeInTheDocument();
    expect(screen.getByTestId("conta-elefante")).toHaveTextContent(
      "3,333333 (nível) × 0,982296 (tamanho) × 1,20 (série) = 9,8765 pontos");
  });

  it("só o nível: chama a API com nivel e serie e mostra o aviso do livro típico", async () => {
    responder("GET", URL_ELEFANTE, exemploElefanteFake({
      entrada: { origem: "nivel", livro_id: null, elefante_id: null, titulo: null, nivel: "D", serie: 2 },
      serie: 2,
      livro: { titulo: null, nivel: "D", palavras: null, palavras_status: "ausente", resolvido_por: null },
      avisos: ["Sem um livro escolhido, o exemplo mostra o livro típico do nível (fator de tamanho 1,00)."],
    }));
    renderComApp(<ExemploPontuacao escolaId={1} />);
    const u = userEvent.setup();
    await u.click(await screen.findByLabelText(/Informar só o nível/));
    await u.selectOptions(screen.getByLabelText("Nível"), "D");
    await u.selectOptions(screen.getByLabelText("Ano escolar do aluno"), "2");
    await u.click(screen.getByRole("button", { name: "Ver exemplo" }));

    expect(await screen.findByText(/livro típico do nível \(fator de tamanho 1,00\)/)).toBeInTheDocument();
    expect(api).toHaveBeenCalledWith(`${URL_ELEFANTE}?nivel=D&serie=2`);
    expect(screen.getByText("nenhum livro escolhido")).toBeInTheDocument();
    expect(screen.getByText("sem contagem")).toBeInTheDocument();
  });

  it("sem livro nem série: avisa antes de chamar a API", async () => {
    renderComApp(<ExemploPontuacao escolaId={1} />);
    const u = userEvent.setup();
    await u.click(await screen.findByRole("button", { name: "Ver exemplo" }));
    expect(
      screen.getByText("Escolha um livro do acervo (ou marque a opção de informar só o nível)."),
    ).toBeInTheDocument();
    await u.click(screen.getByLabelText(/Informar só o nível/));
    await u.selectOptions(screen.getByLabelText("Nível"), "D");
    await u.click(screen.getByRole("button", { name: "Ver exemplo" }));
    expect(screen.getByText("Escolha o ano escolar do aluno.")).toBeInTheDocument();
    expect(api).not.toHaveBeenCalledWith(expect.stringContaining("/pontuacao/exemplo/"));
  });

  it("busca sem resultado mostra a dica, sem inventar livro", async () => {
    responder("GET", URL_LIVROS, { total: 0, pagina: 1, por_pagina: 8, itens: [] });
    renderComApp(<ExemploPontuacao escolaId={1} />);
    const u = userEvent.setup();
    await u.type(await screen.findByLabelText("Livro do acervo"), "Cade");
    expect(
      await screen.findByText(/Nenhum livro do acervo encontrado com esse título/),
    ).toBeInTheDocument();
  });

  it.each([
    [404, "Livro não encontrado no acervo desta escola."],
    [422, "Escolha o ano escolar do aluno: do 1º ao 5º ano (as premiações são do Ensino Fundamental I)."],
  ])("erro %s da API aparece com a mensagem do servidor", async (status, mensagem) => {
    responder("GET", URL_LIVROS, { total: 1, pagina: 1, por_pagina: 8, itens: [livroFake()] });
    responderErro("GET", URL_ELEFANTE, status, mensagem);
    renderComApp(<ExemploPontuacao escolaId={1} />);
    const u = userEvent.setup();
    await u.type(await screen.findByLabelText("Livro do acervo"), "Exem");
    await u.click(await screen.findByRole("button", { name: /Livro de Exemplo/ }));
    await u.selectOptions(screen.getByLabelText("Ano escolar do aluno"), "3");
    await u.click(screen.getByRole("button", { name: "Ver exemplo" }));
    expect(await screen.findByText(mensagem)).toBeInTheDocument();
    expect(screen.queryByText(/pontos$/)).toBeNull();
  });

  it("falha de conexão: mensagem amigável, nenhum número", async () => {
    responder("GET", URL_LIVROS, { total: 1, pagina: 1, por_pagina: 8, itens: [livroFake()] });
    responderErro("GET", URL_ELEFANTE, 0, "Failed to fetch");
    renderComApp(<ExemploPontuacao escolaId={1} />);
    const u = userEvent.setup();
    await u.type(await screen.findByLabelText("Livro do acervo"), "Exem");
    await u.click(await screen.findByRole("button", { name: /Livro de Exemplo/ }));
    await u.selectOptions(screen.getByLabelText("Ano escolar do aluno"), "1");
    await u.click(screen.getByRole("button", { name: "Ver exemplo" }));
    expect(
      await screen.findByText("Não foi possível calcular o exemplo agora. Verifique a conexão e tente de novo."),
    ).toBeInTheDocument();
    expect(screen.queryByTestId("conta-elefante")).toBeNull();
  });

  /** Resposta da régua própria (perfil personalizado), no formato do backend. */
  function reguaPropriaFake(over: Record<string, unknown> = {}) {
    return exemploElefanteFake({
      regra: "escola_legada_v0",
      personalizada: true,
      valor: 9,
      valor_exibido: 9,
      base_do_valor: "serie",
      valor_padrao_escola: 4,
      valor_minimo: 9,
      valor_maximo: 9,
      por_turma: [{ turma_id: 3, turma: "3º Ano A", valor: 9, valor_exibido: 9 }],
      livro: { titulo: null, nivel: "D" },
      entrada: { origem: "nivel", livro_id: null, elefante_id: null, titulo: null, nivel: "D", serie: 3 },
      calculo: null,
      avisos: [
        "Esta escola usa uma régua própria, autorizada pela Constela.",
        "Para o 3º ano, a escola ajustou o valor do nível D: o padrão da escola é 4,00.",
      ],
      ...over,
    });
  }

  async function pedirSoNivelD() {
    renderComApp(<ExemploPontuacao escolaId={1} />);
    const u = userEvent.setup();
    await u.click(await screen.findByLabelText(/Informar só o nível/));
    await u.selectOptions(screen.getByLabelText("Nível"), "D");
    await u.selectOptions(screen.getByLabelText("Ano escolar do aluno"), "3");
    await u.click(screen.getByRole("button", { name: "Ver exemplo" }));
  }

  it("escola com régua própria: o valor do ano (com o ajuste da série) e o padrão, sem fatores", async () => {
    responder("GET", URL_ELEFANTE, reguaPropriaFake());
    await pedirSoNivelD();
    expect(await screen.findByText(/régua própria/)).toBeInTheDocument();
    // O valor que a premiação paga ao 3º ano (9), não o padrão (4).
    expect(screen.getByText(/para um aluno\s+do 3º ano/)).toHaveTextContent(
      "Um livro do nível D vale 9,00 pontos para um aluno do 3º ano.");
    expect(screen.getByText("3º Ano A").parentElement).toHaveTextContent("9,00 pontos");
    expect(screen.getByText(/Valor padrão da escola para o nível/)).toHaveTextContent(
      "Valor padrão da escola para o nível D: 4,00 pontos.");
    expect(screen.getByText("Turmas do 3º ano")).toBeInTheDocument();
    expect(screen.queryByTestId("conta-elefante")).toBeNull();
    expect(screen.queryByText("Calculado pelo Constela")).toBeNull();
  });

  it("régua própria com valor diferente por turma: mostra a faixa e cada turma, sem escolher um valor", async () => {
    responder("GET", URL_ELEFANTE, reguaPropriaFake({
      valor: null,
      valor_exibido: null,
      base_do_valor: "turmas",
      valor_minimo: 4,
      valor_maximo: 6.5,
      por_turma: [
        { turma_id: 3, turma: "3º Ano A", valor: 4, valor_exibido: 4 },
        { turma_id: 4, turma: "3º Ano B", valor: 6.5, valor_exibido: 6.5 },
      ],
      avisos: ["Nesta escola o valor muda conforme a turma do 3º ano: veja o valor de cada turma."],
    }));
    await pedirSoNivelD();
    expect(await screen.findByText(/conforme a turma\.$/)).toHaveTextContent(
      "Um livro do nível D vale de 4,00 a 6,50 pontos para um aluno do 3º ano, conforme a turma.");
    expect(screen.getByText("3º Ano A").parentElement).toHaveTextContent("4,00 pontos");
    expect(screen.getByText("3º Ano B").parentElement).toHaveTextContent("6,50 pontos");
  });

  it("régua própria sem turma do ano: diz que é o valor padrão da escola, não do ano", async () => {
    responder("GET", URL_ELEFANTE, reguaPropriaFake({
      valor: 4,
      valor_exibido: 4,
      base_do_valor: "padrao",
      valor_minimo: null,
      valor_maximo: null,
      por_turma: [],
      avisos: ["Esta escola não tem turma do 3º ano neste ano letivo: aparece o valor padrão da escola para o nível."],
    }));
    await pedirSoNivelD();
    expect(await screen.findByText(/pelo valor\s+padrão da escola/)).toBeInTheDocument();
    expect(screen.queryByText(/para um aluno/)).toBeNull();
    expect(screen.queryByText(/Turmas do/)).toBeNull();
    expect(screen.getByText(/não tem turma do 3º ano/)).toBeInTheDocument();
  });
});

describe("Exemplo de pontuação — Matific (Premiação Melhor Matemática)", () => {
  async function abrirMatific() {
    renderComApp(<ExemploPontuacao escolaId={1} />);
    const u = userEvent.setup();
    await u.click(await screen.findByRole("tab", { name: "Matific" }));
    return u;
  }

  it("chama a API com atividades, estrelas e o período das Premiações e explica o resultado", async () => {
    responder("GET", URL_MATIFIC, exemploMatificFake());
    const u = await abrirMatific();
    await u.type(screen.getByLabelText("Atividades no período"), "8");
    await u.type(screen.getByLabelText("Estrelas no período"), "60");
    await u.click(screen.getByRole("button", { name: "Ver exemplo" }));

    expect(await screen.findByText(/Com estes dados, o Constela chegou a/)).toBeInTheDocument();
    // Período padrão do contexto (o mesmo da tela de Premiações).
    expect(api).toHaveBeenCalledWith(`${URL_MATIFIC}?atividades=8&estrelas=60&periodo=ano_letivo`);
    expect(screen.getByText(/as 40 estrelas que contam foram divididas pelas 8 atividades mais 6,5/))
      .toBeInTheDocument();
    expect(screen.getByText(/20% da mediana de atividades da escola, 32,5/)).toBeInTheDocument();
    expect(screen.getByTestId("conta-matific")).toHaveTextContent("40 ÷ (8 + 6,5) = 40 ÷ 14,5 ≈ 2,76");
    expect(screen.getByText(/no máximo 5: contam 40/)).toBeInTheDocument();
    expect(screen.getByText(/Ano letivo 2026/)).toBeInTheDocument();
    // teto_aplicado = false: a tela não diz que o índice parou no máximo.
    expect(screen.getByText(/O resultado vai de 0 a 5/)).toBeInTheDocument();
    expect(screen.queryByText(/parou no máximo/)).toBeNull();
  });

  it("usa o período global escolhido (mesma query da tela de Premiações)", async () => {
    responder("GET", URL_MATIFIC, exemploMatificFake());
    renderComApp(<ExemploPontuacao escolaId={1} />, {
      periodo: { preset: "personalizado", inicio: "2026-08-01", fim: "2026-08-31" },
    });
    const u = userEvent.setup();
    await u.click(await screen.findByRole("tab", { name: "Matific" }));
    await u.type(screen.getByLabelText("Atividades no período"), "20");
    await u.type(screen.getByLabelText("Estrelas no período"), "70");
    await u.click(screen.getByRole("button", { name: "Ver exemplo" }));
    await screen.findByText(/Com estes dados/);
    expect(api).toHaveBeenCalledWith(
      `${URL_MATIFIC}?atividades=20&estrelas=70&periodo=personalizado&inicio=2026-08-01&fim=2026-08-31`);
  });

  it("poucos alunos no período: mostra o motivo e nenhum k nem índice", async () => {
    responder("GET", URL_MATIFIC, exemploMatificFake({
      referencia_disponivel: false,
      motivo: "poucos_alunos",
      mensagem: "Poucos alunos no período para mostrar a referência: só 3 fizeram atividades.",
      regua: { ...exemploMatificFake().regua, alunos_com_atividade: 3, k_mediana_atividades: null, zeros_extras: null },
      calculo: null,
      avisos: [],
      entrada: { atividades: 20, estrelas: 70 },
      estrelas_consideradas: 70,
    }));
    const u = await abrirMatific();
    await u.type(screen.getByLabelText("Atividades no período"), "20");
    await u.type(screen.getByLabelText("Estrelas no período"), "70");
    await u.click(screen.getByRole("button", { name: "Ver exemplo" }));

    expect(await screen.findByText(/Poucos alunos no período para mostrar a referência/)).toBeInTheDocument();
    expect(screen.queryByTestId("conta-matific")).toBeNull();
    expect(screen.queryByText(/Com estes dados/)).toBeNull();
    expect(screen.queryByText(/Mediana de atividades/)).toBeNull();
  });

  it("sem atividade no período: mostra a mensagem da API", async () => {
    responder("GET", URL_MATIFIC, exemploMatificFake({
      referencia_disponivel: false,
      motivo: "sem_atividade",
      mensagem: "Nenhum aluno do 1º ao 5º ano fez atividade no Matific neste período.",
      regua: { ...exemploMatificFake().regua, alunos_com_atividade: 0, k_mediana_atividades: null, zeros_extras: null },
      calculo: null,
      avisos: [],
    }));
    const u = await abrirMatific();
    await u.type(screen.getByLabelText("Atividades no período"), "5");
    await u.type(screen.getByLabelText("Estrelas no período"), "10");
    await u.click(screen.getByRole("button", { name: "Ver exemplo" }));
    expect(await screen.findByText(/Nenhum aluno do 1º ao 5º ano fez atividade/)).toBeInTheDocument();
    expect(screen.queryByTestId("conta-matific")).toBeNull();
  });

  it("atividades zero: avisa sem chamar a API", async () => {
    const u = await abrirMatific();
    await u.type(screen.getByLabelText("Atividades no período"), "0");
    await u.type(screen.getByLabelText("Estrelas no período"), "3");
    await u.click(screen.getByRole("button", { name: "Ver exemplo" }));
    expect(screen.getByText("Informe pelo menos 1 atividade (número inteiro).")).toBeInTheDocument();
    expect(api).not.toHaveBeenCalledWith(expect.stringContaining("/pontuacao/exemplo/matific"));
  });

  it("422 da API aparece com a mensagem do servidor", async () => {
    responderErro("GET", URL_MATIFIC, 422, "Use números de um aluno: até 100.000 atividades no período.");
    const u = await abrirMatific();
    await u.type(screen.getByLabelText("Atividades no período"), "200000");
    await u.type(screen.getByLabelText("Estrelas no período"), "3");
    await u.click(screen.getByRole("button", { name: "Ver exemplo" }));
    expect(await screen.findByText("Use números de um aluno: até 100.000 atividades no período.")).toBeInTheDocument();
  });
});
