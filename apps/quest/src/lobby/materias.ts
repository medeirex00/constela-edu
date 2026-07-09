/**
 * Matérias = planetas. Cada uma tem nome de planeta, gradiente do céu,
 * atmosfera (nebulosas de luz), corpo de planeta, partículas temáticas e as
 * missões do dia. O `Cena` compõe todas essas camadas para dar a sensação de
 * viajar para um mundo diferente por matéria.
 */
export interface Missao {
  nome: string;
  xp: number;
}

export interface Particula {
  /** 'glifo' usa `glifos`; as demais desenham formas pequenas. */
  tipo: "glifo" | "bolha" | "folha" | "faisca" | "tinta";
  glifos?: string[];
  cor?: string;
}

export interface Materia {
  slug: string;
  nome: string;
  /** Nome do planeta (ex.: "Planeta Numéria"). */
  planeta: string;
  icone: string;
  c1: string;
  c2: string;
  /** Gradiente do céu quando a matéria está selecionada. */
  sky: [string, string];
  /** Nebulosas de luz (radiais) que dão iluminação própria ao planeta. */
  nebulas: [string, string];
  /** Cores do corpo do planeta que flutua no cenário. */
  corpo: { c1: string; c2: string; aneis?: boolean };
  particula: Particula;
  missoes: Missao[];
}

export const MATERIAS: Materia[] = [
  {
    slug: "matematica", nome: "Matemática", planeta: "Numéria", icone: "➗",
    c1: "#FF7A2F", c2: "#E8384F", sky: ["#FFB25E", "#FF6E7A"],
    nebulas: ["#FFD98A", "#FF5470"], corpo: { c1: "#FF9E3C", c2: "#E8384F", aneis: true },
    particula: { tipo: "glifo", glifos: ["+", "−", "×", "÷", "=", "7", "9", "π", "√"] },
    missoes: [
      { nome: "Tabuada relâmpago do 7", xp: 30 },
      { nome: "Caça às frações", xp: 45 },
      { nome: "Desafio: problemas do dia a dia", xp: 60 },
    ],
  },
  {
    slug: "portugues", nome: "Português", planeta: "Palavras", icone: "📚",
    c1: "#12B8A6", c2: "#0E86C9", sky: ["#6FD8CC", "#49B6FF"],
    nebulas: ["#9BF0E4", "#49B6FF"], corpo: { c1: "#2AD6C0", c2: "#0E86C9" },
    particula: { tipo: "glifo", glifos: ["A", "B", "a", "?", "!", "ç", "z"] },
    missoes: [
      { nome: "Complete a história maluca", xp: 35 },
      { nome: "Caça-palavras: animais", xp: 40 },
      { nome: "Acentos em ação", xp: 50 },
    ],
  },
  {
    slug: "ciencias", nome: "Ciências", planeta: "Biozênia", icone: "🧪",
    c1: "#8B3DFF", c2: "#00A8E8", sky: ["#B07CFF", "#4FD8FF"],
    nebulas: ["#D6B0FF", "#4FD8FF"], corpo: { c1: "#A24BFF", c2: "#00A8E8" },
    particula: { tipo: "bolha", cor: "rgba(255,255,255,.7)" },
    missoes: [
      { nome: "Sistema solar em ordem", xp: 40 },
      { nome: "Estados da água", xp: 35 },
      { nome: "Corpo humano: órgãos", xp: 60 },
    ],
  },
  {
    slug: "geografia", nome: "Geografia", planeta: "Terra Nova", icone: "🌎",
    c1: "#1FA85B", c2: "#0E86C9", sky: ["#5ED08A", "#3EB8FF"],
    nebulas: ["#A6F0C2", "#3EB8FF"], corpo: { c1: "#2EC76F", c2: "#0E86C9", aneis: true },
    particula: { tipo: "faisca", cor: "rgba(255,255,255,.8)" },
    missoes: [
      { nome: "Capitais do Brasil", xp: 40 },
      { nome: "Monte o mapa das regiões", xp: 50 },
      { nome: "Rios e montanhas", xp: 60 },
    ],
  },
  {
    slug: "historia", nome: "História", planeta: "Chronos", icone: "🏛️",
    c1: "#C89B3C", c2: "#7A4A1E", sky: ["#E8C367", "#C08A3E"],
    nebulas: ["#F5DE9E", "#B5732E"], corpo: { c1: "#D9A94A", c2: "#7A4A1E" },
    particula: { tipo: "faisca", cor: "rgba(255,240,200,.85)" },
    missoes: [
      { nome: "Linha do tempo do Brasil", xp: 40 },
      { nome: "Quem foi? Personagens históricos", xp: 45 },
      { nome: "Grandes invenções", xp: 55 },
    ],
  },
  {
    slug: "ingles", nome: "Inglês", planeta: "Oxford", icone: "🗽",
    c1: "#3D5AFE", c2: "#00A8E8", sky: ["#6D8CFF", "#5FD0FF"],
    nebulas: ["#AEC0FF", "#5FD0FF"], corpo: { c1: "#4E6BFF", c2: "#00A8E8" },
    particula: { tipo: "glifo", glifos: ["A", "B", "C", "?", "!"] },
    missoes: [
      { nome: "Cores em inglês", xp: 30 },
      { nome: "Monte a frase: My family", xp: 45 },
      { nome: "Bingo de animais", xp: 55 },
    ],
  },
  {
    slug: "artes", nome: "Artes", planeta: "Colorium", icone: "🎨",
    c1: "#F0447C", c2: "#7A3DF0", sky: ["#FF7DB0", "#9D7BFF"],
    nebulas: ["#FFB3D2", "#B79BFF"], corpo: { c1: "#FF5FA0", c2: "#7A3DF0" },
    particula: { tipo: "tinta" },
    missoes: [
      { nome: "Pinte o astronauta", xp: 30 },
      { nome: "Formas e cores", xp: 40 },
      { nome: "Música: complete o ritmo", xp: 45 },
    ],
  },
  {
    slug: "edfisica", nome: "Ed. Física", planeta: "Movi", icone: "⚽",
    c1: "#2EC77A", c2: "#128F4E", sky: ["#7BE6A8", "#2FB06A"],
    nebulas: ["#B6F5CE", "#2FB06A"], corpo: { c1: "#3DD98A", c2: "#128F4E" },
    particula: { tipo: "faisca", cor: "rgba(255,255,255,.85)" },
    missoes: [
      { nome: "Desafio dos alongamentos", xp: 30 },
      { nome: "Regras dos esportes", xp: 40 },
      { nome: "Corrida dos números", xp: 45 },
    ],
  },
  {
    slug: "erer", nome: "ERER", planeta: "Raízes", icone: "🌍",
    c1: "#E8730E", c2: "#B5179E", sky: ["#FFB35C", "#E86FC0"],
    nebulas: ["#FFD29E", "#E86FC0"], corpo: { c1: "#F08C2E", c2: "#B5179E" },
    particula: { tipo: "folha", cor: "rgba(255,220,150,.85)" },
    missoes: [
      { nome: "Histórias e culturas do Brasil", xp: 40 },
      { nome: "Ritmos e instrumentos", xp: 40 },
      { nome: "Padrões e cores", xp: 45 },
    ],
  },
];

export const MATERIA_POR_SLUG: Record<string, Materia> = Object.fromEntries(
  MATERIAS.map((m) => [m.slug, m]),
);
