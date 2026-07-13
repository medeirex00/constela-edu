/**
 * Ranking Geral — tela única com um seletor (segmented control) para escolher o
 * tipo de ranking, sem trocar de página. Cada tipo é a MESMA tela de antes
 * (filtros de período/turma/série, paginação e comportamento preservados),
 * apenas embutida aqui sem o próprio cabeçalho. A opção fica sincronizada na URL
 * (`?ver=leitura`), o que mantém os atalhos e links diretos funcionando.
 */
import { useSearchParams } from "react-router-dom";

import { PageHeader } from "../components/ui";
import RankingEscolar from "./RankingEscolar";
import RankingEvolucao from "./RankingEvolucao";
import RankingGeral from "./RankingGeral";
import RankingLeitura from "./RankingLeitura";
import RankingMatematica from "./RankingMatematica";

// Uma aba por FONTE de dados: Geral (consolidado), Elefante Letrado (leitura),
// Matific (matemática), Evolução e Escolar (dados escolares — em construção).
const VISOES = [
  { chave: "geral", rotulo: "Geral" },
  { chave: "leitura", rotulo: "Elefante Letrado" },
  { chave: "matematica", rotulo: "Matific" },
  { chave: "evolucao", rotulo: "Evolução" },
  { chave: "escolar", rotulo: "Escolar" },
] as const;

type Visao = (typeof VISOES)[number]["chave"];

function ehVisao(valor: string | null): valor is Visao {
  return VISOES.some((v) => v.chave === valor);
}

export default function Rankings() {
  const [params, setParams] = useSearchParams();
  // A URL é a ÚNICA fonte da verdade: `visao` é derivada de `?ver=` a cada
  // render. Assim atalhos/deep-links que mudam só a query (Alt+2/Alt+3, o link
  // "Ranking Geral" da barra) trocam a aba mesmo com a tela já montada — o React
  // Router NÃO remonta a rota quando muda apenas a query string.
  const ver = params.get("ver");
  const visao: Visao = ehVisao(ver) ? ver : "geral";

  function trocar(nova: Visao) {
    // Reflete a escolha na URL (deep-link/atalho) sem empilhar histórico; o
    // render seguinte lê `visao` da própria URL.
    const prox = new URLSearchParams(params);
    if (nova === "geral") prox.delete("ver");
    else prox.set("ver", nova);
    setParams(prox, { replace: true });
  }

  return (
    <div>
      <PageHeader
        titulo="Ranking Geral"
        descricao="Escolha o tipo de ranking. Os filtros de período, turma e série ficam dentro de cada um."
      />

      <div
        role="tablist"
        aria-label="Tipo de ranking"
        className="mb-4 inline-flex flex-wrap gap-1 rounded-lg border border-zinc-200 bg-zinc-100 p-1 dark:border-zinc-800 dark:bg-zinc-900/60"
      >
        {VISOES.map((v) => (
          <button
            key={v.chave}
            type="button"
            role="tab"
            aria-selected={visao === v.chave}
            onClick={() => trocar(v.chave)}
            className={`rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
              visao === v.chave
                ? "bg-white text-indigo-700 shadow-sm dark:bg-zinc-800 dark:text-indigo-300"
                : "text-zinc-600 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100"
            }`}
          >
            {v.rotulo}
          </button>
        ))}
      </div>

      {visao === "geral" && <RankingGeral embutido />}
      {visao === "leitura" && <RankingLeitura embutido />}
      {visao === "matematica" && <RankingMatematica embutido />}
      {visao === "evolucao" && <RankingEvolucao embutido />}
      {visao === "escolar" && <RankingEscolar embutido />}
    </div>
  );
}
