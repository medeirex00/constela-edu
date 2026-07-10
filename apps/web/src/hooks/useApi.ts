/**
 * Arquitetura única de consumo de API no web.
 *
 * `useApi` substitui o padrão repetido (e frágil) espalhado pelas telas:
 *
 *   const [dados, setDados] = useState<T | null>(null);
 *   const [carregando, setCarregando] = useState(true);
 *   useEffect(() => {
 *     api<T>(url).then(setDados).catch(() => setDados(null)).finally(...);
 *   }, [dep]);            // erro engolido, sem cancelamento, sem timeout/retry
 *
 * por uma única linha declarativa:
 *
 *   const { dados, erro, carregando, recarregar } = useApi<T>(url);
 *
 * Entrega: dados · erro · carregando · recarregar · cancelamento (AbortController)
 * · timeout · retry (só em falha transitória) · cache opcional em memória.
 */
import { useCallback, useEffect, useRef, useState, type DependencyList } from "react";

import { ApiError, api } from "../lib/api";

/** Busca customizada (POST, composição de chamadas...) recebendo o sinal de
 *  cancelamento. Para GET simples, passe apenas a URL. */
export type Buscador<T> = (sinal: AbortSignal) => Promise<T>;

/** `null` = ocioso (não busca) — ideal para dependências ainda indefinidas. */
export type FonteApi<T> = string | Buscador<T> | null;

export interface OpcoesUseApi<T> {
  /** Para o buscador-função: refaz a busca quando estas dependências mudam. */
  chave?: DependencyList;
  /** `false` não busca (fica ocioso). Útil para gates (ex.: sem escola ainda). */
  ativo?: boolean;
  /** Aborta a requisição após N ms (0 desliga). Padrão: 15s. */
  timeoutMs?: number;
  /** Nº de RETENTATIVAS extras em falha transitória (rede/5xx/timeout). Padrão: 1. */
  tentativas?: number;
  /** > 0 guarda o resultado em memória por essa duração (só para fonte-URL). */
  cacheMs?: number;
  /** Efeito colateral opcional ao falhar (ex.: toast). */
  aoErro?: (erro: ApiError) => void;
  /** Chamado com os dados a cada busca bem-sucedida. */
  aoSucesso?: (dados: T) => void;
}

export interface ResultadoUseApi<T> {
  dados: T | null;
  erro: ApiError | null;
  carregando: boolean;
  /** Refaz a busca AGORA, ignorando o cache. */
  recarregar: () => void;
}

// Cache em memória compartilhado por URL (opt-in via `cacheMs`).
const _cache = new Map<string, { valor: unknown; expira: number }>();

/** Limpa o cache: tudo, ou só as chaves que contêm `prefixo`. */
export function limparCacheApi(prefixo?: string): void {
  if (prefixo === undefined) {
    _cache.clear();
    return;
  }
  for (const chave of _cache.keys()) {
    if (chave.includes(prefixo)) _cache.delete(chave);
  }
}

function _paraApiError(erro: unknown): ApiError {
  if (erro instanceof ApiError) return erro;
  if (erro instanceof DOMException && erro.name === "TimeoutError") {
    return new ApiError(408, "A conexão demorou demais. Tente novamente.");
  }
  return new ApiError(0, "Falha de conexão. Verifique a internet e tente de novo.");
}

/** Só falhas TRANSITÓRIAS voltam a ser tentadas: rede, timeout e 5xx. Erros do
 *  cliente (4xx) e sessão expirada (401) não se resolvem repetindo. */
function _transitorio(erro: ApiError): boolean {
  return erro.status === 0 || erro.status === 408 || erro.status >= 500;
}

function _espera(ms: number, sinal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(resolve, ms);
    sinal.addEventListener("abort", () => {
      clearTimeout(timer);
      reject(new DOMException("Aborted", "AbortError"));
    }, { once: true });
  });
}

