/**
 * Situação de uma integração (Matific / Elefante Letrado) na linguagem da
 * escola: um rótulo curto (badge) + uma frase que diz o que fazer.
 *
 * Deriva SOMENTE do que GET /escolas/{id}/sync/status já devolve — nada é
 * inventado: campo ausente não vira número nem estado. Os campos de cobertura
 * (alunos_com_dados, alunos_sem_dados, alunos_com_zero_registros,
 * dado_mais_recente_em), os de frescor/falha (frescor, idade_horas,
 * falha_categoria, ultima_tentativa, fila_parada) e os do contrato da etapa 2
 * (ultima_verificacao_em, ultimo_status, ultimo_motivo, recalculo_pendente,
 * periodo_um_dia_permitido; na execução: qtd_linhas, qtd_em_revisao,
 * qtd_falhas, recalculo_pendente, motivo, periodo) são OPCIONAIS — sem eles, a
 * regra cai no que a resposta antiga já trazia.
 *
 * Estados distintos (e "falhou" nunca vira "atualizado"): Atualizado,
 * Atualizado em parte (coleta parcial), Verificado em parte (coleta parcial
 * sem aluno aplicado), Verificado: nada mudou, Sem
 * atualização: correspondência pendente, Sem atualização: nenhuma conta da
 * escola reconhecida (tudo em revisão), Sem dados na última coleta, Dados
 * desatualizados (com a idade), Falhou — por acesso recusado × plataforma fora
 * do ar/bloqueando × erro ao processar, com o código traduzido —, Nova
 * tentativa pendente (sem esconder a falha anterior), Coleta indisponível neste
 * servidor, Sincronizando, Conexão não validada, Ainda não configurada, Sem
 * dados ainda.
 */
import { dataHora } from "../lib/formato";

// --- Tipos (espelham app/sync/schemas.py) ----------------------------------
/** Período pedido numa execução (dos ``parametros``), quando houver. */
export interface PeriodoExecucao {
  inicio: string | null;
  fim: string | null;
}

export interface Execucao {
  id: number; plataforma: string; origem: string; status: string;
  iniciada_em: string | null; finalizada_em: string | null; duracao_ms: number;
  /** Contrato novo: ALUNOS DISTINTOS com dado novo/alterado aplicado. Em
   *  execuções antigas (sem ``qtd_linhas``) era a soma por arquivo. */
  qtd_alunos: number; qtd_turmas: number; qtd_arquivos: number; qtd_erros: number;
  tentativa: number; erro_resumo: string | null; conector_versao?: string | null;
  parser_versao?: string | null; created_at?: string;
  qtd_alteracoes?: number;
  // --- Contrato da etapa 2 (migração 0039): opcionais e anuláveis ----------
  /** Linhas recebidas da plataforma. ``null``/ausente = execução antiga. */
  qtd_linhas?: number | null;
  /** Contas distintas enviadas à revisão de identidade. */
  qtd_em_revisao?: number | null;
  /** Unidades (turma, lote, aluno, endpoint) que falharam. */
  qtd_falhas?: number | null;
  /** Dado gravado, mas o recálculo das notas falhou. */
  recalculo_pendente?: boolean | null;
  /** nada_mudou | correspondencia_pendente | tudo_em_revisao | queda_retida |
   *  linhas_descartadas | falha_apos_gravacao | coleta_parcial | código do erro. */
  motivo?: string | null;
  periodo?: PeriodoExecucao | null;
}

/** Tipo da falha que explica o estado (backend: router._categoria_falha). */
export type CategoriaFalha =
  | "autenticacao" | "indisponibilidade_externa" | "processamento" | "indisponivel"
  | "configuracao";

export interface PlataformaStatus {
  plataforma: string; estrategia: string; conectada: boolean;
  /** nao_configurada | nao_validada | valida | invalida | expirada | ilegivel (a senha
   *  salva não abre mais com a chave do servidor: só o recadastro resolve). */
  credencial_status: string; validada_em: string | null; ultimo_erro: string | null;
  agendada: boolean; cadencia: string; hora_local: string; dia_semana: number | null;
  proxima_execucao: string | null; ultima_execucao: Execucao | null;
  /** Último DADO APLICADO (execução concluída ou parcial). */
  ultimo_sucesso_em: string | null; desatualizada: boolean;
  /** A última TENTATIVA que terminou (concluída / parcial / sem atualização /
   *  sem dados / erro) — opcional. */
  ultima_tentativa?: Execucao | null;
  /** Frescor do DADO (último sucesso): atualizado | desatualizado | sem_sucesso. */
  frescor?: "atualizado" | "desatualizado" | "sem_sucesso" | null;
  idade_horas?: number | null;
  limite_horas?: number | null;
  falha_categoria?: CategoriaFalha | null;
  /** A execução mais recente está na fila de um agendador desligado. */
  fila_parada?: boolean;
  /** Cobertura (opcionais — o backend pode não informar; nunca inventar).
   *  ``null`` = o backend não conseguiu contar (≠ 0). */
  alunos_com_dados?: number | null;
  alunos_sem_dados?: number | null;
  alunos_com_zero_registros?: number | null;
  dado_mais_recente_em?: string | null;
  // --- Contrato da etapa 2: opcionais ---------------------------------------
  /** Última VERIFICAÇÃO (concluída, parcial, nada mudou ou sem dados). */
  ultima_verificacao_em?: string | null;
  /** Status e motivo da última tentativa terminada. */
  ultimo_status?: string | null;
  ultimo_motivo?: string | null;
  /** Há dado gravado que ainda não entrou nas notas/rankings. */
  recalculo_pendente?: boolean | null;
  /** O servidor aceita coletar o Matific de UM dia só (início = fim)? */
  periodo_um_dia_permitido?: boolean | null;
}

export interface EscolaStatus {
  escola_id: number; escola_nome: string; qtd_alunos: number; qtd_turmas: number;
  plataformas: PlataformaStatus[]; alertas_abertos: number;
  lista_piloto_importada: boolean; integracao_configurada: boolean;
  /** Linhas de relatório sem aluno correspondente nos últimos 30 dias (opcional). */
  pendencias_correspondencia_30d?: number;
  /** O agendador automático está ligado no servidor? (opcional) */
  agendador_ativo?: boolean;
}

