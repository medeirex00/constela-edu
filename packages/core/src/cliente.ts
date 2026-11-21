/**
 * Cliente HTTP da API do Constela Edu — compartilhado por Web, Mobile e Desktop.
 *
 * Nada aqui depende de navegador: armazenamento de token e reação à sessão
 * expirada são ADAPTADORES injetados por cada plataforma na inicialização
 * (web → localStorage, mobile → SecureStore, desktop → localStorage do
 * WebView). A base da API também é configurável, porque só o web em
 * desenvolvimento tem proxy `/api` — desktop e mobile falam direto com o
 * servidor.
 */

export class ApiError extends Error {
  status: number;
  /** O id da requisição no log do servidor (cabeçalho X-Request-ID), quando veio. */
  requestId?: string;
  constructor(status: number, mensagem: string, requestId?: string) {
    super(mensagem);
    this.status = status;
    if (requestId) this.requestId = requestId;
  }
}

/** O id que o servidor põe em toda resposta (X-Request-ID, exposto no CORS) e grava em
 *  cada linha do log daquela requisição. Só o formato que ele gera (letras, números e
 *  hífen): um valor estranho, de um proxy no caminho, não vai para a tela. */
export function idDaRequisicao(resposta: Response): string | undefined {
  const cabecalhos = (resposta as { headers?: { get?: unknown } }).headers;
  if (!cabecalhos || typeof cabecalhos.get !== "function") return undefined;
  const id = ((cabecalhos as Headers).get("X-Request-ID") ?? "").trim();
  return /^[A-Za-z0-9-]{8,64}$/.test(id) ? id : undefined;
}

/** Num erro do SERVIDOR (5xx), a mensagem termina com o começo do id da requisição —
 *  "(código: 4f1c2b9a)" — para a pessoa repassar ao suporte, que acha o erro no log por
 *  ele. Nos erros de quem pediu (4xx), a mensagem já diz o que corrigir e fica como está. */
export function comCodigoDeSuporte(mensagem: string, status: number, requestId?: string): string {
  if (status < 500 || !requestId) return mensagem;
  return `${mensagem} (código: ${requestId.slice(0, 8)})`;
}

export interface ArmazenamentoToken {
  obter(): string | null | Promise<string | null>;
  guardar(token: string): void | Promise<void>;
  remover(): void | Promise<void>;
}

interface ConfiguracaoApi {
  /** Ex.: "/api/v1" (web com proxy) ou "https://servidor:8000/api/v1". */
  base?: string;
  armazenamento?: ArmazenamentoToken;
  /** Chamado em 401 — cada app decide como voltar ao login. */
  aoExpirarSessao?: () => void;
}

let base = "/api/v1";
let aoExpirarSessao: () => void = () => undefined;

// Padrão em memória: funciona em testes e antes da configuração da plataforma.
let tokenEmMemoria: string | null = null;
let armazenamento: ArmazenamentoToken = {
  obter: () => tokenEmMemoria,
  guardar: (token) => {
    tokenEmMemoria = token;
  },
  remover: () => {
    tokenEmMemoria = null;
  },
};

let ultimaAlteracaoDoToken = Promise.resolve();

/** Serializa gravação e invalidação quando o cofre da plataforma é assíncrono. */
function alterarToken(alterar: () => void | Promise<void>): Promise<void> {
  const resultado = ultimaAlteracaoDoToken.then(alterar);
  ultimaAlteracaoDoToken = resultado.catch(() => undefined);
  return resultado;
}

export function configurarApi(config: ConfiguracaoApi): void {
  if (config.base !== undefined) base = config.base.replace(/\/$/, "");
  if (config.armazenamento) armazenamento = config.armazenamento;
  if (config.aoExpirarSessao) aoExpirarSessao = config.aoExpirarSessao;
}

export function baseDaApi(): string {
  return base;
}

export async function obterToken(): Promise<string | null> {
  return armazenamento.obter();
}

export function guardarToken(token: string): Promise<void> {
  return alterarToken(() => armazenamento.guardar(token));
}

export function limparToken(): Promise<void> {
  return alterarToken(() => armazenamento.remover());
}

/** Uma resposta atrasada só pode invalidar a sessão que fez a requisição. */
export function invalidarSessao(tokenDaRequisicao: string | null): Promise<void> {
  if (!tokenDaRequisicao) return Promise.resolve();
  return alterarToken(async () => {
    const leitura = armazenamento.obter();
    const tokenAtual = typeof leitura === "string" || leitura === null ? leitura : await leitura;
    if (tokenAtual !== tokenDaRequisicao) return;
    const remocao = armazenamento.remover();
    if (remocao) await remocao;
    aoExpirarSessao();
  });
}

