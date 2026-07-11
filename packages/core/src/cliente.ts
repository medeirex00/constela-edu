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
  constructor(status: number, mensagem: string) {
    super(mensagem);
    this.status = status;
  }
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

export async function guardarToken(token: string): Promise<void> {
  await armazenamento.guardar(token);
}

export async function limparToken(): Promise<void> {
  await armazenamento.remover();
}

async function extrairDetalhe(resposta: Response, padrao: string): Promise<string> {
  try {
    const corpo = await resposta.json();
    if (typeof corpo.detail === "string") return corpo.detail;
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
  } catch {
    // fetch só rejeita por falha de REDE (offline, DNS, CORS, servidor fora) —
    // um TypeError em inglês. Vira um ApiError(0) traduzido: status 0 sinaliza
    // "transitório" (a UI pode reconectar em vez de tratar como erro final).
    throw new ApiError(0, MENSAGEM_SEM_REDE);
  }
}

async function tratarErro(resposta: Response): Promise<never> {
  if (resposta.status === 401) {
    await limparToken();
    aoExpirarSessao();
    throw new ApiError(401, "Sessão expirada. Entre novamente.");
  }
  throw new ApiError(
    resposta.status,
    await extrairDetalhe(resposta, "Não foi possível completar a operação."),
  );
}

export async function api<T>(caminho: string, opcoes: RequestInit = {}): Promise<T> {
  const token = await obterToken();
  const resposta = await buscar(`${base}${caminho}`, {
    ...opcoes,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...((opcoes.headers as Record<string, string>) ?? {}),
    },
  });
  if (!resposta.ok) await tratarErro(resposta);
  return resposta.json() as Promise<T>;
}

/** Envio multipart (upload de arquivos) — a plataforma define o Content-Type. */
export async function apiUpload<T>(caminho: string, dados: FormData): Promise<T> {
  const token = await obterToken();
  const resposta = await buscar(`${base}${caminho}`, {
    method: "POST",
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: dados,
  });
  if (!resposta.ok) await tratarErro(resposta);
  return resposta.json() as Promise<T>;
}

/** Busca um recurso binário autenticado (PDF, XLSX...) e devolve o Blob. */
export async function apiBlob(
  caminho: string,
): Promise<{ blob: Blob; nomeArquivo: string }> {
  const token = await obterToken();
  const resposta = await buscar(`${base}${caminho}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!resposta.ok) await tratarErro(resposta);
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
    const detalhe = await extrairDetalhe(resposta, "Falha no login.");
    throw new ApiError(resposta.status, detalhe);
  }
  return resposta.json();
}
