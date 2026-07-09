import { useEffect, useState } from "react";

import { Ceu } from "../lobby/Ceu";
import { Cerimonia } from "../cerimonia/Cerimonia";
import { Cosmo } from "../cosmo/Cosmo";
import { Entrada } from "../entrada/Entrada";
import { Palco3D } from "../personagem/Palco3D";
import { Lobby } from "../lobby/Lobby";
import { SessaoProvider, useSessao } from "../estado/sessao";
import { narrar, tocar } from "../audio/audio";
import "./confirmar.css";

/** Tablet compartilhado: sessão guardada NUNCA cola direto no lobby —
 * a criança do turno seguinte não pode herdar a conta da anterior. */
function ConfirmarIdentidade() {
  const { perfil, confirmarIdentidade, negarIdentidade } = useSessao();

  useEffect(() => {
    if (perfil) {
      narrar(`Oi! É você, ${perfil.nome}? Se for você, toque no botão verde!`);
    }
  }, [perfil]);

  if (!perfil) return null;
  return (
    <div className="confirmar">
      <div className="painel confirmar-painel">
        <Palco3D avatar={perfil.avatar} altura="180px" />
        <span className="nome">É você, {perfil.nome}?</span>
        <button className="botao3d verde" autoFocus
                onClick={() => { tocar("clique"); confirmarIdentidade(); }}>
          ✅ Sou eu!
        </button>
        <button className="botao3d fantasma"
                onClick={() => { tocar("clique"); void negarIdentidade(); }}>
          ↩ Não sou eu
        </button>
      </div>
    </div>
  );
}

function Telas() {
  const { estado, perfil, entrarComSessao } = useSessao();
  // A cerimônia fica ABERTA até o próprio componente concluir — salvar o
  // nome no passo 1 não pode derrubar a criança no lobby sem escolher a cor
  const [cerimoniaAberta, setCerimoniaAberta] = useState(false);

  useEffect(() => {
    if (estado === "logado" && perfil && perfil.nome_exibicao === "") {
      setCerimoniaAberta(true);
    }
  }, [estado, perfil]);

  if (estado === "carregando") {
    return (
      <>
        <Ceu />
        <div style={{ position: "fixed", inset: 0, display: "grid", placeItems: "center" }}>
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

  if (estado === "confirmar") {
    return (
      <>
        <Ceu />
        <ConfirmarIdentidade />
      </>
    );
  }

  // Primeira vez (ainda sem nome escolhido): cerimônia de boas-vindas
  if (cerimoniaAberta) {
    return (
      <>
        <Ceu />
        <Cerimonia aoConcluir={() => setCerimoniaAberta(false)} />
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
