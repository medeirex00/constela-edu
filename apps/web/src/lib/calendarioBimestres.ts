/**
 * Calendário oficial dos bimestres e elegibilidade às premiações (espelhos do backend).
 *
 * Saiu de pages/Relatorios.tsx (que continua re-exportando `bimestreDeHoje` e
 * `participaDePremiacao`) para que o menu, o Ranking, as Premiações e a Visão Geral usem
 * a MESMA cópia sem carregar a página de Relatórios.
 */

/** Calendário oficial dos bimestres (Rede Estadual de SP, 2026) — as MESMAS
 *  datas de `backend/app/services/bimestres.py`, que é quem manda. Aqui elas só
 *  decidem qual opção o seletor abre marcada e quantos dias faltam para o fim do
 *  bimestre; o número impresso é sempre o que o backend recebe. Início e fim de
 *  cada bimestre, inclusivos: 02/02–22/04, 23/04–23/07, 24/07–04/10, 05/10–31/12.
 *
 *  Não é o mês do relógio: em 01/10 o 3º bimestre ainda não acabou, e era
 *  exatamente aí que o mapa por mês fazia o seletor abrir em "4º". */
const BIMESTRES: Array<{ numero: number; ano: number; inicio: number; fim: number }> = [
  { numero: 1, ano: 2026, inicio: Date.UTC(2026, 1, 2), fim: Date.UTC(2026, 3, 22) },
  { numero: 2, ano: 2026, inicio: Date.UTC(2026, 3, 23), fim: Date.UTC(2026, 6, 23) },
  { numero: 3, ano: 2026, inicio: Date.UTC(2026, 6, 24), fim: Date.UTC(2026, 9, 4) },
  { numero: 4, ano: 2026, inicio: Date.UTC(2026, 9, 5), fim: Date.UTC(2026, 11, 31) },
];

const DIA_MS = 24 * 60 * 60 * 1000;

function diaUTC(d: Date): number {
  return Date.UTC(d.getFullYear(), d.getMonth(), d.getDate());
}

export function bimestreDeHoje(d: Date): number {
  const dia = diaUTC(d);
  const doAno = BIMESTRES.filter((b) => b.ano === d.getFullYear());
  if (!doAno.length) return 1; // ano sem calendário: o backend decide o padrão
  const achado = doAno.find((b) => dia <= b.fim);
  return achado ? achado.numero : 4;
}

/**
 * Bimestre em curso na data, com quantos dias faltam para o fim (contando o dia de
 * hoje como dia em curso: no último dia, faltam 0). `null` fora do calendário
 * (férias entre bimestres ou ano sem calendário) — nunca um número inventado.
 */
export function bimestreEmCurso(d: Date): { numero: number; ano: number; inicio: Date; fim: Date; diasParaOFim: number } | null {
  const dia = diaUTC(d);
  const b = BIMESTRES.find((x) => dia >= x.inicio && dia <= x.fim);
  if (!b) return null;
  return {
    numero: b.numero,
    ano: b.ano,
    inicio: new Date(b.inicio),
    fim: new Date(b.fim),
    diasParaOFim: Math.round((b.fim - dia) / DIA_MS),
  };
}

/** Turmas que NÃO concorrem às premiações — espelho de
 *  `backend/app/services/elegibilidade.py`. O backend barra de verdade (409);
 *  isto aqui só evita oferecer na tela um nome que não pode ser emitido. */
const RE_ETAPA_FORA =
  /\b(FASE|ETAPA|EMEI|INFANTIL|MATERNAL|BERCARIO|CRECHE|JARDIM|PRE|EJA|MINIGRUPO)\b/;
// O `O` maiúsculo na classe não é descuido: NFKD decompõe "º" em "o", e o rótulo
// é passado para MAIÚSCULAS logo em seguida — "4º" chega aqui como "4O".
const RE_ANO_EXPLICITO = /\b(\d\s*[º°O]?\s*ANO|ANO\s*\d)\b/;

export function participaDePremiacao(anoEscolar: string | null | undefined): boolean {
  const plano = (anoEscolar ?? "")
    .normalize("NFKD").replace(/[̀-ͯ]/g, "").toUpperCase().trim();
  if (!plano) return true; // sem rótulo não dá para afirmar que é fase
  if (!RE_ANO_EXPLICITO.test(plano) && RE_ETAPA_FORA.test(plano)) return false;
  const n = Number((plano.match(/\d/) ?? [])[0]);
  return n >= 1 && n <= 5;
}
