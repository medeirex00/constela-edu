/**
 * Acessórios e itens especiais 3D. Cabeça: centro (0,2,0) r=0.62. Itens
 * especiais têm brilho (emissivo), luz própria e animação (asas batem, aura
 * orbita, jatos tremeluzem, halo gira, pet flutua).
 */
import { useRef } from "react";
import type { RefObject } from "react";
import { useFrame } from "@react-three/fiber";
import { RoundedBox } from "@react-three/drei";
import type { Group, Mesh } from "three";

function mat(cor: string, rough = 0.6) {
  return <meshStandardMaterial color={cor} roughness={rough} metalness={0} />;
}
function brilho(cor: string, intensidade = 1.1) {
  return <meshStandardMaterial color={cor} emissive={cor} emissiveIntensity={intensidade}
                               roughness={0.35} toneMapped={false} />;
}

// ---- Acessórios de cabeça (slot chapeu) ---------------------------------
export function Acessorio3D({ slug }: { slug: string }) {
  switch (slug) {
    case "oculos":
      return (
        <group>
          {[-0.24, 0.24].map((x) => (
            <mesh key={x} position={[x, 2.02, 0.52]}>
              <torusGeometry args={[0.16, 0.03, 10, 24]} />{mat("#231D4E", 0.4)}
            </mesh>
          ))}
          <mesh position={[0, 2.02, 0.52]}><boxGeometry args={[0.14, 0.03, 0.03]} />{mat("#231D4E", 0.4)}</mesh>
        </group>
      );
    case "bone":
      return (
        <group position={[0, 2.02, 0]}>
          <mesh position={[0, 0.34, 0]} castShadow>
            <sphereGeometry args={[0.64, 22, 16, 0, Math.PI * 2, 0, Math.PI * 0.5]} />{mat("#3D5AFE")}
          </mesh>
          <mesh position={[0, 0.3, 0.5]} rotation={[0.4, 0, 0]} castShadow>
            <cylinderGeometry args={[0.36, 0.36, 0.06, 20, 1, false, 0, Math.PI]} />{mat("#2B3FB0")}
          </mesh>
          <mesh position={[0, 0.5, 0.1]}><sphereGeometry args={[0.05, 10, 10]} />{mat("#fff")}</mesh>
        </group>
      );
    case "coroa":
      return (
        <group position={[0, 2.62, 0]}>
          <mesh><torusGeometry args={[0.4, 0.06, 10, 24]} />{brilho("#FFC93C", 0.5)}</mesh>
          {[0, 1, 2, 3, 4].map((i) => {
            const a = (i / 5) * Math.PI * 2;
            return <mesh key={i} position={[Math.cos(a) * 0.4, 0.12, Math.sin(a) * 0.4]}>
              <coneGeometry args={[0.07, 0.2, 8]} />{brilho("#FFC93C", 0.5)}</mesh>;
          })}
        </group>
      );
    case "fone":
    case "catfone":
      return (
        <group position={[0, 2.0, 0]}>
          <mesh position={[0, 0.42, 0]} rotation={[0, 0, 0]}>
            <torusGeometry args={[0.62, 0.06, 10, 24, Math.PI]} />{mat(slug === "catfone" ? "#7A3DF0" : "#231D4E", 0.5)}
          </mesh>
          {[-1, 1].map((s) => (
            <RoundedBox key={s} args={[0.16, 0.28, 0.24]} radius={0.07}
                        position={[0.62 * s, 0.02, 0]}>{mat(slug === "catfone" ? "#7A3DF0" : "#231D4E", 0.5)}</RoundedBox>
          ))}
          {slug === "catfone" && [-1, 1].map((s) => (
            <mesh key={s} position={[0.34 * s, 0.7, 0]} rotation={[0, 0, -0.3 * s]}>
              <coneGeometry args={[0.14, 0.28, 4]} />{mat("#B57BFF")}
            </mesh>
          ))}
        </group>
      );
    case "capacete":
      return (
        <group position={[0, 2.0, 0]}>
          <mesh>
            <sphereGeometry args={[0.78, 28, 22]} />
            <meshStandardMaterial color="#BFE2FF" transparent opacity={0.28} roughness={0.1} metalness={0.1} />
          </mesh>
          <mesh position={[0, -0.5, 0]}><torusGeometry args={[0.6, 0.08, 10, 24]} />{mat("#EDEFF6", 0.4)}</mesh>
          <pointLight position={[0.3, 0.3, 0.4]} intensity={0.4} distance={2} color="#BFE2FF" />
        </group>
      );
    default:
      return null;
  }
}

