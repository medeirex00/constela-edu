import { useEffect, useState } from "react";

/**
 * Janelamento de lista (virtualização leve, sem dependência externa).
 *
 * Renderiza apenas os primeiros `passo` itens e revela mais sob demanda
 * (botão "mostrar mais"). Em escolas grandes, evita montar centenas de linhas
 * de uma vez — o custo do DOM cresce só conforme o usuário avança. Reinicia a
 * janela sempre que a lista muda (novo período/filtro), para nunca mostrar um
 * recorte obsoleto.
 *
 *   const { visiveis, restantes, mostrarMais } = useJanela(itens);
 *   {visiveis.map(...)}
 *   {restantes > 0 && <button onClick={mostrarMais}>Mostrar mais</button>}
 */
export function useJanela<T>(itens: T[], passo = 60) {
  const [limite, setLimite] = useState(passo);

  // A identidade de `itens` muda a cada nova busca do useApi (novo array),
  // então trocar período/filtro volta a janela ao início automaticamente.
  useEffect(() => {
    setLimite(passo);
  }, [itens, passo]);

  return {
    visiveis: itens.slice(0, limite),
    restantes: Math.max(0, itens.length - limite),
    mostrarMais: () => setLimite((n) => n + passo),
  };
}
