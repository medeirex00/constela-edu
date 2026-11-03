/**
 * Peças visuais da tela de CRITÉRIOS de pontuação (identidade visual v2, referência
 * 3 "Critérios"): cartão com ícone pastel, barra empilhada colorida com a legenda
 * dos pesos, linhas "ícone + título + descrição curta + percentual em caixa" e o
 * cartão SÓ LEITURA das regras da premiação.
 *
 * NADA AQUI CALCULA. Os percentuais chegam prontos da API (GET
 * /configuracoes/pontuacao/regra para a régua efetiva; GET /configuracoes/pesos/{ns}
 * no editor do Admin Global) e a barra só desenha as fatias que já existem — sem
 * fórmula nenhuma no front. As regras da premiação descritas aqui são as FIXAS do
 * backend (services/premiacoes.py): 4 categorias, quem concorre e o desempate.
 *
 * Testes: a legenda da barra é um texto único por item ("Livros · 35%") e é
 * aria-hidden (as linhas já dizem tudo ao leitor de tela), para não repetir no DOM
 * o rótulo exato das linhas nem os textos "nome N%" que a explicação "Como
 * funciona?" usa.
 */
import {
  Award,
  BookMarked,
  BookOpen,
  Calculator,
  CalendarRange,
  CheckCheck,
  CircleCheckBig,
  Clock,
  MessageCircleQuestion,
  Mountain,
  PencilLine,
  Scale,
  SlidersHorizontal,
  Star,
  Target,
  Timer,
  Trophy,
  Users,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useId, type ReactNode } from "react";
import { Link } from "react-router-dom";

import { useModulos } from "../hooks/useModulos";
import { Chip, IconePastel, type TomPastel } from "./ui";

/* -------------------------------------------------------------------------
 * Cores de cada critério: a MESMA cor no quadrado pastel, na fatia da barra e
 * no controle deslizante (accent-color) — a linha funciona como legenda.
 * ----------------------------------------------------------------------- */
export const COR_TOM: Record<TomPastel, { barra: string; hex: string }> = {
  violeta: { barra: "bg-indigo-600", hex: "#6C5CE7" },
  teal: { barra: "bg-teal-600", hex: "#0D9488" }, // a mesma cor da Matemática no gráfico da Visão geral
  // Barras e marcadores com 3:1 sobre o branco (WCAG 1.4.11): âmbar, azul e verde
  // em 600 (o ouro-400 dava 1,8:1; sky/emerald-500, 2,5–2,8:1).
  ambar: { barra: "bg-amber-600", hex: "#D97706" },
  rosa: { barra: "bg-rose-500", hex: "#F43F5E" },
  azul: { barra: "bg-sky-600", hex: "#0284C7" },
  verde: { barra: "bg-emerald-600", hex: "#059669" },
  neutro: { barra: "bg-zinc-400", hex: "#8A8EA9" },
};

export interface MetaCriterio {
  /** Nome do indicador (o mesmo rótulo do editor do Admin Global). */
  titulo: string;
  /** Nome curto, só para a legenda da barra. */
  curto: string;
  /** Uma frase, em linguagem de gente. */
  descricao: string;
  icone: LucideIcon;
  tom: TomPastel;
}

/** Indicadores REAIS da nota (backend/app/services/scoring.py, PESOS_PADRAO). */
export const META_CRITERIOS: Record<string, MetaCriterio> = {
  livros: {
    titulo: "Livros únicos concluídos",
    curto: "Livros",
    descricao: "Cada livro diferente que o aluno termina. Reler não soma de novo.",
    icone: BookOpen,
    tom: "violeta",
  },
  dificuldade: {
    titulo: "Dificuldade dos livros",
    curto: "Dificuldade",
    descricao: "Livros de nível mais alto valem mais pontos.",
    icone: Mountain,
    tom: "rosa",
  },
  questoes: {
    titulo: "Questões",
    curto: "Questões",
    descricao: "As perguntas de compreensão feitas depois da leitura.",
    icone: MessageCircleQuestion,
    tom: "azul",
  },
  tempo: {
    titulo: "Tempo de leitura",
    curto: "Tempo",
    descricao: "Minutos de leitura registrados no Elefante Letrado.",
    icone: Clock,
    tom: "ambar",
  },
  atividades: {
    titulo: "Atividades finalizadas",
    curto: "Atividades",
    descricao: "Atividades do Matific que o aluno concluiu.",
    icone: CircleCheckBig,
    tom: "teal",
  },
  media: {
    titulo: "Pontuação média",
    curto: "Média",
    descricao: "A média das pontuações nas atividades.",
    icone: Target,
    tom: "azul",
  },
  estrelas: {
    titulo: "Estrelas",
    curto: "Estrelas",
    descricao: "Estrelas conquistadas nas atividades.",
    icone: Star,
    tom: "ambar",
  },
  tentativas: {
    titulo: "Tentativas",
    curto: "Tentativas",
    descricao: "Quantas questões o aluno respondeu.",
    icone: PencilLine,
    tom: "azul",
  },
  acertos: {
    titulo: "Acertos",
    curto: "Acertos",
    descricao: "Quantas questões o aluno acertou.",
    icone: CheckCheck,
    tom: "verde",
  },
  matific: {
    titulo: "Matific",
    curto: "Matific",
    descricao: "Quanto a nota de Matemática pesa na Nota Geral.",
    icone: Calculator,
    tom: "teal",
  },
  elefante: {
    titulo: "Elefante Letrado",
    curto: "Elefante",
    descricao: "Quanto a nota de Leitura pesa na Nota Geral.",
    icone: BookOpen,
    tom: "violeta",
  },
};

