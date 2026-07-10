/**
 * Mock manual de `../lib/api` (usado automaticamente por `vi.mock` no setup).
 *
 * TODA tela e todo hook consomem a API por este módulo (`api`, `apiUpload`,
 * `loginRequest`, `apiDownload` + helpers de token). Interceptando aqui, os
 * testes rodam sem rede, de forma determinística, exercitando o componente REAL
 * e os hooks REAIS (useApi/useMutation) — só o transporte HTTP é falso.
 *
 * Um registro de "handlers" casa (método, caminho) → resposta. Os testes
 * declaram o que a API deve responder com `responder(...)` / `responderErro(...)`
 * e o `api` mockado despacha por esse registro.
 */
import { vi } from "vitest";

/** Réplica fiel do ApiError do @constela/core (mesma forma: status + message).
 *  Precisa ser a MESMA classe que os hooks importam de `../lib/api` para os
 *  `instanceof ApiError` continuarem valendo. */
export class ApiError extends Error {
  status: number;
  constructor(status: number, mensagem: string) {
    super(mensagem);
    this.name = "ApiError";
    this.status = status;
  }
}

type Metodo = "GET" | "POST" | "PATCH" | "PUT" | "DELETE" | "UPLOAD";
type Padrao = string | RegExp | ((caminho: string) => boolean);
type Resposta =
  | unknown
  | ApiError
  | ((caminho: string, opcoes: RequestInit | FormData) => unknown);

interface Handler {
  metodo: Metodo;
  padrao: Padrao;
  resposta: Resposta;
}

const handlers: Handler[] = [];
let tokenEmMemoria: string | null = null;

function casa(padrao: Padrao, caminho: string): boolean {
  if (typeof padrao === "function") return padrao(caminho);
  if (padrao instanceof RegExp) return padrao.test(caminho);
  // String: casa o MESMO caminho (com ou sem query string), mas NUNCA um
  // sub-caminho mais profundo — senão "/escolas" casaria "/escolas/1/dashboard".
  // Para prefixos amplos, use RegExp ou função.
  const semQuery = caminho.split("?")[0];
  return caminho === padrao || semQuery === padrao || caminho.startsWith(`${padrao}?`);
}

function resolver(metodo: Metodo, caminho: string, corpo: RequestInit | FormData): unknown {
  // Percorre do mais recente para o mais antigo: o último `responder` vence
  // (permite sobrescrever um padrão default no meio do teste).
  for (let i = handlers.length - 1; i >= 0; i--) {
    const h = handlers[i];
    if (h.metodo === metodo && casa(h.padrao, caminho)) {
      const valor = typeof h.resposta === "function"
        ? (h.resposta as (c: string, o: RequestInit | FormData) => unknown)(caminho, corpo)
        : h.resposta;
      if (valor instanceof ApiError) throw valor;
      return valor;
    }
  }
  throw new ApiError(404, `Sem handler mockado para ${metodo} ${caminho}`);
}

/** `api(caminho, {method})` — despacha pelo registro de handlers. */
export const api = vi.fn(
  async <T>(caminho: string, opcoes: RequestInit = {}): Promise<T> => {
    const metodo = (opcoes.method ?? "GET").toUpperCase() as Metodo;
    return resolver(metodo, caminho, opcoes) as T;
  },
);

/** Upload multipart — despachado como método "UPLOAD". */
export const apiUpload = vi.fn(
  async <T>(caminho: string, dados: FormData): Promise<T> => {
    return resolver("UPLOAD", caminho, dados) as T;
  },
);

/** Login — vi.fn com default de sucesso; sobrescreva com mockRejectedValueOnce. */
export const loginRequest = vi.fn(async (_email: string, _senha: string) => ({
  access_token: "token-de-teste",
  token_type: "bearer",
}));

/** Download de arquivo — no-op observável (asserção via toHaveBeenCalledWith). */
export const apiDownload = vi.fn(async (_caminho: string): Promise<void> => undefined);

// --- Adaptadores de token (equivalentes síncronos da versão web real) --------
export function obterToken(): string | null {
  return tokenEmMemoria;
}
export function guardarToken(token: string): void {
  tokenEmMemoria = token;
}
export function limparToken(): void {
  tokenEmMemoria = null;
}

// --- API de configuração dos testes ------------------------------------------

/** Registra a resposta de sucesso para um (método, caminho). */
export function responder(metodo: Metodo, padrao: Padrao, resposta: Resposta): void {
  handlers.push({ metodo, padrao, resposta });
}

/** Registra uma FALHA (status + mensagem) para um (método, caminho). */
export function responderErro(
  metodo: Metodo, padrao: Padrao, status: number, mensagem = "Erro de teste",
): void {
  handlers.push({ metodo, padrao, resposta: new ApiError(status, mensagem) });
}

/** Zera handlers, token e o histórico dos vi.fn — chamado no afterEach global. */
export function resetApiMock(): void {
  handlers.length = 0;
  tokenEmMemoria = null;
  api.mockClear();
  apiUpload.mockClear();
  apiDownload.mockClear();
  loginRequest.mockClear();
  loginRequest.mockResolvedValue({ access_token: "token-de-teste", token_type: "bearer" });
}
