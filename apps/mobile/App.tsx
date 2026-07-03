/**
 * SGPE Mobile — offline-first.
 *
 * Estratégia offline/sincronização:
 *   - TanStack Query com cache PERSISTIDO no AsyncStorage: as telas abrem
 *     instantaneamente com o último estado sincronizado, mesmo sem rede.
 *   - onlineManager ligado ao NetInfo: ao voltar a conexão, todas as
 *     consultas ativas são re-buscadas automaticamente (refetchOnReconnect).
 *   - focusManager ligado ao AppState: voltar ao app também revalida.
 *   - Escritas exigem rede (são raras no celular — o app é primariamente
 *     de consulta); leituras funcionam sempre.
 */
import NetInfo from "@react-native-community/netinfo";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { NavigationContainer } from "@react-navigation/native";
import { QueryClient, focusManager, onlineManager } from "@tanstack/react-query";
import { createAsyncStoragePersister } from "@tanstack/query-async-storage-persister";
import { PersistQueryClientProvider } from "@tanstack/react-query-persist-client";
import { StatusBar } from "expo-status-bar";
import { useEffect } from "react";
import { AppState, Platform } from "react-native";
import { SafeAreaProvider } from "react-native-safe-area-context";

import { Carregando } from "./src/componentes/basicos";
import { ProvedorAutenticacao, useAutenticacao } from "./src/contexto/Autenticacao";
import { NavegacaoPrincipal } from "./src/navegacao";
import Entrar from "./src/telas/Entrar";

// Reconexão → revalida tudo (a "sincronização automática" pedida no produto)
onlineManager.setEventListener((setOnline) =>
  NetInfo.addEventListener((estado) => {
    setOnline(!!estado.isConnected);
  }),
);

const clienteQuery = new QueryClient({
  defaultOptions: {
    queries: {
      networkMode: "offlineFirst",
      staleTime: 60 * 1000,
      gcTime: 7 * 24 * 60 * 60 * 1000, // uma semana de cache offline
      retry: 1,
      refetchOnReconnect: "always",
    },
  },
});

const persistidor = createAsyncStoragePersister({ storage: AsyncStorage });

function Raiz() {
  const { usuario, carregando } = useAutenticacao();

  useEffect(() => {
    const inscricao = AppState.addEventListener("change", (estado) => {
      if (Platform.OS !== "web") focusManager.setFocused(estado === "active");
    });
    return () => inscricao.remove();
  }, []);

  if (carregando) return <Carregando texto="Abrindo o SGPE..." />;
  if (!usuario) return <Entrar />;
  return (
    <NavigationContainer>
      <NavegacaoPrincipal />
    </NavigationContainer>
  );
}

export default function App() {
  return (
    <SafeAreaProvider>
      <PersistQueryClientProvider
        client={clienteQuery}
        persistOptions={{ persister: persistidor, maxAge: 7 * 24 * 60 * 60 * 1000 }}
      >
        <ProvedorAutenticacao>
          <StatusBar style="auto" />
          <Raiz />
        </ProvedorAutenticacao>
      </PersistQueryClientProvider>
    </SafeAreaProvider>
  );
}
