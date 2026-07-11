/**
 * Vestiário mágico — ambiente espacial, o personagem 3D girando devagar numa
 * plataforma flutuante, e o armário completo. Cada item atualiza o
 * personagem 3D na hora. Itens especiais têm invocação (o Skate tem a
 * sequência cinematográfica). Os thumbnails são chips 2D (o preview 3D é o
 * herói — só um contexto WebGL por tela).
 */
import { useEffect, useState } from "react";

import { ApiError } from "@constela/core";
import { escolherNome, trocarAvatar } from "@constela/quest-core";
import type { Avatar } from "@constela/quest-core";

import { InvocacaoSkate } from "../cosmo/InvocacaoSkate";
import { Palco3D } from "../personagem/Palco3D";
import { narrar, tocar } from "../audio/audio";
import { useSessao } from "../estado/sessao";
import { AmbienteEspacial } from "../lobby/AmbienteEspacial";
import "./vestiario.css";

const PELES = ["#F6C8A0", "#E8B07E", "#C98A56", "#9C6B3F", "#6E4A2C", "#4A3020"];
const COR_CABELO = ["#2B2B2B", "#6B3F1D", "#C9302C", "#F4C430", "#3D7BFF", "#E24AA0", "#7A3DF0"];
const CAMISETAS = ["#FF5470", "#FFC93C", "#2EE6A8", "#4EA8FF", "#A78BFA", "#FF8E3C", "#231D4E"];
const CALCAS = ["#3A2E66", "#4EA8FF", "#2EC77A", "#E8384F", "#5A5480", "#F2EFFF"];
const TENIS = ["#FF5470", "#4EA8FF", "#2EE6A8", "#FFC93C", "#F2EFFF", "#231D4E"];
const CABELOS = ["espetado", "longo", "afro", "coques", "afro_puff", "liso", "moicano", "careca"];
const TOPS = ["camiseta", "moletom", "jaqueta", "jardineira"];
const BAIXOS = ["calca", "shorts"];
const CHAPEUS = ["nenhum", "oculos", "bone", "coroa", "fone", "catfone", "capacete"];
const PETS = ["nenhum", "gatinho", "dino", "estrelinha", "robo"];

interface Aba { id: string; nome: string; icone: string;
  slot?: string; valores?: string[]; corSlot?: string; cores?: string[];
  itens?: { slot: string; valor: string }[]; }

const ABAS: Aba[] = [
  { id: "pele", nome: "Pele", icone: "🖐️", corSlot: "pele", cores: PELES },
  { id: "cabelo", nome: "Cabelo", icone: "💇", slot: "cabelo", valores: CABELOS },
  { id: "corcabelo", nome: "Cor do Cabelo", icone: "🎨", corSlot: "cor_cabelo", cores: COR_CABELO },
  { id: "blusa", nome: "Blusa", icone: "👕", slot: "top", valores: TOPS, corSlot: "camiseta", cores: CAMISETAS },
  { id: "calca", nome: "Calça", icone: "👖", slot: "baixo", valores: BAIXOS, corSlot: "calca", cores: CALCAS },
  { id: "tenis", nome: "Tênis", icone: "👟", corSlot: "tenis", cores: TENIS },
  { id: "acessorio", nome: "Acessórios", icone: "🕶️", slot: "chapeu", valores: CHAPEUS },
  { id: "pet", nome: "Pets", icone: "🐾", slot: "pet", valores: PETS },
  { id: "especiais", nome: "Itens Especiais", icone: "✨", itens: [
    { slot: "veiculo", valor: "skate" }, { slot: "costas", valor: "asas" },
    { slot: "costas", valor: "mochila" }, { slot: "costas", valor: "jetpack" },
    { slot: "aura", valor: "estelar" }, { slot: "aura", valor: "halo" },
    { slot: "aura", valor: "rastro" }, { slot: "mao", valor: "varinha" },
  ] },
];

