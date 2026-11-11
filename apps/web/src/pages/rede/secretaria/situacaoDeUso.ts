/**
 * A SITUAÇÃO DE USO de cada escola da rede no Constela (DESENHO3 §2) — função pura, sem leitura.
 *
 * Três coisas que NÃO são sinônimos:
 * - CADASTRADA: a escola está vinculada à rede (toda linha do `/redes/{id}/dashboard`);
 * - ATIVA: a situação do cadastro (`status === "ativa"`) — não diz nada sobre uso;
 * - COM USO no ano letivo: pelo menos um aluno do 1º ao 5º ano leu um livro no Elefante (o
 *   servidor conta também a releitura: nada de "livro novo" aqui) ou fez uma atividade no Matific
 *   no período, pelas coletas (`/redes/{id}/analise/plataformas`).
 *
 * Ausência nunca vira "sem uso": sem coleta, sem conta, sem alunos do 1º ao 5º ano é SEM DADO; a
 * escola (ou a métrica) escondida para proteger as crianças é PROTEGIDA. "Sem uso registrado" só
 * quando a coleta da plataforma está em dia (ou parcial, com a data) e o número é zero — e a
 * situação GERAL com coleta parcial leva a data junto ("Sem uso registrado até 15/03/2026 (coleta
 * parcial)": o resto do ano não foi medido; `parcialGeral`/`ateGeral`, `rotuloGeral`). Os números
 * do `/dashboard` (`alunos_com_dados`, `adocao`) são contas e retratos SEM período: não são uso e
 * nunca entram aqui (do cartão só saem o cadastro, os alunos e o texto da escola sem aluno do 1º
 * ao 5º ano). O número que falta SEM a marca de protegido (`metricas_protegidas`) é falta de dado,
 * não proteção. Testes: `test/situacaoDeUso.test.ts`.
 */
import { diaBR, numeroProtegido, porNome } from "../../analise/formato";
import type {
  EscolaPlataformas, MetricasElefante, MetricasMatific, RespostaPlataformas,
} from "../../analise/tipos";
import type { EscolaCartao } from "../comum";

export type EstadoUso = "com_uso" | "sem_uso" | "sem_dado" | "protegido";
export type Plataforma = "elefante" | "matific";

export interface UsoDaPlataforma {
  estado: EstadoUso;
  /** A frase por extenso ("62% dos alunos com conta leram ao menos um livro", "sem coleta…"). */
  texto: string;
  /** Coleta parcial: até quando o número vale (dd/mm/aaaa). */
  ate: string | null;
}

export interface SituacaoEscola {
  escolaId: number;
  nome: string;
  /** Situação do CADASTRO (null sem o cartão do painel). */
  ativa: boolean | null;
  /** Alunos ativos matriculados no ano letivo, todas as etapas (null sem o cartão). */
  alunos: number | null;
  geral: EstadoUso;
  /** Só com a situação geral "sem uso registrado": a coleta de alguma plataforma é PARCIAL (o
   *  zero só vale até a data dela). Fora desse caso, false. */
  parcialGeral: boolean;
  /** Com `parcialGeral`: até quando o "sem uso registrado" vale — a data MAIS ANTIGA das coletas
   *  parciais (dd/mm/aaaa); null se alguma parcial não trouxe a data (e fora desse caso). */
  ateGeral: string | null;
  /** Só as plataformas CONTRATADAS pela rede. */
  plataformas: Partial<Record<Plataforma, UsoDaPlataforma>>;
}

export const ROTULO_ESTADO: Record<EstadoUso, string> = {
  com_uso: "Com uso no ano letivo",
  sem_uso: "Sem uso registrado",
  sem_dado: "Sem dado",
  protegido: "Protegida (poucos alunos)",
};

/** O rótulo curto da situação de UMA plataforma numa escola (a frase vem em `texto`). */
export const ROTULO_PLATAFORMA: Record<EstadoUso, string> = {
  com_uso: "Com uso",
  sem_uso: "Sem uso registrado",
  sem_dado: "Sem dado",
  protegido: "Protegido (poucos alunos)",
};

