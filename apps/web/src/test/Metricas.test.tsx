/**
 * /metricas por perfil — "Critérios de pontuação" (identidade visual v2).
 *
 * Escola (coordenador/admin de escola) e Secretaria: a régua EFETIVA em cartões
 * (pesos lidos de GET /pontuacao/regra), as regras fixas da premiação e a
 * explicação de como a nota é calculada, SEM nenhum editor (o motor ignora a
 * configuração local no perfil institucional e as rotas de escrita são só do
 * Admin Global). Admin Global: os mesmos cartões com os editores, o aviso de que
 * no perfil Padrão Constela nada disso afeta as notas e a explicação.
 */
import { describe, expect, it } from "vitest";

import Metricas from "../pages/configuracoes/Metricas";
import {
  api,
  rankingItemFake,
  renderComApp,
  responder,
  responderErro,
  screen,
  userEvent,
  usuarioFake,
  within,
} from "./utils";

const URL_PERFIL = "/escolas/1/configuracoes/perfil-scoring";
const URL_DIFICULDADE_LIVRO = "/escolas/1/configuracoes/dificuldade-livro";
const URL_PESOS_MATIFIC = "/escolas/1/configuracoes/pesos/matific";
const URL_PESOS_ELEFANTE = "/escolas/1/configuracoes/pesos/elefante";
const URL_PESOS_QUESTOES = "/escolas/1/configuracoes/pesos/questoes";
const URL_REGRA = "/escolas/1/configuracoes/pontuacao/regra";
const URL_RANKING_LEITURA = /^\/escolas\/1\/ranking\?dimensao=leitura$/;
const URL_RANKING_MATEMATICA = /^\/escolas\/1\/ranking\?dimensao=matematica$/;
const URL_REFERENCIAS = "/escolas/1/configuracoes/referencias";
const URL_EXTRA = "/escolas/1/configuracoes/elefante-extra";
const URL_DIFICULDADE = "/escolas/1/configuracoes/dificuldade";
const URL_LIVROS = "/escolas/1/livros";
const URL_EXEMPLO_ELEFANTE = "/escolas/1/configuracoes/pontuacao/exemplo/elefante";

const TEXTO_DO_DONO =
  "Os pontos dos livros são calculados automaticamente pelo Constela considerando o nível de leitura, as características do livro e o ano escolar.";
const RODAPE = "Esta regra vale para toda a rede e só a Constela pode alterá-la.";
const AVISO_GLOBAL =
  "No perfil Padrão Constela estas configurações não afetam as notas; valem só na régua personalizada.";
const MENSAGEM_FALHA =
  "Não foi possível carregar os detalhes da regra agora. A pontuação continua sendo calculada normalmente pelo Constela; tente de novo mais tarde.";
const TEXTO_REGUA_PERSONALIZADA_RE =
  /A Constela configurou uma régua própria para esta escola; os pesos podem diferir do padrão da rede\./;

const adminGlobal = usuarioFake({ id: 99, nome: "Admin Constela", is_global: true, cargo: "admin" });
const secretaria = usuarioFake({ id: 50, nome: "Secretaria", rede_id: 7 });

/** Resposta de GET /dificuldade-livro (formato real do backend, sem exemplo). */
function dificuldadeLivroFake() {
  return {
    versao_vigente: "elefante_dificuldade_v1",
    regra_da_escola: "elefante_dificuldade_v1",
    parametros: {
      posicoes_extra: { "Z+": 30, "A+": 4.5 },
      posicoes_faixa: { pre_leitor: 1.5, nivel_1: 5 },
      medianas_wordcount: { AA: 12, D: 139 },
      alpha: 0.35,
      razao_log: 3,
      piso: 0.8,
      teto: 1.35,
      fator_serie: { "1": 1.4, "2": 1.3, "3": 1.2, "4": 1.1, "5": 1.0 },
      fator_serie_padrao: 1.0,
      calibracao: { n_livros: 752, catalogo_de: "2026-09-14", fonte: "catálogo" },
    },
    catalogo: { n: 752, gerado_em: "2026-09-14" },
  };
}

