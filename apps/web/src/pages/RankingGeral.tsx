/**
 * Ranking Geral — a ORDEM ÚNICA da escola: "Geral (Leitura + Matemática)", a
 * classificação acumulada do ano letivo pela nota geral. Nenhum cálculo muda
 * aqui: a lista vem carimbada de `/ranking` (posições e denominador da API).
 *
 * O desempenho POR MATÉRIA (classificação oficial de Leitura e de Matemática,
 * com o corte "ausência não é zero" e a lista de não aferidos) vive em
 * `components/DesempenhoDimensao`, nas abas Leitura e Matemática.
 *
 * Esta ordem única segue como padrão porque aposentá-la muda quem sobe ao pódio
 * em toda escola mista — premiações nº 7/8/11 da spec, DECISÃO DE PRODUTO do
 * dono.
 *
 * Identidade visual v2 (referência "Ranking"): filtros numa barra-cartão, pódio
 * dos 3 primeiros (`PodioRanking`, só com as posições 1–3 de verdade, sem link) e a
 * tabela com avatar, turma em chip e a nota geral em negrito. Sem coluna de
 * variação de posição (D8: não há histórico de posição no sistema). As ações
 * (Baixar cartaz, Exportar lista, Gerar certificados) vão para o cabeçalho da tela
 * Ranking (`alvoAcoes`); avulsa, ficam no próprio cabeçalho.
 *
 * PERÍODO: o Ranking Geral é sempre a classificação ACUMULADA do ano letivo.
 * Com qualquer outro período global escolhido, a tela avisa e oferece a aba
 * Evolução (a classificação por período), em vez de repetir aqui a mesma
 * tabela daquela aba. O seletor de período fica na tela porque é global (segue
 * o usuário para Leitura, Matemática, Evolução e Premiações).
 *
 * TURNO: o turno global filtra a lista (`?turno=`); com turno, a API renumera
 * as posições dentro do recorte e carimba o denominador do conjunto filtrado.
 *
 * CONTAGEM honesta no cabeçalho da tabela (a posição exibida precisa bater com
 * o número ao lado):
 *   - sem filtro           → "N aluno(s) na classificação";
 *   - com turno            → "N aluno(s) no turno X" (posições do turno);
 *   - turma/série sem turno → "N aluno(s) neste filtro · posição na escola
 *     inteira" (a gestão vê a posição carimbada da escola; o professor já recebe
 *     a lista renumerada nas turmas dele, então o sufixo não se aplica).
 */
import { Download, Info, Trophy, TrendingUp } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

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
  tabelaRanking as t,
} from "../components/RankingUi";
import { SeletorPeriodo } from "../components/SeletorPeriodo";
import { SeloFrescorDaEscola } from "../components/SeloFrescor";
import { SeletorTurno } from "../components/SeletorTurno";
import { TabelaRolavel } from "../components/TabelaRolavel";
import { Botao, Card, Chip, Erro, Mensagem, PageHeader, Vazio } from "../components/ui";
import { useApp } from "../context/AppContext";
import { useApi } from "../hooks/useApi";
import { useJanela } from "../hooks/useJanela";
import { useModulos } from "../hooks/useModulos";
import { usePerfil } from "../hooks/usePerfil";
import { apiDownload } from "../lib/api";
import { nomeArquivoCsv, type TabelaCsv } from "../lib/csvRanking";
import { nota, notaDaMateria, numero } from "../lib/formato";
import { TURNO_SEM, TURNO_TODOS, aplicarTurno, rotuloTurno, turnoEfetivo } from "../lib/turnos";
import type { Dimensao, RankingItem, Turma } from "../lib/types";