export const NOME_PLATAFORMA: Record<Plataforma, string> = { elefante: "Elefante", matific: "Matific" };
const NOME = NOME_PLATAFORMA;
const SEM_ALUNOS_NO_RECORTE = "sem_alunos_no_recorte";
/** Os campos que dizem se HOUVE uso (o Elefante conta quem leu; o Matific só manda a taxa). */
const CAMPOS_DE_USO: Record<Plataforma, string[]> = {
  elefante: ["alunos_com_leitura", "participacao_pct"],
  matific: ["participacao_pct"],
};

const pct = (v: number) => `${v.toLocaleString("pt-BR", { maximumFractionDigits: 1 })}%`;

/** A coleta da plataforma parou antes do fim do período (pelo bloco ou pela cobertura da escola). */
const coletaParcial = (p: Plataforma, escola: EscolaPlataformas | undefined) =>
  Boolean(escola?.[p]?.coleta_parcial) || escola?.cobertura?.[p] === "coleta_parcial";

/** A data mais antiga de uma lista de "dd/mm/aaaa" (não vazia). */
const maisAntiga = (datas: string[]) => {
  const chave = (d: string) => d.split("/").reverse().join("");
  return datas.reduce((a, b) => (chave(b) < chave(a) ? b : a));
};

/** Houve uso no bloco? `null` = o número não veio (protegido ou ausente: não dá para dizer pelo total). */
function houveUso(p: Plataforma, bloco: MetricasElefante | MetricasMatific): boolean | null {
  if (p === "elefante") {
    const e = bloco as MetricasElefante;
    if (e.alunos_com_leitura != null) return e.alunos_com_leitura > 0;
  }
  return bloco.participacao_pct != null ? bloco.participacao_pct > 0 : null;
}

/** A participação por extenso, com o denominador de CADA plataforma (o mesmo do cartão da rede
 *  e da conclusão): no Elefante, os alunos com conta; no Matific, os alunos com dado no período.
 *  O número do Elefante conta também a releitura — por isso "um livro", nunca "um livro novo". */
function frasesDeUso(p: Plataforma, bloco: MetricasElefante | MetricasMatific): string {
  if (bloco.participacao_pct != null) {
    return p === "elefante"
      ? `${pct(bloco.participacao_pct)} dos alunos com conta leram ao menos um livro`
      : `${pct(bloco.participacao_pct)} dos alunos com dado no período fizeram ao menos uma atividade`;
  }
  return p === "elefante" ? "pelo menos um aluno leu um livro" : "pelo menos um aluno fez uma atividade";
}

/** A escola sem aluno do 1º ao 5º ano: com alunos matriculados (só Educação Infantil, por
 *  exemplo), diz que as plataformas são medidas do 1º ao 5º ano; sem nenhum, diz isso. */
function textoSemAlunos(alunosMatriculados: number | null | undefined): string | null {
  if (alunosMatriculados == null) return null;
  return alunosMatriculados > 0
    ? "só alunos fora do 1º ao 5º ano (as plataformas são medidas do 1º ao 5º ano)"
    : "nenhum aluno matriculado no ano letivo";
}

/**
 * O uso de UMA plataforma contratada numa escola, no período da resposta (ano letivo).
 * `alunosMatriculados` (o `total_alunos` do cartão do painel, todas as etapas) só afina o
 * texto da escola sem aluno do 1º ao 5º ano — nunca decide uso.
 */
