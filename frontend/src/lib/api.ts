const BASE = "/api/v1";
const CHAVE_TOKEN = "sgpe_token";

export class ApiError extends Error {
  status: number;
  constructor(status: number, mensagem: string) {
    super(mensagem);
    this.status = status;
  }
}

export function obterToken(): string | null {
  return localStorage.getItem(CHAVE_TOKEN);
}

export function guardarToken(token: string): void {
  localStorage.setItem(CHAVE_TOKEN, token);
}

export function limparToken(): void {
  localStorage.removeItem(CHAVE_TOKEN);
}

export async function api<T>(caminho: string, opcoes: RequestInit = {}): Promise<T> {
  const token = obterToken();
  const resposta = await fetch(`${BASE}${caminho}`, {
    ...opcoes,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(opcoes.headers ?? {}),
    },
  });

  if (resposta.status === 401) {
    limparToken();
    window.location.href = "/login";
    throw new ApiError(401, "Sessão expirada. Entre novamente.");
  }
  if (!resposta.ok) {
    let detalhe = "Não foi possível completar a operação.";
    try {
      const corpo = await resposta.json();
      if (typeof corpo.detail === "string") detalhe = corpo.detail;
    } catch {
      /* corpo não-JSON */
    }
    throw new ApiError(resposta.status, detalhe);
  }
  return resposta.json() as Promise<T>;
}

/** Envio multipart (upload de arquivos) — o navegador define o Content-Type. */
export async function apiUpload<T>(caminho: string, dados: FormData): Promise<T> {
  const token = obterToken();
  const resposta = await fetch(`${BASE}${caminho}`, {
    method: "POST",
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: dados,
  });
  if (resposta.status === 401) {
    limparToken();
    window.location.href = "/login";
    throw new ApiError(401, "Sessão expirada. Entre novamente.");
  }
  if (!resposta.ok) {
    let detalhe = "Não foi possível completar a operação.";
    try {
      const corpo = await resposta.json();
      if (typeof corpo.detail === "string") detalhe = corpo.detail;
    } catch {
      /* corpo não-JSON */
    }
    throw new ApiError(resposta.status, detalhe);
  }
  return resposta.json() as Promise<T>;
}

export async function loginRequest(email: string, senha: string) {
  const corpo = new URLSearchParams({ username: email, password: senha });
  const resposta = await fetch(`${BASE}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: corpo,
  });
  if (!resposta.ok) {
    const dados = await resposta.json().catch(() => ({}));
    throw new ApiError(resposta.status, dados.detail ?? "Falha no login.");
  }
  return resposta.json();
}
