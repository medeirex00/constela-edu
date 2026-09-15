/**
 * Seletor do TURNO global (AppContext.turno) — o mesmo controle em Ranking
 * Geral, Leitura, Matemática, Evolução e Premiações.
 *
 * As opções são "Todos os turnos" + os turnos que EXISTEM na escola (derivados
 * de `turmas[].turno`, na ordem manhã/tarde/noite/integral); "Sem turno" só
 * aparece quando alguma turma está sem turno cadastrado. Nada é escrito à mão.
 *
 * Se o valor persistido não existe nesta escola (ex.: "Noite" escolhida em outra
 * escola), o seletor MOSTRA "Todos" mas não sobrescreve o que está guardado —
 * as telas consultam com `turnoEfetivo()` e o usuário mantém a escolha ao
 * voltar para a escola que tem aquele turno.
 */
import { Clock } from "lucide-react";

import { TURNO_TODOS, chaveTurno, rotuloTurno, turnosDasTurmas } from "../lib/turnos";
import type { Turma } from "../lib/types";
import { estiloInput } from "./ui";

export function SeletorTurno({
  turmas,
  valor,
  onChange,
  disabled = false,
  title,
  descricaoId,
  className = "",
}: {
  turmas: Pick<Turma, "turno">[];
  valor: string;
  onChange: (turno: string) => void;
  disabled?: boolean;
  /** Dica exibida no controle (ex.: por que está desabilitado). */
  title?: string;
  /** Id de um texto VISÍVEL que explica o controle (ex.: por que está
   *  desabilitado) — vira `aria-describedby` do select; `title` sozinho não
   *  chega a leitor de tela nem a toque. */
  descricaoId?: string;
  className?: string;
}) {
  const opcoes = turnosDasTurmas(turmas);
  const existe = valor !== TURNO_TODOS && opcoes.some((t) => chaveTurno(t) === valor);
  const atual = existe ? valor : TURNO_TODOS;

  return (
    <span className={`inline-flex items-center gap-2 ${className}`} title={title}>
      <Clock size={15} className="text-zinc-400" />
      <select
        aria-label="Turno"
        className={`${estiloInput} w-auto disabled:opacity-60`}
        value={atual}
        disabled={disabled}
        aria-describedby={descricaoId}
        onChange={(e) => onChange(e.target.value)}
      >
        <option value={TURNO_TODOS}>Todos os turnos</option>
        {opcoes.map((t) => (
          <option key={chaveTurno(t) || "_sem"} value={chaveTurno(t)}>
            {rotuloTurno(t)}
          </option>
        ))}
      </select>
    </span>
  );
}
