/**
 * Matérias (planetas) do trilho do lobby — cores, ícones, gradiente do céu e
 * as missões do dia. Dados de vitrine da Q0 (o catálogo real vem do backend
 * na Q1); o formato espelha o SUBJECTS do protótipo constela-play-v7.
 */
export interface Missao {
  nome: string;
  xp: number;
}

export interface Materia {
  slug: string;
  nome: string;
  icone: string;
  c1: string;
  c2: string;
  /** Gradiente do céu (claro) quando a matéria está selecionada. */
  sky: [string, string];
  missoes: Missao[];
}

export const MATERIAS: Materia[] = [
  {
    slug: "matematica", nome: "Matemática", icone: "➗",
    c1: "#FF7A2F", c2: "#E8384F", sky: ["#FFB25E", "#FF6E7A"],
    missoes: [
      { nome: "Tabuada relâmpago do 7", xp: 30 },
      { nome: "Caça às frações", xp: 45 },
      { nome: "Desafio: problemas do dia a dia", xp: 60 },
    ],
  },
  {
    slug: "portugues", nome: "Português", icone: "📚",
    c1: "#12B8A6", c2: "#0E86C9", sky: ["#6FD8CC", "#49B6FF"],
    missoes: [
      { nome: "Complete a história maluca", xp: 35 },
      { nome: "Caça-palavras: animais", xp: 40 },
      { nome: "Acentos em ação", xp: 50 },
    ],
  },
  {
    slug: "ciencias", nome: "Ciências", icone: "🧪",
    c1: "#8B3DFF", c2: "#00A8E8", sky: ["#B07CFF", "#4FD8FF"],
    missoes: [
      { nome: "Sistema solar em ordem", xp: 40 },
      { nome: "Estados da água", xp: 35 },
      { nome: "Corpo humano: órgãos", xp: 60 },
    ],
  },
  {
    slug: "geografia", nome: "Geografia", icone: "🌎",
    c1: "#1FA85B", c2: "#0E86C9", sky: ["#5ED08A", "#3EB8FF"],
    missoes: [
      { nome: "Capitais do Brasil", xp: 40 },
      { nome: "Monte o mapa das regiões", xp: 50 },
      { nome: "Rios e montanhas", xp: 60 },
    ],
  },
  {
    slug: "historia", nome: "História", icone: "🏛️",
    c1: "#C89B3C", c2: "#7A4A1E", sky: ["#E8C367", "#C08A3E"],
    missoes: [
      { nome: "Linha do tempo do Brasil", xp: 40 },
      { nome: "Quem foi? Personagens históricos", xp: 45 },
      { nome: "Grandes invenções", xp: 55 },
    ],
  },
  {
    slug: "ingles", nome: "Inglês", icone: "🗽",
    c1: "#3D5AFE", c2: "#00A8E8", sky: ["#6D8CFF", "#5FD0FF"],
    missoes: [
      { nome: "Cores em inglês", xp: 30 },
      { nome: "Monte a frase: My family", xp: 45 },
      { nome: "Bingo de animais", xp: 55 },
    ],
  },
  {
    slug: "outros", nome: "Artes e Música", icone: "🎨",
    c1: "#F0447C", c2: "#7A3DF0", sky: ["#FF7DB0", "#9D7BFF"],
    missoes: [
      { nome: "Quiz surpresa do dia", xp: 30 },
      { nome: "Arte: desenhe e ganhe", xp: 40 },
      { nome: "Música: complete o ritmo", xp: 45 },
    ],
  },
];

export const MATERIA_POR_SLUG: Record<string, Materia> = Object.fromEntries(
  MATERIAS.map((m) => [m.slug, m]),
);
