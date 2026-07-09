/**
 * Cabelos 3D (slot `cabelo` + `cor_cabelo`). Cabeça: esfera centro (0,2,0)
 * raio 0.62. O cabelo é modelado com um "capacete" (esfera parcial) + volumes
 * (topetes/cachos/coques/puffs) para dar forma e volume reais.
 */
import { escurecer } from "./cor";

const HR = 0.64; // raio do capacete de cabelo

function mat(cor: string, rough = 0.75) {
  return <meshStandardMaterial color={cor} roughness={rough} metalness={0} />;
}

export function Cabelo3D({ estilo, cor }: { estilo: string; cor: string }) {
  const esc = escurecer(cor, 0.14);
  // capacete base cobrindo topo/laterais (esfera parcial)
  const capacete = (raio = HR, theta = Math.PI * 0.62) => (
    <mesh position={[0, 2.0, 0]} castShadow>
      <sphereGeometry args={[raio, 28, 20, 0, Math.PI * 2, 0, theta]} />
      {mat(cor)}
    </mesh>
  );

  switch (estilo) {
    case "careca":
      return null;

    case "espetado":
      return (
        <group>
          {capacete(0.63, Math.PI * 0.55)}
          {[[-0.32, 0.35], [-0.1, 0.5], [0.14, 0.52], [0.36, 0.34], [0, 0.62]].map(
            ([x, up], i) => (
              <mesh key={i} position={[x, 2.28 + up * 0.25, 0.08]}
                    rotation={[0.2, 0, x * 0.5]} castShadow>
                <coneGeometry args={[0.15, 0.42, 12]} />
                {mat(cor)}
              </mesh>
            ),
          )}
        </group>
      );

    case "afro":
      return (
        <group>
          {capacete(0.66, Math.PI * 0.54)}
          {[[0, 2.62, -0.02], [-0.42, 2.46, -0.04], [0.42, 2.46, -0.04],
            [-0.5, 2.24, -0.16], [0.5, 2.24, -0.16], [0, 2.5, -0.32],
            [-0.26, 2.62, -0.18], [0.26, 2.62, -0.18]].map(([x, y, z], i) => (
            <mesh key={i} position={[x, y, z]} castShadow>
              <sphereGeometry args={[0.3, 16, 14]} />{mat(cor, 0.85)}
            </mesh>
          ))}
        </group>
      );

    case "coques":
      return (
        <group>
          {capacete(0.64, Math.PI * 0.56)}
          {[[-0.42, 2.52, 0.02], [0.42, 2.52, 0.02]].map(([x, y, z], i) => (
            <mesh key={i} position={[x, y, z]} castShadow>
              <sphereGeometry args={[0.24, 18, 16]} />{mat(esc)}
            </mesh>
          ))}
        </group>
      );

    case "afro_puff":
      return (
        <group>
          {capacete(0.66, Math.PI * 0.54)}
          {[[-0.5, 2.44, -0.02], [0.5, 2.44, -0.02]].map(([x, y, z], i) => (
            <mesh key={i} position={[x, y, z]} castShadow>
              <sphereGeometry args={[0.34, 18, 16]} />{mat(esc, 0.85)}
            </mesh>
          ))}
        </group>
      );

    case "moicano":
      return (
        <group>
          {[0, 1, 2, 3, 4].map((i) => (
            <mesh key={i} position={[0, 2.42 + Math.sin(i) * 0.02, 0.32 - i * 0.16]}
                  rotation={[-0.15, 0, 0]} castShadow>
              <coneGeometry args={[0.13, 0.5 - Math.abs(i - 2) * 0.06, 12]} />
              {mat(cor)}
            </mesh>
          ))}
        </group>
      );

    case "longo":
      return (
        <group>
          {capacete(0.65, Math.PI * 0.62)}
          {[-1, 1].map((s) => (
            <mesh key={s} position={[0.5 * s, 1.62, -0.12]} rotation={[0.1, 0, -0.12 * s]}
                  castShadow>
              <capsuleGeometry args={[0.17, 0.72, 8, 16]} />
              {mat(esc)}
            </mesh>
          ))}
          <mesh position={[0, 1.5, -0.28]} castShadow>
            <capsuleGeometry args={[0.28, 0.5, 8, 16]} />
            {mat(esc)}
          </mesh>
        </group>
      );

    case "liso":
    default:
      return (
        <group>
          {capacete(0.66, Math.PI * 0.58)}
          {[-1, 1].map((s) => (
            <mesh key={s} position={[0.54 * s, 1.94, 0.02]} rotation={[0, 0, 0.05 * s]}
                  castShadow>
              <capsuleGeometry args={[0.12, 0.42, 8, 14]} />
              {mat(cor)}
            </mesh>
          ))}
          {/* franja */}
          <mesh position={[0, 2.4, 0.44]} rotation={[0.5, 0, 0]} castShadow>
            <boxGeometry args={[0.7, 0.2, 0.16]} />
            {mat(cor)}
          </mesh>
        </group>
      );
  }
}
