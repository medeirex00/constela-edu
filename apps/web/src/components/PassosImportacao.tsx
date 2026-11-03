/**
 * Passo a passo das importações (envio → análise/conferência → confirmação): uma
 * fileira de bolinhas numeradas que diz em que etapa a pessoa está. É só orientação
 * visual — quem decide a etapa é a tela (estado real do fluxo), nunca este componente.
 *
 * Acessível: lista ordenada rotulada; a etapa atual leva aria-current="step" e as
 * concluídas dizem isso em texto (não só pela cor/ícone).
 *
 * Layout: a partir de 640 px os passos ficam SEMPRE numa linha só — quando falta
 * largura, o rótulo de cada passo quebra dentro dele ("Conferir turmas / e alunos").
 * Antes a fileira quebrava entre os passos: o 3º caía sozinho na linha de baixo e o
 * traço de ligação ficava pendurado no fim da primeira, apontando para o nada. No
 * celular os passos vão um embaixo do outro, sem traços.
 */
import { Check } from "lucide-react";

export function PassosImportacao({
  passos,
  atual,
  rotulo = "Etapas da importação",
  className = "",
}: {
  passos: readonly string[];
  /** Índice da etapa atual (0…n-1); `passos.length` = todas concluídas. */
  atual: number;
  rotulo?: string;
  className?: string;
}) {
  return (
    <ol aria-label={rotulo} className={`flex flex-col gap-2 sm:flex-row sm:items-center sm:gap-1.5 ${className}`}>
      {passos.map((passo, i) => {
        const feito = i < atual;
        const agora = i === atual;
        return (
          <li key={passo} aria-current={agora ? "step" : undefined} className="flex min-w-0 items-center gap-2">
            <span
              aria-hidden
              className={`grid h-7 w-7 shrink-0 place-items-center rounded-full text-xs font-bold tabular-nums transition-colors ${
                feito
                  ? "bg-emerald-500 text-white"
                  : agora
                    ? "bg-indigo-600 text-white shadow-pilula"
                    : "border border-zinc-200 bg-white text-zinc-500 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-400"
              }`}
            >
              {feito ? <Check size={14} strokeWidth={3} /> : i + 1}
            </span>
            <span
              className={`min-w-0 text-sm leading-snug ${
                agora
                  ? "font-semibold text-zinc-900 dark:text-white"
                  : feito
                    ? "font-medium text-zinc-700 dark:text-zinc-200"
                    : "text-zinc-500 dark:text-zinc-400"
              }`}
            >
              {passo}
              {feito && <span className="sr-only"> — feito</span>}
            </span>
            {i < passos.length - 1 && (
              <span aria-hidden className="mx-1.5 hidden h-px w-6 shrink-0 bg-zinc-300 dark:bg-zinc-700 sm:block lg:w-10" />
            )}
          </li>
        );
      })}
    </ol>
  );
}
