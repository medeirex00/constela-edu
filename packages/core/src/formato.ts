export function numero(valor: number): string {
  return valor.toLocaleString("pt-BR");
}

export function nota(valor: number): string {
  return valor.toLocaleString("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 2 });
}

export function dataHora(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
}

export function tempoLeitura(minutos: number): string {
  if (minutos < 60) return `${minutos} min`;
  const horas = Math.floor(minutos / 60);
  const resto = minutos % 60;
  return resto ? `${horas}h ${resto}min` : `${horas}h`;
}
