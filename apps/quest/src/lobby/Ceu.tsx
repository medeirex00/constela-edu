/** Céu vivo de fundo: gradiente, constelação e neblina (protótipo v7). */
export function Ceu() {
  return (
    <>
      <div className="ceu" />
      <svg className="constelacao" width="100%" height="100%"
           preserveAspectRatio="none" aria-hidden>
        <line x1="8%" y1="16%" x2="16%" y2="26%" />
        <line x1="16%" y1="26%" x2="27%" y2="19%" />
        <line x1="27%" y1="19%" x2="34%" y2="30%" />
        <line x1="70%" y1="14%" x2="79%" y2="22%" />
        <line x1="79%" y1="22%" x2="88%" y2="15%" />
        <line x1="79%" y1="22%" x2="84%" y2="34%" />
        <circle cx="8%" cy="16%" r="3.5" />
        <circle cx="16%" cy="26%" r="5" />
        <circle cx="27%" cy="19%" r="3.5" />
        <circle cx="34%" cy="30%" r="4.5" />
        <circle cx="70%" cy="14%" r="4" />
        <circle cx="79%" cy="22%" r="5.5" />
        <circle cx="88%" cy="15%" r="3.5" />
        <circle cx="84%" cy="34%" r="4" />
        <circle cx="50%" cy="10%" r="3" />
        <circle cx="60%" cy="40%" r="3" />
        <circle cx="12%" cy="44%" r="3" />
        <circle cx="93%" cy="46%" r="3.5" />
      </svg>
      <div className="neblina" />
    </>
  );
}