async function extrairDetalhe(resposta: Response, padrao: string): Promise<string> {
  try {
    const corpo = await resposta.json();
    if (typeof corpo.detail === "string") return corpo.detail;
    // 422 de validação (Pydantic): `detail` é uma LISTA de {loc, msg, ...}. Sem
    // isto, "senha fraca" ou "e-mail inválido" viravam a mensagem genérica e o
    // gestor não sabia o que corrigir.
    if (Array.isArray(corpo.detail)) {
      const mensagens = corpo.detail
        .map((item: { msg?: unknown }) => (typeof item?.msg === "string" ? item.msg : ""))
        // Pydantic v2 prefixa "Value error, " nos erros de validador — ruído para quem lê.
        .map((msg: string) => msg.replace(/^Value error,\s*/i, "").trim())
        .filter(Boolean);
      if (mensagens.length) return Array.from(new Set(mensagens)).join(" ");
    }
  } catch {
    /* corpo não-JSON */
  }
  return padrao;
}

/** Mensagem amigável (pt-BR) de falha de REDE — nunca o "Failed to fetch" cru
 *  do navegador, que chegava a ser NARRADO para a criança no Quest. */
export const MENSAGEM_SEM_REDE =
  "Não foi possível conectar. Verifique a internet e tente de novo.";

async function buscar(url: string, init: RequestInit): Promise<Response> {
  try {
    return await fetch(url, init);
  } catch (erro) {
    // Timeout/cancelamento NÃO é falta de internet: um AbortController que
    // estoura (useApi usa "TimeoutError") ou o cancelamento ao desmontar
    // ("AbortError") precisa PROPAGAR para o chamador — o useApi mapeia o
    // timeout para 408 ("A conexão demorou demais") e ignora o abort. Sem esta
    // ponte, uma requisição lenta era rotulada como "sem internet".
    // Compara pelo NOME, não por `instanceof DOMException`: o React Native
    // (Hermes) não tem DOMException global — ler o identificador lançava
    // ReferenceError — e o abort do fetch dele usa um DOMException local.
    const nome = (erro as { name?: unknown } | null)?.name;
    if (nome === "TimeoutError" || nome === "AbortError") {
      throw erro;
    }
    // Falha de REDE real (offline, DNS, CORS, servidor fora) — um TypeError em
    // inglês. Vira ApiError(0) traduzido: status 0 sinaliza "transitório" (a UI
    // pode reconectar em vez de tratar como erro final).
    throw new ApiError(0, MENSAGEM_SEM_REDE);
  }
}

async function tratarErro(resposta: Response, token: string | null): Promise<never> {
  if (resposta.status === 401) {
    await invalidarSessao(token);
    throw new ApiError(401, "Sessão expirada. Entre novamente.");
  }
  const requestId = idDaRequisicao(resposta);
  const mensagem = await extrairDetalhe(resposta, "Não foi possível completar a operação.");
  throw new ApiError(resposta.status, comCodigoDeSuporte(mensagem, resposta.status, requestId),
    requestId);
}

/** Corpo JSON de uma resposta OK. 204 (No Content) e corpo vazio devolvem
 *  `undefined`: `resposta.json()` lançava SyntaxError num sucesso sem corpo
 *  (resolver alerta, remover credencial...) e a tela o tratava como falha. */
async function lerCorpo<T>(resposta: Response): Promise<T> {
  if (resposta.status === 204) return undefined as T;
  const texto = await resposta.text();
  return (texto.trim() ? JSON.parse(texto) : undefined) as T;
}

export async function api<T>(
  caminho: string, opcoes: RequestInit = {}, tokenDaSessao?: string,
): Promise<T> {
  const token = await obterToken();
  if (tokenDaSessao !== undefined && token !== tokenDaSessao) {
    throw new ApiError(401, "Esta operação pertence a uma sessão encerrada.");
  }
  const resposta = await buscar(`${base}${caminho}`, {
    ...opcoes,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...((opcoes.headers as Record<string, string>) ?? {}),
    },
  });
  if (!resposta.ok) await tratarErro(resposta, token);
  return lerCorpo<T>(resposta);
}

/** Envio multipart (upload de arquivos) — a plataforma define o Content-Type. */
export async function apiUpload<T>(caminho: string, dados: FormData): Promise<T> {
  const token = await obterToken();
  const resposta = await buscar(`${base}${caminho}`, {
    method: "POST",
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: dados,
  });
  if (!resposta.ok) await tratarErro(resposta, token);
  return lerCorpo<T>(resposta);
}

/** Busca um recurso binário autenticado (PDF, XLSX...) e devolve o Blob. */
export async function apiBlob(
  caminho: string,
): Promise<{ blob: Blob; nomeArquivo: string }> {
  const token = await obterToken();
  const resposta = await buscar(`${base}${caminho}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!resposta.ok) await tratarErro(resposta, token);
  const disposicao = resposta.headers.get("Content-Disposition") ?? "";
  const nomeArquivo = /filename="?([^";]+)"?/.exec(disposicao)?.[1] ?? "arquivo";
  return { blob: await resposta.blob(), nomeArquivo };
}

export async function loginRequest(email: string, senha: string) {
  const corpo = new URLSearchParams({ username: email, password: senha });
  const resposta = await buscar(`${base}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: corpo.toString(),
  });
  if (!resposta.ok) {
    const requestId = idDaRequisicao(resposta);
    const detalhe = await extrairDetalhe(resposta, "Falha no login.");
    throw new ApiError(resposta.status, comCodigoDeSuporte(detalhe, resposta.status, requestId),
      requestId);
  }
  return resposta.json();
}
