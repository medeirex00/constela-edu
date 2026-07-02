import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { Card, Carregando, PageHeader, Vazio } from "../components/ui";
import { useApp } from "../context/AppContext";
import { api } from "../lib/api";
import type { Professor, Turma } from "../lib/types";

export function Turmas() {
  const { escolaId } = useApp();
  const [turmas, setTurmas] = useState<Turma[] | null>(null);

  useEffect(() => {
    if (!escolaId) return;
    setTurmas(null);
    api<Turma[]>(`/escolas/${escolaId}/turmas`).then(setTurmas).catch(() => setTurmas([]));
  }, [escolaId]);

  return (
    <div>
      <PageHeader titulo="Turmas" descricao="Turmas do ano letivo ativo." />
      <Card>
        {turmas === null ? (
          <Carregando />
        ) : turmas.length === 0 ? (
          <Vazio titulo="Nenhuma turma cadastrada" />
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-zinc-200 text-left text-xs uppercase tracking-wide text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
                <th className="px-4 py-2 font-medium">Turma</th>
                <th className="px-4 py-2 font-medium">Série</th>
                <th className="px-4 py-2 font-medium">Ano letivo</th>
              </tr>
            </thead>
            <tbody>
              {turmas.map((turma) => (
                <tr key={turma.id} className="border-b border-zinc-100 last:border-0 dark:border-zinc-800/60">
                  <td className="px-4 py-2.5">
                    <Link to={`/turmas/${turma.id}`} className="font-medium hover:text-indigo-600 dark:hover:text-indigo-400">
                      {turma.nome}
                    </Link>
                  </td>
                  <td className="px-4 py-2.5 text-zinc-500 dark:text-zinc-400">{turma.ano_escolar}</td>
                  <td className="px-4 py-2.5 text-zinc-500 dark:text-zinc-400">{turma.ano_letivo}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  );
}

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
