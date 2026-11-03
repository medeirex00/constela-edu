/**
 * Tipos da tela de Critérios de pontuação (/metricas) e das telas que mostram a
 * régua da nota. Ficam aqui (e não em lib/types) porque são do contrato de uma
 * rota só: GET /escolas/{id}/configuracoes/pontuacao/regra
 * (backend/app/routers/configuracoes.py::regra_da_pontuacao).
 */

/** Régua de pontuação da escola (GET /configuracoes/perfil-scoring → modo). */
export type ModoRegua = "institucional" | "personalizado";

/** Uma matéria da régua, como o MOTOR a aplica nesta escola. */
export interface DimensaoRegra {
  dimensao: "leitura" | "matematica";
  plataforma: string;
  /** A matéria faz parte do plano da rede? Sem ela não há nota daquela matéria. */
  contratada: boolean;
  /** Pesos EFETIVOS (percentuais) de cada indicador da nota da matéria. */
  pesos: Record<string, number>;
  /** Só na Leitura: tentativas × acertos dentro do indicador "questões". */
  subpesos_questoes?: Record<string, number>;
}

/** A regra da nota desta escola — a fonte única dos pesos que a tela mostra. */
export interface RegraPontuacao {
  perfil: ModoRegua;
  versoes: { composicao: string; dificuldade: string; dificuldade_da_rede: string };
  dimensoes: DimensaoRegra[];
  /** LEGADO: pesos da Nota Geral (ordena o Ranking Geral, o certificado "Geral" e as vitrines). */
  nota_geral: { pesos: Record<string, number> };
  normalizacao: {
    modo: "auto" | "manual";
    percentil_referencia: number;
    minimo_alunos_percentil: number;
    indicadores_volume: string[];
  };
}

/** Pesos efetivos por matéria, como a explicação "Como funciona?" os recebe. */
export interface PesosDaRegua {
  leitura?: Record<string, number> | null;
  matematica?: Record<string, number> | null;
}
