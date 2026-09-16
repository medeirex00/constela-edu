/**
 * Premiações da escola por PERÍODO.
 *
 * Categorias (Melhor Leitor, Melhor Matemática, Mais Livros, Mais Tempo) com o
 * pódio calculado EXCLUSIVAMENTE no intervalo escolhido. "Melhor Matemática" é a
 * média ajustada de estrelas por atividade feita DENTRO do período, com a régua
 * da escola inteira (decisão do dono 2026-09-15). O índice chega PRONTO do
 * backend: a tela só formata (2 casas + unidade), nunca recalcula. Abaixo,
 * "Melhor Evolução" (Leitura e Matemática) premia quem mais CRESCEU no período
 * (motor de evolução, leitura read-only) — só entra no pódio quem cresceu (> 0).
 *
 * Duas dimensões independentes e GLOBAIS (seguem o usuário pelos rankings): o
 * PERÍODO temporal (seletor de datas) e o TURNO escolar (seletor de turno; as
 * opções vêm de `Turma.turno` da escola, nunca hardcoded). Os pódios por turno
 * vêm do backend (`?turnos=true`): vencedores calculados só com os alunos do
 * turno; a régua da Matemática é a da escola inteira (decisão registrada).
 * Com UMA TURMA selecionada, a turma vence (o turno fica desabilitado, com o
 * motivo em texto visível ligado ao seletor por `aria-describedby`).
 *
 * O backend agrupa por turno TODOS os alunos ativos matriculados no ano letivo
 * (com ou sem dado no período): um turno sem grupo significa "ninguém
 * matriculado nesse turno", não "ninguém com dados".
 *
 * Dados DO RECORTE ATUAL: `useApi` mantém a resposta anterior enquanto a nova
 * URL carrega (e há um render com `carregando=false` antes do efeito). O aviso
 * de turno sem grupo e os cartões de Melhor Evolução só usam uma resposta
 * carregada PARA a URL atual — senão o pódio de uma turma decidiria o turno da
 * evolução por um instante (e dispararia consulta com o recorte errado).
 *
 * PERÍODO PEDIDO × JANELA USADA: a Matemática é recortada pelo ANO LETIVO, e o
 * backend devolve em `regua_matematica` o `modo` e as datas efetivamente usadas.
 * Quando a janela difere do período do cabeçalho, a tela mostra qual intervalo
 * entrou na conta; e um pódio vazio explica o MOTIVO pelo modo (fora do ano
 * letivo, datas invertidas, sem atividade), em vez de afirmar sempre que
 * ninguém fez atividade — o que era falso justamente quando o dado existia e
 * foi descartado pelo filtro de ano. Nada aqui recalcula: só lê e formata.
 */
import { Award, TrendingUp, Trophy } from "lucide-react";
import { useId, useState } from "react";
import { Link } from "react-router-dom";

import { SeletorPeriodo, periodoParaQuery } from "../components/SeletorPeriodo";
import { SeletorTurno } from "../components/SeletorTurno";
import { Card, Carregando, PageHeader, Vazio, estiloInput } from "../components/ui";
import { useApp } from "../context/AppContext";
import { useApi } from "../hooks/useApi";
import { nota as fmtNota, numero, tempoLeitura } from "../lib/formato";
import { TURNO_TODOS, chaveTurno, rotuloTurno, turnoEfetivo, turnoParaQuery } from "../lib/turnos";
import type { CategoriaPremiacao, Premiacoes as PremiacoesT, Turma } from "../lib/types";

const MEDALHAS = ["🥇", "🥈", "🥉"];
const UNIDADE_MATEMATICA = "estrelas/atividade";

/** Régua da "Melhor Matemática": a janela REALMENTE usada pelo backend.
 *  Ainda não está em packages/core (ver pendências), por isso é tipada aqui e
 *  intersectada na resposta. */
type ModoRegua = "periodo" | "situacao_atual" | "fora_do_ano_letivo" | "periodo_invalido";

interface ReguaMatematica {
  modo: ModoRegua;
  ano_letivo: number;
  inicio_efetivo: string | null;
  fim_efetivo: string | null;
}

type RespostaPremiacoes = PremiacoesT & { regua_matematica?: ReguaMatematica };

