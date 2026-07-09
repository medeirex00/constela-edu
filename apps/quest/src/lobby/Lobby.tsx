/**
 * Lobby — a casa do astronauta, com abas Jogar / Vestiário / Carreira.
 *
 * Jogar: Cosmo vivo (com física e, se equipado, skate voador que entra pela
 * constelação), céu tocável, trilho de matérias — ao escolher uma matéria o
 * fundo vira o cenário temático dela e aparecem as missões do dia + "Jogar
 * agora". Sair é uma despedida do Cosmo (sem guardar a conta no aparelho).
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { trocarPreferencias } from "@constela/quest-core";

import { configurarAudio, narrar, tocar } from "../audio/audio";
import { Carreira } from "../carreira/Carreira";
import { Cosmo } from "../cosmo/Cosmo";
import { Palco3D } from "../personagem/Palco3D";
import { useSessao } from "../estado/sessao";
import { Vestiario } from "../vestiario/Vestiario";
import { Cena } from "./Cena";
import { Ceu } from "./Ceu";
import { MATERIAS, MATERIA_POR_SLUG } from "./materias";
import "./lobby.css";

type Aba = "jogar" | "vestiario" | "carreira";

const SAUDACOES = ["Bom dia", "Boa tarde", "Boa noite"];
const FALAS_TOQUE = [
  "Que bom te ver por aqui!",
  "Pronto para explorar o universo?",
  "Escolha um planeta pra gente viajar!",
  "Já tentou tocar nas estrelas do céu?",
  "Você está ficando cada vez mais estiloso!",
];
function saudacaoPorHora(): string {
  const h = new Date().getHours();
  if (h < 6) return "Jogando de madrugada, astronauta?";
  return SAUDACOES[h < 12 ? 0 : h < 18 ? 1 : 2];
}

export function Lobby() {
  const { perfil, atualizarPerfil, sair } = useSessao();
  const [aba, setAba] = useState<Aba>("jogar");
  const [materia, setMateria] = useState<string | null>(null);
  const [gaveta, setGaveta] = useState(false);
  const [despedida, setDespedida] = useState(false);
  const [fala, setFala] = useState("");
  const [toast, setToast] = useState("");
  const tToast = useRef(0);
  const tFala = useRef(0);
  const botaoAvatarRef = useRef<HTMLButtonElement>(null);
  const gavetaRef = useRef<HTMLElement>(null);

  const falar = useCallback((texto: string, dur = 4500) => {
    window.clearTimeout(tFala.current);
    setFala(texto);
    narrar(texto);
    tFala.current = window.setTimeout(() => setFala(""), dur);
  }, []);

  function avisar(texto: string) {
    window.clearTimeout(tToast.current);
    setToast(texto);
    tToast.current = window.setTimeout(() => setToast(""), 2600);
  }

  useEffect(() => {
    configurarAudio({
      som: perfil?.preferencias.som !== false,
      narracao: perfil?.preferencias.narracao !== false,
    });
  }, [perfil?.preferencias.som, perfil?.preferencias.narracao]);

  // Saudação com memória — só na chegada
  useEffect(() => {
    if (!perfil) return;
    if (perfil.dias_sem_jogar >= 3) {
      falar(`Que saudade, ${perfil.nome}! O universo sentiu sua falta! 💫`, 6000);
    } else {
      falar(`${saudacaoPorHora()}, ${perfil.nome}! 👋`, 5000);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Fundo temático: muda o gradiente do céu conforme a matéria escolhida
  useEffect(() => {
    const raiz = document.documentElement;
    const m = materia ? MATERIA_POR_SLUG[materia] : null;
    if (aba === "jogar" && m) {
      raiz.style.setProperty("--sky-a", m.sky[0]);
      raiz.style.setProperty("--sky-b", m.sky[1]);
    } else {
      raiz.style.removeProperty("--sky-a");
      raiz.style.removeProperty("--sky-b");
    }
    return () => {
      raiz.style.removeProperty("--sky-a");
      raiz.style.removeProperty("--sky-b");
    };
  }, [aba, materia]);

  // Gaveta acessível
  useEffect(() => {
    const g = gavetaRef.current;
    if (g) {
      if (gaveta) { g.removeAttribute("inert"); g.querySelector<HTMLButtonElement>(".fechar")?.focus(); }
      else g.setAttribute("inert", "");
    }
    if (!gaveta) return;
    const aoTeclar = (e: KeyboardEvent) => {
      if (e.key === "Escape") { setGaveta(false); botaoAvatarRef.current?.focus(); }
    };
    window.addEventListener("keydown", aoTeclar);
    return () => window.removeEventListener("keydown", aoTeclar);
  }, [gaveta]);

  function trocarAba(nova: Aba) {
    tocar("clique");
    setAba(nova);
    if (nova !== "jogar") setMateria(null);
  }

  function selecionar(slug: string) {
    tocar("clique");
    setMateria(slug);
    const m = MATERIA_POR_SLUG[slug];
    falar(`Planeta ${m.nome}! Escolha uma missão e partiu! 🚀`);
  }

  async function alternarPreferencia(chave: "som" | "narracao") {
    if (!perfil) return;
    const valor = !(perfil.preferencias[chave] !== false);
    try {
      atualizarPerfil(await trocarPreferencias({ [chave]: valor }));
      tocar("clique");
    } catch {
      avisar("Não consegui salvar. Tente de novo!");
    }
  }

  function confirmarSaida() {
    setGaveta(false);
    setDespedida(true);
    narrar(`Você quer mesmo ir embora, ${perfil?.nome ?? "astronauta"}?`);
  }
  async function despedirse() {
    tocar("clique");
    narrar("Até a próxima!");
    await sair();
  }

  if (!perfil) return null;
  const mostrarChips = perfil.xp_total > 0 || perfil.moedas > 0;
  const materiaAtual = materia ? MATERIA_POR_SLUG[materia] : null;

  return (
    <>
      <Ceu
        tocavel={aba === "jogar" && !materia}
        aoCompletar={() => { tocar("fanfarra"); falar("UAU! Você acendeu o céu inteiro! ✨"); }}
      />
      <Cena slug={aba === "jogar" && materia ? materia : "lobby"} />

      <header className="hud">
        <div className="marca">
          <div className="lua" />
          <span>constela</span>
          <small>QUEST</small>
        </div>
        <nav className="nav">
          <button className={`tab${aba === "jogar" ? " ativa" : ""}`}
                  onClick={() => trocarAba("jogar")}>Jogar</button>
          <button className={`tab${aba === "vestiario" ? " ativa" : ""}`}
                  onClick={() => trocarAba("vestiario")}>Vestiário</button>
          <button className={`tab${aba === "carreira" ? " ativa" : ""}`}
                  onClick={() => trocarAba("carreira")}>Carreira</button>
        </nav>
        <div className="hud-direita">
          {mostrarChips && (
            <>
              <div className="chip">⭐ <span>{perfil.xp_total}</span> XP</div>
              <div className="chip">🪙 <span>{perfil.moedas}</span></div>
            </>
          )}
          <button ref={botaoAvatarRef} className="botao-avatar"
                  onClick={() => { tocar("clique"); setGaveta(true); }}
                  aria-label="Abrir minha mochila" aria-expanded={gaveta}>
            🧑‍🚀
          </button>
        </div>
      </header>

      {aba === "jogar" && (
        <>
          <main className="palco">
            <div className="palco-interno">
              <div className="podio" />
              <Palco3D avatar={perfil.avatar} interativo altura="min(62vh, 600px)" className="lobby-3d" />
              {/* Cosmo virou o mascote-companheiro: fica ao lado e fala */}
              <div className="companheiro">
                {fala && <div className="cosmo-fala">{fala}</div>}
                <Cosmo altura="150px" cor="#7C6FF0"
                       aoClicar={() => falar(
                         FALAS_TOQUE[Math.floor(Math.random() * FALAS_TOQUE.length)])}
                       fisica />
              </div>
            </div>
          </main>

          <aside className={`missoes${materiaAtual ? " aberto" : ""}`}
                 style={materiaAtual ? ({ "--m-cor": materiaAtual.c1 } as React.CSSProperties) : undefined}
                 aria-live="polite">
            {materiaAtual && (
              <>
                <h2><span aria-hidden>{materiaAtual.icone}</span> {materiaAtual.nome}</h2>
                <p className="sub">{materiaAtual.missoes.length} missões disponíveis hoje</p>
                {materiaAtual.missoes.map((m) => (
                  <div className="missao" key={m.nome}>
                    <span className="anel" />
                    <span className="info">{m.nome}</span>
                    <span className="xp">+{m.xp} XP</span>
                  </div>
                ))}
                <button className="btn-jogar"
                        onClick={() => { tocar("clique"); avisar("As missões chegam em breve! 🎮"); }}>
                  Jogar agora!
                </button>
              </>
            )}
          </aside>

          <div className="materias-area">
            <p className="materias-dica">Escolha sua matéria e partiu missão! 🚀</p>
            <div className="materias">
              {MATERIAS.map((m) => (
                <button
                  key={m.slug}
                  className={`materia-card${materia === m.slug ? " selecionada" : ""}`}
                  style={{ "--c1": m.c1, "--c2": m.c2 } as React.CSSProperties}
                  onClick={() => selecionar(m.slug)}
                >
                  <span className="icone" aria-hidden>{m.icone}</span>
                  <span className="nome">{m.nome}</span>
                  <span className="conta">{m.missoes.length} missões</span>
                  <span className="fundo-icone" aria-hidden>{m.icone}</span>
                </button>
              ))}
            </div>
          </div>
        </>
      )}

      {aba === "vestiario" && <Vestiario />}
      {aba === "carreira" && <Carreira />}

      <div className={`escurecedor${gaveta ? " aberta" : ""}`} onClick={() => setGaveta(false)} />
      <aside ref={gavetaRef} className={`gaveta${gaveta ? " aberta" : ""}`}
             role="dialog" aria-modal="true" aria-label="Minha mochila">
        <button className="fechar"
                onClick={() => { setGaveta(false); botaoAvatarRef.current?.focus(); }}
                aria-label="Fechar">✕</button>
        <div className="quem-sou">
          <div className="quem-av" aria-hidden>🧑‍🚀</div>
          <div>
            <b>{perfil.nome}</b>
            <span>✨ {perfil.apelido} · Nível {perfil.nivel}</span>
            <br />
            <span>🤝 {perfil.codigo_amigo}</span>
          </div>
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
        <button className="opcao trocar" onClick={confirmarSaida}>
          <span className="icone-opcao">👋</span> Trocar de astronauta
        </button>
      </aside>

      {despedida && (
        <div className="despedida" role="dialog" aria-modal="true">
          <div className="painel despedida-painel">
            <Palco3D avatar={perfil.avatar} altura="180px" />
            <h2>Você quer mesmo ir embora?</h2>
            <button className="botao3d verde" autoFocus
                    onClick={() => { tocar("clique"); setDespedida(false); }}>
              ✅ Ainda não!
            </button>
            <button className="botao3d fantasma" onClick={() => void despedirse()}>
              👋 Tchau, Cosmo!
            </button>
          </div>
        </div>
      )}

      <div id="toast" className={toast ? "on" : ""} role="status">{toast}</div>
    </>
  );
}
