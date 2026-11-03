/**
 * Os textos que EXPLICAM as telas principais da Secretaria (DESENHO2 §1): o "O que mede" de
 * cada indicador oficial e de cada métrica das plataformas, a frase das plataformas, a frase
 * que separa avaliações externas de plataformas e a reescrita, em linguagem simples, dos
 * termos técnicos que alguns textos do servidor trazem.
 *
 * Um lugar só para os textos: o Panorama, as Avaliações externas, o Comparar escolas, as
 * Plataformas e o Acompanhamento dizem a MESMA coisa com as mesmas palavras (e os testes
 * conferem estes textos, não cópias deles).
 *
 * Linguagem administrativa: nada de "Spearman", "coorte", "k", "TPS", "IC 95%", "correlação"
 * ou "proveniência" no fluxo principal — termo técnico só nas Análises avançadas. E nada de
 * causalidade: um número "mostra", "indica onde olhar"; nunca "causa", "efeito", "impacto".
 */

/** Um indicador oficial explicado para quem não é especialista. */
export interface ExplicacaoIndicador {
  sigla: string;
  nomeCompleto: string;
  /** Quem publica (o órgão). */
  orgao: string;
  /** Uma frase: o que o número mede. */
  oQueMede: string;
  /** Para quem existe (rede, escola). */
  abrangencia: string;
  /** De quanto em quanto tempo sai. */
  frequencia: string;
  /** Se há meta oficial. */
  meta: string;
}

/** DESENHO2 §1.1 — os textos do dono, só com a forma ajustada. */
export const INDICADORES_EXPLICADOS: Record<string, ExplicacaoIndicador> = {
  ica: {
    sigla: "ICA",
    nomeCompleto: "Indicador Criança Alfabetizada",
    orgao: "INEP",
    oQueMede: "Percentual de crianças do 2º ano da rede consideradas alfabetizadas, pela avaliação de Língua "
      + "Portuguesa.",
    abrangencia: "Existe só para a rede (não por escola).",
    frequencia: "Anual",
    meta: "Com meta",
  },
  saresp: {
    sigla: "SARESP",
    nomeCompleto: "Sistema de Avaliação de Rendimento Escolar do Estado de São Paulo",
    orgao: "SEDUC-SP",
    oQueMede: "Prova do Estado de São Paulo em Língua Portuguesa e Matemática no 2º e no 5º ano. O resultado é "
      + "uma nota (proficiência) numa escala própria.",
    abrangencia: "Para a rede e para cada escola.",
    frequencia: "Anual",
    meta: "Sem meta",
  },
  iee: {
    sigla: "IEE",
    nomeCompleto: "Índice de Excelência Educacional",
    orgao: "SEDUC-SP",
    oQueMede: "Índice de cada escola calculado a partir do SARESP do 2º e do 5º ano.",
    abrangencia: "Só por escola: não existe para a rede.",
    frequencia: "Anual",
    meta: "Cada escola tem a sua meta anual",
  },
  ideb: {
    sigla: "Ideb",
    nomeCompleto: "Índice de Desenvolvimento da Educação Básica",
    orgao: "INEP",
    oQueMede: "Combina o desempenho no Saeb (Português e Matemática) com a aprovação dos alunos, numa escala de "
      + "0 a 10.",
    abrangencia: "Para a rede e para cada escola (anos iniciais = 5º ano).",
    frequencia: "A cada dois anos",
    meta: "Metas oficiais só até 2021",
  },
  saeb: {
    sigla: "Saeb",
    nomeCompleto: "Sistema de Avaliação da Educação Básica",
    orgao: "INEP",
    oQueMede: "Prova nacional de Língua Portuguesa e Matemática do 5º ano; a nota fica numa escala própria.",
    abrangencia: "Para a rede e para cada escola.",
    frequencia: "A cada dois anos",
    meta: "Sem meta",
  },
};

/** A explicação de um indicador do catálogo (um indicador novo, sem texto aqui, fica sem). */
export const explicacaoDe = (chave: string): ExplicacaoIndicador | null => INDICADORES_EXPLICADOS[chave] ?? null;

