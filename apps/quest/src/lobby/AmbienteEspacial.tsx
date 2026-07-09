/**
 * Ambiente espacial mágico (usado no vestiário): fundo profundo com
 * nebulosas, planetas à deriva, constelações vivas, partículas luminosas e
 * um meteoro cruzando de vez em quando.
 */
import { ConstelacoesVivas } from "./ConstelacoesVivas";
import "./ambiente.css";

export function AmbienteEspacial() {
  return (
    <div className="espaco" aria-hidden>
      <div className="espaco-nebula" />
      <ConstelacoesVivas />

      {/* planetas decorativos à deriva */}
      <svg className="espaco-planeta p-a" viewBox="0 0 200 200">
        <circle cx="100" cy="100" r="70" fill="#7C6FF0" />
        <ellipse cx="100" cy="100" rx="120" ry="34" fill="none"
                 stroke="rgba(255,255,255,.4)" strokeWidth="7"
                 transform="rotate(-20 100 100)" />
        <ellipse cx="78" cy="78" rx="18" ry="12" fill="rgba(255,255,255,.18)" />
      </svg>
      <svg className="espaco-planeta p-b" viewBox="0 0 160 160">
        <circle cx="80" cy="80" r="60" fill="#FF7DB0" />
        <ellipse cx="62" cy="62" rx="16" ry="11" fill="rgba(255,255,255,.2)" />
        <ellipse cx="98" cy="96" rx="20" ry="13" fill="rgba(0,0,0,.12)" />
      </svg>
      <svg className="espaco-planeta p-c" viewBox="0 0 120 120">
        <circle cx="60" cy="60" r="44" fill="#4EA8FF" />
        <ellipse cx="48" cy="48" rx="12" ry="8" fill="rgba(255,255,255,.22)" />
      </svg>

      {/* partículas luminosas subindo */}
      <div className="espaco-poeira">
        {Array.from({ length: 22 }, (_, i) => (
          <span key={i} className="poeira" style={{
            left: `${(i * 47) % 100}%`,
            bottom: `${(i * 29) % 45}%`,
            animationDuration: `${8 + (i % 7)}s`,
            animationDelay: `${-(i % 11)}s`,
            width: `${3 + (i % 4)}px`,
            height: `${3 + (i % 4)}px`,
          }} />
        ))}
      </div>

      {/* meteoros cruzando */}
      <span className="meteoro m1" />
      <span className="meteoro m2" />
    </div>
  );
}
