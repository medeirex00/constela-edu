/**
 * Situação de uma integração (Matific / Elefante Letrado) na linguagem da
 * escola: um rótulo curto (badge) + uma frase que diz o que fazer.
 *
 * Deriva SOMENTE do que GET /escolas/{id}/sync/status já devolve — nada é
 * inventado: campo ausente não vira número nem estado. Os campos de cobertura
 * (alunos_com_dados, alunos_sem_dados, alunos_com_zero_registros,
 * dado_mais_recente_em) são OPCIONAIS e só são exibidos quando presentes.
 */
import { dataHora } from "../lib/formato";

// --- Tipos (espelham app/sync/schemas.py) ----------------------------------
export interface Execucao {
  id: number; plataforma: string; origem: string; status: string;
  iniciada_em: string | null; finalizada_em: string | null; duracao_ms: number;
  qtd_alunos: number; qtd_turmas: number; qtd_arquivos: number; qtd_erros: number;
  tentativa: number; erro_resumo: string | null; conector_versao?: string | null;
  parser_versao?: string | null; created_at?: string;
}

export interface PlataformaStatus {
  plataforma: string; estrategia: string; conectada: boolean;
  credencial_status: string; validada_em: string | null; ultimo_erro: string | null;
  agendada: boolean; cadencia: string; hora_local: string; dia_semana: number | null;
  proxima_execucao: string | null; ultima_execucao: Execucao | null;
  ultimo_sucesso_em: string | null; desatualizada: boolean;
  /** Cobertura (opcionais — o backend pode não informar; nunca inventar).
   *  ``null`` = o backend não conseguiu contar (≠ 0). */
  alunos_com_dados?: number | null;
  alunos_sem_dados?: number | null;
  alunos_com_zero_registros?: number | null;
  dado_mais_recente_em?: string | null;
}

export interface EscolaStatus {
  escola_id: number; escola_nome: string; qtd_alunos: number; qtd_turmas: number;
  plataformas: PlataformaStatus[]; alertas_abertos: number;
  lista_piloto_importada: boolean; integracao_configurada: boolean;
  /** Linhas de relatório sem aluno correspondente nos últimos 30 dias (opcional). */
  pendencias_correspondencia_30d?: number;
}

export const NOME_PLATAFORMA: Record<string, string> = {
  matific: "Matific",
  elefante: "Elefante Letrado",
};

// Tipos de alerta do backend (app/sync/service.py) → rótulo para a escola.
export const TIPO_ALERTA: Record<string, string> = {
  senha_invalida: "Senha inválida",
  senha_expirada: "Senha expirada",
  falha_autenticacao: "Falha no acesso",
  falha_auth: "Falha no acesso",
  falha_download: "Falha ao baixar o relatório",
  timeout: "Demorou demais",
  plataforma_indisponivel: "Plataforma indisponível",
  parser_incompativel: "Formato do relatório mudou",
  desatualizada: "Dados desatualizados",
  interrompida: "Sincronização interrompida",
  lento: "Sincronização lenta",
};
export const rotuloAlerta = (tipo: string) => TIPO_ALERTA[tipo] ?? tipo.replace(/_/g, " ");

// Alertas que NÃO explicam uma falha de execução (são avisos de estado).
const ALERTAS_NAO_FALHA = new Set(["desatualizada", "lento"]);

export type ChaveSituacao =
  | "nao_configurada" | "andamento" | "falhou" | "desatualizada"
  | "nao_validada" | "ok" | "sem_dados";

export type TomSituacao = "ok" | "alerta" | "erro" | "neutro" | "andamento";

export interface Situacao {
  chave: ChaveSituacao;
  /** Texto curto do badge (ex.: "Funcionando", "Dados desatualizados"). */
  rotulo: string;
  /** Uma frase para a escola: o que está acontecendo e o que fazer. */
  frase: string;
  tom: TomSituacao;
  /** Texto CRU do erro (erro_resumo / ultimo_erro), só para "Detalhe técnico".
   *  Nunca vai no badge. */
  detalheTecnico?: string | null;
}

/**
 * Regra (em ordem de prioridade):
 *   1. sem credencial → "Ainda não configurada"
 *   2. execução em andamento → "Sincronizando"
 *   3. credencial inválida/expirada ou última execução com erro → "Falhou: <motivo humano>"
 *      (senha recusada / senha expirada / tipo do alerta aberto da plataforma /
 *      "a última sincronização não terminou"). O texto cru vira detalheTecnico.
 *   4. desatualizada (agendada e sem sucesso há tempo demais) → "Dados desatualizados"
 *   5. credencial salva mas não testada → "Conexão não validada"
 *   6. conectada e última execução concluída → "Funcionando"
 *   7. conectada e sem execução → "Sem dados ainda"
 */
