/**
 * Relatórios — uma área só, com duas abas:
 *
 *   OFICIAIS    → exportações com a identidade visual da escola (ranking,
 *                 lista de alunos, catálogo, certificados).
 *   POR PERÍODO → o que aconteceu numa janela de datas.
 *
 * POR QUE ISTO EXISTE. "Relatório por Período" é um TIPO de relatório, e estava
 * na barra lateral como se fosse um módulo à parte, ao lado de "Relatórios".
 * Quem procurava um relatório tinha de adivinhar em qual dos dois entrar. Aqui
 * a barra lateral volta a ter uma entrada só e a escolha acontece dentro da
 * página, onde o usuário já está olhando para relatórios.
 *
 * NENHUMA LÓGICA MUDA. Esta tela não busca dado, não filtra, não calcula e não
 * gera PDF: ela só escolhe qual das DUAS páginas existentes renderizar. Os
 * filtros, as métricas, as ressalvas, o botão "Gerar PDF" e as permissões
 * continuam onde sempre estiveram, dentro de cada uma delas.
 *
 * A URL CONTINUA SENDO A MESMA. `/relatorios` abre em Oficiais e
 * `/relatorios/periodo` abre em Por período — a rota que já estava publicada,
 * preservada inteira para não quebrar link salvo, histórico nem atalho. A aba
 * é derivada do caminho a cada render, então voltar/avançar no navegador troca
 * a aba sem remontar nada.
 *
 * SEM TÍTULO PRÓPRIO, de propósito: cada página filha já traz o seu
 * `PageHeader` (e o de "Por período" carrega o botão "Gerar PDF"). Pôr mais um
 * por cima daria dois títulos na mesma tela — o mesmo motivo pelo qual
 * `Rankings.tsx` não desenha cabeçalho na categoria "Escolas".
 *
 * Acessibilidade: o mesmo padrão de `Rankings.tsx` — `role="tablist"`, abas com
 * `aria-controls` apontando para o painel, e o painel (`role="tabpanel"`)
 * rotulado pela aba ativa.
 */
import { useId } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import RelatorioPeriodo from "./RelatorioPeriodo";
import Relatorios from "./Relatorios";

const ABAS = [
  { chave: "oficiais", rotulo: "Relatórios oficiais", caminho: "/relatorios" },
  { chave: "periodo", rotulo: "Por período", caminho: "/relatorios/periodo" },
] as const;
type Aba = (typeof ABAS)[number]["chave"];

// Mesmo estilo de aba de `Rankings.tsx` — é o padrão da casa, não um novo.
const estiloAba = (ativa: boolean) =>
  `rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
    ativa
      ? "bg-white text-indigo-700 shadow-sm dark:bg-zinc-800 dark:text-indigo-300"
      : "text-zinc-600 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100"
  }`;

export default function RelatoriosArea() {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const idBase = useId();
  const idAba = (chave: string) => `${idBase}-aba-${chave}`;
  const idPainel = `${idBase}-painel`;

  // O CAMINHO é a fonte da verdade: a aba é derivada dele a cada render, para
  // que link direto, voltar/avançar e atalho funcionem sem estado paralelo.
  const aba: Aba = pathname.startsWith("/relatorios/periodo") ? "periodo" : "oficiais";

  return (
    <div>
      <div
        role="tablist"
        aria-label="Tipo de relatório"
        className="mb-4 flex flex-wrap gap-1 rounded-lg border border-zinc-200 bg-zinc-100 p-1 dark:border-zinc-800 dark:bg-zinc-900/60 sm:inline-flex"
      >
        {ABAS.map((a) => (
          <button
            key={a.chave}
            id={idAba(a.chave)}
            type="button"
            role="tab"
            aria-selected={aba === a.chave}
            aria-controls={idPainel}
            // `replace` para a troca de aba não empilhar histórico — voltar
            // devolve o usuário à tela de onde ele veio, não à outra aba.
            onClick={() => navigate(a.caminho, { replace: true })}
            className={estiloAba(aba === a.chave)}
          >
            {a.rotulo}
          </button>
        ))}
      </div>

      <div role="tabpanel" id={idPainel} aria-labelledby={idAba(aba)}>
        {aba === "periodo" ? <RelatorioPeriodo /> : <Relatorios />}
      </div>
    </div>
  );
}
