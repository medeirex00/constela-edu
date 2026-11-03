/**
 * Gamificação (PRD §64, §79–§84): mural, destaques e ranking de XP.
 *
 * Identidade visual v2 (docs/design/IDENTIDADE-VISUAL-V2.md): os três destaques
 * (Aluno do Dia, da Semana e do Mês — maior evolução em 1, 7 e 30 dias, decididos
 * pelo backend) em cartões com avatar e a pílula de evolução; o mural no padrão
 * "Destaques recentes" (emoji da conquista em quadrado pastel e tempo relativo);
 * o Ranking de XP no padrão da tabela do Ranking (medalha 1º–3º, avatar, chip da
 * turma, nível em pílula). A tela não reordena nada: a ordem é a da API.
 *
 * Estados honestos: enquanto o mural carrega, os destaques mostram o esqueleto
 * (antes diziam "Sem destaque no período." durante a carga); se o mural falha,
 * dizem que estão indisponíveis — "sem destaque" só quando a API diz que não há.
 */
import { CalendarDays, ChevronDown, Flame, Medal, Sparkles, Trophy, TrendingUp } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { QuadradoEmoji, plural, tempoRelativo } from "../components/ConquistasUi";
import { TabelaRolavel } from "../components/TabelaRolavel";
import {
  Avatar,
  Botao,
  Card,
  Chip,
  ESTILOS_BOTAO,
  Erro,
  IconePastel,
  Medalha,
  PageHeader,
  PosicaoBolinha,
  Skeleton,
  TAMANHOS_BOTAO,
  Vazio,
  classesTabela,
} from "../components/ui";
import type { TomPastel } from "../components/ui";
import { useApp } from "../context/AppContext";
import { useApi } from "../hooks/useApi";
import { dataHora, nota, numero } from "../lib/formato";

interface Destaque {
  aluno_id: number;
  nome: string;
  turma: string | null;
  nota_evolucao: number;
  ganhos: Record<string, number>;
}

interface Mural {
  destaques: { dia: Destaque | null; semana: Destaque | null; mes: Destaque | null };
  eventos: { tipo: string; icone: string; texto: string; data: string }[];
}

interface ItemXp {
  posicao: number;
  aluno_id: number;
  nome: string;
  turma: string;
  xp: number;
  nivel: number;
  conquistas: number;
}

/** Quantos eventos do mural e linhas do XP aparecem antes de "Mostrar mais". */
const PASSO_MURAL = 8;
const PASSO_XP = 15;

function CartaoDestaque({ titulo, janela, icone, tom, destaque, carregando, falhou }: {
  titulo: string;
  /** De QUANDO é a evolução (o backend usa 1, 7 e 30 dias). */
  janela: string;
  icone: LucideIcon;
  tom: TomPastel;
  destaque: Destaque | null;
  carregando: boolean;
  falhou: boolean;
}) {
  return (
    <Card className="flex flex-col p-5">
      <div className="flex items-center gap-3">
        <IconePastel icone={icone} tom={tom} />
        <div className="min-w-0">
          <h2 className="text-[15px] font-semibold text-zinc-900 dark:text-white">{titulo}</h2>
          <p className="text-xs text-zinc-500 dark:text-zinc-400">{janela}</p>
        </div>
      </div>
      {carregando ? (
        <div className="mt-5 flex items-center gap-3.5">
          <Skeleton className="h-10 w-10 rounded-full" />
          <div className="flex-1 space-y-2">
            <Skeleton className="h-4 w-3/4" />
            <Skeleton className="h-3 w-1/2" />
          </div>
          <span className="sr-only">Carregando o destaque…</span>
        </div>
      ) : falhou ? (
        <p className="mt-5 text-sm text-zinc-500 dark:text-zinc-400">
          Destaque indisponível: o mural não carregou.
        </p>
      ) : destaque ? (
        // De 640 a 1023 px os três cartões ficam lado a lado e estreitos (~220 px): o
        // avatar sobe para cima do nome e o nome pode quebrar em duas linhas — antes
        // ele era cortado com reticências ("Otávio Fernande…"). No celular cada cartão
        // tem a largura toda e avatar e nome voltam a ficar lado a lado.
        <div className="mt-5 flex items-center gap-3.5 sm:flex-col sm:items-start sm:gap-2.5 lg:flex-row lg:items-center lg:gap-3.5">
          <Avatar nome={destaque.nome} chave={destaque.aluno_id} tamanho="md" />
          <div className="min-w-0">
            <Link
              to={`/alunos/${destaque.aluno_id}/evolucao`}
              className="block break-words text-base font-semibold leading-snug text-zinc-900 transition-colors hover:text-indigo-600 dark:text-white dark:hover:text-indigo-300"
             title={destaque.nome}>
              {destaque.nome}
            </Link>
            <div className="mt-1 flex flex-wrap items-center gap-1.5">
              {destaque.turma && <Chip>{destaque.turma}</Chip>}
              <span className="inline-flex items-center gap-1 whitespace-nowrap rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-semibold tabular-nums text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300">
                <TrendingUp size={12} aria-hidden />
                evolução {nota(destaque.nota_evolucao)}
              </span>
            </div>
          </div>
        </div>
      ) : (
        <p className="mt-5 text-sm text-zinc-500 dark:text-zinc-400">Sem destaque no período.</p>
      )}
    </Card>
  );
}

