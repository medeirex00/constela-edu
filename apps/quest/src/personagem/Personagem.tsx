/**
 * Personagem 3D — o avatar do jogador, montado com geometria 3D real e
 * VIVO: respira, pisca, olha em volta (e segue o ponteiro), troca o peso,
 * balança os braços e o cabelo (física secundária). Passar o mouse = acena;
 * clicar = animação divertida (giro / pulo / comemora). Turntable no girar.
 */
import { useRef, useState } from "react";
import { useFrame } from "@react-three/fiber";
import type { Group } from "three";

import type { Avatar } from "@constela/quest-core";

import { escurecer } from "./cor";
import { Cabelo3D } from "./Cabelo3D";
import {
  Acessorio3D, Asas3D, Aura3D, Halo3D, Jetpack3D, Pet3D, Rastro3D, Skate3D, Varinha3D,
} from "./Itens3D";
import { Pernas3D, Tenis3D, Top3D } from "./Roupa3D";

const D: Required<Pick<Avatar, "pele" | "cabelo" | "cor_cabelo" | "top" | "camiseta" | "baixo" | "calca" | "tenis" | "chapeu" | "costas" | "aura" | "mao" | "pet" | "veiculo">> = {
  pele: "#F6C8A0", cabelo: "espetado", cor_cabelo: "#6B3F1D", top: "camiseta",
  camiseta: "#4EA8FF", baixo: "calca", calca: "#3A2E66", tenis: "#FF5470",
  chapeu: "nenhum", costas: "nenhum", aura: "nenhum", mao: "nenhum",
  pet: "nenhum", veiculo: "nenhum",
};

function mat(cor: string, rough = 0.72) {
  return <meshStandardMaterial color={cor} roughness={rough} metalness={0} />;
}

type Acao = { tipo: "giro" | "pulo" | "comemora" | null; t0: number };

