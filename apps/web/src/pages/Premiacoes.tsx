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
 *
 * ANO DAS CRIANÇAS: num período de um ano letivo já encerrado (a cerimônia de 2026
 * feita depois da virada), o backend monta os pódios com as crianças e as turmas
 * daquele ano e diz isso em `populacao`; a tela avisa, e também quando o período
 * passa por dois anos letivos (aí valem as crianças de agora).
 *
 * ÍNDICE OCULTO: com poucos alunos com atividade no período, o backend devolve
 * as linhas da Matemática com `valor: null` (o índice, junto das estrelas e das
 * atividades, revelaria a mediana da escola — e com ela a contagem de uma
 * criança). A tela mostra "—" no lugar do número e diz por quê; a ordem e as
 * posições são as do backend, como sempre.
 *
 * IDENTIDADE VISUAL v2 (docs/design/IDENTIDADE-VISUAL-V2.md): cada categoria num
 * cartão com ícone em quadrado pastel, o 1º colocado em destaque creme/ouro com
 * medalha e avatar, 2º e 3º com medalha prata/bronze, os demais com a bolinha
 * da posição. "Certificados do pódio" abre a emissão EM LOTE (GerarCertificados)
 * com a lista da categoria, na ordem da tela (D7) — escondido de quem não emite
 * (Secretaria). O chip "Fim do Nº bimestre · em N dias" usa o calendário oficial
 * (não existe data de premiação no sistema) e só aparece quando o período é o
 * bimestre em curso.
 */
