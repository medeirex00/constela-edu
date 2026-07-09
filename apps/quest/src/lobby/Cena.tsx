/**
 * Cenário temático de fundo. Troca com fade quando a matéria muda. O SVG é
 * conteúdo estático do próprio app (cenas.ts) — dangerouslySetInnerHTML é
 * seguro aqui.
 */
import { useEffect, useRef, useState } from "react";

import { CENAS } from "./cenas";
import "./cena.css";

export function Cena({ slug }: { slug: string }) {
  const [atual, setAtual] = useState(slug);
  const [visivel, setVisivel] = useState(true);
  const anterior = useRef(slug);

  useEffect(() => {
    if (slug === anterior.current) return;
    anterior.current = slug;
    setVisivel(false);                       // fade out
    const t = window.setTimeout(() => {
      setAtual(slug);
      setVisivel(true);                      // fade in do novo
    }, 260);
    return () => window.clearTimeout(t);
  }, [slug]);

  return (
    <div
      className={`cena${visivel ? "" : " esvanecendo"}`}
      aria-hidden
      dangerouslySetInnerHTML={{ __html: CENAS[atual] ?? CENAS.lobby }}
    />
  );
}
