/**
 * Ranking de Leitura (Elefante Letrado) — um bloco principal e duas seções
 * secundárias, do que se premia ao que se acompanha:
 *  1. LEITURA NO PERÍODO (principal, com o pódio): livros, pontos de dificuldade e
 *     tempo somados apenas no intervalo escolhido (base do "melhor leitor da
 *     semana/mês/bimestre"). É a lista que o "Gerar certificados" usa (D7).
 *  2. CLASSIFICAÇÃO OFICIAL (nota 0–100 do ano letivo, só alunos aferidos;
 *     `components/DesempenhoDimensao`) — respeita turma/série e o turno global;
 *  3. COMPETIÇÃO POR TURNO (a mesma nota, dividida por `Turma.turno`, rótulos do
 *     backend) — abre no turno global quando ele existe.
 * As seções 2 e 3 são recolhíveis (fechadas ao abrir a aba), mas ficam montadas:
 * as consultas, os avisos e a lista de não aferidos continuam valendo.
 *
 * Os filtros (período, turma/série, turno) ficam juntos numa barra só, no topo.
 */
import { BookOpen, Trophy } from "lucide-react";
import { useMemo, useState } from "react";

import { CompeticaoLeituraTurno } from "../components/CompeticaoLeituraTurno";
import { DesempenhoDimensao } from "../components/DesempenhoDimensao";
import { FiltroTurmaSerie, type AlvoRanking } from "../components/FiltroTurmaSerie";
import { itensDoPodio, type ItemPodio } from "../components/PodioRanking";
import {
  AcoesRanking,
  BarraFiltrosRanking,
  CabecalhoCartao,
  CelulaAluno,
  DescricaoRanking,
  EsqueletoRanking,
  FaixaPodio,
  MostrarMais,
  PosicaoRanking,
  SecaoRanking,
  rotuloDoPeriodo,
  tabelaRanking as t,
} from "../components/RankingUi";
import { SeletorPeriodo, periodoParaQuery } from "../components/SeletorPeriodo";
import { SeloFrescorDaEscola } from "../components/SeloFrescor";
import { SeletorTurno } from "../components/SeletorTurno";
import { TabelaRolavel } from "../components/TabelaRolavel";
import { Card, Chip, Erro, PageHeader, Vazio } from "../components/ui";
import { useApp } from "../context/AppContext";
import { useApi } from "../hooks/useApi";
import { useJanela } from "../hooks/useJanela";
import { useCalendarioBimestres } from "../lib/calendarioBimestres";
import { nomeArquivoCsv, type TabelaCsv } from "../lib/csvRanking";
import { numero, tempoLeitura } from "../lib/formato";
import { bimestreDoPeriodo } from "../lib/tiposCertificados";
import { TURNO_SEM, TURNO_TODOS, aplicarTurno, rotuloTurno, turnoEfetivo } from "../lib/turnos";
import type { RankingLeituraItem, Turma } from "../lib/types";

