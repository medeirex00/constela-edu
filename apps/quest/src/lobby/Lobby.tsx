/**
 * Lobby — a casa do astronauta (Fase Q0): Cosmo vivo no palco, HUD com XP e
 * moedas reais, trilho de planetas em teaser ("em breve") e a gaveta com
 * cor do traje, som e sair. Missões chegam na Fase Q1 (docs/quest/05).
 */
import { useEffect, useMemo, useRef, useState } from "react";

import {
  coresDoTraje,
  trocarCorDoTraje,
  trocarPreferencias,
} from "@constela/quest-core";

import { configurarAudio, narrar, tocar } from "../audio/audio";
import { Cosmo } from "../cosmo/Cosmo";
import { useSessao } from "../estado/sessao";
import { Ceu } from "./Ceu";
import "./lobby.css";

/* Teaser dos planetas (paleta do protótipo; o catálogo real vem do banco
   na Fase Q1 — aqui é só vitrine do que está chegando). */
const PLANETAS_EM_BREVE = [
  { slug: "matematica", nome: "Matemática", icone: "➗", c1: "#FF7A2F", c2: "#E8384F" },
  { slug: "portugues", nome: "Português", icone: "📚", c1: "#12B8A6", c2: "#0E86C9" },
  { slug: "ciencias", nome: "Ciências", icone: "🧪", c1: "#8B3DFF", c2: "#00A8E8" },
  { slug: "geografia", nome: "Geografia", icone: "🌎", c1: "#1FA85B", c2: "#0E86C9" },
  { slug: "historia", nome: "História", icone: "🏛️", c1: "#C89B3C", c2: "#7A4A1E" },
  { slug: "ingles", nome: "Inglês", icone: "🗽", c1: "#3D5AFE", c2: "#00A8E8" },
];

const FALAS_BOAS_VINDAS = [
  "Que bom te ver por aqui!",
  "Pronto para explorar o universo?",
  "Os planetas estão quase prontos para você!",
  "Sua constelação está crescendo!",
];

