/**
 * Barra das listas de alunos das plataformas (Elefante Letrado e Matific): a
 * identidade da plataforma (ícone e cor), quantos alunos aparecem e os filtros de
 * TELA — busca pelo nome e turma. Os filtros só estreitam o que a API já mandou
 * (que é o recorte de permissão do usuário); não mudam regra nem consulta.
 */
import { ChevronDown, Search } from "lucide-react";
import { useId, useMemo, useState } from "react";

import { IconePlataforma, identidadeDe } from "./identidadePlataforma";
import { estiloInput } from "./ui";
import { normalizar } from "../lib/nomes";

export function useFiltroAlunos<T extends { nome: string; turma: string | null }>(linhas: T[] | null | undefined) {
  const [busca, setBusca] = useState("");
  const [turma, setTurma] = useState("");
  const turmas = useMemo(
    () => [...new Set((linhas ?? []).map((l) => l.turma).filter((t): t is string => Boolean(t)))]
      .sort((a, b) => a.localeCompare(b, "pt-BR", { numeric: true })),
    [linhas],
  );
  const termo = normalizar(busca.trim());
  const filtradas = useMemo(
    () => (linhas ?? []).filter((l) =>
      (!turma || l.turma === turma) && (!termo || normalizar(l.nome).includes(termo))),
    [linhas, turma, termo],
  );
  const ativo = Boolean(termo || turma);
  return {
    busca, setBusca, turma, setTurma, turmas, filtradas, ativo,
    limpar: () => { setBusca(""); setTurma(""); },
  };
}

export function BarraFiltroAlunos({
  plataforma,
  total,
  visiveis,
  busca,
  aoBuscar,
  turma,
  aoMudarTurma,
  turmas,
}: {
  plataforma: "elefante" | "matific";
  total: number;
  visiveis: number;
  busca: string;
  aoBuscar: (v: string) => void;
  turma: string;
  aoMudarTurma: (v: string) => void;
  turmas: string[];
}) {
  const idBusca = useId();
  const idTurma = useId();
  const identidade = identidadeDe(plataforma);
  return (
    <div className="flex flex-wrap items-center gap-4 px-6 pb-4 pt-5">
      <div className="flex min-w-0 items-center gap-3">
        <IconePlataforma plataforma={plataforma} />
        <div className="min-w-0">
          <p className="text-[15px] font-semibold text-zinc-900 dark:text-white">
            {visiveis === total ? `${total} aluno${total === 1 ? "" : "s"}` : `${visiveis} de ${total} alunos`}
          </p>
          {/* A área (Leitura/Matemática) e não o nome: o nome já é o título da página. */}
          <span className={`mt-0.5 inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-semibold ${identidade?.pilula ?? ""}`}>
            <span aria-hidden className={`h-1.5 w-1.5 rounded-full ${identidade?.ponto ?? ""}`} />
            {identidade?.area}
          </span>
        </div>
      </div>
      {/* Celular (< 640 px): busca e turma em linhas inteiras, uma embaixo da outra (lado
          a lado as duas saíam cortadas: "Buscar pel", "Todas as turma"). */}
      <div className="ml-auto flex w-full flex-col gap-2.5 sm:w-auto sm:flex-row sm:flex-wrap sm:items-center">
        <label htmlFor={idBusca} className="sr-only">Buscar aluno pelo nome</label>
        <span className="relative block w-full min-w-0 sm:w-60 sm:flex-none">
          <Search size={15} aria-hidden className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-zinc-400" />
          <input
            id={idBusca}
            type="search"
            className={`${estiloInput} pl-9`}
            placeholder="Buscar pelo nome"
            value={busca}
            onChange={(e) => aoBuscar(e.target.value)}
          />
        </span>
        {turmas.length > 1 && (
          <>
            <label htmlFor={idTurma} className="sr-only">Filtrar por turma</label>
            {/* A largura fica no invólucro: o w-full do estiloInput vence um w-* no próprio
                select, que ia para a linha de baixo ocupando a largura toda. O select segue
                NATIVO, com a seta fina da v2 (appearance-none + ChevronDown) e espaço à
                direita para o texto não invadir a seta. */}
            <span className="relative block w-full min-w-0 sm:w-48 sm:flex-none">
              <select
                id={idTurma}
                className={`${estiloInput} cursor-pointer appearance-none truncate pr-10`}
                value={turma}
                onChange={(e) => aoMudarTurma(e.target.value)}
              >
                <option value="">Todas as turmas</option>
                {turmas.map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
              <ChevronDown
                size={16}
                aria-hidden
                className="pointer-events-none absolute right-3.5 top-1/2 -translate-y-1/2 text-zinc-500 dark:text-zinc-400"
              />
            </span>
          </>
        )}
      </div>
    </div>
  );
}