/** Ordem de exibição dos indicadores (a mesma da explicação e do backend). */
const ORDEM_CRITERIOS = [
  "livros", "dificuldade", "questoes", "tempo",
  "atividades", "media", "estrelas",
  "tentativas", "acertos",
  "elefante", "matific",
];

export function ordenarCriterios(chaves: string[]): string[] {
  const posicao = (chave: string) => {
    const i = ORDEM_CRITERIOS.indexOf(chave);
    return i < 0 ? ORDEM_CRITERIOS.length : i;
  };
  return [...chaves].sort((a, b) => posicao(a) - posicao(b));
}

export function metaDoCriterio(chave: string, titulo?: string): MetaCriterio {
  const meta = META_CRITERIOS[chave];
  if (meta) return titulo ? { ...meta, titulo } : meta;
  return {
    titulo: titulo ?? chave,
    curto: titulo ?? chave,
    descricao: "",
    icone: SlidersHorizontal,
    tom: "neutro",
  };
}

const FORMATO_PESO = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 1 });

/** 35 → "35"; 33.3333 → "33,3" (só exibição). */
export function formatarPeso(valor: number): string {
  return FORMATO_PESO.format(Number.isFinite(valor) ? valor : 0);
}

/* -------------------------------------------------------------------------
 * Barra empilhada + legenda. Cada fatia = o peso do indicador, sobre 100. Se a
 * soma (no editor, enquanto o Admin Global mexe) passar de 100, a barra escala
 * pela soma; abaixo de 100 sobra trilho vazio — o Badge "Soma" do editor diz o
 * que falta. Decorativa para leitor de tela: as linhas abaixo dela dão os números.
 * ----------------------------------------------------------------------- */
export interface FatiaPeso {
  chave: string;
  rotulo: string;
  valor: number;
  tom: TomPastel;
}