export default function RankingLeitura({ embutido = false, alvoAcoes }: {
  embutido?: boolean;
  /** Espaço de ações do cabeçalho da tela Ranking (os botões vão para lá). */
  alvoAcoes?: HTMLElement | null;
} = {}) {
  const { escolaId, periodo, definirPeriodo, turno, definirTurno } = useApp();
  // Período TEMPORAL e TURNO vêm do contexto global (seguem o usuário entre as
  // abas). O Elefante traz o TOTAL acumulado por aluno; recortes por semana/mês
  // só têm dados quando há relatório individual datado.
  const [alvo, setAlvo] = useState<AlvoRanking>({});

  const { dados: turmas } = useApi<Turma[]>(
    escolaId ? `/escolas/${escolaId}/turmas` : null, { cacheMs: 60_000 });
  const turnoAtivo = turnoEfetivo(turno, turmas);
  // Calendário oficial do ano, do backend: sem ele a web só conhece 2026 (o número de
  // "Este bimestre" e o bimestre do lote de "Bimestre passado" sumiam de 2027 em diante).
  const calendario = useCalendarioBimestres(escolaId);

  // Recalcula a URL quando período/turma/série/turno mudam; o hook rebusca sozinho.
  const q = new URLSearchParams(periodoParaQuery(periodo));
  if (alvo.turma_id) q.set("turma_id", alvo.turma_id);
  else if (alvo.ano_escolar) q.set("ano_escolar", alvo.ano_escolar);
  aplicarTurno(q, turnoAtivo);
  const {
    dados: itens,
    erro,
    carregando,
    recarregar,
  } = useApi<RankingLeituraItem[]>(
    escolaId ? `/escolas/${escolaId}/ranking/leitura?${q}` : null,
  );
  const lista = useMemo(() => itens ?? [], [itens]);
  // Janelamento: em escolas grandes só as primeiras linhas entram no DOM.
  const { visiveis, restantes, mostrarMais } = useJanela(lista);

  const rotuloPeriodo = rotuloDoPeriodo(periodo, new Date(), calendario);
  const turmaEscolhida = alvo.turma_id ? turmas?.find((x) => String(x.id) === alvo.turma_id)?.nome : null;
  const recorte = [
    turmaEscolhida ?? (alvo.ano_escolar ? `${alvo.ano_escolar} (todas as turmas)` : null),
    turnoAtivo !== TURNO_TODOS ? (turnoAtivo === TURNO_SEM ? "turmas sem turno" : rotuloTurno(turnoAtivo)) : null,
  ].filter(Boolean).join(" · ");

  const csv: TabelaCsv | null = lista.length === 0 ? null : {
    nomeArquivo: nomeArquivoCsv(`ranking-leitura-${rotuloPeriodo}${recorte ? `-${recorte}` : ""}`),
    cabecalho: ["Posição", "Aluno", "Turma", "Livros", "Pontos", "Tempo de leitura (min)"],
    linhas: lista.map((item) => [
      item.posicao, item.nome, item.turma ?? "", item.livros, item.pontos, item.tempo_leitura_min,
    ]),
  };

  const acoes = (
    <AcoesRanking
      alvo={alvoAcoes}
      embutido={embutido}
      csv={csv}
      certificados={{
        alunos: lista.map((item) => ({
          aluno_id: item.aluno_id, nome: item.nome, turma: item.turma, posicao: item.posicao,
        })),
        modeloInicial: "elefante",
        contexto: `Ranking · Leitura no período (pontos) · ${rotuloPeriodo}${recorte ? ` · ${recorte}` : ""}`,
        // Lista de um bimestre: o bimestre impresso abre nele, não no de hoje.
        bimestreInicial: bimestreDoPeriodo(periodo.preset, new Date(), calendario),
      }}
    />
  );

  // Pódio: os pontos (o que ordena), com livros e tempo do MESMO período.
  const podio: ItemPodio[] = itensDoPodio(lista).map((item) => ({
    chave: item.aluno_id,
    posicao: item.posicao,
    nome: item.nome,
    turma: item.turma,
    avatar: item.aluno_id,
    destaque: { valor: numero(item.pontos), unidade: item.pontos === 1 ? "ponto" : "pontos" },
    metricas: [
      { rotulo: "livros", valor: numero(item.livros) },
      { rotulo: "tempo", valor: tempoLeitura(item.tempo_leitura_min) },
    ],
  }));

  return (
    <div>
      {embutido ? acoes : (
        <PageHeader
          titulo="Ranking de Leitura"
          descricao={<DescricaoRanking periodo={rotuloPeriodo} dimensoes={["leitura"]} />}
          acoes={acoes}
        />
      )}

      {/* Filtros que valem para a lista do período E para a classificação oficial
          (que não usa o período: é do ano letivo). */}
      <BarraFiltrosRanking>
        <SeletorPeriodo valor={periodo} onChange={definirPeriodo} />
        <FiltroTurmaSerie turmas={turmas ?? []} valor={alvo} onChange={setAlvo} />
        <SeletorTurno turmas={turmas ?? []} valor={turno} onChange={definirTurno} />
      </BarraFiltrosRanking>

      {/* DE QUANDO é o dado: o ranking usa o último retrato de cada aluno, e a
          coleta pode estar parada — o selo diz a data e avisa. */}
      <SeloFrescorDaEscola dimensoes={["leitura"]} />

      {/* 1. LEITURA NO PERÍODO (temporal, pontos brutos) — o bloco principal. */}
      <Card className="mb-5 overflow-hidden">
        <CabecalhoCartao
          icone={BookOpen}
          tom="violeta"
          titulo="Leitura no período"
          subtitulo={!carregando && !erro && lista.length > 0
            ? `${rotuloPeriodo} · ${numero(lista.length)} aluno(s) com leitura · ordem por pontos de dificuldade`
            : `${rotuloPeriodo} · ordem por pontos de dificuldade`}
          ajuda={<AjudaLeitura />}
        />
        {carregando ? (
          <EsqueletoRanking />
        ) : erro ? (
          <Erro titulo="Não foi possível carregar" descricao={erro.message} aoTentar={recarregar} />
        ) : lista.length === 0 ? (
          <Vazio icone={BookOpen} titulo="Nenhuma leitura no período"
                 descricao="Sincronize o Elefante Letrado (ou importe o relatório), ou escolha um período maior, como “Ano letivo”, para ver a leitura do ano inteiro." />
        ) : (
          <>
            <FaixaPodio itens={podio} rotulo="Pódio da leitura no período" />
            {/* Celular: os PONTOS (o que ordena) ficam presos à direita. */}
            <TabelaRolavel rotulo="Leitura no período: tabela completa">
              <table className={t.tabela}>
                <thead className={t.thead}>
                  <tr>
                    <th scope="col" className={t.th}>#</th>
                    <th scope="col" className={t.th}>Aluno</th>
                    <th scope="col" className={t.th}>Turma</th>
                    <th scope="col" className={t.thNum}>Livros</th>
                    <th scope="col" className={`${t.thNum} ${t.thPresa}`}>Pontos</th>
                    <th scope="col" className={t.thNum}>Tempo</th>
                  </tr>
                </thead>
                <tbody>
                  {visiveis.map((item) => (
                    <tr key={item.aluno_id} className={t.tr}>
                      <td className={t.td}><PosicaoRanking posicao={item.posicao} /></td>
                      <td className={t.td}>
                        <CelulaAluno nome={item.nome} href={`/alunos/${item.aluno_id}`} chave={item.aluno_id} />
                      </td>
                      <td className={t.tdCurto}>{item.turma ? <Chip>{item.turma}</Chip> : "—"}</td>
                      <td className={t.tdNum}>{numero(item.livros)}</td>
                      <td className={`${t.tdForte} ${t.tdPresa}`}>{numero(item.pontos)}</td>
                      <td className={`${t.tdNum} text-zinc-500 dark:text-zinc-400`}>{tempoLeitura(item.tempo_leitura_min)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TabelaRolavel>
            <MostrarMais restantes={restantes} aoMostrar={mostrarMais}
                         rotulo={`Mostrar mais ${numero(restantes)} aluno(s)`} />
          </>
        )}
      </Card>

      <div className="space-y-5">
        {/* 2. CLASSIFICAÇÃO OFICIAL: só aferidos, nota do ano, não aferidos ao lado. */}
        <DesempenhoDimensao dimensao="leitura" filtros={{ ...alvo, turno: turnoAtivo }} recolhivel />

        {/* 3. COMPETIÇÃO POR TURNO: nota 0–100 por turno (régua única da escola). */}
        <SecaoRanking
          titulo="Competição por turno"
          subtitulo="A mesma nota oficial, com os alunos de cada turno competindo entre si (1º ao 5º ano juntos)."
          icone={Trophy}
          tom="ambar"
        >
          {/* A competição NÃO recebe o filtro de turma/série da tela (é sempre o
              turno inteiro); sem este aviso, parece que o filtro foi ignorado. */}
          <p className="mb-3 text-xs text-zinc-500 dark:text-zinc-400">
            Sempre todas as turmas de cada turno — o filtro de turma e série acima não se aplica aqui.
          </p>
          <CompeticaoLeituraTurno />
        </SecaoRanking>
      </div>
    </div>
  );
}

/** "Como funciona" da leitura no período (texto recolhido por padrão). */
function AjudaLeitura() {
  return (
    <ul className="list-disc space-y-1.5 pl-5">
      <li>
        Melhor leitor da semana, do mês ou do bimestre: soma de livros, pontos de dificuldade e
        tempo de leitura só dentro do período escolhido, com os dados do Elefante Letrado.
      </li>
      <li>
        A ordem é por pontos de dificuldade; no empate, decidem os livros, depois o tempo e o
        nome. A posição vem pronta do sistema.
      </li>
      <li>
        Não é a classificação oficial do ano (a nota de 0 a 100), que fica logo abaixo, nem a
        competição por turno.
      </li>
      <li>
        O pódio mostra só quem está de fato em 1º, 2º e 3º. “Gerar certificados” usa esta lista,
        na ordem da tela, com a arte do Elefante Letrado.
      </li>
    </ul>
  );
}
