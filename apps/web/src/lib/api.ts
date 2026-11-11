/**
 * Adaptador Web/Desktop do cliente compartilhado (@constela/core).
 *
 * A lógica HTTP vive no pacote core (compartilhada com o mobile); aqui ficam
 * apenas as decisões de plataforma:
 *   - token no localStorage (síncrono, como o AppContext espera);
 *   - sessão expirada → redireciona para /login;
 *   - base da API: proxy relativo "/api/v1" no web; no desktop (Tauri) não há
 *     proxy, então o build injeta VITE_API_URL apontando para o servidor.
 */
import {
  ApiError,
  MENSAGEM_SEM_REDE,
  apiBlob,
  baseDaApi,
  comCodigoDeSuporte,
  configurarApi,
  idDaRequisicao,
} from "@constela/core";

import { ehTelaPublica } from "./pwaAtualizacao";

export { api, apiUpload, loginRequest, ApiError } from "@constela/core";

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

// No desktop (Tauri) o app roda em tauri://localhost — não existe proxy /api.
// Ordem de resolução: VITE_API_URL (build) > padrão local no Tauri > proxy web.
const rodandoNoTauri =
  typeof window !== "undefined" &&
  (window.location.protocol === "tauri:" ||
    window.location.hostname === "tauri.localhost");

configurarApi({
  base:
    (import.meta.env.VITE_API_URL as string | undefined) ??
    (rodandoNoTauri ? "http://localhost:8000/api/v1" : "/api/v1"),
  armazenamento: {
    obter: obterToken,
    guardar: guardarToken,
    remover: limparToken,
  },
  aoExpirarSessao: () => {
    // Página pública (telão, vitrine): sem login — um 401 nunca a troca pela tela de login
    // (o token vencido já foi limpo pelo core).
    if (ehTelaPublica(window.location.pathname)) return;
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

/** Erro de uma resposta não-OK: a mensagem é o `detail` do backend (texto, ou a lista
 *  de validação do Pydantic), como no cliente compartilhado — num 5xx, com o código de
 *  suporte (o começo do X-Request-ID), e o id inteiro em `requestId`. O corpo JSON
 *  inteiro vai em `corpo`, para a tela ler campos extras (ex.: `itens` do 422 do lote de
 *  certificados) sem perder a mensagem. */
async function erroDaResposta(resposta: Response): Promise<ApiError & { corpo?: unknown }> {
  let corpo: unknown;
  let mensagem = "Não foi possível completar a operação.";
  try {
    corpo = await resposta.json();
    const detalhe = (corpo as { detail?: unknown } | null)?.detail;
    if (typeof detalhe === "string") {
      mensagem = detalhe;
    } else if (Array.isArray(detalhe)) {
      const mensagens = detalhe
        .map((item: { msg?: unknown }) => (typeof item?.msg === "string" ? item.msg : ""))
        .map((msg: string) => msg.replace(/^Value error,\s*/i, "").trim())
        .filter(Boolean);
      if (mensagens.length) mensagem = Array.from(new Set(mensagens)).join(" ");
    }
  } catch {
    /* corpo não-JSON */
  }
  const requestId = idDaRequisicao(resposta);
  return Object.assign(
    new ApiError(resposta.status, comCodigoDeSuporte(mensagem, resposta.status, requestId),
      requestId),
    { corpo },
  );
}

/**
 * Baixa um arquivo gerado por POST (ex.: o PDF do lote de certificados) e dispara o
 * download no navegador. Espelha o `apiDownload`: mesmo token, mesma reação à sessão
 * expirada (401 → /login), mesma mensagem de erro (o `detail` do backend) e o nome do
 * arquivo pelo Content-Disposition (`nomePadrao` quando o cabeçalho não traz).
 * Devolve o nome com que o arquivo foi salvo.
 */
export async function apiDownloadPost(
  caminho: string,
  corpo: unknown,
  nomePadrao = "arquivo",
): Promise<string> {
  const token = obterToken();
  let resposta: Response;
  try {
    resposta = await fetch(`${baseDaApi()}${caminho}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify(corpo),
    });
  } catch (erro) {
    // Mesmo critério do cliente compartilhado: timeout/cancelamento propaga; falha de
    // rede vira ApiError(0) com a mensagem amigável (nunca o "Failed to fetch" cru).
    const nome = (erro as { name?: unknown } | null)?.name;
    if (nome === "TimeoutError" || nome === "AbortError") throw erro;
    throw new ApiError(0, MENSAGEM_SEM_REDE);
  }
  if (resposta.status === 401) {
    // A mesma reação do `aoExpirarSessao` configurado acima.
    limparToken();
    window.location.href = "/login";
    throw new ApiError(401, "Sessão expirada. Entre novamente.");
  }
  if (!resposta.ok) throw await erroDaResposta(resposta);
  const disposicao = resposta.headers.get("Content-Disposition") ?? "";
  const nomeArquivo = /filename="?([^";]+)"?/.exec(disposicao)?.[1] ?? nomePadrao;
  const blob = await resposta.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = nomeArquivo;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
  return nomeArquivo;
}
