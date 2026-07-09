/**
 * Vestiário estilo Roblox: um Cosmo grande ao vivo e um armário com abas
 * (Cores, Rostos, Chapéus, Veículos). Cada toque equipa o item na hora e
 * persiste no perfil. Aqui também se troca o apelido.
 */
import { useEffect, useState } from "react";

import { ApiError } from "@constela/core";
import { escolherNome, trocarAvatar } from "@constela/quest-core";
import type { Avatar } from "@constela/quest-core";

import { narrar, tocar } from "../audio/audio";
import { Cosmo } from "../cosmo/Cosmo";
import { Skate } from "../cosmo/Skate";
import { useSessao } from "../estado/sessao";
import "./vestiario.css";

type Slot = "cor" | "rosto" | "chapeu" | "veiculo";

const ABAS: { slot: Slot; nome: string; icone: string }[] = [
  { slot: "cor", nome: "Cores", icone: "🎨" },
  { slot: "rosto", nome: "Rostos", icone: "😀" },
  { slot: "chapeu", nome: "Chapéus", icone: "🎩" },
  { slot: "veiculo", nome: "Veículos", icone: "🛹" },
];

const OPCOES: Record<Slot, string[]> = {
  cor: ["#FF4D9D", "#FFC93C", "#2EE6A8", "#4EA8FF", "#A78BFA", "#FF8E3C"],
  rosto: ["sorriso", "sorrisao", "fofo", "surpreso", "oculos", "heroi"],
  chapeu: ["nenhum", "coroa", "cartola", "laco", "fone", "cowboy"],
  veiculo: ["nenhum", "skate"],
};

const ROTULOS: Record<string, string> = {
  sorriso: "Sorriso", sorrisao: "Risada", fofo: "Fofo",
  surpreso: "Uau!", oculos: "Óculos", heroi: "Herói",
  nenhum: "Nenhum", coroa: "Coroa", cartola: "Cartola",
  laco: "Laço", fone: "Fone", cowboy: "Cowboy", skate: "Skate Voador",
};

export function Vestiario() {
  const { perfil, atualizarPerfil } = useSessao();
  const [aba, setAba] = useState<Slot>("cor");
  const [apelido, setApelido] = useState(perfil?.nome ?? "");
  const [salvandoApelido, setSalvandoApelido] = useState(false);
  const [erroApelido, setErroApelido] = useState("");

  useEffect(() => { setApelido(perfil?.nome ?? ""); }, [perfil?.nome]);

  if (!perfil) return null;
  const avatar = perfil.avatar as Avatar;

  async function equipar(slot: Slot, valor: string) {
    if ((avatar[slot] ?? (slot === "cor" ? "#FF4D9D" : "nenhum")) === valor) return;
    tocar("sucesso");
    try {
      atualizarPerfil(await trocarAvatar({ [slot]: valor }));
    } catch {
      /* mantém o anterior — sem travar a brincadeira */
    }
  }

  async function salvarApelido() {
    const novo = apelido.trim();
    if (salvandoApelido || novo === perfil?.nome) return;
    setSalvandoApelido(true);
    setErroApelido("");
    try {
      atualizarPerfil(await escolherNome(novo));
      tocar("sucesso");
      narrar(`Agora você é ${novo}!`);
    } catch (excecao) {
      setErroApelido(excecao instanceof ApiError || excecao instanceof Error
        ? excecao.message : "Não consegui trocar agora.");
      tocar("erro");
    } finally {
      setSalvandoApelido(false);
    }
  }

  const equipado = (slot: Slot) =>
    (avatar[slot] as string) ?? (slot === "cor" ? "#FF4D9D" : "nenhum");

  return (
    <section className="view vestiario">
      <div className="palco-vestiario">
        <div className="cosmo-vitrine">
          <Cosmo
            altura="min(46vh, 420px)"
            cor={avatar.cor}
            rosto={avatar.rosto}
            chapeu={avatar.chapeu}
            fisica
          />
          {avatar.veiculo === "skate" && (
            <div className="skate-vitrine"><Skate /></div>
          )}
        </div>

        <div className="armario">
          <label className="apelido-editor">
            <span>Meu apelido</span>
            <div className="apelido-linha">
              <input
                value={apelido}
                maxLength={20}
                onChange={(e) => setApelido(e.target.value.replace(/[^\p{L} ]/gu, ""))}
                onKeyDown={(e) => e.key === "Enter" && salvarApelido()}
                aria-label="Meu apelido"
              />
              <button
                className="botao3d sol"
                onClick={salvarApelido}
                disabled={salvandoApelido || apelido.trim().length < 2
                  || apelido.trim() === perfil.nome}
              >
                Salvar
              </button>
            </div>
            {erroApelido && <em className="apelido-erro">{erroApelido}</em>}
          </label>

          <div className="armario-abas" role="tablist">
            {ABAS.map((a) => (
              <button
                key={a.slot}
                className={`armario-aba${aba === a.slot ? " ativa" : ""}`}
                onClick={() => { tocar("clique"); setAba(a.slot); }}
                role="tab"
                aria-selected={aba === a.slot}
              >
                <span aria-hidden>{a.icone}</span> {a.nome}
              </button>
            ))}
          </div>

          <div className="armario-grade">
            {OPCOES[aba].map((valor) => {
              const sel = equipado(aba) === valor;
              return (
                <button
                  key={valor}
                  className={`item${sel ? " equipado" : ""}`}
                  onClick={() => equipar(aba, valor)}
                  aria-label={aba === "cor" ? "Cor" : ROTULOS[valor] ?? valor}
                >
                  {aba === "cor" ? (
                    <span className="item-cor" style={{ background: valor }} />
                  ) : aba === "veiculo" && valor === "skate" ? (
                    <span className="item-mini"><Skate /></span>
                  ) : aba === "veiculo" ? (
                    <span className="item-emoji">🚶</span>
                  ) : (
                    <span className="item-mini">
                      <Cosmo altura="70px" vivo={false}
                             cor={avatar.cor}
                             rosto={aba === "rosto" ? valor : avatar.rosto}
                             chapeu={aba === "chapeu" ? valor : avatar.chapeu} />
                    </span>
                  )}
                  <b>{aba === "cor" ? "" : ROTULOS[valor] ?? valor}</b>
                  {sel && <span className="selo">✓</span>}
                </button>
              );
            })}
          </div>
        </div>
      </div>
    </section>
  );
}
