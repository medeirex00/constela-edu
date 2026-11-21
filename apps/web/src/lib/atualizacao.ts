/**
 * Recuperação de DEPLOY (chunk obsoleto).
 *
 * O app é dividido por rota (React.lazy) e servido como PWA. Depois de publicar
 * uma versão nova, os arquivos de chunk da versão anterior (ex.: `Dashboard-<hash>.js`)
 * deixam de existir no servidor. Uma página que ainda roda a versão anterior e não
 * tem esses arquivos no cache do service worker que a controla — a aba que ficou para
 * trás depois que OUTRA aba aplicou a versão nova, ou a página que veio da rede (1ª
 * visita, Ctrl+Shift+R, plano B) — pede o chunk de uma tela que ainda não abriu, leva
 * 404, o import dinâmico rejeita e a página cairia em branco ou no LimiteErro.
 *
 * A cura é buscar a versão nova: desregistramos o service worker e recarregamos (a
 * página vem da rede) UMA vez por sessão — guarda contra laço se o chunk estiver de
 * fato quebrado, não só obsoleto. O login fica (está no localStorage).
 *
 * NÃO apaga o cache do PWA (o mesmo cuidado do plano B de pwaAtualizacao.ts): o Cache
 * Storage é de todas as abas do navegador. Outra aba que segue na versão antiga, com
 * o aviso "Nova versão disponível", abre as telas dela por esse cache; apagá-lo a
 * fazia recarregar sozinha na próxima tela, e a aba já na versão nova deixava de
 * abrir sem internet até o próximo deploy. Para a recarga desta aba vir da rede basta
 * desregistrar.
 */
import { recarregarSemServiceWorker } from "./pwaAtualizacao";

const CHAVE_GUARDA = "recarga_chunk_obsoleto";

/** O erro é de carregamento de chunk (import dinâmico que falhou)? */
export function ehErroDeChunk(erro: unknown): boolean {
  const msg = erro instanceof Error ? `${erro.name} ${erro.message}` : String(erro ?? "");
  return /ChunkLoadError|dynamically imported module|Importing a module script failed|Failed to fetch dynamically imported|error loading dynamically imported/i.test(
    msg,
  );
}

/** Recupera de um chunk obsoleto no MÁXIMO uma vez por sessão. */
export function recuperarDeChunkObsoleto(): void {
  if (sessionStorage.getItem(CHAVE_GUARDA)) return; // já tentou nesta sessão → evita loop
  sessionStorage.setItem(CHAVE_GUARDA, "1");
  void recarregarSemServiceWorker();
}