/** Resposta de GET /pontuacao/regra (formato real do backend): os pesos
 *  EFETIVOS de cada matéria. Padrão = os institucionais (PESOS_PADRAO). */
function regraFake(
  perfil: "institucional" | "personalizado",
  over: {
    leitura?: Record<string, number>;
    matematica?: Record<string, number>;
    questoes?: Record<string, number>;
    semLeitura?: boolean;
  } = {},
) {
  return {
    perfil,
    versoes: {
      composicao: "por_dimensao_v1",
      dificuldade: "elefante_dificuldade_v1",
      dificuldade_da_rede: "elefante_dificuldade_v1",
    },
    dimensoes: [
      {
        dimensao: "leitura", plataforma: "elefante", contratada: !over.semLeitura,
        pesos: over.leitura ?? { livros: 35, dificuldade: 30, questoes: 30, tempo: 5 },
        subpesos_questoes: over.questoes ?? { tentativas: 30, acertos: 70 },
      },
      {
        dimensao: "matematica", plataforma: "matific", contratada: true,
        pesos: over.matematica ?? { atividades: 40, media: 35, estrelas: 25 },
      },
    ],
    nota_geral: { pesos: { matific: 50, elefante: 50 } },
    normalizacao: {
      modo: "auto", percentil_referencia: 90, minimo_alunos_percentil: 8,
      indicadores_volume: ["livros", "tempo", "atividades"],
    },
  };
}

/** Ranking oficial por matéria (GET /ranking?dimensao=...): nomes diferentes
 *  em cada matéria, para os testes não confundirem as duas listas. */
function semearRanking() {
  responder("GET", URL_RANKING_LEITURA, [
    rankingItemFake({ posicao: 1, aluno_id: 10, nome: "Ana Beatriz Souza", dimensao: "leitura", nota: 92.5, n_aferidos: 2 }),
    rankingItemFake({ posicao: 2, aluno_id: 11, nome: "João Pedro Barbosa", dimensao: "leitura", nota: 81, n_aferidos: 2 }),
  ]);
  responder("GET", URL_RANKING_MATEMATICA, [
    rankingItemFake({ posicao: 1, aluno_id: 20, nome: "Maria Clara Lima", dimensao: "matematica", nota: 88.25, n_aferidos: 1 }),
  ]);
}

function semearEditoresGlobal() {
  responder("GET", URL_PERFIL, { modo: "institucional" });
  responder("GET", URL_REGRA, regraFake("institucional"));
  semearRanking();
  responder("GET", URL_PESOS_QUESTOES, {
    namespace: "questoes",
    valores: { tentativas: 30, acertos: 70 },
    soma: 100,
  });
  responder("GET", URL_PESOS_MATIFIC, {
    namespace: "matific",
    valores: { atividades: 40, media: 35, estrelas: 25 },
    soma: 100,
  });
  responder("GET", URL_PESOS_ELEFANTE, {
    namespace: "elefante",
    valores: { livros: 35, dificuldade: 30, questoes: 30, tempo: 5 },
    soma: 100,
  });
  responder("GET", URL_REFERENCIAS, {
    modo: "auto",
    valores_manuais: {},
    valores_em_uso: { max_atividades: 120, max_livros: 40 },
  });
  responder("GET", URL_EXTRA, { ativo: false, pontos_por_livro: 1 });
  responder("GET", URL_DIFICULDADE, { niveis: [] });
  responder("GET", URL_DIFICULDADE_LIVRO, dificuldadeLivroFake());
}

