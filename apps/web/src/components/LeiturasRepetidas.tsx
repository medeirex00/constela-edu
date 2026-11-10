/**
 * O que a fusão faz com os livros que estão nas DUAS fichas (A7).
 *
 * A regra não muda aqui (decisão do dono): fica a data da ficha principal e a da
 * outra é descartada. Esta peça só diz isso ANTES do FUNDIR — e diz quando a data
 * descartada era a que fazia o livro contar num bimestre, porque é aí que o
 * pódio muda sem ninguém perceber. O cálculo é do backend
 * (`GET /alunos/fundir/previa` e `GET /alunos/duplicados`).
 */
import { CalendarClock } from "lucide-react";

export interface ResumoLeiturasRepetidas {
  livros_repetidos: number;
  com_data_diferente: number;
  /** Livros que deixam de contar no bimestre da premiação (null: sem calendário). */
  no_bimestre: number | null;
  bimestre: { numero: number; rotulo: string; inicio: string; fim: string } | null;
  por_bimestre: { numero: number; rotulo: string; livros: number }[];
  exemplos: {
    livro_id: number;
    livro?: string | null;
    data_manter: string;
    data_remover: string;
    deixa_de_contar_em: number | null;
  }[];
}

/** "2026-03-25" → "25/03/2026" (é data, não instante: sem fuso). */
export function dataCurta(iso: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  return m ? `${m[3]}/${m[2]}/${m[1]}` : iso;
}

function livros(n: number): string {
  return `${n} livro${n === 1 ? "" : "s"}`;
}

/** "1 no 3º bimestre (o bimestre atual) e 2 no 1º bimestre". */
export function textoBimestres(r: ResumoLeiturasRepetidas): string {
  const partes = r.por_bimestre.map((b) => {
    const premiado = r.bimestre?.numero === b.numero ? " (o bimestre atual)" : "";
    return `${b.livros} no ${b.rotulo}${premiado}`;
  });
  if (partes.length <= 1) return partes.join("");
  return `${partes.slice(0, -1).join(", ")} e ${partes[partes.length - 1]}`;
}

export default function LeiturasRepetidas({ resumo, nomeFica, nomeSai, dica }: {
  resumo: ResumoLeiturasRepetidas;
  nomeFica: string;
  nomeSai: string;
  /** O que fazer se a data certa for a outra (muda com a tela). */
  dica?: string;
}) {
  if (resumo.livros_repetidos === 0) return null;
  if (resumo.com_data_diferente === 0) {
    return (
      <p className="text-xs text-zinc-500 dark:text-zinc-400">
        {livros(resumo.livros_repetidos)} {resumo.livros_repetidos === 1 ? "está" : "estão"} nas
        duas fichas com a mesma data: a fusão mantém uma leitura de cada e nenhum período muda.
      </p>
    );
  }
  const muda = resumo.por_bimestre.length > 0;
  return (
    <div role="note" aria-label="Livros repetidos com data diferente"
         className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-100">
      <p className="flex items-start gap-2 font-medium">
        <CalendarClock size={16} aria-hidden className="mt-0.5 shrink-0" />
        <span>
          {livros(resumo.com_data_diferente)} {resumo.com_data_diferente === 1 ? "está" : "estão"} nas
          duas fichas com datas diferentes. Fica a data de “{nomeFica}”; a de “{nomeSai}” é descartada.
        </span>
      </p>
      <p className="mt-1 text-xs">
        {muda
          ? <>Com isso, deixam de contar: <strong>{textoBimestres(resumo)}</strong>.</>
          : resumo.bimestre
            ? "Nenhum desses livros muda de bimestre."
            : "Este ano letivo não tem calendário oficial de bimestres cadastrado: não dá para dizer em qual bimestre cada livro conta."}
      </p>
      {resumo.exemplos.length > 0 && (
        <ul className="mt-2 space-y-0.5 text-xs">
          {resumo.exemplos.slice(0, 5).map((e) => (
            <li key={e.livro_id}>
              • {e.livro ?? `livro ${e.livro_id}`}: fica {dataCurta(e.data_manter)}, sai{" "}
              {dataCurta(e.data_remover)}
              {e.deixa_de_contar_em ? ` (deixa de contar no ${e.deixa_de_contar_em}º bimestre)` : ""}
            </li>
          ))}
          {resumo.com_data_diferente > 5 && (
            <li>• e mais {livros(resumo.com_data_diferente - 5)}.</li>
          )}
        </ul>
      )}
      {dica && <p className="mt-2 text-xs">{dica}</p>}
    </div>
  );
}
