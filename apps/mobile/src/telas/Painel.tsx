/**
 * Painel (dashboard) — usa o pacote consolidado /sincronizacao: uma única
 * viagem de rede hidrata estatísticas, destaque, alertas e mural. Com o
 * cache persistido, tudo isso reaparece instantaneamente offline.
 */
import { api, nota, numero, tempoLeitura, type PacoteSincronizacao } from "@sgpe/core";
import { useQuery } from "@tanstack/react-query";
import { RefreshControl, ScrollView, StyleSheet, Text, View } from "react-native";

import { Carregando, Cartao, Etiqueta, TextoSuave, Titulo } from "../componentes/basicos";
import { useAutenticacao } from "../contexto/Autenticacao";
import { cores, espacos } from "../tema";

function Estatistica({ rotulo, valor }: { rotulo: string; valor: string }) {
  return (
    <View style={estilos.estatistica}>
      <Text style={estilos.estatisticaValor}>{valor}</Text>
      <TextoSuave>{rotulo}</TextoSuave>
    </View>
  );
}

export default function Painel() {
  const { escolaId, escolas } = useAutenticacao();
  const escola = escolas.find((item) => item.id === escolaId);

  const { data, isLoading, refetch, isRefetching, dataUpdatedAt } = useQuery({
    queryKey: ["sincronizacao", escolaId],
    queryFn: () => api<PacoteSincronizacao>(`/escolas/${escolaId}/sincronizacao`),
    enabled: escolaId !== null,
  });

  if (isLoading && !data) return <Carregando texto="Sincronizando..." />;
  if (!data) return <Carregando texto="Sem dados — conecte-se uma vez para sincronizar." />;

  const painel = data.dashboard;

  return (
    <ScrollView
      style={estilos.tela}
      contentContainerStyle={{ padding: espacos.l }}
      refreshControl={<RefreshControl refreshing={isRefetching} onRefresh={() => refetch()} />}
    >
      <Titulo>{escola?.nome ?? painel.escola.nome}</Titulo>
      <TextoSuave>
        Atualizado em {new Date(dataUpdatedAt).toLocaleString("pt-BR")} · puxe para sincronizar
      </TextoSuave>

      <View style={estilos.grade}>
        <Estatistica rotulo="Alunos" valor={numero(painel.total_alunos)} />
        <Estatistica rotulo="Média geral" valor={nota(painel.media_geral)} />
        <Estatistica rotulo="Atividades" valor={numero(painel.total_atividades)} />
        <Estatistica rotulo="Livros" valor={numero(painel.total_livros)} />
        <Estatistica rotulo="Leitura" valor={tempoLeitura(painel.tempo_leitura_min)} />
        <Estatistica rotulo="Turmas" valor={numero(painel.total_turmas)} />
      </View>

      <Cartao>
        <Titulo>Top 5 — Ranking Geral</Titulo>
        {painel.top10.slice(0, 5).map((item) => (
          <View key={item.aluno_id} style={estilos.linha}>
            <Etiqueta texto={`${item.posicao}º`} tom={item.posicao <= 3 ? "destaque" : "neutro"} />
            <Text style={estilos.linhaNome} numberOfLines={1}>
              {item.nome}
            </Text>
            <Text style={estilos.linhaNota}>{nota(item.nota_geral)}</Text>
          </View>
        ))}
      </Cartao>

      {data.alertas.length > 0 && (
        <Cartao>
          <Titulo>Alertas ({data.alertas.length})</Titulo>
          {data.alertas.slice(0, 5).map((alerta, indice) => (
            <View key={indice} style={estilos.alerta}>
              <Etiqueta texto={alerta.gravidade} tom={alerta.gravidade === "alta" ? "alerta" : "neutro"} />
              <Text style={estilos.alertaTexto}>{alerta.texto}</Text>
            </View>
          ))}
        </Cartao>
      )}

      <Cartao>
        <Titulo>Mural</Titulo>
        {data.mural.length === 0 ? (
          <TextoSuave>Nada por aqui ainda.</TextoSuave>
        ) : (
          data.mural.slice(0, 8).map((evento, indice) => (
            <View key={indice} style={estilos.linha}>
              <Text style={{ fontSize: 16 }}>{evento.icone}</Text>
              <Text style={estilos.muralTexto}>{evento.texto}</Text>
            </View>
          ))
        )}
      </Cartao>
    </ScrollView>
  );
}

const estilos = StyleSheet.create({
  tela: { flex: 1, backgroundColor: cores.fundo },
  grade: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: espacos.m,
    marginVertical: espacos.l,
  },
  estatistica: {
    backgroundColor: cores.cartao,
    borderRadius: 12,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: cores.borda,
    padding: espacos.m,
    minWidth: "30%",
    flexGrow: 1,
  },
  estatisticaValor: { fontSize: 20, fontWeight: "700", color: cores.texto },
  linha: {
    flexDirection: "row",
    alignItems: "center",
    gap: espacos.m,
    paddingVertical: 6,
  },
  linhaNome: { flex: 1, color: cores.texto, fontSize: 14, fontWeight: "500" },
  linhaNota: { fontWeight: "700", color: cores.texto },
  alerta: { flexDirection: "row", alignItems: "flex-start", gap: espacos.s, paddingVertical: 4 },
  alertaTexto: { flex: 1, fontSize: 13, color: cores.texto },
  muralTexto: { flex: 1, fontSize: 13, color: cores.texto },
});
