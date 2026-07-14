/**
 * Seletor de PERÍODO reutilizável (rankings, histórico, estatísticas).
 *
 * Presets (hoje, este bimestre, ano letivo...), intervalo personalizado e um
 * dia específico. Converte a escolha nos parâmetros que o backend espera via
 * `periodoParaQuery`.
 */
import { CalendarRange } from "lucide-react";

import { estiloInput } from "./ui";

export interface Periodo {
  preset: string; // chave do preset, "personalizado" ou "dia"
  inicio?: string; // AAAA-MM-DD (personalizado/dia)
  fim?: string; // AAAA-MM-DD (personalizado)
}

// Só os períodos que a escola usa para premiar: dia, semana, mês, bimestre, ano
// e o PERSONALIZADO (escolher as datas — premiação por qualquer intervalo).
export const PRESETS_PERIODO = [
  { valor: "hoje", rotulo: "Hoje" },
  { valor: "semana", rotulo: "Esta semana" },
  { valor: "mes", rotulo: "Este mês" },
  { valor: "bimestre", rotulo: "Este bimestre" },
  { valor: "ano_letivo", rotulo: "Ano letivo" },
  { valor: "personalizado", rotulo: "Período personalizado" },
] as const;

/** Monta a query string (?periodo=... / ?dia=... / ?inicio=&fim=). */
export function periodoParaQuery(p: Periodo): string {
  const q = new URLSearchParams();
  if (p.preset === "dia") {
    if (p.inicio) q.set("dia", p.inicio);
  } else if (p.preset === "personalizado") {
    q.set("periodo", "personalizado");
    if (p.inicio) q.set("inicio", p.inicio);
    if (p.fim) q.set("fim", p.fim);
  } else {
    q.set("periodo", p.preset);
  }
  return q.toString();
}

const estiloData = `${estiloInput} w-auto`;

export function SeletorPeriodo({ valor, onChange }: {
  valor: Periodo;
  onChange: (p: Periodo) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <CalendarRange size={15} className="text-zinc-400" />
      <select
        aria-label="Período de análise"
        className={`${estiloInput} w-auto`}
        value={valor.preset}
        onChange={(e) => onChange({ ...valor, preset: e.target.value })}
      >
        {PRESETS_PERIODO.map((p) => (
          <option key={p.valor} value={p.valor}>{p.rotulo}</option>
        ))}
      </select>

      {valor.preset === "personalizado" && (
        <>
          <input type="date" aria-label="Data inicial" className={estiloData}
                 value={valor.inicio ?? ""} onChange={(e) => onChange({ ...valor, inicio: e.target.value })} />
          <span className="text-sm text-zinc-500">até</span>
          <input type="date" aria-label="Data final" className={estiloData}
                 value={valor.fim ?? ""} onChange={(e) => onChange({ ...valor, fim: e.target.value })} />
        </>
      )}

      {valor.preset === "dia" && (
        <input type="date" aria-label="Dia" className={estiloData}
               value={valor.inicio ?? ""} onChange={(e) => onChange({ ...valor, inicio: e.target.value })} />
      )}
    </div>
  );
}
