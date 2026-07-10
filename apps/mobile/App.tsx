/**
 * Constela Edu Mobile — offline-first.
 *
 * Estratégia offline/sincronização:
 *   - TanStack Query com cache PERSISTIDO e CIFRADO (AES-256, chave no
 *     SecureStore): as telas abrem instantaneamente com o último estado
 *     sincronizado, mesmo sem rede, e o dado sensível (LGPD) fica cifrado no
 *     aparelho.
 *   - onlineManager ligado ao NetInfo: ao voltar a conexão, as consultas ativas
 *     são re-buscadas (refetchOnReconnect) E a fila de escritas offline é
 *     drenada (reconexão automática).
 *   - focusManager ligado ao AppState: voltar ao app também revalida.
 *   - retry com backoff exponencial que NÃO repete erros 4xx (não se resolvem
 *     repetindo).
 *   - LimiteErro (Error Boundary) evita a "tela branca" em erro de render.
 */
import NetInfo from "@react-native-community/netinfo";
import { NavigationContainer } from "@react-navigation/native";
import { focusManager, onlineManager } from "@tanstack/react-query";
import { PersistQueryClientProvider } from "@tanstack/react-query-persist-client";
import { StatusBar } from "expo-status-bar";
import { useEffect } from "react";
import { AppState, Platform, View } from "react-native";
import { SafeAreaProvider } from "react-native-safe-area-context";

import { clienteQuery, persistidor } from "./src/cliente-query";
import { BannerConexao } from "./src/componentes/BannerConexao";
import { Carregando } from "./src/componentes/basicos";
import { LimiteErro } from "./src/componentes/LimiteErro";
import { ProvedorAutenticacao, useAutenticacao } from "./src/contexto/Autenticacao";
import { ligarFilaAReconexao, processarFila } from "./src/filaOffline";
import { NavegacaoPrincipal } from "./src/navegacao";
import Entrar from "./src/telas/Entrar";

// Reconexão → revalida tudo (a "sincronização automática" pedida no produto).
onlineManager.setEventListener((setOnline) =>
  NetInfo.addEventListener((estado) => {
    setOnline(!!estado.isConnected);
  }),
);

// A fila de escritas offline drena sozinha quando a rede volta (vive todo o
// ciclo do app).
ligarFilaAReconexao();

function Raiz() {
  const { usuario, carregando } = useAutenticacao();

  useEffect(() => {
    const inscricao = AppState.addEventListener("change", (estado) => {
      if (Platform.OS !== "web") focusManager.setFocused(estado === "active");
    });
    return () => inscricao.remove();
  }, []);

  let conteudo: JSX.Element;
  if (carregando) conteudo = <Carregando texto="Abrindo o Constela Edu..." />;
  else if (!usuario) conteudo = <Entrar />;
  else
    conteudo = (
      <NavigationContainer>
        <NavegacaoPrincipal />
      </NavigationContainer>
    );

  return (
    <View style={{ flex: 1 }}>
      <BannerConexao />
      {conteudo}
    </View>
  );
}

export default function App() {
  return (
    <SafeAreaProvider>
      <LimiteErro>
        <PersistQueryClientProvider
          client={clienteQuery}
          persistOptions={{ persister: persistidor, maxAge: 7 * 24 * 60 * 60 * 1000 }}
          onSuccess={() => {
            // Cache restaurado no boot: retoma mutações pausadas e drena a fila
            // (caso o app tenha sido fechado com escritas pendentes e já haja rede).
            void clienteQuery.resumePausedMutations();
            void processarFila();
          }}
        >
          <ProvedorAutenticacao>
            <StatusBar style="auto" />
            <Raiz />
          </ProvedorAutenticacao>
        </PersistQueryClientProvider>
      </LimiteErro>
    </SafeAreaProvider>
  );
}
