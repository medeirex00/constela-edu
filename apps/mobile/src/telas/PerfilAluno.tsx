/** Perfil do aluno: notas, posição e o "como esta nota foi calculada". */
import { api, nota, type LinhaCalculo, type PerfilAluno as Perfil } from "@sgpe/core";
import { useQuery } from "@tanstack/react-query";
import type { NativeStackScreenProps } from "@react-navigation/native-stack";
import { ScrollView, StyleSheet, Text, View } from "react-native";

import { Carregando, Cartao, Etiqueta, TextoSuave, Titulo } from "../componentes/basicos";
import { useAutenticacao } from "../contexto/Autenticacao";
import type { PilhaPrincipal } from "../navegacao";
import { cores, espacos } from "../tema";

type Props = NativeStackScreenProps<PilhaPrincipal, "PerfilAluno">;

function TabelaCalculo({ titulo, linhas, notaFinal }: {
  titulo: string;
  linhas: LinhaCalculo[];
  notaFinal: number;
}) {
  return (
    <Cartao>
      <View style={estilos.cabecalhoTabela}>
        <Titulo>{titulo}</Titulo>
        <Text style={estilos.notaFinal}>{nota(notaFinal)}</Text>
      </View>
      {linhas.map((linha) => (
        <View key={linha.indicador} style={estilos.linhaCalculo}>
          <Text style={estilos.indicador}>{linha.indicador}</Text>
          <TextoSuave>
            {nota(linha.valor)} → {nota(linha.normalizado)} × {linha.peso}% ={" "}
            {nota(linha.contribuicao)}
          </TextoSuave>
        </View>
      ))}
    </Cartao>
  );
}

export default function PerfilAluno({ route }: Props) {
  const { escolaId } = useAutenticacao();
  const { alunoId } = route.params;

  const { data: perfil, isLoading } = useQuery({
    queryKey: ["perfil", escolaId, alunoId],
    queryFn: () => api<Perfil>(`/escolas/${escolaId}/alunos/${alunoId}/perfil`),
    enabled: escolaId !== null,
  });

  if (isLoading && !perfil) return <Carregando />;
  if (!perfil) return <Carregando texto="Perfil indisponível offline — conecte-se uma vez." />;

  const { detalhes } = perfil;

  return (
    <ScrollView style={estilos.tela} contentContainerStyle={{ padding: espacos.l }}>
      <Titulo>{perfil.aluno.nome}</Titulo>
      <View style={estilos.etiquetas}>
        {perfil.posicao ? <Etiqueta texto={`${perfil.posicao}º no ranking`} tom="destaque" /> : null}
        <Etiqueta texto={`${perfil.aluno.turma ?? ""} · ${perfil.aluno.ano_escolar ?? ""}`} />
      </View>

      <View style={estilos.notas}>
        {[
          { rotulo: "Matific", valor: perfil.nota_matific },
          { rotulo: "Leitura", valor: perfil.nota_elefante },
          { rotulo: "Geral", valor: perfil.nota_geral },
        ].map((item) => (
          <View key={item.rotulo} style={estilos.nota}>
            <Text style={estilos.notaValor}>{nota(item.valor)}</Text>
            <TextoSuave>{item.rotulo}</TextoSuave>
          </View>
        ))}
      </View>

      {detalhes.matific && (
        <TabelaCalculo
          titulo="Matific"
          linhas={detalhes.matific.indicadores}
          notaFinal={detalhes.matific.nota}
        />
      )}
      {detalhes.elefante && (
        <TabelaCalculo
          titulo="Elefante Letrado"
          linhas={detalhes.elefante.indicadores}
          notaFinal={detalhes.elefante.nota}
        />
      )}
      {!detalhes.matific && !detalhes.elefante && (
        <Cartao>
          <TextoSuave>Ainda não há nota calculada para este aluno.</TextoSuave>
        </Cartao>
      )}
    </ScrollView>
  );
}

const estilos = StyleSheet.create({
  tela: { flex: 1, backgroundColor: cores.fundo },
  etiquetas: { flexDirection: "row", gap: espacos.s, marginBottom: espacos.l },
  notas: { flexDirection: "row", gap: espacos.m, marginBottom: espacos.l },
  nota: {
    flex: 1,
    backgroundColor: cores.cartao,
    borderRadius: 12,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: cores.borda,
    padding: espacos.m,
    alignItems: "center",
  },
  notaValor: { fontSize: 20, fontWeight: "700", color: cores.texto },
  cabecalhoTabela: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  notaFinal: { fontSize: 18, fontWeight: "700", color: cores.primaria },
  linhaCalculo: {
    paddingVertical: 6,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: cores.borda,
  },
  indicador: { fontSize: 13, fontWeight: "600", color: cores.texto },
});
