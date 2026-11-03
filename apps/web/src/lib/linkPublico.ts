/**
 * Endereço das páginas PÚBLICAS (painel da escola `/p/:token`, vitrine da rede
 * `/rede/p/:token`) para abrir, copiar e gerar o QR code.
 *
 * Quem decide a base do link é o SERVIDOR (`publico.base_do_link_publico`): o
 * `PUBLIC_BASE_URL` configurado de propósito vence sempre; sem ele (o padrão do código é o
 * domínio de PRODUÇÃO), a origem de loopback que a tela informa; senão, o domínio
 * publicado. Antes, num ambiente LOCAL sem a variável — a demo, o ambiente de teste, o
 * desenvolvimento — o link apontava para a produção, onde o token local não existe: a
 * vitrine "não abria". A tela só INFORMA a própria origem (em loopback) e mostra o link
 * que o servidor devolve, sem reescrevê-lo.
 */

/** O endereço é do próprio computador (localhost, *.localhost, 127.x, [::1])? O app de
 *  desktop NÃO conta: no Windows ele roda em http://tauri.localhost (no Mac/Linux em
 *  tauri://localhost) ligado ao servidor de verdade — lá vale o link do backend, como na
 *  regra do backend (`core/config.py`, origem local). */
export function ehOrigemLocal(origem: string): boolean {
  try {
    const { protocol, hostname } = new URL(origem);
    if (protocol !== "http:" && protocol !== "https:") return false;
    const host = hostname.replace(/\.$/, "");
    return host === "localhost" || (host.endsWith(".localhost") && host !== "tauri.localhost")
      || /^127\.\d{1,3}\.\d{1,3}\.\d{1,3}$/.test(host) || host === "[::1]";
  } catch {
    return false;
  }
}

/** O caminho de uma chamada da API que devolve (ou gera) o link público, com
 *  `origem=<origem desta tela>` quando a tela roda em loopback — o servidor só usa essa
 *  origem se o `PUBLIC_BASE_URL` não foi configurado. Fora de loopback, o caminho segue igual. */
export function comOrigemLocal(caminho: string, origemDaTela: string = window.location.origin): string {
  if (!ehOrigemLocal(origemDaTela)) return caminho;
  return `${caminho}${caminho.includes("?") ? "&" : "?"}origem=${encodeURIComponent(origemDaTela)}`;
}

/** O link só abre NESTE computador (localhost, *.localhost, 127.x, [::1])? Um telão, um
 *  celular ou o QR lido por outro aparelho não chegam nele — a tela avisa. */
export function linkSoNestaMaquina(url: string | null | undefined): boolean {
  if (!url) return false;
  try {
    return ehOrigemLocal(new URL(url).origin);
  } catch {
    return false;
  }
}
