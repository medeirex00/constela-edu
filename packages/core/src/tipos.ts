export interface Usuario {
  id: number;
  nome: string;
  email: string;
  /** Nome de usuário do login (estilo @), único na rede — opcional. */
  username?: string | null;
  cargo: string;
  is_global: boolean;
  escola_id: number | null;
  /** Rede/Secretaria à qual o usuário pertence (nulo = escola única). Habilita
   *  a visão da Secretaria (menu + /rede). */
  rede_id?: number | null;
  status?: string;
  ultimo_acesso?: string | null;
  created_at?: string | null;
  /** MÓDULOS contratados que valem para este usuário (SaaS): "leitura",
   *  "matematica", … Vem de /auth/me e do login; a interface se monta a partir
   *  dele (ver hooks/useModulos). Ausente = payload antigo ⇒ tudo ligado. */
  modulos?: string[];
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
  data_nascimento?: string | null;
  observacoes?: string | null;
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
  /** Alunos ativos do ano letivo da turma (número amigável exibido). */
  total_alunos: number;
  /** Matrículas cruas (qualquer ano/situação) — o que a exclusão enxerga. */
  total_matriculas: number;
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

/** As duas dimensões de desempenho (Arquitetura 2). Cada uma é medida na sua
 *  própria plataforma e NÃO é comparável com a outra: não existe ordem única
 *  entre elas. */
export type Dimensao = "leitura" | "matematica";

/** Desempenho do aluno em UMA dimensão.
 *
 *  `aferido: false` significa AUSÊNCIA de dado — `nota` e `posicao` vêm `null`
 *  e a tela mostra "—". Nunca 0: o zero fica reservado ao zero LEGÍTIMO (tem
 *  snapshot, ainda não produziu), que vem com `aferido: true` e `nota: 0`. */
export interface DesempenhoDimensao {
  dimensao: Dimensao | string;
  plataforma: string;
  contratada: boolean;
  aferido: boolean;
  nota: number | null;
  posicao: number | null;
  /** Denominador da posição ("8º de 21 aferidos em Leitura"). */
  n_aferidos: number;
  /** Data do snapshot que sustenta a nota — distingue nota baixa de nota velha. */
  snapshot_em: string | null;
  /** Indicadores brutos da própria dimensão (livros/tempo ou atividades/estrelas). */
  dados: Record<string, number>;
}

/** Cobertura do aluno: |D| / |P|. Fica AO LADO do desempenho, nunca somada. */
export interface AdocaoAluno {
  contratadas: string[];
  com_dados: string[];
  pct: number;
}

export interface RankingItem {
  posicao: number;
  aluno_id: number;
  nome: string;
  turma: string | null;
  ano_escolar: string | null;
  nota_matific: number;
  nota_elefante: number;
  /** LEGADO: composição entre dimensões. Não ordena mais nada. */
  nota_geral: number;
  /** DISCRIMINANTE das duas notas acima: `nota_matific`/`nota_elefante` chegam
   *  `0.0` tanto para quem NÃO tem snapshot da plataforma quanto para quem tem
   *  e ainda não produziu — e a lista legada (sem `?dimensao=`) traz os dois
   *  misturados, porque ela não corta por aferido.
   *
   *  Sem estes dois campos, o Top 10 do painel (web e app) não tem como mostrar
   *  "—" para o primeiro caso: ele exibe "0,0" e afirma que a criança foi
   *  medida em matemática quando ela nunca abriu o Matific.
   *
   *  `routers/rankings.py::_ranking` carimba os dois em TODO item, inclusive na
   *  rota legada, a partir das colunas `Nota.aferido_*` (existência do snapshot,
   *  nunca `nota > 0`). São opcionais só por compatibilidade: contra um servidor
   *  ANTERIOR ao carimbo eles vêm `undefined`, e `notaDaMateria` mantém o
   *  comportamento de exibir o número em vez de inventar uma ausência. */
  aferido_leitura?: boolean | null;
  aferido_matematica?: boolean | null;
  // --- Preenchidos quando a rota é chamada com `?dimensao=` ------------------
  dimensao?: Dimensao | string | null;
  /** Nota DAQUELA dimensão. Quem não é aferido não entra na lista. */
  nota?: number | null;
  aferido?: boolean | null;
  n_aferidos?: number | null;
  dados?: Record<string, number>;
  snapshot_em?: string | null;
  /** Cobertura do aluno (0–100), ao lado do desempenho — nunca somada a ele. */
  adocao?: number | null;
  /** TURNO da turma do aluno (`Turma.turno` cru: manha|tarde|noite|integral|null).
   *  Preenchido no ranking de leitura POR TURNO; a série (`ano_escolar`) segue
   *  sendo só informação exibida ao lado — nunca entra na nota. */
  turno?: string | null;
}

/** Um turno e o ranking de leitura dos alunos DAQUELE turno — a competição
 *  escolar oficial, dividida por `Turma.turno` (descoberto do banco). Dentro de
 *  cada turno competem TODOS os alunos do 1º ao 5º ano juntos, pela mesma
 *  `nota_elefante` (régua única da escola). A posição reinicia em 1 por turno. */
export interface RankingTurno {
  turno: string | null;
  turno_rotulo: string;
  total: number;
  alunos: RankingItem[];
}

/** Aluno SEM dado numa dimensão — visão OPERACIONAL, não competitiva: sem nota
 *  e sem posição de propósito. */
export interface AlunoNaoAferido {
  aluno_id: number;
  nome: string;
  turma: string | null;
  ano_escolar: string | null;
}

export interface DimensaoNaoAferida {
  dimensao: string;
  plataforma: string;
  n_aferidos: number;
  total: number;
  alunos: AlunoNaoAferido[];
}

export interface NaoAferidos {
  contratadas: string[];
  total_alunos: number;
  dimensoes: DimensaoNaoAferida[];
  /** Sem dado em NENHUMA dimensão contratada: adoção 0%. */
  sem_nenhuma: AlunoNaoAferido[];
}

export interface Dashboard {
  escola: Escola;
  total_alunos: number;
  total_turmas: number;
  total_professores: number;
  total_atividades: number;
  total_livros: number;
  tempo_leitura_min: number;
  /** Desempenho por DIMENSÃO — cada média só sobre quem TEM dado da plataforma,
   *  com o seu próprio denominador ao lado. */
  media_leitura?: number;
  alunos_com_dado_leitura?: number;
  media_matematica?: number;
  alunos_com_dado_matematica?: number;
  /** Média das dimensões COM DADO. Mantida por compatibilidade; não ordena. */
  media_geral: number;
  /** Cobertura: % com dado de ALGUMA plataforma contratada. */
  alcance?: number;
  /** Quantos não têm dado de nenhuma — a lista de ação da coordenação. */
  nao_aferidos?: number;
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

export interface FaixaLeitura {
  codigo: string;
  nome: string;
  quantidade: number;
  pontos_por_livro: number;
  pontos: number;
  percentual: number;
}

export interface LeituraNiveis {
  faixas: FaixaLeitura[];
  total_livros: number;
  pontos_dificuldade: number;
  faixa_predominante: string | null;
}

export interface PerfilAluno {
  aluno: Aluno;
  nota_matific: number;
  nota_elefante: number;
  /** LEGADO: composição entre dimensões — `dimensoes` é a fonte oficial. */
  nota_geral: number;
  posicao: number | null;
  /** Desempenho por dimensão contratada (a verdade oficial) + a cobertura. */
  dimensoes?: DesempenhoDimensao[];
  adocao?: AdocaoAluno | null;
  detalhes: {
    modo_normalizacao?: string;
    matific?: { indicadores: LinhaCalculo[]; nota: number };
    elefante?: { indicadores: LinhaCalculo[]; nota: number };
    /** LEGADO: a equação que compunha as dimensões. `legado: true` no motor. */
    geral?: { pesos: Record<string, number>; nota: number; legado?: boolean };
  };
  calculada_em: string | null;
  leitura_niveis?: LeituraNiveis | null;
  // Ficha cadastral da planilha de matrículas — só chega preenchida ao gestor.
  ficha?: Record<string, string>;
}

export interface Pesos {
  namespace: string;
  valores: Record<string, number>;
  soma: number;
}

export interface Nivel {
  id: number;
  nome: string;
  codigo?: string | null;
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

/** Uma leitura no histórico do aluno (relatório individual do Elefante). */
export interface LeituraHistorico {
  id: number;
  livro: string;
  nivel: string;
  categoria: string | null;
  plataforma: string;
  data: string; // ISO "AAAA-MM-DDTHH:MM:SS" (ou só a data quando sem horário)
  tempo_leitura_min: number | null;
  pontos: number;
}

/** Resposta do histórico de leituras filtrado por período. */
export interface HistoricoLeituras {
  periodo: { chave: string; rotulo: string; inicio: string | null; fim: string | null };
  resumo: { total_livros: number; pontos: number; tempo_total_min: number };
  itens: LeituraHistorico[];
}

/** Item do ranking de leitura por período (livros/pontos/tempo no intervalo). */
export interface RankingLeituraItem {
  posicao: number;
  aluno_id: number;
  nome: string;
  turma: string | null;
  ano_escolar: string | null;
  livros: number;
  pontos: number;
  tempo_leitura_min: number;
}

/** Ranking de Matemática por período (estrelas/atividades do Matific). */
export interface RankingMatematicaItem {
  posicao: number;
  aluno_id: number;
  nome: string;
  turma: string | null;
  ano_escolar: string | null;
  estrelas: number;
  atividades: number;
  pontuacao_media: number;
}

/** Um colocado no pódio de uma premiação. */
export interface PodioItem {
  posicao: number;
  aluno_id: number;
  nome: string;
  turma: string | null;
  valor: number;
}

/** Uma categoria de premiação (com o pódio do período). */
export interface CategoriaPremiacao {
  chave: string;
  titulo: string;
  icone: string;
  descricao: string;
  unidade: string;
  podio: PodioItem[];
}

/** Premiações da escola calculadas exclusivamente no período escolhido. */
export interface Premiacoes {
  periodo: { chave: string; rotulo: string; inicio: string | null; fim: string | null };
  categorias: CategoriaPremiacao[];
}

/** Aluno no painel de gestão da turma — com nota, posição e data de cadastro. */
export interface AlunoGestao {
  id: number;
  nome: string;
  foto_url: string | null;
  numero_chamada: number | null;
  status: string;
  turma: string | null;
  ano_escolar: string | null;
  created_at: string | null;
  /** LEGADO (composição entre dimensões): não ordena mais nada. */
  nota_geral: number | null;
  posicao: number | null;
  /** Por DIMENSÃO — `null` quando não aferido (a tela mostra "—"), nunca 0. */
  nota_leitura?: number | null;
  nota_matematica?: number | null;
  aferido_leitura?: boolean;
  aferido_matematica?: boolean;
  posicao_leitura?: number | null;
  posicao_matematica?: number | null;
}

// --- Fase 2: importações e plataformas ---------------------------------------

export interface Correspondencia {
  // Motor único (prévia = confirmação): "vinculado" (vincula automático),
  // "revisar" (possível duplicata — o gestor decide), "bloqueado" (conflito de
  // identidade). "exato"/"provavel"/"nao_encontrado" = casamento por nome (fallback
  // fora da turma) mantidos por compatibilidade.
  status: "vinculado" | "revisar" | "bloqueado"
    | "exato" | "provavel" | "nao_encontrado";
  aluno_id: number | null;
  aluno_nome: string | null;
  similaridade: number | null;
  motivo?: string;   // uuid|identificador|exato|abreviacao|parcial|variante|typo|conflito
  alternativas: { aluno_id: number; nome: string; turma?: string; similaridade: number }[];
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
  /** Turma lida do cabeçalho do PDF (relatórios do Elefante). */
  turma_detectada: string;
  /** Como o nome foi identificado: "arquivo" | "conteudo" | "nenhum" | "". */
  origem_nome: string;
  /** "Intervalo de datas" do relatório (Matific), ISO "AAAA-MM-DD" ou "". */
  periodo_inicio?: string;
  periodo_fim?: string;
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
  /** LEGADO: a ordem única de crescimento. */
  nota_evolucao: number;
  /** Crescimento por DIMENSÃO na janela — `null` = não aferido nela. */
  notas?: Partial<Record<Dimensao, number | null>>;
  posicao_dimensao?: Partial<Record<Dimensao, number | null>>;
  n_aferidos?: Partial<Record<Dimensao, number>>;
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
  /** LEGADO: ordem única por nota geral. */
  ranking: RankingItem[];
  /** Uma lista POR MATÉRIA contratada — só os alunos aferidos em cada uma.
   *  Viaja junto para que o app OFFLINE nunca precise compor nota nenhuma
   *  localmente (compor entre matérias é o que a Arquitetura 2 elimina). */
  ranking_por_dimensao?: Partial<Record<Dimensao, RankingItem[]>>;
  evolucao: ItemEvolucaoResumo[];
  alertas: AlertaPedagogico[];
  mural: EventoMural[];
}

export interface DispositivoRegistrado {
  id: number;
  plataforma: string;
}
