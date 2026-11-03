/**
 * Tipos da VISÃO GERAL da escola (identidade visual v2, referência 1).
 *
 * Contratos EXATOS das rotas que a tela consome (todas só de leitura):
 *   GET /escolas/{id}/visao-geral?periodo=bimestre   → VisaoGeral
 *       (backend/app/schemas/visao_geral.py — VisaoGeralOut)
 *   GET /escolas/{id}/atividade-semanal?semanas=8    → AtividadeSemanal
 *       (backend/app/schemas/visao_geral.py — AtividadeSemanalOut)
 *   GET /escolas/{id}/resumo-escola                  → ResumoEscolaPainel
 *       (backend/app/services/evolucao.py — resumo_escola / _monta_resumo_turma; só gestão)
 *   GET /escolas/{id}/gamificacao/mural              → MuralEscola
 *       (backend/app/services/gamificacao.py — mural; só gestão da própria escola)
 *
 * AUSÊNCIA NÃO É ZERO: todo `null` destas respostas quer dizer "sem coleta / sem
 * medida" e a tela mostra isso por extenso, nunca como 0.
 */

/** Cobertura do Matific no período (a mesma semântica do Relatório por Período). */
export type CoberturaMatematica = "completa" | "parcial" | "sem_dado";

export interface PeriodoVisaoGeral {
  /** Preset pedido (ex.: "bimestre"). */
  chave: string;
  /** Rótulo do backend, ex.: "4º bimestre (05/10 a 31/12)". */
  rotulo: string;
  /** AAAA-MM-DD */
  inicio: string;
  /** AAAA-MM-DD */
  fim: string;
  /** Dias do início até min(hoje, fim), contando hoje (0..dias_total). */
  dias_decorridos: number;
  dias_total: number;
}

/** A MESMA quantidade de dias desde o início do período anterior (decisão D6). */
export interface ComparacaoVisaoGeral {
  /** Ex.: "mesmo ponto do 3º bimestre". */
  rotulo: string;
  inicio: string;
  fim: string;
}

export interface VisaoGeral {
  periodo: PeriodoVisaoGeral;
  /** `null` = não há anterior equivalente (ou as janelas não estão medidas). */
  comparacao: ComparacaoVisaoGeral | null;
  alunos: {
    /** Coorte: alunos ativos matriculados no ano letivo (recorte do professor). */
    total: number;
    /** União dos ativos nas plataformas contratadas e com dado. */
    ativos: number | null;
    ativos_anterior: number | null;
    ativos_leitura: number | null;
    ativos_matematica: number | null;
  };
  leitura: {
    contratado: boolean;
    livros: number | null;
    livros_anterior: number | null;
    tempo_min: number | null;
    tempo_min_anterior: number | null;
    /** "parcial" = a última coleta do Elefante é anterior à véspera do fim do período
     *  (ou de hoje): o número conta só até `coletado_ate`. Opcional: API anterior. */
    cobertura?: CoberturaMatematica;
    /** AAAA-MM-DD (Brasília): último dia já coletado do Elefante para esses alunos. */
    coletado_ate?: string | null;
  };
  matematica: {
    contratado: boolean;
    atividades: number | null;
    atividades_anterior: number | null;
    cobertura: CoberturaMatematica;
  };
  /** ISO 8601 com fuso (UTC): a coleta MAIS ATRASADA entre as fontes contratadas. */
  atualizado_em: string | null;
}

export interface SemanaAtividade {
  /** Segunda-feira (AAAA-MM-DD). */
  inicio: string;
  /** Domingo (AAAA-MM-DD). */
  fim: string;
  leitura_alunos: number | null;
  /** round(alunos / denominador × 100, 1); `null` = semana sem coleta (lacuna). */
  leitura_pct: number | null;
  matematica_alunos: number | null;
  matematica_pct: number | null;
}

export interface AtividadeSemanal {
  /** Base do percentual: alunos ativos matriculados no ano (recorte do professor). */
  denominador: number;
  leitura_contratado: boolean;
  matematica_contratado: boolean;
  /** Texto do backend com a regra de "aluno ativo na semana". */
  observacao: string;
  /** Em ordem cronológica; a última contém hoje (em curso). */
  semanas: SemanaAtividade[];
}

/** Uma turma de `/resumo-escola` (só os campos que a Visão Geral usa). */
export interface ResumoTurmaPainel {
  turma: { id: number; nome: string; ano_escolar: string | null };
  total_alunos: number;
  /** Acumulado do ano (último retrato de cada aluno). */
  indicadores: {
    livros_unicos?: number;
    tempo_leitura_min?: number;
    atividades?: number;
    estrelas?: number;
    pontuacao_media?: number;
    [chave: string]: number | undefined;
  };
  n_leitura?: number;
  n_matematica?: number;
  contratadas?: string[];
  /** Média, entre as plataformas contratadas, da % de alunos da turma com dado. */
  adocao?: number;
  adocao_leitura?: number;
  adocao_matematica?: number;
  /** % de alunos da turma com dado de ALGUMA plataforma contratada. */
  alcance?: number;
}

export interface ResumoEscolaPainel {
  escola: { id: number; nome: string };
  turmas: ResumoTurmaPainel[];
}

/** Evento do mural: hoje, só conquistas desbloqueadas nos últimos 30 dias. */
export interface EventoMural {
  tipo: string;
  /** Emoji da conquista (enfeite; o texto diz tudo). */
  icone: string;
  /** Ex.: "Ana Souza desbloqueou “Leitor de Bronze”". */
  texto: string;
  /** Data da COLETA que registrou a conquista (UTC, sem sufixo), não o instante real. */
  data: string;
}

export interface MuralEscola {
  destaques: Record<"dia" | "semana" | "mes", unknown>;
  eventos: EventoMural[];
}
