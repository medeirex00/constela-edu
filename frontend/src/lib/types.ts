export interface Usuario {
  id: number;
  nome: string;
  email: string;
  cargo: string;
  is_global: boolean;
  escola_id: number | null;
}

export interface Escola {
  id: number;
  nome: string;
  cidade: string | null;
  estado: string | null;
  logotipo_url: string | null;
  ano_letivo_ativo: number;
  status: string;
}

export interface Aluno {
  id: number;
  nome: string;
  foto_url: string | null;
  numero_chamada: number | null;
  status: string;
  turma: string | null;
  ano_escolar: string | null;
}

export interface Turma {
  id: number;
  nome: string;
  ano_escolar: string;
  ano_letivo: number;
  professor_id: number | null;
}

export interface Professor {
  id: number;
  nome: string;
  email: string | null;
  observacoes: string | null;
}

export interface RankingItem {
  posicao: number;
  aluno_id: number;
  nome: string;
  turma: string | null;
  ano_escolar: string | null;
  nota_matific: number;
  nota_elefante: number;
  nota_geral: number;
}

export interface Dashboard {
  escola: Escola;
  total_alunos: number;
  total_turmas: number;
  total_professores: number;
  total_atividades: number;
  total_livros: number;
  tempo_leitura_min: number;
  media_geral: number;
  top10: RankingItem[];
}

export interface LinhaCalculo {
  indicador: string;
  valor: number;
  referencia: number;
  normalizado: number;
  peso: number;
  contribuicao: number;
}

export interface PerfilAluno {
  aluno: Aluno;
  nota_matific: number;
  nota_elefante: number;
  nota_geral: number;
  posicao: number | null;
  detalhes: {
    modo_normalizacao?: string;
    matific?: { indicadores: LinhaCalculo[]; nota: number };
    elefante?: { indicadores: LinhaCalculo[]; nota: number };
    geral?: { pesos: Record<string, number>; nota: number };
  };
  calculada_em: string | null;
}

export interface Pesos {
  namespace: string;
  valores: Record<string, number>;
  soma: number;
}

export interface Nivel {
  id: number;
  nome: string;
  codigos: string[];
  pontos_padrao: number;
  ordem: number;
}

export interface Dificuldade {
  niveis: Nivel[];
  series: { ano_escolar: string; pontos: Record<number, number> }[];
}

export interface Referencias {
  modo: "auto" | "manual";
  valores_manuais: Record<string, number>;
  valores_em_uso: Record<string, number>;
}

export interface PaginaAlunos {
  total: number;
  pagina: number;
  por_pagina: number;
  itens: Aluno[];
}