/** Uma métrica de plataforma: o rótulo (o mesmo dos cartões e da tabela) e o que mede. */
export interface MetricaExplicada {
  chave: string;
  rotulo: string;
  oQueMede: string;
}

export const METRICAS_ELEFANTE: MetricaExplicada[] = [
  { chave: "participacao_pct", rotulo: "Participação",
    oQueMede: "Dos alunos com conta, quantos leram ao menos um livro no período." },
  { chave: "livros_por_aluno", rotulo: "Livros novos por aluno",
    oQueMede: "Média de livros lidos pela primeira vez no período, por aluno com conta." },
  { chave: "minutos_por_aluno", rotulo: "Minutos de leitura por aluno",
    oQueMede: "Tempo médio de leitura registrado no período. É um mínimo: a plataforma nem sempre informa o tempo." },
  { chave: "taxa_acerto_pct", rotulo: "Acerto nas questões",
    oQueMede: "Parte das questões dos livros que os alunos responderam certo no período." },
  { chave: "nivel_medio", rotulo: "Nível médio dos livros",
    oQueMede: "O nível de dificuldade típico dos livros lidos no período, na escala de níveis do Elefante." },
];

export const METRICAS_MATIFIC: MetricaExplicada[] = [
  { chave: "participacao_pct", rotulo: "Participação",
    oQueMede: "Dos alunos com dado no período, quantos fizeram ao menos uma atividade." },
  { chave: "atividades_por_aluno", rotulo: "Atividades por aluno",
    oQueMede: "Média de atividades feitas no período, por aluno com dado." },
  { chave: "estrelas_por_aluno", rotulo: "Estrelas por aluno",
    oQueMede: "Média de estrelas ganhas nas atividades do período, por aluno com dado." },
  { chave: "desempenho_medio", rotulo: "Desempenho",
    oQueMede: "Estrelas por atividade, de 0 a 5: quanto melhor, mais estrelas em cada atividade." },
];

/** As plataformas contratadas pela rede (a forma de `RespostaPlataformas.modulos`). */
export interface ModulosDaRede {
  elefante: boolean;
  matific: boolean;
}

/** "leu um livro no Elefante ou fez uma atividade no Matific" — só o que a rede contratou. O uso
 *  do Elefante conta também a releitura (o mesmo número da participação): "um livro", não "um
 *  livro novo". */
function usoEmTexto(m: ModulosDaRede): string {
  const partes = [
    m.elefante ? "leu um livro no Elefante" : null,
    m.matific ? "fez uma atividade no Matific" : null,
  ].filter(Boolean);
  return partes.length ? partes.join(" ou ") : "usou uma plataforma";
}

/**
 * DESENHO3 §2 — o que mede cada número de "A rede no Constela". Cadastrada, ativa e com uso
 * NÃO são sinônimos: a ativa é só a situação do cadastro; o uso vem das coletas das plataformas.
 */
export const O_QUE_MEDE_REDE = {
  cadastradas: "Escolas vinculadas à rede no Constela, ativas ou não.",
  ativas: "Escolas com a situação “ativa” no cadastro. É situação do cadastro: não indica uso.",
  comUso: (m: ModulosDaRede) =>
    `Escolas em que pelo menos um aluno do 1º ao 5º ano ${usoEmTexto(m)} no ano letivo, pelas coletas.`,
  demais: "As outras escolas: sem uso registrado (nenhum uso nas coletas; com a coleta parcial, a tela diz até que "
    + "data), sem dado (sem coleta, sem conta ou sem alunos do 1º ao 5º ano) ou protegidas (poucos alunos: os "
    + "números não aparecem).",
};

/**
 * DESENHO3 §2.5 — o critério das ESCOLAS EM DESTAQUE, por extenso: o mesmo da vitrine pública.
 * Uma linha por plataforma contratada e a regra de quem entra (com o `k` e o limite da resposta).
 * Quem soma vale POR PLATAFORMA (como no servidor): na leitura, alunos com algum livro lido; na
 * matemática, alunos com alguma estrela — não "um ou outro".
 */
