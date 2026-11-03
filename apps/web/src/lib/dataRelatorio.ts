/**
 * Data do relatório numa importação MANUAL.
 *
 * Sem ela, o servidor datava o retrato com o relógio de agora: um relatório antigo
 * (o arquivo de exemplo de agosto) virava "o dado de hoje" — ranking e nota caíam
 * para o valor antigo e o retrato que a sincronização tinha gravado era
 * sobrescrito. No total acumulado (formato "resumo" sem "Intervalo de datas"), a
 * tela PEDE a data em que o relatório foi gerado — padrão vazio, sem presumir
 * hoje — e a envia como `data_referencia`.
 */

const FUSO_BR = "America/Sao_Paulo";
const DIA_ISO = /^\d{4}-\d{2}-\d{2}$/;

/** Hoje no fuso de Brasília, "AAAA-MM-DD" (o máximo do campo de data). */
export function hojeEmBrasilia(agora: Date = new Date()): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: FUSO_BR, year: "numeric", month: "2-digit", day: "2-digit",
  }).format(agora);
}

/** O primeiro dia aceito, "AAAA-MM-DD" (o mínimo do campo de data): 1º de janeiro
 *  do ano letivo ANTERIOR ao da escola — sem o ano letivo, o anterior ao ano de
 *  hoje em Brasília. Antes disso a data quase sempre é erro de digitação (2006 em
 *  vez de 2026); o servidor recusa com a mesma regra. */
export function primeiroDiaDoRelatorio(
  anoLetivo?: number | null,
  agora: Date = new Date(),
): string {
  const ano = anoLetivo ?? Number(hojeEmBrasilia(agora).slice(0, 4));
  return `${String(Math.max(ano - 1, 1)).padStart(4, "0")}-01-01`;
}

/** A tela exige a data? Só no total acumulado: o relatório por período (Matific
 *  com "Intervalo de datas") já traz as datas, e o individual (leituras) só soma. */
export function exigeDataDoRelatorio(analise: {
  formato: string;
  periodo_inicio?: string | null;
  periodo_fim?: string | null;
}): boolean {
  return analise.formato === "resumo" && !(analise.periodo_inicio && analise.periodo_fim);
}

/** Dia preenchido, no formato do campo e não depois de hoje (Brasília). */
function diaAteHoje(dia: string, agora: Date): boolean {
  return DIA_ISO.test(dia) && dia <= hojeEmBrasilia(agora);
}

/** Dia preenchido, no formato do campo, entre o primeiro dia aceito
 *  (`primeiroDiaDoRelatorio`) e hoje (Brasília). */
export function dataDoRelatorioValida(
  dia: string,
  agora: Date = new Date(),
  anoLetivo?: number | null,
): boolean {
  return diaAteHoje(dia, agora) && dia >= primeiroDiaDoRelatorio(anoLetivo, agora);
}

/** O que há de errado com o dia escolhido (texto do alerta da tela), ou `null`. */
export function problemaDaDataDoRelatorio(
  dia: string,
  agora: Date = new Date(),
  anoLetivo?: number | null,
): string | null {
  if (dia === "" || dataDoRelatorioValida(dia, agora, anoLetivo)) return null;
  if (DIA_ISO.test(dia) && dia > hojeEmBrasilia(agora)) {
    return "A data do relatório não pode ser depois de hoje.";
  }
  return (
    "A data do relatório parece errada: confira o ano (a partir de " +
    `${diaPorExtenso(primeiroDiaDoRelatorio(anoLetivo, agora))}).`
  );
}

/** O instante (ISO, UTC) que data os números de um relatório gerado no dia `dia`:
 *  o fim desse dia em Brasília, nunca depois de agora. `null` se o dia é inválido
 *  ou depois de hoje. O mínimo fica com a tela (`dataDoRelatorioValida`, que
 *  conhece o ano letivo da escola); o servidor recusa com a mesma regra. */
export function instanteDoRelatorio(dia: string, agora: Date = new Date()): string | null {
  if (!diaAteHoje(dia, agora)) return null;
  const fimDoDia = new Date(`${dia}T23:59:59-03:00`);
  if (Number.isNaN(fimDoDia.getTime())) return null;
  return (fimDoDia > agora ? agora : fimDoDia).toISOString();
}

/** "2026-08-14" → "14/08/2026". */
export function diaPorExtenso(dia: string): string {
  return DIA_ISO.test(dia) ? dia.split("-").reverse().join("/") : dia;
}