/** Cabeçalho de um cartão de seção (ícone pastel + título h2 + linha de apoio). */
function CabecalhoSecao({ icone, tom, titulo, apoio }: {
  icone: LucideIcon; tom: TomPastel; titulo: string; apoio: string;
}) {
  return (
    <div className="flex items-center gap-3 border-b border-zinc-100 px-5 py-4 dark:border-zinc-800">
      <IconePastel icone={icone} tom={tom} tamanho="sm" />
      <div className="min-w-0">
        <h2 className="text-[15px] font-semibold text-zinc-900 dark:text-white">{titulo}</h2>
        <p className="text-xs text-zinc-500 dark:text-zinc-400">{apoio}</p>
      </div>
    </div>
  );
}

function LinhasEsqueleto({ quantas }: { quantas: number }) {
  return (
    <div aria-hidden className="space-y-3 px-5 py-4">
      {Array.from({ length: quantas }, (_, i) => (
        <div key={i} className="flex items-center gap-3">
          <Skeleton className="h-10 w-10 rounded-xl" />
          <div className="flex-1 space-y-1.5">
            <Skeleton className="h-3.5 w-4/5" />
            <Skeleton className="h-3 w-1/4" />
          </div>
        </div>
      ))}
    </div>
  );
}

export default function Conquistas() {
  const { escolaId } = useApp();
  const {
    dados: mural,
    erro: erroMural,
    carregando: carregandoMural,
    recarregar: recarregarMural,
  } = useApi<Mural>(escolaId ? `/escolas/${escolaId}/gamificacao/mural` : null);
  const {
    dados: rankingXp,
    erro: erroRanking,
    carregando: carregandoRanking,
    recarregar: recarregarRanking,
  } = useApi<ItemXp[]>(escolaId ? `/escolas/${escolaId}/gamificacao/ranking-xp` : null);
  const [eventosVisiveis, setEventosVisiveis] = useState(PASSO_MURAL);
  const [linhasXp, setLinhasXp] = useState(PASSO_XP);

  // Com escola e ainda sem resposta (inclusive no render antes do efeito do hook) é
  // carregamento, não "sem destaque".
  const destaquesCarregando = carregandoMural || (escolaId != null && !mural && !erroMural);
  const eventos = mural?.eventos ?? [];
  const xp = rankingXp ?? [];
  const agora = Date.now();

  return (
    <div className="space-y-6">
      <PageHeader
        titulo="Conquistas e Mural"
        descricao="Destaques, medalhas e XP — tudo derivado dos dados reais e recalculado automaticamente."
        acoes={
          <Link
            to="/conquistas/biblioteca"
            className={`inline-flex items-center justify-center font-semibold transition-colors ${TAMANHOS_BOTAO.md} ${ESTILOS_BOTAO.primario}`}
          >
            <Medal size={16} aria-hidden /> Biblioteca de Conquistas
          </Link>
        }
      />

      <div className="grid grid-cols-1 gap-5 sm:grid-cols-3">
        <CartaoDestaque
          titulo="Aluno do Dia" janela="Maior evolução no último dia" icone={Sparkles} tom="violeta"
          destaque={mural?.destaques.dia ?? null} carregando={destaquesCarregando} falhou={Boolean(erroMural)}
        />
        <CartaoDestaque
          titulo="Aluno da Semana" janela="Maior evolução nos últimos 7 dias" icone={CalendarDays} tom="teal"
          destaque={mural?.destaques.semana ?? null} carregando={destaquesCarregando} falhou={Boolean(erroMural)}
        />
        <CartaoDestaque
          titulo="Aluno do Mês" janela="Maior evolução nos últimos 30 dias" icone={Trophy} tom="ambar"
          destaque={mural?.destaques.mes ?? null} carregando={destaquesCarregando} falhou={Boolean(erroMural)}
        />
      </div>

      {/* Com a barra lateral (≥ 1280 px) o Ranking de XP fica com 3/5 da largura: em
          metades iguais a coluna "Conquistas" saía do cartão (rolagem lateral). Cada
          cartão tem a altura do próprio conteúdo (items-start): o mural não é mais
          esticado até a altura do ranking. */}
      <div className="grid grid-cols-1 items-start gap-6 xl:grid-cols-5">
        <Card className="overflow-hidden xl:col-span-2">
          <CabecalhoSecao
            icone={Sparkles} tom="violeta" titulo="Mural da escola"
            apoio="Conquistas desbloqueadas nos últimos 30 dias"
          />
          {carregandoMural ? (
            <LinhasEsqueleto quantas={4} />
          ) : erroMural ? (
            <Erro descricao={erroMural.message} aoTentar={recarregarMural} />
          ) : eventos.length === 0 ? (
            <Vazio icone={Sparkles} titulo="Nada por aqui ainda" descricao="Importe dados para movimentar o mural." />
          ) : (
            <>
              <ul className="divide-y divide-zinc-100 dark:divide-zinc-800/60">
                {eventos.slice(0, eventosVisiveis).map((evento, indice) => {
                  const quando = tempoRelativo(evento.data, agora);
                  return (
                    <li key={indice} className="flex items-start gap-3.5 px-5 py-3.5">
                      <QuadradoEmoji emoji={evento.icone} raridade="epica" tamanho="sm" />
                      <div className="min-w-0 flex-1">
                        <p className="text-sm text-zinc-800 dark:text-zinc-100">{evento.texto}</p>
                        <p className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">
                          {/* Mesmo rótulo dos "Destaques recentes" da Visão geral: a data é a
                              do dado (snapshot) em que a conquista apareceu. */}
                          {quando
                            ? <>registrado <time dateTime={evento.data} title={`Dado de ${quando.completo}`}>{quando.texto}</time></>
                            : <>registrado em {dataHora(evento.data)}</>}
                        </p>
                      </div>
                    </li>
                  );
                })}
              </ul>
              <div className="space-y-2 border-t border-zinc-100 px-5 py-3.5 dark:border-zinc-800">
                <p className="text-xs text-zinc-500 dark:text-zinc-400">
                  A data é a do dado em que a conquista apareceu (numa coleta por período, o fim do período), não o momento exato na plataforma.
                </p>
                {eventos.length > eventosVisiveis && (
                  <button
                    type="button"
                    onClick={() => setEventosVisiveis(eventos.length)}
                    className="inline-flex items-center gap-1 rounded-lg text-sm font-semibold text-indigo-600 transition-colors hover:text-indigo-700 hover:underline dark:text-indigo-300"
                  >
                    Mostrar todos os {eventos.length} eventos <ChevronDown size={15} aria-hidden />
                  </button>
                )}
              </div>
            </>
          )}
        </Card>

        <Card className="overflow-hidden xl:col-span-3">
          <CabecalhoSecao
            icone={Flame} tom="ambar" titulo="Ranking de XP"
            apoio="Nível e conquistas de cada aluno — separado das notas"
          />
          {carregandoRanking ? (
            <LinhasEsqueleto quantas={5} />
          ) : erroRanking ? (
            <Erro descricao={erroRanking.message} aoTentar={recarregarRanking} />
          ) : xp.length === 0 ? (
            <Vazio icone={Flame} titulo="Nenhum aluno com XP" />
          ) : (
            <>
              {/* Celular (< 640 px): a coluna Posição fica do tamanho da medalha (o rótulo
                  "Posição" continua para o leitor de tela), o avatar decorativo sai, o nome
                  quebra em até duas linhas e o XP fica preso à direita (presa-celular) —
                  "Ranking de XP" mostra o XP sem rolar. Conquistas vem deslizando a tabela,
                  com o aviso acima dela. */}
              <TabelaRolavel rotulo="Ranking de XP: tabela completa">
                <table className={`${classesTabela.tabela} tabular-nums`}>
                  <thead>
                    <tr>
                      <th scope="col" className={`${classesTabela.th} max-sm:pr-0`}>
                        <span className="max-sm:sr-only">Posição</span>
                      </th>
                      <th scope="col" className={classesTabela.th}>Aluno</th>
                      <th scope="col" className={`${classesTabela.th} text-right max-sm:px-2`}>Nível</th>
                      <th scope="col" className={`${classesTabela.th} presa-celular text-right max-sm:px-3`}>XP</th>
                      <th scope="col" className={`${classesTabela.th} text-right`}>Conquistas</th>
                    </tr>
                  </thead>
                  <tbody>
                    {xp.slice(0, linhasXp).map((item) => (
                      <tr key={item.aluno_id} className={classesTabela.tr}>
                        <td className={`${classesTabela.td} w-16 max-sm:w-12 max-sm:pr-0`}>
                          {item.posicao >= 1 && item.posicao <= 3 ? (
                            <Medalha posicao={item.posicao as 1 | 2 | 3} tamanho={28} semFita />
                          ) : (
                            <>
                              <span aria-hidden className="inline-flex"><PosicaoBolinha posicao={item.posicao} /></span>
                              <span className="sr-only">{item.posicao}º lugar</span>
                            </>
                          )}
                        </td>
                        <td className={classesTabela.td}>
                          <div className="flex min-w-0 items-center gap-3">
                            <Avatar nome={item.nome} chave={item.aluno_id} tamanho="sm" className="max-sm:hidden" />
                            <div className="min-w-0 max-sm:min-w-[8rem]">
                              {/* O nome quebra linha em vez de empurrar a tabela para
                                  fora do cartão (a contagem de conquistas sumia). */}
                              <Link
                                to={`/alunos/${item.aluno_id}`}
                                className="block break-words font-semibold leading-snug text-zinc-900 transition-colors hover:text-indigo-600 dark:text-white dark:hover:text-indigo-300"
                               title={item.nome}>
                                {item.nome}
                              </Link>
                              {item.turma && <Chip className="mt-0.5">{item.turma}</Chip>}
                            </div>
                          </div>
                        </td>
                        <td className={`${classesTabela.td} text-right max-sm:px-2`}>
                          <span className="inline-flex items-center whitespace-nowrap rounded-full bg-indigo-50 px-2.5 py-0.5 text-xs font-bold text-indigo-700 dark:bg-indigo-500/15 dark:text-indigo-200">
                            Nv {item.nivel}
                          </span>
                        </td>
                        <td className={`${classesTabela.td} presa-celular text-right font-bold text-zinc-900 max-sm:px-3 dark:text-white`}>
                          {numero(item.xp)}
                        </td>
                        <td className={`${classesTabela.td} text-right`}>
                          <span className="inline-flex items-center gap-1 whitespace-nowrap">
                            <Medal size={13} aria-hidden className="text-ouro-600" />
                            {item.conquistas}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </TabelaRolavel>
              {xp.length > linhasXp && (
                <div className="flex flex-wrap items-center justify-between gap-2 border-t border-zinc-100 px-5 py-3 dark:border-zinc-800">
                  <p className="text-xs text-zinc-500 dark:text-zinc-400">
                    Mostrando {Math.min(linhasXp, xp.length)} de {plural(xp.length, "aluno", "alunos")}
                  </p>
                  <Botao variante="secundario" tamanho="sm" onClick={() => setLinhasXp((n) => n + PASSO_XP)}>
                    Mostrar mais
                  </Botao>
                </div>
              )}
            </>
          )}
        </Card>
      </div>
    </div>
  );
}
