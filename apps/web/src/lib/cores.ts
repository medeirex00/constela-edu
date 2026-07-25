/** Cor por faixa de nota (escala 0–100, a mesma das barras do Insights):
 *  verde ≥ 66, âmbar ≥ 33, vermelho abaixo. Usada nos marcadores do mapa e nos
 *  pontos do ranking de escolas da Secretaria. */
export function corPorMedia(media: number): string {
  if (media >= 66) return "#10b981"; // emerald-500
  if (media >= 33) return "#f59e0b"; // amber-500
  return "#f87171"; // red-400
}