export const NOME_PLATAFORMA: Record<string, string> = {
  matific: "Matific",
  elefante: "Elefante Letrado",
};

// Tipos de alerta do backend (app/sync/service.py, ALERTA_POR_CODIGO) → rótulo
// para a escola.
export const TIPO_ALERTA: Record<string, string> = {
  senha_invalida: "Senha inválida",
  senha_expirada: "Senha expirada",
  // A senha SALVA não abre com as chaves do servidor (não é recusa da plataforma).
  credencial_ilegivel: "Senha salva ilegível",
  falha_autenticacao: "Falha no acesso",
  falha_auth: "Falha no acesso",
  mfa: "Verificação em duas etapas",
  pagina_login: "Página de login não abriu",
  captcha: "Bloqueio anti-robô da plataforma",
  erro_navegador: "A plataforma não respondeu",
  sem_escola: "Escola não localizada na plataforma",
  sem_acesso_ao_dado: "Sem acesso aos dados",
  falha_download: "Falha ao baixar o relatório",
  timeout: "Demorou demais",
  erro_inesperado: "Erro ao processar",
  plataforma_indisponivel: "Coleta indisponível neste servidor",
  parser_incompativel: "Formato do relatório mudou",
  desatualizada: "Dados desatualizados",
  interrompida: "Sincronização interrompida",
  lento: "Sincronização lenta",
  queda_matific: "Total menor que o gravado (revisar)",
  coleta_parcial: "Coleta parcial",
  correspondencia_pendente: "Correspondência pendente",
  plataforma_sem_dados: "A plataforma não trouxe dados",
  recalculo_pendente: "Recálculo pendente",
  // Matific (Placar do ano) e Elefante (relatórios de turma da coleta completa).
  contas_ausentes: "Contas vinculadas ausentes na coleta",
  // Escola EXTERNA (backend: app/sync/escola_externa.py).
  conta_multiescola: "A conta enxerga mais de uma escola",
  escola_externa_trocada: "A conta é de outra escola",
  escola_externa_em_outra_escola: "Escola da plataforma já usada por outra escola",
  escola_nao_identificada: "Escola da conta não identificada",
  contas_de_outra_escola: "Todas as contas são de outra escola",
  identidade_de_outra_escola: "Contas já vinculadas a outra escola",
  periodo_invalido: "Período inválido",
  escola_sem_responsavel: "Escola sem administrador ou coordenador ativo",
};
export const rotuloAlerta = (tipo: string) => TIPO_ALERTA[tipo] ?? tipo.replace(/_/g, " ");

// Alertas que NÃO explicam uma falha de execução (são avisos de estado/revisão).
const ALERTAS_NAO_FALHA = new Set([
  "desatualizada", "lento", "queda_matific",
  "coleta_parcial", "correspondencia_pendente", "plataforma_sem_dados", "recalculo_pendente",
  "contas_ausentes", "identidade_de_outra_escola",
]);

// Categoria por tipo de alerta — o mesmo mapa do backend (service.CATEGORIA_POR_TIPO),
// usado quando a resposta não traz ``falha_categoria``.
const CATEGORIA_POR_TIPO: Record<string, CategoriaFalha> = {
  senha_invalida: "autenticacao", senha_expirada: "autenticacao",
  falha_autenticacao: "autenticacao", falha_auth: "autenticacao", mfa: "autenticacao",
  sem_acesso_ao_dado: "autenticacao",
  pagina_login: "indisponibilidade_externa", captcha: "indisponibilidade_externa",
  erro_navegador: "indisponibilidade_externa", sem_escola: "indisponibilidade_externa",
  falha_download: "indisponibilidade_externa", timeout: "indisponibilidade_externa",
  interrompida: "processamento", erro_inesperado: "processamento",
  parser_incompativel: "processamento",
  plataforma_indisponivel: "indisponivel",
  conta_multiescola: "autenticacao", escola_externa_trocada: "autenticacao",
  escola_externa_em_outra_escola: "autenticacao", escola_nao_identificada: "processamento",
  contas_de_outra_escola: "autenticacao",
  periodo_invalido: "configuracao",
  credencial_ilegivel: "configuracao",
  escola_sem_responsavel: "configuracao",
};

// --- Resultado de uma execução (contrato comum da etapa 2) -------------------
/** Status em que a execução TERMINOU (as demais estão na fila/rodando/canceladas). */
export const STATUS_TERMINAIS: ReadonlySet<string> = new Set([
  "concluida", "parcial", "sem_atualizacao", "sem_dados", "erro",
]);

