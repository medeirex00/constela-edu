/**
 * Ranking POR MATÉRIA (Leitura, Matemática — só as contratadas) e de Evolução,
 * com toque para abrir o perfil do aluno.
 *
 * Cada aba de matéria é a ordenação OFICIAL da Arquitetura 2: só os alunos
 * AFERIDOS naquela matéria, com a nota e a posição que o servidor carimbou
 * nela. Quem não tem dado da plataforma não entra com 0,0 — sai da lista,
 * porque ausência não é zero — e aparece LOGO ABAIXO, no bloco "Ainda não
 * aferidos em <matéria>", sem nota e sem posição (spec §1.2, consequência 3, e
 * §2.4). O bloco não é enfeite: esta tela é a única porta do app para o perfil
 * do aluno, e sem ele a criança sem dado ficaria inalcançável. O Ranking Geral
 * (ordem única pela nota composta) não é mais lido pelo app.
 *
 * Fonte da lista: o pacote de sincronização quando ele traz
 * `ranking_por_dimensao` (uma viagem de rede, disponível offline); senão a rota
 * oficial `GET /ranking?dimensao=` — a mesma do web, também guardada no cache
 * cifrado. Os não aferidos vêm de `GET /nao-aferidos` (também a do web, também
 * no cache cifrado). Sem alguma delas, a aba explica o porquê em vez de quebrar.
 */
