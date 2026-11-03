/**
 * Ranking de Matemática (Matific) — um bloco principal e uma seção secundária:
 *  1. PLACAR MATIFIC (principal, com o pódio): estrelas e atividades no período.
 *     É a lista que o "Gerar certificados" usa (D7).
 *     • ANO LETIVO → lê o BANCO LOCAL (mantido pela sincronização diária).
 *       Rápido e não depende do Matific estar no ar. O turno vai na query.
 *     • Sub-períodos (Hoje, Ontem, Esta/Semana passada, Mês/Mês passado,
 *       Bimestre/Bimestre passado, Personalizado) → CONSULTA O MATIFIC AO VIVO
 *       (API interna por HTTP; navegador só para autenticar). Mostra os mesmos
 *       alunos, estrelas e atividades do site. Resultado tem cache curto;
 *       "Atualizar" força a busca. O turno é aplicado NO CLIENTE (nome da turma
 *       → turno, pelo cadastro de turmas); turma cujo NOME existe em mais de um
 *       turno fica fora do recorte, com aviso na tela.
 *  2. CLASSIFICAÇÃO OFICIAL (nota 0–100 do ano letivo, só alunos aferidos;
 *     `components/DesempenhoDimensao`) — respeita turma/série e o turno global.
 *     Recolhível (fechada ao abrir a aba), mas montada.
 *
 * Nada é pré-carregado: a consulta ao vivo só sai com esta aba aberta (ela pode
 * fazer o robô refazer o login no Matific, ~1 min).
 */
import { Calculator, Database, Radio, RefreshCw, Star, Users } from "lucide-react";
import { useMemo, useState } from "react";

import { DesempenhoDimensao, type FiltrosDimensao } from "../components/DesempenhoDimensao";
import { itensDoPodio, type ItemPodio } from "../components/PodioRanking";
import {
  AcoesRanking,
  BarraFiltrosRanking,
  CabecalhoCartao,
  CelulaAluno,
  DescricaoRanking,
  EsqueletoRanking,
  FaixaPodio,
  PosicaoRanking,
  rotuloDoPeriodo,
  tabelaRanking as t,
} from "../components/RankingUi";
import { SeletorPeriodo, periodoParaQuery, type Periodo } from "../components/SeletorPeriodo";
import { MolduraPilula, estiloSelectPilula } from "../components/SeletorPilula";
import { SeloFrescorDaEscola } from "../components/SeloFrescor";
import { SeletorTurno } from "../components/SeletorTurno";
import { TabelaRolavel } from "../components/TabelaRolavel";
import { BotaoIcone, Card, Carregando, Chip, Erro, PageHeader, Vazio } from "../components/ui";
import { useApp } from "../context/AppContext";
import { useApi } from "../hooks/useApi";
import { nomeArquivoCsv, type TabelaCsv } from "../lib/csvRanking";
import { dataHora, numero } from "../lib/formato";
import { bimestreDoPeriodo } from "../lib/tiposCertificados";
import { TURNO_SEM, TURNO_TODOS, chaveTurno, rotuloTurno, turnoEfetivo, turnoParaQuery } from "../lib/turnos";
import type { Turma } from "../lib/types";

type PlacarItem = {
  posicao: number;
  nome: string;
  turma: string | null;
  serie?: string | null;
  estrelas: number;
  atividades: number;
  pontuacao_media: number;
  aluno_id: number | null;
};
type PlacarAoVivo = {
  periodo: string;
  atualizado_em: string;
  total: number;
  itens: PlacarItem[];
};

