/** Perfil do usuário, escola ativa, estado da conexão/cache e logout. */
import { useNetInfo } from "@react-native-community/netinfo";
import { useQueryClient } from "@tanstack/react-query";
import { ScrollView, StyleSheet, Text, TouchableOpacity, View } from "react-native";

import { Botao, Cartao, Etiqueta, TextoSuave, Titulo } from "../componentes/basicos";
import { useAutenticacao } from "../contexto/Autenticacao";
import { BASE_API } from "../api";
import { cores, espacos } from "../tema";

export default function Ajustes() {
  const { usuario, escolas, escolaId, selecionarEscola, sair } = useAutenticacao();
  const rede = useNetInfo();
  const clienteQuery = useQueryClient();

  const online = rede.isConnected !== false;
  const sincronizacao = clienteQuery.getQueryState(["sincronizacao", escolaId]);

  return (
    <ScrollView style={estilos.tela} contentContainerStyle={{ padding: espacos.l }}>
      <Cartao>
        <Titulo>{usuario?.nome}</Titulo>
        <TextoSuave>{usuario?.email}</TextoSuave>
        <View style={{ height: espacos.s }} />
        <Etiqueta texto={usuario?.cargo ?? ""} tom="destaque" />
      </Cartao>

      <Cartao>
        <Titulo>Escola</Titulo>
        {escolas.map((escola) => (
          <TouchableOpacity
            key={escola.id}
            style={[estilos.escola, escola.id === escolaId && estilos.escolaAtiva]}
            onPress={() => selecionarEscola(escola.id)}
          >
            <Text
              style={[
                estilos.escolaNome,
                escola.id === escolaId && { color: cores.primaria },
              ]}
            >
              {escola.nome}
            </Text>
          </TouchableOpacity>
        ))}
      </Cartao>

      <Cartao>
        <Titulo>Sincronização</Titulo>
        <View style={estilos.linhaEstado}>
          <Etiqueta texto={online ? "online" : "offline"} tom={online ? "ok" : "alerta"} />
          <TextoSuave>
            {online
              ? "Dados atualizados automaticamente."
              : "Exibindo o último estado sincronizado — atualiza sozinho ao reconectar."}
          </TextoSuave>
        </View>
        <TextoSuave>
          Última sincronização:{" "}
          {sincronizacao?.dataUpdatedAt
            ? new Date(sincronizacao.dataUpdatedAt).toLocaleString("pt-BR")
            : "ainda não sincronizado"}
        </TextoSuave>
        <TextoSuave>Servidor: {BASE_API}</TextoSuave>
      </Cartao>

      <Botao titulo="Sair da conta" onPress={() => sair()} />
    </ScrollView>
  );
}

const estilos = StyleSheet.create({
  tela: { flex: 1, backgroundColor: cores.fundo },
  escola: {
    paddingVertical: 10,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: cores.borda,
  },
  escolaAtiva: {},
  escolaNome: { fontSize: 14, fontWeight: "600", color: cores.texto },
  linhaEstado: {
    flexDirection: "row",
    alignItems: "center",
    gap: espacos.s,
    marginBottom: espacos.s,
  },
});
