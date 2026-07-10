/**
 * QueryClient e persister compartilhados. Ficam num módulo próprio para que o
 * logout (no contexto de autenticação) também consiga LIMPAR o cache em memória
 * e o blob persistido — sem isso, os dados do usuário anterior sobreviveriam no
 * aparelho até expirarem.
 */
import { ApiError } from "@constela/core";
import { createAsyncStoragePersister } from "@tanstack/query-async-storage-persister";
import { QueryClient } from "@tanstack/react-query";

import { armazenamentoCifrado } from "./armazenamento/armazenamentoCifrado";

export const clienteQuery = new QueryClient({
  defaultOptions: {
    queries: {
      networkMode: "offlineFirst",
      staleTime: 60 * 1000,
      gcTime: 7 * 24 * 60 * 60 * 1000, // uma semana de cache offline
      refetchOnReconnect: "always",
      // Backoff exponencial (1s, 2s, 4s… até 30s), mas erros do cliente (4xx,
      // incl. 401/403) não se resolvem repetindo — não retenta.
      retry: (contador, erro) => {
        if (erro instanceof ApiError && erro.status >= 400 && erro.status < 500) {
          return false;
        }
        return contador < 3;
      },
      retryDelay: (tentativa) => Math.min(1000 * 2 ** tentativa, 30_000),
    },
  },
});

// Cache persistido e CIFRADO em repouso (chave no SecureStore).
export const persistidor = createAsyncStoragePersister({ storage: armazenamentoCifrado });
