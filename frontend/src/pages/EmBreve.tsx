import { CalendarClock } from "lucide-react";

import { Card, PageHeader } from "../components/ui";

export default function EmBreve({ titulo, fase, descricao }: { titulo: string; fase: string; descricao: string }) {
  return (
    <div>
      <PageHeader titulo={titulo} />
      <Card className="flex flex-col items-center gap-3 px-6 py-14 text-center">
        <span className="flex h-11 w-11 items-center justify-center rounded-full bg-indigo-50 text-indigo-600 dark:bg-indigo-500/10 dark:text-indigo-400">
          <CalendarClock size={20} />
        </span>
        <p className="text-sm font-semibold">Planejado para a {fase}</p>
        <p className="max-w-md text-sm text-zinc-500 dark:text-zinc-400">{descricao}</p>
        <p className="text-xs text-zinc-400 dark:text-zinc-500">
          O roteiro completo está em <code>docs/ROADMAP.md</code>.
        </p>
      </Card>
    </div>
  );
}
