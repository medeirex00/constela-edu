/**
 * TURNO escolar — vocabulário único do front (espelha `backend/app/services/
 * turnos.py`): códigos, rótulos, ordem de exibição e a tradução do filtro
 * GLOBAL de turno (AppContext) para a query string dos endpoints.
 *
 * O filtro global tem três formas:
 *   - `"todos"` → não filtra (o parâmetro `turno` NÃO é enviado);
 *   - `""`      → só as turmas SEM turno cadastrado (`Turma.turno = null`),
 *                 enviado como `turno=` (vazio);
 *   - `"manha"` etc. → o código exato.
 *
 * Nenhum rótulo de turno é escrito à mão nas telas: tudo passa por aqui.
 */
export const TURNOS = [
  { valor: "manha", rotulo: "Manhã" },
  { valor: "tarde", rotulo: "Tarde" },
  { valor: "noite", rotulo: "Noite" },
  { valor: "integral", rotulo: "Integral" },
] as const;

export type CodigoTurno = (typeof TURNOS)[number]["valor"];

/** Valor do filtro global que significa "todos os turnos" (não filtrar). */
export const TURNO_TODOS = "todos";
/** Valor do filtro global para as turmas SEM turno (`Turma.turno = null`). */
export const TURNO_SEM = "";

/** Rótulo de um turno cru (`Turma.turno`). `null`/vazio = "Sem turno"; um código
 *  desconhecido volta como está (nunca inventa um nome). */
export function rotuloTurno(codigo: string | null | undefined): string {
  if (codigo == null || codigo === TURNO_SEM) return "Sem turno";
  return TURNOS.find((t) => t.valor === codigo)?.rotulo ?? codigo;
}

/** Posição de exibição: manhã, tarde, noite, integral; códigos desconhecidos
 *  depois; "Sem turno" sempre por último. */
export function ordemTurno(codigo: string | null | undefined): number {
  if (codigo == null || codigo === TURNO_SEM) return TURNOS.length + 1;
  const indice = TURNOS.findIndex((t) => t.valor === codigo);
  return indice === -1 ? TURNOS.length : indice;
}

/** Chave estável para comparar turnos: `null` (sem turno) vira `""`. */
export function chaveTurno(codigo: string | null | undefined): string {
  return codigo ?? TURNO_SEM;
}

/** Query string do filtro global: `""` (não manda) para "todos", `turno=` para
 *  "Sem turno", `turno=<codigo>` para um turno. */
export function turnoParaQuery(turno: string): string {
  if (turno === TURNO_TODOS) return "";
  const q = new URLSearchParams();
  q.set("turno", turno);
  return q.toString();
}

/** Aplica o filtro global num `URLSearchParams` já montado (mesma regra de
 *  `turnoParaQuery`). Devolve o próprio objeto para encadear. */
export function aplicarTurno(params: URLSearchParams, turno: string): URLSearchParams {
  if (turno !== TURNO_TODOS) params.set("turno", turno);
  return params;
}

/** Turnos EXISTENTES numa lista de turmas, sem repetição e na ordem de exibição.
 *  `null` entra (por último) se alguma turma não tem turno. */
export function turnosDasTurmas(turmas: { turno: string | null }[]): (string | null)[] {
  const vistos = new Map<string, string | null>();
  for (const t of turmas) {
    const chave = chaveTurno(t.turno);
    if (!vistos.has(chave)) vistos.set(chave, t.turno ?? null);
  }
  return Array.from(vistos.values()).sort((a, b) =>
    ordemTurno(a) - ordemTurno(b) || chaveTurno(a).localeCompare(chaveTurno(b)));
}

/** Turno EFETIVO para a consulta: o valor persistido, se ele existir nas turmas
 *  desta escola; senão "todos". Não altera o que está guardado — o usuário que
 *  escolheu "Noite" numa escola continua com "Noite" ao voltar para ela. Com
 *  as turmas ainda não carregadas (`null`), devolve o valor como está. */
export function turnoEfetivo(
  turno: string, turmas: { turno: string | null }[] | null | undefined,
): string {
  if (turno === TURNO_TODOS || turmas == null) return turno;
  return turmas.some((t) => chaveTurno(t.turno) === turno) ? turno : TURNO_TODOS;
}