export default function RankingGeral({ embutido = false, alvoAcoes }: {
  embutido?: boolean;
  /** Espaço de ações do cabeçalho da tela Ranking (os botões vão para lá). */
  alvoAcoes?: HTMLElement | null;
} = {}) {
  const { escolaId, periodo, definirPeriodo, turno, definirTurno } = useApp();
  const [params, setParams] = useSearchParams();
  const [alvo, setAlvo] = useState<AlvoRanking>({});
  const [baixandoCartaz, setBaixandoCartaz] = useState(false);
  const [erroCartaz, setErroCartaz] = useState("");

  // O cartaz (pôster) é documento de vitrine — só gestão (admin/coordenador/rede).
  const { gestor } = usePerfil();
  const { tem } = useModulos();

  // Período ≠ ano letivo: a classificação por período é a aba Evolução.
  const porPeriodo = periodo.preset !== "ano_letivo";

  // Cache curto: a lista de turmas do dropdown de filtro muda raramente e é
  // invalidada em Turmas.tsx ao criar/editar/excluir (limparCacheApi).
  const { dados: turmas } = useApi<Turma[]>(
    escolaId ? `/escolas/${escolaId}/turmas` : null, { cacheMs: 60_000 });
  // Turno persistido que não existe nesta escola conta como "todos" na
  // consulta (sem sobrescrever a escolha guardada).
  const turnoAtivo = turnoEfetivo(turno, turmas);

  // Filtros: uma turma específica OU uma série consolidada (todas as turmas do
  // ano) — nunca os dois ao mesmo tempo — e o turno global.
  const parametros = new URLSearchParams();
  if (alvo.turma_id) parametros.set("turma_id", alvo.turma_id);
  if (alvo.ano_escolar) parametros.set("ano_escolar", alvo.ano_escolar);
  aplicarTurno(parametros, turnoAtivo);

  const { dados: itens, erro, carregando, recarregar } = useApi<RankingItem[]>(
    escolaId ? `/escolas/${escolaId}/ranking?${parametros}` : null,
  );
  const lista = useMemo(() => itens ?? [], [itens]);
  // Janelamento: em escolas grandes só as primeiras linhas entram no DOM.
  const { visiveis, restantes, mostrarMais } = useJanela(lista);

  const comTurmaOuSerie = Boolean(alvo.turma_id || alvo.ano_escolar);
  const comTurno = turnoAtivo !== TURNO_TODOS;
  // Denominador carimbado pela API (conjunto filtrado quando há recorte) ou,
  // na falta dele, o tamanho da lista.
  const totalDaApi = numero(lista[0]?.n_aferidos ?? lista.length);
  let contagem: string;
  if (comTurno) {
    // Posições renumeradas pela API dentro do turno (e da turma/série, se houver).
    // "Sem turno" não é nome de turno: vira "em turmas sem turno".
    const recorteTurno = turnoAtivo === TURNO_SEM
      ? "em turmas sem turno" : `no turno ${rotuloTurno(turnoAtivo)}`;
    contagem = comTurmaOuSerie
      ? `${totalDaApi} aluno(s) neste filtro, ${recorteTurno}`
      : `${totalDaApi} aluno(s) ${recorteTurno}`;
  } else if (comTurmaOuSerie) {
    // Sem turno, a gestão recebe a posição carimbada da ESCOLA: o número ao lado
    // é só quantos alunos o filtro mostra, e a tela diz isso.
    contagem = gestor
      ? `${numero(lista.length)} aluno(s) neste filtro · posição na escola inteira`
      : `${numero(lista.length)} aluno(s) neste filtro`;
  } else {
    contagem = `${totalDaApi} aluno(s) na classificação`;
  }

  // O cartaz é sempre da escola inteira; ao mudar período/filtro, um erro antigo
  // do cartaz perde o contexto — limpa para não ficar pendurado na tela.
  useEffect(() => { setErroCartaz(""); }, [periodo, alvo, turnoAtivo]);

  // Troca para a aba Evolução mantendo os demais parâmetros da URL (a tela
  // vive embutida em Rankings.tsx, que deriva a aba de `?ver=`).
  function irParaEvolucao() {
    const prox = new URLSearchParams(params);
    prox.set("ver", "evolucao");
    setParams(prox);
  }

  // Baixa o cartaz do Ranking Geral (PDF de vitrine, com TODOS os alunos).
  async function baixarCartaz() {
    if (!escolaId) return;
    setBaixandoCartaz(true);
    setErroCartaz("");
    try {
      await apiDownload(`/escolas/${escolaId}/ranking/cartaz`);
    } catch (excecao) {
      setErroCartaz(excecao instanceof Error ? excecao.message : "Não foi possível gerar o cartaz.");
    } finally {
      setBaixandoCartaz(false);
    }
  }

  // Recorte em palavras (para o CSV e o contexto do lote de certificados).
  const turmaEscolhida = alvo.turma_id ? turmas?.find((x) => String(x.id) === alvo.turma_id)?.nome : null;
  const recorte = [
    turmaEscolhida ?? (alvo.ano_escolar ? `${alvo.ano_escolar} (todas as turmas)` : null),
    comTurno ? (turnoAtivo === TURNO_SEM ? "turmas sem turno" : rotuloTurno(turnoAtivo)) : null,
  ].filter(Boolean).join(" · ");

  const csv: TabelaCsv | null = lista.length === 0 ? null : {
    nomeArquivo: nomeArquivoCsv(`ranking-geral${recorte ? `-${recorte}` : ""}`),
    cabecalho: ["Posição", "Aluno", "Turma", "Matemática", "Leitura", "Geral"],
    linhas: lista.map((item) => [
      item.posicao,
      item.nome,
      item.turma ?? "",
      notaDaMateria(item.nota_matific, item.aferido_matematica),
      notaDaMateria(item.nota_elefante, item.aferido_leitura),
      nota(item.nota_geral),
    ]),
  };

  const cartaz = gestor && (
    <Botao
      variante="secundario"
      onClick={baixarCartaz}
      // O cartaz é sempre da escola inteira (classificação do ano); não
      // depende dos filtros de turma/série/turno. Só desabilita por
      // escola vazia quando NENHUM filtro está aplicado.
      disabled={baixandoCartaz
        || (!comTurmaOuSerie && !comTurno && lista.length === 0)}
      title="Gera um pôster em PDF com todos os alunos da escola (não usa os filtros de turma, série ou turno)"
    >
      <Download size={16} aria-hidden /> {baixandoCartaz ? "Gerando cartaz…" : "Baixar cartaz"}
    </Botao>
  );

  const acoes = (
    <AcoesRanking
      alvo={alvoAcoes}
      embutido={embutido}
      antes={cartaz || undefined}
      csv={csv}
      certificados={{
        alunos: lista.map((item) => ({
          aluno_id: item.aluno_id, nome: item.nome, turma: item.turma, posicao: item.posicao,
        })),
        modeloInicial: null,
        contexto: `Ranking Geral (Leitura + Matemática) · ano letivo${recorte ? ` · ${recorte}` : ""}`,
      }}
    />
  );

  // Pódio: só as posições 1–3 de verdade (com filtro de turma, a gestão recebe a
  // posição da escola inteira e pode não haver pódio no recorte).
  const podio: ItemPodio[] = itensDoPodio(lista).map((item) => ({
    chave: item.aluno_id,
    posicao: item.posicao,
    nome: item.nome,
    turma: item.turma,
    avatar: item.aluno_id,
    destaque: { valor: nota(item.nota_geral), unidade: "nota geral" },
    metricas: [
      ...(tem("leitura") ? [{ rotulo: "leitura", valor: notaDaMateria(item.nota_elefante, item.aferido_leitura) }] : []),
      ...(tem("matematica")
        ? [{ rotulo: "matemática", valor: notaDaMateria(item.nota_matific, item.aferido_matematica) }]
        : []),
    ],
  }));

  const dimensoes = (["leitura", "matematica"] as Dimensao[]).filter((d) => tem(d));

  return (
    <div>
      {embutido ? acoes : (
        <PageHeader
          titulo="Ranking Geral"
          descricao={<DescricaoRanking periodo="Ano letivo · classificação acumulada" dimensoes={dimensoes} />}
          acoes={acoes}
        />
      )}

      <BarraFiltrosRanking>
        <SeletorPeriodo valor={periodo} onChange={definirPeriodo} />
        <FiltroTurmaSerie turmas={turmas ?? []} valor={alvo} onChange={setAlvo} />
        <SeletorTurno turmas={turmas ?? []} valor={turno} onChange={definirTurno} />
      </BarraFiltrosRanking>

      {/* DE QUANDO é o dado das duas plataformas (o motor usa o último retrato
          de cada aluno, sem olhar a idade): selo com a data e aviso se velho. */}
      <SeloFrescorDaEscola dimensoes={["leitura", "matematica"]} />

      {erroCartaz && <div className="mb-4"><Mensagem tipo="erro">{erroCartaz}</Mensagem></div>}

      {/* Período ≠ ano letivo: NÃO repetimos aqui a tabela da aba Evolução
          (era a mesma consulta, duplicada). O aviso aponta para lá. */}
      {porPeriodo && (
        <div
          role="status"
          className="mb-4 flex flex-wrap items-center gap-3 rounded-2xl border border-ouro-200 bg-ouro-50 px-4 py-3 text-sm text-zinc-800 dark:border-ouro-400/30 dark:bg-ouro-400/10 dark:text-zinc-100"
        >
          <Info size={18} aria-hidden className="shrink-0 text-ouro-700 dark:text-ouro-300" />
          <span className="min-w-0 flex-1">
            O Ranking Geral é a classificação acumulada do ano letivo.
            A classificação por período fica na aba Evolução.
          </span>
          <Botao variante="secundario" tamanho="sm" onClick={irParaEvolucao}>
            <TrendingUp size={15} aria-hidden /> Ver a aba Evolução
          </Botao>
        </div>
      )}

      <Card className="overflow-hidden">
        {/* Nome da ordem + contagem coerente com a posição exibida (ver
            "CONTAGEM honesta" no topo do arquivo). */}
        <CabecalhoCartao
          icone={Trophy}
          tom="ambar"
          titulo="Classificação do ano letivo"
          subtitulo={!carregando && !erro && lista.length > 0
            ? <>Geral (Leitura + Matemática) · {contagem}</>
            : "Geral (Leitura + Matemática)"}
          ajuda={<AjudaGeral />}
        />
        {carregando ? (
          <EsqueletoRanking />
        ) : erro ? (
          <Erro titulo="Não foi possível carregar" descricao={erro.message} aoTentar={recarregar} />
        ) : lista.length === 0 ? (
          <Vazio
            icone={Trophy}
            titulo="Nenhuma nota calculada ainda"
            descricao="Importe dados das plataformas para gerar o ranking." />
        ) : (
          <>
            <FaixaPodio itens={podio} />
            {/* Celular: a nota GERAL (a que ordena) fica presa à direita — posição,
                aluno e nota em toda linha sem rolar; turma e matérias a um deslize. */}
            <TabelaRolavel rotulo="Ranking Geral: tabela completa">
              <table className={t.tabela}>
                <thead className={t.thead}>
                  <tr>
                    <th scope="col" className={t.th}>#</th>
                    <th scope="col" className={t.th}>Aluno</th>
                    <th scope="col" className={t.th}>Turma</th>
                    <th scope="col" className={t.thNum}>Matemática</th>
                    <th scope="col" className={t.thNum}>Leitura</th>
                    <th scope="col" className={`${t.thNum} ${t.thPresa}`}>Geral</th>
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
                      {/* Ordem única: a lista não corta por aferido, então
                          `nota_matific`/`nota_elefante` chegam 0,0 tanto para quem
                          não tem snapshot da plataforma quanto para quem tem e não
                          produziu. O item carimba `aferido_*` (existência do
                          snapshot), e `notaDaMateria` separa os dois: "—" no
                          primeiro caso, "0,0" no segundo. */}
                      <td className={t.tdNum}>
                        {notaDaMateria(item.nota_matific, item.aferido_matematica)}
                      </td>
                      <td className={t.tdNum}>
                        {notaDaMateria(item.nota_elefante, item.aferido_leitura)}
                      </td>
                      <td className={`${t.tdForte} ${t.tdPresa}`}>{nota(item.nota_geral)}</td>
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
    </div>
  );
}

/** "Como funciona" do Ranking Geral (texto explicativo, recolhido por padrão). */
function AjudaGeral() {
  return (
    <ul className="list-disc space-y-1.5 pl-5">
      <li>
        As abas no alto escolhem o que classificar (alunos, turmas ou escolas, conforme o seu
        perfil) e de qual plataforma vem o dado. Os filtros de período, turma, série e turno
        ficam na barra de cada ranking.
      </li>
      <li>
        Esta é a ordem única do ano letivo pela nota geral (0 a 100), que junta Leitura e
        Matemática. O período escolhido não muda esta lista; o crescimento no período fica na
        aba Evolução.
      </li>
      <li>
        Com um turno escolhido, as posições são recontadas dentro do turno. Com turma ou série
        e sem turno, a coordenação vê a posição da escola toda (por isso pode aparecer 7º, 12º…)
        e o pódio só aparece quando o 1º lugar está no recorte.
      </li>
      <li>
        “—” quer dizer que o aluno não tem dado daquela plataforma; “0,0” é um zero de verdade
        (ele usa a plataforma e ainda não produziu).
      </li>
      <li>
        O cartaz em PDF é sempre da escola toda. O “Exportar lista (CSV)” leva exatamente a
        lista desta tela, com os filtros aplicados.
      </li>
      <li>
        Em “Gerar certificados”, entram os primeiros desta lista, na ordem da tela. Quem não
        puder receber aparece com o motivo, e ninguém entra no lugar.
      </li>
    </ul>
  );
}
