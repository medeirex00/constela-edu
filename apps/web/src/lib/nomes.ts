/** Normaliza um nome para comparação: sem acentos, sem caixa, espaços simples. */
export function normalizar(nome: string): string {
  return nome
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();
}

// Número da série + ordinal opcional + "ano/série" opcional + a LETRA da sala como
// palavra inteira (nunca o "a" de "ano", "fase" ou "tarde") — o ``_RE_CANON`` de
// ``backend/app/services/matriculas.py``.
const RE_SERIE_LETRA = /(\d+)\s*[ºªo°]?\s*(?:ano|serie)?\s*\b([a-z])\b/i;

/** Chave da SALA de uma turma pelo nome — a regra de ``chave_turma_norm`` do backend
 *  (``services/matriculas.py``): série e letra INTEIRAS ("1 ANO A TARDE ANUAL
 *  (300302821)", "1ºA" e "1A" → "1|A"), sem o turno e sem o código entre parênteses.
 *  Nome sem série+letra (Maternal, Pré, EJA, "1ª Fase A"…) fica com o nome
 *  normalizado: só casa com ele mesmo. */
export function chaveDaSala(nome: string): string {
  const espacado = (nome ?? "").replace(/(\d)([A-Za-z])/g, "$1 $2");
  const limpo = espacado.replace(/\(.*?\)/g, " ").replace(/[ºª°]/g, " ");
  const base = normalizar(limpo);
  const m = RE_SERIE_LETRA.exec(base);
  return m ? `${m[1]}|${m[2].toUpperCase()}` : base;
}

/** A turma cadastrada da SALA do nome lido no relatório, quando ela é ÚNICA: série e
 *  letra inteiras (``chaveDaSala``), como o backend casa a sala. Sem turma da sala, ou
 *  com mais de uma ("5º Ano A Manhã" e "5º Ano A Tarde"), devolve null — quem chama
 *  não adivinha. O destino do aluno novo NÃO sai daqui: é a turma que a prévia do
 *  backend decidiu (``correspondencia.turma_id``/``turma_nova``). */
export function acharTurmaPorNome<T extends { id: number; nome: string }>(
  turmas: T[],
  nomeDetectado: string,
): number | null {
  if (!nomeDetectado || !nomeDetectado.trim()) return null;
  const alvo = chaveDaSala(nomeDetectado);
  const candidatas = turmas.filter((t) => chaveDaSala(t.nome) === alvo);
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