export function criterioDosDestaques(m: ModulosDaRede, kMinimo: number, limite: number): string[] {
  const linhas: string[] = [];
  if (m.elefante) {
    linhas.push("Leitura (Elefante): livros por aluno — os livros lidos desde o início da conta de cada aluno, "
      + "divididos pelos alunos do 1º ao 5º ano matriculados.");
  }
  if (m.matific) {
    linhas.push("Matemática (Matific): estrelas por aluno no ano letivo, divididas pelos alunos do 1º ao 5º ano "
      + "matriculados.");
  }
  const porPlataforma = [
    m.elefante ? `na leitura, pelo menos ${kMinimo} deles com algum livro lido` : null,
    m.matific ? `na matemática, pelo menos ${kMinimo} deles com alguma estrela` : null,
  ].filter(Boolean);
  const regra = porPlataforma.length ? `; ${porPlataforma.join("; ")}` : "";
  linhas.push(`Entram só escolas ativas, com pelo menos ${kMinimo} alunos do 1º ao 5º ano${regra}. Aparecem as `
    + `${limite} maiores ${porPlataforma.length === 1 ? "da plataforma" : "de cada plataforma"}. É o mesmo critério `
    + "da vitrine pública.");
  return linhas;
}

/**
 * O Ranking da Rede NÃO continua a lista de destaques do Panorama: ele ordena pela pontuação do
 * Constela (abre no Índice Geral), não pelos livros ou estrelas por aluno dos destaques. O nome
 * do link é o mesmo da tela Escolas; a frase cita só o que a rede contratou.
 */
export const ROTULO_LINK_RANKING = "Ranking da Rede (pontuação do Constela — outra medida)";

export function fraseRankingOutraMedida(m: ModulosDaRede): string {
  const destaques = [
    m.elefante ? "os livros por aluno" : null,
    m.matific ? "as estrelas por aluno" : null,
  ].filter(Boolean);
  const nao = destaques.length ? `, não ${destaques.join(" ou ")} destes destaques` : "";
  return `A ordem do Ranking da Rede é a da pontuação do Constela${nao}: as posições podem ser diferentes.`;
}

/**
 * Quantas escolas entraram no número da rede de uma plataforma. O servidor soma só as escolas
 * mostradas com a coleta em dia (ou cobrindo ao menos 90% do período); as demais ficam FORA da
 * soma (não valem zero). `null` sem a contagem na resposta.
 */
export function textoEscolasNaSoma(naSoma: number | null | undefined, total: number): string | null {
  if (naSoma == null || total <= 0) return null;
  if (naSoma === 0) {
    return `Nenhuma das ${total} escolas entrou na soma: sem a coleta em dia no período ou com os números `
      + "protegidos (poucos alunos).";
  }
  if (naSoma >= total) {
    // O servidor soma também a escola com coleta parcial que cobre ao menos 90% do período.
    return total === 1
      ? "Número da única escola da rede (com a coleta em dia ou cobrindo ao menos 90% do período)."
      : `Soma das ${total} escolas da rede (todas com a coleta em dia ou cobrindo ao menos 90% do período).`;
  }
  return `Soma de ${naSoma} das ${total} escolas: as com a coleta em dia no período (ou cobrindo ao menos 90% `
    + "dele). As demais ficam fora da soma — sem dado não é zero.";
}

/** As escolas da rede em anos letivos DIFERENTES (a análise mede cada uma no ano letivo dela; o
 *  `janela.ano_letivo` é só o mais comum): a frase por extenso, sem afirmar um ano só. */
export const fraseAnosMistos = (anos: number[]) =>
  `As escolas da rede estão em anos letivos diferentes (${anos.join(", ")}): o uso de cada escola é o do ano `
  + "letivo dela.";

/**
 * A nota de cada métrica de META no Panorama: de quando é o número e o que ele é — as metas não
 * seguem todas o ano letivo, e adoção não é uso. Só o Panorama passa estas notas ao
 * `ProgressoMetas` (o Painel da Rede continua igual).
 */
