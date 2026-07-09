/**
 * Cerimônia da primeira vez:
 *   1. "Escolha seu personagem!" — carrossel 3D dos 6 personagens-base
 *   2. "Como você quer ser chamado?" (a criança escreve)
 *   3. Festa: "Tudo pronto!" e o lobby abre
 * Depois, tudo é personalizável no vestiário.
 */
import { useEffect, useRef, useState } from "react";

import { ApiError } from "@constela/core";
import { escolherNome, personagensBase, trocarAvatar } from "@constela/quest-core";
import type { Avatar, PersonagemBase } from "@constela/quest-core";

import { narrar, tocar } from "../audio/audio";
import { Palco3D } from "../personagem/Palco3D";
import { useSessao } from "../estado/sessao";
import "./cerimonia.css";

type Passo = "personagem" | "nome" | "pronto";

interface CerimoniaProps { aoConcluir(): void; }

export function Cerimonia({ aoConcluir }: CerimoniaProps) {
  const { perfil, atualizarPerfil } = useSessao();
  const [passo, setPasso] = useState<Passo>("personagem");
  const [bases, setBases] = useState<PersonagemBase[]>([]);
  const [i, setI] = useState(0);
  const [nome, setNome] = useState(perfil?.nome ?? "");
  const [erro, setErro] = useState("");
  const [ocupado, setOcupado] = useState(false);
  const campoNome = useRef<HTMLInputElement>(null);

  useEffect(() => {
    personagensBase().then((p) => setBases(Object.values(p))).catch(() => setBases([]));
    narrar("Oba! Escolha o seu personagem para começar a aventura!");
  }, []);

  useEffect(() => {
    if (passo === "nome") {
      campoNome.current?.focus();
      narrar("Agora, como você quer ser chamado aqui no Quest?");
    }
  }, [passo]);

  const base = bases[i];
  const trocar = (d: number) => {
    if (!bases.length) return;
    tocar("clique");
    setI((v) => (v + d + bases.length) % bases.length);
  };

  async function confirmarPersonagem() {
    if (!base) return;
    tocar("sucesso");
    const { nome: _n, ...avatar } = base;
    try { atualizarPerfil(await trocarAvatar(avatar)); } catch { /* ok */ }
    setPasso("nome");
  }

  async function confirmarNome() {
    if (ocupado || nome.trim().length < 2) return;
    setOcupado(true); setErro("");
    try {
      atualizarPerfil(await escolherNome(nome));
      tocar("fanfarra");
      narrar(`Tudo pronto, ${nome.trim()}! Sua aventura vai começar!`);
      setPasso("pronto");
      window.setTimeout(aoConcluir, 2600);
    } catch (e) {
      const m = e instanceof ApiError || e instanceof Error ? e.message : "Não deu.";
      setErro(m); tocar("erro"); narrar(m);
    } finally { setOcupado(false); }
  }

  const avatarAtual = (perfil?.avatar ?? {}) as Avatar;

  return (
    <div className="cerimonia">
      {passo === "personagem" && (
        <>
          <div className="cerimonia-carrossel">
            <button className="seta" onClick={() => trocar(-1)} aria-label="Anterior">‹</button>
            <div className="carrossel-palco">
              {base && <Palco3D avatar={base as Avatar} interativo altura="42vh" />}
            </div>
            <button className="seta" onClick={() => trocar(1)} aria-label="Próximo">›</button>
          </div>
          <div className="painel cerimonia-painel">
            <h1>🚀 Escolha seu personagem!</h1>
            <p className="nome-base">{base?.nome ?? "…"}</p>
            <div className="pontos">
              {bases.map((_, k) => <span key={k} className={`ponto${k === i ? " on" : ""}`} />)}
            </div>
            <p className="dica">Depois você personaliza tudo no vestiário</p>
            <button className="botao3d verde" disabled={!base} onClick={confirmarPersonagem}>
              ✅ É esse!
            </button>
          </div>
        </>
      )}

      {passo === "nome" && (
        <>
          <div className="cerimonia-palco">
            <Palco3D avatar={avatarAtual} interativo altura="40vh" />
          </div>
          <div className="painel cerimonia-painel">
            <h1>🌟 Como você quer ser chamado?</h1>
            <p className="dica">Pode ser seu nome ou seu apelido preferido</p>
            <input ref={campoNome} className="campo-nome" value={nome} maxLength={20}
                   autoComplete="off" spellCheck={false}
                   onChange={(e) => setNome(e.target.value.replace(/[^\p{L} ]/gu, ""))}
                   onKeyDown={(e) => e.key === "Enter" && confirmarNome()}
                   aria-label="Como você quer ser chamado" />
            {erro && <div className="entrada-erro" role="alert">{erro}</div>}
            <button className="botao3d sol" onClick={confirmarNome}
                    disabled={ocupado || nome.trim().length < 2}>🚀 Começar!</button>
          </div>
        </>
      )}

      {passo === "pronto" && (
        <div className="painel cerimonia-painel festa">
          <h1>🎉 Tudo pronto, {nome.trim()}!</h1>
          <p className="dica">Sua aventura vai começar…</p>
        </div>
      )}
    </div>
  );
}
