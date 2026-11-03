/** Cor por faixa do ÍNDICE DA REDE (escala 0–1000, per capita — a métrica
 *  comparável entre escolas), para o mapa pintar pelo número que ordena a
 *  lista: pintar pela média 0–100 deixava a escola que mais lê do município
 *  vermelha no mapa enquanto ela liderava o ranking. Verde ≥ 660; o vermelho
 *  começa no MESMO corte do alerta de "índice baixo" do Painel da Rede (abaixo
 *  de 300 — `INDICE_BAIXO`, backend/app/services/rede.py): com o antigo 330, a
 *  escola com índice 315 saía vermelha no mapa e ficava fora dos alertas ao lado. */
export function corPorIndice(indice: number): string {
  const i = Number(indice) || 0;
  // Tons 600: marcador e bolinha precisam de 3:1 sobre o branco (WCAG 1.4.11);
  // os 500/400 antigos davam 2,2–2,8:1. A faixa também vai em texto ao lado.
  if (i >= 660) return "#059669"; // emerald-600 (3,8:1)
  if (i >= 300) return "#D97706"; // amber-600 (3,2:1)
  return "#DC2626"; // red-600 (4,8:1)
}
