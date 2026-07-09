/**
 * Vestiário mágico — ambiente espacial, o boneco humanoide numa plataforma
 * flutuante, e o armário com as categorias do mockup: Pele, Cabelo,
 * Camiseta, Calça, Tênis, Acessórios, Pets e Itens Especiais. Itens
 * especiais têm invocação (o Skate Voador tem a sequência cinematográfica).
 */
import { useEffect, useState } from "react";

import { ApiError } from "@constela/core";
import { escolherNome, trocarAvatar } from "@constela/quest-core";
import type { Avatar } from "@constela/quest-core";

import { Boneco } from "../boneco/Boneco";
import { propsBoneco } from "../boneco/avatar";
import { CABELO_COR } from "../boneco/cabelos";
import { Skate } from "../cosmo/Skate";
import { InvocacaoSkate } from "../cosmo/InvocacaoSkate";
import { narrar, tocar } from "../audio/audio";
import { useSessao } from "../estado/sessao";
import { AmbienteEspacial } from "../lobby/AmbienteEspacial";
import "./vestiario.css";

type Item = { slot: string; valor: string };

interface Aba {
  id: string;
  nome: string;
  icone: string;
  cores?: string[];       // categoria de cor (renderiza amostra)
  slot?: string;          // categoria de preset de um slot
  valores?: string[];
  itens?: Item[];         // categoria multi-slot (itens especiais)
}

const PELES = ["#F6C8A0", "#E8B07E", "#C98A56", "#9C6B3F", "#6E4A2C"];
const CAMISETAS = ["#FF5470", "#FFC93C", "#2EE6A8", "#4EA8FF", "#A78BFA", "#FF8E3C", "#231D4E"];
const CALCAS = ["#3A2E66", "#4EA8FF", "#2EC77A", "#E8384F", "#5A5480"];
const TENIS = ["#FF5470", "#4EA8FF", "#2EE6A8", "#FFC93C", "#F2EFFF"];
const CABELOS = ["curto_castanho", "espetado_azul", "espetado_preto", "longo_loiro",
  "cacheado_preto", "chanel_rosa", "moicano_vermelho", "careca"];
const CHAPEUS = ["nenhum", "oculos", "bone", "coroa", "fone"];
const PETS = ["nenhum", "gatinho", "dino", "estrelinha"];

const ABAS: Aba[] = [
  { id: "pele", nome: "Pele", icone: "🖐️", slot: "pele", cores: PELES },
  { id: "cabelo", nome: "Cabelo", icone: "💇", slot: "cabelo", valores: CABELOS },
  { id: "camiseta", nome: "Camiseta", icone: "👕", slot: "camiseta", cores: CAMISETAS },
  { id: "calca", nome: "Calça", icone: "👖", slot: "calca", cores: CALCAS },
  { id: "tenis", nome: "Tênis", icone: "👟", slot: "tenis", cores: TENIS },
  { id: "acessorio", nome: "Acessórios", icone: "🕶️", slot: "chapeu", valores: CHAPEUS },
  { id: "pet", nome: "Pets", icone: "🐾", slot: "pet", valores: PETS },
  { id: "especiais", nome: "Itens Especiais", icone: "✨", itens: [
    { slot: "costas", valor: "mochila" }, { slot: "costas", valor: "asas" },
    { slot: "mao", valor: "varinha" }, { slot: "veiculo", valor: "skate" },
  ] },
];

const ROTULOS: Record<string, string> = {
  curto_castanho: "Curtinho", espetado_azul: "Espetado", espetado_preto: "Punk",
  longo_loiro: "Longo", cacheado_preto: "Cacheado", chanel_rosa: "Chanel",
  moicano_vermelho: "Moicano", careca: "Careca",
  nenhum: "Nenhum", oculos: "Óculos", bone: "Boné", coroa: "Coroa", fone: "Fone",
  gatinho: "Gatinho", dino: "Dino", estrelinha: "Estrelinha",
  mochila: "Mochila", asas: "Asas de Luz", varinha: "Varinha", skate: "Skate Voador",
};

const PADRAO: Record<string, string> = {
  pele: "#F6C8A0", cabelo: "curto_castanho", camiseta: "#4EA8FF",
  calca: "#3A2E66", tenis: "#FF5470", chapeu: "nenhum",
  costas: "nenhum", mao: "nenhum", pet: "nenhum", veiculo: "nenhum",
};

