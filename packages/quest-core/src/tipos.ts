/**
 * Contrato TypeScript da API do Quest — espelha backend/app/quest/schemas.py.
 * O vocabulário interno segue docs/quest/README.md (a criança vê outro).
 */

export interface Figura {
  slug: string;
  nome: string;
  emoji: string;
}

/** Resposta do "É você?" — o mínimo para a criança se reconhecer. */
export interface Quem {
  primeiro_nome: string;
  apelido: string;
  avatar: Avatar;
}

export interface Avatar {
  cor?: string;
  [slot: string]: unknown;
}

export interface Preferencias {
  som?: boolean;
  musica?: boolean;
  narracao?: boolean;
  reduzir_animacoes?: boolean;
}

export interface PerfilQuest {
  id: number;
  apelido: string;
  codigo_amigo: string;
  nivel: number;
  xp_total: number;
  moedas: number;
  estrelas_total: number;
  sequencia_dias: number;
  avatar: Avatar;
  preferencias: Preferencias;
  primeiro_nome: string;
}

export interface SessaoQuest {
  access_token: string;
  token_type: string;
  perfil: PerfilQuest;
}

/** Situação de acesso de um aluno (tela do professor no Edu). */
export interface AcessoAluno {
  aluno_id: number;
  nome: string;
  apelido: string | null;
  codigo_login: string | null;
  ultimo_acesso: string | null;
  tem_credencial: boolean;
}
