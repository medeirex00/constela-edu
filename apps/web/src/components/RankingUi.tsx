/**
 * Peças visuais das telas de RANKING na identidade visual v2
 * (docs/design/IDENTIDADE-VISUAL-V2.md, referência "Ranking"): posição em pílula,
 * aluno com avatar, barra de filtros em cartão, cabeçalho de cartão com "Como
 * funciona", seção secundária recolhível, abas com id (para o tabpanel), ações do
 * cabeçalho (Exportar lista + Gerar certificados) e o subtítulo com o período e a
 * data do dado.
 *
 * Só apresentação: nada aqui decide permissão, filtra, ordena ou calcula nota. A
 * ordem e a posição são sempre as da API; os números chegam formatados pela tela.
 */
import { useEffect, useId, useRef, useState } from "react";
import type { KeyboardEvent as ReactKeyboardEvent, ReactNode } from "react";
import { createPortal } from "react-dom";
import { Link } from "react-router-dom";
import { Award, ChevronDown, FileDown, HelpCircle, SlidersHorizontal } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { paraData } from "@constela/core";

import { useApp } from "../context/AppContext";
import { useApi } from "../hooks/useApi";
import { usePerfil } from "../hooks/usePerfil";
import { bimestreEmCurso } from "../lib/calendarioBimestres";
import { baixarCsv, type TabelaCsv } from "../lib/csvRanking";
import type { AlunoParaCertificado, ModeloCertificado } from "../lib/tiposCertificados";
import type { Dimensao } from "../lib/types";
import { GerarCertificados } from "./GerarCertificados";
import { PodioRanking, type ItemPodio } from "./PodioRanking";
import { PRESETS_PERIODO, type Periodo } from "./SeletorPeriodo";
import type { Frescor } from "./SeloFrescor";
import { Avatar, Botao, IconePastel, Skeleton, type TomPastel } from "./ui";

// ── Posição e aluno na tabela ──────────────────────────────────────────────

const COR_POSICAO: Record<number, string> = {
  1: "bg-medalha-ouro text-[#5B3B00]",
  2: "bg-medalha-prata text-[#2B3350]",
  3: "bg-medalha-bronze text-[#4A2306]",
};

/** Posição em pílula ("1º" ouro, "2º" prata, "3º" bronze, demais neutro). O número
 *  vai em texto (não depende da cor). */
export function PosicaoRanking({ posicao }: { posicao: number }) {
  const cor = COR_POSICAO[posicao] ?? "bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300";
  return (
    <span
      className={`inline-flex h-7 min-w-7 items-center justify-center rounded-full px-1.5 text-xs font-bold tabular-nums ${cor}`}
    >
      {posicao}º
    </span>
  );
}

/** Avatar (decorativo, FORA do link) + nome; o nome é o link para a ficha quando há.
 *  No celular (< 640 px) a célula guarda ~10 rem: a tabela rola de lado e, sem isso,
 *  o nome era espremido em uma palavra por linha ("Otávio / Fernandes / Cruz"). */
export function CelulaAluno({
  nome,
  href,
  chave,
}: {
  nome: string;
  href?: string | null;
  chave?: string | number | null;
}) {
  return (
    <span className="flex min-w-0 items-center gap-3 max-sm:min-w-[10.5rem]">
      <Avatar nome={nome} chave={chave ?? nome} tamanho="sm" />
      {href ? (
        <Link
          to={href}
          className="min-w-0 break-words font-semibold text-zinc-900 hover:text-indigo-700 hover:underline dark:text-zinc-100 dark:hover:text-indigo-300"
        >
          {nome}
        </Link>
      ) : (
        <span className="min-w-0 break-words font-semibold text-zinc-900 dark:text-zinc-100">{nome}</span>
      )}
    </span>
  );
}

/**
 * Classes das células da tabela de ranking (padrão `classesTabela`, com alinhamento).
 * A moldura é a `TabelaRolavel` (rola de lado dentro do cartão e avisa em texto).
 *
 * Celular (< 640 px): a tabela perde a largura mínima (fica do tamanho do conteúdo),
 * as células ficam com 12 px de respiro e a coluna da NOTA QUE ORDENA (`thPresa`/
 * `tdPresa`) fica presa à direita — posição, aluno e nota aparecem em toda linha sem
 * rolar; as demais colunas continuam a um deslize. No desktop nada muda.
 */