import {
  AlertTriangle,
  Award,
  BookOpenCheck,
  Calculator,
  CalendarClock,
  ChevronRight,
  Clock,
  Info,
  Library,
  Timer,
  TrendingUp,
  Trophy,
  Users,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { Fragment, useId, useState } from "react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import GerarCertificados from "../components/GerarCertificados";
import { SeletorPeriodo, avisoPopulacao, periodoParaQuery } from "../components/SeletorPeriodo";
import { MolduraPilula, estiloSelectPilula } from "../components/SeletorPilula";
import { SeletorTurno } from "../components/SeletorTurno";
import { SeloFrescor, type Frescor } from "../components/SeloFrescor";
import {
  Avatar,
  Botao,
  Card,
  Carregando,
  Chip,
  ESTILOS_BOTAO,
  Erro,
  IconePastel,
  Medalha,
  Modal,
  PageHeader,
  PosicaoBolinha,
  SecaoRecolhivel,
  Skeleton,
  TAMANHOS_BOTAO,
} from "../components/ui";
import type { TomPastel } from "../components/ui";
import { useApp } from "../context/AppContext";
import { useApi } from "../hooks/useApi";
import { useModulos } from "../hooks/useModulos";
import { usePerfil } from "../hooks/usePerfil";
import { bimestreEmCurso, useCalendarioBimestres } from "../lib/calendarioBimestres";
import { nota as fmtNota, numero, tempoLeitura } from "../lib/formato";
import { bimestreDoPeriodo } from "../lib/tiposCertificados";
import type { AlunoParaCertificado, ModeloCertificado } from "../lib/tiposCertificados";
import { TURNO_TODOS, chaveTurno, rotuloTurno, turnoEfetivo, turnoParaQuery } from "../lib/turnos";
import type { CategoriaPremiacao, Premiacoes as PremiacoesT, Turma } from "../lib/types";

/** Quantos alunos o ranking completo traz por vez (e por "Carregar mais"). */
const PASSO_RANKING = 50;
/** Teto do `limite` aceito pelo endpoint de premiações (`le=500`). Pedir mais
 *  do que isso devolveria 422 e a janela mostraria erro no lugar do ranking. */
const LIMITE_MAXIMO_RANKING = 500;
const UNIDADE_MATEMATICA = "estrelas/atividade";

/** Visual de cada categoria (ícone lucide no quadrado pastel). Só apresentação:
 *  a lista de categorias e a ordem vêm do backend; chave desconhecida cai no troféu. */
interface VisualCategoria {
  icone: LucideIcon;
  tom: TomPastel;
}

const VISUAL_CATEGORIA: Record<string, VisualCategoria> = {
  melhor_leitor: { icone: BookOpenCheck, tom: "violeta" },
  melhor_matematica: { icone: Calculator, tom: "teal" },
  mais_livros: { icone: Library, tom: "azul" },
  mais_tempo: { icone: Timer, tom: "rosa" },
};
const VISUAL_PADRAO: VisualCategoria = { icone: Trophy, tom: "ambar" };
const VISUAL_EVOLUCAO: VisualCategoria = { icone: TrendingUp, tom: "verde" };

const visualDa = (chave: string): VisualCategoria => VISUAL_CATEGORIA[chave] ?? VISUAL_PADRAO;

/** Modelo do certificado pela categoria (D7): Leitura → arte do Elefante Letrado,
 *  Matemática → arte do Matific. Chave sem modelo de plataforma abre no Geral (a
 *  pessoa ainda pode escolher no modal, que respeita os módulos do plano). */
const MODELO_DA_CATEGORIA: Record<string, ModeloCertificado> = {
  melhor_leitor: "elefante",
  mais_livros: "elefante",
  mais_tempo: "elefante",
  melhor_matematica: "matific",
};

/** O que o modal de certificados recebe: a lista da categoria, NA ORDEM da tela. */
interface PedidoCertificados {
  alunos: AlunoParaCertificado[];
  modelo: ModeloCertificado;
  contexto: string;
}

/** Régua da "Melhor Matemática": a janela REALMENTE usada pelo backend.
 *  Ainda não está em packages/core (ver pendências), por isso é tipada aqui e
 *  intersectada na resposta. */
type ModoRegua = "periodo" | "situacao_atual" | "fora_do_ano_letivo" | "periodo_invalido";

interface ReguaMatematica {
  modo: ModoRegua;
  ano_letivo: number;
  inicio_efetivo: string | null;
  fim_efetivo: string | null;
  /** Quantos alunos fizeram atividade no período (base da régua). */
  alunos_com_atividade?: number;
}

/** `frescor`: DE QUANDO é o dado dos pódios (`frescor_ranking`, o mesmo bloco
 *  de `/ranking/frescor`, com a população do pódio). Um pódio de "outubro"
 *  montado com a última coleta de 01/10 parece completo e não é. Vem `null` num
 *  período de um ano já encerrado: o selo só sabe medir as crianças do ano atual, e
 *  sem selo é melhor que um selo de outra população.
 *  `populacao`: de que ANO LETIVO são as crianças e as turmas dos pódios — num
 *  período de um ano já encerrado (a cerimônia de 2026 depois da virada), as daquele
 *  ano; num período que passa por dois anos, as do ano atual (a tela avisa). */
type RespostaPremiacoes = PremiacoesT & {
  regua_matematica?: ReguaMatematica;
  frescor?: Frescor | null;
};

/** "2026-01-31T23:59:59.999999" → "31/01/2026". Sem passar por `Date`: a data
 *  vem na hora local da escola e converter fuso deslocaria o dia. */
function soData(iso: string | null | undefined): string | null {
  const partes = (iso ?? "").split("T")[0].split("-");
  return partes.length === 3 && partes[0].length === 4
    ? `${partes[2]}/${partes[1]}/${partes[0]}`
    : null;
}

/** O período RESPONDIDO pelo backend contém o dia de hoje? O "Nº bimestre" é resolvido
 *  no ANO LETIVO da escola: na virada (escola ainda no ano anterior), o "1º bimestre" é
 *  o do ano passado, já encerrado, enquanto o 1º do ano novo está em curso. Ponta sem
 *  data é aberta. Compara o texto AAAA-MM-DD, sem passar por fuso (como `soData`). */
function periodoContemHoje(p: { inicio: string | null; fim: string | null }, hoje: Date): boolean {
  const dois = (n: number) => String(n).padStart(2, "0");
  const dia = `${hoje.getFullYear()}-${dois(hoje.getMonth() + 1)}-${dois(hoje.getDate())}`;
  const inicio = p.inicio?.split("T")[0];
  const fim = p.fim?.split("T")[0];
  return (!inicio || inicio <= dia) && (!fim || dia <= fim);
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

/** O índice da Matemática que o backend não exibe (poucos alunos com atividade):
 *  um traço no lugar do número — nunca "0", "NaN" ou "null". */
const VALOR_OCULTO = "—";

/** Alguma linha desta premiação veio sem o valor (índice oculto pelo backend)? */
function temValorOculto(categoria: CategoriaPremiacao): boolean {
  return categoria.podio.some((item) => item.valor == null);
}

/** Por que a Matemática mostra "—": o número de alunos vem da própria régua
 *  (sem fixar aqui o mínimo, que é decisão do backend). */
function notaIndiceOculto(regua?: ReguaMatematica): string {
  const n = regua?.alunos_com_atividade;
  const quem = typeof n === "number" && n > 0
    ? `só ${n} ${n === 1 ? "aluno fez" : "alunos fizeram"} atividade no período`
    : "poucos alunos fizeram atividade no período";
  return `Índice não exibido: ${quem}, e com tão poucos ele revelaria o resultado de `
    + "uma criança. A ordem do pódio é a mesma.";
}

function formatarValor(valor: number | null, unidade: string): string {
  if (valor == null) return VALOR_OCULTO;
  if (unidade === "min") return tempoLeitura(valor);
  if (unidade === UNIDADE_MATEMATICA) {
    // Só exibição: o índice (0 a 5) já vem calculado pelo backend.
    const texto = valor.toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    return `${texto} ${unidade}`;
  }
  return `${numero(valor)} ${unidade}`;
}

/** O valor com um ponto de quebra depois de cada "/" ("estrelas/atividade"): no
 *  celular a unidade longa quebrava o cartão para fora da tela. O texto é o mesmo. */
function quebravel(texto: string): ReactNode {
  const partes = texto.split("/");
  return partes.map((parte, i) => (
    <Fragment key={i}>{i > 0 && <>/<wbr /></>}{parte}</Fragment>
  ));
}

// --- Peças visuais -----------------------------------------------------------

/** Posição de uma linha: medalha prata/bronze/ouro (1º–3º, com "Nº lugar" para
 *  leitor de tela) ou a bolinha com o número; o ordinal também vai em texto
 *  (sr-only), para a informação não depender do desenho. */
function MarcadorPosicao({ posicao }: { posicao: number }) {
  if (posicao >= 1 && posicao <= 3) {
    return <Medalha posicao={posicao as 1 | 2 | 3} tamanho={28} semFita />;
  }
  return (
    <span className="inline-flex shrink-0">
      <span aria-hidden className="inline-flex">
        <PosicaoBolinha posicao={posicao} />
      </span>
      <span className="sr-only">{posicao}º</span>
      <span className="sr-only"> lugar</span>
    </span>
  );
}

/** "Fim do 4º bimestre · em 61 dias" — calendário oficial, nunca "premiação em N dias". */
function ChipFimDoBimestre({ numero: n, dias }: { numero: number; dias: number }) {
  const texto = dias === 0
    ? `O ${n}º bimestre termina hoje`
    : `Fim do ${n}º bimestre · em ${dias} ${dias === 1 ? "dia" : "dias"}`;
  return (
    <span className="inline-flex items-center gap-2 rounded-full bg-ouro-100 px-4 py-2 text-sm font-semibold text-marinho-900 shadow-ambar ring-1 ring-ouro-200 dark:bg-ouro-400/15 dark:text-ouro-200 dark:shadow-none dark:ring-ouro-400/30">
      <CalendarClock size={16} strokeWidth={2.2} aria-hidden className="text-ouro-700 dark:text-ouro-300" />
      {texto}
    </span>
  );
}

/** Aviso em faixa (nota, status) com ícone; o texto fica num único elemento. */
function Faixa({ papel, tom, icone: Icone, children }: {
  papel: "note" | "status"; tom: "alerta" | "info"; icone: LucideIcon; children: ReactNode;
}) {
  const estilo = tom === "alerta"
    ? "bg-amber-50 text-amber-900 ring-amber-200 dark:bg-amber-500/10 dark:text-amber-200 dark:ring-amber-500/25"
    : "bg-white text-zinc-700 ring-zinc-200 dark:bg-zinc-900 dark:text-zinc-200 dark:ring-zinc-800";
  return (
    <p role={papel} className={`mb-4 flex items-start gap-2.5 rounded-2xl px-4 py-3 text-sm ring-1 ${estilo}`}>
      <Icone size={16} aria-hidden className="mt-0.5 shrink-0" />
      <span>{children}</span>
    </p>
  );
}

/** Pódio vazio, com o motivo em texto (nunca um "0" no lugar). */
function PodioVazio({ texto }: { texto: string }) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center rounded-2xl border border-dashed border-zinc-200 px-4 py-8 text-center dark:border-zinc-700">
      <Trophy size={22} aria-hidden className="mb-2 text-zinc-400" />
      <p className="max-w-xs text-sm text-zinc-500 dark:text-zinc-400">{texto}</p>
    </div>
  );
}

