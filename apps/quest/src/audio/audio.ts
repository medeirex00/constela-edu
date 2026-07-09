/**
 * Áudio base da Fase Q0: efeitos curtos sintetizados com WebAudio — zero
 * assets para baixar, funciona offline. Música e narração gravada entram
 * nas próximas fases (docs/quest/05); a API já separa efeito × música.
 *
 * Instrução de 1º/2º ano ainda usa a Web Speech API (narrar) como ponte até
 * os áudios gravados — melhor uma voz sintética que uma criança sem leitura.
 */

let contexto: AudioContext | null = null;
let efeitosAtivos = true;
let narracaoAtiva = true;

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

export type Efeito = "clique" | "sucesso" | "erro" | "fanfarra";

/** Efeitos gentis — "erro" nunca soa punitivo (docs/quest/03). */
export function tocar(efeito: Efeito) {
  if (!efeitosAtivos) return;
  switch (efeito) {
    case "clique":
      nota(660, 0, 0.08, "triangle", 0.08);
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

/** Narra um texto em pt-BR (instruções para quem ainda não lê). */
export function narrar(texto: string) {
  if (!narracaoAtiva || typeof speechSynthesis === "undefined") return;
  speechSynthesis.cancel();
  const fala = new SpeechSynthesisUtterance(texto);
  fala.lang = "pt-BR";
  fala.rate = 0.95;
  fala.pitch = 1.15;
  speechSynthesis.speak(fala);
}