// ---- Asas de luz ---------------------------------------------------------
export function Asas3D() {
  const l = useRef<Group>(null); const r = useRef<Group>(null);
  useFrame((s) => {
    const a = Math.sin(s.clock.elapsedTime * 2.2) * 0.34;
    if (l.current) l.current.rotation.y = 0.5 + a;
    if (r.current) r.current.rotation.y = -0.5 - a;
  });
  const asa = (ref: RefObject<Group>, lado: number) => (
    <group ref={ref} position={[0.2 * lado, 1.35, -0.28]}>
      {[0, 1, 2].map((i) => (
        <mesh key={i} position={[0.28 * lado * (i + 1), 0.12 * (1 - i), 0]}
              rotation={[0, 0, (0.3 - i * 0.25) * lado]} scale={[1, 1, 0.3]}>
          <capsuleGeometry args={[0.16 - i * 0.02, 0.5 - i * 0.08, 6, 12]} />
          <meshStandardMaterial color="#DFF3FF" emissive="#7FD0FF" emissiveIntensity={0.9}
                                roughness={0.3} transparent opacity={0.92} toneMapped={false} />
        </mesh>
      ))}
    </group>
  );
  return (
    <group>
      {asa(l, -1)}{asa(r, 1)}
      <pointLight position={[0, 1.4, -0.4]} intensity={0.6} distance={3} color="#7FD0FF" />
    </group>
  );
}

// ---- Aura estelar --------------------------------------------------------
export function Aura3D() {
  const g = useRef<Group>(null);
  useFrame((_state, d) => { if (g.current) g.current.rotation.y += d * 0.6; });
  return (
    <group ref={g} position={[0, 1.1, 0]}>
      {Array.from({ length: 14 }).map((_, i) => {
        const a = (i / 14) * Math.PI * 2;
        const y = Math.sin(a * 3) * 0.5;
        return <mesh key={i} position={[Math.cos(a) * 1.05, y, Math.sin(a) * 1.05]}>
          <sphereGeometry args={[0.06, 8, 8]} />{brilho("#C0A6FF", 1.4)}</mesh>;
      })}
      <pointLight intensity={0.5} distance={4} color="#A78BFA" />
    </group>
  );
}

export function Halo3D() {
  const g = useRef<Group>(null);
  useFrame((s) => { if (g.current) { g.current.rotation.y += 0.01; g.current.position.y = 2.78 + Math.sin(s.clock.elapsedTime * 2) * 0.03; } });
  return (
    <group ref={g} position={[0, 2.78, 0]}>
      <mesh rotation={[Math.PI / 2, 0, 0]}><torusGeometry args={[0.38, 0.05, 10, 28]} />{brilho("#FFE59E", 1.3)}</mesh>
      <pointLight intensity={0.4} distance={2.5} color="#FFE59E" />
    </group>
  );
}

export function Rastro3D() {
  const g = useRef<Group>(null);
  useFrame((s) => { if (g.current) g.current.children.forEach((c, i) => { c.position.y = 1.0 - i * 0.34 + Math.sin(s.clock.elapsedTime * 2 + i) * 0.05; }); });
  return (
    <group ref={g} position={[-0.9, 0, -0.2]}>
      {[0, 1, 2, 3].map((i) => (
        <mesh key={i} position={[-i * 0.14, 1.0 - i * 0.34, 0]} scale={1 - i * 0.18}>
          <icosahedronGeometry args={[0.12, 0]} />{brilho("#FFE59E", 1.2)}
        </mesh>
      ))}
    </group>
  );
}

// ---- Jetpack -------------------------------------------------------------
export function Jetpack3D() {
  const f = useRef<Group>(null);
  useFrame((s) => { if (f.current) { const k = 0.8 + Math.abs(Math.sin(s.clock.elapsedTime * 20)) * 0.5; f.current.scale.y = k; } });
  return (
    <group position={[0, 1.2, -0.34]}>
      {[-1, 1].map((s) => (
        <mesh key={s} position={[0.26 * s, 0, 0]} castShadow>
          <cylinderGeometry args={[0.14, 0.14, 0.6, 16]} />{mat("#5A5480", 0.5)}
        </mesh>
      ))}
      <group ref={f}>
        {[-1, 1].map((s) => (
          <mesh key={s} position={[0.26 * s, -0.42, 0]}>
            <coneGeometry args={[0.1, 0.34, 12]} />{brilho("#FF8E3C", 1.5)}
          </mesh>
        ))}
      </group>
      <pointLight position={[0, -0.5, 0]} intensity={0.5} distance={2} color="#FF8E3C" />
    </group>
  );
}

// ---- Varinha (na mão direita) -------------------------------------------
export function Varinha3D() {
  const p = useRef<Mesh>(null);
  useFrame((s) => { if (p.current) { const k = 1 + Math.sin(s.clock.elapsedTime * 4) * 0.2; p.current.scale.setScalar(k); } });
  return (
    <group position={[0.62, 1.05, 0.2]} rotation={[0, 0, -0.3]}>
      <mesh position={[0, 0.25, 0]}><cylinderGeometry args={[0.03, 0.03, 0.5, 8]} />{mat("#C89B3C", 0.4)}</mesh>
      <mesh ref={p} position={[0, 0.56, 0]}>
        <icosahedronGeometry args={[0.14, 0]} />{brilho("#FFC93C", 1.5)}
      </mesh>
      <pointLight position={[0, 0.56, 0]} intensity={0.6} distance={2} color="#FFC93C" />
    </group>
  );
}