/** Códigos de erro do contrato → rótulo e frase para a escola. */
export const CODIGO_ERRO: Record<string, { rotulo: string; frase: string; categoria: CategoriaFalha }> = {
  sem_acesso_ao_dado: {
    rotulo: "Sem acesso aos dados",
    categoria: "autenticacao",
    frase:
      "A plataforma recusou o acesso ao relatório (a conta entrou, mas não pôde ler os dados). Confira se esta conta ainda enxerga as turmas da escola; se continuar, envie o relatório manualmente.",
  },
  falha_download: {
    rotulo: "Falha ao baixar o relatório",
    categoria: "indisponibilidade_externa",
    frase:
      "A plataforma respondeu com erro ao entregar o relatório. Tente de novo mais tarde; se continuar, envie o relatório manualmente.",
  },
  timeout: {
    rotulo: "Demorou demais",
    categoria: "indisponibilidade_externa",
    frase:
      "A coleta passou do tempo máximo e foi interrompida. Tente de novo mais tarde; se continuar, envie o relatório manualmente.",
  },
  parser_incompativel: {
    rotulo: "Formato do relatório mudou",
    categoria: "processamento",
    frase:
      "O relatório chegou num formato que o Constela não reconhece (a plataforma pode ter mudado os campos). Avise o suporte; enquanto isso, envie o relatório manualmente.",
  },
  // Escola EXTERNA: a coleta não sabe, com segurança, de qual escola da
  // plataforma são os dados — nada foi aplicado.
  conta_multiescola: {
    rotulo: "A conta enxerga mais de uma escola",
    categoria: "autenticacao",
    frase:
      // O vínculo da escola externa é gravado SÓ pelo Admin Global (PUT
      // /sync/escola-externa): a coordenação confere no "Testar conexão" e pede.
      "A conta cadastrada enxerga mais de uma escola na plataforma e nada foi aplicado. O Admin Global escolhe qual delas é esta escola (vínculo da escola externa): o “Testar conexão” mostra as escolas da conta para você informar a ele.",
  },
  escola_externa_trocada: {
    rotulo: "A conta é de outra escola",
    categoria: "autenticacao",
    frase:
      "A conta cadastrada não enxerga a escola da plataforma vinculada a esta escola e nada foi aplicado. Confira se a credencial é desta escola; se a escola trocou de conta de propósito, peça ao Admin Global para refazer o vínculo da escola externa.",
  },
  escola_externa_em_outra_escola: {
    rotulo: "Escola da plataforma já usada por outra escola",
    categoria: "autenticacao",
    frase:
      "A conta cadastrada lê uma escola da plataforma que já alimenta outra escola do Constela e nada foi aplicado. Confira se a credencial cadastrada é desta escola.",
  },
  escola_nao_identificada: {
    rotulo: "Escola da conta não identificada",
    categoria: "processamento",
    frase:
      "A resposta da plataforma não disse de qual escola são os dados e nada foi aplicado (a plataforma pode ter mudado). Tente de novo; se continuar, avise o suporte e envie o relatório manualmente.",
  },
  // D8 (LGPD): sem vínculo da escola externa, TODAS as contas da coleta já são de
  // alunos de outra escola do Constela — nada foi gravado, nem pendência com nome.
  contas_de_outra_escola: {
    rotulo: "Todas as contas são de outra escola",
    categoria: "autenticacao",
    frase:
      "Todas as contas desta coleta já estão vinculadas a alunos de outra escola do Constela e nada foi gravado (nem fichas, nem números, nem pendências com os nomes). Confira se a credencial cadastrada é desta escola. Se as crianças são mesmo daqui, o Admin Global grava o vínculo da escola externa e confirma as contas em Revisão de identidade.",
  },
  // O PEDIDO não é aceito (não é falha da plataforma, da senha nem nossa).
  periodo_invalido: {
    rotulo: "Período inválido",
    categoria: "configuracao",
    frase:
      "O período pedido não é aceito (datas inválidas, fim antes do início ou um dia só) e os dados dele não foram gravados. Ajuste as datas e peça a coleta de novo.",
  },
  // A senha SALVA não abre com as chaves do servidor (chave trocada sem recifrar):
  // a plataforma não recusou nada e a credencial não foi marcada inválida.
  credencial_ilegivel: {
    rotulo: "Senha salva ilegível",
    categoria: "configuracao",
    frase:
      "A senha salva não pôde ser lida pelo servidor (a chave que a protegia foi trocada) e nada foi coletado. Informe usuário e senha de novo em “Configurar conexão” e clique em “Salvar e validar”; se já fez isso, peça a sincronização de novo.",
  },
  // A importação automática precisa de um usuário ativo da escola que a assine.
  escola_sem_responsavel: {
    rotulo: "Escola sem administrador ou coordenador ativo",
    categoria: "configuracao",
    frase:
      "A escola não tem administrador nem coordenador ativo para assinar a importação automática, e nada foi coletado. Cadastre ou reative um em Usuários e peça a sincronização de novo.",
  },
};

/** Motivos de uma execução sem falha (contrato) → texto curto. */
export const MOTIVO_EXECUCAO: Record<string, string> = {
  nada_mudou: "nada mudou",
  correspondencia_pendente: "correspondência pendente",
  // Tudo em revisão e NENHUMA conta da escola conferida: não conta como em dia
  // (credencial de outra escola, casamento quebrado ou 1ª coleta sem vínculo).
  tudo_em_revisao: "nenhuma conta da escola reconhecida",
  falha_apos_gravacao: "falhou depois de gravar",
  // Linhas que chegaram com defeito (sem data, sem nome) e não viraram dado.
  linhas_descartadas: "linhas com defeito descartadas",
  // Total do Matific MENOR que o gravado: o valor ficou retido (alerta
  // "Total menor que o gravado"); não há revisão de identidade a fazer.
  queda_retida: "total menor retido para conferência",
  // Tempo e/ou questões do Elefante sumiram da resposta: ficaram os números de
  // antes. O motivo não diz QUAIS campos (o alerta crítico diz).
  campos_nao_atualizados: "tempo ou questões não vieram da plataforma",
};

/** A última TENTATIVA que terminou: o backend novo informa; no antigo, a
 *  última execução é ela quando já terminou. */
export function ultimaTentativa(p: PlataformaStatus): Execucao | null {
  const exec = p.ultima_execucao;
  if (p.ultima_tentativa !== undefined) return p.ultima_tentativa;
  return exec && exec.status !== "fila" && exec.status !== "executando" && exec.status !== "cancelada"
    ? exec : null;
}

/** Status e motivo da última tentativa terminada. ``ultimo_status`` /
 *  ``ultimo_motivo`` do /status (quando vêm) valem sobre a execução. */
export function resultadoDaTentativa(p: PlataformaStatus): { status: string | null; motivo: string | null } {
  const t = ultimaTentativa(p);
  if (p.ultimo_status && STATUS_TERMINAIS.has(p.ultimo_status)) {
    const motivo = p.ultimo_motivo !== undefined
      ? p.ultimo_motivo
      : (t?.status === p.ultimo_status ? t?.motivo ?? null : null);
    return { status: p.ultimo_status, motivo: motivo ?? null };
  }
  return { status: t?.status ?? null, motivo: t?.motivo ?? null };
}

