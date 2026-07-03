import { useState } from "react";
import {
  KeyboardAvoidingView,
  Platform,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";

import { Botao, Cartao, TextoSuave } from "../componentes/basicos";
import { useAutenticacao } from "../contexto/Autenticacao";
import { cores, espacos } from "../tema";

export default function Entrar() {
  const { entrar } = useAutenticacao();
  const [email, setEmail] = useState("");
  const [senha, setSenha] = useState("");
  const [erro, setErro] = useState("");
  const [ocupado, setOcupado] = useState(false);

  async function enviar() {
    setOcupado(true);
    setErro("");
    try {
      await entrar(email.trim(), senha);
    } catch (excecao) {
      setErro(excecao instanceof Error ? excecao.message : "Falha no login.");
    } finally {
      setOcupado(false);
    }
  }

  return (
    <KeyboardAvoidingView
      style={estilos.tela}
      behavior={Platform.OS === "ios" ? "padding" : undefined}
    >
      <View style={estilos.marca}>
        <View style={estilos.logo}>
          <Text style={estilos.logoTexto}>S</Text>
        </View>
        <Text style={estilos.nome}>SGPE</Text>
        <TextoSuave>Gestão e Premiação Escolar</TextoSuave>
      </View>

      <Cartao>
        <TextInput
          style={estilos.campo}
          placeholder="E-mail"
          autoCapitalize="none"
          autoComplete="email"
          keyboardType="email-address"
          value={email}
          onChangeText={setEmail}
        />
        <TextInput
          style={estilos.campo}
          placeholder="Senha"
          secureTextEntry
          value={senha}
          onChangeText={setSenha}
          onSubmitEditing={enviar}
        />
        {erro ? <Text style={estilos.erro}>{erro}</Text> : null}
        <Botao
          titulo={ocupado ? "Entrando..." : "Entrar"}
          onPress={enviar}
          desabilitado={ocupado || !email.trim() || !senha}
        />
      </Cartao>
    </KeyboardAvoidingView>
  );
}

const estilos = StyleSheet.create({
  tela: {
    flex: 1,
    backgroundColor: cores.fundo,
    justifyContent: "center",
    padding: espacos.xl,
  },
  marca: { alignItems: "center", marginBottom: espacos.xl },
  logo: {
    width: 56,
    height: 56,
    borderRadius: 14,
    backgroundColor: cores.primaria,
    alignItems: "center",
    justifyContent: "center",
    marginBottom: espacos.s,
  },
  logoTexto: { color: "#fff", fontSize: 28, fontWeight: "800" },
  nome: { fontSize: 22, fontWeight: "800", color: cores.texto },
  campo: {
    borderWidth: 1,
    borderColor: cores.borda,
    borderRadius: 10,
    paddingHorizontal: 12,
    paddingVertical: 10,
    fontSize: 15,
    marginBottom: espacos.m,
    backgroundColor: "#fff",
  },
  erro: { color: cores.erro, marginBottom: espacos.m, fontSize: 13 },
});
