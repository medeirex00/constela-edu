/**
 * Suporte: o guia do perfil, as dúvidas comuns, a regra da nota COMO O SERVIDOR
 * A DEVOLVE (nenhum número da fórmula mora na tela), o exemplo interativo para a
 * gestão e a orientação de sincronização.
 */
import { describe, expect, it } from "vitest";

import { COR_TOM, META_CRITERIOS } from "../components/CriteriosVisuais";
import Suporte, { PASTAS_GUIAS, type RegraPontuacao } from "../pages/Suporte";
import {
  FAQ_COORDENACAO,
  FAQ_PROFESSOR,
  FAQ_SECRETARIA,
  SINCRONIZACAO_GESTAO,
  faqDaGestao,
  faqDaSecretaria,
  sincronizacaoDaGestao,
} from "../pages/suporteConteudo";
import { escolaFake, renderComApp, responder, responderErro, screen, usuarioFake, within } from "./utils";

const URL_REGRA = "/escolas/1/configuracoes/pontuacao/regra";

function regra(over: Partial<RegraPontuacao> = {}): RegraPontuacao {
  return {
    perfil: "institucional",
    versoes: {
      composicao: "por_dimensao_v1",
      dificuldade: "elefante_dificuldade_v2",
      dificuldade_da_rede: "elefante_dificuldade_v2",
    },
    // Números de TESTE, diferentes dos oficiais: a tela tem de mostrar o que a
    // API manda, não o que ela "sabe".
    dimensoes: [
      { dimensao: "leitura", plataforma: "elefante", contratada: true,
        pesos: { livros: 41, dificuldade: 29, questoes: 25, tempo: 5 },
        subpesos_questoes: { tentativas: 33, acertos: 67 } },
      { dimensao: "matematica", plataforma: "matific", contratada: true,
        pesos: { atividades: 44, media: 31, estrelas: 25 } },
    ],
    nota_geral: { pesos: { matific: 57, elefante: 43 } },
    normalizacao: { modo: "auto", percentil_referencia: 87, minimo_alunos_percentil: 11,
                    indicadores_volume: ["atividades", "livros"] },
    ...over,
  };
}

const coordenadora = usuarioFake({ cargo: "coordenador", is_global: false });
const professor = usuarioFake({ cargo: "professor", is_global: false });
const secretaria = usuarioFake({ cargo: "coordenador", rede_id: 7 });

function abrir(usuario = coordenadora, dados: RegraPontuacao | null = regra()) {
  if (dados) responder("GET", URL_REGRA, dados);
  return renderComApp(<Suporte />, {
    usuario, escolas: [escolaFake({ id: 1 })],
    ...(usuario.rede_id != null ? { escolaSelecionada: 1 } : {}),
  });
}

