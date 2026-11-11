/** Ranking de Evolução (PRD §72) — independente do Ranking Geral. Respeita o
 *  período e o turno GLOBAIS (`?turno=`, que o endpoint já aceita).
 *
 *  Identidade visual v2: pódio dos 3 primeiros (a nota de evolução, com os ganhos
 *  reais do período), tabela com os ganhos em chips e a evolução em negrito. A
 *  ordem e a posição são as da API; nada é recalculado aqui. */
import { BookOpen, Calculator, CheckCircle2, Star, TrendingUp } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useMemo, useState } from "react";

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
import { useModulos } from "../hooks/useModulos";
import { useCalendarioBimestres } from "../lib/calendarioBimestres";
import { nomeArquivoCsv, type TabelaCsv } from "../lib/csvRanking";
import { nota, numero } from "../lib/formato";
import { bimestreDoPeriodo } from "../lib/tiposCertificados";
import { TURNO_SEM, TURNO_TODOS, aplicarTurno, rotuloTurno, turnoEfetivo } from "../lib/turnos";
import type { Dimensao, Turma } from "../lib/types";

interface ItemEvolucao {
  posicao: number;
  aluno_id: number;
  nome: string;
  turma: string;
  ano_escolar: string;
  nota_evolucao: number;
  ganhos: {
    atividades: number;
    estrelas: number;
    livros: number;
    tempo_leitura_min: number;
    acertos: number;
  };
}

/** Os ganhos exibidos (os mesmos de antes), com o tom da plataforma de cada um. */
const GANHOS: {
  chave: keyof ItemEvolucao["ganhos"];
  rotulo: string;
  /** Rótulo quando o ganho é exatamente 1 ("+1 livro", não "+1 livros"). */
  singular: string;
  icone: LucideIcon;
  tom: string;
}[] = [
  { chave: "atividades", rotulo: "atividades", singular: "atividade", icone: Calculator,
    tom: "bg-teal-50 text-teal-700 dark:bg-teal-500/15 dark:text-teal-300" },
  { chave: "livros", rotulo: "livros", singular: "livro", icone: BookOpen,
    tom: "bg-indigo-50 text-indigo-700 dark:bg-indigo-500/15 dark:text-indigo-300" },
  { chave: "estrelas", rotulo: "estrelas", singular: "estrela", icone: Star,
    tom: "bg-ouro-50 text-ouro-700 dark:bg-ouro-400/15 dark:text-ouro-300" },
  { chave: "acertos", rotulo: "acertos", singular: "acerto", icone: CheckCircle2,
    tom: "bg-emerald-50 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300" },
];

/** Ganhos positivos do aluno, com o rótulo já no número certo (singular só no 1). */
const ganhosDe = (item: ItemEvolucao) =>
  GANHOS.filter((g) => (item.ganhos?.[g.chave] ?? 0) > 0).map((g) => {
    const valor = item.ganhos[g.chave];
    return { ...g, valor, rotulo: valor === 1 ? g.singular : g.rotulo };
  });

