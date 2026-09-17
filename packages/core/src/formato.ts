export function numero(valor: number): string {
  return valor.toLocaleString("pt-BR");
}

export function nota(valor: number): string {
  return valor.toLocaleString("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 2 });
}

/** Nota de UMA matéria com o corte de AFERIDO (Arquitetura 2).
 *
 *  Regra, e ela é dura: `aferido === false` significa que NÃO existe snapshot
 *  daquela plataforma para o aluno — não há o que medir, então a tela mostra
 *  "—". O `0,0` fica reservado ao zero LEGÍTIMO (o aluno usa a plataforma e
 *  ainda não produziu), que é uma afirmação diferente e verdadeira.
 *
 *  `aferido === undefined` = o payload NÃO traz o discriminante. Aí mostramos o
 *  número: dizer "—" seria inventar uma ausência que o servidor não declarou —
 *  o erro simétrico do que esta função existe para corrigir. É o caso de um
 *  servidor ANTIGO (anterior ao carimbo de `aferido_leitura`/`aferido_matematica`
 *  no item do Ranking Geral legado), com o qual um app já atualizado pode falar
 *  durante um rollout escalonado.
 *
 *  Vive no pacote compartilhado de propósito: web e app têm de dizer a MESMA
 *  coisa sobre a mesma criança. */
export function notaDaMateria(valor: number | null | undefined,
                              aferido?: boolean | null): string {
  return aferido === false ? "—" : nota(valor ?? 0);
}

/** Fuso oficial do produto (escolas brasileiras). Mostrar sempre no horário de
 *  Brasília, independentemente do fuso do navegador de quem acessa. */
const FUSO_BR = "America/Sao_Paulo";

/** Normaliza um timestamp da API para um Date correto.
 *
 *  A API grava os horários em UTC, mas os serializa SEM sufixo de fuso (naive,
 *  ex.: "2026-07-12T14:31:00"). Sem o "Z", o `Date` interpretaria como horário
 *  LOCAL e adiantaria o relógio (ex.: 3h em São Paulo). Aqui anexamos "Z"
 *  quando o valor tem hora e não traz marca de fuso. */
export function paraData(iso: string): Date {
  const temHora = iso.includes("T");
  const temFuso = /[zZ]$|[+-]\d{2}:?\d{2}$/.test(iso);
  return new Date(temHora && !temFuso ? `${iso}Z` : iso);
}

export function dataHora(iso: string | null): string {
  if (!iso) return "—";
  const d = paraData(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("pt-BR", {
    timeZone: FUSO_BR,
    dateStyle: "short",
    timeStyle: "short",
  });
}

export function tempoLeitura(minutos: number): string {
  if (minutos < 60) return `${minutos} min`;
  const horas = Math.floor(minutos / 60);
  const resto = minutos % 60;
  return resto ? `${horas}h ${resto}min` : `${horas}h`;
}
