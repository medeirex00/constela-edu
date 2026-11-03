/**
 * Aviso de VERSÃO NOVA do app (PWA). A troca só acontece no clique — nada recarrega
 * sozinho com alguém editando (a regra completa está em lib/pwaAtualizacao.ts e em
 * docs/operacao/PWA-ATUALIZACAO.md). Fora da árvore do roteador e do LimiteErro: o
 * aviso aparece até numa tela que quebrou por arquivo antigo em cache.
 *
 * role="status" (polido): anuncia sem roubar o foco de quem está digitando.
 *
 * Identidade v2: cartão de 20 px com sombra flutuante e botão violeta. No desktop o
 * cartão sai de cima do rodapé da barra lateral (cartões Escola e usuário): fica
 * logo depois dela (a barra tem 16rem aberta).
 */
import { RefreshCw, X } from "lucide-react";
import { useSyncExternalStore } from "react";

import { atualizacaoPwaAtual, ehTelaPublica, type AtualizacaoPwa } from "../lib/pwaAtualizacao";

export function PwaAviso({ atualizacao = atualizacaoPwaAtual() }: { atualizacao?: AtualizacaoPwa }) {
  const estado = useSyncExternalStore(atualizacao.assinar, atualizacao.estado, () => "ocioso" as const);
  // Telão e vitrine trocam de versão sozinhos (sem ninguém para clicar): nada de aviso
  // nem de região viva extra na TV.
  if (ehTelaPublica(window.location.pathname)) return null;
  // "trocando" (troca automática da abertura) fica sem cartão: ninguém pediu, e o
  // "Salve o que estiver editando" durante a espera assustava sem motivo.
  const visivel = estado === "disponivel" || estado === "aplicando" || estado === "aplicada-em-outra-aba";
  return (
    <div role="status" aria-live="polite"
      className="pointer-events-none fixed inset-x-0 bottom-0 z-50 flex justify-start p-4 pb-safe sm:left-4 sm:right-auto xl:left-64">
      {visivel && (
        <div className="pointer-events-auto flex w-full max-w-sm items-start gap-3 rounded-cartao border border-zinc-200/80 bg-white p-4 text-sm text-zinc-800 shadow-flutuante dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100">
          <span aria-hidden className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-indigo-50 text-indigo-600 dark:bg-indigo-500/15 dark:text-indigo-300">
            <RefreshCw size={18} />
          </span>
          <div className="min-w-0 flex-1">
            {estado === "aplicada-em-outra-aba" ? (
              <>
                <p className="font-semibold text-zinc-900 dark:text-white">O Constela foi atualizado em outra aba.</p>
                <p className="mt-1 text-zinc-600 dark:text-zinc-300">
                  Recarregue esta página quando terminar o que está fazendo.
                </p>
                <button type="button" onClick={atualizacao.recarregar}
                  className="mt-3 rounded-xl bg-indigo-600 px-3.5 py-2 text-xs font-semibold text-white shadow-pilula transition-colors hover:bg-indigo-700">
                  Recarregar
                </button>
              </>
            ) : (
              <>
                <p className="font-semibold text-zinc-900 dark:text-white">Nova versão do Constela disponível.</p>
                <p className="mt-1 text-zinc-600 dark:text-zinc-300">
                  Salve o que estiver editando: atualizar recarrega a página.
                </p>
                <div className="mt-3 flex flex-wrap gap-2">
                  <button type="button" onClick={atualizacao.atualizarAgora} disabled={estado === "aplicando"}
                    className="rounded-xl bg-indigo-600 px-3.5 py-2 text-xs font-semibold text-white shadow-pilula transition-colors hover:bg-indigo-700 disabled:opacity-70">
                    {estado === "aplicando" ? "Atualizando…" : "Atualizar agora"}
                  </button>
                  {estado === "disponivel" && (
                    <button type="button" onClick={atualizacao.dispensar}
                      className="rounded-xl px-3.5 py-2 text-xs font-semibold text-zinc-700 transition-colors hover:bg-zinc-100 dark:text-zinc-200 dark:hover:bg-zinc-800">
                      Depois
                    </button>
                  )}
                </div>
              </>
            )}
          </div>
          {estado === "disponivel" && (
            <button type="button" onClick={atualizacao.dispensar} aria-label="Fechar o aviso de nova versão"
              className="-m-1 grid h-8 w-8 shrink-0 place-items-center rounded-full text-zinc-500 transition-colors hover:bg-zinc-100 hover:text-zinc-800 dark:text-zinc-400 dark:hover:bg-zinc-800">
              <X aria-hidden size={16} />
            </button>
          )}
        </div>
      )}
    </div>
  );
}