export const tabelaRanking = {
  tabela: "w-full text-sm tabular-nums sm:min-w-[600px]",
  thead: "border-y border-zinc-100 bg-zinc-50/70 dark:border-zinc-800 dark:bg-zinc-800/30",
  th: "whitespace-nowrap px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-[0.08em] text-zinc-500 max-sm:px-3 dark:text-zinc-400",
  thNum: "whitespace-nowrap px-4 py-3 text-right text-[11px] font-semibold uppercase tracking-[0.08em] text-zinc-500 max-sm:px-3 dark:text-zinc-400",
  /** Cabeçalho da coluna presa: `presa-celular` (index.css) + o fundo OPACO do <thead>
   *  (zinc-50/70 e zinc-800/30 já compostos sobre o cartão), para a faixa não mudar
   *  de cor na coluna presa. */
  thPresa: "presa-celular max-sm:bg-[#f8f9fc] dark:max-sm:bg-[#1f213e]",
  tdPresa: "presa-celular",
  /** Cabeçalho LONGO da coluna presa ("Nota de Matemática"): no celular quebra em duas
   *  linhas ("Nota de / Matemática"), não numa palavra por linha, para a coluna presa
   *  não cobrir o nome do aluno. */
  thQuebraCelular: "max-sm:min-w-[5.75rem] max-sm:whitespace-normal",
  tr: "border-t border-zinc-100 transition-colors first:border-t-0 hover:bg-zinc-50/80 dark:border-zinc-800 dark:hover:bg-zinc-800/40",
  td: "px-4 py-3 text-zinc-700 max-sm:px-3 dark:text-zinc-200",
  /** Célula de rótulo curto (chip da turma, série, turno): numa linha só. Sem isso,
   *  em tela estreita a tabela espremia o chip em "2º / Ano / A". */
  tdCurto: "whitespace-nowrap px-4 py-3 text-zinc-700 max-sm:px-3 dark:text-zinc-200",
  tdNum: "px-4 py-3 text-right text-zinc-700 max-sm:px-3 dark:text-zinc-200",
  tdForte: "px-4 py-3 text-right text-[15px] font-bold text-zinc-900 max-sm:px-3 dark:text-white",
} as const;

/**
 * Ações do cabeçalho da PÁGINA no celular (< 640 px): uma coluna de botões da mesma
 * largura, em vez de botões soltos de larguras diferentes. Vai no contêiner dos botões
 * (a caixa de ações do `PageHeader` já ocupa a linha toda no celular). A marca
 * `acoes-celular` não tem estilo próprio: só identifica o contêiner. No desktop nada muda.
 */
export const ACOES_CELULAR = "acoes-celular max-sm:grid max-sm:w-full max-sm:grid-cols-1 max-sm:[&>*]:w-full";

/**
 * Abas no celular (< 640 px), em vez de quebrarem em linhas desalinhadas:
 * `grade` = duas colunas iguais (a última, se sobrar sozinha, ocupa a linha);
 * `linha` = uma linha só de colunas iguais (2 ou 3 abas curtas).
 */
export const ABAS_CELULAR = {
  grade: "max-sm:grid max-sm:w-full max-sm:grid-cols-2 max-sm:[&>*:last-child:nth-child(odd)]:col-span-2",
  linha: "max-sm:grid max-sm:w-full max-sm:auto-cols-fr max-sm:grid-flow-col",
} as const;

/** Faixa do pódio dentro do cartão do ranking (some quando não há pódio). */
export function FaixaPodio({ itens, rotulo }: { itens: ItemPodio[]; rotulo?: string }) {
  if (itens.length === 0) return null;
  return (
    <div className="border-t border-zinc-100 bg-gradient-to-b from-indigo-50/70 to-white px-4 pb-6 pt-5 sm:px-6 dark:border-zinc-800 dark:from-indigo-500/5 dark:to-zinc-900">
      <PodioRanking itens={itens} rotulo={rotulo} />
    </div>
  );
}