/** A execução tem as contagens novas (por aluno distinto)? */
export function temContagemPorAluno(e: Execucao | null | undefined): boolean {
  return Boolean(e) && typeof e!.qtd_linhas === "number";
}

/** A última tentativa foi uma VERIFICAÇÃO sem dado novo? "Nada mudou" e "total
 *  retido" são (o backend as conta em ultima_verificacao_em); "linhas
 *  descartadas" não é. Sem motivo = backend que não informa: vale o "nada mudou". */
export function tentativaVerificada(p: PlataformaStatus): boolean {
  const { status, motivo } = resultadoDaTentativa(p);
  return status === "sem_atualizacao"
    && (!motivo || motivo === "nada_mudou" || motivo === "queda_retida");
}

/** O dado desta plataforma está velho? Pela regra da agenda (``desatualizada``,
 *  que cobre "agenda ativa há dias e nenhum sucesso ainda") OU pela idade do
 *  último dado aplicado (``frescor``, vale também sem agenda). Depois de uma
 *  verificação em que nada mudou, a idade do último dado aplicado não conta: só
 *  a regra da agenda. A regra ÚNICA do card (``situacaoIntegracao``) e do banner
 *  (``precisaVerificacao``) — antes o banner dizia "Dados desatualizados" para a
 *  plataforma cujo card dizia "Verificado: nada mudou". */
export function dadoDesatualizado(p: PlataformaStatus): boolean {
  return Boolean(p.desatualizada) || (p.frescor === "desatualizado" && !tentativaVerificada(p));
}

/** Há recálculo pendente nesta plataforma? (o /status vale sobre a execução) */
export function recalculoPendente(p: PlataformaStatus): boolean {
  if (typeof p.recalculo_pendente === "boolean") return p.recalculo_pendente;
  return Boolean(ultimaTentativa(p)?.recalculo_pendente);
}

export type ChaveSituacao =
  | "nao_configurada" | "credencial_ilegivel" | "andamento" | "nova_tentativa" | "falhou"
  | "indisponivel"
  | "desatualizada" | "nao_validada" | "ok" | "parcial" | "sem_atualizacao"
  | "correspondencia_pendente" | "tudo_em_revisao" | "sem_dados_coleta" | "sem_dados";

export type TomSituacao = "ok" | "parcial" | "info" | "alerta" | "erro" | "neutro" | "andamento";

export interface Situacao {
  chave: ChaveSituacao;
  /** Texto curto do badge (ex.: "Atualizado", "Dados desatualizados"). */
  rotulo: string;
  /** Uma frase para a escola: o que está acontecendo e o que fazer. */
  frase: string;
  tom: TomSituacao;
  /** Texto CRU do erro (erro_resumo / ultimo_erro), só para "Detalhe técnico".
   *  Nunca vai no badge. */
  detalheTecnico?: string | null;
  /** Tipo da falha, quando a situação é uma falha. */
  categoria?: CategoriaFalha | null;
  /** Onde a escola resolve (ex.: Revisões de identidade). */
  link?: { para: string; texto: string } | null;
}

/** Rótulo e tom de UMA execução (histórico, "última tentativa"). */
export function descreverExecucao(e: Pick<Execucao, "status"> & Partial<Pick<Execucao, "motivo" | "tentativa">>): {
  rotulo: string; tom: TomSituacao;
} {
  const motivo = e.motivo ?? null;
  switch (e.status) {
    case "concluida":
      return { rotulo: "concluída", tom: "ok" };
    case "parcial":
      return {
        rotulo: motivo === "falha_apos_gravacao" ? "parcial: falhou depois de gravar" : "parcial",
        tom: "parcial",
      };
    case "sem_atualizacao":
      return {
        rotulo: motivo && MOTIVO_EXECUCAO[motivo]
          ? `sem atualização: ${MOTIVO_EXECUCAO[motivo]}` : "sem atualização",
        tom: motivo === "tudo_em_revisao" ? "alerta" : "info",
      };
    case "sem_dados":
      return { rotulo: "a plataforma não trouxe dados", tom: "alerta" };
    case "erro":
      return {
        rotulo: motivo && CODIGO_ERRO[motivo]
          ? `falhou: ${minusculaInicial(CODIGO_ERRO[motivo].rotulo)}` : "falhou",
        tom: "erro",
      };
    case "executando":
      return { rotulo: "executando", tom: "andamento" };
    case "fila":
      return { rotulo: (e.tentativa ?? 1) > 1 ? "nova tentativa pendente" : "na fila", tom: "alerta" };
    case "cancelada":
      return { rotulo: "cancelada", tom: "neutro" };
    default:
      return { rotulo: e.status.replace(/_/g, " "), tom: "neutro" };
  }
}

/** "há 3 dias" / "há 5 horas" / "há menos de 1 hora" — a idade do último sucesso. */
export function idadeHumana(horas: number | null | undefined): string | null {
  if (horas == null || horas < 0) return null;
  if (horas < 1) return "há menos de 1 hora";
  if (horas < 48) return `há ${horas} hora${horas === 1 ? "" : "s"}`;
  const dias = Math.floor(horas / 24);
  return `há ${dias} dias`;
}

const FRASE_FALHA: Record<CategoriaFalha, string> = {
  autenticacao:
    "A plataforma recusou o acesso. Confira usuário e senha em “Configurar conexão” (e se a conta pede verificação em duas etapas).",
  indisponibilidade_externa:
    "A plataforma não respondeu como esperado (fora do ar, mudou a página ou bloqueou o acesso automático). Tente de novo mais tarde; se continuar, envie o relatório manualmente.",
  processamento:
    "O relatório chegou, mas houve um erro ao processá-lo do nosso lado. Tente de novo; se continuar, copie o detalhe técnico para o suporte ou envie o relatório manualmente.",
  indisponivel:
    "A coleta automática não está disponível neste servidor. Envie o relatório manualmente e avise o suporte.",
  configuracao:
    "A sincronização foi pedida com uma configuração que não é aceita (por exemplo, um período inválido). Confira as datas ou a configuração e peça de novo.",
};

const FRASE_FALHA_GENERICA =
  "A última sincronização não terminou. Confira a conexão e tente de novo; se continuar, envie o relatório manualmente.";

