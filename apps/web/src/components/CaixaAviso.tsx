/**
 * Caixa de aviso (callout) da identidade visual v2: cartão arredondado em tom pastel,
 * ícone num quadradinho branco e o texto em cor escura (contraste AA nos dois temas).
 *
 * Existe porque `Mensagem` (ui.tsx) só tem "ok" e "erro": aviso que NÃO é erro
 * ("nenhuma turma cadastrada", "agendador desligado", "cobertura parcial") acabava
 * pintado de vermelho e anunciado como alerta. Aqui o tom e o papel de anúncio são
 * escolhas separadas: `role` só quando o conteúdo é uma mensagem de estado.
 */
import type { ReactNode } from "react";
import { AlertTriangle, CheckCircle2, Info, XCircle } from "lucide-react";
import type { LucideIcon } from "lucide-react";

export type TomAviso = "alerta" | "erro" | "info" | "ok" | "neutro";

const ESTILO: Record<TomAviso, { caixa: string; icone: string; padrao: LucideIcon }> = {
  alerta: {
    caixa: "border-ouro-200 bg-ouro-50 dark:border-ouro-400/25 dark:bg-ouro-400/10",
    icone: "text-ouro-700 dark:text-ouro-300",
    padrao: AlertTriangle,
  },
  erro: {
    caixa: "border-rose-200 bg-rose-50 dark:border-rose-500/25 dark:bg-rose-500/10",
    icone: "text-rose-600 dark:text-rose-300",
    padrao: XCircle,
  },
  info: {
    caixa: "border-sky-200 bg-sky-50/70 dark:border-sky-500/25 dark:bg-sky-500/10",
    icone: "text-sky-600 dark:text-sky-300",
    padrao: Info,
  },
  ok: {
    caixa: "border-emerald-200 bg-emerald-50/70 dark:border-emerald-500/25 dark:bg-emerald-500/10",
    icone: "text-emerald-600 dark:text-emerald-300",
    padrao: CheckCircle2,
  },
  neutro: {
    caixa: "border-zinc-200 bg-zinc-50 dark:border-zinc-800 dark:bg-zinc-800/40",
    icone: "text-zinc-500 dark:text-zinc-300",
    padrao: Info,
  },
};

export function CaixaAviso({
  tom = "alerta",
  icone,
  titulo,
  children,
  role,
  acoes,
  className = "",
  testId,
}: {
  tom?: TomAviso;
  icone?: LucideIcon;
  titulo?: ReactNode;
  children?: ReactNode;
  /** "alert" (urgente) ou "status" (educado); sem role, é só conteúdo da página. */
  role?: "alert" | "status";
  /** Botões/links da caixa (ficam embaixo do texto). */
  acoes?: ReactNode;
  className?: string;
  testId?: string;
}) {
  const estilo = ESTILO[tom];
  const Icone = icone ?? estilo.padrao;
  return (
    <div
      role={role}
      data-testid={testId}
      className={`flex items-start gap-3 rounded-2xl border px-4 py-3.5 text-sm text-zinc-800 dark:text-zinc-100 ${estilo.caixa} ${className}`}
    >
      <span
        aria-hidden
        className={`grid h-8 w-8 shrink-0 place-items-center rounded-xl bg-white shadow-sm dark:bg-zinc-900/70 ${estilo.icone}`}
      >
        <Icone size={16} strokeWidth={2.2} />
      </span>
      <div className="min-w-0 flex-1 space-y-1 pt-1">
        {titulo && <p className="font-semibold">{titulo}</p>}
        {children}
        {acoes && <div className="flex flex-wrap items-center gap-2 pt-2">{acoes}</div>}
      </div>
    </div>
  );
}
