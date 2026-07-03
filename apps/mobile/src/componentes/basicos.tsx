/** Componentes visuais básicos do app (equivalentes móveis do ui.tsx do web). */
import type { ReactNode } from "react";
import {
  ActivityIndicator,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from "react-native";

import { cores, espacos } from "../tema";

export function Cartao({ children, estilo }: { children: ReactNode; estilo?: object }) {
  return <View style={[estilos.cartao, estilo]}>{children}</View>;
}

export function Titulo({ children }: { children: ReactNode }) {
  return <Text style={estilos.titulo}>{children}</Text>;
}

export function TextoSuave({ children }: { children: ReactNode }) {
  return <Text style={estilos.textoSuave}>{children}</Text>;
}

export function Carregando({ texto = "Carregando..." }: { texto?: string }) {
  return (
    <View style={estilos.carregando}>
      <ActivityIndicator color={cores.primaria} />
      <TextoSuave>{texto}</TextoSuave>
    </View>
  );
}

export function Botao({
  titulo,
  onPress,
  desabilitado,
}: {
  titulo: string;
  onPress: () => void;
  desabilitado?: boolean;
}) {
  return (
    <TouchableOpacity
      accessibilityRole="button"
      style={[estilos.botao, desabilitado && estilos.botaoDesabilitado]}
      onPress={onPress}
      disabled={desabilitado}
    >
      <Text style={estilos.botaoTexto}>{titulo}</Text>
    </TouchableOpacity>
  );
}

export function Etiqueta({
  texto,
  tom = "neutro",
}: {
  texto: string;
  tom?: "neutro" | "ok" | "alerta" | "destaque";
}) {
  const fundo = {
    neutro: "#F4F4F5",
    ok: "#ECFDF5",
    alerta: "#FFFBEB",
    destaque: cores.primariaClara,
  }[tom];
  const cor = {
    neutro: cores.textoSuave,
    ok: cores.ok,
    alerta: cores.alerta,
    destaque: cores.primaria,
  }[tom];
  return (
    <View style={[estilos.etiqueta, { backgroundColor: fundo }]}>
      <Text style={{ color: cor, fontSize: 12, fontWeight: "600" }}>{texto}</Text>
    </View>
  );
}

const estilos = StyleSheet.create({
  cartao: {
    backgroundColor: cores.cartao,
    borderRadius: 12,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: cores.borda,
    padding: espacos.l,
    marginBottom: espacos.m,
  },
  titulo: {
    fontSize: 18,
    fontWeight: "700",
    color: cores.texto,
    marginBottom: espacos.s,
  },
  textoSuave: { color: cores.textoSuave, fontSize: 13 },
  carregando: {
    alignItems: "center",
    justifyContent: "center",
    gap: espacos.s,
    paddingVertical: espacos.xl * 2,
  },
  botao: {
    backgroundColor: cores.primaria,
    borderRadius: 10,
    paddingVertical: 12,
    alignItems: "center",
  },
  botaoDesabilitado: { opacity: 0.5 },
  botaoTexto: { color: "#fff", fontWeight: "600", fontSize: 15 },
  etiqueta: {
    alignSelf: "flex-start",
    borderRadius: 6,
    paddingHorizontal: 8,
    paddingVertical: 2,
  },
});