/** "2026-01-31T23:59:59.999999" → "31/01/2026". Sem passar por `Date`: a data
 *  vem na hora local da escola e converter fuso deslocaria o dia. */
function soData(iso: string | null | undefined): string | null {
  const partes = (iso ?? "").split("T")[0].split("-");
  return partes.length === 3 && partes[0].length === 4
    ? `${partes[2]}/${partes[1]}/${partes[0]}`
    : null;
}

/** A janela usada na Matemática difere do período pedido? Devolve o texto a
 *  exibir, ou null quando o cabeçalho já conta a verdade. */
function janelaDivergente(dados: RespostaPremiacoes): string | null {
  const regua = dados.regua_matematica;
  if (!regua) return null;
  // "Todo o histórico" não recorta período: vale o acumulado do ano letivo.
  if (regua.modo === "situacao_atual") {
    return `Matemática: acumulado do ano letivo ${regua.ano_letivo}, sem recorte de período`;
  }
  // Sem janela (fora do ano letivo / datas invertidas): o motivo vai no card vazio.
  if (regua.modo !== "periodo") return null;
  const inicio = soData(regua.inicio_efetivo);
  const fim = soData(regua.fim_efetivo);
  if (!inicio || !fim) return null;
  if (inicio === soData(dados.periodo.inicio) && fim === soData(dados.periodo.fim)) return null;
  return `Matemática: ${inicio} a ${fim} (ano letivo ${regua.ano_letivo})`;
}

/** Por que o pódio de Matemática está vazio — derivado do modo, nunca fixo. */
function textoVazioMatematica(regua?: ReguaMatematica): string {
  switch (regua?.modo) {
    case "fora_do_ano_letivo":
      return `O período escolhido está fora do ano letivo ${regua.ano_letivo}: a Matemática só `
        + "considera dados do ano letivo, então não há janela a apurar.";
    case "periodo_invalido":
      return "A data inicial é posterior à final — corrija o período para apurar a Matemática.";
    case "situacao_atual":
      return `Nenhum aluno com atividade do Matific no ano letivo ${regua.ano_letivo}.`;
    default:
      return "Nenhuma atividade do Matific feita dentro do período.";
  }
}

function formatarValor(valor: number, unidade: string): string {
  if (unidade === "min") return tempoLeitura(valor);
  if (unidade === UNIDADE_MATEMATICA) {
    // Só exibição: o índice (0 a 5) já vem calculado pelo backend.
    const texto = valor.toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    return `${texto} ${unidade}`;
  }
  return `${numero(valor)} ${unidade}`;
}

