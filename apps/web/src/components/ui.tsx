/** Componentes básicos reutilizáveis (PRD §25) — a base visual do sistema. */
import { useEffect } from "react";
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

export function Modal({
  titulo,
  aberto,
  aoFechar,
  children,
}: {
  titulo: string;
  aberto: boolean;
  aoFechar: () => void;
  children: ReactNode;
}) {
  // Trava o scroll do fundo enquanto o modal está aberto (evita "vazar" o
  // rolar por trás no iOS). O cleanup restaura o estado anterior.
  useEffect(() => {
    if (!aberto) return;
    const anterior = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = anterior;
    };
  }, [aberto]);

  if (!aberto) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <button
        aria-label="Fechar janela"
        className="absolute inset-0 bg-zinc-950/50"
        onClick={aoFechar}
      />
      {/* dvh: no iOS Safari a caixa nunca estoura o viewport visível quando a
          barra de URL aparece/some. overscroll-contain corta o scroll chaining. */}
      <div className="relative max-h-[90dvh] w-full max-w-lg overflow-y-auto overscroll-contain rounded-xl border border-zinc-200 bg-white p-5 shadow-xl dark:border-zinc-700 dark:bg-zinc-900">
        <h2 className="mb-4 text-base font-semibold tracking-tight">{titulo}</h2>
        {children}
      </div>
    </div>
  );
}

export function Drawer({
  titulo,
  aberto,
  aoFechar,
  children,
}: {
  titulo: string;
  aberto: boolean;
  aoFechar: () => void;
  children: ReactNode;
}) {
  useEffect(() => {
    if (!aberto) return;
    const anterior = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const aoTecla = (evento: KeyboardEvent) => {
      if (evento.key === "Escape") aoFechar();
    };
    window.addEventListener("keydown", aoTecla);
    return () => {
      document.body.style.overflow = anterior;
      window.removeEventListener("keydown", aoTecla);
    };
  }, [aberto, aoFechar]);

  if (!aberto) return null;
  return (
    <div className="fixed inset-0 z-50">
      <button
        aria-label="Fechar painel"
        className="absolute inset-0 bg-zinc-950/50"
        onClick={aoFechar}
      />
      <aside
        role="dialog"
        aria-label={titulo}
        className="absolute inset-y-0 right-0 flex w-full max-w-md flex-col border-l border-zinc-200 bg-white shadow-2xl dark:border-zinc-700 dark:bg-zinc-900"
      >
        <div className="flex items-center justify-between border-b border-zinc-200 px-5 py-3.5 dark:border-zinc-800">
          <h2 className="text-base font-semibold tracking-tight">{titulo}</h2>
          <button
            aria-label="Fechar"
            className="rounded-lg p-1.5 text-zinc-500 transition-colors hover:bg-zinc-100 hover:text-zinc-800 dark:hover:bg-zinc-800 dark:hover:text-zinc-100"
            onClick={aoFechar}
          >
            <span aria-hidden className="block h-4 w-4 leading-none">✕</span>
          </button>
        </div>
        <div className="flex-1 overflow-y-auto overscroll-contain p-5">{children}</div>
      </aside>
    </div>
  );
}

export function Campo({
  rotulo,
  children,
}: {
  rotulo: string;
  children: ReactNode;
}) {
  return (
    <label className="block text-sm">
      <span className="mb-1 block font-medium text-zinc-700 dark:text-zinc-300">{rotulo}</span>
      {children}
    </label>
  );
}

export const estiloInput =
  "w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-900";
