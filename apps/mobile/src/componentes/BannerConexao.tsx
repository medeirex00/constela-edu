/** Faixa fina no topo quando o app está sem conexão (dados vêm do cache). */
import { StyleSheet, Text, View } from "react-native";

import { useOnline } from "../rede";
import { cores, espacos } from "../tema";

export function BannerConexao() {
  const online = useOnline();
  if (online) return null;
  return (
    <View style={estilos.banner}>
      <Text style={estilos.texto}>Sem conexão — exibindo os dados salvos.</Text>
    </View>
  );
}

const estilos = StyleSheet.create({
  banner: {
    backgroundColor: cores.alerta,
    paddingVertical: espacos.xs,
    paddingHorizontal: espacos.m,
    alignItems: "center",
  },
  texto: { color: "#fff", fontSize: 12, fontWeight: "600" },
});
