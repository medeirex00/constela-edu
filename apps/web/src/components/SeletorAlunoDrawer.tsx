/** Painel lateral: escolher a turma, achar o aluno (busca + alfabética) e
 *  confirmar o vínculo de um relatório individual. Usado na importação
 *  de um PDF e na importação em lote. */
import { ChevronRight, FileText, UserCheck } from "lucide-react";
import { useEffect, useState } from "react";

import { useApi } from "../hooks/useApi";
import { normalizar } from "../lib/nomes";
import type { Aluno, PaginaAlunos, Turma } from "../lib/types";
import { AvatarAluno, CampoBusca, SelectNativo } from "./PessoasUi";
import { Botao, Campo, Carregando, Chip, Drawer, IconePastel, RotuloSecao } from "./ui";

export default function SeletorAlunoDrawer({
  escolaId,
  aberto,
  turmas,
  turmaInicial,
  nomePdf,
  aoFechar,
  aoConfirmar,
  erroTurmas = null,
}: {
  escolaId: number;
  aberto: boolean;
  turmas: Turma[];
  turmaInicial: number | null;
  nomePdf: string;
  aoFechar: () => void;
  aoConfirmar: (aluno: Aluno, turmaNome: string) => void;
  /** A lista de turmas da escola NÃO carregou (o GET /turmas falhou): sem turmas,
   *  o seletor não pode dizer "Nenhuma turma cadastrada" — a escola tem turmas. */
  erroTurmas?: string | null;
}) {
  const [turmaId, setTurmaId] = useState<number | null>(turmaInicial);
  const [busca, setBusca] = useState("");
  const [selecionado, setSelecionado] = useState<Aluno | null>(null);

  useEffect(() => {
    if (aberto) {
      setTurmaId(turmaInicial ?? turmas[0]?.id ?? null);
      setBusca("");
      setSelecionado(null);
    }
  }, [aberto, turmaInicial, turmas]);

  // Alunos da turma escolhida — só busca com o painel aberto e uma turma definida.
  const { dados: pagina, erro, carregando } = useApi<PaginaAlunos>(
    aberto && turmaId ? `/escolas/${escolaId}/alunos?turma_id=${turmaId}&por_pagina=100` : null,
  );

  const turmaNome = turmas.find((t) => t.id === turmaId)?.nome ?? "";
  const filtrados = (pagina?.itens ?? [])
    .filter((a) => normalizar(a.nome).includes(normalizar(busca)))
    .sort((a, b) => a.nome.localeCompare(b.nome, "pt-BR"));
  // A consulta traz até 100 alunos: numa turma maior, a lista avisa que está cortada.
  const cortada = pagina != null && pagina.total > pagina.itens.length;

  return (
    <Drawer titulo="Alterar aluno" aberto={aberto} aoFechar={aoFechar}>
      {selecionado ? (
        <div className="space-y-4">
          <p className="text-sm text-zinc-600 dark:text-zinc-300">Este relatório será vinculado ao aluno:</p>
          <div className="flex items-center gap-4 rounded-2xl border border-indigo-100 bg-indigo-50 p-4 dark:border-indigo-500/20 dark:bg-indigo-500/10">
            <AvatarAluno nome={selecionado.nome} chave={selecionado.id} foto={selecionado.foto_url} tamanho="lg" />
            <div className="min-w-0">
              <p className="text-lg font-bold leading-tight tracking-tight text-zinc-900 dark:text-white">{selecionado.nome}</p>
              <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-300">Turma: {turmaNome}</p>
            </div>
          </div>
          <p className="text-xs text-zinc-500 dark:text-zinc-400">
            As leituras, a pontuação e todo o histórico do PDF passarão a pertencer a este aluno.
          </p>
          <div className="flex justify-end gap-2.5">
            <Botao variante="secundario" onClick={() => setSelecionado(null)}>Cancelar</Botao>
            <Botao onClick={() => aoConfirmar(selecionado, turmaNome)}>
              <UserCheck size={16} aria-hidden /> Confirmar
            </Botao>
          </div>
        </div>
      ) : (
        <div className="space-y-5">
          <div className="flex items-center gap-3 rounded-2xl bg-zinc-50 p-3.5 dark:bg-zinc-800/50">
            <IconePastel icone={FileText} tom="violeta" tamanho="sm" />
            <div className="min-w-0">
              <RotuloSecao>Aluno do relatório (PDF)</RotuloSecao>
              <p className="truncate text-sm font-semibold text-zinc-900 dark:text-zinc-100" title={nomePdf || "—"}>{nomePdf || "—"}</p>
            </div>
          </div>

          <Campo rotulo="1. Selecione a turma">
            <SelectNativo
              className="w-full"
              value={turmaId ?? ""}
              onChange={(e) => setTurmaId(Number(e.target.value))}
            >
              {turmas.length === 0 && (
                <option value="">{erroTurmas ? "As turmas não carregaram" : "Nenhuma turma cadastrada"}</option>
              )}
              {turmas.map((turma) => (
                <option key={turma.id} value={turma.id}>{turma.nome}</option>
              ))}
            </SelectNativo>
          </Campo>

          <div>
            <p className="mb-1.5 text-sm font-medium text-zinc-700 dark:text-zinc-300">2. Escolha o aluno</p>
            <CampoBusca
              rotulo="Pesquisar aluno por nome"
              placeholder="Pesquisar por nome..."
              value={busca}
              onChange={(e) => setBusca(e.target.value)}
            />
          </div>

          {cortada && pagina && (
            <p role="note" className="rounded-xl border border-amber-200 bg-amber-50 px-3.5 py-2.5 text-xs text-amber-900 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200">
              Esta turma tem {pagina.total} alunos e a lista mostra só os {pagina.itens.length} primeiros.
              Se não achar o aluno, confira a turma escolhida.
            </p>
          )}

          <div className="max-h-[45vh] overflow-y-auto rounded-2xl border border-zinc-200/80 dark:border-zinc-800">
            {carregando ? (
              <Carregando />
            ) : erro ? (
              <p role="alert" className="py-8 text-center text-sm text-rose-600 dark:text-rose-400">
                {erro.message}
              </p>
            ) : filtrados.length === 0 ? (
              <p className="py-8 text-center text-sm text-zinc-500 dark:text-zinc-400">
                {busca ? "Nenhum aluno encontrado." : "Turma sem alunos."}
              </p>
            ) : (
              <ul className="divide-y divide-zinc-100 dark:divide-zinc-800/60">
                {filtrados.map((aluno) => (
                  <li key={aluno.id}>
                    <button
                      type="button"
                      className="flex w-full items-center gap-3 px-3.5 py-2.5 text-left transition-colors hover:bg-indigo-50/60 dark:hover:bg-zinc-800/60"
                      onClick={() => setSelecionado(aluno)}
                    >
                      <AvatarAluno nome={aluno.nome} chave={aluno.id} foto={aluno.foto_url} tamanho="sm" />
                      <span className="min-w-0 flex-1 truncate text-sm font-semibold text-zinc-900 dark:text-zinc-100" title={aluno.nome}>{aluno.nome}</span>
                      {aluno.numero_chamada != null && (
                        <Chip className="shrink-0 tabular-nums">Nº {aluno.numero_chamada}</Chip>
                      )}
                      <ChevronRight size={16} aria-hidden className="shrink-0 text-zinc-400" />
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