const ROTULOS: Record<string, string> = {
  espetado: "Espetado", longo: "Longo", afro: "Black Power", coques: "Coques",
  afro_puff: "Puffs", liso: "Liso", moicano: "Moicano", careca: "Careca",
  camiseta: "Camiseta", moletom: "Moletom", jaqueta: "Jaqueta", jardineira: "Jardineira",
  calca: "Calça", shorts: "Shorts", nenhum: "Nenhum", oculos: "Óculos", bone: "Boné",
  coroa: "Coroa", fone: "Fone", catfone: "Fone Gato", capacete: "Capacete",
  gatinho: "Gatinho", dino: "Dino", estrelinha: "Estrelinha", robo: "Robô",
  mochila: "Mochila", asas: "Asas de Luz", jetpack: "Jetpack", varinha: "Varinha",
  estelar: "Aura Estelar", halo: "Halo", rastro: "Rastro", skate: "Skate Voador",
};
const ICONE: Record<string, string> = {
  nenhum: "🚫", oculos: "🕶️", bone: "🧢", coroa: "👑", fone: "🎧", catfone: "🐱",
  capacete: "👨‍🚀", gatinho: "🐱", dino: "🦖", estrelinha: "⭐", robo: "🤖",
  skate: "🛹", asas: "🪽", mochila: "🎒", jetpack: "🚀", estelar: "✨", halo: "😇",
  rastro: "🌠", varinha: "🪄",
};
const PADRAO: Record<string, string> = {
  pele: "#F6C8A0", cabelo: "espetado", cor_cabelo: "#6B3F1D", top: "camiseta",
  camiseta: "#4EA8FF", baixo: "calca", calca: "#3A2E66", tenis: "#FF5470",
  chapeu: "nenhum", costas: "nenhum", aura: "nenhum", mao: "nenhum", pet: "nenhum", veiculo: "nenhum",
};