export function Lobby() {
  const { perfil, atualizarPerfil, sair } = useSessao();
  const [gavetaAberta, setGavetaAberta] = useState(false);
  const [cores, setCores] = useState<string[]>([]);
  const [fala, setFala] = useState("");
  const [toast, setToast] = useState("");
  const temporizadorToast = useRef(0);
  const temporizadorFala = useRef(0);

  const cor = (perfil?.avatar.cor as string) ?? "#FF4D9D";

  useEffect(() => {
    coresDoTraje().then(setCores).catch(() => setCores([]));
  }, []);

  useEffect(() => {
    configurarAudio({
      som: perfil?.preferencias.som !== false,
      narracao: perfil?.preferencias.narracao !== false,
    });
  }, [perfil?.preferencias.som, perfil?.preferencias.narracao]);

  const saudacao = useMemo(
    () => `Oi, ${perfil?.primeiro_nome ?? "astronauta"}! 👋`,
    [perfil?.primeiro_nome],
  );

  useEffect(() => {
    falar(saudacao, 5000);
    narrar(`Oi, ${perfil?.primeiro_nome ?? "astronauta"}! Que bom te ver!`);
    // Só na chegada ao lobby
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function falar(texto: string, duracao = 4000) {
    window.clearTimeout(temporizadorFala.current);
    setFala(texto);
    temporizadorFala.current = window.setTimeout(() => setFala(""), duracao);
  }

  function avisar(texto: string) {
    window.clearTimeout(temporizadorToast.current);
    setToast(texto);
    temporizadorToast.current = window.setTimeout(() => setToast(""), 2600);
  }

  async function escolherCor(nova: string) {
    if (!perfil || nova === cor) return;
    tocar("sucesso");
    try {
      atualizarPerfil(await trocarCorDoTraje(nova));
      falar("Adorei a cor nova! ✨");
    } catch {
      avisar("Não consegui trocar agora. Tente de novo!");
    }
  }

  async function alternarPreferencia(chave: "som" | "musica" | "narracao") {
    if (!perfil) return;
    const valor = !(perfil.preferencias[chave] !== false);
    try {
      atualizarPerfil(await trocarPreferencias({ [chave]: valor }));
      tocar("clique");
    } catch {
      avisar("Não consegui salvar. Tente de novo!");
    }
  }

  function clicarPlaneta() {
    tocar("clique");
    falar(FALAS_BOAS_VINDAS[Math.floor(Math.random() * FALAS_BOAS_VINDAS.length)]);
    avisar("As missões chegam em breve! 🎮");
  }

  if (!perfil) return null;

  return (
    <>
      <Ceu />

      <header className="hud">
        <div className="marca">
          <div className="lua" />
          <span>constela</span>
          <small>QUEST</small>
        </div>
        <div className="hud-direita">
          <div className="chip">⭐ <span>{perfil.xp_total}</span> XP</div>
          <div className="chip">🪙 <span>{perfil.moedas}</span></div>
          <button
            className="botao-avatar"
            onClick={() => { tocar("clique"); setGavetaAberta(true); }}
            aria-label="Abrir minha mochila"
            title="Minha mochila"
          >
            🧑‍🚀
          </button>
        </div>
      </header>

      <main className="palco">
        <div className="palco-interno">
          {fala && <div className="cosmo-fala">{fala}</div>}
          <div className="podio" />
          <Cosmo
            altura="min(58vh, 560px)"
            cor={cor}
            aoClicar={() => falar(
              FALAS_BOAS_VINDAS[Math.floor(Math.random() * FALAS_BOAS_VINDAS.length)],
            )}
          />
        </div>
      </main>

      <div className="planetas-area">
        <p className="planetas-titulo">Seus planetas estão chegando! 🚀</p>
        <div className="planetas">
          {PLANETAS_EM_BREVE.map((planeta) => (
            <button
              key={planeta.slug}
              className="planeta"
              style={{ "--c1": planeta.c1, "--c2": planeta.c2 } as React.CSSProperties}
              onClick={clicarPlaneta}
            >
              <span className="icone" aria-hidden>{planeta.icone}</span>
              <span className="nome">{planeta.nome}</span>
              <span className="emblema">🔒 Em breve</span>
              <span className="fundo-icone" aria-hidden>{planeta.icone}</span>
            </button>
          ))}
        </div>
      </div>

      <div
        className={`escurecedor${gavetaAberta ? " aberta" : ""}`}
        onClick={() => setGavetaAberta(false)}
      />
      <aside className={`gaveta${gavetaAberta ? " aberta" : ""}`}
             aria-label="Minha mochila">
        <button className="fechar" onClick={() => setGavetaAberta(false)}
                aria-label="Fechar">✕</button>

        <div className="quem-sou">
          <Cosmo altura="72px" vivo={false} cor={cor} />
          <div>
            <b>{perfil.primeiro_nome}</b>
            <span>✨ {perfil.apelido} · Nível {perfil.nivel}</span>
            <br />
            <span>🤝 {perfil.codigo_amigo}</span>
          </div>
        </div>

        <h3>👕 Cor do meu traje</h3>
        <div className="amostras">
          {cores.map((opcao) => (
            <button
              key={opcao}
              className={`amostra${opcao === cor ? " escolhida" : ""}`}
              style={{ background: opcao }}
              onClick={() => escolherCor(opcao)}
              aria-label={`Cor ${opcao === cor ? "escolhida" : "disponível"}`}
            />
          ))}
        </div>

        <h3>🎵 Sons</h3>
        <button className="opcao" onClick={() => alternarPreferencia("som")}>
          <span className="icone-opcao">🔊</span> Efeitos
          <small>{perfil.preferencias.som !== false ? "ligados" : "desligados"}</small>
        </button>
        <button className="opcao" onClick={() => alternarPreferencia("narracao")}>
          <span className="icone-opcao">🗣️</span> Narração
          <small>{perfil.preferencias.narracao !== false ? "ligada" : "desligada"}</small>
        </button>

        <button
          className="opcao perigo"
          onClick={() => { tocar("clique"); void sair(); }}
        >
          <span className="icone-opcao">🚪</span> Sair da minha conta
        </button>
      </aside>

      <div id="toast" className={toast ? "on" : ""} role="status">{toast}</div>
    </>
  );
}
