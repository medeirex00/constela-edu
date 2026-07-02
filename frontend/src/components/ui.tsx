/** Componentes básicos reutilizáveis (PRD §25) — a base visual do sistema. */
import type { ButtonHTMLAttributes, ReactNode } from "react";

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`card ${className}`}>{children}</div>;
}

export function PageHeader({ titulo, descricao, acoes }: { titulo: string; descricao?: string; acoes?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">{titulo}</h1>
        {descricao && <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">{descricao}</p>}
      </div>
      {acoes}
    </div>
  );
}

export function StatCard({ icone, rotulo, valor, detalhe }: { icone: ReactNode; rotulo: string; valor: string; detalhe?: string }) {
  return (
    <Card className="p-4">
      <div className="flex items-center gap-2 text-zinc-500 dark:text-zinc-400">
        {icone}
        <span className="text-xs font-medium uppercase tracking-wide">{rotulo}</span>
      </div>
      <p className="mt-2 text-2xl font-semibold tabular-nums tracking-tight">{valor}</p>
      {detalhe && <p className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">{detalhe}</p>}
    </Card>
  );
}

type BotaoProps = ButtonHTMLAttributes<HTMLButtonElement> & { variante?: "primario" | "neutro" };

export function Botao({ variante = "primario", className = "", ...props }: BotaoProps) {
  const estilos =
    variante === "primario"
      ? "bg-indigo-600 text-white hover:bg-indigo-500 disabled:bg-zinc-300 dark:disabled:bg-zinc-700 disabled:text-zinc-500"
      : "border border-zinc-300 bg-white text-zinc-700 hover:bg-zinc-50 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-200 dark:hover:bg-zinc-800";
  return (
    <button
      className={`inline-flex items-center justify-center gap-2 rounded-lg px-3.5 py-2 text-sm font-medium transition-colors disabled:cursor-not-allowed ${estilos} ${className}`}
      {...props}
    />
  );
}

export function Badge({ children, tom = "neutro" }: { children: ReactNode; tom?: "neutro" | "destaque" | "ok" | "alerta" }) {
  const tons = {
    neutro: "bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300",
    destaque: "bg-indigo-50 text-indigo-700 dark:bg-indigo-500/10 dark:text-indigo-300",
    ok: "bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300",
    alerta: "bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300",
  } as const;
  return (
    <span className={`inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium ${tons[tom]}`}>
      {children}
    </span>
  );
}

export function Mensagem({ tipo, children }: { tipo: "ok" | "erro"; children: ReactNode }) {
  const estilos =
    tipo === "ok"
      ? "border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-500/20 dark:bg-emerald-500/10 dark:text-emerald-200"
      : "border-red-200 bg-red-50 text-red-800 dark:border-red-500/20 dark:bg-red-500/10 dark:text-red-200";
  return <div className={`rounded-lg border px-3 py-2 text-sm ${estilos}`}>{children}</div>;
}

export function Carregando({ texto = "Carregando..." }: { texto?: string }) {
  return (
    <div className="flex items-center justify-center gap-2 py-16 text-sm text-zinc-500 dark:text-zinc-400">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-zinc-300 border-t-indigo-600 dark:border-zinc-600" />
      {texto}
    </div>
  );
}

export function Vazio({ titulo, descricao }: { titulo: string; descricao?: string }) {
  return (
    <div className="py-16 text-center">
      <p className="text-sm font-medium">{titulo}</p>
      {descricao && <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">{descricao}</p>}
    </div>
  );
}

export function rotuloCampo(chave: string, rotulos: Record<string, string>): string {
  return rotulos[chave] ?? chave;
}