/** Esqueleto do cartão de ranking enquanto a lista carrega (pódio + linhas). */
export function EsqueletoRanking({ linhas = 6, podio = true }: { linhas?: number; podio?: boolean }) {
  return (
    <div aria-busy="true" className="border-t border-zinc-100 px-5 pb-6 pt-5 dark:border-zinc-800">
      <span className="sr-only">Carregando a lista…</span>
      {podio && (
        <div className="mb-6 grid grid-cols-1 gap-4 md:grid-cols-3 md:items-end">
          <Skeleton className="h-48 rounded-cartao md:order-1" />
          <Skeleton className="h-56 rounded-cartao md:order-2" />
          <Skeleton className="h-44 rounded-cartao md:order-3" />
        </div>
      )}
      <div className="space-y-3">
        {Array.from({ length: linhas }, (_, i) => (
          <div key={i} className="flex items-center gap-3">
            <Skeleton className="h-7 w-7 rounded-full" />
            <Skeleton className="h-8 w-8 rounded-full" />
            <Skeleton className="h-4 flex-1" />
            <Skeleton className="h-4 w-16" />
          </div>
        ))}
      </div>
    </div>
  );
}

/** "Mostrar mais N aluno(s)" do janelamento (useJanela), centralizado sob a tabela. */
export function MostrarMais({ restantes, aoMostrar, rotulo }: { restantes: number; aoMostrar: () => void; rotulo: string }) {
  if (restantes <= 0) return null;
  return (
    <div className="border-t border-zinc-100 p-3 text-center dark:border-zinc-800">
      <button
        type="button"
        onClick={aoMostrar}
        className="rounded-xl px-3 py-1.5 text-sm font-semibold max-sm:min-h-10 text-indigo-700 transition-colors hover:bg-indigo-50 dark:text-indigo-300 dark:hover:bg-indigo-500/10"
      >
        {rotulo}
      </button>
    </div>
  );
}

// ── Filtros e cabeçalhos ───────────────────────────────────────────────────

/** Barra-cartão compacta com os filtros (selects nativos em pílula). No celular
 *  (< 640 px) os filtros ficam um por linha, todos com a largura do cartão (antes cada
 *  pílula tinha a largura do próprio texto). */
export function BarraFiltrosRanking({ children, extra }: { children: ReactNode; extra?: ReactNode }) {
  return (
    <div className="card mb-4 flex flex-wrap items-center gap-2.5 p-3 sm:px-4 max-sm:grid max-sm:grid-cols-1 max-sm:[&_select]:w-full max-sm:[&_span:has(>select)]:w-full">
      <span className="mr-1 hidden items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.08em] text-zinc-500 sm:inline-flex dark:text-zinc-400">
        <SlidersHorizontal size={14} aria-hidden /> Filtros
      </span>
      {children}
      {extra && <div className="ml-auto flex flex-wrap items-center gap-2">{extra}</div>}
    </div>
  );
}

/**
 * Cabeçalho do cartão principal de um ranking: ícone pastel, título, subtítulo e,
 * opcionalmente, o "Como funciona" (texto explicativo recolhido; só entra no DOM
 * quando aberto).
 */