export function BarraPesos({ fatias, className = "" }: { fatias: FatiaPeso[]; className?: string }) {
  const validas = fatias.map((f) => ({ ...f, valor: Number.isFinite(f.valor) ? Math.max(0, f.valor) : 0 }));
  const soma = validas.reduce((total, f) => total + f.valor, 0);
  const base = Math.max(soma, 100);
  return (
    <div aria-hidden className={className}>
      <div className="flex h-3.5 w-full gap-1 overflow-hidden rounded-full bg-zinc-100 dark:bg-zinc-800">
        {validas
          .filter((f) => f.valor > 0)
          .map((f) => (
            <span
              key={f.chave}
              className={`h-full shrink-0 rounded-full transition-[width] duration-300 motion-reduce:transition-none ${COR_TOM[f.tom].barra}`}
              style={{ width: `calc(${(f.valor / base) * 100}% - 0.25rem)` }}
            />
          ))}
      </div>
      <ul className="mt-3 flex flex-wrap gap-x-4 gap-y-1.5 text-xs font-medium text-zinc-600 dark:text-zinc-300">
        {validas.map((f) => (
          <li key={f.chave} className="inline-flex items-center gap-1.5">
            <span className={`h-2.5 w-2.5 shrink-0 rounded-full ${COR_TOM[f.tom].barra}`} />
            <span className="tabular-nums">{`${f.rotulo} · ${formatarPeso(f.valor)}%`}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Percentual em caixa (o "35%" à direita de cada critério). */
export function CaixaPercentual({ valor }: { valor: number }) {
  return (
    <span className="inline-flex min-w-[4.5rem] items-center justify-center rounded-xl border border-zinc-200 bg-zinc-50 px-3 py-2 text-base font-bold tabular-nums text-zinc-900 dark:border-zinc-700 dark:bg-zinc-800 dark:text-white">
      {`${formatarPeso(valor)}%`}
    </span>
  );
}

/** Cabeçalho de cartão: ícone pastel grande, título (h2) e subtítulo. */
export function CabecalhoCartao({
  id,
  icone,
  tom = "violeta",
  titulo,
  subtitulo,
  extra,
}: {
  id?: string;
  icone: LucideIcon;
  tom?: TomPastel;
  titulo: ReactNode;
  subtitulo?: ReactNode;
  extra?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-start gap-3.5">
      <IconePastel icone={icone} tom={tom} tamanho="lg" />
      <div className="min-w-0 flex-1">
        <h2 id={id} className="text-[17px] font-semibold leading-snug text-zinc-900 dark:text-white">
          {titulo}
        </h2>
        {subtitulo && <p className="mt-0.5 text-sm text-zinc-500 dark:text-zinc-400">{subtitulo}</p>}
      </div>
      {/* Celular (< 640 px): a ação (ex.: "Ver premiações") desce para a linha de baixo,
          alinhada ao texto. Ao lado do título ela espremia título e subtítulo numa
          coluna de ~105 px (8 linhas de 2 palavras). A partir de 640 px, como antes. */}
      {extra && (
        <div className="flex shrink-0 flex-wrap items-center gap-2 max-sm:w-full max-sm:pl-[3.875rem]">{extra}</div>
      )}
    </div>
  );
}

/** Uma linha de critério: ícone pastel, título, descrição curta e, à direita, o
 *  percentual (ou o campo exato, no editor). `children` vai embaixo (slider). */
export function LinhaCriterio({
  meta,
  direita,
  children,
}: {
  meta: MetaCriterio;
  direita: ReactNode;
  children?: ReactNode;
}) {
  return (
    <li className="py-4 first:pt-0 last:pb-0">
      <div className="flex items-start gap-3.5">
        <IconePastel icone={meta.icone} tom={meta.tom} />
        <div className="min-w-0 flex-1 pt-0.5">
          <p className="text-[15px] font-semibold leading-snug text-zinc-900 dark:text-zinc-50">{meta.titulo}</p>
          {meta.descricao && (
            <p className="mt-0.5 text-[13px] leading-snug text-zinc-500 dark:text-zinc-400">{meta.descricao}</p>
          )}
        </div>
        <div className="shrink-0">{direita}</div>
      </div>
      {children}
    </li>
  );
}

/** Classes da lista de critérios. `duasColunas`: a partir de md, as linhas
 *  ficam lado a lado (cartão de largura inteira, ex.: Questões). */
export function classesListaCriterios(duasColunas = false): string {
  return duasColunas
    ? "mt-5 divide-y divide-zinc-100 dark:divide-zinc-800 md:grid md:grid-cols-2 md:gap-x-10 md:gap-y-5 md:divide-y-0 md:[&>li]:py-0"
    : "mt-5 divide-y divide-zinc-100 dark:divide-zinc-800";
}

/**
 * Controle deslizante na COR do critério: trilho cheio até o valor (gradiente
 * com o valor local — só desenho, nenhuma conta) e o botão branco com aro
 * colorido. Continua um <input type="range"> nativo (teclado, leitor de tela e
 * foco do navegador; o nome acessível vem de `rotulo`).
 */
export function ControleDeslizante({
  rotulo,
  valor,
  tom,
  desabilitado,
  aoMudar,
}: {
  rotulo: string;
  valor: number;
  tom: TomPastel;
  desabilitado?: boolean;
  aoMudar: (valor: number) => void;
}) {
  const hex = COR_TOM[tom].hex;
  const cheio = Math.max(0, Math.min(100, Number.isFinite(valor) ? valor : 0));
  return (
    <input
      type="range"
      min={0}
      max={100}
      step={1}
      aria-label={rotulo}
      value={valor}
      disabled={desabilitado}
      onChange={(evento) => aoMudar(Number(evento.target.value))}
      style={{
        accentColor: hex,
        ["--cor" as string]: hex,
        background: `linear-gradient(to right, ${hex} 0%, ${hex} ${cheio}%, var(--trilho) ${cheio}%, var(--trilho) 100%)`,
      }}
      className={[
        "block h-2 w-full cursor-pointer appearance-none rounded-full [--trilho:#E5E7F0] dark:[--trilho:#2A2D4D]",
        "disabled:cursor-not-allowed disabled:opacity-60",
        "[&::-webkit-slider-thumb]:h-5 [&::-webkit-slider-thumb]:w-5 [&::-webkit-slider-thumb]:appearance-none",
        "[&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:border-[3px] [&::-webkit-slider-thumb]:border-solid",
        "[&::-webkit-slider-thumb]:bg-white [&::-webkit-slider-thumb]:shadow-md [&::-webkit-slider-thumb]:[border-color:var(--cor)]",
        "[&::-moz-range-thumb]:h-4 [&::-moz-range-thumb]:w-4 [&::-moz-range-thumb]:rounded-full",
        "[&::-moz-range-thumb]:border-[3px] [&::-moz-range-thumb]:border-solid [&::-moz-range-thumb]:bg-white",
        "[&::-moz-range-thumb]:[border-color:var(--cor)]",
      ].join(" ")}
    />
  );
}

/** Fatias da barra a partir de {chave: peso}, na ordem oficial. */
export function fatiasDosPesos(pesos: Record<string, number>, rotulos?: Record<string, string>): FatiaPeso[] {
  return ordenarCriterios(Object.keys(pesos)).map((chave) => {
    const meta = metaDoCriterio(chave, rotulos?.[chave]);
    return { chave, rotulo: META_CRITERIOS[chave]?.curto ?? meta.titulo, valor: pesos[chave], tom: meta.tom };
  });
}

/* -------------------------------------------------------------------------
 * Cartão SÓ LEITURA de uma parte da régua (escola e Secretaria): mesma cara do
 * editor do Admin Global, sem nenhum controle. É uma região nomeada pelo título.
 * ----------------------------------------------------------------------- */
export function CartaoRegua({
  titulo,
  subtitulo,
  icone,
  tom,
  pesos,
  extra,
  rodape,
  duasColunas = false,
  className = "",
}: {
  titulo: string;
  subtitulo?: ReactNode;
  icone: LucideIcon;
  tom: TomPastel;
  pesos: Record<string, number>;
  extra?: ReactNode;
  /** Nota curta no pé do cartão (fica embaixo mesmo num cartão esticado). */
  rodape?: ReactNode;
  /** Linhas lado a lado a partir de md (cartão de largura inteira). */
  duasColunas?: boolean;
  className?: string;
}) {
  const idTitulo = useId();
  const chaves = ordenarCriterios(Object.keys(pesos));
  return (
    <section aria-labelledby={idTitulo} className={`card flex flex-col p-5 sm:p-6 ${className}`}>
      <CabecalhoCartao id={idTitulo} icone={icone} tom={tom} titulo={titulo} subtitulo={subtitulo} extra={extra} />
      <BarraPesos className="mt-5" fatias={fatiasDosPesos(pesos)} />
      <ul className={classesListaCriterios(duasColunas)}>
        {chaves.map((chave) => (
          <LinhaCriterio key={chave} meta={metaDoCriterio(chave)} direita={<CaixaPercentual valor={pesos[chave]} />} />
        ))}
      </ul>
      {rodape && (
        <p className="mt-auto pt-5 text-xs text-zinc-500 dark:text-zinc-400">
          <span className="block border-t border-zinc-100 pt-4 dark:border-zinc-800">{rodape}</span>
        </p>
      )}
    </section>
  );
}

/* -------------------------------------------------------------------------
 * Regras da premiação — SÓ LEITURA. São as regras FIXAS de
 * backend/app/services/premiacoes.py (nenhuma é configurável): 4 categorias
 * (cada uma com UM critério; nenhuma usa os pesos da nota), quem concorre
 * (aluno ativo do 1º ao 5º ano com resultado no período), o desempate e o
 * período, escolhido na tela de Premiações. Categoria de módulo não contratado
 * não aparece. O único item de premiação que existe no sistema é o certificado.
 * ----------------------------------------------------------------------- */
const CATEGORIAS_PREMIACAO: Array<{
  chave: string;
  modulo: "leitura" | "matematica";
  titulo: string;
  regra: string;
  icone: LucideIcon;
  tom: TomPastel;
}> = [
  {
    chave: "melhor_leitor",
    modulo: "leitura",
    titulo: "Melhor Leitor",
    regra: "Mais pontos de dificuldade somados no período.",
    icone: Trophy,
    tom: "violeta",
  },
  {
    chave: "melhor_matematica",
    modulo: "matematica",
    titulo: "Melhor Matemática",
    regra: "Estrelas ÷ (atividades + 20% da mediana de atividades da escola), de 0 a 5.",
    icone: Calculator,
    tom: "teal",
  },
  {
    chave: "mais_livros",
    modulo: "leitura",
    titulo: "Mais Livros Lidos",
    regra: "Mais livros lidos no período.",
    icone: BookMarked,
    tom: "rosa",
  },
  {
    chave: "mais_tempo",
    modulo: "leitura",
    titulo: "Mais Tempo de Leitura",
    regra: "Mais minutos de leitura no período.",
    icone: Timer,
    tom: "ambar",
  },
];

function RegraFixa({ icone: Icone, titulo, children }: { icone: LucideIcon; titulo: string; children: ReactNode }) {
  return (
    <li className="flex items-start gap-3">
      <span
        aria-hidden
        className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300"
      >
        <Icone size={16} />
      </span>
      <div className="min-w-0 text-sm">
        <p className="font-semibold text-zinc-900 dark:text-zinc-50">{titulo}</p>
        <div className="mt-0.5 text-zinc-600 dark:text-zinc-300">{children}</div>
      </div>
    </li>
  );
}

export function RegrasPremiacao({ mostrarLink = true }: { mostrarLink?: boolean }) {
  const modulos = useModulos();
  const idTitulo = useId();
  const categorias = CATEGORIAS_PREMIACAO.filter((c) => modulos.tem(c.modulo));
  const temMatematica = categorias.some((c) => c.modulo === "matematica");
  return (
    <section aria-labelledby={idTitulo} className="card p-5 sm:p-6">
      <CabecalhoCartao
        id={idTitulo}
        icone={Award}
        tom="ambar"
        titulo="Regras da premiação"
        subtitulo="Cada categoria tem um critério único e fixo, definido pelo Constela. As premiações não usam os pesos da nota."
        extra={
          mostrarLink ? (
            <Link
              to="/premiacoes"
              className="inline-flex items-center text-sm font-semibold text-indigo-600 hover:text-indigo-700 hover:underline max-sm:min-h-10 dark:text-indigo-300"
            >
              Ver premiações
            </Link>
          ) : null
        }
      />

      <ul className="mt-5 grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {categorias.map((c) => (
          <li
            key={c.chave}
            className="flex flex-col gap-3 rounded-2xl border border-zinc-200/80 bg-zinc-50/60 p-4 dark:border-zinc-800 dark:bg-zinc-800/40"
          >
            <IconePastel icone={c.icone} tom={c.tom} />
            <div>
              <p className="text-[15px] font-semibold text-zinc-900 dark:text-white">{c.titulo}</p>
              <p className="mt-1 text-[13px] leading-snug text-zinc-600 dark:text-zinc-300">{c.regra}</p>
            </div>
          </li>
        ))}
      </ul>

      <ul className="mt-6 grid grid-cols-1 gap-4 md:grid-cols-2">
        <RegraFixa icone={Users} titulo="Quem concorre">
          Alunos ativos do 1º ao 5º ano com resultado maior que zero no período.
        </RegraFixa>
        <RegraFixa icone={CalendarRange} titulo="Período">
          Escolhido na tela de Premiações (bimestre, mês, ano letivo ou outro intervalo). Só conta o que
          foi feito dentro dele.
        </RegraFixa>
        <RegraFixa icone={Scale} titulo="Empate">
          {temMatematica
            ? "Na Melhor Matemática vence quem tem mais estrelas e, depois, mais atividades. Persistindo o empate, e nas demais categorias, a ordem é alfabética. A ordem usa o valor completo, não o arredondado."
            : "Persistindo o empate, a ordem é alfabética. A ordem usa o valor completo, não o arredondado."}
        </RegraFixa>
        <RegraFixa icone={Award} titulo="O que a escola entrega">
          <span className="mt-1 flex flex-wrap gap-1.5">
            <Chip className="bg-ouro-50 text-ouro-700 dark:bg-ouro-400/15 dark:text-ouro-300">Certificado</Chip>
          </span>
        </RegraFixa>
      </ul>
    </section>
  );
}