/** Executa a busca com timeout por tentativa, encadeado ao sinal do componente. */
async function _buscarComTimeout<T>(
  buscar: Buscador<T>, sinalComponente: AbortSignal, timeoutMs: number,
): Promise<T> {
  const ctrl = new AbortController();
  const propagar = () => ctrl.abort(sinalComponente.reason);
  if (sinalComponente.aborted) propagar();
  else sinalComponente.addEventListener("abort", propagar, { once: true });
  const timer = timeoutMs > 0
    ? setTimeout(() => ctrl.abort(new DOMException("Timeout", "TimeoutError")), timeoutMs)
    : null;
  try {
    return await buscar(ctrl.signal);
  } finally {
    if (timer) clearTimeout(timer);
    sinalComponente.removeEventListener("abort", propagar);
  }
}

export function useApi<T>(
  fonte: FonteApi<T>,
  opcoes: OpcoesUseApi<T> = {},
): ResultadoUseApi<T> {
  const {
    ativo = true, timeoutMs = 15000, tentativas = 1, cacheMs = 0,
    aoErro, aoSucesso, chave = [],
  } = opcoes;

  const urlFonte = typeof fonte === "string" ? fonte : null;
  const habilitado = ativo && fonte !== null;

  const [dados, setDados] = useState<T | null>(() => {
    if (cacheMs > 0 && urlFonte) {
      const c = _cache.get(urlFonte);
      if (c && c.expira > Date.now()) return c.valor as T;
    }
    return null;
  });
  const [erro, setErro] = useState<ApiError | null>(null);
  const [carregando, setCarregando] = useState(habilitado);
  const [gatilho, setGatilho] = useState(0);

  // Callbacks e o buscador-função vivem em refs para não entrarem na lista de
  // dependências do efeito (evita rebuscas por identidade nova a cada render).
  const refBuscador = useRef(fonte);
  refBuscador.current = fonte;
  const refAoErro = useRef(aoErro);
  refAoErro.current = aoErro;
  const refAoSucesso = useRef(aoSucesso);
  refAoSucesso.current = aoSucesso;

  const recarregar = useCallback(() => setGatilho((n) => n + 1), []);

  useEffect(() => {
    if (!habilitado) {
      // Fonte ociosa (busca abaixo do mínimo, escola ainda não escolhida...):
      // volta ao estado vazio para não exibir resultado obsoleto.
      setCarregando(false);
      setDados(null);
      setErro(null);
      return;
    }
    // Cache: entrega imediata quando fresco (recarregar() usa gatilho e ignora).
    if (cacheMs > 0 && urlFonte && gatilho === 0) {
      const c = _cache.get(urlFonte);
      if (c && c.expira > Date.now()) {
        setDados(c.valor as T);
        setErro(null);
        setCarregando(false);
        return;
      }
    }

    const controller = new AbortController();
    let vivo = true;
    setCarregando(true);
    setErro(null);

    const buscar: Buscador<T> = typeof refBuscador.current === "function"
      ? (refBuscador.current as Buscador<T>)
      : (sinal) => api<T>(urlFonte as string, { signal: sinal });

    (async () => {
      let ultimo: ApiError | null = null;
      for (let tentativa = 0; tentativa <= tentativas; tentativa++) {
        try {
          const valor = await _buscarComTimeout(buscar, controller.signal, timeoutMs);
          if (!vivo) return;
          setDados(valor);
          if (cacheMs > 0 && urlFonte) {
            _cache.set(urlFonte, { valor, expira: Date.now() + cacheMs });
          }
          refAoSucesso.current?.(valor);
          return;
        } catch (bruto) {
          if (controller.signal.aborted && (bruto as DOMException)?.name === "AbortError") {
            return;                       // cancelado pelo componente: silencioso
          }
          ultimo = _paraApiError(bruto);
          if (tentativa < tentativas && _transitorio(ultimo)) {
            try {
              await _espera(300 * 2 ** tentativa, controller.signal);  // backoff
              continue;
            } catch {
              return;                     // abortado durante o backoff
            }
          }
          break;
        }
      }
      if (!vivo || !ultimo) return;
      setErro(ultimo);
      refAoErro.current?.(ultimo);
    })().finally(() => {
      if (vivo) setCarregando(false);
    });

    return () => {
      vivo = false;
      controller.abort();
    };
    // urlFonte cobre a fonte-URL; `chave` cobre a fonte-função; gatilho força reload.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [urlFonte, habilitado, timeoutMs, tentativas, cacheMs, gatilho, ...chave]);

  return { dados, erro, carregando, recarregar };
}
