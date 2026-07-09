/**
 * Palco 3D reutilizável — moldura + carregamento sob demanda da cena (o
 * bundle three.js só baixa quando um personagem aparece na tela). A cena em
 * si (Canvas + rig de luz + Personagem) vive em Cena3D. Embarcado por lobby,
 * vestiário, cerimônia e entrada.
 */
import { lazy, Suspense } from "react";

import type { Avatar } from "@constela/quest-core";

const Cena3D = lazy(() => import("./Cena3D"));

interface Props {
  avatar: Avatar;
  girar?: boolean;
  interativo?: boolean;
  altura?: string;
  className?: string;
}

export function Palco3D({ avatar, girar, interativo, altura = "60vh", className }: Props) {
  return (
    <div className={className}
         style={{ height: altura, width: "100%", pointerEvents: interativo ? "auto" : "none" }}>
      <Suspense fallback={<div className="palco-carregando" aria-hidden />}>
        <Cena3D avatar={avatar} girar={girar} interativo={interativo} />
      </Suspense>
    </div>
  );
}