describe("Métricas — visão da escola (Critérios de pontuação)", () => {
  it("coordenadora vê a explicação, sem nenhum editor", async () => {
    responder("GET", URL_PERFIL, { modo: "institucional" });
    responder("GET", URL_REGRA, regraFake("institucional"));
    semearRanking();
    responder("GET", URL_DIFICULDADE_LIVRO, dificuldadeLivroFake());
    renderComApp(<Metricas />, { rota: "/metricas" });

    expect(await screen.findByText("Como a pontuação é calculada")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Critérios de pontuação", level: 1 })).toBeInTheDocument();
    expect(screen.getByText(TEXTO_DO_DONO)).toBeInTheDocument();
    expect(
      await screen.findByText("Régua Padrão Constela — a mesma para toda a rede"),
    ).toBeInTheDocument();
    // Rodapé e descrição dependem da régua vigente (só afirmam "toda a rede"
    // depois de saber que é a institucional).
    expect(screen.getByText(RODAPE)).toBeInTheDocument();
    expect(screen.getByText(/com a mesma regra para toda a rede/)).toBeInTheDocument();

    // Cartões da régua EFETIVA (GET /pontuacao/regra): cada critério com o seu
    // percentual, só leitura.
    const leitura = await screen.findByRole("region", { name: "Leitura" });
    expect(within(leitura).getByText("Livros únicos concluídos").closest("li")).toHaveTextContent("35%");
    expect(within(leitura).getByText("Tempo de leitura").closest("li")).toHaveTextContent("5%");
    const matematica = screen.getByRole("region", { name: "Matemática" });
    expect(within(matematica).getByText("Atividades finalizadas").closest("li")).toHaveTextContent("40%");
    expect(within(matematica).getByText("Estrelas").closest("li")).toHaveTextContent("25%");
    const questoes = screen.getByRole("region", { name: "Questões" });
    expect(within(questoes).getByText("Acertos").closest("li")).toHaveTextContent("70%");

    // Regras da premiação: só leitura, as 4 categorias fixas e o certificado.
    const regras = screen.getByRole("region", { name: "Regras da premiação" });
    for (const categoria of ["Melhor Leitor", "Melhor Matemática", "Mais Livros Lidos", "Mais Tempo de Leitura"]) {
      expect(within(regras).getByText(categoria)).toBeInTheDocument();
    }
    expect(within(regras).getByText("Certificado")).toBeInTheDocument();
    // No celular "Ver premiações" desce para baixo do subtítulo (linha inteira): ao lado
    // do título ele espremia título e texto numa coluna de ~105 px.
    const verPremiacoes = within(regras).getByRole("link", { name: "Ver premiações" });
    expect(verPremiacoes.parentElement).toHaveClass("max-sm:w-full");
    expect(verPremiacoes).toHaveClass("max-sm:min-h-10");
    expect(screen.queryByRole("switch")).toBeNull();
    expect(screen.queryByRole("checkbox")).toBeNull();

    // Ranking atual: os primeiros de cada matéria, como o servidor ordenou.
    const ranking = screen.getByRole("region", { name: "Ranking atual com esta régua" });
    expect(await within(ranking).findByText("Ana Beatriz Souza")).toBeInTheDocument();
    // Nome que não cabe quebra em até 2 linhas; o nome completo fica na dica.
    expect(within(ranking).getByText("Ana Beatriz Souza")).toHaveAttribute("title", "Ana Beatriz Souza");
    expect(await within(ranking).findByText("Maria Clara Lima")).toBeInTheDocument();
    // Notas sempre com duas casas (a coluna fica alinhada): 92,5 → "92,50"; 81 → "81,00".
    expect(within(ranking).getByText("92,50")).toBeInTheDocument();
    expect(within(ranking).getByText("81,00")).toBeInTheDocument();
    expect(within(ranking).getByText("88,25")).toBeInTheDocument();

    // "Como funciona?" começa fechado e abre com os fatores vindos da API.
    const u = userEvent.setup();
    const botao = screen.getByRole("button", { name: "Como funciona?" });
    expect(botao).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText(/Nível do livro\./)).toBeNull();
    await u.click(botao);
    expect(botao).toHaveAttribute("aria-expanded", "true");

    expect(await screen.findByText("1º ano: ×1,40")).toBeInTheDocument();
    expect(screen.getByText("3º ano: ×1,20")).toBeInTheDocument();
    expect(screen.getByText("5º ano: ×1,00")).toBeInTheDocument();
    expect(screen.getByText("Outras séries: ×1,00")).toBeInTheDocument();
    expect(screen.getByText(/até \+35%/)).toBeInTheDocument();
    expect(screen.getByText(/no mínimo −20%/)).toBeInTheDocument();
    expect(screen.getByText(/Cada livro conta uma vez\./)).toBeInTheDocument();
    // Pesos das notas, lidos da régua efetiva (GET /pontuacao/regra).
    expect(
      screen.getByText(/livros únicos 35%, dificuldade dos livros 30%, questões 30%, tempo de leitura 5%/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/atividades finalizadas 40%, pontuação média 35%, estrelas 25%/),
    ).toBeInTheDocument();
    expect(screen.getByText(/Catálogo de referência: 752 livros/)).toBeInTheDocument();

    // Nenhum editor: nem abas de editor, nem pesos, nem referências, nem a
    // escolha de régua. A ÚNICA lista de abas é a do exemplo por plataforma.
    expect(screen.queryByText("Referências de Normalização")).toBeNull();
    expect(screen.queryByText("Pesos da Nota")).toBeNull();
    expect(screen.queryByRole("radio")).toBeNull();
    expect(screen.queryByRole("radiogroup")).toBeNull();
    expect(screen.getAllByRole("tablist")).toHaveLength(1);
    expect(screen.getByRole("tablist", { name: "Exemplo por plataforma" })).toBeInTheDocument();
    expect(screen.getAllByRole("tab").map((t) => t.textContent)).toEqual(["Elefante Letrado", "Matific"]);
    expect(screen.queryByRole("slider")).toBeNull();
    expect(screen.queryByRole("button", { name: /Salvar/ })).toBeNull();
    expect(screen.queryByText(/modo leitura/)).toBeNull();
    expect(screen.queryByText(/coordenador da escola/)).toBeNull();
    expect(screen.queryByText(AVISO_GLOBAL)).toBeNull();
    // A explicação não bate na API de pesos/referências (não há editor).
    expect(api).not.toHaveBeenCalledWith(URL_PESOS_MATIFIC, expect.anything());
    expect(api).not.toHaveBeenCalledWith(URL_REFERENCIAS, expect.anything());
  });

  it("Secretaria (rede vinculada) vê a mesma visão somente leitura", async () => {
    responder("GET", URL_PERFIL, { modo: "personalizado" });
    responder("GET", URL_REGRA, regraFake("personalizado"));
    semearRanking();
    responder("GET", URL_DIFICULDADE_LIVRO, dificuldadeLivroFake());
    renderComApp(<Metricas />, { rota: "/metricas", usuario: secretaria, escolaSelecionada: 1 });

    expect(await screen.findByText("Como a pontuação é calculada")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Critérios de pontuação", level: 1 })).toBeInTheDocument();
    expect(screen.getByText(TEXTO_DO_DONO)).toBeInTheDocument();
    expect(
      await screen.findByText("Régua personalizada, autorizada pela Constela"),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Como funciona?" })).toBeInTheDocument();

    expect(screen.queryByText("Referências de Normalização")).toBeNull();
    expect(screen.queryByText("Pesos da Nota")).toBeNull();
    expect(screen.queryByRole("radio")).toBeNull();
    expect(screen.queryByRole("tab")).toBeNull();
    expect(screen.queryByRole("button", { name: /Salvar/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Somente leitura" })).toBeNull();
    expect(screen.queryByRole("slider")).toBeNull();

    // Os cartões da régua aparecem (só leitura) ...
    expect(await screen.findByRole("region", { name: "Leitura" })).toBeInTheDocument();
    // ... mas nome de criança, não: sem o ranking atual e sem buscá-lo.
    expect(screen.queryByRole("region", { name: "Ranking atual com esta régua" })).toBeNull();
    const urls = api.mock.calls.map(([url]) => String(url));
    expect(urls.filter((url) => url.includes("/ranking"))).toEqual([]);
    // A Secretaria não abre /premiacoes: sem o atalho para lá.
    expect(screen.queryByRole("link", { name: "Ver premiações" })).toBeNull();
  });

  it("régua personalizada: sem a lista fixa de pesos e sem 'mesma regra para toda a rede'", async () => {
    responder("GET", URL_PERFIL, { modo: "personalizado" });
    responder("GET", URL_REGRA, regraFake("personalizado", {
      leitura: { livros: 50, dificuldade: 20, questoes: 20, tempo: 10 },
      matematica: { atividades: 30, media: 30, estrelas: 40 },
    }));
    semearRanking();
    responder("GET", URL_DIFICULDADE_LIVRO, dificuldadeLivroFake());
    renderComApp(<Metricas />, { rota: "/metricas" });

    expect(
      await screen.findByText("Régua personalizada, autorizada pela Constela"),
    ).toBeInTheDocument();
    expect(screen.getByText(TEXTO_DO_DONO)).toBeInTheDocument();
    // Descrição e rodapé não afirmam regra única da rede.
    expect(screen.queryByText(/mesma regra para toda a rede/)).toBeNull();
    expect(screen.queryByText(RODAPE)).toBeNull();
    expect(screen.queryByText(/vale para toda a rede/)).toBeNull();
    expect(
      screen.getByText("Esta régua vale só para esta escola e só a Constela pode alterá-la."),
    ).toBeInTheDocument();
    // Os cartões mostram os pesos EFETIVOS da régua própria, vindos da API.
    const leitura = await screen.findByRole("region", { name: "Leitura" });
    expect(within(leitura).getByText("Livros únicos concluídos").closest("li")).toHaveTextContent("50%");
    const matematica = screen.getByRole("region", { name: "Matemática" });
    expect(within(matematica).getByText("Estrelas").closest("li")).toHaveTextContent("40%");

    const u = userEvent.setup();
    await u.click(screen.getByRole("button", { name: "Como funciona?" }));
    expect(await screen.findByText("1º ano: ×1,40")).toBeInTheDocument();
    expect(screen.getByText(TEXTO_REGUA_PERSONALIZADA_RE)).toBeInTheDocument();
    // Nenhum dos pesos institucionais fixos aparece.
    expect(screen.queryByText(/livros únicos 35%/)).toBeNull();
    expect(screen.queryByText(/dificuldade dos livros 30%/)).toBeNull();
    expect(screen.queryByText(/tempo de leitura 5%/)).toBeNull();
    expect(screen.queryByText(/atividades finalizadas 40%/)).toBeNull();
    expect(screen.queryByText(/pontuação média 35%/)).toBeNull();
    expect(screen.queryByText(/estrelas 25%/)).toBeNull();
  });

  it("sem conseguir ler a régua, não afirma nem os pesos institucionais nem 'toda a rede'", async () => {
    responderErro("GET", URL_PERFIL, 403, "Sem acesso");
    responderErro("GET", URL_REGRA, 403, "Sem acesso");
    semearRanking();
    responder("GET", URL_DIFICULDADE_LIVRO, dificuldadeLivroFake());
    renderComApp(<Metricas />, { rota: "/metricas" });

    expect(
      await screen.findByText("Não foi possível verificar a régua em uso agora."),
    ).toBeInTheDocument();
    expect(screen.queryByText(/mesma regra para toda a rede/)).toBeNull();
    expect(screen.queryByText(RODAPE)).toBeNull();
    expect(screen.getByText("Só a Constela pode alterar a regra de pontuação.")).toBeInTheDocument();
    // Sem a régua, os cartões dizem que não carregaram — nenhum percentual.
    expect(await screen.findByText("Não foi possível carregar os pesos em uso")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Leitura" })).toBeNull();

    const u = userEvent.setup();
    await u.click(screen.getByRole("button", { name: "Como funciona?" }));
    expect(await screen.findByText("1º ano: ×1,40")).toBeInTheDocument();
    expect(screen.queryByText(/livros únicos 35%/)).toBeNull();
    expect(screen.queryByText(/atividades finalizadas 40%/)).toBeNull();
    expect(screen.queryByText(TEXTO_REGUA_PERSONALIZADA_RE)).toBeNull();
  });

  it("quando /dificuldade-livro falha, mostra mensagem amigável sem inventar números", async () => {
    responder("GET", URL_PERFIL, { modo: "institucional" });
    responder("GET", URL_REGRA, regraFake("institucional"));
    semearRanking();
    responderErro("GET", URL_DIFICULDADE_LIVRO, 503, "Serviço indisponível");
    renderComApp(<Metricas />, { rota: "/metricas" });

    const u = userEvent.setup();
    await u.click(await screen.findByRole("button", { name: "Como funciona?" }));

    expect(await screen.findByText(MENSAGEM_FALHA, {}, { timeout: 4000 })).toBeInTheDocument();
    expect(screen.queryByText(/×1,40/)).toBeNull();
    expect(screen.queryByText(/\+35%/)).toBeNull();
    expect(screen.queryByText(/−20%/)).toBeNull();
    expect(screen.queryByText(/Nível do livro\./)).toBeNull();
    expect(screen.queryByText(/752/)).toBeNull();
    // O texto do dono e o rodapé continuam — não dependem da API.
    expect(screen.getByText(TEXTO_DO_DONO)).toBeInTheDocument();
    expect(screen.getByText(RODAPE)).toBeInTheDocument();
    // O exemplo tem rotas próprias: a área continua, sem nenhum número.
    expect(screen.getByText("Quer ver um exemplo?")).toBeInTheDocument();
    expect(screen.queryByText(/pontos$/)).toBeNull();
  });

  it("o exemplo do Elefante usa o livro do acervo e a rota nova, com os números da API", async () => {
    responder("GET", URL_PERFIL, { modo: "institucional" });
    responder("GET", URL_REGRA, regraFake("institucional"));
    semearRanking();
    responder("GET", URL_DIFICULDADE_LIVRO, dificuldadeLivroFake());
    responder("GET", URL_LIVROS, {
      total: 1, pagina: 1, por_pagina: 8,
      itens: [{ id: 7, titulo: "Livro Teste", autor: null, nivel_codigo: "D", categoria: null,
                paginas: null, pontos: 2.06, leituras: 0 }],
    });
    responder("GET", URL_EXEMPLO_ELEFANTE, {
      plataforma: "elefante", regra: "elefante_dificuldade_v2", regra_da_rede: "elefante_dificuldade_v2",
      catalogo: { versao: "78ca392a0a48", n_livros: 752 },
      entrada: { origem: "acervo", livro_id: 7, elefante_id: null, titulo: "Livro Teste", nivel: "D", serie: 3 },
      serie: 3, valor: 2.4676, valor_exibido: 2.47, personalizada: false,
      livro: { titulo: "Livro Teste", nivel: "D", palavras: null, palavras_status: "ausente",
               resolvido_por: null, encontrado_no_catalogo: false },
      calculo: { posicao_nivel: 7, base_nivel: 2.056345, mediana_palavras_nivel: 139, fator_tamanho: 1,
                 limite_tamanho: null, piso_tamanho: 0.8, teto_tamanho: 1.35, fator_serie: 1.2, valor: 2.4676 },
      avisos: ["Não há contagem de palavras deste livro no catálogo oficial, então ele vale o livro típico do nível (fator de tamanho 1,00)."],
    });
    renderComApp(<Metricas />, { rota: "/metricas" });

    const u = userEvent.setup();
    await u.click(await screen.findByRole("button", { name: "Como funciona?" }));
    expect(await screen.findByText("Quer ver um exemplo?")).toBeInTheDocument();
    await u.type(screen.getByLabelText("Livro do acervo"), "Livro");
    await u.click(await screen.findByRole("button", { name: /Livro Teste/ }));
    await u.selectOptions(screen.getByLabelText("Ano escolar do aluno"), "3");
    await u.click(screen.getByRole("button", { name: "Ver exemplo" }));

    expect(await screen.findByText("2,47 pontos")).toBeInTheDocument();
    expect(api).toHaveBeenCalledWith(`${URL_EXEMPLO_ELEFANTE}?livro_id=7&serie=3`);
    expect(api).toHaveBeenCalledWith(`${URL_LIVROS}?busca=Livro&por_pagina=8`, expect.anything());
    expect(screen.getByTestId("conta-elefante")).toHaveTextContent(
      "2,056345 (nível) × 1,00 (tamanho) × 1,20 (série) = 2,4676 pontos");
    expect(screen.getByText(/vale o livro típico do nível/)).toBeInTheDocument();
    // A rota antiga (?nivel= em /dificuldade-livro) não é mais usada pelo exemplo.
    // Varre TODAS as chamadas (com 1 ou 2 argumentos): /dificuldade-livro é
    // carregada sem query pela explicação, nunca com ?nivel=.
    const urls = api.mock.calls.map(([url]) => String(url));
    expect(urls).toContain(URL_DIFICULDADE_LIVRO);
    expect(urls.filter((url) => /dificuldade-livro\?/.test(url))).toEqual([]);
  });

  it("rede sem Leitura: a explicação diz que está fora do plano, e o exemplo segue com o Matific", async () => {
    responder("GET", URL_PERFIL, { modo: "institucional" });
    responder("GET", URL_REGRA, regraFake("institucional", { semLeitura: true }));
    semearRanking();
    responderErro("GET", URL_DIFICULDADE_LIVRO, 403, "O módulo Leitura não faz parte do plano desta rede.");
    renderComApp(<Metricas />, { rota: "/metricas", usuario: usuarioFake({ modulos: ["matematica"] }) });

    // Só o cartão da Matemática; nada de Leitura nem das premiações de leitura.
    expect(await screen.findByRole("region", { name: "Matemática" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Leitura" })).toBeNull();
    expect(screen.queryByRole("region", { name: "Questões" })).toBeNull();
    const regras = screen.getByRole("region", { name: "Regras da premiação" });
    expect(within(regras).getByText("Melhor Matemática")).toBeInTheDocument();
    expect(within(regras).queryByText("Melhor Leitor")).toBeNull();
    expect(within(regras).queryByText("Mais Livros Lidos")).toBeNull();

    const u = userEvent.setup();
    await u.click(await screen.findByRole("button", { name: "Como funciona?" }));
    expect(await screen.findByText("O módulo Leitura não faz parte do plano desta rede.")).toBeInTheDocument();
    expect(screen.getByText("Quer ver um exemplo?")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Matific" })).toHaveAttribute("aria-selected", "true");
    expect(screen.queryByRole("tab", { name: "Elefante Letrado" })).toBeNull();
    expect(screen.getByText("Premiação Melhor Matemática")).toBeInTheDocument();
  });
});

describe("Métricas — Admin Global", () => {
  it("mantém os editores, com a explicação no topo e o aviso do perfil Padrão", async () => {
    semearEditoresGlobal();
    renderComApp(<Metricas />, { rota: "/metricas", usuario: adminGlobal });

    expect(
      await screen.findByRole("heading", { name: "Critérios de pontuação", level: 1 }),
    ).toBeInTheDocument();
    expect(screen.getByText(AVISO_GLOBAL)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Como funciona?" })).toBeInTheDocument();

    // Escolha da régua (radios) + editor de pesos da aba Matific.
    expect(
      await screen.findByRole("radiogroup", { name: "Régua de pontuação da escola" }),
    ).toBeInTheDocument();
    expect(screen.getAllByRole("radio")).toHaveLength(2);
    // Um cartão por grupo de pesos, cada um com o PRÓPRIO "Salvar pesos".
    const matematica = await screen.findByRole("region", { name: "Matemática" });
    expect(await within(matematica).findByRole("button", { name: "Salvar pesos" })).toBeEnabled();
    // No perfil Padrão o selo continua em cada cartão (agora numa linha própria, sob o título).
    expect(await within(matematica).findByText("Vale só na régua personalizada")).toBeInTheDocument();
    expect(within(matematica).getByRole("slider", { name: "Atividades finalizadas" })).toBeEnabled();
    expect(
      within(matematica).getByRole("spinbutton", { name: "Atividades finalizadas (valor exato)" }),
    ).toHaveValue(40);
    expect(await screen.findAllByRole("button", { name: "Salvar pesos" })).toHaveLength(3);
    expect(screen.getByText("Pesos da Nota")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Referências de Normalização" })).toBeInTheDocument();

    // O banner falso ("o coordenador da escola ... podem alterar") não existe mais.
    expect(screen.queryByText(/modo leitura/)).toBeNull();
    expect(screen.queryByText(/coordenador da escola/)).toBeNull();

    const u = userEvent.setup();
    // Sub-abas do Elefante (níveis e dificuldade por turma) seguem disponíveis.
    await u.click(screen.getByRole("tab", { name: "Elefante Letrado" }));
    expect(await screen.findByRole("tab", { name: "Níveis de dificuldade" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Dificuldade por turma" })).toBeInTheDocument();
    await u.click(screen.getByRole("tab", { name: "Pontos Extras" }));
    expect(
      await screen.findByLabelText("Ativar pontos extras por livros lidos na escola"),
    ).toBeEnabled();

    await u.click(screen.getByRole("tab", { name: "Referências de Normalização" }));
    expect(await screen.findByRole("button", { name: "Salvar referências" })).toBeEnabled();
  });

  it("abre 'Como funciona?' com os mesmos fatores da régua", async () => {
    semearEditoresGlobal();
    renderComApp(<Metricas />, { rota: "/metricas", usuario: adminGlobal });

    const u = userEvent.setup();
    await u.click(await screen.findByRole("button", { name: "Como funciona?" }));
    expect(await screen.findByText("1º ano: ×1,40")).toBeInTheDocument();
    // Escola na régua institucional → os pesos padrão aparecem.
    expect(await screen.findByText(/livros únicos 35%, dificuldade dos livros 30%/)).toBeInTheDocument();
  });

  it("escola com régua personalizada: 'Como funciona?' do Admin Global também não lista os pesos fixos", async () => {
    semearEditoresGlobal();
    responder("GET", URL_PERFIL, { modo: "personalizado" });
    responder("GET", URL_REGRA, regraFake("personalizado"));
    renderComApp(<Metricas />, { rota: "/metricas", usuario: adminGlobal });

    const u = userEvent.setup();
    await u.click(await screen.findByRole("button", { name: "Como funciona?" }));
    expect(await screen.findByText("1º ano: ×1,40")).toBeInTheDocument();
    expect(await screen.findByText(TEXTO_REGUA_PERSONALIZADA_RE)).toBeInTheDocument();
    expect(screen.queryByText(/livros únicos 35%/)).toBeNull();
    expect(screen.queryByText(/atividades finalizadas 40%/)).toBeNull();
  });
});
