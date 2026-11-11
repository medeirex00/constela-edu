/**
 * A regra de pontuação em linguagem de gente — fonte única para as telas que a
 * citam (Suporte › "Como a nota é calculada", Critérios de pontuação › "Como
 * funciona?" e o "Quer ver um exemplo?" das duas). O identificador técnico da versão (o que o backend devolve, ex.:
 * `elefante_dificuldade_v2`) não aparece no texto: fica só na dica (title), para
 * quem precisa conferir com a equipe.
 */

/** Versões conhecidas (backend: `services/dificuldade_livro.VERSAO_*` e
 *  `services/scoring.COMPOSICAO_ATUAL`). */
const NOME_DA_VERSAO: Record<string, string> = {
  por_dimensao_v1: "a ordem oficial é por matéria (Leitura e Matemática)",
  elefante_dificuldade_v2: "régua de dificuldade dos livros da rede, versão 2",
  elefante_dificuldade_v1: "régua de dificuldade dos livros da rede, versão 1",
  escola_legada_v0: "régua própria da escola, por faixa de nível",
};

/** Nome comum de uma versão da regra; versão desconhecida volta como veio (melhor
 *  o identificador do que esconder qual regra está em uso). */
export function nomeDaVersaoDaRegra(versao: string): string {
  return NOME_DA_VERSAO[versao] ?? versao;
}

/** "AAAA-MM-DD…" → "DD/MM/AAAA", cortando o texto: a data do catálogo é um DIA, não
 *  um instante — passar por `Date` a leria como meia-noite UTC e, em Brasília,
 *  mostraria o dia anterior. Vazio ou ilegível → `null` (a tela não mostra). */
export function diaDoCatalogo(texto: string | null | undefined): string | null {
  const partes = /^(\d{4})-(\d{2})-(\d{2})/.exec(texto ?? "");
  return partes ? `${partes[3]}/${partes[2]}/${partes[1]}` : null;
}
