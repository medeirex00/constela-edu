/**
 * Fronteira de erro (Error Boundary): captura erros de renderização em qualquer
 * tela e mostra uma tela amigável com "tentar de novo", em vez de derrubar o
 * app inteiro (tela branca). Precisa ser componente de classe (a API de
 * fronteira de erro do React só existe em classe).
 */
import { Component, type ReactNode } from "react";
import { StyleSheet, Text, View } from "react-native";

import { cores, espacos } from "../tema";
import { Botao } from "./basicos";

interface Props {
  children: ReactNode;
}
interface Estado {
  erro: Error | null;
}

export class LimiteErro extends Component<Props, Estado> {
  state: Estado = { erro: null };

  static getDerivedStateFromError(erro: Error): Estado {
    return { erro };
  }

  reiniciar = () => this.setState({ erro: null });

  render() {
    if (this.state.erro) {
      return (
        <View style={estilos.centro}>
          <Text style={estilos.titulo}>Algo deu errado</Text>
          <Text style={estilos.texto}>
            Feche e abra o app. Seus dados salvos continuam no aparelho.
          </Text>
          <Botao titulo="Tentar de novo" onPress={this.reiniciar} />
        </View>
      );
    }
    return this.props.children;
  }
}

const estilos = StyleSheet.create({
  centro: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    gap: espacos.m,
    padding: espacos.xl,
    backgroundColor: cores.fundo,
  },
  titulo: { fontSize: 18, fontWeight: "700", color: cores.texto },
  texto: { color: cores.textoSuave, fontSize: 14, textAlign: "center" },
});
