import { Ceu } from "../lobby/Ceu";
import { Cosmo } from "../cosmo/Cosmo";
import { Entrada } from "../entrada/Entrada";
import { Lobby } from "../lobby/Lobby";
import { SessaoProvider, useSessao } from "../estado/sessao";

function Telas() {
  const { estado, entrarComSessao } = useSessao();

  if (estado === "carregando") {
    return (
      <>
        <Ceu />
        <div style={{
          position: "fixed", inset: 0, display: "grid",
          placeItems: "center",
        }}>
          <Cosmo altura="40vh" vivo={false} />
        </div>
      </>
    );
  }

  if (estado === "deslogado") {
    return (
      <>
        <Ceu />
        <Entrada aoEntrar={(sessao) => void entrarComSessao(sessao)} />
      </>
    );
  }

  return <Lobby />;
}

export function App() {
  return (
    <SessaoProvider>
      <Telas />
    </SessaoProvider>
  );
}