export function situacaoIntegracao(
  p: PlataformaStatus,
  nome?: string,
  /** Alertas ABERTOS desta plataforma (opcional) — dão o motivo humano da falha. */
  alertasAbertos: ReadonlyArray<{ tipo: string }> = [],
): Situacao {
  const rotuloNome = nome ?? NOME_PLATAFORMA[p.plataforma] ?? p.plataforma;
  const exec = p.ultima_execucao;
  const credencialRuim =
    p.credencial_status === "invalida" || p.credencial_status === "expirada";

  if (p.credencial_status === "nao_configurada") {
    return {
      chave: "nao_configurada", tom: "neutro", rotulo: "Ainda não configurada",
      frase: `Informe o acesso do ${rotuloNome} em “Configurar conexão” para os dados começarem a chegar sozinhos.`,
    };
  }
  if (exec && (exec.status === "executando" || exec.status === "fila")) {
    return {
      chave: "andamento", tom: "andamento", rotulo: "Sincronizando",
      frase: "Uma sincronização está em andamento. A tela atualiza sozinha.",
    };
  }
  if (credencialRuim || exec?.status === "erro") {
    // O badge só leva motivo HUMANO; o texto cru (que pode vir em inglês ou
    // com detalhe do conector) fica em detalheTecnico.
    let motivo: string;
    if (p.credencial_status === "invalida") {
      motivo = "senha recusada pela plataforma";
    } else if (p.credencial_status === "expirada") {
      motivo = "senha expirada";
    } else {
      const alerta = alertasAbertos.find(
        (a) => Object.prototype.hasOwnProperty.call(TIPO_ALERTA, a.tipo) && !ALERTAS_NAO_FALHA.has(a.tipo));
      motivo = alerta
        ? minusculaInicial(TIPO_ALERTA[alerta.tipo])
        : "a última sincronização não terminou";
    }
    const detalheTecnico =
      (exec?.status === "erro" ? exec.erro_resumo : null) ||
      p.ultimo_erro ||
      exec?.erro_resumo ||
      null;
    return {
      chave: "falhou", tom: "erro", rotulo: `Falhou: ${motivo}`, detalheTecnico,
      frase: credencialRuim
        ? "A plataforma recusou o acesso. Confira usuário e senha em “Configurar conexão”."
        : "A última sincronização não terminou. Confira a conexão e tente de novo; se continuar, envie o relatório manualmente.",
    };
  }
  if (p.desatualizada) {
    return {
      chave: "desatualizada", tom: "alerta", rotulo: "Dados desatualizados",
      frase: p.ultimo_sucesso_em
        ? `Sem sincronização bem-sucedida desde ${dataHora(p.ultimo_sucesso_em)}. Confira a conexão e a agenda em “Configurar conexão”.`
        : "Nenhuma sincronização bem-sucedida ainda. Confira a conexão e a agenda em “Configurar conexão”.",
    };
  }
  if (p.credencial_status === "nao_validada") {
    return {
      chave: "nao_validada", tom: "alerta", rotulo: "Conexão não validada",
      frase: "O acesso foi salvo, mas ainda não foi testado. Use “Testar conexão” em “Configurar conexão”.",
    };
  }
  if (p.conectada && exec && (exec.status === "concluida" || exec.status === "sem_dados")) {
    return {
      chave: "ok", tom: "ok", rotulo: "Funcionando",
      frase: exec.status === "sem_dados"
        ? "Tudo certo: a última sincronização não encontrou dados novos."
        : "Tudo certo: os dados desta plataforma chegam automaticamente.",
    };
  }
  if (p.conectada && !exec) {
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

const TONS: Record<TomSituacao, string> = {
  ok: "bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300",
  alerta: "bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300",
  erro: "bg-red-50 text-red-700 dark:bg-red-500/10 dark:text-red-300",
  neutro: "bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300",
  andamento: "bg-indigo-50 text-indigo-700 dark:bg-indigo-500/10 dark:text-indigo-300",
};

/** Badge da situação — mesmo visual do Badge do design system, com o tom "erro". */
export function StatusIntegracaoBadge({ situacao }: { situacao: Situacao }) {
  return (
    <span
      className={`inline-flex max-w-full items-center rounded-md px-2 py-0.5 text-xs font-medium ${TONS[situacao.tom]}`}
      title={situacao.rotulo}
    >
      <span className="truncate">{situacao.rotulo}</span>
    </span>
  );
}

/** Há algo que a escola precisa olhar? (banner do topo de Integrações). */
export function precisaVerificacao(
  dados: EscolaStatus, alertasCarregados: number | null,
): { alertas: number; pendencias: number; desatualizadas: string[] } {
  const alertas = Math.max(dados.alertas_abertos ?? 0, alertasCarregados ?? 0);
  const pendencias = dados.pendencias_correspondencia_30d ?? 0;
  const desatualizadas = dados.plataformas
    .filter((p) => p.desatualizada)
    .map((p) => NOME_PLATAFORMA[p.plataforma] ?? p.plataforma);
  return { alertas, pendencias, desatualizadas };
}