export default function RankingEvolucao({ embutido = false, alvoAcoes }: {
  embutido?: boolean;
  /** Espaço de ações do cabeçalho da tela Ranking (os botões vão para lá). */
  alvoAcoes?: HTMLElement | null;
} = {}) {
  const { escolaId, periodo, definirPeriodo, turno, definirTurno } = useApp();
  const { tem } = useModulos();
  const [alvo, setAlvo] = useState<AlvoRanking>({});

  // Turmas alimentam apenas os filtros; na falha caímos para lista vazia.
  const { dados: turmasDados } = useApi<Turma[]>(
    escolaId ? `/escolas/${escolaId}/turmas` : null, { cacheMs: 60_000 });
  const turmas = turmasDados ?? [];
  const turnoAtivo = turnoEfetivo(turno, turmasDados);
  // Calendário oficial do ano, do backend: sem ele a web só conhece 2026 (o número de
  // "Este bimestre" e o bimestre do lote de "Bimestre passado" sumiam de 2027 em diante).
  const calendario = useCalendarioBimestres(escolaId);

  const parametros = new URLSearchParams(periodoParaQuery(periodo));
  if (alvo.turma_id) parametros.set("turma_id", alvo.turma_id);
  if (alvo.ano_escolar) parametros.set("ano_escolar", alvo.ano_escolar);
  aplicarTurno(parametros, turnoAtivo);
  const { dados: itens, erro, carregando, recarregar } = useApi<ItemEvolucao[]>(
    escolaId ? `/escolas/${escolaId}/ranking-evolucao?${parametros}` : null,
  );
  const lista = useMemo(() => itens ?? [], [itens]);
  // Janelamento: em escolas grandes só as primeiras linhas entram no DOM.
  const { visiveis, restantes, mostrarMais } = useJanela(lista);

  const rotuloPeriodo = rotuloDoPeriodo(periodo, new Date(), calendario);
  const turmaEscolhida = alvo.turma_id ? turmas.find((x) => String(x.id) === alvo.turma_id)?.nome : null;
  const recorte = [
    turmaEscolhida ?? (alvo.ano_escolar ? `${alvo.ano_escolar} (todas as turmas)` : null),
    turnoAtivo !== TURNO_TODOS ? (turnoAtivo === TURNO_SEM ? "turmas sem turno" : rotuloTurno(turnoAtivo)) : null,
  ].filter(Boolean).join(" · ");

  const csv: TabelaCsv | null = lista.length === 0 ? null : {
    nomeArquivo: nomeArquivoCsv(`ranking-evolucao-${rotuloPeriodo}${recorte ? `-${recorte}` : ""}`),
    cabecalho: ["Posição", "Aluno", "Turma", "Atividades (+)", "Livros (+)", "Estrelas (+)", "Acertos (+)", "Evolução"],
    linhas: lista.map((item) => [
      item.posicao, item.nome, item.turma ?? "",
      item.ganhos?.atividades ?? 0, item.ganhos?.livros ?? 0, item.ganhos?.estrelas ?? 0, item.ganhos?.acertos ?? 0,
      nota(item.nota_evolucao),
    ]),
  };

  // Só sobe ao pódio e recebe certificado de evolução quem CRESCEU (> 0), a regra do
  // telão e das Premiações: num período em que ninguém cresceu, os primeiros empatam
  // em 0,0 e a ordem entre eles é só o desempate alfabético — não há o que celebrar.
  // A API ordena pela evolução (maior primeiro), então quem cresceu é o começo da
  // lista, na mesma ordem e com a mesma posição. A tabela continua com todos.
  const cresceram = lista.filter((item) => item.nota_evolucao > 0);

  const acoes = (
    <AcoesRanking
      alvo={alvoAcoes}
      embutido={embutido}
      csv={csv}
      certificados={{
        alunos: cresceram.map((item) => ({
          aluno_id: item.aluno_id, nome: item.nome, turma: item.turma, posicao: item.posicao,
        })),
        // Evolução não tem arte própria: abre no Geral, e o modal deixa trocar.
        modeloInicial: null,
        contexto: `Ranking de Evolução · quem cresceu · ${rotuloPeriodo}${recorte ? ` · ${recorte}` : ""}`,
        // A tabela mostra todos, com 0,0 de quem não cresceu: "Não há alunos nesta lista"
        // seria falso ao lado dela (DEC-20).
        semAlunos: "Ninguém cresceu no período: não há certificado de evolução a gerar.",
        // Evolução dentro de um bimestre: trocando para uma arte de plataforma, o
        // bimestre impresso abre nele, não no de hoje.
        bimestreInicial: bimestreDoPeriodo(periodo.preset, new Date(), calendario),
      }}
    />
  );

  // Pódio: a nota de evolução (o que ordena), com os ganhos reais do período, só de
  // quem cresceu (ver `cresceram` acima).
  const podio: ItemPodio[] = itensDoPodio(cresceram).map((item) => ({
    chave: item.aluno_id,
    posicao: item.posicao,
    nome: item.nome,
    turma: item.turma,
    avatar: item.aluno_id,
    destaque: { valor: nota(item.nota_evolucao), unidade: "de evolução" },
    metricas: ganhosDe(item).slice(0, 3).map((g) => ({ rotulo: g.rotulo, valor: `+${numero(g.valor)}` })),
  }));

  const dimensoes = (["leitura", "matematica"] as Dimensao[]).filter((d) => tem(d));

  return (
    <div>
      {embutido ? acoes : (
        <PageHeader
          titulo="Ranking de Evolução"
          descricao={<DescricaoRanking periodo={rotuloPeriodo} dimensoes={dimensoes} />}
          acoes={acoes}
        />
      )}

      <BarraFiltrosRanking>
        <SeletorPeriodo valor={periodo} onChange={definirPeriodo} />
        <FiltroTurmaSerie turmas={turmas} valor={alvo} onChange={setAlvo} />
        <SeletorTurno turmas={turmas} valor={turno} onChange={definirTurno} />
      </BarraFiltrosRanking>

      {/* A evolução é medida entre retratos: se a última coleta é antiga, o
          crescimento "do período" pode simplesmente não ter sido coletado. */}
      <SeloFrescorDaEscola dimensoes={["leitura", "matematica"]} />

      {/* No ano inteiro não há acumulado anterior a descontar (serviço evolucao._janela):
          o ganho é o total do ano e o pódio coincide com o do Ranking Geral. */}
      {periodo.preset === "ano_letivo" && (
        <p
          role="note"
          className="mb-4 rounded-2xl border border-indigo-100 bg-indigo-50/40 p-3 text-sm text-indigo-900 dark:border-indigo-500/20 dark:bg-indigo-500/5 dark:text-indigo-200"
        >
          No ano letivo inteiro todos os alunos partem do zero, por isso esta lista fica igual à do
          Ranking Geral. Para ver quem mais cresceu, escolha um bimestre ou um mês.
        </p>
      )}

      <Card className="overflow-hidden">
        <CabecalhoCartao
          icone={TrendingUp}
          tom="verde"
          titulo="Quem mais cresceu no período"
          subtitulo={`${rotuloPeriodo} · independente da nota acumulada`}
          ajuda={<AjudaEvolucao />}
        />
        {carregando ? (
          <EsqueletoRanking />
        ) : erro ? (
          <Erro titulo="Não foi possível carregar" descricao={erro.message} aoTentar={recarregar} />
        ) : lista.length === 0 ? (
          <Vazio icone={TrendingUp} titulo="Sem dados no período" descricao="Importe novos relatórios para medir a evolução." />
        ) : (
          <>
            <FaixaPodio itens={podio} rotulo="Pódio da evolução no período" />
            {/* Celular: a EVOLUÇÃO (o que ordena) fica presa à direita. */}
            <TabelaRolavel rotulo="Ranking de Evolução: tabela completa">
              <table className={t.tabela}>
                <thead className={t.thead}>
                  <tr>
                    <th scope="col" className={t.th}>#</th>
                    <th scope="col" className={t.th}>Aluno</th>
                    <th scope="col" className={t.th}>Turma</th>
                    <th scope="col" className={t.th}>Ganhos no período</th>
                    <th scope="col" className={`${t.thNum} ${t.thPresa}`}>Evolução</th>
                  </tr>
                </thead>
                <tbody>
                  {visiveis.map((item) => {
                    const ganhos = ganhosDe(item);
                    return (
                      <tr key={item.aluno_id} className={t.tr}>
                        <td className={t.td}><PosicaoRanking posicao={item.posicao} /></td>
                        <td className={t.td}>
                          <CelulaAluno nome={item.nome} href={`/alunos/${item.aluno_id}/evolucao`} chave={item.aluno_id} />
                        </td>
                        <td className={t.tdCurto}>{item.turma ? <Chip>{item.turma}</Chip> : "—"}</td>
                        <td className={t.td}>
                          {ganhos.length === 0 ? (
                            <span className="text-xs text-zinc-500 dark:text-zinc-400">sem ganhos</span>
                          ) : (
                            <span className="flex flex-wrap gap-1.5">
                              {ganhos.map((g) => (
                                <span key={g.chave} className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold ${g.tom}`}>
                                  <g.icone size={12} aria-hidden /> +{numero(g.valor)} {g.rotulo}
                                </span>
                              ))}
                            </span>
                          )}
                        </td>
                        <td className={`${t.tdForte} ${t.tdPresa}`}>{nota(item.nota_evolucao)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </TabelaRolavel>
            <MostrarMais restantes={restantes} aoMostrar={mostrarMais}
                         rotulo={`Mostrar mais ${numero(restantes)} aluno(s)`} />
          </>
        )}
      </Card>
    </div>
  );
}

/** "Como funciona" da Evolução (texto recolhido por padrão). */
function AjudaEvolucao() {
  return (
    <ul className="list-disc space-y-1.5 pl-5">
      <li>
        Quem mais cresceu no período escolhido, independente da nota acumulada do ano. Usa os
        mesmos pesos configuráveis da pontuação, aplicados aos ganhos do período.
      </li>
      <li>
        Os ganhos são medidos entre as coletas das plataformas: se a última coleta é antiga, o
        crescimento do período pode ainda não ter chegado (veja a data no selo).
      </li>
      <li>
        O nome do aluno abre a evolução dele. Em “Gerar certificados” entram só os alunos que
        cresceram no período, como no pódio. O modelo começa no Geral (que imprime a posição do
        Ranking Geral, não a desta lista); dá para trocar pela arte de uma plataforma.
      </li>
    </ul>
  );
}
