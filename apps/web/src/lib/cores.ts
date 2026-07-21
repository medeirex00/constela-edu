/** Cores de UI compartilhadas entre as telas de perfil. */

/** Cor por desempenho (média 0–10): verde (alto) → âmbar → vermelho (baixo). */
export function corPorMedia(m: number): string {
  if (m >= 7) return "#2EB88A";
  if (m >= 5) return "#F5B942";
  return "#E2555A";
}
