/** Navegação: abas (Painel, Ranking, Scanner, Ajustes) + pilha para perfis. */
import { createBottomTabNavigator } from "@react-navigation/bottom-tabs";
import { createNativeStackNavigator } from "@react-navigation/native-stack";
import { Text } from "react-native";

import Ajustes from "./telas/Ajustes";
import Painel from "./telas/Painel";
import PerfilAluno from "./telas/PerfilAluno";
import Ranking from "./telas/Ranking";
import Scanner from "./telas/Scanner";
import { cores } from "./tema";

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

function NavegacaoAbas() {
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
      <Abas.Screen name="Painel" component={Painel} />
      <Abas.Screen name="Ranking" component={Ranking} />
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
