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
  pele?: string;
  cabelo?: string;
  cor_cabelo?: string;
  top?: string;
  camiseta?: string;
  baixo?: string;
  calca?: string;
  tenis?: string;
  chapeu?: string;
  costas?: string;
  aura?: string;
  mao?: string;
  pet?: string;
  veiculo?: string;
  /** legado (Cosmo astronauta) — não usado no avatar humanoide. */
  cor?: string;
  [slot: string]: unknown;
}

/** Um personagem-base (preset gratuito) — dobra como Partial<Avatar>. */
export interface PersonagemBase extends Partial<Avatar> {
  nome: string;
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

// ---------------------------------------------------------------------------
// Jogo — loop jogável (Fase 1). Espelha os schemas de backend/app/quest.
// O gabarito NUNCA chega ao cliente; a explicação só vem depois de responder.
// ---------------------------------------------------------------------------

/** Card de matéria (planeta) no Lobby, com o progresso da série do aluno. */
export interface MundoResumo {
  slug: string;
  nome: string;
  icone: string | null;
  total_missoes: number;
  concluidas: number;
  estrelas: number;
  proxima_missao_id: number | null;
}

/** Item do trilho de missões de um planeta (Lobby). */
export interface MissaoResumo {
  missao_id: number;
  nome: string;
  icone: string | null;
  xp_base: number;
  ordem: number;
  estrelas: number;     // melhor do próprio aluno (0–3)
  concluida: boolean;
  /** Progressão: true enquanto a missão anterior da trilha não foi concluída. */
  bloqueada: boolean;
}

/** Uma alternativa do quiz. */
export interface Opcao {
  id: string;
  texto: string;
  midia?: Record<string, unknown> | null;
}

/** Um desafio jogável — sem gabarito nem explicação. */
export interface DesafioJogavel {
  desafio_id: number;
  ordem: number;
  mecanica: string;
  dificuldade: number;
  bncc_codigo: string | null;
  enunciado: string;
  opcoes: Opcao[];
  midia?: Record<string, unknown> | null;
}

export interface MissaoJogavel {
  missao_id: number;
  nome: string;
  xp_base: number;
  versao: number;
  desafios: DesafioJogavel[];
}

/** Uma resposta que o cliente envia (só o id da opção escolhida). */
export interface RespostaEnvio {
  desafio_id: number;
  resposta: string;
}

export interface Correcao {
  desafio_id: number;
  correta: boolean;
  explicacao?: { texto?: string } | null;
}

/** Feedback imediato de UMA questão (acerto/erro) — não revela o gabarito. */
export interface ConferirResultado {
  correta: boolean;
  explicacao?: { texto?: string } | null;
}

/** Resultado da tentativa — correção + recompensa creditada + perfil novo. */
export interface Resultado {
  acertos: number;
  total: number;
  pct: number;
  estrelas: number;       // creditadas nesta jogada (0 em replay)
  xp_ganho: number;       // creditado ao total (0 em replay)
  moedas_ganhas: number;
  primeira_vez: boolean;
  correcoes: Correcao[];
  perfil: PerfilQuest;
}

/** Uma conquista de APRENDIZADO do aluno (derivada dos snapshots Matific/
 *  Elefante — o backend é a fonte da verdade; nada é concedido no cliente). */
export interface ConquistaAluno {
  codigo: string;
  nome: string;
  icone: string;
  descricao: string;
  criterio: string;       // frase pronta ("Leia 100 livros")
  limite: number;         // alvo do indicador (ex.: 100 livros)
  progresso: number;      // valor atual do indicador
  pct: number;            // 0..100 quando aplicável
  faltam: number;
  atingida: boolean;      // desbloqueada?
  data: string | null;    // ISO quando desbloqueada
  unidade: string;
}

/** Payload de GET /quest/conquistas — SÓ as conquistas do próprio aluno. */
export interface ConquistasDoAluno {
  aluno_id: number;
  nivel: number;
  xp: number;
  conquistas: ConquistaAluno[];
}
