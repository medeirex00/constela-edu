/**
 * Painel (dashboard) — usa o pacote consolidado /sincronizacao: uma única
 * viagem de rede hidrata estatísticas, destaque, alertas e mural. Com o
 * cache persistido, tudo isso reaparece instantaneamente offline.
 *
 * Desempenho POR MATÉRIA (Arquitetura 2): uma média por matéria contratada,
 * cada uma só sobre quem tem dado da plataforma dela, e o Top com a nota de
 * cada matéria — "—" para quem não usa a plataforma, nunca 0,0. Nenhuma nota
 * composta entre matérias é lida nem exibida (regras em `../materias`).
 */
import { api, numero, tempoLeitura, type PacoteSincronizacao } from "@constela/core";
import { useQuery } from "@tanstack/react-query";
import { RefreshControl, ScrollView, StyleSheet, Text, View } from "react-native";

import { Carregando, Cartao, Etiqueta, TextoSuave, Titulo } from "../componentes/basicos";
import { useAutenticacao } from "../contexto/Autenticacao";
import { materiasDaEscola, mediasDaEscola, notasDoItem } from "../materias";
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
  const { escolaId, escolas, usuario } = useAutenticacao();
  const escola = escolas.find((item) => item.id === escolaId);

  const { data, isLoading, refetch, isRefetching, dataUpdatedAt } = useQuery({
    queryKey: ["sincronizacao", escolaId],
    queryFn: () => api<PacoteSincronizacao>(`/escolas/${escolaId}/sincronizacao`),
    enabled: escolaId !== null,
  });

  if (isLoading && !data) return <Carregando texto="Sincronizando..." />;
  if (!data) return <Carregando texto="Sem dados — conecte-se uma vez para sincronizar." />;

  const painel = data.dashboard;
  // Matéria fora do plano da rede não aparece — nem a média, nem os totais da
  // plataforma dela, nem a nota dela no Top.
  const materias = materiasDaEscola(data, usuario?.modulos);
  const temLeitura = materias.includes("leitura");
  const temMatematica = materias.includes("matematica");
  // `null` = pacote salvo por um servidor anterior às médias por matéria: a tela
  // avisa em vez de voltar para a média composta.
  const medias = mediasDaEscola(painel, materias);
  const top = painel.top10.slice(0, 5);

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
        {(medias ?? []).map((media) => (
          <Estatistica
            key={media.materia}
            rotulo={`Média em ${media.rotulo} (${numero(media.comDado)} com dado)`}
            valor={media.valor}
          />
        ))}
        {temMatematica && (
          <Estatistica rotulo="Atividades" valor={numero(painel.total_atividades)} />
        )}
        {temLeitura && <Estatistica rotulo="Livros" valor={numero(painel.total_livros)} />}
        {temLeitura && (
          <Estatistica rotulo="Tempo de leitura" valor={tempoLeitura(painel.tempo_leitura_min)} />
        )}
        <Estatistica rotulo="Turmas" valor={numero(painel.total_turmas)} />
      </View>
      {medias === null && materias.length > 0 && (
        <TextoSuave>
          As médias por matéria ainda não vieram neste pacote — puxe para sincronizar.
        </TextoSuave>
      )}

      {/* A ORDEM deste Top é a que o servidor decide para o painel da escola:
          trocá-la por um Top por matéria muda quem sobe ao pódio, e isso é
          decisão de produto pendente (plano de retirada §4, item 7). O que o
          app mostra é a nota de CADA matéria, nunca a composta. */}
      <Cartao>
        <Titulo>Top 5 — Ranking Geral</Titulo>
        {top.map((item) => {
          const notas = notasDoItem(item, materias);
          return (
            <View key={item.aluno_id} style={estilos.linha}>
              <Etiqueta texto={`${item.posicao}º`} tom={item.posicao <= 3 ? "destaque" : "neutro"} />
              <View style={estilos.linhaCorpo}>
                <Text style={estilos.linhaNome} numberOfLines={1}>
                  {item.nome}
                </Text>
                {notas.length > 0 && (
                  <TextoSuave>{notas.map((n) => `${n.rotulo} ${n.valor}`).join(" · ")}</TextoSuave>
                )}
              </View>
            </View>
          );
        })}
        {top.length > 0 && materias.length > 0 && (
          <TextoSuave>"—" = ainda sem dado da plataforma (não é nota zero).</TextoSuave>
        )}
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
  linhaCorpo: { flex: 1 },
  linhaNome: { color: cores.texto, fontSize: 14, fontWeight: "500" },
  alerta: { flexDirection: "row", alignItems: "flex-start", gap: espacos.s, paddingVertical: 4 },
  alertaTexto: { flex: 1, fontSize: 13, color: cores.texto },
  muralTexto: { flex: 1, fontSize: 13, color: cores.texto },
});