/** Botão "Ver ranking completo" (secundário, com o nome da premiação no rótulo acessível). */
function BotaoRankingCompleto({ titulo, extra, aoClicar }: {
  titulo: string; extra?: string; aoClicar: () => void;
}) {
  return (
    <button
      type="button"
      onClick={aoClicar}
      /* São vários botões iguais na tela: o rótulo acessível diz de QUAL
         premiação é este, para quem navega por leitor de tela. */
      aria-label={`Ver ranking completo de ${titulo}`}
      className={`inline-flex items-center font-semibold transition-colors ${TAMANHOS_BOTAO.sm} ${ESTILOS_BOTAO.secundario}`}
    >
      Ver ranking completo{extra}
      <ChevronRight size={14} aria-hidden className="-mr-0.5 text-zinc-500" />
    </button>
  );
}

function BotaoCertificados({ titulo, aoClicar }: { titulo: string; aoClicar: () => void }) {
  return (
    <Botao
      variante="ambar"
      tamanho="sm"
      onClick={aoClicar}
      aria-label={`Certificados do pódio de ${titulo}`}
      aria-haspopup="dialog"
    >
      <Award size={14} aria-hidden />
      Certificados do pódio
    </Botao>
  );
}

/** Cabeçalho de um cartão de categoria: quadrado pastel + título (h3) + descrição.
 *  O título NÃO pode ficar dentro de outro `div.flex-col` (os testes sobem até o
 *  cartão por `closest("div.flex-col")`). */
