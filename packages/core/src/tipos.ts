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
  turno: string | null;
  capacidade_maxima: number | null;
  observacoes: string | null;
  status: string;
  professor_nome: string | null;
  total_alunos: number;
}

/** Payload de criação/edição de turma (campos opcionais podem ir nulos). */
export interface TurmaPayload {
  nome: string;
  ano_escolar: string;
  ano_letivo: number;
  professor_id: number | null;
  turno: string | null;
  capacidade_maxima: number | null;
  observacoes: string | null;
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

// --- Fase 2: importações e plataformas ---------------------------------------

export interface Correspondencia {
  status: "exato" | "provavel" | "nao_encontrado";
  aluno_id: number | null;
  aluno_nome: string | null;
  similaridade: number | null;
  alternativas: { aluno_id: number; nome: string; similaridade: number }[];
}

export interface LinhaAnalise {
  numero: number;
  nome: string;
  dados: Record<string, unknown>;
  erros: string[];
  avisos: string[];
  correspondencia: Correspondencia | null;
}

export interface Analise {
  plataforma: string;
  formato: string;
  tipo: string;
  arquivo_token: string | null;
  arquivo_nome: string | null;
  /** Estratégia vencedora: tabela | cabecalho_vertical | rotulos | posicional */
  estrategia: string;
  /** Ex.: "Este arquivo pertence ao Matific." */
  mensagem_deteccao: string;
  total_alunos: number;
  total_linhas: number;
  total_erros: number;
  total_avisos: number;
  erros_gerais: string[];
  linhas: LinhaAnalise[];
}

export interface ResultadoImportacao {
  mensagem: string;
  importacao_id: number;
  qtd_alunos: number;
  qtd_erros: number;
  avisos: string[];
}

export interface Importacao {
  id: number;
  plataforma: string;
  tipo: string;
  arquivo_original: string | null;
  qtd_alunos: number;
  qtd_erros: number;
  tempo_ms: number;
  status: string;
  created_at: string;
  usuario_nome: string | null;
}

export interface MatificAluno {
  aluno_id: number;
  nome: string;
  turma: string | null;
  ano_escolar: string | null;
  atividades: number;
  estrelas: number;
  pontuacao_media: number;
  data_referencia: string | null;
}

export interface ElefanteAluno {
  aluno_id: number;
  nome: string;
  turma: string | null;
  ano_escolar: string | null;
  livros_unicos: number;
  tempo_leitura_min: number;
  questoes_tentativas: number;
  questoes_acertos: number;
  livros_por_nivel: Record<string, number>;
  data_referencia: string | null;
}

export interface Livro {
  id: number;
  titulo: string;
  autor: string | null;
  nivel_codigo: string;
  categoria: string | null;
  paginas: number | null;
  pontos: number;
  leituras: number;
}

export interface PaginaLivros {
  total: number;
  pagina: number;
  por_pagina: number;
  itens: Livro[];
}

// --- Multiplataforma: sincronizacao e notificacoes push ----------------------

export interface ItemEvolucaoResumo {
  posicao: number;
  aluno_id: number;
  nome: string;
  turma: string;
  nota_evolucao: number;
}

export interface AlertaPedagogico {
  tipo: string;
  gravidade: "alta" | "media" | "baixa";
  aluno_id: number;
  nome: string;
  turma: string;
  texto: string;
}

export interface EventoMural {
  tipo: string;
  icone: string;
  texto: string;
  data: string;
}

/** Pacote consolidado devolvido por GET /escolas/{id}/sincronizacao —
 *  uma unica viagem de rede para o mobile hidratar todas as telas. */
export interface PacoteSincronizacao {
  gerado_em: string;
  dashboard: Dashboard;
  ranking: RankingItem[];
  evolucao: ItemEvolucaoResumo[];
  alertas: AlertaPedagogico[];
  mural: EventoMural[];
}

export interface DispositivoRegistrado {
  id: number;
  plataforma: string;
}
