import { useEffect, useState, type RefObject } from "react";

/**
 * Há conteúdo escondido no começo/fim de um contêiner que rola? Fonte única para os
 * avisos de rolagem da v2: os esmaecidos da lista do menu lateral (eixo y) e os
 * degradês das tabelas largas (eixo x). Mede ao rolar, ao redimensionar a janela e
 * quando o contêiner ou um filho direto muda de tamanho (grupo do menu que abre,
 * tabela que recebe dados). Só muda o estado quando o resultado muda.
 */
export function useBordasDaRolagem(
  ref: RefObject<HTMLElement | null>,
  eixo: "x" | "y" = "y",
  ativo = true,
): { inicio: boolean; fim: boolean } {
  const [bordas, setBordas] = useState({ inicio: false, fim: false });
  useEffect(() => {
    const el = ref.current;
    if (!ativo || !el) return;
    const medir = () => {
      const [pos, visivel, total] = eixo === "y"
        ? [el.scrollTop, el.clientHeight, el.scrollHeight]
        : [el.scrollLeft, el.clientWidth, el.scrollWidth];
      const inicio = pos > 1;
      const fim = pos + visivel < total - 1;
      setBordas((atual) => (atual.inicio === inicio && atual.fim === fim ? atual : { inicio, fim }));
    };
    medir();
    el.addEventListener("scroll", medir, { passive: true });
    window.addEventListener("resize", medir);
    // O tamanho do CONTÊINER nem sempre muda quando o conteúdo muda: observa também
    // os filhos diretos.
    const observador = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(medir);
    if (observador) {
      observador.observe(el);
      for (const filho of Array.from(el.children)) observador.observe(filho);
    }
    return () => {
      el.removeEventListener("scroll", medir);
      window.removeEventListener("resize", medir);
      observador?.disconnect();
    };
  }, [ref, eixo, ativo]);
  return bordas;
}
