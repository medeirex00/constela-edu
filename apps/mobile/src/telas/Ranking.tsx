/** Ranking Geral e de Evolução, com toque para abrir o perfil do aluno. */
import { api, nota, type PacoteSincronizacao } from "@sgpe/core";
import { useQuery } from "@tanstack/react-query";
import { useNavigation } from "@react-navigation/native";
import type { NativeStackNavigationProp } from "@react-navigation/native-stack";
import { useState } from "react";
import {
  FlatList,
  RefreshControl,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from "react-native";

import { Carregando, Etiqueta, TextoSuave } from "../componentes/basicos";
import { useAutenticacao } from "../contexto/Autenticacao";
import type { PilhaPrincipal } from "../navegacao";
import { cores, espacos } from "../tema";

type Aba = "geral" | "evolucao";

export default function Ranking() {
  const { escolaId } = useAutenticacao();
  const navegacao = useNavigation<NativeStackNavigationProp<PilhaPrincipal>>();
  const [aba, setAba] = useState<Aba>("geral");

  const { data, isLoading, refetch, isRefetching } = useQuery({
    queryKey: ["sincronizacao", escolaId],
    queryFn: () => api<PacoteSincronizacao>(`/escolas/${escolaId}/sincronizacao`),
    enabled: escolaId !== null,
  });

  if (isLoading && !data) return <Carregando />;

  const itens =
    aba === "geral"
      ? (data?.ranking ?? []).map((item) => ({
          chave: item.aluno_id,
          posicao: item.posicao,
          nome: item.nome,
          detalhe: item.turma ?? "",
          valor: item.nota_geral,
        }))
      : (data?.evolucao ?? []).map((item) => ({
          chave: item.aluno_id,
          posicao: item.posicao,
          nome: item.nome,
          detalhe: item.turma,
          valor: item.nota_evolucao,
        }));

  return (
    <View style={estilos.tela}>
      <View style={estilos.abas}>
        {(["geral", "evolucao"] as const).map((opcao) => (
          <TouchableOpacity
            key={opcao}
            style={[estilos.aba, aba === opcao && estilos.abaAtiva]}
            onPress={() => setAba(opcao)}
          >
            <Text style={[estilos.abaTexto, aba === opcao && estilos.abaTextoAtivo]}>
              {opcao === "geral" ? "Ranking Geral" : "Evolução (30d)"}
            </Text>
          </TouchableOpacity>
        ))}
      </View>

      <FlatList
        data={itens}
        keyExtractor={(item) => String(item.chave)}
        contentContainerStyle={{ padding: espacos.l }}
        refreshControl={<RefreshControl refreshing={isRefetching} onRefresh={() => refetch()} />}
        ListEmptyComponent={<TextoSuave>Sem dados no período.</TextoSuave>}
        renderItem={({ item }) => (
          <TouchableOpacity
            style={estilos.linha}
            onPress={() => navegacao.navigate("PerfilAluno", { alunoId: item.chave, nome: item.nome })}
          >
            <Etiqueta texto={`${item.posicao}º`} tom={item.posicao <= 3 ? "destaque" : "neutro"} />
            <View style={{ flex: 1 }}>
              <Text style={estilos.nome}>{item.nome}</Text>
              <TextoSuave>{item.detalhe}</TextoSuave>
            </View>
            <Text style={estilos.valor}>{nota(item.valor)}</Text>
          </TouchableOpacity>
        )}
      />
    </View>
  );
}

const estilos = StyleSheet.create({
  tela: { flex: 1, backgroundColor: cores.fundo },
  abas: {
    flexDirection: "row",
    margin: espacos.l,
    marginBottom: 0,
    backgroundColor: "#EDEDF0",
    borderRadius: 10,
    padding: 3,
  },
  aba: { flex: 1, paddingVertical: 8, borderRadius: 8, alignItems: "center" },
  abaAtiva: { backgroundColor: "#fff" },
  abaTexto: { fontSize: 13, color: cores.textoSuave, fontWeight: "600" },
  abaTextoAtivo: { color: cores.primaria },
  linha: {
    flexDirection: "row",
    alignItems: "center",
    gap: espacos.m,
    backgroundColor: cores.cartao,
    borderRadius: 12,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: cores.borda,
    padding: espacos.m,
    marginBottom: espacos.s,
  },
  nome: { fontSize: 14, fontWeight: "600", color: cores.texto },
  valor: { fontSize: 16, fontWeight: "700", color: cores.texto },
});
