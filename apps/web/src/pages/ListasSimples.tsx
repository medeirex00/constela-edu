import { useEffect, useState } from "react";

import { Card, Carregando, PageHeader, Vazio } from "../components/ui";
import { useApp } from "../context/AppContext";
import { api } from "../lib/api";
import type { Professor } from "../lib/types";

// A gestão de turmas ganhou página própria: pages/Turmas.tsx

export function Professores() {
  const { escolaId } = useApp();
  const [professores, setProfessores] = useState<Professor[] | null>(null);

  useEffect(() => {
    if (!escolaId) return;
    setProfessores(null);
    api<Professor[]>(`/escolas/${escolaId}/professores`).then(setProfessores).catch(() => setProfessores([]));
  }, [escolaId]);

  return (
    <div>
      <PageHeader titulo="Professores" descricao="Equipe cadastrada nesta escola." />
      <Card>
        {professores === null ? (
          <Carregando />
        ) : professores.length === 0 ? (
          <Vazio titulo="Nenhum professor cadastrado" />
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-zinc-200 text-left text-xs uppercase tracking-wide text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
                <th className="px-4 py-2 font-medium">Nome</th>
                <th className="px-4 py-2 font-medium">E-mail</th>
              </tr>
            </thead>
            <tbody>
              {professores.map((professor) => (
                <tr key={professor.id} className="border-b border-zinc-100 last:border-0 dark:border-zinc-800/60">
                  <td className="px-4 py-2.5 font-medium">{professor.nome}</td>
                  <td className="px-4 py-2.5 text-zinc-500 dark:text-zinc-400">{professor.email ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  );
}
