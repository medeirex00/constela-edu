/** Normaliza um nome para comparação: sem acentos, sem caixa, espaços simples. */
export function normalizar(nome: string): string {
  return nome
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();
}

// Palavras genéricas que NÃO distinguem uma turma de outra da mesma série.
const GENERICOS = new Set([
  "ano", "serie", "anual", "manha", "tarde", "noite", "integral", "turma",
  "de", "do", "da", "pre", "i", "ii",
]);

/** Turma cujo nome bate com o lido do PDF. Exige que os tokens distintivos
 *  (letra da turma, número da série) coincidam e que a correspondência seja
 *  ÚNICA — senão "5 Ano B" casaria por engano com "5 Ano A". */
export function acharTurmaPorNome<T extends { id: number; nome: string }>(
  turmas: T[],
  nomeDetectado: string,
): number | null {
  if (!nomeDetectado) return null;
  const limpar = (s: string) => normalizar(s).replace(/[ºª°]/g, "");
  const alvo = limpar(nomeDetectado);
  const exata = turmas.find((t) => limpar(t.nome) === alvo);
  if (exata) return exata.id;

  const distintivos = alvo.split(" ").filter((t) => t.length > 0 && !GENERICOS.has(t));
  if (distintivos.length === 0) return null;
  const candidatas = turmas.filter((t) => {
    const nome = ` ${limpar(t.nome)} `;
    return distintivos.every((tk) => nome.includes(` ${tk} `) || nome.includes(tk));
  });
  return candidatas.length === 1 ? candidatas[0].id : null;
}

// ETAPA da sala — espelho de ``matriculas.etapa_da_sala`` e
// ``elegibilidade.e_etapa_fora_da_premiacao`` (backend): palavra de etapa fora do
// Fundamental, como palavra inteira, sobre o rótulo sem acento e em maiúsculas; um
// "ANO" explícito ("1º Ano", "Ano 1", "primeiro") afirma o Fundamental e vence.
const RE_ETAPA_FORA =
  /\b(?:FASE|ETAPA|EMEI|INFANTIL|MATERNAL|BERCARIO|BERCARISTA|CRECHE|JARDIM|PRE|PREI|PREII|EJA|MINIGRUPO)\b/;
// O "O" na classe: o NFKD decompõe "º" em "o", e o rótulo vai para maiúsculas.
const RE_ANO_EXPLICITO =
  /\b(?:\d\s*[º°O]?\s*ANO|ANO\s*\d|PRIMEIRO|SEGUNDO|TERCEIRO|QUARTO|QUINTO)\b/;

function foraDoFundamental(rotulo: string): boolean {
  const plano = rotulo.normalize("NFKD").replace(/\p{M}/gu, "").replace(/\s+/g, " ")
    .trim().toUpperCase();
  return !RE_ANO_EXPLICITO.test(plano) && RE_ETAPA_FORA.test(plano);
}

/** "fora_do_fundamental" (Fase, EMEI, Pré, Maternal, EJA…) ou "fundamental", lendo o
 *  ``ano_escolar`` e o nome da turma: se qualquer um nomeia etapa fora do Fundamental,
 *  a sala é tratada como tal (``matriculas.etapa_da_sala``). */
export function etapaDaSala(nome: string, anoEscolar = ""): "fundamental" | "fora_do_fundamental" {
  return [anoEscolar, nome].some((rotulo) => rotulo && foraDoFundamental(rotulo))
    ? "fora_do_fundamental"
    : "fundamental";
}