export const NOTA_DAS_METAS_NO_PANORAMA: Record<string, string> = {
  livros: "soma os livros lidos desde o início da conta de cada aluno (não só no ano letivo)",
  adocao: "parte dos alunos com conta ou dado em alguma plataforma, sem período — não é uso",
  atividades: "atividades do ano letivo no Matific, pela última coleta",
  pontuacao_geral: "a pontuação do Constela (a do Ranking da Rede): outra medida, não a participação no ano letivo",
  media_geral: "a nota de 0 a 100 do Constela: outra medida, não a participação no ano letivo",
  media_elefante: "a nota de 0 a 100 do Constela na leitura: outra medida, não a participação no ano letivo",
  media_matific: "a nota de 0 a 100 do Constela na matemática: outra medida, não a participação no ano letivo",
};

/** DESENHO2 §1.1 — a frase de toda plataforma. */
export const FRASE_PLATAFORMA =
  "Mostra quanto e como as crianças usam a plataforma — não é avaliação oficial de aprendizagem.";

/**
 * DESENHO2 §1.4 — a frase padrão quando avaliações externas e plataformas aparecem perto. Com
 * os anos quando se sabe (o da avaliação é a edição MAIS NOVA: "até"); no MESMO ano (o SARESP de
 * 2026 importado, por exemplo) não diz "outras edições" — ainda assim são medidas diferentes.
 */
export function fraseSeparacao(anoAvaliacao: number | null | undefined, anoPlataforma: number | null | undefined): string {
  if (anoAvaliacao != null && anoPlataforma != null && anoAvaliacao === anoPlataforma) {
    return `As avaliações oficiais (até ${anoAvaliacao}) e as plataformas (ano letivo de ${anoPlataforma}) `
      + "são medidas diferentes — não se comparam diretamente.";
  }
  const aval = anoAvaliacao != null ? ` (até ${anoAvaliacao})` : "";
  const plat = anoPlataforma != null ? `do ano letivo de ${anoPlataforma}` : "do ano letivo corrente";
  return `As avaliações oficiais são de outras edições${aval} e as plataformas, ${plat}: são medidas e `
    + "períodos diferentes — não se comparam diretamente.";
}

/**
 * Reescreve, para o fluxo principal, os termos técnicos que alguns textos do servidor trazem
 * (os mesmos textos servem às Análises avançadas, onde o termo técnico é bem-vindo). Só troca a
 * forma: o motivo continua o mesmo.
 *
 *  - "média instável (TPS = 0: participação abaixo do mínimo do SARESP)" → "média instável
 *    (poucos alunos fizeram a prova)";
 *  - "IEE calculado com médias de TPS = 0 (participação abaixo do mínimo)" → "IEE calculado com
 *    médias instáveis (poucos alunos fizeram a prova)";
 *  - "escola com TPS = 0 (participação abaixo do mínimo…)" → "escola com média instável
 *    (participação abaixo do mínimo…)"; "TPS = 0: a escola não atingiu…" → "Média instável: …";
 *  - "(k = 5)" sai (o texto já diz "para proteger as crianças");
 *  - "edição/coorte" → "edição (outro grupo de alunos)"; "proveniência" → "origem";
 *  - nada de jargão interno: "(o botão de importação em 1 clique…)", "(decisão D2)" e "(CODMUN)"
 *    saem; "pelo ICM oficial da SEDUC" → "segundo a SEDUC"; "não entra no diagnóstico" → "não
 *    gera sinal" (a tela diz que não é diagnóstico);
 *  - a Secretaria não importa arquivo (só o admin global importa): "importe/reimporte o arquivo
 *    oficial desta edição" → "falta importar… / precisa ser importado de novo… — quem importa é
 *    o administrador global";
 *  - a relação com as plataformas e os "destaques" (nome de campo da API) não aparecem no fluxo
 *    principal: "nem na relação…", "e na relação com as plataformas" e "— ele fica fora da
 *    relação…" saem; "nos destaques" → "nos resultados da rede nos cartões".
 */
