/**
 * Cerimônia da primeira vez — o momento de POSSE do personagem:
 *   1. "Como você quer ser chamado?" (a criança escreve)
 *   2. "Monte seu personagem!" — escolhe cabelo e cor da camiseta, com o
 *      boneco atualizando ao vivo
 *   3. Festa: "Tudo pronto!" e o lobby abre
 */
import { useEffect, useRef, useState } from "react";

import { ApiError } from "@constela/core";
import { escolherNome, trocarAvatar } from "@constela/quest-core";
import type { Avatar } from "@constela/quest-core";

import { narrar, tocar } from "../audio/audio";
import { Boneco } from "../boneco/Boneco";
import { propsBoneco } from "../boneco/avatar";
import { CABELO_COR } from "../boneco/cabelos";
import { useSessao } from "../estado/sessao";
import "./cerimonia.css";

type Passo = "nome" | "visual" | "pronto";

const CABELOS = ["curto_castanho", "espetado_azul", "longo_loiro", "cacheado_preto",
  "chanel_rosa", "moicano_vermelho"];
const CAMISETAS = ["#FF5470", "#FFC93C", "#2EE6A8", "#4EA8FF", "#A78BFA", "#FF8E3C"];

interface CerimoniaProps { aoConcluir(): void; }

export function Cerimonia({ aoConcluir }: CerimoniaProps) {
  const { perfil, atualizarPerfil } = useSessao();
  const [passo, setPasso] = useState<Passo>("nome");
  const [nome, setNome] = useState(perfil?.nome ?? "");
  const [erro, setErro] = useState("");
  const [ocupado, setOcupado] = useState(false);
  const campoNome = useRef<HTMLInputElement>(null);

  const avatar = (perfil?.avatar ?? {}) as Avatar;

  useEffect(() => {
    if (passo === "nome") {
      campoNome.current?.focus();
      narrar("Oba, você chegou! Como você quer ser chamado aqui no Quest?");
    }
    if (passo === "visual") {
      narrar("Agora monte o seu personagem! Escolha o cabelo e a cor da camiseta.");
    }
  }, [passo]);

  async function confirmarNome() {
    if (ocupado || nome.trim().length < 2) return;
    setOcupado(true); setErro("");
    try {
      atualizarPerfil(await escolherNome(nome));
      tocar("sucesso"); setPasso("visual");
    } catch (e) {
      const m = e instanceof ApiError || e instanceof Error ? e.message : "Não deu.";
      setErro(m); tocar("erro"); narrar(m);
    } finally { setOcupado(false); }
  }

  async function escolher(slot: string, valor: string) {
    tocar("clique");
    try { atualizarPerfil(await trocarAvatar({ [slot]: valor })); } catch { /* ok */ }
  }

  function concluir() {
    tocar("fanfarra");
    narrar(`Tudo pronto, ${nome.trim() || "astronauta"}! Sua aventura vai começar!`);
    setPasso("pronto");
    window.setTimeout(aoConcluir, 2600);
  }

  return (
    <div className="cerimonia">
      <div className="cerimonia-palco">
        <Boneco altura={passo === "nome" ? "34vh" : "40vh"} {...propsBoneco(avatar)}
                vivo={passo !== "pronto"} />
      </div>

      {passo === "nome" && (
        <div className="painel cerimonia-painel">
          <h1>🌟 Como você quer ser chamado?</h1>
          <p className="dica">Pode ser seu nome ou seu apelido preferido</p>
          <input ref={campoNome} className="campo-nome" value={nome} maxLength={20}
                 autoComplete="off" spellCheck={false}
                 onChange={(e) => setNome(e.target.value.replace(/[^\p{L} ]/gu, ""))}
                 onKeyDown={(e) => e.key === "Enter" && confirmarNome()}
                 aria-label="Como você quer ser chamado" />
          {erro && <div className="entrada-erro" role="alert">{erro}</div>}
          <button className="botao3d verde" onClick={confirmarNome}
                  disabled={ocupado || nome.trim().length < 2}>
            ✅ É assim que eu quero!
          </button>
        </div>
      )}

      {passo === "visual" && (
        <div className="painel cerimonia-painel">
          <h1>🎨 Monte seu personagem!</h1>
          <p className="dica">Cabelo</p>
          <div className="cerimonia-cabelos">
            {CABELOS.map((c) => (
              <button key={c}
                      className={`mini-cabelo${(avatar.cabelo ?? "curto_castanho") === c ? " sel" : ""}`}
                      style={{ background: CABELO_COR[c] }}
                      onClick={() => escolher("cabelo", c)} aria-label="Cabelo" />
            ))}
          </div>
          <p className="dica">Camiseta</p>
          <div className="cerimonia-cores">
            {CAMISETAS.map((cor) => (
              <button key={cor}
                      className={`amostra grande${(avatar.camiseta ?? "#4EA8FF") === cor ? " escolhida" : ""}`}
                      style={{ background: cor }} onClick={() => escolher("camiseta", cor)}
                      aria-label="Cor da camiseta">
                {(avatar.camiseta ?? "#4EA8FF") === cor ? "✓" : ""}
              </button>
            ))}
          </div>
          <button className="botao3d sol" onClick={concluir}>🚀 Pronto!</button>
        </div>
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
