/**
 * Cenário de um planeta — compõe as camadas que dão a sensação de viajar
 * para um mundo próprio por matéria:
 *   atmosfera (nebulosas de luz) · constelações vivas · corpo do planeta ·
 *   primeiro-plano temático · partículas.
 * Troca com fade quando a matéria muda. Sem matéria, mantém só as
 * constelações vivas de ambiente (o espaço vivo do lobby).
 */
import { useEffect, useRef, useState } from "react";

import { CENAS_TEMA } from "./cenasTema";
import { ConstelacoesVivas } from "./ConstelacoesVivas";
import { MATERIA_POR_SLUG } from "./materias";
import { Particulas } from "./Particulas";
import { Planeta } from "./Planeta";
import "./cena.css";

export function Cena({ slug }: { slug: string }) {
  const [atual, setAtual] = useState(slug);
  const [visivel, setVisivel] = useState(true);
  const anterior = useRef(slug);

  useEffect(() => {
    if (slug === anterior.current) return;
    anterior.current = slug;
    setVisivel(false);
    const t = window.setTimeout(() => {
      setAtual(slug);
      setVisivel(true);
    }, 260);
    return () => window.clearTimeout(t);
  }, [slug]);

  const materia = MATERIA_POR_SLUG[atual];

  return (
    <div className="cena" aria-hidden>
      <ConstelacoesVivas />
      {materia && (
        <div
          className={`cena-tema${visivel ? "" : " esvanecendo"}`}
          style={{
            "--neb1": materia.nebulas[0],
            "--neb2": materia.nebulas[1],
          } as React.CSSProperties}
        >
          <div className="cena-atmosfera" />
          <Planeta materia={materia} />
          <svg className="cena-foreground" viewBox="0 0 1440 900"
               preserveAspectRatio="xMidYMax slice"
               dangerouslySetInnerHTML={{ __html: CENAS_TEMA[atual] ?? "" }} />
          <Particulas config={materia.particula} />
        </div>
      )}
    </div>
  );
}
