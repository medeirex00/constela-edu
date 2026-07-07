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