// ---- Skate voador (sob os pés) ------------------------------------------
export function Skate3D() {
  const g = useRef<Group>(null); const f = useRef<Group>(null);
  useFrame((s) => {
    if (g.current) g.current.position.y = -0.04 + Math.sin(s.clock.elapsedTime * 2) * 0.04;
    if (f.current) f.current.scale.x = 0.8 + Math.abs(Math.sin(s.clock.elapsedTime * 18)) * 0.5;
  });
  return (
    <group ref={g}>
      <RoundedBox args={[0.6, 0.12, 1.5]} radius={0.06} smoothness={4} position={[0, 0, 0]} castShadow>
        <meshStandardMaterial color="#7C6FF0" roughness={0.35} emissive="#4EA8FF" emissiveIntensity={0.3} />
      </RoundedBox>
      <group ref={f}>
        {[-1, 1].map((s) => (
          <mesh key={s} position={[0.32 * s, 0, -0.78]} rotation={[Math.PI / 2, 0, 0]}>
            <coneGeometry args={[0.08, 0.4, 10]} />{brilho("#FF8E3C", 1.5)}
          </mesh>
        ))}
      </group>
      <pointLight position={[0, -0.2, 0]} intensity={0.5} distance={2.5} color="#7FD0FF" />
    </group>
  );
}

// ---- Pets ---------------------------------------------------------------
export function Pet3D({ slug }: { slug: string }) {
  const g = useRef<Group>(null);
  useFrame((s) => { if (g.current) g.current.position.y = (slug === "robo" || slug === "estrelinha" ? 0.55 : 0.32) + Math.sin(s.clock.elapsedTime * 2.4) * (slug === "robo" || slug === "estrelinha" ? 0.08 : 0.03); });
  if (slug === "nenhum") return null;
  return (
    <group ref={g} position={[1.15, 0.32, 0.2]}>
      {slug === "gatinho" && (
        <group>
          <mesh castShadow><sphereGeometry args={[0.22, 18, 16]} />{mat("#FF8E3C")}</mesh>
          <mesh position={[0, 0.24, 0]} castShadow><sphereGeometry args={[0.18, 18, 16]} />{mat("#FF8E3C")}</mesh>
          {[-1, 1].map((s) => <mesh key={s} position={[0.1 * s, 0.4, 0]} rotation={[0, 0, -0.3 * s]}><coneGeometry args={[0.06, 0.14, 8]} />{mat("#FF8E3C")}</mesh>)}
          {[-1, 1].map((s) => <mesh key={s} position={[0.07 * s, 0.26, 0.16]}><sphereGeometry args={[0.03, 8, 8]} />{mat("#231D4E", 0.3)}</mesh>)}
        </group>
      )}
      {slug === "dino" && (
        <group>
          <mesh castShadow><sphereGeometry args={[0.24, 18, 16]} />{mat("#2EE6A8")}</mesh>
          <mesh position={[0, 0.26, 0]} castShadow><sphereGeometry args={[0.17, 18, 16]} />{mat("#2EE6A8")}</mesh>
          {[0, 1].map((i) => <mesh key={i} position={[0, 0.44 - i * 0.14, -0.12 + i * 0.02]}><coneGeometry args={[0.05, 0.12, 6]} />{mat("#12B8A6")}</mesh>)}
          {[-1, 1].map((s) => <mesh key={s} position={[0.07 * s, 0.28, 0.15]}><sphereGeometry args={[0.03, 8, 8]} />{mat("#231D4E", 0.3)}</mesh>)}
        </group>
      )}
      {slug === "estrelinha" && (
        <mesh><icosahedronGeometry args={[0.24, 0]} />{brilho("#FFC93C", 1.3)}</mesh>
      )}
      {slug === "robo" && (
        <group>
          <RoundedBox args={[0.34, 0.3, 0.28]} radius={0.1} castShadow>{mat("#9BB7D0", 0.4)}</RoundedBox>
          <mesh position={[0, 0, 0.15]}><boxGeometry args={[0.24, 0.16, 0.02]} />{mat("#231D4E", 0.2)}</mesh>
          {[-1, 1].map((s) => <mesh key={s} position={[0.06 * s, 0, 0.17]}><sphereGeometry args={[0.03, 10, 10]} />{brilho("#5FD0FF", 1.4)}</mesh>)}
          <mesh position={[0, 0.24, 0]}><sphereGeometry args={[0.05, 10, 10]} />{brilho("#FFC93C", 1.2)}</mesh>
        </group>
      )}
    </group>
  );
}
