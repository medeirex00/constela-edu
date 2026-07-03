/**
 * Adaptador Web/Desktop do cliente compartilhado (@sgpe/core).
 *
 * A lógica HTTP vive no pacote core (compartilhada com o mobile); aqui ficam
 * apenas as decisões de plataforma:
 *   - token no localStorage (síncrono, como o AppContext espera);
 *   - sessão expirada → redireciona para /login;
 *   - base da API: proxy relativo "/api/v1" no web; no desktop (Tauri) não há
 *     proxy, então o build injeta VITE_API_URL apontando para o servidor.
 */
import { apiBlob, configurarApi } from "@sgpe/core";

export { api, apiUpload, loginRequest, ApiError } from "@sgpe/core";

const CHAVE_TOKEN = "sgpe_token";

export function obterToken(): string | null {
  return localStorage.getItem(CHAVE_TOKEN);
}

export function guardarToken(token: string): void {
  localStorage.setItem(CHAVE_TOKEN, token);
}

export function limparToken(): void {
  localStorage.removeItem(CHAVE_TOKEN);
}

configurarApi({
  base: (import.meta.env.VITE_API_URL as string | undefined) ?? "/api/v1",
  armazenamento: {
    obter: obterToken,
    guardar: guardarToken,
    remover: limparToken,
  },
  aoExpirarSessao: () => {
    window.location.href = "/login";
  },
});

/** Baixa um arquivo autenticado e dispara o download no navegador (DOM). */
export async function apiDownload(caminho: string): Promise<void> {
  const { blob, nomeArquivo } = await apiBlob(caminho);
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = nomeArquivo;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
