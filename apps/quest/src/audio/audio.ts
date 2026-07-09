/**
 * Áudio do Quest — efeitos sintetizados (WebAudio, zero assets, funciona
 * offline) e narração pt-BR à prova de tablet de escola:
 *
 *  - a voz é escolhida EXPLICITAMENTE entre as vozes pt-* do aparelho
 *    (getVoices carrega assíncrono no Android — ouvimos voiceschanged);
 *  - navegador exige gesto do usuário para tocar som: o primeiro
 *    pointerdown destrava o AudioContext e solta a narração pendente
 *    (cobre o fluxo por QR, que chega ao lobby sem nenhum toque);
 *  - sem voz pt disponível, `narracaoDisponivel()` devolve false e a
 *    interface mostra o texto no balão do Cosmo (nunca falha em silêncio).
 *
 * Áudios gravados (OGG) entram na Q1 para as frases fixas; a Web Speech
 * fica de fallback para texto dinâmico (docs/quest/05).
 */

let contexto: AudioContext | null = null;
let efeitosAtivos = true;
let narracaoAtiva = true;
let vozPt: SpeechSynthesisVoice | null = null;
let vozesProntas = false;
let narracaoPendente: string | null = null;
let desbloqueado = false;

// ---------------------------------------------------------------------------
// Inicialização (vozes + gesto de desbloqueio)
// ---------------------------------------------------------------------------

function escolherVoz() {
  if (typeof speechSynthesis === "undefined") return;
  const vozes = speechSynthesis.getVoices();
  if (!vozes.length) return;
  vozesProntas = true;
  // Preferência: pt-BR local > pt-BR qualquer > pt-* qualquer
  vozPt =
    vozes.find((v) => v.lang.replace("_", "-") === "pt-BR" && v.localService) ??
    vozes.find((v) => v.lang.replace("_", "-") === "pt-BR") ??
    vozes.find((v) => v.lang.toLowerCase().startsWith("pt")) ??
    null;
}

function aoPrimeiroGesto() {
  desbloqueado = true;
  void ctx()?.resume();
  if (narracaoPendente) {
    const texto = narracaoPendente;
    narracaoPendente = null;
    narrar(texto);
  }
  window.removeEventListener("pointerdown", aoPrimeiroGesto);
  window.removeEventListener("keydown", aoPrimeiroGesto);
}

export function iniciarAudio() {
  if (typeof speechSynthesis !== "undefined") {
    escolherVoz();
    speechSynthesis.addEventListener?.("voiceschanged", escolherVoz);
  }
  window.addEventListener("pointerdown", aoPrimeiroGesto, { passive: true });
  window.addEventListener("keydown", aoPrimeiroGesto);
}

/** false = este aparelho não tem voz em português (a UI mostra o texto). */
export function narracaoDisponivel(): boolean {
  if (typeof speechSynthesis === "undefined") return false;
  if (!vozesProntas) escolherVoz();
  return vozPt !== null;
}

function ctx(): AudioContext | null {
  if (typeof AudioContext === "undefined") return null;
  if (!contexto) contexto = new AudioContext();
  if (contexto.state === "suspended") void contexto.resume();
  return contexto;
}

export function configurarAudio(opcoes: { som?: boolean; narracao?: boolean }) {
  if (opcoes.som !== undefined) efeitosAtivos = opcoes.som;
  if (opcoes.narracao !== undefined) narracaoAtiva = opcoes.narracao;
}

// ---------------------------------------------------------------------------
// Efeitos (sintetizados — gentis, nunca punitivos)
// ---------------------------------------------------------------------------

function nota(
  frequencia: number,
  inicio: number,
  duracao: number,
  tipo: OscillatorType = "sine",
  volume = 0.12,
) {
  const audio = ctx();
  if (!audio) return;
  const osc = audio.createOscillator();
  const ganho = audio.createGain();
  osc.type = tipo;
  osc.frequency.value = frequencia;
  const t = audio.currentTime + inicio;
  ganho.gain.setValueAtTime(0, t);
  ganho.gain.linearRampToValueAtTime(volume, t + 0.015);
  ganho.gain.exponentialRampToValueAtTime(0.001, t + duracao);
  osc.connect(ganho).connect(audio.destination);
  osc.start(t);
  osc.stop(t + duracao + 0.05);
}

/** Nota solta (usada pelo céu tocável — escala pentatônica). */
export function tocarNota(frequencia: number, volume = 0.1) {
  if (!efeitosAtivos) return;
  nota(frequencia, 0, 0.5, "triangle", volume);
}

export type Efeito = "clique" | "sucesso" | "erro" | "fanfarra" | "bip";

export function tocar(efeito: Efeito) {
  if (!efeitosAtivos) return;
  switch (efeito) {
    case "clique":
      nota(660, 0, 0.08, "triangle", 0.08);
      break;
    case "bip":
      nota(1180, 0, 0.09, "square", 0.05);
      nota(1560, 0.09, 0.12, "square", 0.05);
      break;
    case "sucesso":
      nota(523.25, 0, 0.12, "triangle");
      nota(659.25, 0.09, 0.12, "triangle");
      nota(783.99, 0.18, 0.2, "triangle");
      break;
    case "erro":
      // Descida curta e suave — "quase!", não "buzina de reprovação"
      nota(392, 0, 0.14, "sine", 0.09);
      nota(329.63, 0.12, 0.18, "sine", 0.09);
      break;
    case "fanfarra":
      nota(523.25, 0, 0.12, "triangle");
      nota(659.25, 0.1, 0.12, "triangle");
      nota(783.99, 0.2, 0.12, "triangle");
      nota(1046.5, 0.3, 0.3, "triangle", 0.14);
      break;
  }
}

// ---------------------------------------------------------------------------
// Narração pt-BR
// ---------------------------------------------------------------------------

function limparParaFala(texto: string): string {
  // Emojis e símbolos viram silêncio, não "cara sorridente"
  return texto
    .replace(/[\u{1F000}-\u{1FFFF}\u{2600}-\u{27BF}\u{2190}-\u{21FF}]/gu, "")
    .replace(/\s+/g, " ")
    .trim();
}

/** Narra em pt-BR. Antes do primeiro gesto do usuário, guarda a última
 * frase e a solta quando a criança tocar na tela. */
export function narrar(texto: string) {
  if (!narracaoAtiva || !narracaoDisponivel()) return;
  const fala = limparParaFala(texto);
  if (!fala) return;
  if (!desbloqueado) {
    narracaoPendente = fala;
    return;
  }
  speechSynthesis.cancel();
  // O cancel() imediato seguido de speak() engasga em alguns Android —
  // um respiro de 60ms resolve.
  window.setTimeout(() => {
    const declaracao = new SpeechSynthesisUtterance(fala);
    declaracao.lang = "pt-BR";
    if (vozPt) declaracao.voice = vozPt;
    declaracao.rate = 0.95;
    declaracao.pitch = 1.15;
    speechSynthesis.speak(declaracao);
  }, 60);
}