const media = (v: number) => v.toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export default function RankingMatematica({ embutido = false, alvoAcoes }: {
  embutido?: boolean;
  /** Espaço de ações do cabeçalho da tela Ranking (os botões vão para lá). */
  alvoAcoes?: HTMLElement | null;
} = {}) {
  const { escolaId, periodo, definirPeriodo, turno, definirTurno } = useApp();
  // Alvo do filtro: "" (todas), "turma:<nome>" (uma turma) ou "serie:<ano_escolar>"
  // (série consolidada). O placar vem do Matific AO VIVO e é filtrado no cliente,
  // então guardamos o NOME da turma (não um id) — igual às linhas retornadas.
  const [alvo, setAlvo] = useState("");
  const [forcarTick, setForcarTick] = useState(0);

  // Turmas da BASE: mapeiam turma → série (o placar ao vivo traz a série crua
  // do Matific, ex. "3"; a base tem o rótulo bonito, ex. "3º Ano"), turma →
  // turno (filtro global no placar ao vivo) e turma → id (classificação oficial).
  const { dados: turmasBase } = useApi<Turma[]>(
    escolaId ? `/escolas/${escolaId}/turmas` : null, { cacheMs: 60_000 });
  const turnoAtivo = turnoEfetivo(turno, turmasBase);

  const isAno = periodo.preset === "ano_letivo";
  // Personalizado só busca com as duas datas — evita disparar login pela metade.
  const periodoCompleto =
    periodo.preset !== "personalizado" || Boolean(periodo.inicio && periodo.fim);

  const q = periodoParaQuery(periodo);
  // Trocar de período zera o "forçar" NA MESMA atualização (sem efeito atrasado
  // que dispararia uma busca forcada indevida do período novo).
  const trocarPeriodo = (p: Periodo) => {
    setForcarTick(0);
    definirPeriodo(p);   // período é global (segue o usuário entre as abas)
  };

  // ANO LETIVO: banco local (sincronização diária), turno na query. Sub-períodos:
  // Matific ao vivo (turno aplicado no cliente, abaixo).
  const forcarQS = forcarTick > 0 ? `&forcar=true&r=${forcarTick}` : "";
  const turnoQS = turnoParaQuery(turnoAtivo);
  const local = useApi<PlacarItem[]>(
    escolaId && isAno
      ? `/escolas/${escolaId}/ranking/matematica?periodo=ano_letivo${turnoQS ? `&${turnoQS}` : ""}`
      : null,
  );
  const live = useApi<PlacarAoVivo>(
    escolaId && !isAno && periodoCompleto
      ? `/escolas/${escolaId}/sync/matific/placar-ao-vivo?${q}${forcarQS}`
      : null,
    { timeoutMs: 180_000, tentativas: 0 },
  );

  const carregando = isAno ? local.carregando : live.carregando;
  const erro = isAno ? local.erro : live.erro;
  const atualizar = () => (isAno ? local.recarregar() : setForcarTick((t) => t + 1));
  // "Tentar de novo" após uma falha: a mesma consulta (sem forçar novo login).
  const tentarDeNovo = () => (isAno ? local.recarregar() : live.recarregar());

  // Nome da turma → série / turno / id (rótulos da base). Best-effort: turma sem
  // correspondência na base não entra em nenhuma série nem em nenhum turno
  // (segue visível em "Todas"/"Todos os turnos").
  const turmaDaBase = useMemo(() => {
    const mapa = new Map<string, Turma>();
    (turmasBase ?? []).forEach((t) => mapa.set(t.nome, t));
    return mapa;
  }, [turmasBase]);

  // Nome da turma → turnos em que esse NOME existe no cadastro. O placar ao
  // vivo só traz o nome: "3º Ano A" da manhã e "3º Ano A" da tarde chegam
  // iguais, então um nome em mais de um turno é AMBÍGUO para o filtro de turno.
  const turnosPorNome = useMemo(() => {
    const mapa = new Map<string, Set<string>>();
    (turmasBase ?? []).forEach((t) => {
      const turnos = mapa.get(t.nome) ?? new Set<string>();
      turnos.add(chaveTurno(t.turno));
      mapa.set(t.nome, turnos);
    });
    return mapa;
  }, [turmasBase]);

  // TURNO no placar AO VIVO: filtrado no cliente (o Matific não conhece turno).
  // No ano letivo o backend já filtrou pela query. Aluno de turma com nome
  // ambíguo fica FORA do recorte (não dá para saber o turno dele) e é contado
  // para a tela avisar, em vez de ser encaixado no turno errado.
  const { itens, foraPorNomeRepetido } = useMemo(() => {
    const brutos: PlacarItem[] = isAno ? (local.dados ?? []) : (live.dados?.itens ?? []);
    if (isAno || turnoAtivo === TURNO_TODOS) return { itens: brutos, foraPorNomeRepetido: 0 };
    let ambiguos = 0;
    const filtrados = brutos.filter((i) => {
      const turnos = i.turma ? turnosPorNome.get(i.turma) : undefined;
      if (turnos === undefined) return false;   // turma fora do cadastro: turno desconhecido
      if (turnos.size > 1) {
        ambiguos += 1;
        return false;
      }
      return turnos.has(turnoAtivo);
    });
    return { itens: filtrados, foraPorNomeRepetido: ambiguos };
  }, [isAno, local.dados, live.dados, turnoAtivo, turnosPorNome]);

  // Opções de TURMA vêm dos dados exibidos (como antes — casam sempre com as linhas).
  const turmas = useMemo(
    () => (Array.from(new Set(itens.map((i) => i.turma).filter(Boolean))) as string[]).sort(),
    [itens],
  );
  // Séries consolidadas presentes no placar (via mapa da base).
  const series = useMemo(
    () => Array.from(new Set(
      turmas.map((nome) => turmaDaBase.get(nome)?.ano_escolar).filter(Boolean) as string[],
    )).sort(),
    [turmas, turmaDaBase],
  );

  const visiveis = useMemo(() => {
    if (alvo.startsWith("turma:")) {
      const nome = alvo.slice(6);
      return itens.filter((i) => i.turma === nome);
    }
    if (alvo.startsWith("serie:")) {
      const serie = alvo.slice(6);
      return itens.filter((i) => turmaDaBase.get(i.turma ?? "")?.ano_escolar === serie);
    }
    return itens;
  }, [alvo, itens, turmaDaBase]);

  // A classificação oficial usa ids do cadastro: traduz o alvo (nome/série) do
  // placar. Uma turma do placar sem correspondência no cadastro não filtra a
  // classificação — e a tela avisa, em vez de fingir que filtrou.
  const filtrosOficial: FiltrosDimensao & { semCorrespondencia?: boolean } = useMemo(() => {
    if (alvo.startsWith("turma:")) {
      const t = turmaDaBase.get(alvo.slice(6));
      return t ? { turma_id: String(t.id), turno: turnoAtivo }
               : { turno: turnoAtivo, semCorrespondencia: true };
    }
    if (alvo.startsWith("serie:")) return { ano_escolar: alvo.slice(6), turno: turnoAtivo };
    return { turno: turnoAtivo };
  }, [alvo, turmaDaBase, turnoAtivo]);

  const atualizadoEm = !isAno && live.dados?.atualizado_em ? dataHora(live.dados.atualizado_em) : null;

  const rotuloPeriodo = rotuloDoPeriodo(periodo);
  const recorte = [
    alvo.startsWith("turma:") ? alvo.slice(6) : alvo.startsWith("serie:") ? `${alvo.slice(6)} (todas as turmas)` : null,
    turnoAtivo !== TURNO_TODOS ? (turnoAtivo === TURNO_SEM ? "turmas sem turno" : rotuloTurno(turnoAtivo)) : null,
  ].filter(Boolean).join(" · ");
  const pronto = periodoCompleto && !carregando && !erro;

  const csv: TabelaCsv | null = !pronto || visiveis.length === 0 ? null : {
    nomeArquivo: nomeArquivoCsv(`ranking-matematica-${rotuloPeriodo}${recorte ? `-${recorte}` : ""}`),
    cabecalho: ["Posição", "Aluno", "Turma", "Estrelas", "Atividades", "Pontuação média (no período)"],
    linhas: visiveis.map((item) => [
      item.posicao, item.nome, item.turma ?? "", item.estrelas, item.atividades, media(item.pontuacao_media),
    ]),
  };

  const acoes = (
    <AcoesRanking
      alvo={alvoAcoes}
      embutido={embutido}
      csv={csv}
      certificados={{
        // A ordem é a do placar exibido; linha sem ficha (aluno_id nulo) fica fora
        // do lote, com aviso no próprio modal.
        alunos: pronto
          ? visiveis.map((item) => ({
            aluno_id: item.aluno_id, nome: item.nome, turma: item.turma, posicao: item.posicao,
          }))
          : [],
        modeloInicial: "matific",
        contexto: `Ranking · Matemática, placar do Matific (estrelas) · ${rotuloPeriodo}${recorte ? ` · ${recorte}` : ""}`,
        // Placar de um bimestre: o bimestre impresso abre nele, não no de hoje.
        bimestreInicial: bimestreDoPeriodo(periodo.preset),
      }}
    />
  );

  // Pódio: as estrelas (o que ordena), com atividades e a pontuação média do
  // MESMO período. Sem link: linha sem ficha também pode subir ao pódio.
  const podio: ItemPodio[] = itensDoPodio(visiveis).map((item, i) => ({
    chave: item.aluno_id ?? `sem-ficha-${i}`,
    posicao: item.posicao,
    nome: item.nome,
    turma: item.turma,
    avatar: item.aluno_id ?? item.nome,
    destaque: { valor: numero(item.estrelas), unidade: item.estrelas === 1 ? "estrela" : "estrelas" },
    metricas: [
      { rotulo: "atividades", valor: numero(item.atividades) },
      { rotulo: "média", valor: media(item.pontuacao_media) },
    ],
  }));

  // Origem do dado, à vista junto do título do placar.
  const origem = carregando ? null : isAno ? (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-zinc-100 px-2.5 py-1 text-xs font-medium text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">
      <Database size={13} aria-hidden /> Banco local · última coleta (data no selo acima)
    </span>
  ) : atualizadoEm ? (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-teal-50 px-2.5 py-1 text-xs font-medium text-teal-700 dark:bg-teal-500/15 dark:text-teal-300">
      <Radio size={13} aria-hidden /> Dados do Matific · {atualizadoEm}
    </span>
  ) : null;

  return (
    <div>
      {embutido ? acoes : (
        <PageHeader
          titulo="Placar Matific (estrelas e atividades no período)"
          descricao={<DescricaoRanking periodo={rotuloPeriodo} dimensoes={["matematica"]} aoVivo={!isAno} />}
          acoes={acoes}
        />
      )}

      {/* Filtros que valem para o placar E para a classificação oficial (que não
          usa o período: é do ano letivo). */}
      <BarraFiltrosRanking
        extra={(
          <BotaoIcone
            rotulo="Atualizar"
            onClick={atualizar}
            disabled={carregando || !periodoCompleto}
            className="disabled:cursor-not-allowed disabled:opacity-50"
          >
            <RefreshCw size={16} aria-hidden className={carregando ? "animate-spin motion-reduce:animate-none" : ""} />
          </BotaoIcone>
        )}
      >
        <SeletorPeriodo valor={periodo} onChange={trocarPeriodo} />
        {/* Mesmo ícone do filtro de turma das abas irmãs (FiltroTurmaSerie). */}
        <MolduraPilula icone={Users}>
          <select
            aria-label="Filtrar por turma ou série"
            className={estiloSelectPilula}
            value={alvo}
            onChange={(e) => setAlvo(e.target.value)}
          >
            <option value="">Todas as turmas</option>
            {series.length > 0 && (
              <optgroup label="Séries — consolidado">
                {series.map((s) => (
                  <option key={`s-${s}`} value={`serie:${s}`}>{s} (todas as turmas)</option>
                ))}
              </optgroup>
            )}
            {turmas.length > 0 && (
              <optgroup label="Turmas">
                {turmas.map((t) => <option key={`t-${t}`} value={`turma:${t}`}>{t}</option>)}
              </optgroup>
            )}
          </select>
        </MolduraPilula>
        <SeletorTurno turmas={turmasBase ?? []} valor={turno} onChange={definirTurno} />
      </BarraFiltrosRanking>

      {/* DE QUANDO é o dado do banco local (classificação oficial e placar do
          ano): a coleta pode estar parada — o selo diz a data e avisa. */}
      <SeloFrescorDaEscola dimensoes={["matematica"]} />

      {!isAno && periodoCompleto && !carregando && foraPorNomeRepetido > 0 && (
        <p
          role="status"
          className="mb-4 rounded-xl border border-ouro-200 bg-ouro-50 px-3.5 py-2.5 text-xs text-zinc-800 dark:border-ouro-400/30 dark:bg-ouro-400/10 dark:text-zinc-100"
        >
          {numero(foraPorNomeRepetido)} aluno(s) de turmas com o mesmo nome em turnos diferentes
          não entram no filtro de turno do placar ao vivo.
        </p>
      )}

      {/* 1. PLACAR MATIFIC no período (estrelas e atividades) — o bloco principal. */}
      <Card className="mb-5 overflow-hidden">
        <CabecalhoCartao
          icone={Star}
          tom="teal"
          titulo="Estrelas e atividades no período"
          subtitulo={`${rotuloPeriodo} · ordem por estrelas, depois atividades`}
          acoes={origem}
          ajuda={<AjudaMatematica />}
        />
        {!periodoCompleto ? (
          <Vazio icone={Calculator} titulo="Escolha as duas datas"
                 descricao="Para o período personalizado, informe a data inicial e a final." />
        ) : carregando ? (
          isAno ? <EsqueletoRanking /> : (
            <div className="flex flex-col items-center gap-2 border-t border-zinc-100 px-5 py-10 text-center dark:border-zinc-800">
              <Carregando />
              <p className="text-sm text-zinc-600 dark:text-zinc-300">
                Consultando o Matific em tempo real…
              </p>
              <p className="max-w-md text-xs text-zinc-500 dark:text-zinc-400">
                Normalmente rápido. Se a sessão expirou, a primeira consulta pode levar
                cerca de um minuto (o robô refaz o login no Matific).
              </p>
            </div>
          )
        ) : erro ? (
          <Erro titulo={isAno ? "Não foi possível carregar" : "Não foi possível consultar o Matific"}
                descricao={erro.message} aoTentar={tentarDeNovo} />
        ) : visiveis.length === 0 ? (
          <Vazio icone={Star} titulo="Nenhuma atividade de matemática no período"
                 descricao="Ninguém pontuou no Matific nesse intervalo. Ajuste o período ou o turno." />
        ) : (
          <>
            <FaixaPodio itens={podio} rotulo="Pódio do placar do Matific" />
            {/* Celular: as ESTRELAS (o que ordena) ficam presas à direita. */}
            <TabelaRolavel rotulo="Placar do Matific: tabela completa">
              <table className={t.tabela}>
                <thead className={t.thead}>
                  <tr>
                    <th scope="col" className={t.th}>#</th>
                    <th scope="col" className={t.th}>Aluno</th>
                    <th scope="col" className={t.th}>Turma</th>
                    <th scope="col" className={`${t.thNum} ${t.thPresa}`}>Estrelas</th>
                    <th scope="col" className={t.thNum}>Atividades</th>
                    {/* Em duas linhas: numa só, o cabeçalho empurrava a tabela para fora do
                        cartão e espremia Aluno e Turma. O texto (e o nome da coluna) é o mesmo. */}
                    <th scope="col" className={t.thNum}>
                      Pontuação média{" "}
                      <span className="block">(no período)</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {visiveis.map((item, idx) => (
                    <tr key={`${item.posicao}-${item.nome}-${idx}`} className={t.tr}>
                      <td className={t.td}><PosicaoRanking posicao={item.posicao} /></td>
                      <td className={t.td}>
                        <CelulaAluno
                          nome={item.nome}
                          href={item.aluno_id ? `/alunos/${item.aluno_id}` : null}
                          chave={item.aluno_id ?? item.nome}
                        />
                      </td>
                      <td className={t.tdCurto}>{item.turma ? <Chip>{item.turma}</Chip> : "—"}</td>
                      <td className={`${t.tdForte} ${t.tdPresa}`}>
                        <span className="inline-flex items-center gap-1">
                          <Star size={14} aria-hidden className="fill-ouro-400 text-ouro-500" />
                          {numero(item.estrelas)}
                        </span>
                      </td>
                      <td className={t.tdNum}>{numero(item.atividades)}</td>
                      <td className={`${t.tdNum} text-zinc-500 dark:text-zinc-400`}>{media(item.pontuacao_media)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TabelaRolavel>
          </>
        )}
      </Card>

      {/* 2. CLASSIFICAÇÃO OFICIAL: só aferidos, nota do ano, não aferidos ao lado. */}
      <DesempenhoDimensao
        dimensao="matematica"
        filtros={filtrosOficial}
        recolhivel
        aviso={filtrosOficial.semCorrespondencia && (
          <p className="mb-3 rounded-xl border border-ouro-200 bg-ouro-50 px-3.5 py-2.5 text-xs text-zinc-800 dark:border-ouro-400/30 dark:bg-ouro-400/10 dark:text-zinc-100">
            A turma escolhida não existe no cadastro de turmas; a classificação oficial mostra todas as turmas.
          </p>
        )}
      />
    </div>
  );
}

/** "Como funciona" do placar (texto recolhido por padrão). */
function AjudaMatematica() {
  return (
    <ul className="list-disc space-y-1.5 pl-5">
      <li>
        Placar do Matific: estrelas, atividades e pontuação média só no período escolhido.
        Não é a classificação oficial do ano (nota de 0 a 100), que fica logo abaixo.
      </li>
      <li>
        No ano letivo, o placar vem do banco do Constela, mantido pela sincronização diária (a
        data da última coleta aparece no selo). Qualquer outro período é consultado no Matific
        na hora: os mesmos alunos, estrelas e atividades do site. O botão de atualizar força uma
        nova consulta.
      </li>
      <li>
        Na consulta ao vivo, o turno é aplicado pelo nome da turma no cadastro; turma com o
        mesmo nome em dois turnos fica de fora do recorte, e a tela avisa quantos alunos são.
      </li>
      <li>
        Aluno do Matific sem ficha no Constela aparece sem link e fica de fora do lote de
        certificados (ninguém entra no lugar).
      </li>
    </ul>
  );
}