export function Vestiario() {
  const { perfil, atualizarPerfil } = useSessao();
  const [abaId, setAbaId] = useState("blusa");
  const [apelido, setApelido] = useState(perfil?.nome ?? "");
  const [salvando, setSalvando] = useState(false);
  const [erro, setErro] = useState("");
  const [invocandoSkate, setInvocandoSkate] = useState(false);

  useEffect(() => { setApelido(perfil?.nome ?? ""); }, [perfil?.nome]);

  if (!perfil) return null;
  const avatar = perfil.avatar as Avatar;
  const aba = ABAS.find((a) => a.id === abaId)!;
  const eq = (slot: string) => (avatar[slot] as string) ?? PADRAO[slot];

  async function definir(slot: string, valor: string) {
    setErro("");
    try {
      atualizarPerfil(await trocarAvatar({ [slot]: valor }));
    } catch (e) {
      // Não engolir a falha: mostrar erro e NÃO tocar "sucesso" (antes o chime
      // de sucesso soava mesmo quando a troca falhava — falso-positivo). Falha
      // de rede (status 0) usa a voz da criança, não o "Failed to fetch" cru.
      setErro(e instanceof ApiError && e.status !== 0 ? e.message
        : "Não consegui trocar agora. Tente de novo!");
      tocar("erro");
      return;
    }
    tocar("sucesso");
    if (slot === "veiculo" && valor === "skate") { setInvocandoSkate(true); narrar("Skate voador!"); }
  }
  function equipar(slot: string, valor: string) { if (eq(slot) !== valor) void definir(slot, valor); }
  function alternar(slot: string, valor: string) { void definir(slot, eq(slot) === valor ? "nenhum" : valor); }

  async function salvarApelido() {
    const novo = apelido.trim();
    if (salvando || novo === perfil?.nome) return;
    setSalvando(true); setErro("");
    try { atualizarPerfil(await escolherNome(novo)); tocar("sucesso"); narrar(`Agora você é ${novo}!`); }
    catch (e) {
      setErro(e instanceof ApiError && e.status !== 0 ? e.message
        : "Não consegui salvar agora. Tenta de novo?");
      tocar("erro");
    }
    finally { setSalvando(false); }
  }

  function visualEstilo(slot: string, valor: string) {
    if (valor === "nenhum") return <span className="item-emoji">🚫</span>;
    if (slot === "cabelo") return <span className="chip-dot" style={{ background: eq("cor_cabelo") }} />;
    if (slot === "top") return <span className="chip-dot" style={{ background: eq("camiseta") }} />;
    if (slot === "baixo") return <span className="chip-dot" style={{ background: eq("calca") }} />;
    return <span className="item-emoji">{ICONE[valor] ?? "✨"}</span>;
  }

  return (
    <section className="view vestiario">
      <AmbienteEspacial />
      <div className="vestiario-grade">
        <nav className="categorias" aria-label="Categorias do vestiário">
          {ABAS.map((a) => (
            <button key={a.id} className={`categoria${abaId === a.id ? " ativa" : ""}`}
                    onClick={() => { tocar("clique"); setAbaId(a.id); }}>
              <span className="cat-icone" aria-hidden>{a.icone}</span>
              <span className="cat-nome">{a.nome}</span>
            </button>
          ))}
        </nav>

        <div className="vitrine">
          <Palco3D avatar={avatar} girar interativo altura="min(56vh, 480px)" className="vitrine-3d" />
          <div className="plataforma">
            <div className="plataforma-anel" />
            <div className="plataforma-luz" />
          </div>
        </div>

        <div className="itens-painel">
          <label className="apelido-editor">
            <span>Meu apelido</span>
            <div className="apelido-linha">
              <input value={apelido} maxLength={20}
                     onChange={(e) => setApelido(e.target.value.replace(/[^\p{L} ]/gu, ""))}
                     onKeyDown={(e) => e.key === "Enter" && salvarApelido()} aria-label="Meu apelido" />
              <button className="botao3d sol" onClick={salvarApelido}
                      disabled={salvando || apelido.trim().length < 2 || apelido.trim() === perfil.nome}>Salvar</button>
            </div>
            {erro && <em className="apelido-erro">{erro}</em>}
          </label>

          <h2 className="itens-titulo">{aba.nome}</h2>

          {aba.cores && aba.corSlot && aba.valores && (
            <div className="cores-linha">
              {aba.cores.map((cor) => (
                <button key={cor} className={`cor-bola${eq(aba.corSlot!) === cor ? " sel" : ""}`}
                        style={{ background: cor }} onClick={() => equipar(aba.corSlot!, cor)} aria-label="Cor" />
              ))}
            </div>
          )}

          <div className="itens-grade">
            {aba.cores && !aba.valores && aba.corSlot && aba.cores.map((cor) => (
              <button key={cor} className={`item${eq(aba.corSlot!) === cor ? " equipado" : ""}`}
                      onClick={() => equipar(aba.corSlot!, cor)} aria-label="Cor">
                <span className="item-cor" style={{ background: cor }} />
                {eq(aba.corSlot!) === cor && <span className="selo">✓</span>}
              </button>
            ))}

            {aba.valores && aba.slot && aba.valores.map((valor) => {
              const sel = eq(aba.slot!) === valor;
              return (
                <button key={valor} className={`item${sel ? " equipado" : ""}`}
                        onClick={() => equipar(aba.slot!, valor)} aria-label={ROTULOS[valor] ?? valor}>
                  {visualEstilo(aba.slot!, valor)}
                  <b>{ROTULOS[valor] ?? valor}</b>
                  {sel && <span className="selo">✓</span>}
                </button>
              );
            })}

            {aba.itens && aba.itens.map((it) => {
              const sel = eq(it.slot) === it.valor;
              return (
                <button key={it.slot + it.valor} className={`item${sel ? " equipado" : ""}`}
                        onClick={() => alternar(it.slot, it.valor)} aria-label={ROTULOS[it.valor] ?? it.valor}>
                  <span className="item-emoji">{ICONE[it.valor] ?? "✨"}</span>
                  <b>{ROTULOS[it.valor] ?? it.valor}</b>
                  {sel && <span className="selo">✓</span>}
                </button>
              );
            })}
          </div>
        </div>
      </div>

      {invocandoSkate && (
        <InvocacaoSkate aoPular={() => tocar("fanfarra")} aoTerminar={() => setInvocandoSkate(false)} />
      )}
    </section>
  );
}
