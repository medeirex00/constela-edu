/**
 * Peças comuns da aba "IDEB e SAEB" (por escola — `AbaIDEB` — e da rede municipal —
 * `RedeIDEB`): bloco com título, aviso, nota, seletor rotulado e a situação "atingiu /
 * não atingiu" da meta. Só apresentação; os textos vêm da API.
 */
import { AlertTriangle, Info } from "lucide-react";
import { type ReactNode, useId } from "react";

import { Badge } from "../../components/ui";
import { diferencaIDEB, type ComparacaoMeta } from "./ideb";

export function Bloco({ titulo, children, testId }: { titulo: string; children: ReactNode; testId?: string }) {
  return (
    <section className="space-y-2" aria-label={titulo} data-testid={testId}>
      <h3 className="text-[15px] font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">{titulo}</h3>
      {children}
    </section>
  );
}

export function Aviso({ children, testId }: { children: ReactNode; testId?: string }) {
  return (
    <div className="flex items-start gap-2 rounded-xl border border-amber-200/70 bg-amber-50 p-3 text-xs text-amber-800 dark:border-amber-500/20 dark:bg-amber-500/10 dark:text-amber-300"
         data-testid={testId}>
      <AlertTriangle size={14} className="mt-0.5 shrink-0" aria-hidden="true" />
      <div className="min-w-0 space-y-1 break-words">{children}</div>
    </div>
  );
}

export function Nota({ children, testId }: { children: ReactNode; testId?: string }) {
  return (
    <div className="flex items-start gap-2 rounded-xl bg-indigo-50 p-3 text-xs text-indigo-800 dark:bg-indigo-500/10 dark:text-indigo-300"
         data-testid={testId}>
      <Info size={14} className="mt-0.5 shrink-0" aria-hidden="true" />
      <div className="min-w-0 space-y-1 break-words">{children}</div>
    </div>
  );
}

/** Seletor de edição, de escola ou de componente (rótulo visível, ligado ao campo). */
export function Seletor<T extends string | number>({ rotulo, valor, opcoes, aoMudar }: {
  rotulo: string; valor: T; opcoes: { valor: T; texto: string }[]; aoMudar: (v: T) => void;
}) {
  const id = useId();
  return (
    <div className="flex flex-wrap items-center gap-2 text-xs text-zinc-600 dark:text-zinc-300">
      <label htmlFor={id}>{rotulo}</label>
      <select id={id} value={String(valor)}
              onChange={(e) => {
                const escolhida = opcoes.find((o) => String(o.valor) === e.target.value);
                if (escolhida) aoMudar(escolhida.valor);
              }}
              className="min-w-0 max-w-full rounded-xl border border-zinc-300 bg-white px-2.5 py-1.5 text-sm text-zinc-900 transition-colors hover:border-zinc-400 focus:border-indigo-500 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100">
        {opcoes.map((o) => <option key={String(o.valor)} value={String(o.valor)}>{o.texto}</option>)}
      </select>
    </div>
  );
}

/** "atingiu (+0,3)" / "não atingiu (−0,8)" — o texto diz a situação (a cor não é o único código). */
export function Situacao({ c }: { c: ComparacaoMeta }) {
  const dif = ` (${diferencaIDEB(c.diferenca, c.casas_decimais)})`;
  if (c.situacao === "atingiu") return <Badge tom="ok">atingiu{dif}</Badge>;
  return <Badge tom="alerta">não atingiu{dif}</Badge>;
}