export function textoSimples(texto: string | null | undefined): string {
  if (!texto) return "";
  return texto
    .replace(/m[ée]dias de TPS\s*=\s*0\s*(\([^)]*\))?/gi, "médias instáveis (poucos alunos fizeram a prova)")
    .replace(/com TPS\s*=\s*0\s*(\([^)]*\))/gi, "com média instável $1")
    .replace(/^TPS\s*=\s*0\s*:\s*/i, "Média instável: ")
    .replace(/\(\s*TPS\s*=\s*0[^)]*\)/gi, "(poucos alunos fizeram a prova)")
    .replace(/TPS\s*=\s*0/gi, "média instável")
    .replace(/\s*\(\s*k\s*=\s*\d+\s*\)/gi, "")
    .replace(/edi[çc][ãa]o\/coorte/gi, "edição (outro grupo de alunos)")
    // "Coorte: alunos ATIVOS…" (início de frase) continua com maiúscula.
    .replace(/\bCoortes?\b/g, "Grupo de alunos")
    .replace(/\bcoortes?\b/gi, "grupo de alunos")
    .replace(/proveni[êe]ncia/gi, "origem")
    // Jargão interno (o nome do botão da importação, a decisão de projeto, o nome do campo).
    .replace(/\s*\(o bot[ãa]o de importa[çc][ãa]o em 1 clique[^)]*\)/gi, "")
    .replace(/,?\s*pelo bot[ãa]o de importa[çc][ãa]o em 1 clique,?\s*sem pr[ée]via nem registro do arquivo/gi,
             ", sem o registro do arquivo oficial")
    .replace(/\s*\(decis[ãa]o D2\)/gi, "")
    .replace(/\s*\(CODMUN\):([^.]*)\./g, ":$1. Quem cadastra é o administrador global.")
    .replace(/\(\s*pelo ICM oficial da SEDUC\s*\)/gi, "(segundo a SEDUC)")
    .replace(/n[ãa]o entra no diagn[óo]stico/gi, "não gera sinal")
    // Quem importa é o admin global: a Secretaria lê o que falta, não uma ordem que ela não pode cumprir.
    .replace(/\breimporte o arquivo oficial desta edi[çc][ãa]o/gi,
             "o arquivo oficial desta edição precisa ser importado de novo — quem importa é o administrador global")
    .replace(/\bimporte o arquivo oficial desta edi[çc][ãa]o/gi,
             "falta importar o arquivo oficial desta edição — quem importa é o administrador global")
    // A relação com as plataformas mora nas Análises avançadas; "destaques" é nome de campo.
    .replace(/\s*—\s*ele fica fora da rela[çc][ãa]o com as plataformas/gi, "")
    .replace(/\s+e na rela[çc][ãa]o com as plataformas/gi, "")
    .replace(/\s*nem na rela[çc][ãa]o( com as plataformas)?/gi, "")
    .replace(/\bnos destaques\b/gi, "nos resultados da rede nos cartões");
}

/**
 * As frases que falam da RELAÇÃO ESTATÍSTICA entre avaliações e plataformas (o método, o
 * intervalo, o aviso de que não é causa e efeito) — assunto das Análises avançadas, que têm a
 * metodologia completa na aba Relação. No fluxo principal elas saem: a tela não mostra relação
 * nenhuma, e o termo técnico ("Spearman", "correlação", "intervalo de 95%") não entra.
 */
const FRASE_DA_RELACAO = /Spearman|correla[çc][ãa]o|intervalo de 95|IC 95|rela[çc][ãa]o estat[íi]stica|causa e efeito/i;

/**
 * Os textos do servidor (metodologia, limitações) para o FLUXO PRINCIPAL: a língua simples de
 * `textoSimples` e sem as frases da relação estatística. O resto de cada texto fica (ex.: "As
 * plataformas só têm dados do ano letivo em curso; as avaliações oficiais por escola são de anos
 * anteriores."); o texto que era só sobre a relação some da lista.
 */
export function textosDoFluxoPrincipal(textos: readonly string[] | null | undefined): string[] {
  return (textos ?? [])
    .map((t) => {
      const simples = textoSimples(t);
      if (!FRASE_DA_RELACAO.test(simples)) return simples;
      return simples.split(/(?<=[.!?])\s+/).filter((frase) => !FRASE_DA_RELACAO.test(frase)).join(" ").trim();
    })
    .filter((t) => t.length > 0);
}
