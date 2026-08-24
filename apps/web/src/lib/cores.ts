/** Cor por faixa de nota (escala 0–100, a mesma das barras do Insights):
 *  verde ≥ 66, âmbar ≥ 33, vermelho abaixo. Usada nos marcadores do mapa e nos
 *  pontos do ranking de escolas da Secretaria. */
export function corPorMedia(media: number): string {
  if (media >= 66) return "#10b981"; // emerald-500
  if (media >= 33) return "#f59e0b"; // amber-500
  return "#f87171"; // red-400
}

/** Cor por faixa do ÍNDICE DA REDE (escala 0–1000, per capita — a métrica
 *  comparável entre escolas). Mesmas faixas de `corPorMedia`, só reescaladas,
 *  para o mapa e o ranking da Secretaria pintarem pelo número que ordena a
 *  lista: pintar pela média 0–100 deixava a escola que mais lê do município
 *  vermelha no mapa enquanto ela liderava o ranking. */
export function corPorIndice(indice: number): string {
  return corPorMedia((Number(indice) || 0) / 10);
}
