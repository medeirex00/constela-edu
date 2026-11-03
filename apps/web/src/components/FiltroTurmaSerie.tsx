/**
 * Seletor ÚNICO de alvo do ranking: "Todas as turmas", uma SÉRIE consolidada
 * (todas as turmas do ano) ou uma TURMA específica — num só dropdown, agrupado
 * com <optgroup> para deixar clara a diferença entre "1º Ano (todas as turmas)"
 * e "1º Ano A". Substitui os dois seletores separados (turma + série).
 *
 * Emite `{ ano_escolar }` para uma série, `{ turma_id }` para uma turma, ou `{}`
 * para "todas" — pronto para virar query (`?ano_escolar=` ou `?turma_id=`).
 *
 * Identidade v2: a pílula branca com ícone das referências, com o <select>
 * NATIVO por baixo (mesmo aria-label e mesmos valores "turma:<id>"/"serie:<rótulo>",
 * que os testes e o teclado/leitor de tela usam).
 */
import { Users } from "lucide-react";

import { MolduraPilula, estiloSelectPilula } from "./SeletorPilula";
import type { Turma } from "../lib/types";

export type AlvoRanking = { turma_id?: string; ano_escolar?: string };

export function FiltroTurmaSerie({
  turmas,
  valor,
  onChange,
  className = "",
}: {
  turmas: Turma[];
  valor: AlvoRanking;
  onChange: (valor: AlvoRanking) => void;
  className?: string;
}) {
  // Séries distintas (ordenadas) presentes nas turmas.
  const series = Array.from(new Set(turmas.map((t) => t.ano_escolar))).sort();

  // Codifica a seleção atual numa string para o <select>.
  const atual = valor.ano_escolar
    ? `serie:${valor.ano_escolar}`
    : valor.turma_id
      ? `turma:${valor.turma_id}`
      : "";

  return (
    <MolduraPilula icone={Users} className={className}>
      <select
        aria-label="Filtrar por turma ou série"
        className={estiloSelectPilula}
        value={atual}
        onChange={(e) => {
          const v = e.target.value;
          if (!v) onChange({});
          else if (v.startsWith("serie:")) onChange({ ano_escolar: v.slice(6) });
          else onChange({ turma_id: v.slice(6) });
        }}
      >
        <option value="">Todas as turmas</option>
        {series.length > 0 && (
          <optgroup label="Séries — consolidado">
            {series.map((s) => (
              <option key={`s-${s}`} value={`serie:${s}`}>
                {s} (todas as turmas)
              </option>
            ))}
          </optgroup>
        )}
        {turmas.length > 0 && (
          <optgroup label="Turmas">
            {turmas.map((t) => (
              <option key={`t-${t.id}`} value={`turma:${t.id}`}>
                {t.nome}
              </option>
            ))}
          </optgroup>
        )}
      </select>
    </MolduraPilula>
  );
}
