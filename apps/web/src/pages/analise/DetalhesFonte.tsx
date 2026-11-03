/**
 * "Detalhes e fontes" da análise educacional — a fonte documental fica FORA da
 * interface principal (nenhum cartão, célula ou destaque cita arquivo) e aparece
 * aqui, sob demanda: o conteúdo só é montado quando a pessoa abre o bloco.
 *
 * Cada número mostrado aponta `fonte_id` para o mapa `fontes` da resposta (o formato
 * canônico das fontes oficiais, o mesmo do `SeloFonte`): o bloco agrupa os números por
 * arquivo e escreve o texto da fonte com a data de importação e a licença.
 */
import { ChevronDown, FileSearch } from "lucide-react";
import { useId, useState, type ReactNode } from "react";

import { textoFonte, type FonteOficial } from "../../components/SeloFonte";
import { dataHora } from "../../lib/formato";

/** Bloco recolhível que só MONTA o conteúdo quando aberto (nada lido antes do clique). */
export function Recolhivel({
  titulo,
  icone,
  children,
  testId,
  inicialAberto = false,
}: {
  titulo: string;
  icone?: ReactNode;
  children: ReactNode;
  testId?: string;
  inicialAberto?: boolean;
}) {
  const [aberto, setAberto] = useState(inicialAberto);
  const id = useId();
  return (
    <div className="rounded-2xl border border-zinc-200/80 bg-white dark:border-zinc-800 dark:bg-zinc-900" data-testid={testId}>
      <button
        type="button"
        aria-expanded={aberto}
        aria-controls={aberto ? id : undefined}
        onClick={() => setAberto((a) => !a)}
        className="flex min-h-[2.75rem] w-full items-center gap-2 rounded-2xl px-4 py-2.5 text-left text-sm font-semibold text-zinc-700 transition-colors hover:text-indigo-600 dark:text-zinc-200 dark:hover:text-indigo-400"
      >
        {icone}
        <span className="min-w-0 flex-1 break-words">{titulo}</span>
        <ChevronDown size={15} aria-hidden
                     className={`shrink-0 text-zinc-400 transition-transform duration-200 ${aberto ? "rotate-180" : ""}`} />
      </button>
      {aberto && (
        <div id={id} className="space-y-2 break-words border-t border-zinc-100 px-4 py-3 text-xs text-zinc-600 dark:border-zinc-800 dark:text-zinc-300">
          {children}
        </div>
      )}
    </div>
  );
}

/** Um número mostrado na tela e de onde ele vem. */
export interface ItemDetalhe {
  /** Como o número aparece na tela: "2023 — Rede municipal". */
  rotulo: string;
  fonte_id: number | null;
  /** Observação de conferência (ex.: o valor com mais casas de outro arquivo). */
  detalhe?: string | null;
}

/** As fontes dos números MOSTRADOS, agrupadas por arquivo — recolhidas por padrão. */
export default function DetalhesEFontes({
  itens,
  fontes,
  testId,
  titulo = "Detalhes e fontes",
  children,
}: {
  itens: ItemDetalhe[];
  fontes: Record<string, FonteOficial> | null | undefined;
  testId?: string;
  titulo?: string;
  /** Detalhes extras (metodologia curta, observações) no mesmo bloco. */
  children?: ReactNode;
}) {
  const porFonte = new Map<number, string[]>();
  const semFonte: string[] = [];
  for (const item of itens) {
    const f = item.fonte_id != null ? fontes?.[String(item.fonte_id)] : undefined;
    if (!f || item.fonte_id == null) {
      semFonte.push(item.rotulo);
      continue;
    }
    porFonte.set(item.fonte_id, [...(porFonte.get(item.fonte_id) ?? []), item.rotulo]);
  }
  const lista = [...porFonte.entries()].map(([id, rotulos]) => ({ f: fontes![String(id)], rotulos }));
  const detalhes = itens.filter((i) => i.detalhe);
  return (
    <Recolhivel titulo={titulo} testId={testId}
                icone={<FileSearch size={14} className="shrink-0 text-zinc-400" aria-hidden />}>
      {children}
      {lista.length === 0 && semFonte.length === 0 && <p>Nenhum número oficial mostrado neste bloco.</p>}
      {lista.length > 0 && (
        <ul className="space-y-2">
          {lista.map(({ f, rotulos }) => (
            <li key={f.importacao_id} data-testid="detalhe-fonte">
              <p>
                Fonte: {textoFonte(f)}
                {f.importado_em ? ` · importado em ${dataHora(f.importado_em)}` : ""}
              </p>
              <p className="text-zinc-600 dark:text-zinc-400">Números deste arquivo: {rotulos.join("; ")}.</p>
            </li>
          ))}
        </ul>
      )}
      {semFonte.length > 0 && (
        <p className="text-zinc-600 dark:text-zinc-400">Sem arquivo oficial associado: {semFonte.join("; ")}.</p>
      )}
      {detalhes.length > 0 && (
        <ul className="space-y-0.5 text-zinc-600 dark:text-zinc-400">
          {detalhes.map((d) => <li key={d.rotulo}>{d.rotulo}: {d.detalhe}</li>)}
        </ul>
      )}
      {lista[0]?.f.licenca && <p className="text-zinc-600 dark:text-zinc-400">{lista[0].f.licenca}</p>}
    </Recolhivel>
  );
}