function CartaoCategoria({ categoria, vazioTexto, legenda }: {
  categoria: CategoriaPremiacao; vazioTexto?: string; legenda?: string;
}) {
  const [campeao, ...resto] = categoria.podio;
  return (
    <Card className="flex flex-col p-5">
      <div className="mb-3 flex items-start gap-3">
        <span className="text-2xl leading-none">{categoria.icone}</span>
        <div>
          <h3 className="text-sm font-semibold">{categoria.titulo}</h3>
          <p className="text-xs text-zinc-500 dark:text-zinc-400">{categoria.descricao}</p>
          {legenda && <p className="mt-0.5 text-[11px] text-zinc-400">{legenda}</p>}
        </div>
      </div>

      {!campeao ? (
        <p className="py-6 text-center text-sm text-zinc-400">
          {vazioTexto ?? "Sem dados no período."}
        </p>
      ) : (
        <>
          <Link
            to={`/alunos/${campeao.aluno_id}`}
            className="flex items-center gap-3 rounded-xl border border-amber-200 bg-amber-50/70 p-3 transition-colors hover:bg-amber-50 dark:border-amber-500/20 dark:bg-amber-500/10"
          >
            <span className="text-2xl">🥇</span>
            <div className="min-w-0 flex-1">
              <p className="truncate font-semibold">{campeao.nome}</p>
              {campeao.turma && <p className="text-xs text-zinc-500 dark:text-zinc-400">{campeao.turma}</p>}
            </div>
            <span className="shrink-0 text-right text-sm font-bold tabular-nums text-amber-700 dark:text-amber-300">
              {formatarValor(campeao.valor, categoria.unidade)}
            </span>
          </Link>

          {resto.length > 0 && (
            <ul className="mt-2 space-y-0.5">
              {resto.map((item) => (
                <li key={item.aluno_id}>
                  <Link
                    to={`/alunos/${item.aluno_id}`}
                    className="flex items-center gap-2.5 rounded-lg px-2 py-1.5 text-sm transition-colors hover:bg-zinc-50 dark:hover:bg-zinc-800/60"
                  >
                    <span className="w-5 shrink-0 text-center">
                      {MEDALHAS[item.posicao - 1] ?? <span className="text-xs text-zinc-400">{item.posicao}º</span>}
                    </span>
                    <span className="min-w-0 flex-1 truncate">{item.nome}</span>
                    {item.turma && <span className="hidden shrink-0 text-xs text-zinc-400 sm:block">{item.turma}</span>}
                    <span className="shrink-0 tabular-nums text-zinc-500 dark:text-zinc-400">
                      {formatarValor(item.valor, categoria.unidade)}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </Card>
  );
}

// --- Melhor Evolução (Leitura / Matemática) ---------------------------------
// Reusa o endpoint de evolução por DIMENSÃO (crescimento DENTRO da janela, motor
// oficial read-only). O critério (evolução, não desempenho absoluto) fica claro
// no rótulo. Matemática pode vir vazia por baixa densidade de snapshots (L1).
interface EvolucaoItem {
  aluno_id: number; nome: string; turma: string;
  posicao: number; nota: number | null; n_aferidos: number | null;
}

function CartaoEvolucao({ escolaId, dimensao, titulo, icone, params, vazio }: {
  escolaId: number; dimensao: "leitura" | "matematica";
  titulo: string; icone: string; params: string; vazio: string;
}) {
  // `params` traz o MESMO período e turno das premiações (o filtro é lockado).
  const { dados, erro, carregando } = useApi<EvolucaoItem[]>(
    `/escolas/${escolaId}/ranking-evolucao?dimensao=${dimensao}${params}`,
  );
  // Pódio de EVOLUÇÃO só com quem cresceu (nota > 0) — o zero legítimo de quem
  // usa a plataforma e não avançou fica na lista da API, não no pódio.
  const podio = (dados ?? []).filter((item) => (item.nota ?? 0) > 0).slice(0, 5);
  const [campeao, ...resto] = podio;
  return (
    <Card className="flex flex-col p-5">
      <div className="mb-3 flex items-start gap-3">
        <span className="text-2xl leading-none">{icone}</span>
        <div>
          <h3 className="text-sm font-semibold">{titulo}</h3>
          <p className="text-xs text-zinc-500 dark:text-zinc-400">
            Quem mais CRESCEU no período (não o maior acumulado)
          </p>
        </div>
      </div>
      {carregando ? (
        <div className="py-6"><Carregando /></div>
      ) : erro ? (
        <p className="py-6 text-center text-sm text-zinc-400">Não foi possível carregar.</p>
      ) : !campeao ? (
        <p className="py-6 text-center text-sm text-zinc-400">{vazio}</p>
      ) : (
        <>
          <Link
            to={`/alunos/${campeao.aluno_id}/evolucao`}
            className="flex items-center gap-3 rounded-xl border border-emerald-200 bg-emerald-50/70 p-3 transition-colors hover:bg-emerald-50 dark:border-emerald-500/20 dark:bg-emerald-500/10"
          >
            <span className="text-2xl">🥇</span>
            <div className="min-w-0 flex-1">
              <p className="truncate font-semibold">{campeao.nome}</p>
              {campeao.turma && <p className="text-xs text-zinc-500 dark:text-zinc-400">{campeao.turma}</p>}
            </div>
            <span className="shrink-0 inline-flex items-center gap-1 text-sm font-bold tabular-nums text-emerald-700 dark:text-emerald-300">
              <TrendingUp size={13} /> {fmtNota(campeao.nota ?? 0)}
            </span>
          </Link>
          {resto.length > 0 && (
            <ul className="mt-2 space-y-0.5">
              {resto.map((item) => (
                <li key={item.aluno_id}>
                  <Link to={`/alunos/${item.aluno_id}/evolucao`}
                        className="flex items-center gap-2.5 rounded-lg px-2 py-1.5 text-sm transition-colors hover:bg-zinc-50 dark:hover:bg-zinc-800/60">
                    <span className="w-5 shrink-0 text-center">
                      {MEDALHAS[item.posicao - 1] ?? <span className="text-xs text-zinc-400">{item.posicao}º</span>}
                    </span>
                    <span className="min-w-0 flex-1 truncate">{item.nome}</span>
                    <span className="shrink-0 tabular-nums text-zinc-500 dark:text-zinc-400">{fmtNota(item.nota ?? 0)}</span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </Card>
  );
}

export default function Premiacoes() {
  const { escolaId, periodo, definirPeriodo, turno, definirTurno } = useApp();
  const [turmaId, setTurmaId] = useState("");
  const idMotivoTurno = useId();

  const { dados: turmas } = useApi<Turma[]>(
    escolaId ? `/escolas/${escolaId}/turmas` : null, { cacheMs: 60_000 });

  const q = periodoParaQuery(periodo);
  const filtroTurma = turmaId ? `&turma_id=${turmaId}` : "";
  // Só pede a quebra por turno na visão "todas as turmas".
  const pedirTurnos = turmaId ? "" : "&turnos=true";
  const urlPremiacoes = escolaId
    ? `/escolas/${escolaId}/premiacoes?${q}${filtroTurma}${pedirTurnos}` : null;
  // URL da última resposta que CHEGOU (ver "Dados DO RECORTE ATUAL" no topo).
  const [urlCarregada, setUrlCarregada] = useState<string | null>(null);
  const { dados: ultimaResposta, erro, carregando } = useApi<RespostaPremiacoes>(urlPremiacoes, {
    aoSucesso: () => setUrlCarregada(urlPremiacoes),
  });
  const respostaAtual = urlCarregada === urlPremiacoes;
  const dados = !carregando && respostaAtual ? ultimaResposta : null;
  // Resposta antiga na mão e a nova ainda não chegou: é carregamento, não vazio.
  const aguardando = carregando || (!erro && ultimaResposta != null && !respostaAtual);

  // TURNO global: com uma turma selecionada, a turma vence (o turno não se
  // aplica). Um turno persistido que não existe nesta escola conta como "todos"
  // — sem sobrescrever a escolha guardada.
  const turnoAtivo = turmaId ? TURNO_TODOS : turnoEfetivo(turno, turmas);
  const turnos = (!turmaId && dados?.turnos) || [];
  // Escopo de categorias exibido: o grupo do turno escolhido ou "Todos".
  const grupoTurno = turnoAtivo !== TURNO_TODOS
    ? turnos.find((g) => chaveTurno(g.turno) === turnoAtivo) : undefined;
  // Turno escolhido, mas sem nenhum aluno matriculado nele neste ano letivo:
  // mostra "Todos" e AVISA (não finge que o pódio é do turno), sem mexer no que
  // está guardado. `dados` já é só a resposta do recorte atual.
  const turnoSemRecorte = turnoAtivo !== TURNO_TODOS && !!dados && !grupoTurno;
  const categorias = grupoTurno?.categorias ?? dados?.categorias ?? [];

  // Evolução respeita EXATAMENTE os mesmos filtros lockados: período + turma +
  // turno (vazio = "Sem turno"). Sem isto, a evolução ignoraria período/turno e
  // a tela mostraria recortes divergentes. Quando o turno não existe no recorte
  // (pódios caíram em "Todos"), a evolução também vai sem turno.
  const filtroTurno = turnoAtivo !== TURNO_TODOS && !turnoSemRecorte
    ? `&${turnoParaQuery(turnoAtivo)}` : "";
  const paramsEvol = `&${q}${filtroTurma}${filtroTurno}`;

  // Régua da Matemática: o período do cabeçalho pode não ser o intervalo usado.
  const regua = dados?.regua_matematica;
  const avisoJanela = dados ? janelaDivergente(dados) : null;

  return (
    <div>
      <PageHeader
        titulo="Premiações"
        descricao="Vencedores calculados apenas com os dados do período escolhido — por semana, mês, bimestre ou datas personalizadas."
      />

      <Card className="mb-6 flex flex-wrap items-center gap-3 p-4">
        <SeletorPeriodo valor={periodo} onChange={definirPeriodo} />
        <select
          aria-label="Filtrar por turma"
          className={`${estiloInput} w-auto`}
          value={turmaId}
          onChange={(e) => setTurmaId(e.target.value)}
        >
          <option value="">Todas as turmas</option>
          {(turmas ?? []).map((t) => <option key={t.id} value={t.id}>{t.nome}</option>)}
        </select>
        <SeletorTurno
          turmas={turmas ?? []}
          valor={turmaId ? TURNO_TODOS : turno}
          onChange={definirTurno}
          disabled={Boolean(turmaId)}
          descricaoId={turmaId ? idMotivoTurno : undefined}
        />
        {/* Motivo do seletor desabilitado em TEXTO visível (title não chega a
            leitor de tela nem a toque). */}
        {turmaId && (
          <span id={idMotivoTurno} className="text-xs text-zinc-500 dark:text-zinc-400">
            Com uma turma escolhida, o turno não se aplica.
          </span>
        )}
        {dados && (
          <span className="ml-auto inline-flex items-center gap-1.5 text-sm font-medium text-indigo-700 dark:text-indigo-300">
            <Trophy size={15} /> {dados.periodo.rotulo}
            {grupoTurno && <> · {grupoTurno.turno_rotulo} ({grupoTurno.total})</>}
          </span>
        )}
      </Card>

      {avisoJanela && (
        <p role="note" className="mb-4 text-sm text-amber-700 dark:text-amber-300">
          O período mostrado não é o intervalo usado na Matemática. {avisoJanela}.
        </p>
      )}

      {turnoSemRecorte && (
        <p role="status" className="mb-4 text-sm text-amber-700 dark:text-amber-300">
          Nenhum aluno matriculado no turno {rotuloTurno(turnoAtivo)} neste ano letivo; mostrando todos os turnos.
        </p>
      )}

      {aguardando ? (
        <Carregando />
      ) : erro ? (
        <Vazio titulo="Não foi possível carregar as premiações" descricao={erro.message} />
      ) : !dados ? (
        <Vazio titulo="Não foi possível carregar as premiações" />
      ) : (
        <>
          <div className="grid gap-4 md:grid-cols-2">
            {categorias.map((categoria) => (
              <CartaoCategoria
                key={categoria.chave} categoria={categoria}
                vazioTexto={categoria.chave === "melhor_matematica"
                  ? textoVazioMatematica(regua)
                  : undefined}
                legenda={categoria.chave === "melhor_matematica"
                  ? "Média ajustada de estrelas por atividade no período (0 a 5)"
                  : undefined}
              />
            ))}
          </div>

          {/* MELHOR EVOLUÇÃO — quem mais cresceu no período (mesmo período +
              turma + turno dos pódios acima). */}
          <h2 className="mb-3 mt-8 text-sm font-semibold text-zinc-700 dark:text-zinc-300">
            Melhor Evolução no período
          </h2>
          {escolaId && (
            <div className="grid gap-4 md:grid-cols-2">
              <CartaoEvolucao
                escolaId={escolaId} dimensao="leitura" params={paramsEvol}
                titulo="Melhor Evolução — Leitura" icone="📚"
                vazio="Sem dados suficientes para medir evolução de leitura no período." />
              <CartaoEvolucao
                escolaId={escolaId} dimensao="matematica" params={paramsEvol}
                titulo="Melhor Evolução — Matemática" icone="🧮"
                vazio="Sem dados suficientes no período para medir evolução de Matemática." />
            </div>
          )}
        </>
      )}

      <p className="mt-6 flex items-start gap-1.5 text-xs text-zinc-400">
        <Award size={13} className="mt-0.5 shrink-0" />
        <span>
          Melhor Matemática divide as estrelas do período pelas atividades do período somadas a atividades extras sem estrela (20% da mediana de atividades da escola).
          {" "}A régua é a da escola inteira, em qualquer filtro, e{" "}
          {regua?.modo === "situacao_atual"
            ? `vale o acumulado do ano letivo ${regua.ano_letivo} — “Todo o histórico” não recorta período.`
            : regua
              ? `só entram atividades feitas dentro do período, sempre recortado pelo ano letivo ${regua.ano_letivo}.`
              : "só entram atividades feitas dentro do período."}
          {" "}Evolução mede o crescimento dentro do intervalo, não o acumulado.
        </span>
      </p>
      {grupoTurno && (
        <p className="mt-1 text-xs text-zinc-400">
          Vencedores calculados só com os alunos do turno selecionado; a régua da Matemática é a da escola inteira.
        </p>
      )}
    </div>
  );
}
