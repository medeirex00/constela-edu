/** Navegação: abas (Painel, Ranking, Scanner, Ajustes) + pilha para perfis. */
import type { Usuario } from "@constela/core";
import { createBottomTabNavigator } from "@react-navigation/bottom-tabs";
import { createNativeStackNavigator } from "@react-navigation/native-stack";
import { ScrollView, Text } from "react-native";

import { Cartao, TextoSuave, Titulo } from "./componentes/basicos";
import { useAutenticacao } from "./contexto/Autenticacao";
import Ajustes from "./telas/Ajustes";
import Painel from "./telas/Painel";
import PerfilAluno from "./telas/PerfilAluno";
import Ranking from "./telas/Ranking";
import Scanner from "./telas/Scanner";
import { cores, espacos } from "./tema";

export type PilhaPrincipal = {
  Abas: undefined;
  PerfilAluno: { alunoId: number; nome: string };
};

const Abas = createBottomTabNavigator();
const Pilha = createNativeStackNavigator<PilhaPrincipal>();

const ICONES: Record<string, string> = {
  Painel: "📊",
  Ranking: "🏆",
  Scanner: "📷",
  Ajustes: "⚙️",
};

/** Secretaria (SEDUC): conta com rede e NÃO global — a mesma regra da web
 *  (`usePerfil`) e do servidor (`permissoes.e_secretaria`). */
export function ehSecretaria(usuario: Usuario | null): boolean {
  return usuario != null && !usuario.is_global && usuario.rede_id != null;
}

/** No lugar do Painel da escola, para a Secretaria. Ela nunca vê nome de criança, e
 *  o pacote do app é recortado por isso: os números da escola sairiam todos 0 (o
 *  servidor responde 403 com esta mesma explicação). Sem o Ranking, pelo mesmo
 *  motivo. */
function PainelDaSecretaria() {
  return (
    <ScrollView
      style={{ flex: 1, backgroundColor: cores.fundo }}
      contentContainerStyle={{ padding: espacos.l }}
    >
      <Cartao>
        <Titulo>Acompanhamento da rede</Titulo>
        <TextoSuave>
          No aplicativo, os números de cada escola são de quem trabalha nela. A Secretaria
          acompanha a rede pelo Panorama da Rede, na versão web.
        </TextoSuave>
      </Cartao>
    </ScrollView>
  );
}

function NavegacaoAbas() {
  const { usuario } = useAutenticacao();
  const secretaria = ehSecretaria(usuario);
  return (
    <Abas.Navigator
      screenOptions={({ route }) => ({
        headerTitleStyle: { fontWeight: "700" },
        tabBarActiveTintColor: cores.primaria,
        tabBarIcon: ({ focused }) => (
          <Text style={{ fontSize: 18, opacity: focused ? 1 : 0.45 }}>
            {ICONES[route.name] ?? "•"}
          </Text>
        ),
      })}
    >
      <Abas.Screen name="Painel" component={secretaria ? PainelDaSecretaria : Painel} />
      {secretaria ? null : <Abas.Screen name="Ranking" component={Ranking} />}
      <Abas.Screen name="Scanner" component={Scanner} options={{ headerShown: false }} />
      <Abas.Screen name="Ajustes" component={Ajustes} />
    </Abas.Navigator>
  );
}

export function NavegacaoPrincipal() {
  return (
    <Pilha.Navigator>
      <Pilha.Screen name="Abas" component={NavegacaoAbas} options={{ headerShown: false }} />
      <Pilha.Screen
        name="PerfilAluno"
        component={PerfilAluno}
        options={({ route }) => ({ title: route.params.nome })}
      />
    </Pilha.Navigator>
  );
}
