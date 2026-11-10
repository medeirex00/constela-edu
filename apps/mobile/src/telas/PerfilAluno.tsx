/** Perfil do aluno: notas, posição e o "como esta nota foi calculada". */
import { api, nota, type LinhaCalculo, type PerfilAluno as Perfil } from "@constela/core";
import { useQuery } from "@tanstack/react-query";
import type { NativeStackScreenProps } from "@react-navigation/native-stack";
import { ScrollView, StyleSheet, Text, View } from "react-native";

import { Carregando, Cartao, Etiqueta, TextoSuave, Titulo } from "../componentes/basicos";
import { useAutenticacao } from "../contexto/Autenticacao";
import type { PilhaPrincipal } from "../navegacao";
import { notasDoPerfil } from "../notasDoPerfil";
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

/** No lugar do passo a passo de uma plataforma sem dado da criança. */
function SemDadoDaPlataforma({ plataforma }: { plataforma: string }) {
  return (
    <Cartao>
      <Titulo>{plataforma}</Titulo>
      <TextoSuave>Ainda não há dados desta criança nesta plataforma, por isso não há nota (“—”).</TextoSuave>
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
  // "—" para quem não tem dado da plataforma (o mesmo critério da web).
  const notas = notasDoPerfil(perfil);

  return (
    <ScrollView style={estilos.tela} contentContainerStyle={{ padding: espacos.l }}>
      <Titulo>{perfil.aluno.nome}</Titulo>
      <View style={estilos.etiquetas}>
        {perfil.posicao ? <Etiqueta texto={`${perfil.posicao}º no ranking`} tom="destaque" /> : null}
        <Etiqueta texto={`${perfil.aluno.turma ?? ""} · ${perfil.aluno.ano_escolar ?? ""}`} />
      </View>

      <View style={estilos.notas}>
        {[
          { rotulo: "Matific", valor: notas.matific },
          { rotulo: "Leitura", valor: notas.leitura },
          { rotulo: "Geral", valor: notas.geral },
        ].map((item) => (
          <View key={item.rotulo} style={estilos.nota}>
            {/* Sem dado da plataforma ou módulo fora do plano: "—", nunca um 0,0 falso. */}
            <Text style={estilos.notaValor}>{item.valor}</Text>
            <TextoSuave>{item.rotulo}</TextoSuave>
          </View>
        ))}
      </View>

      {notas.semDadoNenhum ? (
        <Cartao>
          <TextoSuave>Ainda não há dados desta criança nas plataformas.</TextoSuave>
        </Cartao>
      ) : (
        <>
          {detalhes.matific && (notas.calculoMatific ? (
            <TabelaCalculo
              titulo="Matific"
              linhas={detalhes.matific.indicadores}
              notaFinal={detalhes.matific.nota}
            />
          ) : <SemDadoDaPlataforma plataforma="Matific" />)}
          {detalhes.elefante && (notas.calculoLeitura ? (
            <TabelaCalculo
              titulo="Elefante Letrado"
              linhas={detalhes.elefante.indicadores}
              notaFinal={detalhes.elefante.nota}
            />
          ) : <SemDadoDaPlataforma plataforma="Elefante Letrado" />)}
          {!detalhes.matific && !detalhes.elefante && (
            <Cartao>
              <TextoSuave>Ainda não há nota calculada para este aluno.</TextoSuave>
            </Cartao>
          )}
        </>
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