const plural = (n: number, um: string, varios: string) => `${n} ${n === 1 ? um : varios}`;

/**
 * Regra (em ordem de prioridade):
 *   1. sem credencial → "Ainda não configurada"
 *  1b. credencial que o servidor não consegue mais ler (chave trocada) →
 *      "Recadastre o acesso" — nenhuma coleta funciona até salvar de novo, então
 *      vence até o "Sincronizando" de uma execução que vai falhar
 *   2. execução em andamento (que vai rodar) → "Sincronizando"; uma NOVA
 *      TENTATIVA na fila → "Nova tentativa pendente", com a falha anterior na
 *      frase (nunca "Sincronizando" indefinidamente)
 *   3. coleta indisponível no servidor → "Coleta indisponível"
 *   4. credencial recusada/expirada ou última TENTATIVA com erro →
 *      "Falhou: <motivo humano>" (código do erro traduzido quando vier), com a
 *      frase do código ou do TIPO da falha. O texto cru vira detalheTecnico.
 *   5. credencial salva mas não validada → "Conexão não validada"
 *   6. última tentativa parcial → "Atualizado em parte" (com as falhas); a
 *      parcial sem nenhum aluno aplicado (D2(6): só o endpoint dos nomes do
 *      Matific falhou, contas conferidas) → "Verificado em parte"
 *  6b. sem atualização com tudo em revisão e nenhuma conta da escola conferida
 *      → "Sem atualização: nenhuma conta da escola reconhecida" (não é "em dia";
 *      confira se o acesso é desta escola) — link para Revisões
 *   7. sem atualização por correspondência pendente → link para Revisões
 *   8. última tentativa sem dados → "Sem dados na última coleta"
 *   9. dado velho (frescor / agenda) → "Dados desatualizados" com a idade
 *  9b. sem atualização com linhas descartadas por defeito → "Sem atualização:
 *      linhas com defeito" (não é verificação: não segura o frescor)
 *  10. sem atualização porque nada mudou → "Verificado: nada mudou"
 *  11. último sucesso em dia → "Atualizado"
 *  12. conectada e nenhuma tentativa → "Sem dados ainda"
 */
