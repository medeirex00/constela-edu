/**
 * Lobby — a casa do astronauta:
 *
 *  - Cosmo vivo com zonas de toque; céu tocável (constelação do dia);
 *  - saudação com memória (hora do dia + "que saudade!" após dias fora);
 *  - chips de XP/moedas só aparecem quando existe o que mostrar;
 *  - sair é uma DESPEDIDA do Cosmo com confirmação, não um botão de perigo;
 *  - toda fala do Cosmo também é narrada (quem não lê não fica de fora).
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { trocarCorDoTraje, trocarPreferencias } from "@constela/quest-core";

import { configurarAudio, narrar, tocar } from "../audio/audio";
import { Cosmo } from "../cosmo/Cosmo";
import { useSessao } from "../estado/sessao";
import { Ceu } from "./Ceu";
import { CORES_TRAJE } from "./cores";
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

const FALAS_TOQUE = [
  "Que bom te ver por aqui!",
  "Pronto para explorar o universo?",
  "Os planetas estão quase prontos para você!",
  "Sua constelação está crescendo!",
  "Você já tentou tocar nas estrelas do céu?",
];

function saudacaoPorHora(): string {
  const hora = new Date().getHours();
  if (hora < 6) return "Jogando de madrugada, astronauta?";
  if (hora < 12) return "Bom dia";
  if (hora < 18) return "Boa tarde";
  return "Boa noite";
}

export function Lobby() {
  const { perfil, atualizarPerfil, sair } = useSessao();
  const [gavetaAberta, setGavetaAberta] = useState(false);
  const [despedida, setDespedida] = useState(false);
  const [fala, setFala] = useState("");
  const [toast, setToast] = useState("");
  const temporizadorToast = useRef(0);
  const temporizadorFala = useRef(0);
  const gavetaRef = useRef<HTMLElement>(null);
  const botaoAvatarRef = useRef<HTMLButtonElement>(null);

  const cor = (perfil?.avatar.cor as string) ?? "#FF4D9D";

  useEffect(() => {
    configurarAudio({
      som: perfil?.preferencias.som !== false,
      narracao: perfil?.preferencias.narracao !== false,
    });
  }, [perfil?.preferencias.som, perfil?.preferencias.narracao]);

  const falar = useCallback((texto: string, duracao = 4500) => {
    window.clearTimeout(temporizadorFala.current);
    setFala(texto);
    narrar(texto);
    temporizadorFala.current = window.setTimeout(() => setFala(""), duracao);
  }, []);

  function avisar(texto: string) {
    window.clearTimeout(temporizadorToast.current);
    setToast(texto);
    temporizadorToast.current = window.setTimeout(() => setToast(""), 2600);
  }

  // Saudação com memória — só na chegada ao lobby
  useEffect(() => {
    if (!perfil) return;
    const dias = perfil.dias_sem_jogar;
    if (dias >= 3) {
      falar(`Que saudade, ${perfil.nome}! O universo sentiu sua falta! 💫`, 6000);
    } else {
      falar(`${saudacaoPorHora()}, ${perfil.nome}! 👋`, 5000);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Gaveta acessível: Escape fecha, foco entra e volta
  useEffect(() => {
    const gaveta = gavetaRef.current;
    if (gaveta) {
      if (gavetaAberta) {
        gaveta.removeAttribute("inert");
        gaveta.querySelector<HTMLButtonElement>(".fechar")?.focus();
      } else {
        gaveta.setAttribute("inert", "");
      }
    }
    if (!gavetaAberta) return;
    const aoTeclar = (evento: KeyboardEvent) => {
      if (evento.key === "Escape") {
        setGavetaAberta(false);
        botaoAvatarRef.current?.focus();
      }
    };
    window.addEventListener("keydown", aoTeclar);
    return () => window.removeEventListener("keydown", aoTeclar);
  }, [gavetaAberta]);

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

  function clicarPlaneta(nome: string, evento: React.MouseEvent<HTMLButtonElement>) {
    tocar("clique");
    const botao = evento.currentTarget;
    botao.classList.remove("balancando");
    void botao.getBoundingClientRect();
    botao.classList.add("balancando");
    falar(`O Planeta ${nome} ainda está sendo construído! Já já a gente viaja pra lá! 🚀`);
  }

  function completouCeu() {
    tocar("fanfarra");
    falar("UAU! Você acendeu o céu inteiro! ✨ Amanhã tem estrelas novas!", 6000);
  }

  function confirmarSaida() {
    setGavetaAberta(false);
    setDespedida(true);
    narrar(`Você quer mesmo ir embora, ${perfil?.nome ?? "astronauta"}?`);
  }

  async function despedirse() {
    tocar("clique");
    narrar("Até a próxima! Vou guardar seu lugar!");
    await sair();
  }

  if (!perfil) return null;

  const mostrarChips = perfil.xp_total > 0 || perfil.moedas > 0;

  return (
    <>
      <Ceu tocavel aoCompletar={completouCeu} />

      <header className="hud">
        <div className="marca">
          <div className="lua" />
          <span>constela</span>
          <small>QUEST</small>
        </div>
        <div className="hud-direita">
          {/* Contador zerado não é progresso, é lembrete de vazio — os
              chips só aparecem quando a economia existir para a criança */}
          {mostrarChips && (
            <>
              <div className="chip">⭐ <span>{perfil.xp_total}</span> XP</div>
              <div className="chip">🪙 <span>{perfil.moedas}</span></div>
            </>
          )}
          <button
            ref={botaoAvatarRef}
            className="botao-avatar"
            onClick={() => { tocar("clique"); setGavetaAberta(true); }}
            aria-label="Abrir minha mochila"
            aria-expanded={gavetaAberta}
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
              FALAS_TOQUE[Math.floor(Math.random() * FALAS_TOQUE.length)],
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
              onClick={(evento) => clicarPlaneta(planeta.nome, evento)}
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
      <aside
        ref={gavetaRef}
        className={`gaveta${gavetaAberta ? " aberta" : ""}`}
        role="dialog"
        aria-modal="true"
        aria-label="Minha mochila"
      >
        <button className="fechar"
                onClick={() => { setGavetaAberta(false); botaoAvatarRef.current?.focus(); }}
                aria-label="Fechar">✕</button>

        <div className="quem-sou">
          <Cosmo altura="72px" vivo={false} cor={cor} />
          <div>
            <b>{perfil.nome}</b>
            <span>✨ {perfil.apelido} · Nível {perfil.nivel}</span>
            <br />
            <span>🤝 {perfil.codigo_amigo}</span>
          </div>
        </div>

        <h3>👕 Cor do meu traje</h3>
        <div className="amostras">
          {CORES_TRAJE.map((opcao) => (
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

        <button className="opcao trocar" onClick={confirmarSaida}>
          <span className="icone-opcao">👋</span> Trocar de astronauta
        </button>
      </aside>

      {despedida && (
        <div className="despedida" role="dialog" aria-modal="true">
          <div className="painel despedida-painel">
            <Cosmo altura="160px" vivo={false} cor={cor} />
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
