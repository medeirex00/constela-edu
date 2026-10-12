/**
 * Perfil do aluno: a nota e a posição de CADA matéria contratada e o "como esta
 * nota foi calculada" de cada uma.
 *
 * Arquitetura 2: não existe mais uma nota "Geral" nem uma posição única no
 * ranking — compor as matérias é o que a arquitetura eliminou. Cada matéria
 * traz a SUA posição ("3º de 21"), e a matéria sem dado da plataforma mostra
 * "—", nunca 0,0 (regras e fontes em `../materias`).
 */
import { api, nota, type LinhaCalculo, type PerfilAluno as Perfil } from "@constela/core";
import { useQuery } from "@tanstack/react-query";
import type { NativeStackScreenProps } from "@react-navigation/native-stack";
import { ScrollView, StyleSheet, Text, View } from "react-native";

import { Carregando, Cartao, Etiqueta, TextoSuave, Titulo } from "../componentes/basicos";
import { useAutenticacao } from "../contexto/Autenticacao";
import { blocosDoPerfil, calculoDaMateria } from "../materias";
import type { PilhaPrincipal } from "../navegacao";
import { cores, espacos } from "../tema";

type Props = NativeStackScreenProps<PilhaPrincipal, "PerfilAluno">;

// Nome da plataforma de cada matéria no título do passo a passo do cálculo.
const PLATAFORMA = { leitura: "Elefante Letrado", matematica: "Matific" } as const;

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
  const { escolaId, usuario } = useAutenticacao();
  const { alunoId } = route.params;

  const { data: perfil, isLoading } = useQuery({
    queryKey: ["perfil", escolaId, alunoId],
    queryFn: () => api<Perfil>(`/escolas/${escolaId}/alunos/${alunoId}/perfil`),
    enabled: escolaId !== null,
  });

  if (isLoading && !perfil) return <Carregando />;
  if (!perfil) return <Carregando texto="Perfil indisponível offline — conecte-se uma vez." />;

  const { blocos, carimbado } = blocosDoPerfil(perfil, usuario?.modulos);
  // O passo a passo só das matérias COM dado: para quem não usa a plataforma o
  // motor grava uma conta de zeros, que afirmaria uma nota 0,0 nunca medida.
  const calculos = blocos.flatMap((bloco) => {
    const calculo = calculoDaMateria(perfil, bloco);
    return calculo ? [{ bloco, calculo }] : [];
  });

  return (
    <ScrollView style={estilos.tela} contentContainerStyle={{ padding: espacos.l }}>
      <Titulo>{perfil.aluno.nome}</Titulo>
      <View style={estilos.etiquetas}>
        <Etiqueta texto={`${perfil.aluno.turma ?? ""} · ${perfil.aluno.ano_escolar ?? ""}`} />
      </View>

      {blocos.length > 0 && (
        <View style={estilos.notas}>
          {blocos.map((bloco) => (
            <View key={bloco.materia} style={estilos.nota}>
              <Text style={estilos.notaValor}>{bloco.valor}</Text>
              <TextoSuave>{bloco.rotulo}</TextoSuave>
              {bloco.posicao ? (
                <Etiqueta texto={bloco.posicao} tom="destaque" />
              ) : bloco.aferido === false ? (
                <TextoSuave>sem dado da plataforma</TextoSuave>
              ) : null}
            </View>
          ))}
        </View>
      )}
      {!carimbado && blocos.length > 0 && (
        <TextoSuave>
          A posição em cada matéria aparece depois do próximo recálculo da escola.
        </TextoSuave>
      )}

      {calculos.map(({ bloco, calculo }) => (
        <TabelaCalculo
          key={bloco.materia}
          titulo={PLATAFORMA[bloco.materia]}
          linhas={calculo.indicadores}
          notaFinal={calculo.nota}
        />
      ))}
      {calculos.length === 0 && (
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
    gap: espacos.xs,
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