function CabecalhoCartao({ visual, titulo, descricao, legenda }: {
  visual: VisualCategoria; titulo: string; descricao: string; legenda?: string;
}) {
  return (
    <div className="mb-4 flex items-start gap-3.5">
      <IconePastel icone={visual.icone} tom={visual.tom} tamanho="lg" />
      <div className="min-w-0 flex-1">
        <h3 className="text-base font-semibold leading-snug text-zinc-900 dark:text-white">{titulo}</h3>
        <p className="mt-0.5 text-sm text-zinc-500 dark:text-zinc-400">{descricao}</p>
        {legenda && <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">{legenda}</p>}
      </div>
    </div>
  );
}

function CartaoCategoria({ categoria, vazioTexto, legenda, aviso, aoVerRanking, aoGerarCertificados }: {
  categoria: CategoriaPremiacao; vazioTexto?: string; legenda?: string;
  /** Nota sob o pódio (ex.: por que o índice da Matemática não aparece). */
  aviso?: string;
  aoVerRanking?: () => void;
  /** Abre a emissão em lote com a lista desta categoria (ausente = quem não emite). */
  aoGerarCertificados?: () => void;
}) {
  const [campeao, ...resto] = categoria.podio;
  return (
    <Card className="flex h-full flex-col p-5 sm:p-6">
      <CabecalhoCartao
        visual={visualDa(categoria.chave)} titulo={categoria.titulo}
        descricao={categoria.descricao} legenda={legenda}
      />

      {!campeao ? (
        <PodioVazio texto={vazioTexto ?? "Sem dados no período."} />
      ) : (
        <>
          <Link
            to={`/alunos/${campeao.aluno_id}`}
            className="flex items-center gap-3.5 rounded-2xl bg-gradient-to-br from-ouro-50 via-ouro-50/70 to-white p-4 ring-1 ring-ouro-200/80 transition-shadow hover:shadow-cartao dark:from-ouro-400/15 dark:via-ouro-400/5 dark:to-transparent dark:ring-ouro-400/25"
          >
            <Medalha posicao={1} tamanho={34} />
            <Avatar nome={campeao.nome} chave={campeao.aluno_id} tamanho="lg" />
            <div className="min-w-0 flex-1">
              <p title={campeao.nome} className="truncate text-[15px] font-semibold text-zinc-900 dark:text-white">{campeao.nome}</p>
              {campeao.turma && (
                <Chip className="mt-1 bg-white/90 dark:bg-zinc-800">{campeao.turma}</Chip>
              )}
              <p className="mt-1.5 text-xl font-bold leading-tight tracking-tight tabular-nums text-zinc-900 dark:text-white">
                {quebravel(formatarValor(campeao.valor, categoria.unidade))}
              </p>
            </div>
          </Link>

          {resto.length > 0 && (
            <ul className="mt-2 space-y-0.5">
              {resto.map((item) => (
                <li key={item.aluno_id}>
                  <Link
                    to={`/alunos/${item.aluno_id}`}
                    className="flex items-center gap-3 rounded-xl px-2.5 py-2 text-sm transition-colors hover:bg-zinc-50 dark:hover:bg-zinc-800/60"
                  >
                    <span className="flex w-7 shrink-0 justify-center">
                      <MarcadorPosicao posicao={item.posicao} />
                    </span>
                    <Avatar nome={item.nome} chave={item.aluno_id} tamanho="sm" />
                    {/* Nome e turma empilhados: a turma não some em tela estreita. */}
                    <span className="min-w-0 flex-1">
                      <span title={item.nome} className="block truncate font-medium text-zinc-800 dark:text-zinc-100">{item.nome}</span>
                      {item.turma && (
                        <span className="block truncate text-xs text-zinc-500 dark:text-zinc-400" title={item.turma}>{item.turma}</span>
                      )}
                    </span>
                    <span className="max-w-[45%] shrink-0 text-right font-semibold tabular-nums text-zinc-700 dark:text-zinc-200">
                      {quebravel(formatarValor(item.valor, categoria.unidade))}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}

          {aviso && (
            <p role="note" className="mt-3 rounded-xl bg-zinc-50 px-3 py-2 text-xs text-zinc-600 dark:bg-zinc-800/60 dark:text-zinc-300">
              {aviso}
            </p>
          )}

          {/* O cartão é o Top 5; o ranking completo da MESMA premiação (mesma
              ordem, mesmas posições) abre sob demanda. */}
          {(aoVerRanking || aoGerarCertificados) && (
            <div className="mt-auto flex flex-wrap items-center gap-2 pt-4">
              {aoVerRanking && (
                <BotaoRankingCompleto
                  titulo={categoria.titulo}
                  extra={categoria.total != null && categoria.total > categoria.podio.length
                    ? ` (${categoria.total} alunos)` : undefined}
                  aoClicar={aoVerRanking}
                />
              )}
              {aoGerarCertificados && (
                <BotaoCertificados titulo={categoria.titulo} aoClicar={aoGerarCertificados} />
              )}
            </div>
          )}
        </>
      )}
    </Card>
  );
}

/** Esqueleto dos cartões enquanto as premiações carregam (sem texto falso). */
function EsqueletoCartoes({ quantos }: { quantos: number }) {
  return (
    <div aria-hidden className="grid grid-cols-1 gap-5 xl:grid-cols-2">
      {Array.from({ length: quantos }, (_, i) => (
        <Card key={i} className="p-5 sm:p-6">
          <div className="flex items-center gap-3.5">
            <Skeleton className="h-12 w-12 rounded-2xl" />
            <div className="flex-1 space-y-2">
              <Skeleton className="h-4 w-1/2" />
              <Skeleton className="h-3 w-3/4" />
            </div>
          </div>
          <Skeleton className="mt-5 h-[88px] w-full rounded-2xl" />
          <div className="mt-3 space-y-2">
            {[0, 1, 2].map((j) => <Skeleton key={j} className="h-9 w-full rounded-xl" />)}
          </div>
        </Card>
      ))}
    </div>
  );
}

/** Uma linha do ranking completo, PRONTA para exibir: a posição e o valor já
 *  vêm decididos por quem produziu a lista (backend). Esta camada não ordena,
 *  não filtra e não calcula nada. */
interface LinhaRanking {
  aluno_id: number;
  nome: string;
  turma: string | null;
  posicao: number;
  valor: string;
  destino: string;
}

/** A JANELA do ranking completo — só apresentação, compartilhada por todas as
 *  premiações (inclusive as de Evolução). Exibe as linhas na ORDEM recebida,
 *  com a posição que o ranking carimbou. O <h2> do Modal continua irmão direto
 *  da lista (os testes sobem do título até a caixa da janela). */
function ModalRanking({ titulo, visual, descricao, rodape, avisoLimite, linhas, total,
                        carregando, erro, erroParcial, temMais, aoCarregarMais,
                        aoTentarDeNovo, aoFechar, vazio }: {
  titulo: string; visual: VisualCategoria; descricao: string; rodape?: string;
  /** Aviso de que a janela mostra só o começo do ranking (teto do endpoint). */
  avisoLimite?: string;
  linhas: LinhaRanking[];
  /** Quantos alunos a premiação tem no recorte (quando o backend informa). */
  total?: number;
  carregando: boolean;
  /** Falha na PRIMEIRA carga: não há nada na tela para preservar. */
  erro: boolean;
  /** Falha ao carregar MAIS: o que já está na tela continua valendo. */
  erroParcial?: boolean;
  temMais: boolean;
  aoCarregarMais: () => void; aoTentarDeNovo?: () => void;
  aoFechar: () => void; vazio: string;
}) {
  return (
    <Modal titulo={titulo} aberto aoFechar={aoFechar} largura="max-w-xl">
      <div className="-mt-1 mb-4 flex items-center gap-3">
        <IconePastel icone={visual.icone} tom={visual.tom} tamanho="sm" />
        <p className="text-sm text-zinc-500 dark:text-zinc-400">
          {descricao}
          {total != null && <> · {total} {total === 1 ? "aluno" : "alunos"} no período</>}
        </p>
      </div>
      {carregando && linhas.length === 0 ? (
        <Carregando />
      ) : erro ? (
        <div role="alert" className="flex flex-col items-center py-8 text-center">
          <span aria-hidden className="mb-3 grid h-12 w-12 place-items-center rounded-full bg-rose-50 text-rose-500 dark:bg-rose-500/15 dark:text-rose-300">
            <AlertTriangle size={22} />
          </span>
          <p className="text-sm font-medium text-zinc-700 dark:text-zinc-200">Não foi possível carregar o ranking.</p>
          {aoTentarDeNovo && (
            <Botao variante="secundario" tamanho="sm" className="mt-3" onClick={aoTentarDeNovo} disabled={carregando}>
              {carregando ? "Carregando..." : "Tentar de novo"}
            </Botao>
          )}
        </div>
      ) : linhas.length === 0 ? (
        <PodioVazio texto={vazio} />
      ) : (
        <>
          <ol className="-mx-2 space-y-0.5">
            {linhas.map((item) => (
              <li key={item.aluno_id}>
                <Link
                  to={item.destino}
                  className="flex items-center gap-3 rounded-xl px-2 py-2 text-sm transition-colors hover:bg-zinc-50 dark:hover:bg-zinc-800/60"
                >
                  <span className="flex w-8 shrink-0 justify-center">
                    <MarcadorPosicao posicao={item.posicao} />
                  </span>
                  <Avatar nome={item.nome} chave={item.aluno_id} tamanho="sm" />
                  {/* Nome e turma empilhados: em tela estreita nada transborda. */}
                  <span className="min-w-0 flex-1">
                    <span title={item.nome} className="block truncate font-medium text-zinc-800 dark:text-zinc-100">{item.nome}</span>
                    {item.turma && (
                      <span className="block truncate text-xs text-zinc-500 dark:text-zinc-400" title={item.turma}>{item.turma}</span>
                    )}
                  </span>
                  <span className="shrink-0 font-semibold tabular-nums text-zinc-700 dark:text-zinc-200">
                    {item.valor}
                  </span>
                </Link>
              </li>
            ))}
          </ol>
          {/* Falhou ao buscar MAIS posições: o que o usuário já estava lendo fica
              na tela; só o lote novo é que não veio. "Tentar de novo" repete o
              MESMO pedido (mesmo limite), então nada é pulado nem duplicado. */}
          {erroParcial ? (
            <div role="alert" className="mt-4 flex flex-wrap items-center gap-2 rounded-xl bg-amber-50 px-3.5 py-2.5 text-sm text-amber-900 ring-1 ring-amber-200 dark:bg-amber-500/10 dark:text-amber-200 dark:ring-amber-500/25">
              <AlertTriangle size={15} aria-hidden className="shrink-0" />
              Não foi possível carregar mais posições.
              {aoTentarDeNovo && (
                <button type="button" onClick={aoTentarDeNovo} disabled={carregando}
                        className="ml-1 font-semibold underline underline-offset-2 disabled:opacity-60">
                  {carregando ? "Carregando..." : "Tentar de novo"}
                </button>
              )}
            </div>
          ) : temMais && (
            <Botao variante="secundario" className="mt-4 w-full" disabled={carregando} onClick={aoCarregarMais}>
              {carregando ? "Carregando..." : "Carregar mais"}
            </Botao>
          )}
          {/* Teto do endpoint: a lista para antes do fim e a janela DIZ isso —
              o total real continua no cabeçalho, sem fingir que acabou. */}
          {avisoLimite && (
            <p role="note" className="mt-3 text-xs font-medium text-amber-800 dark:text-amber-300">{avisoLimite}</p>
          )}
          {rodape && <p className="mt-3 text-xs text-zinc-500 dark:text-zinc-400">{rodape}</p>}
        </>
      )}
    </Modal>
  );
}

/** Ranking COMPLETO de uma premiação: a MESMA resposta da aba, pedida com um
 *  `limite` maior. Nada é reordenado aqui — a posição exibida é a que o backend
 *  carimbou, e "Carregar mais" só aumenta o limite (a lista nova contém a
 *  anterior, então nenhum aluno é pulado nem repetido). */
function ModalRankingCompleto({ categoria, urlBase, turnoChave, regua, aoFechar }: {
  categoria: CategoriaPremiacao;
  urlBase: string;
  /** Turno em exibição na aba (ou null em "Todos"): o ranking respeita o MESMO
   *  recorte de período, turma e turno já aplicado na tela. */
  turnoChave: string | null;
  /** Régua da Matemática da aba, até a resposta maior chegar com a dela. */
  regua?: ReguaMatematica;
  aoFechar: () => void;
}) {
  const [limite, setLimite] = useState(PASSO_RANKING);
  // Já chegou alguma resposta PARA ESTA janela? É o que separa "falhou a
  // primeira carga" (nada a preservar) de "falhou o lote novo" (o que está na
  // tela continua válido). Não dá para deduzir de `dados`, porque a janela abre
  // já mostrando o pódio que o cartão tinha.
  const [houveResposta, setHouveResposta] = useState(false);
  const { dados, erro, carregando, recarregar } = useApi<RespostaPremiacoes>(
    `${urlBase}&limite=${limite}`, { aoSucesso: () => setHouveResposta(true) });
  // Turno em exibição: `null` é "sem filtro" e a string VAZIA é o turno
  // "Sem turno" (turmas com `Turma.turno` nulo). Testar por veracidade
  // confundiria os dois e a janela mostraria a escola inteira.
  const lista = (turnoChave != null
    ? dados?.turnos?.find((g) => chaveTurno(g.turno) === turnoChave)?.categorias
    : dados?.categorias) ?? [];
  // Enquanto a resposta maior não chega, mostra o que o cartão já tinha.
  const completa = lista.find((c) => c.chave === categoria.chave) ?? categoria;
  const podio = completa.podio;
  const total = completa.total;
  // A janela não alcança além do teto da rota: quando a premiação tem mais que
  // isso, ela mostra o começo do ranking e DIZ que é só o começo.
  const truncado = total != null && total > LIMITE_MAXIMO_RANKING;

  return (
    <ModalRanking
      titulo={categoria.titulo} visual={visualDa(categoria.chave)} descricao={categoria.descricao}
      avisoLimite={truncado
        ? `Esta janela mostra as ${LIMITE_MAXIMO_RANKING} primeiras posições.`
        : undefined}
      /* Índice oculto pelo backend: o ranking completo diz o MESMO motivo do cartão. */
      rodape={temValorOculto(completa)
        ? notaIndiceOculto(dados?.regua_matematica ?? regua)
        : undefined}
      linhas={podio.map((item) => ({
        aluno_id: item.aluno_id, nome: item.nome, turma: item.turma, posicao: item.posicao,
        valor: formatarValor(item.valor, categoria.unidade),
        destino: `/alunos/${item.aluno_id}`,
      }))}
      total={total}
      carregando={carregando}
      erro={Boolean(erro) && !houveResposta}
      erroParcial={Boolean(erro) && houveResposta}
      /* Há mais ranking a pedir — e o backend ainda aceita o próximo lote. */
      temMais={(total != null ? podio.length < total : podio.length >= limite)
               && limite < LIMITE_MAXIMO_RANKING}
      aoCarregarMais={() => setLimite((atual) =>
        Math.min(atual + PASSO_RANKING, LIMITE_MAXIMO_RANKING))}
      /* Repete o MESMO pedido (mesmo limite): a lista volta inteira, do 1º ao
         último já pedido, sem pular nem duplicar ninguém. */
      aoTentarDeNovo={recarregar}
      aoFechar={aoFechar}
      vazio="Sem dados no período."
    />
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

/** Pódio de EVOLUÇÃO: só quem cresceu (nota > 0) — o zero legítimo de quem usa a
 *  plataforma e não avançou fica na lista da API, não no pódio. Decisão de
 *  produto registrada, aplicada UMA vez: o Top 5 do cartão e o ranking completo
 *  leem desta mesma lista, na ordem e com a posição que o backend carimbou. */
function cresceram(itens: EvolucaoItem[] | null | undefined): EvolucaoItem[] {
  return (itens ?? []).filter((item) => (item.nota ?? 0) > 0);
}

const DESCRICAO_EVOLUCAO = "Quem mais CRESCEU no período (não o maior acumulado)";

function CartaoEvolucao({ escolaId, dimensao, titulo, params, vazio, aoGerarCertificados }: {
  escolaId: number; dimensao: "leitura" | "matematica";
  titulo: string; params: string; vazio: string;
  /** Abre a emissão em lote com o Top 5 deste cartão (ausente = quem não emite). */
  aoGerarCertificados?: (alunos: AlunoParaCertificado[]) => void;
}) {
  // `params` traz o MESMO período e turno das premiações (o filtro é lockado).
  const { dados, erro, carregando, recarregar } = useApi<EvolucaoItem[]>(
    `/escolas/${escolaId}/ranking-evolucao?dimensao=${dimensao}${params}`,
  );
  const [rankingAberto, setRankingAberto] = useState(false);
  const elegiveis = cresceram(dados);
  const podio = elegiveis.slice(0, 5);
  const [campeao, ...resto] = podio;
  return (
    <Card className="flex h-full flex-col p-5 sm:p-6">
      <CabecalhoCartao visual={VISUAL_EVOLUCAO} titulo={titulo} descricao={DESCRICAO_EVOLUCAO} />
      {carregando ? (
        <div aria-hidden className="space-y-2">
          <Skeleton className="h-[76px] w-full rounded-2xl" />
          <Skeleton className="h-9 w-full rounded-xl" />
          <Skeleton className="h-9 w-full rounded-xl" />
        </div>
      ) : erro ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-2 rounded-2xl border border-dashed border-rose-200 px-4 py-6 text-center dark:border-rose-500/30">
          <p className="text-sm text-zinc-600 dark:text-zinc-300">Não foi possível carregar.</p>
          <Botao variante="secundario" tamanho="sm" onClick={recarregar}>Tentar de novo</Botao>
        </div>
      ) : !campeao ? (
        <PodioVazio texto={vazio} />
      ) : (
        <>
          <Link
            to={`/alunos/${campeao.aluno_id}/evolucao`}
            className="flex items-center gap-3.5 rounded-2xl bg-gradient-to-br from-emerald-50 via-teal-50/60 to-white p-4 ring-1 ring-emerald-200/80 transition-shadow hover:shadow-cartao dark:from-emerald-500/15 dark:via-teal-500/5 dark:to-transparent dark:ring-emerald-500/25"
          >
            <Medalha posicao={1} tamanho={34} />
            <Avatar nome={campeao.nome} chave={campeao.aluno_id} tamanho="lg" />
            <div className="min-w-0 flex-1">
              <p title={campeao.nome} className="truncate text-[15px] font-semibold text-zinc-900 dark:text-white">{campeao.nome}</p>
              {campeao.turma && <Chip className="mt-1 bg-white/90 dark:bg-zinc-800">{campeao.turma}</Chip>}
              <p className="mt-1.5">
                <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100/80 px-2.5 py-1 text-sm font-bold tabular-nums text-emerald-800 dark:bg-emerald-500/20 dark:text-emerald-200">
                  <TrendingUp size={14} aria-hidden /> {fmtNota(campeao.nota ?? 0)}
                </span>
              </p>
            </div>
          </Link>
          {resto.length > 0 && (
            <ul className="mt-2 space-y-0.5">
              {resto.map((item) => (
                <li key={item.aluno_id}>
                  <Link to={`/alunos/${item.aluno_id}/evolucao`}
                        className="flex items-center gap-3 rounded-xl px-2.5 py-2 text-sm transition-colors hover:bg-zinc-50 dark:hover:bg-zinc-800/60">
                    <span className="flex w-7 shrink-0 justify-center">
                      <MarcadorPosicao posicao={item.posicao} />
                    </span>
                    <Avatar nome={item.nome} chave={item.aluno_id} tamanho="sm" />
                    <span className="min-w-0 flex-1">
                      <span title={item.nome} className="block truncate font-medium text-zinc-800 dark:text-zinc-100">{item.nome}</span>
                      {item.turma && (
                        <span className="block truncate text-xs text-zinc-500 dark:text-zinc-400" title={item.turma}>{item.turma}</span>
                      )}
                    </span>
                    <span className="inline-flex shrink-0 items-center gap-1 font-semibold tabular-nums text-emerald-700 dark:text-emerald-300">
                      <TrendingUp size={13} aria-hidden /> {fmtNota(item.nota ?? 0)}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}

          {/* Mesma experiência das demais premiações: o cartão é o Top 5, o
              ranking completo abre sob demanda. A lista já veio inteira do
              endpoint de evolução — nenhuma consulta nova, nenhuma reordenação. */}
          <div className="mt-auto flex flex-wrap items-center gap-2 pt-4">
            <BotaoRankingCompleto
              titulo={titulo}
              extra={elegiveis.length > podio.length ? ` (${elegiveis.length} alunos)` : undefined}
              aoClicar={() => setRankingAberto(true)}
            />
            {aoGerarCertificados && (
              <BotaoCertificados
                titulo={titulo}
                aoClicar={() => aoGerarCertificados(podio.map((item) => ({
                  aluno_id: item.aluno_id, nome: item.nome, turma: item.turma, posicao: item.posicao,
                })))}
              />
            )}
          </div>
        </>
      )}

      {rankingAberto && (
        <ModalRankingEvolucao
          itens={elegiveis} titulo={titulo}
          aoFechar={() => setRankingAberto(false)} />
      )}
    </Card>
  );
}

/** Ranking COMPLETO de uma premiação de EVOLUÇÃO. O endpoint por dimensão já
 *  devolve a lista inteira, ordenada e com a posição de cada aluno carimbada
 *  pelo motor: aqui só se mostra mais linhas da MESMA lista que o cartão usou
 *  (nenhuma consulta nova, nenhum cálculo, nenhuma reordenação). */
function ModalRankingEvolucao({ itens, titulo, aoFechar }: {
  itens: EvolucaoItem[]; titulo: string; aoFechar: () => void;
}) {
  const [limite, setLimite] = useState(PASSO_RANKING);
  const linhas = itens.slice(0, limite);
  return (
    <ModalRanking
      titulo={titulo} visual={VISUAL_EVOLUCAO}
      descricao={DESCRICAO_EVOLUCAO}
      rodape="Só entra quem cresceu no intervalo; o crescimento e a posição vêm do motor de evolução."
      linhas={linhas.map((item) => ({
        aluno_id: item.aluno_id, nome: item.nome, turma: item.turma, posicao: item.posicao,
        valor: fmtNota(item.nota ?? 0),
        destino: `/alunos/${item.aluno_id}/evolucao`,
      }))}
      total={itens.length}
      carregando={false}
      erro={false}
      temMais={linhas.length < itens.length}
      aoCarregarMais={() => setLimite((atual) => atual + PASSO_RANKING)}
      aoFechar={aoFechar}
      vazio="Sem dados suficientes para medir evolução no período."
    />
  );
}

/** Título de seção (h2) com uma linha de apoio. */
function TituloSecao({ titulo, children }: { titulo: string; children?: ReactNode }) {
  return (
    <div className="mb-4">
      <h2 className="text-lg font-bold tracking-tight text-zinc-900 dark:text-white">{titulo}</h2>
      {children && <p className="mt-0.5 text-sm text-zinc-500 dark:text-zinc-400">{children}</p>}
    </div>
  );
}

export default function Premiacoes() {
  const { escolaId, periodo, definirPeriodo, turno, definirTurno } = useApp();
  // Módulo fora do plano: o cartão de evolução dele some (o servidor recusa).
  const modulos = useModulos();
  // Certificados: a rota já barra a Secretaria (RotaSemSecretaria); o botão some
  // também aqui, para nenhum caminho oferecer o que o backend recusa.
  const { secretaria, gestor } = usePerfil();
  const podeEmitir = !secretaria && escolaId != null;
  // Quem só vê as próprias turmas (o professor: a mesma regra de
  // `permissoes.turmas_permitidas` — nem global, nem admin/coordenação, nem Secretaria).
  const soSuasTurmas = !gestor && !secretaria;
  const [turmaId, setTurmaId] = useState("");
  // Premiação cujo ranking completo está aberto (null = só os cartões).
  const [rankingAberto, setRankingAberto] = useState<CategoriaPremiacao | null>(null);
  // Emissão em lote aberta (lista da categoria + modelo + contexto).
  const [certificados, setCertificados] = useState<PedidoCertificados | null>(null);
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
  const { dados: ultimaResposta, erro, carregando, recarregar } = useApi<RespostaPremiacoes>(urlPremiacoes, {
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
  // De que ano são as crianças e as turmas dos pódios: num período de um ano já
  // encerrado, as daquele ano; num período que passa por dois anos, as de agora. A
  // turma escolhida e as turmas do professor são as de agora (só quem está nelas HOJE
  // aparece): a frase diz isso, a mesma do Relatório por Período.
  const avisoAno = avisoPopulacao(dados?.populacao,
                                  turmaId ? "turma" : soSuasTurmas ? "suas_turmas" : undefined);

  // Chip do cabeçalho: só quando o período escolhido É o bimestre em curso
  // ("Este bimestre" ou o número dele), pelo calendário oficial (o do backend), e o
  // período que o backend respondeu para este pódio contém hoje — o número sozinho não
  // basta: na virada, o "1º bimestre" da escola ainda em 2026 é o de 2026, encerrado.
  const calendario = useCalendarioBimestres(escolaId);
  const bimestre = bimestreEmCurso(new Date(), calendario);
  const ehBimestreEmCurso = bimestre != null && dados != null
    && (periodo.preset === "bimestre" || periodo.preset === `bimestre_${bimestre.numero}`)
    && periodoContemHoje(dados.periodo, new Date());

  // De onde sai o Top N do lote (D7): a premiação, o período e o recorte da tela.
  const nomeTurma = turmaId ? (turmas ?? []).find((t) => String(t.id) === turmaId)?.nome : undefined;
  const recorte = nomeTurma ? ` · ${nomeTurma}` : grupoTurno ? ` · ${grupoTurno.turno_rotulo}` : "";
  const contextoDe = (titulo: string) =>
    `Premiações · ${titulo}${dados ? ` · ${dados.periodo.rotulo}` : ""}${recorte}`;

  return (
    <div>
      <PageHeader
        titulo="Premiações"
        descricao="Vencedores calculados apenas com os dados do período escolhido — por semana, mês, bimestre ou datas personalizadas."
        acoes={ehBimestreEmCurso && bimestre
          ? <ChipFimDoBimestre numero={bimestre.numero} dias={bimestre.diasParaOFim} />
          : undefined}
      />

      <Card className="mb-6 flex flex-wrap items-center gap-3 p-3 sm:p-4">
        <SeletorPeriodo valor={periodo} onChange={definirPeriodo} />
        <MolduraPilula icone={Users}>
          <select
            aria-label="Filtrar por turma"
            className={estiloSelectPilula}
            value={turmaId}
            onChange={(e) => setTurmaId(e.target.value)}
          >
            <option value="">Todas as turmas</option>
            {(turmas ?? []).map((t) => <option key={t.id} value={t.id}>{t.nome}</option>)}
          </select>
        </MolduraPilula>
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
          <span className="ml-auto inline-flex items-center gap-1.5 rounded-full bg-indigo-50 px-3 py-1.5 text-sm font-semibold text-indigo-700 dark:bg-indigo-500/15 dark:text-indigo-200">
            <Trophy size={15} aria-hidden /> {dados.periodo.rotulo}
            {grupoTurno && <> · {grupoTurno.turno_rotulo} ({grupoTurno.total})</>}
          </span>
        )}
      </Card>

      {/* Data do dado: o backend já manda o bloco na resposta (sem pedido a
          mais); só as dimensões contratadas aparecem. */}
      {dados && <SeloFrescor frescor={dados.frescor} dimensoes={["leitura", "matematica"]} />}

      {avisoAno && (
        <Faixa papel="note" tom={dados?.populacao?.origem === "atravessa_anos" ? "alerta" : "info"}
               icone={CalendarClock}>
          {avisoAno}
        </Faixa>
      )}

      {avisoJanela && (
        <Faixa papel="note" tom="alerta" icone={AlertTriangle}>
          O período mostrado não é o intervalo usado na Matemática. {avisoJanela}.
        </Faixa>
      )}

      {turnoSemRecorte && (
        <Faixa papel="status" tom="alerta" icone={Info}>
          Nenhum aluno matriculado no turno {rotuloTurno(turnoAtivo)} neste ano letivo; mostrando todos os turnos.
        </Faixa>
      )}

      {aguardando ? (
        <>
          <p role="status" className="sr-only">Carregando as premiações…</p>
          <EsqueletoCartoes quantos={4} />
        </>
      ) : erro ? (
        <Card className="p-6">
          <Erro titulo="Não foi possível carregar as premiações" descricao={erro.message} aoTentar={recarregar} />
        </Card>
      ) : !dados ? (
        <Card className="p-6">
          <Erro titulo="Não foi possível carregar as premiações" aoTentar={recarregar} />
        </Card>
      ) : (
        <>
          <TituloSecao titulo="Pódios do período">
            Top 5 de cada categoria, na ordem calculada pelo sistema.
          </TituloSecao>
          {grupoTurno && (
            <p className="-mt-2 mb-4 flex items-start gap-2 text-sm text-zinc-500 dark:text-zinc-400">
              <Clock size={15} aria-hidden className="mt-0.5 shrink-0 text-indigo-600 dark:text-indigo-300" />
              <span>Vencedores calculados só com os alunos do turno selecionado; a régua da Matemática é a da escola inteira.</span>
            </p>
          )}
          <div className="grid grid-cols-1 gap-5 xl:grid-cols-2">
            {categorias.map((categoria) => (
              <CartaoCategoria
                key={categoria.chave} categoria={categoria}
                vazioTexto={categoria.chave === "melhor_matematica"
                  ? textoVazioMatematica(regua)
                  : undefined}
                legenda={categoria.chave === "melhor_matematica"
                  ? "Média ajustada de estrelas por atividade no período (0 a 5)"
                  : undefined}
                aviso={temValorOculto(categoria) ? notaIndiceOculto(regua) : undefined}
                aoVerRanking={() => setRankingAberto(categoria)}
                aoGerarCertificados={podeEmitir
                  ? () => setCertificados({
                      alunos: categoria.podio.map((item) => ({
                        aluno_id: item.aluno_id, nome: item.nome, turma: item.turma, posicao: item.posicao,
                      })),
                      modelo: MODELO_DA_CATEGORIA[categoria.chave] ?? null,
                      contexto: contextoDe(categoria.titulo),
                    })
                  : undefined}
              />
            ))}
          </div>

          {/* MELHOR EVOLUÇÃO — quem mais cresceu no período (mesmo período +
              turma + turno dos pódios acima). */}
          <div className="mt-10">
            <TituloSecao titulo="Melhor Evolução no período">
              Quem mais cresceu dentro do intervalo, com o mesmo período, turma e turno dos pódios.
            </TituloSecao>
          </div>
          {escolaId && (
            <div className="grid grid-cols-1 gap-5 xl:grid-cols-2">
              {modulos.leitura && (
                <CartaoEvolucao
                  escolaId={escolaId} dimensao="leitura" params={paramsEvol}
                  titulo="Melhor Evolução — Leitura"
                  vazio="Sem dados suficientes para medir evolução de leitura no período."
                  aoGerarCertificados={podeEmitir
                    ? (alunos) => setCertificados({
                        alunos, modelo: "elefante", contexto: contextoDe("Melhor Evolução — Leitura"),
                      })
                    : undefined} />
              )}
              {modulos.matematica && (
                <CartaoEvolucao
                  escolaId={escolaId} dimensao="matematica" params={paramsEvol}
                  titulo="Melhor Evolução — Matemática"
                  vazio="Sem dados suficientes no período para medir evolução de Matemática."
                  aoGerarCertificados={podeEmitir
                    ? (alunos) => setCertificados({
                        alunos, modelo: "matific", contexto: contextoDe("Melhor Evolução — Matemática"),
                      })
                    : undefined} />
              )}
            </div>
          )}
        </>
      )}

      {/* "Como funciona": a fórmula e o recorte por ano letivo continuam na tela,
          recolhidos (nada foi apagado). */}
      {modulos.matematica && (
        <SecaoRecolhivel
          className="mt-10"
          inicialAberto={false}
          titulo="Como as premiações são calculadas"
          icone={<IconePastel icone={Info} tom="neutro" tamanho="sm" />}
        >
          <p className="flex items-start gap-2 text-sm text-zinc-600 dark:text-zinc-300">
            <Award size={15} aria-hidden className="mt-0.5 shrink-0 text-ouro-600" />
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
        </SecaoRecolhivel>
      )}

      {/* Ranking completo: MESMA URL da aba (período, turma e turno já
          aplicados), só com um limite maior.

          `key` pela CHAVE DA PREMIAÇÃO: trocar de premiação com a janela aberta
          remonta o componente, e o ranking novo começa na posição 1 — sem
          herdar o limite, as linhas nem o erro da premiação anterior. Os
          filtros da tela (período, turma, turno) continuam valendo, porque
          vêm de fora. */}
      {rankingAberto && urlPremiacoes && (
        <ModalRankingCompleto
          key={rankingAberto.chave}
          categoria={rankingAberto}
          urlBase={urlPremiacoes}
          turnoChave={grupoTurno ? chaveTurno(grupoTurno.turno) : null}
          regua={regua}
          aoFechar={() => setRankingAberto(null)}
        />
      )}

      {/* Emissão em lote: o Top N sai da lista da categoria, na ordem da tela;
          as guardas por aluno são as do backend (recusado não é substituído). */}
      <GerarCertificados
        escolaId={escolaId}
        alunos={certificados?.alunos ?? []}
        modeloInicial={certificados?.modelo ?? null}
        contexto={certificados?.contexto ?? ""}
        // Período de um bimestre (ex.: "3º bimestre" já fechado): o seletor do bimestre
        // impresso abre nele, não no bimestre de hoje.
        bimestreInicial={bimestreDoPeriodo(periodo.preset, new Date(), calendario)}
        aberto={certificados != null}
        aoFechar={() => setCertificados(null)}
      />
    </div>
  );
}
