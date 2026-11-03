/**
 * Páginas públicas sem login (telão da escola, perfil público do aluno e
 * vitrine da rede): pede aos buscadores que não indexem, não sigam e não
 * arquivem a página enquanto ela está montada (`<meta name="robots">`).
 *
 * Esses endereços são feitos para circular (QR para as famílias) e o telão
 * pode trazer nome de criança — uma cópia indexada sobreviveria até à troca do
 * token. O meta complementa o `X-Robots-Tag` que a borda (vercel.json,
 * nginx.conf) e a API mandam nessas rotas. Fica por PÁGINA, e não no
 * index.html: lá desindexaria o SPA inteiro, login incluso.
 */
import { useLayoutEffect } from "react";

export const ROBOTS_NAO_INDEXAR = "noindex, nofollow, noarchive";

export function useSemIndexacao(): void {
  useLayoutEffect(() => {
    const meta = document.createElement("meta");
    meta.name = "robots";
    meta.content = ROBOTS_NAO_INDEXAR;
    document.head.appendChild(meta);
    return () => meta.remove();
  }, []);
}