export function situacaoIntegracao(
  p: PlataformaStatus,
  nome?: string,
  /** Alertas ABERTOS desta plataforma (opcional) — dão o motivo humano da falha. */
  alertasAbertos: ReadonlyArray<{ tipo: string }> = [],
  /** O agendador do servidor está ligado? (EscolaStatus.agendador_ativo; opcional) */
  agendadorAtivo?: boolean,
): Situacao {
  const rotuloNome = nome ?? NOME_PLATAFORMA[p.plataforma] ?? p.plataforma;
  const exec = p.ultima_execucao;
  const tentativa = ultimaTentativa(p);
  const { status: statusUltimo, motivo: motivoUltimo } = resultadoDaTentativa(p);
  const credencialRuim =
    p.credencial_status === "invalida" || p.credencial_status === "expirada";
  const alertaFalha = alertasAbertos.find(
    (a) => Object.prototype.hasOwnProperty.call(TIPO_ALERTA, a.tipo) && !ALERTAS_NAO_FALHA.has(a.tipo));

  if (p.credencial_status === "nao_configurada") {
    return {
      chave: "nao_configurada", tom: "neutro", rotulo: "Ainda não configurada",
      // "Chegam sozinhos" só é verdade com o agendador ligado no servidor.
      frase: agendadorAtivo === true
        ? `Informe o acesso do ${rotuloNome} em “Configurar conexão” para os dados começarem a chegar sozinhos.`
        : `Informe o acesso do ${rotuloNome} em “Configurar conexão” para poder buscar os dados.`,
    };
  }
  if (p.credencial_status === "ilegivel") {
    return {
      chave: "credencial_ilegivel", tom: "erro", rotulo: "Recadastre o acesso",
      frase: `O acesso salvo do ${rotuloNome} não pode mais ser lido pelo servidor (a chave que protegia a senha foi trocada). Nenhuma sincronização funciona até você informar usuário e senha de novo em “Configurar conexão” e clicar em “Salvar e validar”.`,
    };
  }
  const novaTentativa = Boolean(exec && exec.status === "fila" && (exec.tentativa ?? 1) > 1);
  if (exec && !p.fila_parada && !novaTentativa
      && (exec.status === "executando" || exec.status === "fila")) {
    return {
      chave: "andamento", tom: "andamento", rotulo: "Sincronizando",
      frase: "Uma sincronização está em andamento. A tela atualiza sozinha.",
    };
  }

  // A falha que explica o estado (vale também para a nova tentativa pendente).
  const erroNaTentativa = statusUltimo === "erro";
  const falhou = credencialRuim || erroNaTentativa;
  // Código do erro: o motivo da execução (contrato) > o tipo do alerta aberto.
  const codigoDaExecucao = erroNaTentativa && motivoUltimo && CODIGO_ERRO[motivoUltimo]
    ? motivoUltimo : null;
  const categoria: CategoriaFalha | null = credencialRuim
    ? "autenticacao"
    : falhou
      ? (p.falha_categoria
        ?? (codigoDaExecucao ? CODIGO_ERRO[codigoDaExecucao].categoria : undefined)
        ?? (alertaFalha ? CATEGORIA_POR_TIPO[alertaFalha.tipo] : undefined)
        ?? null)
      : null;
  const detalheTecnico =
    (tentativa?.status === "erro" ? tentativa.erro_resumo : null) ||
    p.ultimo_erro ||
    tentativa?.erro_resumo ||
    null;
  // O badge só leva motivo HUMANO; o texto cru (que pode vir em inglês ou
  // com detalhe do conector) fica em detalheTecnico.
  let motivoFalha = "a última sincronização não terminou";
  if (p.credencial_status === "invalida") {
    motivoFalha = "senha recusada pela plataforma";
  } else if (p.credencial_status === "expirada") {
    motivoFalha = "senha expirada";
  } else if (codigoDaExecucao) {
    motivoFalha = minusculaInicial(CODIGO_ERRO[codigoDaExecucao].rotulo);
  } else if (alertaFalha) {
    motivoFalha = minusculaInicial(TIPO_ALERTA[alertaFalha.tipo]);
  }
  const fraseFalha = !credencialRuim && codigoDaExecucao
    ? CODIGO_ERRO[codigoDaExecucao].frase
    : categoria ? FRASE_FALHA[categoria] : FRASE_FALHA_GENERICA;

  if (novaTentativa) {
    // A retentativa na fila NÃO esconde a falha que a causou.
    const anterior = falhou
      ? `A última sincronização falhou (${motivoFalha}).`
      : "A última sincronização não terminou.";
    const parada = p.fila_parada || agendadorAtivo === false;
    return {
      chave: "nova_tentativa", tom: "alerta", rotulo: "Nova tentativa pendente",
      detalheTecnico, categoria,
      frase: `${anterior} ${parada
        ? "Há uma nova tentativa na fila, mas quem a roda é o agendador, que está desligado neste servidor: use “Sincronizar” para tentar agora."
        : "Uma nova tentativa automática está na fila e começa sozinha em alguns minutos."}`,
    };
  }
  if (falhou && categoria === "indisponivel") {
    return {
      chave: "indisponivel", tom: "erro", rotulo: "Coleta indisponível neste servidor",
      frase: FRASE_FALHA.indisponivel, detalheTecnico, categoria,
    };
  }
  if (falhou) {
    return {
      chave: "falhou", tom: "erro", rotulo: `Falhou: ${motivoFalha}`, detalheTecnico, categoria,
      frase: fraseFalha,
    };
  }
  if (p.credencial_status === "nao_validada") {
    return {
      chave: "nao_validada", tom: "alerta", rotulo: "Conexão não validada",
      detalheTecnico: p.ultimo_erro || null,
      frase: p.ultimo_erro
        ? "O acesso foi salvo, mas a validação não foi concluída (a plataforma não confirmou o login). Use “Testar conexão” em “Configurar conexão” mais tarde."
        : "O acesso foi salvo, mas ainda não foi testado. Use “Testar conexão” em “Configurar conexão”.",
    };
  }
  const contagem = tentativa && tentativa.status === statusUltimo ? tentativa : null;
  if (statusUltimo === "parcial") {
    const alunos = contagem && temContagemPorAluno(contagem) ? contagem.qtd_alunos : null;
    const falhas = typeof contagem?.qtd_falhas === "number" ? contagem.qtd_falhas : null;
    const aplicados = alunos !== null ? ` (${plural(alunos, "aluno atualizado", "alunos atualizados")})` : "";
    // Com o alerta "Formato do relatório mudou" aberto, a tela não sabe se a parte que
    // falhou NESTA coleta foi só a do formato (repetir não completa — 35993e13), se
    // houve também uma turma que falhou de passagem (o servidor diz as duas coisas:
    // "Sincronize de novo para completar" e "o que veio em outro formato não volta"),
    // ou se o alerta de formato ficou aberto de uma coleta anterior (a parcial com
    // falha não o fecha) e esta falhou só por tempo esgotado. Quem diz, por execução,
    // é o alerta "Coleta parcial" (_mensagem_parcial no servidor): a frase manda lê-lo
    // e repete só o que vale nos três casos (REV2-SYNC2-1).
    const proximoPasso = alertasAbertos.some((a) => a.tipo === "parser_incompativel")
      ? `Veja os alertas: o “${TIPO_ALERTA.coleta_parcial}” diz se sincronizar de novo completa o que falhou; o que veio em outro formato não volta com outra coleta (alerta “${TIPO_ALERTA.parser_incompativel}”).`
      : "Veja o alerta e sincronize de novo para completar.";
    if (alunos === 0 && motivoUltimo === "coleta_parcial") {
      // D2(6): falhou só o endpoint acessório (nomes do Matific) e as contas já
      // ligadas foram CONFERIDAS sem número mudado — nada foi aplicado. Mesma
      // chave 'parcial' (o banner continua listando a plataforma).
      return {
        chave: "parcial", tom: "parcial", rotulo: "Verificado em parte",
        detalheTecnico: contagem?.erro_resumo || null,
        frase: `A última sincronização conferiu as contas já ligadas e nenhum número mudou, mas parte da coleta falhou${falhas !== null && falhas > 0 ? ` (${plural(falhas, "falha", "falhas")})` : ""}. ${proximoPasso}`,
      };
    }
    return {
      chave: "parcial", tom: "parcial", rotulo: "Atualizado em parte",
      detalheTecnico: contagem?.erro_resumo || null,
      frase: motivoUltimo === "falha_apos_gravacao"
        ? `A última sincronização falhou depois de já ter gravado parte dos dados${aplicados}. O que chegou foi aplicado; sincronize de novo para completar.`
        : motivoUltimo === "linhas_descartadas"
          ? `A última sincronização aplicou dados${aplicados}, mas parte das linhas recebidas veio com defeito (sem data ou sem nome) e não virou dado. Veja o alerta; se repetir, envie o relatório manualmente.`
          : motivoUltimo === "campos_nao_atualizados"
            ? `A última sincronização aplicou dados${aplicados}, mas a plataforma deixou de mandar parte dos números (tempo de leitura ou questões): eles ficaram com o valor da coleta anterior, e sincronizar de novo não os traz de volta. O alerta “Formato do relatório mudou” diz quais faltaram.`
            : `A última sincronização aplicou dados${aplicados}, mas parte da coleta falhou${falhas !== null && falhas > 0 ? ` (${plural(falhas, "falha", "falhas")})` : ""}. ${proximoPasso}`,
    };
  }
  if (statusUltimo === "sem_atualizacao" && motivoUltimo === "tudo_em_revisao") {
    // Nenhuma conta já vinculada da escola veio nesta coleta: o backend NÃO conta
    // como "em dia" (o "Dados desatualizados" abre depois do prazo da agenda).
    // Pode ser a 1ª coleta (nenhuma conta vinculada ainda) ou o acesso de OUTRA
    // escola — a frase cobre os dois; o alerta do backend diz qual.
    const revisao = typeof contagem?.qtd_em_revisao === "number" ? contagem.qtd_em_revisao : null;
    const desatualizada = p.desatualizada || p.frescor === "desatualizado";
    // Fila vazia (só linhas sem vínculo seguro): não diz "0 contas aguardam".
    const fila = revisao === null
      ? "todas as linhas aguardam em Revisões de identidade"
      : revisao > 0
        ? `${plural(revisao, "conta aguarda", "contas aguardam")} em Revisões de identidade`
        : "as linhas recebidas ficaram sem vínculo seguro com uma ficha e nenhuma foi para Revisões de identidade (veja o histórico)";
    return {
      chave: "tudo_em_revisao", tom: "alerta",
      rotulo: "Sem atualização: nenhuma conta da escola reconhecida",
      frase: `A última coleta terminou sem erro, mas nenhuma conta já ligada a um aluno desta escola veio nela: ${fila}. Por isso ela não conta como dado em dia${desatualizada
        ? " (os dados desta plataforma já estão desatualizados)" : ""}. Se a escola já tinha alunos ligados, confira em “Configurar conexão” se o acesso cadastrado é o desta escola antes de resolver as revisões; se é a primeira coleta, confirme que os nomes são desta escola e resolva as revisões.`,
      link: { para: "/revisoes-identidade", texto: "Ver revisões de identidade" },
    };
  }
  if (statusUltimo === "sem_atualizacao" && motivoUltimo === "correspondencia_pendente") {
    const revisao = typeof contagem?.qtd_em_revisao === "number" ? contagem.qtd_em_revisao : null;
    // Fila vazia (só linhas sem vínculo seguro): antes saía "0 contas aguardam".
    const fila = revisao === null
      ? "as linhas com dado aguardam a escolha do aluno certo em Revisões de identidade"
      : revisao > 0
        ? `${plural(revisao, "conta aguarda", "contas aguardam")} a escolha do aluno certo em Revisões de identidade`
        : "as linhas recebidas ficaram sem vínculo seguro com uma ficha e nenhuma foi para Revisões de identidade (veja o histórico)";
    return {
      chave: "correspondencia_pendente", tom: "info",
      rotulo: "Sem atualização: correspondência pendente",
      frase: `A última coleta terminou sem erro, mas nenhum aluno foi atualizado: ${fila}.`,
      link: { para: "/revisoes-identidade", texto: "Ver revisões de identidade" },
    };
  }
  if (statusUltimo === "sem_dados") {
    return {
      chave: "sem_dados_coleta", tom: "alerta", rotulo: "Sem dados na última coleta",
      frase: "A plataforma não trouxe dados na última sincronização (nenhuma turma ou linha). Confira na plataforma se as turmas têm atividade; se continuar, envie o relatório manualmente.",
    };
  }
  // Sem motivo = backend que não informa: vale o "nada mudou" de antes.
  const nadaMudou = statusUltimo === "sem_atualizacao"
    && (!motivoUltimo || motivoUltimo === "nada_mudou");
  const idade = idadeHumana(p.idade_horas);
  // Dado velho pela agenda ou pelo frescor; depois de uma VERIFICAÇÃO ("nada
  // mudou", "total retido") só a regra da agenda vale (``dadoDesatualizado``).
  if (dadoDesatualizado(p)) {
    const pausada = p.agendada && agendadorAtivo === false;
    return {
      chave: "desatualizada", tom: "alerta",
      rotulo: idade ? `Dados desatualizados (${idade.replace(/^há /, "")})` : "Dados desatualizados",
      frase: (p.ultimo_sucesso_em
        ? `Sem sincronização bem-sucedida desde ${dataHora(p.ultimo_sucesso_em)}. `
        : "Nenhuma sincronização bem-sucedida ainda. ")
        + (pausada
          ? "A atualização automática está pausada no servidor: use “Sincronizar” para buscar os dados agora."
          : "Confira a conexão e a agenda em “Configurar conexão” e use “Sincronizar”."),
    };
  }
  if (statusUltimo === "sem_atualizacao" && motivoUltimo === "linhas_descartadas") {
    return {
      chave: "sem_atualizacao", tom: "alerta", rotulo: "Sem atualização: linhas com defeito",
      frase: "A última coleta terminou sem erro, mas nenhum aluno foi atualizado e parte das linhas recebidas veio com defeito (sem data ou sem nome) e não virou dado. Os dados que já estão aqui continuam valendo; se repetir, envie o relatório manualmente.",
    };
  }
  if (statusUltimo === "sem_atualizacao" && motivoUltimo === "campos_nao_atualizados") {
    // A resposta perdeu tempo/questões (backend: MOTIVO_CAMPOS_NAO_ATUALIZADOS): não
    // é "nada mudou" nem conta como dado em dia.
    return {
      chave: "sem_atualizacao", tom: "alerta", rotulo: "Sem atualização: tempo ou questões não vieram",
      frase: "A última coleta terminou sem erro e nenhum aluno foi atualizado, mas a plataforma deixou de mandar parte dos números (tempo de leitura ou questões): eles ficaram com o valor da coleta anterior, e sincronizar de novo não os traz de volta. O alerta “Formato do relatório mudou” diz quais faltaram.",
    };
  }
  if (statusUltimo === "sem_atualizacao" && motivoUltimo === "queda_retida") {
    return {
      chave: "sem_atualizacao", tom: "alerta", rotulo: "Verificado: total menor retido",
      frase: "A última coleta terminou sem erro e nenhum aluno foi atualizado: a plataforma mandou, para algum aluno, um total MENOR que o já gravado no ano, e o valor gravado foi mantido. Confira no Matific (veja o alerta); se a queda for real, importe o relatório oficial em Importações.",
    };
  }
  if (nadaMudou) {
    return {
      chave: "sem_atualizacao", tom: "info", rotulo: "Verificado: nada mudou",
      frase: "A última coleta terminou sem erro, mas a plataforma não tinha dado novo de nenhum aluno. Os dados que já estão aqui continuam valendo.",
    };
  }
  if (p.conectada && statusUltimo === "concluida") {
    return {
      chave: "ok", tom: "ok", rotulo: "Atualizado",
      frase: idade
        ? `Último dado aplicado ${idade}: os dados desta plataforma estão em dia.`
        : "Os dados desta plataforma estão em dia.",
    };
  }
  if (p.conectada && !tentativa) {
    return {
      chave: "sem_dados", tom: "neutro", rotulo: "Sem dados ainda",
      frase: `Conexão pronta. Clique em “Sincronizar ${rotuloNome}” para receber os primeiros dados.`,
    };
  }
  return {
    chave: "sem_dados", tom: "neutro", rotulo: "Sem dados ainda",
    frase: exec?.status === "cancelada"
      ? "A última sincronização foi cancelada. Clique em “Sincronizar” para tentar de novo."
      : "Ainda não há dados desta plataforma.",
  };
}

