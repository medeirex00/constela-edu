/** Formatação pt-BR compartilhada — a fonte é o pacote @constela/core. */
import { paraData } from "@constela/core";

export { numero, nota, notaDaMateria, dataHora, paraData, tempoLeitura } from "@constela/core";

const FUSO_BR = "America/Sao_Paulo";

/** Dia de um horário da API no fuso de Brasília ("31/10/2026"). A API serializa UTC
 *  sem marca de fuso: `new Date(iso)` lia como horário local e, de 21h a meia-noite,
 *  mostrava o dia SEGUINTE. `curto` = "31/10". */
export function dataDia(iso: string | null | undefined, curto = false): string {
  if (!iso) return "—";
  const d = paraData(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("pt-BR", curto
    ? { timeZone: FUSO_BR, day: "2-digit", month: "2-digit" }
    : { timeZone: FUSO_BR, day: "2-digit", month: "2-digit", year: "numeric" });
}
