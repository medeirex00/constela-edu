/**
 * Conteúdo pesado do palco (three.js / R3F / drei + Personagem). Fica num
 * módulo próprio para ser carregado sob demanda (React.lazy no Palco3D): a
 * tela de código entra na hora, sem esperar o bundle 3D — importa para os
 * tablets/wifi da escola.
 *
 * Recuperação de PERDA DE CONTEXTO WebGL: é um evento assíncrono do GPU
 * (`webglcontextlost`), que a fronteira de erro do React (LimiteErro) NÃO pega.
 * Tratamos aqui, na origem: listeners no canvas do R3F mostram a tela amigável
 * e reativam a restauração pelo navegador; se o contexto voltar (transitório),
 * o R3F reinicializa e o aviso some sozinho.
 */
import { Suspense, useState } from "react";
import { Canvas, type RootState } from "@react-three/fiber";
import { ContactShadows } from "@react-three/drei";

import type { Avatar } from "@constela/quest-core";

import { narrar, tocar } from "../audio/audio";
import { TelaReiniciar } from "../app/TelaReiniciar";
import { Personagem } from "./Personagem";

interface CenaProps {
  avatar: Avatar;
  girar?: boolean;
  interativo?: boolean;
}

export default function Cena3D({ avatar, girar, interativo }: CenaProps) {
  const [contextoPerdido, setContextoPerdido] = useState(false);

  const aoCriar = (estado: RootState) => {
    const canvas = estado.gl.domElement;
    // preventDefault habilita o evento de restauração ('webglcontextrestored').
    canvas.addEventListener("webglcontextlost", (evento) => {
      evento.preventDefault();
      setContextoPerdido(true);
      try {
        tocar("erro");
        narrar("Opa! A imagem sumiu. Espere um pouquinho ou toque no botão!");
      } catch {
        /* áudio indisponível — a tela amigável já cobre */
      }
    });
    canvas.addEventListener("webglcontextrestored", () => setContextoPerdido(false));
  };

  return (
    <>
      <Canvas
        shadows={false}
        dpr={[1, 1.75]}
        gl={{ antialias: true, alpha: true, powerPreference: "high-performance" }}
        camera={{ position: [0, 1.35, 5.4], fov: 30, near: 0.1, far: 50 }}
        style={{ background: "transparent" }}
        onCreated={aoCriar}
      >
        <ambientLight intensity={0.55} />
        <hemisphereLight args={["#bcd4ff", "#463a66", 0.55]} />
        <directionalLight position={[3.5, 6, 4]} intensity={1.25} color="#fff6ec" />
        <directionalLight position={[-4, 2.5, -3]} intensity={0.5} color="#cfe3ff" />
        <directionalLight position={[0, 3, -5]} intensity={0.6} color="#ffffff" />
        <Suspense fallback={null}>
          <group position={[0, -1.15, 0]}>
            <Personagem avatar={avatar} girar={girar} interativo={interativo} />
            <ContactShadows position={[0, 0.01, 0]} opacity={0.42} scale={6}
                            blur={2.6} far={4} resolution={256} color="#170f2e" />
          </group>
        </Suspense>
      </Canvas>
      {contextoPerdido && (
        <TelaReiniciar
          onReiniciar={() => window.location.reload()}
          titulo="A imagem está voltando..."
          detalhe="Se demorar, é só tocar no botão para recomeçar."
        />
      )}
    </>
  );
}