export function CabecalhoCartao({
  icone,
  tom = "violeta",
  titulo,
  subtitulo,
  acoes,
  ajuda,
}: {
  icone: LucideIcon;
  tom?: TomPastel;
  titulo: ReactNode;
  subtitulo?: ReactNode;
  acoes?: ReactNode;
  ajuda?: ReactNode;
}) {
  const [aberto, setAberto] = useState(false);
  const idAjuda = useId();
  return (
    <div className="px-5 pb-4 pt-5">
      <div className="flex flex-wrap items-start gap-3">
        <IconePastel icone={icone} tom={tom} />
        <div className="min-w-0 flex-1 basis-56">
          <h2 className="text-base font-semibold leading-snug text-zinc-900 dark:text-white">{titulo}</h2>
          {subtitulo && <p className="mt-0.5 text-[13px] text-zinc-500 dark:text-zinc-400">{subtitulo}</p>}
        </div>
        {(acoes || ajuda) && (
          <div className="flex flex-wrap items-center gap-2">
            {acoes}
            {ajuda && (
              <button
                type="button"
                onClick={() => setAberto((a) => !a)}
                aria-expanded={aberto}
                aria-controls={idAjuda}
                className="inline-flex items-center gap-1.5 rounded-xl px-2.5 py-1.5 text-xs font-semibold text-indigo-700 transition-colors max-sm:min-h-10 hover:bg-indigo-50 dark:text-indigo-300 dark:hover:bg-indigo-500/10"
              >
                <HelpCircle size={15} aria-hidden /> Como funciona
              </button>
            )}
          </div>
        )}
      </div>
      {ajuda && (
        <div
          id={idAjuda}
          hidden={!aberto}
          className="mt-4 space-y-2 rounded-2xl border border-indigo-100 bg-indigo-50/60 p-4 text-[13px] leading-relaxed text-zinc-700 dark:border-indigo-500/20 dark:bg-indigo-500/5 dark:text-zinc-200"
        >
          {aberto && ajuda}
        </div>
      )}
    </div>
  );
}

/**
 * Seção SECUNDÁRIA recolhível (ex.: classificação oficial, competição por turno).
 * O conteúdo fica montado (as consultas e os textos de honestidade continuam na
 * tela), mas, fechado, recebe `inert`: não entra no foco do teclado nem na árvore
 * de acessibilidade do navegador — o que se vê é o que se alcança.
 */
