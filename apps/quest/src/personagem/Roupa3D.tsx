/**
 * Roupas 3D: torso (camiseta/moletom/jaqueta/jardineira), pernas
 * (calça/shorts/overall) e tênis chunky. Volume real com RoundedBox e
 * cápsulas. Torso centro ~y=1.22; pernas ~y=0.52; pés ~y=0.14.
 */
import { RoundedBox } from "@react-three/drei";

import { clarear, escurecer } from "./cor";

function mat(cor: string, rough = 0.72) {
  return <meshStandardMaterial color={cor} roughness={rough} metalness={0} />;
}

export function Top3D({ estilo, cor, pele }: { estilo: string; cor: string; pele: string }) {
  void pele;
  const esc = escurecer(cor, 0.14);
  const torso = (c: string, s: [number, number, number] = [0.86, 0.82, 0.5]) => (
    <RoundedBox args={s} radius={0.2} smoothness={4} position={[0, 1.22, 0]} castShadow receiveShadow>
      {mat(c)}
    </RoundedBox>
  );

  if (estilo === "jaqueta") {
    return (
      <group>
        {torso("#EFF2FA", [0.7, 0.8, 0.46])}
        {torso(cor)}
        {/* abertura da jaqueta (mostra a camiseta clara) */}
        <RoundedBox args={[0.12, 0.74, 0.06]} radius={0.03} position={[0, 1.22, 0.26]}>
          {mat("#EFF2FA")}
        </RoundedBox>
        {/* zíper */}
        <mesh position={[0, 1.22, 0.28]}><boxGeometry args={[0.03, 0.72, 0.02]} />{mat(esc, 0.4)}</mesh>
        {/* gola */}
        <mesh position={[0, 1.58, 0.16]} rotation={[0.5, 0, 0]}>
          <torusGeometry args={[0.2, 0.06, 8, 20, Math.PI]} />{mat(esc)}
        </mesh>
      </group>
    );
  }

  if (estilo === "jardineira") {
    return (
      <group>
        {torso("#EFF2FA", [0.82, 0.8, 0.48])}
        {/* peito da jardineira */}
        <RoundedBox args={[0.5, 0.42, 0.5]} radius={0.1} position={[0, 1.06, 0.02]} castShadow>{mat(cor)}</RoundedBox>
        {/* alças */}
        {[-1, 1].map((s) => (
          <RoundedBox key={s} args={[0.12, 0.5, 0.14]} radius={0.05}
                      position={[0.24 * s, 1.42, 0.2]} rotation={[0.1, 0, 0.05 * s]}>{mat(cor)}</RoundedBox>
        ))}
        <mesh position={[-0.18, 1.2, 0.28]}><sphereGeometry args={[0.05, 10, 10]} />{mat("#FFC93C", 0.4)}</mesh>
        <mesh position={[0.18, 1.2, 0.28]}><sphereGeometry args={[0.05, 10, 10]} />{mat("#FFC93C", 0.4)}</mesh>
      </group>
    );
  }

  // camiseta ou moletom
  return (
    <group>
      {torso(cor)}
      {estilo === "moletom" && (
        <>
          {/* capuz atrás */}
          <mesh position={[0, 1.62, -0.22]} rotation={[0.4, 0, 0]} castShadow>
            <sphereGeometry args={[0.34, 20, 16, 0, Math.PI * 2, 0, Math.PI * 0.7]} />
            {mat(esc)}
          </mesh>
          {/* bolso */}
          <RoundedBox args={[0.5, 0.22, 0.12]} radius={0.06} position={[0, 1.02, 0.26]}>{mat(esc)}</RoundedBox>
          {/* cordões */}
          {[-1, 1].map((s) => (
            <mesh key={s} position={[0.08 * s, 1.42, 0.28]}>
              <cylinderGeometry args={[0.018, 0.018, 0.24, 8]} />{mat("#EFF2FA", 0.5)}
            </mesh>
          ))}
        </>
      )}
      {/* estrela no peito */}
      <mesh position={[0, 1.26, 0.27]} rotation={[0, 0, 0]}>
        <circleGeometry args={[0.12, 5]} />
        <meshStandardMaterial color={clarear(cor, 0.5)} roughness={0.5} />
      </mesh>
    </group>
  );
}

export function Pernas3D({ baixo, jardineira, corBaixo, corTop, pele }:
  { baixo: string; jardineira: boolean; corBaixo: string; corTop: string; pele: string }) {
  const corCalca = jardineira ? corTop : corBaixo;
  const shorts = !jardineira && baixo === "shorts";
  return (
    <group>
      {[-1, 1].map((s) => (
        <group key={s} position={[0.22 * s, 0, 0]}>
          {/* pele da perna */}
          <mesh position={[0, 0.5, 0]} castShadow>
            <capsuleGeometry args={[0.16, 0.5, 8, 16]} />{mat(pele, 0.75)}
          </mesh>
          {/* calça */}
          {shorts ? (
            <mesh position={[0, 0.72, 0]} castShadow>
              <capsuleGeometry args={[0.18, 0.16, 8, 16]} />{mat(corCalca)}
            </mesh>
          ) : (
            <mesh position={[0, 0.5, 0]} castShadow>
              <capsuleGeometry args={[0.185, 0.5, 8, 16]} />{mat(corCalca)}
            </mesh>
          )}
        </group>
      ))}
    </group>
  );
}

export function Tenis3D({ cor }: { cor: string }) {
  return (
    <group>
      {[-1, 1].map((s) => (
        <group key={s} position={[0.22 * s, 0.14, 0.08]}>
          <RoundedBox args={[0.32, 0.24, 0.52]} radius={0.11} smoothness={4} castShadow receiveShadow>
            {mat(cor, 0.5)}
          </RoundedBox>
          {/* sola */}
          <RoundedBox args={[0.34, 0.1, 0.54]} radius={0.05} position={[0, -0.1, 0]}>
            {mat("#F2EFFF", 0.4)}
          </RoundedBox>
          {/* cadarço */}
          <mesh position={[0, 0.08, 0.14]}><boxGeometry args={[0.2, 0.06, 0.04]} />{mat(escurecer(cor, 0.2), 0.4)}</mesh>
        </group>
      ))}
    </group>
  );
}
