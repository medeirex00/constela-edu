/**
 * Contrato TypeScript da API do Quest — espelha backend/app/quest/schemas.py.
 * O vocabulário interno segue docs/quest/README.md (a criança vê outro).
 */

/** Resposta do "É você?" — o mínimo para a criança se reconhecer. */
export interface Quem {
  nome: string;
  apelido: string;
  avatar: Avatar;
}

export interface Avatar {
  cor?: string;
  rosto?: string;
  chapeu?: string;
  costas?: string;
  mao?: string;
  pet?: string;
  veiculo?: string;
  [slot: string]: unknown;
}

/** Catálogo do vestiário: opções válidas por slot (whitelist do backend). */
export interface Aparencia {
  cor: string[];
  rosto: string[];
  chapeu: string[];
  costas: string[];
  mao: string[];
  pet: string[];
  veiculo: string[];
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
  /** Como a criança pediu para ser chamada ("" = cerimônia pendente). */
  nome_exibicao: string;
  /** Nome usado nas falas (nome_exibicao ou primeiro nome do cadastro). */
  nome: string;
  /** Dias desde o último login — alimenta a saudação com memória. */
  dias_sem_jogar: number;
  /** Código do próprio cartão — alimenta o "Quem vai jogar?" do aparelho. */
  codigo_login: string;
}

export interface SessaoQuest {
  access_token: string;
  token_type: string;
  /** Primeiro login da credencial — o app abre a cerimônia de boas-vindas. */
  primeira_vez: boolean;
  perfil: PerfilQuest;
}

/** Situação de acesso de um aluno (tela do professor no Edu). */
export interface AcessoAluno {
  aluno_id: number;
  nome: string;
  nome_exibicao: string | null;
  apelido: string | null;
  codigo_login: string | null;
  ultimo_acesso: string | null;
  tem_credencial: boolean;
}

/** Astronauta que já entrou neste aparelho ("Quem vai jogar?"). */
export interface AstronautaConhecido {
  codigo: string;
  nome: string;
  cor: string;
}