function minusculaInicial(texto: string): string {
  return texto.charAt(0).toLocaleLowerCase("pt-BR") + texto.slice(1);
}

// Identidade v2: as situações viram PÍLULAS (mesmos tons do Badge do design system,
// mais os três que só a integração tem: parcial, andamento e o "info" azul). O texto
// do rótulo continua sendo a informação — a bolinha colorida é só reforço.
export const TONS: Record<TomSituacao, string> = {
  ok: "bg-emerald-50 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300",
  parcial: "bg-orange-50 text-orange-700 dark:bg-orange-500/15 dark:text-orange-300",
  info: "bg-sky-50 text-sky-700 dark:bg-sky-500/15 dark:text-sky-300",
  alerta: "bg-ouro-50 text-ouro-700 dark:bg-ouro-400/15 dark:text-ouro-300",
  erro: "bg-rose-50 text-rose-700 dark:bg-rose-500/15 dark:text-rose-300",
  neutro: "bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300",
  andamento: "bg-indigo-50 text-indigo-700 dark:bg-indigo-500/15 dark:text-indigo-300",
};

/** A bolinha de cada tom (decorativa: o rótulo diz a situação). */
const PONTOS: Record<TomSituacao, string> = {
  ok: "bg-emerald-500",
  parcial: "bg-orange-500",
  info: "bg-sky-500",
  alerta: "bg-ouro-500",
  erro: "bg-rose-500",
  neutro: "bg-zinc-400",
  andamento: "bg-indigo-500 animate-pulse motion-reduce:animate-none",
};

