/**
 * Tipos da emissão de certificados EM LOTE (identidade visual v2, D7).
 *
 * Contrato das rotas (backend/app/routers/certificados_lote.py; as guardas por aluno
 * vêm de routers/relatorios.py), só leitura até a geração:
 *   POST /escolas/{id}/certificados/lote/previa  {modelo, aluno_ids}            → PreviaCertificados
 *   POST /escolas/{id}/certificados/lote         {modelo, bimestre, aluno_ids}  → application/pdf
 *        (nenhum apto → 422 {detail, itens[...]} no mesmo formato da prévia)
 *
 * As guardas por aluno são as MESMAS da rota individual
 * GET /escolas/{id}/certificados/{aluno_id}: módulo, aluno da escola, professor só os
 * seus, ativo, 1º–5º ano, Lista Piloto e (só no Geral) mérito. Recusado NÃO é
 * substituído pelo próximo colocado.
 */

import { bimestreDeHoje, bimestreEmCurso, type CalendarioDoAno } from "./calendarioBimestres";

/** `null` = certificado Geral (de mérito, com nota e posição); as artes das plataformas são de desempenho, sem nota nem posição. */
export type ModeloCertificado = "elefante" | "matific" | null;

/** Teto de alunos por lote (a rota é síncrona e recusa acima disso). */
export const MAX_CERTIFICADOS_LOTE = 50;

/**
 * Bimestre que o lote abre marcado quando a lista da tela É de um bimestre (preset do
 * período global), espelhando `backend/app/services/periodos.py`:
 *   - "bimestre_N" → N (o 3º fechado, premiado em 31/10, abre no 3º, não no 4º);
 *   - "bimestre" (este bimestre) → o de hoje, pela mesma sugestão do backend;
 *   - "bimestre_anterior" → o anterior ao bimestre em curso (do 1º, volta ao 4º); fora
 *     do calendário oficial (recesso, ano sem calendário) não dá para afirmar → undefined.
 * Outro período (mês, ano letivo, personalizado...) → undefined: o modal abre no
 * bimestre de hoje. É só a sugestão inicial; o número impresso é o que a pessoa escolher.
 *
 * `calendario` é o do backend (`useCalendarioBimestres`); sem ele só 2026 é conhecido, e
 * ano sem calendário dá undefined — antes "Este bimestre" em 2027 sugeria sempre o 1º.
 */
export function bimestreDoPeriodo(
  preset: string,
  hoje: Date = new Date(),
  calendario?: CalendarioDoAno | null,
): number | undefined {
  const pedido = /^bimestre_([1-4])$/.exec(preset);
  if (pedido) return Number(pedido[1]);
  if (preset === "bimestre") return bimestreDeHoje(hoje, calendario) ?? undefined;
  if (preset === "bimestre_anterior") {
    const atual = bimestreEmCurso(hoje, calendario);
    if (!atual) return undefined;
    return atual.numero > 1 ? atual.numero - 1 : 4;
  }
  return undefined;
}

/**
 * Uma linha da lista ORDENADA que a tela está mostrando (ranking, premiação...).
 * `aluno_id` nulo = linha sem ficha vinculada (ex.: placar ao vivo do Matific que
 * não casou com um aluno): fica de fora do lote, com aviso.
 */
export interface AlunoParaCertificado {
  aluno_id: number | null;
  nome: string | null;
  turma?: string | null;
  /** Posição que a TELA mostra (nunca o índice da lista). */
  posicao?: number | null;
}

export interface PedidoPreviaCertificados {
  modelo: ModeloCertificado;
  /** 1 a 50, na ordem da lista, sem repetidos. */
  aluno_ids: number[];
}

export interface PedidoLoteCertificados extends PedidoPreviaCertificados {
  /** Bimestre impresso na arte da plataforma (1–4); o Geral não imprime bimestre (null). */
  bimestre: number | null;
}

export interface ItemPreviaCertificado {
  aluno_id: number;
  /** null quando o aluno não foi encontrado/não é permitido (para não vazar dado). */
  nome: string | null;
  turma: string | null;
  apto: boolean;
  /** Motivo da recusa, com o texto do backend (o mesmo dos 409/422 da rota individual). */
  motivo: string | null;
}

export interface PreviaCertificados {
  modelo: ModeloCertificado;
  itens: ItemPreviaCertificado[];
}