export function usoDaPlataforma(p: Plataforma, escola: EscolaPlataformas | undefined,
                                alunosMatriculados?: number | null): UsoDaPlataforma {
  if (!escola) return { estado: "sem_dado", texto: "sem dado das plataformas para esta escola", ate: null };
  if (escola.suprimido) {
    return { estado: "protegido", texto: escola.texto_supressao ?? "poucos alunos: os números ficam protegidos", ate: null };
  }
  const bloco = escola[p];
  if (!bloco) return { estado: "sem_dado", texto: `sem dado do ${NOME[p]}`, ate: null };
  const motivo = bloco.motivo_sem_dado;
  if (numeroProtegido(bloco)) {
    return { estado: "protegido", texto: bloco.texto_sem_dado ?? "poucos alunos: os números ficam protegidos", ate: null };
  }
  if (motivo === SEM_ALUNOS_NO_RECORTE || (!motivo && escola.cobertura?.[p] === SEM_ALUNOS_NO_RECORTE)) {
    const texto = textoSemAlunos(alunosMatriculados) ?? bloco.texto_sem_dado ?? "sem alunos do 1º ao 5º ano";
    return { estado: "sem_dado", texto, ate: null };
  }
  if (motivo) return { estado: "sem_dado", texto: bloco.texto_sem_dado ?? `sem dado do ${NOME[p]}`, ate: null };

  const parcial = coletaParcial(p, escola);
  const ate = parcial ? diaBR(bloco.coberto_ate ?? escola.coberto_ate?.[p] ?? null) : null;
  const ateTexto = ate ? ` (coleta até ${ate})` : "";
  let usou = houveUso(p, bloco);
  if (usou == null) {
    // O total esconde a métrica (complemento): alguma série VISÍVEL com uso basta para dizer que houve.
    const serieComUso = escola.series.some((s) => !s.suprimido && s[p] != null && houveUso(p, s[p]!) === true);
    if (serieComUso) {
      const fazer = p === "elefante" ? "leu um livro" : "fez uma atividade";
      return { estado: "com_uso", texto: `pelo menos um aluno ${fazer} (o total da escola fica protegido: poucos alunos)${ateTexto}`, ate };
    }
    // Sem número E sem a marca de protegido: é falta de dado, não proteção (nunca "sem uso").
    const protegido = CAMPOS_DE_USO[p].some((c) => numeroProtegido(bloco, c));
    if (!protegido) return { estado: "sem_dado", texto: `sem dado do ${NOME[p]} no período`, ate: null };
    return { estado: "protegido", texto: "número protegido (poucos alunos)", ate: null };
  }
  if (usou) return { estado: "com_uso", texto: `${frasesDeUso(p, bloco)}${ateTexto}`, ate };
  if (parcial) {
    return { estado: "sem_uso", texto: `nenhum uso registrado${ate ? ` até ${ate}` : ""} (coleta parcial)`, ate };
  }
  if (escola.cobertura?.[p] === "ok") {
    const ninguem = p === "elefante" ? "nenhum aluno leu um livro no período" : "nenhum aluno fez atividade no período";
    return { estado: "sem_uso", texto: ninguem, ate: null };
  }
  return { estado: "sem_dado", texto: `sem coleta em dia do ${NOME[p]}`, ate: null };
}

/** A situação geral: com uso se ALGUMA plataforma teve uso; sem uso só se TODAS as contratadas
 *  estão medidas e zeradas (com coleta parcial, a escola leva a data: `classificarEscola`);
 *  senão, protegida (só proteção e zeros) ou sem dado. */
function situacaoGeral(usos: UsoDaPlataforma[]): EstadoUso {
  if (usos.length === 0) return "sem_dado";
  if (usos.some((u) => u.estado === "com_uso")) return "com_uso";
  if (usos.every((u) => u.estado === "sem_uso")) return "sem_uso";
  if (usos.every((u) => u.estado === "protegido" || u.estado === "sem_uso")) return "protegido";
  return "sem_dado";
}