/** Pílula da situação — mesmo visual do Badge do design system, com o tom "erro". */
export function StatusIntegracaoBadge({ situacao }: { situacao: Situacao }) {
  return (
    <span
      className={`inline-flex max-w-full items-center gap-1.5 rounded-full px-3 py-1 text-xs font-semibold ${TONS[situacao.tom]}`}
      title={situacao.rotulo}
      data-tom={situacao.tom}
    >
      <span aria-hidden className={`h-2 w-2 shrink-0 rounded-full ${PONTOS[situacao.tom]}`} />
      <span className="truncate" title={situacao.rotulo}>{situacao.rotulo}</span>
    </span>
  );
}

/** Pílula de UMA execução (histórico): mesmo rótulo/tom de ``descreverExecucao``. */
export function ExecucaoBadge({ execucao }: {
  execucao: Pick<Execucao, "status"> & Partial<Pick<Execucao, "motivo" | "tentativa">>;
}) {
  const d = descreverExecucao(execucao);
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-semibold ${TONS[d.tom]}`}
      data-tom={d.tom}
    >
      <span aria-hidden className={`h-1.5 w-1.5 shrink-0 rounded-full ${PONTOS[d.tom]}`} />
      {d.rotulo}
    </span>
  );
}

/** Há algo que a escola precisa olhar? (banner do topo de Integrações). */
export function precisaVerificacao(
  dados: EscolaStatus, alertasCarregados: number | null,
): {
  alertas: number; pendencias: number; desatualizadas: string[];
  recalculoPendente: string[]; parciais: string[]; correspondenciaPendente: string[];
  /** Plataformas cuja última coleta deixou TUDO em revisão sem conferir nenhuma
   *  conta da escola (motivo ``tudo_em_revisao``). */
  tudoEmRevisao: string[];
  /** Plataformas cuja senha salva o servidor não consegue mais ler (recadastrar). */
  recadastrar: string[];
} {
  const alertas = Math.max(dados.alertas_abertos ?? 0, alertasCarregados ?? 0);
  const pendencias = dados.pendencias_correspondencia_30d ?? 0;
  const configuradas = dados.plataformas.filter((p) => p.credencial_status !== "nao_configurada");
  const nomeDe = (p: PlataformaStatus) => NOME_PLATAFORMA[p.plataforma] ?? p.plataforma;
  // A MESMA regra do card: a coleta verificada ("nada mudou", "total retido") não
  // vira "desatualizada" pela idade do último dado aplicado.
  const desatualizadas = configuradas.filter(dadoDesatualizado).map(nomeDe);
  const recalculo = dados.plataformas.filter(recalculoPendente).map(nomeDe);
  const parciais = configuradas
    .filter((p) => resultadoDaTentativa(p).status === "parcial")
    .map(nomeDe);
  const correspondenciaPendente = configuradas
    .filter((p) => {
      const r = resultadoDaTentativa(p);
      return r.status === "sem_atualizacao" && r.motivo === "correspondencia_pendente";
    })
    .map(nomeDe);
  const tudoEmRevisao = configuradas
    .filter((p) => {
      const r = resultadoDaTentativa(p);
      return r.status === "sem_atualizacao" && r.motivo === "tudo_em_revisao";
    })
    .map(nomeDe);
  const recadastrar = dados.plataformas
    .filter((p) => p.credencial_status === "ilegivel")
    .map(nomeDe);
  return {
    alertas, pendencias, desatualizadas,
    recalculoPendente: recalculo, parciais, correspondenciaPendente, tudoEmRevisao,
    recadastrar,
  };
}
