/**
 * Seletor de PERÍODO reutilizável (rankings, histórico, estatísticas).
 *
 * Presets (hoje, este bimestre, ano letivo...), intervalo personalizado e um
 * dia específico. Converte a escolha nos parâmetros que o backend espera via
 * `periodoParaQuery`.
 */
import { CalendarRange } from "lucide-react";

import type { PopulacaoDoPeriodo } from "../lib/types";

import { MolduraPilula, estiloDataPilula, estiloSelectPilula } from "./SeletorPilula";

export interface Periodo {
  preset: string; // chave do preset, "personalizado" ou "dia"
  inicio?: string; // AAAA-MM-DD (personalizado/dia)
  fim?: string; // AAAA-MM-DD (personalizado)
}

// Períodos de premiação: os atuais e os ANTERIORES (dia/semana/mês/bimestre), o
// ano letivo e o PERSONALIZADO (qualquer intervalo). Esta/semana passada e ano
// usam presets nativos do Matific; os demais vão por datas.
export const PRESETS_PERIODO = [
  { valor: "hoje", rotulo: "Hoje" },
  { valor: "ontem", rotulo: "Ontem" },
  { valor: "semana", rotulo: "Esta semana" },
  { valor: "semana_anterior", rotulo: "Semana passada" },
  { valor: "mes", rotulo: "Este mês" },
  { valor: "mes_anterior", rotulo: "Mês passado" },
  { valor: "bimestre", rotulo: "Este bimestre" },
  { valor: "bimestre_anterior", rotulo: "Bimestre passado" },
  // Bimestre pelo NÚMERO, nas datas do calendário oficial da rede. "Este
  // bimestre" muda de janela quando o dia vira (em 05/10/2026 passa a ser o 4º),
  // então quem vai PREMIAR um bimestre escolhe o número — a janela não se move.
  { valor: "bimestre_1", rotulo: "1º bimestre" },
  { valor: "bimestre_2", rotulo: "2º bimestre" },
  { valor: "bimestre_3", rotulo: "3º bimestre" },
  { valor: "bimestre_4", rotulo: "4º bimestre" },
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

/** De que ano letivo vêm as crianças de uma consulta por período: `populacao` nas
 *  premiações e no Relatório por Período; `ano_letivo` + `populacao` em cada linha dos
 *  rankings por período. Os tipos são os do @constela/core (re-exportados aqui para quem
 *  já os importava deste módulo). */
export type { OrigemPopulacao, PopulacaoDoPeriodo } from "../lib/types";

/** O aviso de que ano são as crianças e as turmas — a mesma frase do PDF do Relatório
 *  por Período (`relatorios_periodo_pdf._populacao`). `null` no caso de sempre (o
 *  período está no ano letivo ativo). `recorte`: há turma escolhida, ou o professor vê
 *  só as turmas dele — num ano encerrado, essas turmas são as de agora e escolhem QUEM
 *  aparece, cada criança com a turma que tinha naquele ano. */
export function avisoPopulacao(
  pop: PopulacaoDoPeriodo | null | undefined,
  recorte?: "turma" | "suas_turmas",
): string | null {
  if (!pop) return null;
  const ano = pop.ano_letivo;
  if (pop.origem === "ano_do_periodo") {
    const turmas = recorte === "turma"
      ? ` A turma escolhida é a de agora: aparecem as crianças dela, com a turma que tinham em ${ano}.`
      : recorte === "suas_turmas"
        ? ` Suas turmas são as de agora: aparecem as crianças delas, com a turma que tinham em ${ano}.`
        : "";
    return `Período do ano letivo de ${ano}, que já terminou: entram as crianças matriculadas em ${ano}, `
      + `com a turma e a série daquele ano.${turmas}`;
  }
  if (pop.origem === "atravessa_anos") {
    return `O período passa por mais de um ano letivo: entram as crianças matriculadas em ${ano}, `
      + `o ano letivo atual da escola, com a turma de agora. Quem não tem matrícula em ${ano} não aparece.`;
  }
  return null;
}

const estiloData = estiloDataPilula;

/** As datas do "personalizado" (início e fim) e do "dia", no contrato do backend.
 *  Fonte única: a pílula abaixo e o campo da Análise educacional só mudam o estilo.
 *  No personalizado, o calendário da data final começa na inicial (`min`) e o da inicial
 *  termina na final (`max`): com as datas trocadas o backend recusa (422, "inverta as
 *  duas"), e antes algumas telas respondiam "nenhuma leitura no período". */
export function DatasDoPeriodo({ valor, onChange, estilo, classeAte = "text-sm text-zinc-500 dark:text-zinc-400" }: {
  valor: Periodo;
  onChange: (p: Periodo) => void;
  estilo: string;
  classeAte?: string;
}) {
  if (valor.preset === "personalizado") {
    return (
      <>
        <input type="date" aria-label="Data inicial" className={estilo} max={valor.fim || undefined}
               value={valor.inicio ?? ""} onChange={(e) => onChange({ ...valor, inicio: e.target.value })} />
        <span className={classeAte}>até</span>
        <input type="date" aria-label="Data final" className={estilo} min={valor.inicio || undefined}
               value={valor.fim ?? ""} onChange={(e) => onChange({ ...valor, fim: e.target.value })} />
      </>
    );
  }
  if (valor.preset === "dia") {
    return (
      <input type="date" aria-label="Dia" className={estilo}
             value={valor.inicio ?? ""} onChange={(e) => onChange({ ...valor, inicio: e.target.value })} />
    );
  }
  return null;
}

/** "Todo o histórico" (preset "tudo" do backend): só nas telas que ABREM sem
 *  recorte de período (as abas do Perfil do Aluno). Fora da lista, o <select>
 *  controlado com `preset: "tudo"` mostrava a 1ª opção ("Hoje") enquanto a
 *  consulta pedia o histórico inteiro. */
export const PRESET_TUDO = { valor: "tudo", rotulo: "Todo o histórico" } as const;

/** Identidade v2: a pílula branca das referências ("4º bimestre"), com o <select>
 *  nativo por baixo — mesmos presets, aria-labels e contrato com o backend.
 *  `comTudo` acrescenta "Todo o histórico" no topo (opt-in: as premiações e os
 *  rankings não oferecem histórico sem recorte). */
export function SeletorPeriodo({ valor, onChange, comTudo = false }: {
  valor: Periodo;
  onChange: (p: Periodo) => void;
  comTudo?: boolean;
}) {
  const presets = comTudo ? [PRESET_TUDO, ...PRESETS_PERIODO] : PRESETS_PERIODO;
  return (
    <div className="flex flex-wrap items-center gap-2">
      <MolduraPilula icone={CalendarRange}>
        <select
          aria-label="Período de análise"
          className={estiloSelectPilula}
          value={valor.preset}
          onChange={(e) => onChange({ ...valor, preset: e.target.value })}
        >
          {presets.map((p) => (
            <option key={p.valor} value={p.valor}>{p.rotulo}</option>
          ))}
        </select>
      </MolduraPilula>
      <DatasDoPeriodo valor={valor} onChange={onChange} estilo={estiloData} />
    </div>
  );
}
