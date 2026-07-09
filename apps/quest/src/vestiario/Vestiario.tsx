/**
 * Vestiário mágico — ambiente espacial (nebulosas, planetas, constelações,
 * partículas, meteoros), o astronauta no centro sobre uma plataforma
 * flutuante, e um armário de categorias grandes. Itens especiais têm
 * animação de invocação (o Skate Voador tem a sequência cinematográfica).
 */
import { useEffect, useState } from "react";

import { ApiError } from "@constela/core";
import { escolherNome, trocarAvatar } from "@constela/quest-core";
import type { Avatar } from "@constela/quest-core";

import { Cosmo } from "../cosmo/Cosmo";
import { InvocacaoSkate } from "../cosmo/InvocacaoSkate";
import { Skate } from "../cosmo/Skate";
import { narrar, tocar } from "../audio/audio";
import { useSessao } from "../estado/sessao";
import { AmbienteEspacial } from "../lobby/AmbienteEspacial";
import "./vestiario.css";

type Slot = "cor" | "rosto" | "chapeu" | "costas" | "mao" | "pet" | "veiculo";

const ABAS: { slot: Slot; nome: string; icone: string }[] = [
  { slot: "cor", nome: "Cores", icone: "🎨" },
  { slot: "rosto", nome: "Rostos", icone: "😀" },
  { slot: "chapeu", nome: "Chapéus", icone: "🎩" },
  { slot: "costas", nome: "Mochila & Asas", icone: "🎒" },
  { slot: "mao", nome: "Acessórios", icone: "✨" },
  { slot: "pet", nome: "Pets", icone: "🐾" },
  { slot: "veiculo", nome: "Itens Especiais", icone: "🛹" },
];

const OPCOES: Record<Slot, string[]> = {
  cor: ["#FF4D9D", "#FFC93C", "#2EE6A8", "#4EA8FF", "#A78BFA", "#FF8E3C"],
  rosto: ["sorriso", "sorrisao", "fofo", "surpreso", "oculos", "heroi"],
  chapeu: ["nenhum", "coroa", "cartola", "laco", "fone", "cowboy"],
  costas: ["nenhum", "mochila", "asas"],
  mao: ["nenhum", "varinha"],
  pet: ["nenhum", "gatinho", "dino", "estrelinha"],
  veiculo: ["nenhum", "skate"],
};

const ROTULOS: Record<string, string> = {
  sorriso: "Sorriso", sorrisao: "Risada", fofo: "Fofo", surpreso: "Uau!",
  oculos: "Óculos", heroi: "Herói", nenhum: "Nenhum", coroa: "Coroa",
  cartola: "Cartola", laco: "Laço", fone: "Fone", cowboy: "Cowboy",
  mochila: "Mochila", asas: "Asas de Luz", varinha: "Varinha Estelar",
  gatinho: "Gatinho", dino: "Dino", estrelinha: "Estrelinha",
  skate: "Skate Voador",
};

const PADRAO: Record<Slot, string> = {
  cor: "#FF4D9D", rosto: "sorriso", chapeu: "nenhum", costas: "nenhum",
  mao: "nenhum", pet: "nenhum", veiculo: "nenhum",
};

