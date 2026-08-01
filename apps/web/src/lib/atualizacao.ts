/**
 * Recuperação de DEPLOY (chunk obsoleto).
 *
 * O app é dividido por rota (React.lazy) e servido como PWA. Depois de publicar
 * uma versão nova, o Service Worker / CDN pode continuar servindo um
 * `index.html` ANTIGO por um tempo — e esse HTML aponta para nomes de arquivo
 * de chunk (ex.: `Dashboard-<hash>.js`) que sumiram no build novo. O import
 * dinâmico da tela então dá 404, a Promise rejeita e a página cai em branco ou
 * no LimiteErro — para TODOS os perfis, já que o Dashboard é um chunk lazy.
 *
 * A cura é buscar o shell novo: limpamos o Service Worker + os caches do PWA e
 * recarregamos UMA vez por sessão (guarda contra loop se o chunk estiver de
 * fato quebrado, não só obsoleto).
 */

const CHAVE_GUARDA = "recarga_chunk_obsoleto";

/** O erro é de carregamento de chunk (import dinâmico que falhou)? */
export function ehErroDeChunk(erro: unknown): boolean {
  const msg = erro instanceof Error ? `${erro.name} ${erro.message}` : String(erro ?? "");
  return /ChunkLoadError|dynamically imported module|Importing a module script failed|Failed to fetch dynamically imported|error loading dynamically imported/i.test(
    msg,
  );
}

/** Desregistra o Service Worker, apaga os caches e recarrega — força o browser
 *  a baixar o `index.html` e os chunks NOVOS direto da rede. */
export async function recarregarLimpandoCache(): Promise<void> {
  try {
    const regs = (await navigator.serviceWorker?.getRegistrations?.()) ?? [];
    await Promise.all(regs.map((r) => r.unregister()));
    if (typeof caches !== "undefined") {
      const chaves = await caches.keys();
      await Promise.all(chaves.map((c) => caches.delete(c)));
    }
  } catch {
    /* mesmo se a limpeza falhar, o reload abaixo já ajuda */
  }
  window.location.reload();
}

/** Recupera de um chunk obsoleto no MÁXIMO uma vez por sessão. */
export function recuperarDeChunkObsoleto(): void {
  if (sessionStorage.getItem(CHAVE_GUARDA)) return; // já tentou nesta sessão → evita loop
  sessionStorage.setItem(CHAVE_GUARDA, "1");
  void recarregarLimpandoCache();
}
