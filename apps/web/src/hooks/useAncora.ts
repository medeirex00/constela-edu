import { useEffect } from "react";
import { useLocation } from "react-router-dom";

/**
 * Rola suavemente até a seção cujo `id` casa com o `#hash` da URL.
 *
 * É a cola dos itens do menu da Secretaria que apontam para uma SEÇÃO de uma
 * tela existente (ex.: `/rede#mapa`, `/rede/avaliacoes#evolucao`) em vez de uma
 * rota própria. Comportamento defensivo: se o alvo ainda não montou (a tela faz
 * fetch antes de renderizar) tenta de novo por ~2s; se o alvo não existe naquele
 * modo da tela, simplesmente não faz nada — degrada sem quebrar a navegação.
 *
 * @param dep valor que, ao mudar, dispara nova tentativa (ex.: os dados da tela,
 *            para reancorar assim que o conteúdo aparece).
 */
export function useAncora(dep?: unknown) {
  const { hash } = useLocation();
  useEffect(() => {
    if (!hash) return;
    const id = decodeURIComponent(hash.slice(1));
    if (!id) return;
    let cancelado = false;
    let tentativas = 0;
    function tentar() {
      if (cancelado) return;
      const alvo = document.getElementById(id);
      if (alvo) {
        alvo.scrollIntoView({ behavior: "smooth", block: "start" });
        return;
      }
      if (tentativas++ < 20) window.setTimeout(tentar, 100);
    }
    tentar();
    return () => {
      cancelado = true;
    };
  }, [hash, dep]);
}
