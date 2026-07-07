/** Painel lateral: escolher a turma, achar o aluno (busca + alfabética) e
 *  confirmar o vínculo de um relatório individual. Usado na importação
 *  de um PDF e na importação em lote. */
import { ChevronRight, Search, UserCheck } from "lucide-react";
import { useEffect, useState } from "react";

import { api } from "../lib/api";
import { normalizar } from "../lib/nomes";
import type { Aluno, PaginaAlunos, Turma } from "../lib/types";
import { Botao, Campo, Card, Carregando, Drawer, estiloInput } from "./ui";

export default function SeletorAlunoDrawer({
  escolaId,
  aberto,
  turmas,
  turmaInicial,
  nomePdf,
  aoFechar,
  aoConfirmar,
}: {
  escolaId: number;
  aberto: boolean;
  turmas: Turma[];
  turmaInicial: number | null;
  nomePdf: string;
  aoFechar: () => void;
  aoConfirmar: (aluno: Aluno, turmaNome: string) => void;
}) {
  const [turmaId, setTurmaId] = useState<number | null>(turmaInicial);
  const [alunos, setAlunos] = useState<Aluno[] | null>(null);
  const [busca, setBusca] = useState("");
  const [selecionado, setSelecionado] = useState<Aluno | null>(null);

  useEffect(() => {
    if (aberto) {
      setTurmaId(turmaInicial ?? turmas[0]?.id ?? null);
      setBusca("");
      setSelecionado(null);
    }
  }, [aberto, turmaInicial, turmas]);

  useEffect(() => {
    if (!aberto || !turmaId) {
      setAlunos(null);
      return;
    }
    setAlunos(null);
    api<PaginaAlunos>(`/escolas/${escolaId}/alunos?turma_id=${turmaId}&por_pagina=100`)
      .then((r) => setAlunos(r.itens))
      .catch(() => setAlunos([]));
  }, [aberto, turmaId, escolaId]);

  const turmaNome = turmas.find((t) => t.id === turmaId)?.nome ?? "";
  const filtrados = (alunos ?? [])
    .filter((a) => normalizar(a.nome).includes(normalizar(busca)))
    .sort((a, b) => a.nome.localeCompare(b.nome, "pt-BR"));

  return (
    <Drawer titulo="Alterar aluno" aberto={aberto} aoFechar={aoFechar}>
      {selecionado ? (
        <div className="space-y-4">
          <p className="text-sm text-zinc-600 dark:text-zinc-300">Este relatório será vinculado ao aluno:</p>
          <Card className="p-4">
            <p className="text-lg font-semibold tracking-tight">{selecionado.nome}</p>
            <p className="mt-0.5 text-sm text-zinc-500 dark:text-zinc-400">Turma: {turmaNome}</p>
          </Card>
          <p className="text-xs text-zinc-500 dark:text-zinc-400">
            As leituras, a pontuação e todo o histórico do PDF passarão a pertencer a este aluno.
          </p>
          <div className="flex justify-end gap-2">
            <Botao variante="neutro" onClick={() => setSelecionado(null)}>Cancelar</Botao>
            <Botao onClick={() => aoConfirmar(selecionado, turmaNome)}>
              <UserCheck size={15} /> Confirmar
            </Botao>
          </div>
        </div>
      ) : (
        <div className="space-y-4">
          <div>
            <p className="mb-2 text-xs font-medium uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
              Aluno do relatório (PDF)
            </p>
            <p className="text-sm font-medium">{nomePdf || "—"}</p>
          </div>

          <Campo rotulo="1. Selecione a turma">
            <select
              className={estiloInput}
              value={turmaId ?? ""}
              onChange={(e) => setTurmaId(Number(e.target.value))}
            >
              {turmas.length === 0 && <option value="">Nenhuma turma cadastrada</option>}
              {turmas.map((turma) => (
                <option key={turma.id} value={turma.id}>{turma.nome}</option>
              ))}
            </select>
          </Campo>

          <div>
            <p className="mb-1.5 text-sm font-medium text-zinc-700 dark:text-zinc-300">2. Escolha o aluno</p>
            <label className="relative block">
              <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-zinc-400" />
              <input
                className={`${estiloInput} pl-9`}
                placeholder="Pesquisar por nome..."
                value={busca}
                onChange={(e) => setBusca(e.target.value)}
              />
            </label>
          </div>

          <div className="max-h-[45vh] overflow-y-auto rounded-lg border border-zinc-200 dark:border-zinc-800">
            {alunos === null ? (
              <Carregando />
            ) : filtrados.length === 0 ? (
              <p className="py-8 text-center text-sm text-zinc-400">
                {busca ? "Nenhum aluno encontrado." : "Turma sem alunos."}
              </p>
            ) : (
              <ul className="divide-y divide-zinc-100 dark:divide-zinc-800/60">
                {filtrados.map((aluno) => (
                  <li key={aluno.id}>
                    <button
                      className="flex w-full items-center gap-3 px-3 py-2.5 text-left transition-colors hover:bg-zinc-50 dark:hover:bg-zinc-800/60"
                      onClick={() => setSelecionado(aluno)}
                    >
                      <span className="flex h-8 w-8 shrink-0 items-center justify-center overflow-hidden rounded-full bg-indigo-100 text-xs font-semibold text-indigo-700 dark:bg-indigo-500/20 dark:text-indigo-300">
                        {aluno.foto_url ? (
                          <img src={aluno.foto_url} alt="" className="h-full w-full object-cover" />
                        ) : (
                          aluno.nome.slice(0, 1).toUpperCase()
                        )}
                      </span>
                      <span className="min-w-0 flex-1 truncate text-sm font-medium">{aluno.nome}</span>
                      <ChevronRight size={15} className="shrink-0 text-zinc-300 dark:text-zinc-600" />
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}
    </Drawer>
  );
}