export function Vestiario() {
  const { perfil, atualizarPerfil } = useSessao();
  const [abaId, setAbaId] = useState("cabelo");
  const [apelido, setApelido] = useState(perfil?.nome ?? "");
  const [salvando, setSalvando] = useState(false);
  const [erro, setErro] = useState("");
  const [invocandoSkate, setInvocandoSkate] = useState(false);
  const [pulando, setPulando] = useState(false);
  const [materializando, setMaterializando] = useState(false);

  useEffect(() => { setApelido(perfil?.nome ?? ""); }, [perfil?.nome]);

  if (!perfil) return null;
  const avatar = perfil.avatar as Avatar;
  const aba = ABAS.find((a) => a.id === abaId)!;
  const eq = (slot: string) => (avatar[slot] as string) ?? PADRAO[slot];

  async function definir(slot: string, valor: string) {
    tocar("sucesso");
    try { atualizarPerfil(await trocarAvatar({ [slot]: valor })); }
    catch { return; }
    if (slot === "veiculo" && valor === "skate") {
      setInvocandoSkate(true); narrar("Skate voador!");
    } else if (valor !== "nenhum" && (slot === "costas" || slot === "mao")) {
      setMaterializando(true);
      window.setTimeout(() => setMaterializando(false), 800);
    }
  }

  function equipar(slot: string, valor: string) {
    if (eq(slot) === valor) return;
    void definir(slot, valor);
  }

  // Itens especiais: clicar alterna equipar/desequipar
  function alternarEspecial(slot: string, valor: string) {
    void definir(slot, eq(slot) === valor ? "nenhum" : valor);
  }

  async function salvarApelido() {
    const novo = apelido.trim();
    if (salvando || novo === perfil?.nome) return;
    setSalvando(true); setErro("");
    try {
      atualizarPerfil(await escolherNome(novo));
      tocar("sucesso"); narrar(`Agora você é ${novo}!`);
    } catch (e) {
      setErro(e instanceof ApiError || e instanceof Error ? e.message : "Não deu.");
      tocar("erro");
    } finally { setSalvando(false); }
  }

  const mostrarSkate = avatar.veiculo === "skate" && !invocandoSkate;
  const base = propsBoneco(avatar);

  function miniBoneco(over: Partial<Avatar>) {
    return <span className="item-mini"><Boneco altura="76px" vivo={false} {...base} {...over} /></span>;
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
          <div className={`boneco-caixa${materializando ? " materializando" : ""}${pulando ? " pulando" : ""}${mostrarSkate ? " montado" : ""}`}>
            <Boneco altura="min(50vh, 440px)" {...base} fisica />
            {mostrarSkate && <div className="vitrine-skate"><Skate /></div>}
          </div>
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
                     onKeyDown={(e) => e.key === "Enter" && salvarApelido()}
                     aria-label="Meu apelido" />
              <button className="botao3d sol" onClick={salvarApelido}
                      disabled={salvando || apelido.trim().length < 2 || apelido.trim() === perfil.nome}>
                Salvar
              </button>
            </div>
            {erro && <em className="apelido-erro">{erro}</em>}
          </label>

          <h2 className="itens-titulo">{aba.nome}</h2>
          <div className="itens-grade">
            {aba.cores && aba.cores.map((cor) => (
              <button key={cor} className={`item${eq(aba.slot!) === cor ? " equipado" : ""}`}
                      onClick={() => equipar(aba.slot!, cor)} aria-label="Cor">
                <span className="item-cor" style={{ background: cor }} />
                {eq(aba.slot!) === cor && <span className="selo">✓</span>}
              </button>
            ))}

            {aba.valores && aba.valores.map((valor) => {
              const sel = eq(aba.slot!) === valor;
              return (
                <button key={valor} className={`item${sel ? " equipado" : ""}`}
                        onClick={() => equipar(aba.slot!, valor)}
                        aria-label={ROTULOS[valor] ?? valor}>
                  {valor === "nenhum" ? <span className="item-emoji">🚫</span>
                    : aba.slot === "cabelo"
                      ? <span className="item-swatch" style={{ background: CABELO_COR[valor] }}>{ROTULOS[valor]}</span>
                      : miniBoneco({ [aba.slot!]: valor })}
                  {aba.slot !== "cabelo" && <b>{ROTULOS[valor] ?? valor}</b>}
                  {sel && <span className="selo">✓</span>}
                </button>
              );
            })}

            {aba.itens && aba.itens.map((it) => {
              const sel = eq(it.slot) === it.valor;
              return (
                <button key={it.slot + it.valor} className={`item${sel ? " equipado" : ""}`}
                        onClick={() => alternarEspecial(it.slot, it.valor)}
                        aria-label={ROTULOS[it.valor] ?? it.valor}>
                  {it.slot === "veiculo" ? <span className="item-mini"><Skate /></span>
                    : miniBoneco({ [it.slot]: it.valor })}
                  <b>{ROTULOS[it.valor] ?? it.valor}</b>
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