export function Personagem({ avatar, girar = false, interativo = false }:
  { avatar: Avatar; girar?: boolean; interativo?: boolean }) {
  const a = { ...D, ...Object.fromEntries(Object.entries(avatar).filter(([, v]) => v != null)) } as typeof D;

  const grupo = useRef<Group>(null);
  const corpo = useRef<Group>(null);
  const tronco = useRef<Group>(null);
  const cabeca = useRef<Group>(null);
  const cabelo = useRef<Group>(null);
  const olhoL = useRef<Group>(null); const olhoR = useRef<Group>(null);
  const pupL = useRef<Group>(null); const pupR = useRef<Group>(null);
  const bracoL = useRef<Group>(null); const bracoR = useRef<Group>(null);
  const olhar = useRef({ x: 0, y: 0 });
  const blink = useRef({ prox: 2, t0: -1 });
  const acao = useRef<Acao>({ tipo: null, t0: 0 });
  const [hover, setHover] = useState(false);

  const mangaLonga = a.top === "moletom" || a.top === "jaqueta";
  const jardineira = a.top === "jardineira";
  const skate = a.veiculo === "skate";
  const mangaCor = mangaLonga ? a.camiseta : a.pele;

  function clicar() {
    if (!interativo || acao.current.tipo) return;
    const tipos: Acao["tipo"][] = ["giro", "pulo", "comemora"];
    acao.current = { tipo: tipos[Math.floor(Math.random() * 3)], t0: -1 };
  }

  useFrame((state) => {
    const t = state.clock.elapsedTime;
    const px = state.pointer.x, py = state.pointer.y;

    // olhar segue o ponteiro (suave)
    olhar.current.x += (px * 0.06 - olhar.current.x) * 0.08;
    olhar.current.y += (py * 0.05 - olhar.current.y) * 0.08;
    if (pupL.current) pupL.current.position.set(olhar.current.x, olhar.current.y, 0.56);
    if (pupR.current) pupR.current.position.set(olhar.current.x, olhar.current.y, 0.56);
    if (cabeca.current) {
      cabeca.current.rotation.y += (px * 0.28 - cabeca.current.rotation.y) * 0.06;
      cabeca.current.rotation.x += (-py * 0.12 - cabeca.current.rotation.x) * 0.06;
    }

    // respiração + troca de peso
    if (tronco.current) tronco.current.scale.setY(1 + Math.sin(t * 1.6) * 0.02);
    if (corpo.current) {
      corpo.current.position.y = (skate ? 0.34 : 0) + Math.sin(t * 1.6) * 0.02;
      corpo.current.rotation.z = Math.sin(t * 0.5) * 0.02;
    }
    if (cabelo.current) cabelo.current.rotation.x = Math.sin(t * 1.6 + 0.5) * 0.03;

    // piscar
    if (blink.current.t0 < 0 && t > blink.current.prox) blink.current.t0 = t;
    let ey = 1;
    if (blink.current.t0 >= 0) {
      const f = (t - blink.current.t0) / 0.14;
      if (f >= 1) { blink.current.t0 = -1; blink.current.prox = t + 2 + Math.random() * 3.5; }
      else ey = 1 - Math.sin(f * Math.PI) * 0.9;
    }
    olhoL.current?.scale.setY(ey); olhoR.current?.scale.setY(ey);

    // braços: balanço + aceno no hover
    const acenando = hover && interativo && !acao.current.tipo;
    if (bracoL.current) bracoL.current.rotation.x = Math.sin(t * 1.6) * 0.06;
    if (bracoR.current) {
      if (acenando) {
        bracoR.current.rotation.z = -1.7;
        bracoR.current.rotation.x = Math.sin(t * 9) * 0.4;
      } else {
        bracoR.current.rotation.z += (0 - bracoR.current.rotation.z) * 0.15;
        bracoR.current.rotation.x += (Math.sin(t * 1.6) * 0.06 - bracoR.current.rotation.x) * 0.15;
      }
    }

    // ação ao clicar
    const g = grupo.current;
    if (g) {
      const ac = acao.current;
      if (ac.tipo && ac.t0 < 0) ac.t0 = t;
      if (ac.tipo) {
        const p = Math.min(1, (t - ac.t0) / (ac.tipo === "giro" ? 0.9 : ac.tipo === "pulo" ? 0.7 : 1));
        if (ac.tipo === "giro") g.rotation.y = p * Math.PI * 2;
        if (ac.tipo === "pulo") g.position.y = Math.sin(p * Math.PI) * 0.5;
        if (ac.tipo === "comemora") {
          g.position.y = Math.abs(Math.sin(p * Math.PI * 2)) * 0.22;
          bracoL.current!.rotation.z = 2.2; bracoR.current!.rotation.z = -2.2;
        }
        if (p >= 1) { acao.current = { tipo: null, t0: 0 }; g.rotation.y = 0; g.position.y = 0; }
      } else if (girar) {
        g.rotation.y = Math.sin(t * 0.5) * 0.5;
      } else {
        g.rotation.y += (0 - g.rotation.y) * 0.1;
      }
    }
  });

  return (
    <group ref={grupo}
           onPointerOver={interativo ? () => setHover(true) : undefined}
           onPointerOut={interativo ? () => setHover(false) : undefined}
           onClick={interativo ? clicar : undefined}>
      {skate && <Skate3D />}
      <group ref={corpo}>
        {a.aura === "estelar" && <Aura3D />}
        {a.aura === "halo" && <Halo3D />}
        {a.aura === "rastro" && <Rastro3D />}
        {a.costas === "asas" && <Asas3D />}
        {a.costas === "jetpack" && <Jetpack3D />}
        {a.costas === "mochila" && (
          <group position={[0, 1.22, -0.34]}>
            <RoundedMochila cor="#7C6FF0" />
          </group>
        )}

        {/* pernas + tênis */}
        <Pernas3D baixo={a.baixo} jardineira={jardineira} corBaixo={a.calca} corTop={a.camiseta} pele={a.pele} />
        <Tenis3D cor={a.tenis} />

        <group ref={tronco}>
          <Top3D estilo={a.top} cor={a.camiseta} pele={a.pele} />

          {/* braços */}
          <group ref={bracoL} position={[-0.5, 1.5, 0]} rotation={[0, 0, 0.12]}>
            <mesh position={[0, -0.32, 0]} castShadow><capsuleGeometry args={[0.14, 0.44, 8, 16]} />{mat(mangaCor)}</mesh>
            <mesh position={[0, -0.64, 0]} castShadow><sphereGeometry args={[0.15, 16, 16]} />{mat(a.pele, 0.75)}</mesh>
            {!mangaLonga && !jardineira && <mesh position={[0, -0.12, 0]}><sphereGeometry args={[0.19, 16, 16]} />{mat(a.camiseta)}</mesh>}
          </group>
          <group ref={bracoR} position={[0.5, 1.5, 0]} rotation={[0, 0, -0.12]}>
            <mesh position={[0, -0.32, 0]} castShadow><capsuleGeometry args={[0.14, 0.44, 8, 16]} />{mat(mangaCor)}</mesh>
            <mesh position={[0, -0.64, 0]} castShadow><sphereGeometry args={[0.15, 16, 16]} />{mat(a.pele, 0.75)}</mesh>
            {!mangaLonga && !jardineira && <mesh position={[0, -0.12, 0]}><sphereGeometry args={[0.19, 16, 16]} />{mat(a.camiseta)}</mesh>}
          </group>

          {/* pescoço + cabeça */}
          <mesh position={[0, 1.66, 0]}><cylinderGeometry args={[0.16, 0.18, 0.2, 16]} />{mat(a.pele, 0.75)}</mesh>
          <group ref={cabeca} position={[0, 2.0, 0]}>
            <group position={[0, -2.0, 0]}>
              <mesh position={[0, 2.0, 0]} castShadow><sphereGeometry args={[0.62, 32, 28]} />{mat(a.pele, 0.72)}</mesh>
              {[-1, 1].map((s) => <mesh key={s} position={[0.6 * s, 1.98, 0]} castShadow><sphereGeometry args={[0.13, 16, 16]} />{mat(a.pele, 0.72)}</mesh>)}
              <group ref={cabelo}><Cabelo3D estilo={a.cabelo} cor={a.cor_cabelo} /></group>

              {/* olhos grandes e expressivos */}
              <group ref={olhoL} position={[-0.24, 2.04, 0]}>
                <mesh position={[0, 0, 0.44]} scale={[1, 1.25, 0.55]}><sphereGeometry args={[0.17, 22, 22]} /><meshStandardMaterial color="#fff" roughness={0.25} /></mesh>
                <group ref={pupL} position={[0, 0, 0.56]}>
                  <mesh><sphereGeometry args={[0.1, 16, 16]} /><meshStandardMaterial color="#2A2350" roughness={0.2} /></mesh>
                  <mesh position={[0.04, 0.05, 0.06]}><sphereGeometry args={[0.035, 10, 10]} /><meshStandardMaterial color="#fff" emissive="#fff" emissiveIntensity={0.6} toneMapped={false} /></mesh>
                </group>
              </group>
              <group ref={olhoR} position={[0.24, 2.04, 0]}>
                <mesh position={[0, 0, 0.44]} scale={[1, 1.25, 0.55]}><sphereGeometry args={[0.17, 22, 22]} /><meshStandardMaterial color="#fff" roughness={0.25} /></mesh>
                <group ref={pupR} position={[0, 0, 0.56]}>
                  <mesh><sphereGeometry args={[0.1, 16, 16]} /><meshStandardMaterial color="#2A2350" roughness={0.2} /></mesh>
                  <mesh position={[0.04, 0.05, 0.06]}><sphereGeometry args={[0.035, 10, 10]} /><meshStandardMaterial color="#fff" emissive="#fff" emissiveIntensity={0.6} toneMapped={false} /></mesh>
                </group>
              </group>
              {/* sobrancelhas */}
              {[-1, 1].map((s) => <mesh key={s} position={[0.24 * s, 2.3, 0.5]} rotation={[0, 0, -0.12 * s]}><boxGeometry args={[0.17, 0.045, 0.05]} />{mat(escurecer(a.cor_cabelo, 0.1), 0.6)}</mesh>)}
              {/* bochechas */}
              {[-1, 1].map((s) => <mesh key={s} position={[0.36 * s, 1.9, 0.44]} scale={[1, 0.7, 0.35]}><sphereGeometry args={[0.12, 14, 14]} /><meshStandardMaterial color="#FF9AA6" roughness={0.8} transparent opacity={0.65} /></mesh>)}
              {/* boca sorriso */}
              <mesh position={[0, 1.82, 0.54]} rotation={[0, 0, Math.PI]}><torusGeometry args={[0.13, 0.028, 8, 16, Math.PI * 0.75]} /><meshStandardMaterial color="#9A4A38" roughness={0.6} /></mesh>

              <Acessorio3D slug={a.chapeu} />
            </group>
          </group>

          {a.mao === "varinha" && <Varinha3D />}
        </group>
      </group>
      <Pet3D slug={a.pet} />
    </group>
  );
}

function RoundedMochila({ cor }: { cor: string }) {
  return (
    <group>
      <mesh castShadow><boxGeometry args={[0.5, 0.6, 0.3]} />{mat(cor)}</mesh>
      <mesh position={[0, -0.02, 0.16]}><boxGeometry args={[0.32, 0.28, 0.06]} />{mat("#A78BFA")}</mesh>
      <mesh position={[0, 0.34, 0.1]}><sphereGeometry args={[0.05, 10, 10]} /><meshStandardMaterial color="#FFC93C" emissive="#FFC93C" emissiveIntensity={0.6} toneMapped={false} /></mesh>
    </group>
  );
}