import { api, nota, numero, type PacoteSincronizacao } from "@constela/core";
import { useQuery } from "@tanstack/react-query";
import { useNavigation } from "@react-navigation/native";
import type { NativeStackNavigationProp } from "@react-navigation/native-stack";
import { useState } from "react";
import {
  RefreshControl,
  SectionList,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from "react-native";

import { Carregando, Etiqueta, TextoSuave } from "../componentes/basicos";
import { useAutenticacao } from "../contexto/Autenticacao";
import {
  estadoDoRanking,
  linhasDaMateria,
  materiasDaEscola,
  naoAferidosDaMateria,
  rankingDoPacote,
  rotuloDaMateria,
  totalAferidos,
  type EstadoNaoAferidos,
  type LinhaNaoAferido,
  type LinhaRanking,
} from "../materias";
import type { PilhaPrincipal } from "../navegacao";
import { cores, espacos } from "../tema";

type Aba = "leitura" | "matematica" | "evolucao";

/** Uma linha da tela: do ranking (com posição e nota) ou da lista de quem ainda
 *  não foi aferido (sem as duas, de propósito). */
type LinhaDaTela =
  | ({ tipo: "ranking" } & LinhaRanking)
  | ({ tipo: "nao-aferido" } & LinhaNaoAferido);

interface Secao {
  chave: "ranking" | "nao-aferidos";
  data: LinhaDaTela[];
}

export default function Ranking() {
  const { escolaId, usuario } = useAutenticacao();
  const navegacao = useNavigation<NativeStackNavigationProp<PilhaPrincipal>>();
  const [aba, setAba] = useState<Aba | null>(null);

  const { data, isLoading, refetch, isRefetching } = useQuery({
    queryKey: ["sincronizacao", escolaId],
    queryFn: () => api<PacoteSincronizacao>(`/escolas/${escolaId}/sincronizacao`),
    enabled: escolaId !== null,
  });

  // Cascata CONTRATO → DADO: a matéria que a rede não assinou não vira uma aba
  // permanentemente vazia (que se leria como "ninguém aqui usa a plataforma").
  const abas: Aba[] = [...materiasDaEscola(data, usuario?.modulos), "evolucao"];
  // A aba escolhida pode não existir nesta escola (troca de escola, contrato
  // mudou): cai na primeira disponível.
  const abaAtiva: Aba = aba !== null && abas.includes(aba) ? aba : abas[0];
  const materia = abaAtiva === "evolucao" ? null : abaAtiva;

  // Pacote sem a lista por matéria (servidor anterior ou cache antigo): busca a
  // da rota oficial. Só dispara para a aba aberta e só quando o pacote já foi
  // lido — se ele traz a lista, nenhuma viagem extra.
  const precisaDaRota =
    escolaId !== null && materia !== null && data !== undefined
    && rankingDoPacote(data, materia) === null;
  const rota = useQuery({
    queryKey: ["ranking-materia", escolaId, materia],
    queryFn: () => api<unknown>(`/escolas/${escolaId}/ranking?dimensao=${materia}`),
    enabled: precisaDaRota,
  });

  // Quem ainda NÃO foi aferido — uma consulta só para todas as matérias (a rota
  // devolve as listas de cada uma), feita quando alguma aba de matéria abre. O
  // escopo (professor: as turmas dele; Secretaria: listas vazias) é do servidor.
  const naoAferidos = useQuery({
    queryKey: ["nao-aferidos", escolaId],
    queryFn: () => api<unknown>(`/escolas/${escolaId}/nao-aferidos`),
    enabled: escolaId !== null && materia !== null,
  });

  if (isLoading && !data) return <Carregando />;

  let itens: LinhaRanking[] = [];
  let cabecalho: string | null = null;
  let aviso: string | null = null;
  let carregandoMateria = false;
  let semDado: EstadoNaoAferidos = { tipo: "oculto" };
  if (materia !== null) {
    const estado = estadoDoRanking(materia, data, {
      dados: rota.data,
      erro: rota.error,
      carregando: rota.isLoading,
    });
    if (estado.tipo === "lista") {
      itens = linhasDaMateria(estado.itens);
      const total = totalAferidos(estado.itens);
      cabecalho = `${numero(total)} ${total === 1 ? "aluno" : "alunos"} com dado em `
        + `${rotuloDaMateria(materia)} · quem ainda não tem dado da plataforma não entra `
        + "nesta lista (não é nota zero): aparece abaixo, sem nota e sem posição.";
    } else if (estado.tipo === "aviso") {
      aviso = estado.texto;
    } else {
      carregandoMateria = true;
    }
    semDado = naoAferidosDaMateria(materia, {
      dados: naoAferidos.data,
      erro: naoAferidos.error,
      carregando: naoAferidos.isLoading,
    });
  } else {
    // Evolução: inalterada nesta mudança — o crescimento composto é assunto
    // próprio da spec (§7, decisão do dono), separado da nota geral.
    itens = (data?.evolucao ?? []).map((item) => ({
      chave: item.aluno_id,
      posicao: item.posicao,
      nome: item.nome,
      detalhe: item.turma,
      valor: nota(item.nota_evolucao),
    }));
  }

  const secoes: Secao[] = [
    { chave: "ranking", data: itens.map((linha) => ({ tipo: "ranking" as const, ...linha })) },
  ];
  if (semDado.tipo === "lista") {
    secoes.push({
      chave: "nao-aferidos",
      data: semDado.linhas.map((linha) => ({ tipo: "nao-aferido" as const, ...linha })),
    });
  }

  const abrirPerfil = (linha: LinhaDaTela) =>
    navegacao.navigate("PerfilAluno", { alunoId: linha.chave, nome: linha.nome });

  return (
    <View style={estilos.tela}>
      <View style={estilos.abas}>
        {abas.map((opcao) => (
          <TouchableOpacity
            key={opcao}
            style={[estilos.aba, abaAtiva === opcao && estilos.abaAtiva]}
            onPress={() => setAba(opcao)}
          >
            <Text style={[estilos.abaTexto, abaAtiva === opcao && estilos.abaTextoAtivo]}>
              {opcao === "evolucao" ? "Evolução (30d)" : rotuloDaMateria(opcao)}
            </Text>
          </TouchableOpacity>
        ))}
      </View>

      {carregandoMateria ? (
        <Carregando />
      ) : (
        <SectionList<LinhaDaTela, Secao>
          sections={secoes}
          keyExtractor={(item) => `${item.tipo}-${item.chave}`}
          contentContainerStyle={{ padding: espacos.l }}
          stickySectionHeadersEnabled={false}
          refreshControl={
            <RefreshControl
              refreshing={isRefetching}
              onRefresh={() => {
                void refetch();
                if (precisaDaRota) void rota.refetch();
                if (materia !== null) void naoAferidos.refetch();
              }}
            />
          }
          ListHeaderComponent={
            cabecalho && itens.length > 0 ? (
              <View style={estilos.cabecalho}>
                <TextoSuave>{cabecalho}</TextoSuave>
              </View>
            ) : null
          }
          renderSectionHeader={({ section }) =>
            section.chave === "nao-aferidos" && semDado.tipo === "lista" ? (
              // NÃO é rodapé decorativo: é a lista de ação da coordenação.
              <View style={estilos.blocoSemDado}>
                <Text style={estilos.tituloBloco}>{semDado.titulo}</Text>
                <TextoSuave>{semDado.explicacao}</TextoSuave>
              </View>
            ) : null
          }
          renderSectionFooter={({ section }) =>
            section.chave === "ranking" && section.data.length === 0 ? (
              <TextoSuave>
                {aviso
                  ?? (materia !== null
                    ? `Nenhum aluno com dado em ${rotuloDaMateria(materia)} ainda.`
                    : "Sem dados no período.")}
              </TextoSuave>
            ) : null
          }
          // Sem a lista (carregando, rota ausente, cache antigo, sem acesso): a
          // aba DIZ que ela falta — o bloco nunca some calado.
          ListFooterComponent={
            semDado.tipo === "carregando" || semDado.tipo === "aviso" ? (
              <View style={estilos.blocoSemDado}>
                <TextoSuave>
                  {semDado.tipo === "aviso"
                    ? semDado.texto
                    : "Carregando quem ainda não foi aferido…"}
                </TextoSuave>
              </View>
            ) : null
          }
          renderItem={({ item }) =>
            item.tipo === "ranking" ? (
              <TouchableOpacity style={estilos.linha} onPress={() => abrirPerfil(item)}>
                <Etiqueta texto={`${item.posicao}º`} tom={item.posicao <= 3 ? "destaque" : "neutro"} />
                <View style={{ flex: 1 }}>
                  <Text style={estilos.nome}>{item.nome}</Text>
                  <TextoSuave>{item.detalhe}</TextoSuave>
                </View>
                <Text style={estilos.valor}>{item.valor}</Text>
              </TouchableOpacity>
            ) : (
              // Sem posição e sem número: não há o que medir, não "foi mal".
              <TouchableOpacity style={estilos.linha} onPress={() => abrirPerfil(item)}>
                <View style={{ flex: 1 }}>
                  <Text style={estilos.nome}>{item.nome}</Text>
                  {item.detalhe ? <TextoSuave>{item.detalhe}</TextoSuave> : null}
                </View>
                <Text style={estilos.semValor}>—</Text>
              </TouchableOpacity>
            )
          }
        />
      )}
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
  cabecalho: { marginBottom: espacos.s },
  blocoSemDado: { marginTop: espacos.xl, marginBottom: espacos.s, gap: espacos.xs },
  tituloBloco: { fontSize: 15, fontWeight: "700", color: cores.texto },
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
  semValor: { fontSize: 16, fontWeight: "700", color: cores.textoSuave },
});