export function SecaoRanking({
  titulo,
  subtitulo,
  icone,
  tom = "violeta",
  acoes,
  inicialAberto = false,
  children,
}: {
  titulo: ReactNode;
  subtitulo?: ReactNode;
  icone?: LucideIcon;
  tom?: TomPastel;
  acoes?: ReactNode;
  inicialAberto?: boolean;
  children: ReactNode;
}) {
  const [aberto, setAberto] = useState(inicialAberto);
  const idConteudo = useId();
  const conteudo = useRef<HTMLDivElement>(null);
  useEffect(() => {
    conteudo.current?.toggleAttribute("inert", !aberto);
  }, [aberto]);
  return (
    <section className="card overflow-hidden">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 px-5 py-4">
        {icone && <IconePastel icone={icone} tom={tom} />}
        <div className="min-w-0 flex-1 basis-56">
          <h2 className="text-[15px] font-semibold leading-snug text-zinc-900 dark:text-white">
            {/* No celular o botão ocupa a linha e o chevron fica sempre na borda direita:
                antes, título de duas linhas mandava o chevron para a borda e título curto o
                deixava colado ao texto (seções vizinhas desalinhadas). */}
            <button
              type="button"
              onClick={() => setAberto((a) => !a)}
              aria-expanded={aberto}
              aria-controls={idConteudo}
              className="inline-flex max-w-full items-center gap-2 rounded-lg text-left transition-colors hover:text-indigo-700 max-sm:flex max-sm:min-h-10 max-sm:w-full max-sm:justify-between dark:hover:text-indigo-300"
            >
              <span>{titulo}</span>
              <ChevronDown
                size={17}
                aria-hidden
                className={`shrink-0 text-zinc-500 transition-transform duration-200 motion-reduce:transition-none ${aberto ? "rotate-180" : ""}`}
              />
            </button>
          </h2>
          {subtitulo && <p className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">{subtitulo}</p>}
        </div>
        {acoes && <div className="flex flex-wrap items-center gap-2">{acoes}</div>}
      </div>
      <div
        id={idConteudo}
        ref={conteudo}
        className={`grid transition-[grid-template-rows,opacity] duration-200 ease-out motion-reduce:transition-none ${
          aberto ? "grid-rows-[1fr] opacity-100" : "grid-rows-[0fr] opacity-0"
        }`}
      >
        <div className="min-h-0 overflow-hidden">
          <div className="border-t border-zinc-100 px-5 pb-5 pt-4 dark:border-zinc-800">{children}</div>
        </div>
      </div>
    </section>
  );
}

// ── Abas (com id, para o tabpanel ser rotulado pela aba ativa) ──────────────

export interface ItemAba<T extends string> {
  valor: T;
  rotulo: string;
  icone?: LucideIcon;
  /** Complemento visual (ex.: "Elefante Letrado"): fora do nome acessível. */
  detalhe?: string;
}

/**
 * Abas segmentadas no estilo de `Abas` (ui.tsx), com `id` em cada aba para o
 * painel usar `aria-labelledby`. Setas ←/→, Home e End movem a aba e o foco.
 * `variante="secundaria"` é a pílula clara (categoria); a padrão é a violeta.
 * `celular` organiza as abas abaixo de 640 px (`ABAS_CELULAR`); no celular cada aba
 * tem pelo menos 40 px de altura (alvo de toque).
 */
export function AbasRanking<T extends string>({
  itens,
  valor,
  aoMudar,
  rotulo,
  idAba,
  idPainel,
  variante = "primaria",
  celular,
  className = "",
}: {
  itens: ItemAba<T>[];
  valor: T;
  aoMudar: (valor: T) => void;
  rotulo: string;
  idAba?: (valor: T) => string;
  idPainel?: string;
  variante?: "primaria" | "secundaria";
  celular?: keyof typeof ABAS_CELULAR;
  className?: string;
}) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const aoTecla = (evento: ReactKeyboardEvent<HTMLButtonElement>, indice: number) => {
    let alvo = -1;
    if (evento.key === "ArrowRight") alvo = (indice + 1) % itens.length;
    else if (evento.key === "ArrowLeft") alvo = (indice - 1 + itens.length) % itens.length;
    else if (evento.key === "Home") alvo = 0;
    else if (evento.key === "End") alvo = itens.length - 1;
    if (alvo < 0) return;
    evento.preventDefault();
    aoMudar(itens[alvo].valor);
    refs.current[alvo]?.focus();
  };
  const primaria = variante === "primaria";
  return (
    <div
      role="tablist"
      aria-label={rotulo}
      className={`inline-flex max-w-full flex-wrap gap-1 rounded-2xl border border-zinc-200/80 bg-white p-1 shadow-cartao dark:border-zinc-800 dark:bg-zinc-900 ${
        celular ? ABAS_CELULAR[celular] : ""
      } ${className}`}
    >
      {itens.map((item, i) => {
        const ativa = item.valor === valor;
        const Icone = item.icone;
        const estilo = primaria
          ? ativa
            ? "bg-indigo-600 text-white shadow-pilula"
            : "text-zinc-600 hover:bg-zinc-100 hover:text-zinc-900 dark:text-zinc-300 dark:hover:bg-zinc-800 dark:hover:text-white"
          : ativa
            ? "bg-indigo-50 text-indigo-700 ring-1 ring-inset ring-indigo-200 dark:bg-indigo-500/15 dark:text-indigo-200 dark:ring-indigo-500/30"
            : "text-zinc-600 hover:bg-zinc-100 hover:text-zinc-900 dark:text-zinc-300 dark:hover:bg-zinc-800 dark:hover:text-white";
        return (
          <button
            key={item.valor}
            ref={(el) => {
              refs.current[i] = el;
            }}
            id={idAba?.(item.valor)}
            type="button"
            role="tab"
            aria-selected={ativa}
            aria-controls={idPainel}
            tabIndex={ativa ? 0 : -1}
            onClick={() => aoMudar(item.valor)}
            onKeyDown={(e) => aoTecla(e, i)}
            className={`inline-flex items-center gap-2 rounded-xl font-semibold transition-colors max-sm:min-h-10 max-sm:justify-center ${
              primaria ? "px-3.5 py-2 text-sm" : "px-3 py-1.5 text-[13px]"
            } ${estilo}`}
          >
            {Icone && <Icone size={primaria ? 16 : 15} aria-hidden />}
            {item.rotulo}
            {item.detalhe && (
              <span
                aria-hidden
                // Aba primária ativa (fundo indigo-600): branco dá 4,86:1; o indigo-100 dava
                // 3,92:1, abaixo dos 4,5:1 de texto de 14 px.
                className={`hidden font-medium md:inline ${ativa && primaria ? "text-white" : "text-zinc-500 dark:text-zinc-400"}`}
              >
                · {item.detalhe}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}

// ── Ações do cabeçalho: Exportar lista (CSV) e Gerar certificados ───────────

/** A lista da tela, na ordem exibida, para o lote de certificados (D7). */
export interface CertificadosDaTela {
  alunos: AlunoParaCertificado[];
  modeloInicial: ModeloCertificado;
  /** De onde vem o Top N, ex.: "Ranking · Leitura no período (pontos) · Este mês". */
  contexto: string;
  /** Bimestre da lista quando o período da aba é um bimestre (`bimestreDoPeriodo`). */
  bimestreInicial?: number;
}

/**
 * Botões do cabeçalho do Ranking. Com `alvo` (o espaço de ações do cabeçalho da
 * tela Ranking), vão para lá por portal — cada aba continua dona da própria lista;
 * embutida sem alvo, não aparecem; fora do Ranking (tela avulsa), ficam no lugar.
 * O lote de certificados é escondido da Secretaria (que não emite certificados).
 */
export function AcoesRanking({
  alvo,
  embutido = false,
  csv,
  certificados,
  antes,
}: {
  alvo?: HTMLElement | null;
  embutido?: boolean;
  /** A tabela da tela para o CSV; null enquanto não há lista. */
  csv: TabelaCsv | null;
  /** Lista para o lote; ausente = sem botão de certificados nesta aba. */
  certificados?: CertificadosDaTela | null;
  /** Ações próprias da aba, antes das comuns (ex.: "Baixar cartaz"). */
  antes?: ReactNode;
}) {
  const { escolaId } = useApp();
  const { secretaria } = usePerfil();
  const [aberto, setAberto] = useState(false);
  const comCertificados = Boolean(certificados) && !secretaria;
  const semLinhas = !csv || csv.linhas.length === 0;

  const botoes = (
    <>
      {antes}
      <Botao
        variante="secundario"
        onClick={() => csv && baixarCsv(csv)}
        disabled={semLinhas}
        title={semLinhas ? "Não há lista para exportar." : "Baixa a lista desta tela (com os filtros aplicados) em CSV."}
      >
        <FileDown size={16} aria-hidden /> Exportar lista (CSV)
      </Botao>
      {comCertificados && (
        // Âmbar: a cor reservada à premiação e aos certificados (doc §2), a mesma do
        // botão de certificados da Visão geral e de Premiações.
        <Botao
          variante="ambar"
          onClick={() => setAberto(true)}
          disabled={!certificados || certificados.alunos.length === 0}
          title={certificados && certificados.alunos.length === 0 ? "Não há alunos nesta lista." : undefined}
        >
          <Award size={16} aria-hidden /> Gerar certificados
        </Botao>
      )}
    </>
  );

  return (
    <>
      {alvo ? createPortal(botoes, alvo) : embutido ? null : botoes}
      {comCertificados && certificados && (
        <GerarCertificados
          escolaId={escolaId}
          alunos={certificados.alunos}
          modeloInicial={certificados.modeloInicial}
          contexto={certificados.contexto}
          bimestreInicial={certificados.bimestreInicial}
          aberto={aberto}
          aoFechar={() => setAberto(false)}
        />
      )}
    </>
  );
}

// ── Subtítulo: período + data do dado ──────────────────────────────────────

/** "Este mês", "4º bimestre", "01/08/2026 a 20/08/2026"... (rótulo do período global). */
export function rotuloDoPeriodo(periodo: Periodo, hoje: Date = new Date()): string {
  const br = (iso?: string) => (iso ? iso.split("-").reverse().join("/") : "");
  if (periodo.preset === "personalizado") {
    return periodo.inicio && periodo.fim ? `${br(periodo.inicio)} a ${br(periodo.fim)}` : "Período personalizado";
  }
  if (periodo.preset === "dia") return periodo.inicio ? `Dia ${br(periodo.inicio)}` : "Um dia";
  if (periodo.preset === "bimestre") {
    // Mesmo calendário oficial que o backend usa para "este bimestre".
    const atual = bimestreEmCurso(hoje);
    return atual ? `${atual.numero}º bimestre` : "Este bimestre";
  }
  return PRESETS_PERIODO.find((p) => p.valor === periodo.preset)?.rotulo ?? periodo.preset;
}

const dd_mm = (iso: string) => {
  const [, mes, dia] = iso.slice(0, 10).split("-");
  return dia && mes ? `${dia}/${mes}` : iso;
};

/** Dia (AAAA-MM-DD) e hora (HH:MM) de um instante da API no horário de Brasília. */
function noHorarioDeBrasilia(iso: string): { dia: string; hora: string } | null {
  const data = paraData(iso);
  if (Number.isNaN(data.getTime())) return null;
  const partes = Object.fromEntries(
    new Intl.DateTimeFormat("en-CA", {
      timeZone: "America/Sao_Paulo",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23",
    })
      .formatToParts(data)
      .map((p) => [p.type, p.value]),
  );
  return { dia: `${partes.year}-${partes.month}-${partes.day}`, hora: `${partes.hour}:${partes.minute}` };
}

/**
 * "dados de 19/10 às 06:10" a partir do frescor do backend (nenhuma conta de idade
 * aqui). A data é a do dado mais recente de cada dimensão; com datas diferentes,
 * vira "dados de 05/10 a 19/10". A hora só aparece quando a última sincronização
 * que aplicou dado é do MESMO dia do dado (senão a hora seria de outra coisa).
 */
export function textoFrescorCabecalho(frescor: Frescor, dimensoes: Dimensao[]): string | null {
  const blocos = dimensoes
    .map((d) => frescor.dimensoes?.[d])
    .filter((b): b is NonNullable<typeof b> =>
      Boolean(b?.contratada && b.estado && b.estado !== "sem_dados" && b.dado_mais_recente_em));
  if (blocos.length === 0) return null;
  const dias = blocos.map((b) => b.dado_mais_recente_em!.slice(0, 10)).sort();
  const de = dias[0];
  const ate = dias[dias.length - 1];
  if (de !== ate) return `dados de ${dd_mm(de)} a ${dd_mm(ate)}`;
  const horas = blocos
    .map((b) => (b.ultima_sincronizacao_ok_em ? noHorarioDeBrasilia(b.ultima_sincronizacao_ok_em) : null))
    .filter((p): p is { dia: string; hora: string } => p != null && p.dia === de)
    .map((p) => p.hora)
    .sort();
  const hora = horas[horas.length - 1];
  return hora ? `dados de ${dd_mm(de)} às ${hora}` : `dados de ${dd_mm(de)}`;
}

/**
 * Subtítulo do cabeçalho: o período (em destaque) e a data do dado, do
 * `/ranking/frescor` da escola. Falha ao buscar = sem data (nunca uma inventada).
 * Uma instância por escola (`key`), como o `SeloFrescorDaEscola`: a data da escola
 * anterior não fica na tela enquanto a nova carrega.
 */
export function DescricaoRanking({
  periodo,
  dimensoes,
  aoVivo = false,
}: {
  periodo: string;
  dimensoes: Dimensao[];
  /** Placar consultado no Matific na hora (a hora do dado aparece junto da lista). */
  aoVivo?: boolean;
}) {
  const { escolaId } = useApp();
  return (
    <>
      <span className="font-semibold text-zinc-700 dark:text-zinc-200">{periodo}</span>
      {aoVivo ? (
        <span> · placar ao vivo do Matific</span>
      ) : (
        escolaId != null && dimensoes.length > 0 && (
          <FrescorDoCabecalho key={escolaId} escolaId={escolaId} dimensoes={dimensoes} />
        )
      )}
    </>
  );
}

function FrescorDoCabecalho({ escolaId, dimensoes }: { escolaId: number; dimensoes: Dimensao[] }) {
  const { dados, erro } = useApi<Frescor>(`/escolas/${escolaId}/ranking/frescor`, { cacheMs: 60_000, tentativas: 0 });
  if (erro || !dados) return null;
  const texto = textoFrescorCabecalho(dados, dimensoes);
  return texto ? <span> · {texto}</span> : null;
}