describe("Suporte — conteúdo por perfil", () => {
  it("coordenação: guia da coordenação, dúvidas, regra, exemplo e Integrações", async () => {
    abrir();
    const guia = await screen.findByRole("link", { name: "Abrir o Guia da Coordenação" });
    expect(guia).toHaveAttribute("href", PASTAS_GUIAS.coordenacao);
    expect(guia).toHaveAttribute("target", "_blank");
    expect(screen.getByRole("link", { name: "Ver todos os guias" })).toHaveAttribute("href", PASTAS_GUIAS.todos);
    for (const p of FAQ_COORDENACAO) expect(screen.getByText(p.pergunta)).toBeInTheDocument();
    expect(await screen.findByText("Quer ver um exemplo?")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Abrir Integrações" })).toHaveAttribute("href", "/sincronizacao");
  });

  it("professor: guia do professor e a explicação SEM os parâmetros da fórmula", async () => {
    abrir(professor, null);
    expect(await screen.findByRole("link", { name: "Abrir o Guia do Professor" }))
      .toHaveAttribute("href", PASTAS_GUIAS.professor);
    for (const p of FAQ_PROFESSOR) expect(screen.getByText(p.pergunta)).toBeInTheDocument();
    expect(screen.getByText(/aparece com “—”, não\s+com zero/)).toBeInTheDocument();
    // Os pesos são da gestão (Onda 2): nem pede a regra, nem mostra números.
    expect(screen.queryByText(/%$/)).toBeNull();
    expect(screen.queryByText("Quer ver um exemplo?")).toBeNull();
    expect(screen.queryByRole("link", { name: "Abrir Integrações" })).toBeNull();
  });

  it("admin da escola e Admin Global: o caminho de Configurações Gerais é o do menu deles", () => {
    const pergunta = "Onde mudo a cor da escola, o brasão ou o nome da escola?";
    const resposta = (lista: { pergunta: string; resposta: string }[]) =>
      lista.find((p) => p.pergunta === pergunta)?.resposta ?? "";
    expect(resposta(faqDaGestao({ admin: false, global: false }))).toMatch(/Regras de pontuação › Editar conquistas/);
    // Admin da escola: Configurações Gerais solto na seção Gestão (o acordeão "Configurações" saiu).
    expect(resposta(faqDaGestao({ admin: true, global: false }))).toMatch(/^Em Gestão › Configurações Gerais/);
    // O seletor de escola saiu do topo na v2: é o cartão Escola, no fim do menu lateral.
    expect(resposta(faqDaGestao({ admin: true, global: true })))
      .toMatch(/Configurações › Configurações Gerais, com a escola escolhida no cartão Escola/);
  });

  it("Secretaria: guia da Secretaria", async () => {
    abrir(secretaria);
    expect(await screen.findByRole("link", { name: "Abrir o Guia da Secretaria" }))
      .toHaveAttribute("href", PASTAS_GUIAS.secretaria);
    for (const p of FAQ_SECRETARIA) expect(screen.getByText(p.pergunta)).toBeInTheDocument();
  });

  it("Secretaria de uma rede só com o Matific: as dúvidas citam só o Matific (nada do Elefante)", async () => {
    abrir({ ...secretaria, modulos: ["matematica"] });
    const pergunta = await screen.findByText("Posso comparar as avaliações oficiais com o Matific?");
    // A lista de dúvidas inteira (perguntas e respostas, que ficam no DOM mesmo fechadas).
    const lista = pergunta.closest("details")?.parentElement as HTMLElement;
    expect(lista).toHaveTextContent("Matemática: estrelas por aluno no Matific, no ano letivo.");
    expect(lista).not.toHaveTextContent(/Elefante/);
    expect(screen.queryByText("De quando são os números do Elefante?")).toBeNull();
  });

  // O seletor saiu do topo na v2: é o cartão do fim do menu lateral — "Contexto" para a
  // Secretaria, "Escola" para os demais. "Selecione uma escola no topo" mandava procurar
  // onde só há a trilha, a pesquisa, as notificações e o tema.
  // Nas outras telas, a escola escolhida pela Secretaria no cartão Contexto abre a FICHA dela
  // (DESENHO3 §1); aqui no Suporte o cartão só grava o contexto (Layout: LEEM_O_CONTEXTO_NO_LUGAR),
  // então a regra aparece nesta mesma página — sem "a ficha vai abrir; volte ao Suporte".
  it("Secretaria em 'Toda a Rede Municipal': a regra da nota manda ao cartão Contexto e aparece aqui mesmo", async () => {
    renderComApp(<Suporte />, { usuario: secretaria, escolas: [escolaFake({ id: 1 })] });
    const texto = await screen.findByText(/Escolha uma escola no cartão Contexto, no fim do menu lateral/);
    expect(texto).toHaveTextContent(
      "Escolha uma escola no cartão Contexto, no fim do menu lateral (no tablet e no celular, dentro do menu), "
      + "para ver aqui a regra da nota dela.");
    expect(texto).not.toHaveTextContent(/ficha|volte ao Suporte/);
    expect(screen.queryByText(/escola no topo/)).toBeNull();
    expect(screen.queryByText(/cartão Escola/)).toBeNull();
  });

  it("gestão sem escola selecionada: a regra da nota manda ao cartão Escola, não ao topo", async () => {
    renderComApp(<Suporte />, { usuario: coordenadora, escolas: [] });
    expect(await screen.findByText(/Escolha uma escola no cartão Escola, no fim do menu lateral/)).toBeInTheDocument();
    expect(screen.queryByText(/escola no topo/)).toBeNull();
    expect(screen.queryByText(/cartão Contexto/)).toBeNull();
  });

  it("toda lista de dúvidas tem conteúdo", () => {
    for (const lista of [FAQ_COORDENACAO, FAQ_PROFESSOR, FAQ_SECRETARIA]) {
      expect(lista.length).toBeGreaterThan(0);
      for (const p of lista) expect(p.resposta.length).toBeGreaterThan(20);
    }
  });
});

describe("Suporte — a regra da nota vem do servidor", () => {
  it("mostra os pesos, o percentil e a amostra mínima EXATAMENTE como a API devolve", async () => {
    abrir();
    expect(await screen.findByText("41%")).toBeInTheDocument();
    expect(screen.getByText("44%")).toBeInTheDocument();
    expect(screen.getByText("67%")).toBeInTheDocument();
    expect(screen.getByText(/percentil 87/)).toBeInTheDocument();
    expect(screen.getByText(/pelo menos\s+11 alunos/)).toBeInTheDocument();
    expect(screen.getByText(/régua da rede/)).toBeInTheDocument();
    // A versão aparece em linguagem comum; o identificador técnico fica na dica.
    expect(screen.getByTitle(/elefante_dificuldade_v2/)).toHaveTextContent(
      "régua de dificuldade dos livros da rede, versão 2");
    expect(screen.getByTitle(/por_dimensao_v1/)).toBeInTheDocument();
    expect(screen.queryByText(/\(elefante_dificuldade_v2\)|\(por_dimensao_v1\)/)).toBeNull();
    // Ausência não é zero.
    expect(screen.getByText(/fora do ranking daquela matéria/)).toBeInTheDocument();
    // A Nota Geral (legado) aparece com os pesos da API e o 0,0 de quem não tem dado.
    expect(screen.getByText("57%")).toBeInTheDocument();
    expect(screen.getByText(/0,0 na coluna Geral/)).toBeInTheDocument();
  });

  it("Nota Geral: a cor vem da matéria (Leitura violeta, Matemática teal), não da posição", async () => {
    // A API manda a Matemática PRIMEIRO: antes ela herdava a cor da 1ª posição (violeta).
    abrir();
    const nota = await screen.findByText("E a Nota Geral?");
    const bloco = nota.parentElement as HTMLElement;
    const bolinha = (nome: RegExp) =>
      (within(bloco).getByText(nome).previousElementSibling as HTMLElement).className;
    expect(bolinha(/^Matemática \(Matific\)$/)).toContain("bg-teal-600");
    expect(bolinha(/^Leitura \(Elefante Letrado\)$/)).toContain("bg-indigo-600");
  });

  it("a cor de cada critério é a MESMA da tela Critérios (vem do critério, não da posição)", async () => {
    // Antes era pela posição na lista: Dificuldade saía teal (a cor da Matemática) aqui e
    // rosa em /metricas, Questões laranja aqui e azul lá, Tentativas/Acertos violeta/teal.
    abrir();
    const [leitura, matematica] = (await screen.findAllByText("Quanto cada indicador pesa:"))
      .map((p) => p.parentElement as HTMLElement);
    const bolinha = (bloco: HTMLElement, nome: string) =>
      (within(bloco).getByText(nome).previousElementSibling as HTMLElement).className;
    const corDosCriterios = (chave: string) => COR_TOM[META_CRITERIOS[chave].tom].barra;
    const LEITURA: Array<[string, string]> = [
      ["livros", "livros únicos"], ["dificuldade", "dificuldade dos livros"], ["questoes", "questões"],
      ["tempo", "tempo de leitura"], ["tentativas", "questões respondidas"], ["acertos", "acertos"],
    ];
    for (const [chave, nome] of LEITURA) expect(bolinha(leitura, nome)).toContain(corDosCriterios(chave));
    const MATEMATICA: Array<[string, string]> = [
      ["atividades", "atividades finalizadas"], ["media", "pontuação média"], ["estrelas", "estrelas"],
    ];
    for (const [chave, nome] of MATEMATICA) expect(bolinha(matematica, nome)).toContain(corDosCriterios(chave));
    // Os casos que a revisão apontou, por extenso.
    expect(bolinha(leitura, "dificuldade dos livros")).toContain("bg-rose-500");
    expect(bolinha(leitura, "questões")).toContain("bg-sky-600");
    expect(bolinha(leitura, "questões respondidas")).toContain("bg-sky-600");
    expect(bolinha(leitura, "acertos")).toContain("bg-emerald-600");
    // O teal é da Matemática: nenhum critério da Leitura usa essa cor.
    expect(leitura.innerHTML).not.toContain("bg-teal-");
  });

  it("subtítulo sem jargão e sem prender a uma escola", async () => {
    abrir();
    expect(await screen.findByText("A regra que o Constela aplica na escola selecionada.")).toBeInTheDocument();
    expect(screen.queryByText(/lida do servidor/)).toBeNull();
    expect(screen.getByRole("button", { name: /Como a nota funciona/ })).toHaveTextContent("A régua da escola");
  });

  it("régua própria da escola e referências manuais aparecem como tais", async () => {
    abrir(coordenadora, regra({
      perfil: "personalizado",
      versoes: { composicao: "por_dimensao_v1", dificuldade: "escola_legada_v0",
                 dificuldade_da_rede: "elefante_dificuldade_v2" },
      normalizacao: { modo: "manual", percentil_referencia: 90, minimo_alunos_percentil: 8,
                      indicadores_volume: [] },
    }));
    expect(await screen.findByText(/régua própria, autorizada/)).toBeInTheDocument();
    expect(screen.getByText(/modo manual/)).toBeInTheDocument();
    expect(screen.getByText(/régua própria da escola, por faixa de nível/)).toBeInTheDocument();
  });

  it("matéria fora do plano: diz que não há nota, sem pesos", async () => {
    const r = regra();
    r.dimensoes[1] = { ...r.dimensoes[1], contratada: false };
    abrir(coordenadora, r);
    expect(await screen.findByText(/não faz parte do plano da rede/)).toBeInTheDocument();
    expect(screen.queryByText("44%")).toBeNull();
  });

  it("falha da API: mensagem amigável e nenhum número inventado", async () => {
    responderErro("GET", URL_REGRA, 500, "erro");
    abrir(coordenadora, null);
    expect(await screen.findByText(/Não foi possível carregar a regra da nota/)).toBeInTheDocument();
    expect(screen.queryByText(/%$/)).toBeNull();
  });
});

describe("Suporte — celular", () => {
  // O Layout mantém a pesquisa em todas as larguras; quem some abaixo de 1024 px é a
  // trilha ("Visão geral › … › página") — `NavegacaoPerfis.test.tsx` trava o Layout.
  it("diz que a pesquisa continua e que a linha de onde você está some (não o contrário)", () => {
    const resposta = FAQ_COORDENACAO.find((p) => p.pergunta === "Dá para usar no celular?")?.resposta ?? "";
    expect(resposta).toContain("a pesquisa continua no topo");
    expect(resposta).toContain("a linha do topo que mostra em que página você está e algumas colunas das tabelas só aparecem em telas maiores");
    expect(resposta).not.toMatch(/pesquisa do topo e algumas colunas só aparecem/);
  });
});

describe("Suporte — caminhos do menu de cada perfil (os mesmos da trilha do topo)", () => {
  const juntar = (lista: { resposta: string }[]) => lista.map((p) => p.resposta).join(" ");
  // Nenhum perfil tem mais as seções/grupos antigos — nem o Usuários em Gestão ou em
  // "Configurações" (rodada 2: ele mora em Minha Escola).
  const ANTIGOS = /Projeto ›|Gamificação ›|Estrutura ›|Plataformas ›|Gestão Escolar ›|Relatórios › Painel Público|Gestão › (Integrações|Revisões|Critérios|Usuários)|Configurações › Usuários/;

  it("coordenação: Dados e integrações, Minha Escola (com Usuários), Reconhecimento e Regras de pontuação", () => {
    const textos = juntar([...faqDaGestao({ admin: false, global: false }),
      ...sincronizacaoDaGestao({ admin: false, global: false })]);
    expect(textos).toMatch(/Dados e integrações › Integrações/);
    expect(textos).toMatch(/Dados e integrações › Revisões de identidade/);
    expect(textos).toMatch(/Minha Escola › Alunos/);
    expect(textos).toMatch(/Minha Escola › Turmas/);
    expect(textos).toMatch(/Minha Escola › Professores/);
    expect(textos).toMatch(/Minha Escola › Usuários/);
    expect(textos).toMatch(/Reconhecimento › Premiações/);
    expect(textos).toMatch(/Reconhecimento › Painel Público/);
    expect(textos).toMatch(/Regras de pontuação › Critérios/);
    expect(textos).not.toMatch(ANTIGOS);
    // A coordenação não tem Configurações Gerais.
    expect(textos).not.toMatch(/Configurações Gerais/);
    // SINCRONIZACAO_GESTAO é o texto-base (coordenação).
    expect(sincronizacaoDaGestao({ admin: false, global: false })).toEqual(SINCRONIZACAO_GESTAO);
  });

  it("admin da escola: Usuários também em Minha Escola; Configurações Gerais solto em Gestão", () => {
    const textos = juntar(faqDaGestao({ admin: true, global: false }));
    expect(textos).toMatch(/Minha Escola › Usuários/);
    expect(textos).toMatch(/Gestão › Configurações Gerais/);
    expect(textos).not.toMatch(ANTIGOS);
    // Os dados estão atualizados?: o mesmo texto da coordenação.
    expect(sincronizacaoDaGestao({ admin: true, global: false })).toEqual(SINCRONIZACAO_GESTAO);
  });

  it("Admin Global: troca Minha Escola por Gestão escolar e acha Usuários em Administração", () => {
    const textos = juntar([...faqDaGestao({ admin: true, global: true }),
      ...sincronizacaoDaGestao({ admin: true, global: true })]);
    expect(textos).not.toMatch(/Minha Escola/);
    expect(textos).not.toMatch(/Dados e integrações/);
    expect(textos).toMatch(/Administração › Usuários/);
    expect(textos).not.toMatch(/Gestão escolar › Usuários/);
    expect(textos).toMatch(/Gestão escolar › Alunos/);
    expect(textos).toMatch(/Integrações e dados › Integrações/);
    expect(textos).toMatch(/Integrações e dados › Revisões de identidade/);
    expect(textos).toMatch(/Configurações › Critérios/);
    expect(textos).toMatch(/Configurações › Configurações Gerais/);
    expect(textos).not.toMatch(/Gestão › Configurações Gerais/);
    expect(textos).not.toMatch(ANTIGOS);
  });

  // DESENHO3 §5: o FAQ da Secretaria fala das TRÊS áreas do menu dela (Panorama da Rede,
  // Escolas e Avaliações externas), da diferença entre cadastrada, ativa e com uso, do critério
  // dos destaques (o mesmo da vitrine), do reconhecimento público, da comparação e da ficha
  // da escola, e de avaliações e plataformas como medidas de períodos diferentes.
  it("Secretaria: as três áreas do menu DELA, nenhum nome de menu antigo e nenhuma palavra de causa e efeito", () => {
    const textos = juntar(FAQ_SECRETARIA);
    const tudo = FAQ_SECRETARIA.map((p) => `${p.pergunta} ${p.resposta}`).join(" ");
    for (const area of ["Panorama da Rede", "Em Escolas", "Em Avaliações externas"]) expect(textos, area).toContain(area);
    expect(textos).toMatch(/três áreas, na seção Rede municipal: Panorama da Rede .*, Escolas .* e Avaliações externas/);
    // Nenhuma seção, grupo ou tela que saiu do menu dela.
    expect(tudo).not.toMatch(/Resultados ›|Relatórios e gestão ›|Rede municipal ›|Aprofundar|Análises avançadas/);
    expect(tudo).not.toMatch(/Relatórios e exportações|Escolas em acompanhamento|Painel da Rede|Comparar escolas ›/);
    expect(tudo).not.toMatch(/Inteligência pedagógica|Relatórios e fontes|Análise educacional|Fontes e arquivos oficiais/);
    // Nada de causalidade (o que a tela mostra não explica o porquê) nem termo técnico.
    expect(tudo).not.toMatch(/\bcausa|\bpor causa\b|\befeito\b|\bimpacto|\bgraças\b/i);
    expect(tudo).not.toMatch(/Spearman|correlação|coorte|TPS|IC 95|proveniência/i);
    // Avaliações oficiais × plataformas: sempre ditas como medidas diferentes.
    expect(textos).toMatch(/medidas e períodos diferentes/);
  });

  it("Secretaria: cadastrada × ativa × com uso, critério dos destaques, vitrine, comparação e ficha", () => {
    const resposta = (pergunta: string) => FAQ_SECRETARIA.find((p) => p.pergunta === pergunta)?.resposta ?? "";
    // Não são sinônimos; ausência nunca é zero.
    const situacao = resposta("Qual a diferença entre escola cadastrada, ativa e com uso?");
    expect(situacao).toMatch(/Cadastrada: .*Ativa: .*não diz se a escola usa as plataformas.*Com uso no ano letivo: /);
    for (const estado of ["“Sem uso registrado”", "“Sem dado”", "“Protegida”"]) expect(situacao, estado).toContain(estado);
    expect(situacao).toContain("Sem dado nunca é zero.");
    // O critério dos destaques é o da vitrine, com o período real de cada plataforma.
    const destaques = resposta("Como as escolas em destaque são escolhidas?");
    expect(destaques).toContain("mesmo critério da vitrine pública");
    expect(destaques).toContain("somados desde o início da conta de cada aluno");
    expect(destaques).toContain("estrelas por aluno no Matific, no ano letivo");
    expect(destaques).toMatch(/escolas ativas, com pelo menos 5 alunos do 1º ao 5º ano/);
    expect(destaques).toContain("as 5 maiores de cada plataforma");
    expect(destaques).toContain("calculado pelo Constela");
    // Reconhecimento público: a vitrine fica no Panorama.
    expect(resposta("Onde ligo a vitrine pública da rede?")).toMatch(/^No Panorama da Rede, em “Reconhecimento público”/);
    // Comparar e ficha.
    expect(resposta("Como comparo as escolas?")).toMatch(/^Em Escolas: .*Marque de 2 a 4 escolas em “Comparar”/);
    const ficha = resposta("O que tem na ficha da escola?");
    expect(ficha).toMatch(/cartão Contexto.*avaliações externas da escola/);
    // A ficha mostra CONTAGENS (nunca uma lista de alunos — a Secretaria não vê dados individuais).
    expect(ficha).toContain("o número de alunos, turmas e professores do ano letivo");
    expect(ficha).not.toMatch(/os alunos, as turmas e os professores/);
    // O Panorama não muda com a escola escolhida no cartão Contexto.
    expect(resposta("Escolhi uma escola no cartão Contexto. O Panorama muda?"))
      .toMatch(/^Não: o Panorama da Rede mostra sempre a rede inteira/);
    // No Suporte, o cartão só troca a escola da regra da nota (não abre a ficha).
    expect(resposta("Escolhi uma escola no cartão Contexto. O Panorama muda?"))
      .toContain("aqui no Suporte, só mostra a regra da nota dela, sem sair da página");
    // Avaliações externas: disponibilidade e fonte.
    expect(resposta("Onde vejo o Ideb, o Saeb, o SARESP, o ICA e o IEE?"))
      .toMatch(/^Em Avaliações externas\..*nenhuma edição foi importada/);
  });

  it("Secretaria de rede com uma plataforma só: só o nome dela (rotuloDasPlataformas) e nada da outra", () => {
    const juntarTudo = (lista: { pergunta: string; resposta: string }[]) =>
      lista.map((p) => `${p.pergunta} ${p.resposta}`).join(" ");
    const soMatific = juntarTudo(faqDaSecretaria(["matematica"]));
    expect(soMatific).toContain("Posso comparar as avaliações oficiais com o Matific?");
    expect(soMatific).toContain("a participação dos alunos no Matific no ano letivo");
    expect(soMatific).toContain("com o Matific no período escolhido");
    expect(soMatific).toContain("fez uma atividade no Matific no ano letivo");
    expect(soMatific).toContain("aparecem as 5 maiores.");
    expect(soMatific).not.toMatch(/Elefante|Leitura:|livro/);
    const soElefante = juntarTudo(faqDaSecretaria(["leitura"]));
    expect(soElefante).toContain("Posso comparar as avaliações oficiais com o Elefante Letrado?");
    // O uso do Elefante conta também a releitura: "um livro", nunca "um livro novo".
    expect(soElefante).toContain("leu um livro no Elefante no ano letivo");
    expect(soElefante).not.toContain("leu um livro novo");
    expect(soElefante).toContain("De quando são os números do Elefante?");
    expect(soElefante).not.toMatch(/Matific|Matemática:|estrelas/);
    // As duas (ou a configuração ausente): o texto de sempre.
    expect(faqDaSecretaria(["leitura", "matematica"])).toEqual(FAQ_SECRETARIA);
    expect(faqDaSecretaria([])).toEqual(FAQ_SECRETARIA);
    expect(juntarTudo(FAQ_SECRETARIA)).toContain("com o Elefante e o Matific?");
    expect(juntarTudo(FAQ_SECRETARIA)).toContain("leu um livro no Elefante ou fez uma atividade no Matific");
    expect(juntarTudo(FAQ_SECRETARIA)).not.toMatch(/leu um livro novo|leram ao menos um livro novo/);
  });
});