export function classificarEscola(cartao: EscolaCartao | undefined, escola: EscolaPlataformas | undefined,
                                  modulos: RespostaPlataformas["modulos"]): SituacaoEscola {
  const plataformas: Partial<Record<Plataforma, UsoDaPlataforma>> = {};
  for (const p of ["elefante", "matific"] as const) {
    if (modulos[p]) plataformas[p] = usoDaPlataforma(p, escola, cartao?.total_alunos);
  }
  const geral = situacaoGeral(Object.values(plataformas));
  // "Sem uso registrado" com a coleta PARCIAL de alguma plataforma: o zero só vale até a data mais
  // antiga das parciais (o resto do ano não foi medido) — a tela escreve a data junto.
  const parciais = geral === "sem_uso"
    ? (Object.keys(plataformas) as Plataforma[]).filter((p) => coletaParcial(p, escola)).map((p) => plataformas[p]!.ate)
    : [];
  const datas = parciais.filter((d): d is string => d != null);
  return {
    escolaId: cartao?.escola_id ?? escola!.escola_id,
    nome: cartao?.nome ?? escola!.nome,
    ativa: cartao ? cartao.status === "ativa" : null,
    alunos: cartao ? cartao.total_alunos : null,
    geral,
    parcialGeral: parciais.length > 0,
    ateGeral: parciais.length > 0 && datas.length === parciais.length ? maisAntiga(datas) : null,
    plataformas,
  };
}

type GeralDaEscola = Pick<SituacaoEscola, "geral" | "parcialGeral" | "ateGeral">;

/** O complemento da situação geral "sem uso registrado" com coleta PARCIAL: "até 15/03/2026
 *  (coleta parcial)" (sem a data: "(coleta parcial)"). null nos outros casos. */
export function complementoDoGeral(s: GeralDaEscola): string | null {
  if (s.geral !== "sem_uso" || !s.parcialGeral) return null;
  return s.ateGeral ? `até ${s.ateGeral} (coleta parcial)` : "(coleta parcial)";
}

/** A situação geral por extenso: "Com uso no ano letivo", "Sem uso registrado", "Sem uso
 *  registrado até 15/03/2026 (coleta parcial)"… */
export function rotuloGeral(s: GeralDaEscola): string {
  const complemento = complementoDoGeral(s);
  return complemento ? `${ROTULO_ESTADO[s.geral]} ${complemento}` : ROTULO_ESTADO[s.geral];
}

/** As datas (`ateGeral`) das escolas "sem uso registrado" com coleta parcial — uma por escola
 *  (null: parcial sem a data). Para a contagem por extenso (`textoDemaisSituacoes`). */
export function datasDoSemUsoParcial(lista: SituacaoEscola[]): (string | null)[] {
  return lista.filter((s) => s.geral === "sem_uso" && s.parcialGeral).map((s) => s.ateGeral);
}

/** O cadastro de uma escola (do painel), SEM a situação de uso: a base da lista do Panorama
 *  quando a leitura do uso (`/analise/plataformas`) falha — nunca vira "sem uso" nem "sem dado". */
export type EscolaDoCadastro = Pick<SituacaoEscola, "escolaId" | "nome" | "ativa" | "alunos">;

/** TODAS as escolas do painel (inativas e sem alunos inclusive), em ordem alfabética, só com o
 *  cadastro e os alunos — o mesmo recorte de `classificarRede`, sem decidir nada sobre uso. */
export function escolasDoCadastro(cartoes: EscolaCartao[]): EscolaDoCadastro[] {
  return porNome(cartoes.map((c) => ({
    escolaId: c.escola_id, nome: c.nome, ativa: c.status === "ativa", alunos: c.total_alunos,
  })));
}

/** TODAS as escolas da rede (a base é o painel, que traz inativas e sem alunos), em ordem
 *  alfabética — mais alguma que só a análise traga. */
export function classificarRede(cartoes: EscolaCartao[], plataformas: RespostaPlataformas): SituacaoEscola[] {
  const daAnalise = new Map(plataformas.escolas.map((e) => [e.escola_id, e]));
  const ids = new Set(cartoes.map((c) => c.escola_id));
  const lista = cartoes.map((c) => classificarEscola(c, daAnalise.get(c.escola_id), plataformas.modulos));
  for (const e of plataformas.escolas) {
    if (!ids.has(e.escola_id)) lista.push(classificarEscola(undefined, e, plataformas.modulos));
  }
  return porNome(lista);
}

export function contarSituacoes(lista: SituacaoEscola[]): Record<EstadoUso, number> {
  const conta: Record<EstadoUso, number> = { com_uso: 0, sem_uso: 0, sem_dado: 0, protegido: 0 };
  for (const s of lista) conta[s.geral] += 1;
  return conta;
}