export function Vestiario() {
  const { perfil, atualizarPerfil } = useSessao();
  const [aba, setAba] = useState<Slot>("cor");
  const [apelido, setApelido] = useState(perfil?.nome ?? "");
  const [salvando, setSalvando] = useState(false);
  const [erro, setErro] = useState("");
  const [invocandoSkate, setInvocandoSkate] = useState(false);
  const [pulando, setPulando] = useState(false);
  const [materializando, setMaterializando] = useState(false);

  useEffect(() => { setApelido(perfil?.nome ?? ""); }, [perfil?.nome]);

  if (!perfil) return null;
  const avatar = perfil.avatar as Avatar;
  const equipado = (slot: Slot) => (avatar[slot] as string) ?? PADRAO[slot];

  async function equipar(slot: Slot, valor: string) {
    if (equipado(slot) === valor) return;
    tocar("sucesso");
    try {
      atualizarPerfil(await trocarAvatar({ [slot]: valor }));
    } catch {
      return;
    }
    // Itens especiais ganham invocação
    if (slot === "veiculo" && valor === "skate") {
      setInvocandoSkate(true);
      narrar("Skate voador!");
    } else if (valor !== "nenhum" && (slot === "costas" || slot === "mao")) {
      setMaterializando(true);
      window.setTimeout(() => setMaterializando(false), 800);
    }
  }

  async function salvarApelido() {
    const novo = apelido.trim();
    if (salvando || novo === perfil?.nome) return;
    setSalvando(true); setErro("");
    try {
      atualizarPerfil(await escolherNome(novo));
      tocar("sucesso");
      narrar(`Agora você é ${novo}!`);
    } catch (e) {
      setErro(e instanceof ApiError || e instanceof Error ? e.message : "Não deu.");
      tocar("erro");
    } finally { setSalvando(false); }
  }

  const mostrarSkate = avatar.veiculo === "skate" && !invocandoSkate;

  return (
    <section className="view vestiario">
      <AmbienteEspacial />

      <div className="vestiario-grade">
        {/* Categorias (esquerda) */}
        <nav className="categorias" aria-label="Categorias do vestiário">
          {ABAS.map((a) => (
            <button key={a.slot}
                    className={`categoria${aba === a.slot ? " ativa" : ""}`}
                    onClick={() => { tocar("clique"); setAba(a.slot); }}>
              <span className="cat-icone" aria-hidden>{a.icone}</span>
              <span className="cat-nome">{a.nome}</span>
            </button>
          ))}
        </nav>

        {/* Personagem na plataforma (centro) */}
        <div className="vitrine">
          <div className={`boneco${materializando ? " materializando" : ""}${pulando ? " pulando" : ""}${mostrarSkate ? " montado" : ""}`}>
            <Cosmo altura="min(50vh, 440px)" cor={avatar.cor} rosto={avatar.rosto}
                   chapeu={avatar.chapeu} costas={avatar.costas} mao={avatar.mao}
                   pet={avatar.pet} fisica />
            {mostrarSkate && <div className="vitrine-skate"><Skate /></div>}
          </div>
          <div className="plataforma">
            <div className="plataforma-anel" />
            <div className="plataforma-luz" />
          </div>
        </div>

        {/* Itens (direita) */}
        <div className="itens-painel">
          <label className="apelido-editor">
            <span>Meu apelido</span>
            <div className="apelido-linha">
              <input value={apelido} maxLength={20}
                     onChange={(e) => setApelido(e.target.value.replace(/[^\p{L} ]/gu, ""))}
                     onKeyDown={(e) => e.key === "Enter" && salvarApelido()}
                     aria-label="Meu apelido" />
              <button className="botao3d sol" onClick={salvarApelido}
                      disabled={salvando || apelido.trim().length < 2 || apelido.trim() === perfil.nome}>
                Salvar
              </button>
            </div>
            {erro && <em className="apelido-erro">{erro}</em>}
          </label>

          <h2 className="itens-titulo">{ABAS.find((a) => a.slot === aba)?.nome}</h2>
          <div className="itens-grade">
            {OPCOES[aba].map((valor) => {
              const sel = equipado(aba) === valor;
              return (
                <button key={valor} className={`item${sel ? " equipado" : ""}`}
                        onClick={() => equipar(aba, valor)}
                        aria-label={aba === "cor" ? "Cor" : ROTULOS[valor] ?? valor}>
                  {aba === "cor" ? (
                    <span className="item-cor" style={{ background: valor }} />
                  ) : aba === "veiculo" && valor === "skate" ? (
                    <span className="item-mini"><Skate /></span>
                  ) : valor === "nenhum" ? (
                    <span className="item-emoji">🚫</span>
                  ) : (
                    <span className="item-mini">
                      <Cosmo altura="72px" vivo={false} cor={avatar.cor}
                             rosto={aba === "rosto" ? valor : avatar.rosto}
                             chapeu={aba === "chapeu" ? valor : avatar.chapeu}
                             costas={aba === "costas" ? valor : avatar.costas}
                             mao={aba === "mao" ? valor : avatar.mao}
                             pet={aba === "pet" ? valor : avatar.pet} />
                    </span>
                  )}
                  {aba !== "cor" && <b>{ROTULOS[valor] ?? valor}</b>}
                  {sel && <span className="selo">✓</span>}
                </button>
              );
            })}
          </div>
        </div>
      </div>

      {invocandoSkate && (
        <InvocacaoSkate
          aoPular={() => { setPulando(true); tocar("fanfarra");
            window.setTimeout(() => setPulando(false), 800); }}
          aoTerminar={() => setInvocandoSkate(false)}
        />
      )}
    </section>
  );
}
