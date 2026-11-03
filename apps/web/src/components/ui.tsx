/**
 * Componentes básicos reutilizáveis (PRD §25) — a base visual do sistema.
 *
 * Identidade visual v2 (docs/design/IDENTIDADE-VISUAL-V2.md): cartões de 20 px com
 * sombra difusa, Poppins, violeta #6C5CE7 como cor de ação, ícones em quadrados
 * pastéis, pílulas e medalhas. As ASSINATURAS e os textos/papéis acessíveis dos
 * componentes antigos foram mantidos (os testes e ~45 telas dependem deles); tudo o
 * que é novo entrou como prop opcional ou como componente novo.
 */
import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import type { ButtonHTMLAttributes, KeyboardEvent as ReactKeyboardEvent, ReactNode } from "react";
import { AlertTriangle, ChevronDown, Minus, TrendingDown, TrendingUp } from "lucide-react";
import type { LucideIcon } from "lucide-react";

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`card ${className}`}>{children}</div>;
}

/**
 * Seção recolhível/expansível — MESMO padrão visual em todo o sistema. O
 * cabeçalho (ícone + título + chevron) é um botão que abre/fecha; o conteúdo
 * anima a altura de forma suave (truque grid-rows 0fr↔1fr, sem medir DOM, 100%
 * responsivo). `acoes` fica FORA do botão (não recolhe ao clicar). Não altera o
 * conteúdo interno — só o embrulha num Card recolhível.
 */
export function SecaoRecolhivel({
  titulo,
  icone,
  acoes,
  inicialAberto = true,
  children,
  className = "",
}: {
  titulo: ReactNode;
  icone?: ReactNode;
  acoes?: ReactNode;
  inicialAberto?: boolean;
  children: ReactNode;
  className?: string;
}) {
  const [aberto, setAberto] = useState(inicialAberto);
  const idConteudo = useId();
  return (
    <Card className={`p-5 ${className}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <button
          type="button"
          onClick={() => setAberto((a) => !a)}
          aria-expanded={aberto}
          aria-controls={idConteudo}
          className="-m-1 flex min-w-0 flex-auto items-center gap-2 rounded-xl p-1 text-left text-[15px] font-semibold text-zinc-900 transition-colors hover:text-indigo-600 dark:text-zinc-100 dark:hover:text-indigo-300"
        >
          {icone}
          <span className="flex items-center gap-2">{titulo}</span>
          <ChevronDown
            size={16}
            aria-hidden
            className={`ml-auto shrink-0 text-zinc-400 transition-transform duration-200 ${aberto ? "rotate-180" : ""}`}
          />
        </button>
        {acoes && <div className="flex flex-wrap gap-2">{acoes}</div>}
      </div>
      <div
        id={idConteudo}
        className={`grid transition-all duration-200 ease-out ${
          aberto ? "grid-rows-[1fr] opacity-100" : "grid-rows-[0fr] opacity-0"
        }`}
      >
        <div className="overflow-hidden">
          <div className="pt-4">{children}</div>
        </div>
      </div>
    </Card>
  );
}

/**
 * Cabeçalho de página: título grande em Poppins (h1), subtítulo e ações à direita.
 * `descricao` aceita texto ou nós (ex.: "4º bimestre · dados de hoje às 07:30").
 */
export function PageHeader({
  titulo,
  descricao,
  acoes,
}: {
  titulo: ReactNode;
  descricao?: ReactNode;
  acoes?: ReactNode;
}) {
  return (
    <div className="mb-7 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        <h1 className="text-2xl font-bold leading-tight tracking-tight text-zinc-900 dark:text-white sm:text-[28px]">
          {titulo}
        </h1>
        {descricao && <p className="mt-1.5 max-w-3xl text-sm text-zinc-500 dark:text-zinc-400">{descricao}</p>}
      </div>
      {/* No celular a caixa de ações ocupa a linha toda (quando quebra para baixo do título,
          ela já começa na esquerda): quem quiser botões de mesma largura (ACOES_CELULAR do
          Ranking) estica os filhos. No desktop ela continua medindo o próprio conteúdo. */}
      {acoes && <div className="flex flex-wrap items-center gap-2.5 max-sm:w-full">{acoes}</div>}
    </div>
  );
}

/** Tons dos quadrados pastéis de ícone (fundo claro + ícone saturado). */
export type TomPastel = "violeta" | "teal" | "ambar" | "rosa" | "azul" | "verde" | "neutro";

const TONS_PASTEL: Record<TomPastel, string> = {
  violeta: "bg-indigo-50 text-indigo-600 dark:bg-indigo-500/15 dark:text-indigo-300",
  teal: "bg-teal-50 text-teal-600 dark:bg-teal-500/15 dark:text-teal-300",
  ambar: "bg-ouro-50 text-ouro-700 dark:bg-ouro-400/15 dark:text-ouro-300",
  rosa: "bg-rose-50 text-rose-600 dark:bg-rose-500/15 dark:text-rose-300",
  azul: "bg-sky-50 text-sky-600 dark:bg-sky-500/15 dark:text-sky-300",
  verde: "bg-emerald-50 text-emerald-600 dark:bg-emerald-500/15 dark:text-emerald-300",
  neutro: "bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300",
};

/** Ícone dentro de um quadrado pastel arredondado (padrão das referências). */
export function IconePastel({
  icone: Icone,
  tom = "violeta",
  tamanho = "md",
  className = "",
}: {
  icone: LucideIcon;
  tom?: TomPastel;
  tamanho?: "sm" | "md" | "lg";
  className?: string;
}) {
  const caixa = { sm: "h-8 w-8 rounded-lg", md: "h-10 w-10 rounded-xl", lg: "h-12 w-12 rounded-2xl" }[tamanho];
  const icone = { sm: 16, md: 20, lg: 22 }[tamanho];
  return (
    <span aria-hidden className={`grid shrink-0 place-items-center ${caixa} ${TONS_PASTEL[tom]} ${className}`}>
      <Icone size={icone} strokeWidth={2} />
    </span>
  );
}

/**
 * Pílula de variação (▲ verde, ▼ vermelho, — neutro). Só deve aparecer com dado REAL
 * de comparação vindo da API. O sentido também vai em texto (sr-only), para a
 * informação não depender só da cor.
 */
export function Variacao({
  sentido,
  children,
  descricao,
}: {
  sentido: "sobe" | "desce" | "igual";
  children: ReactNode;
  /** Texto para leitor de tela, ex.: "a mais que no mesmo ponto do 3º bimestre". */
  descricao?: string;
}) {
  const estilo = {
    sobe: "bg-emerald-50 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300",
    desce: "bg-rose-50 text-rose-700 dark:bg-rose-500/15 dark:text-rose-300",
    igual: "bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300",
  }[sentido];
  const Icone = sentido === "sobe" ? TrendingUp : sentido === "desce" ? TrendingDown : Minus;
  const falado = { sobe: "aumento de", desce: "queda de", igual: "sem variação" }[sentido];
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-semibold tabular-nums ${estilo}`}>
      <Icone size={13} strokeWidth={2.5} aria-hidden />
      <span className="sr-only">{falado} </span>
      {children}
      {descricao && <span className="sr-only"> {descricao}</span>}
    </span>
  );
}

/**
 * Cartão de indicador (KPI). Mantém a API antiga (icone, rotulo, valor, detalhe) e
 * ganha `tom` (quadrado pastel do ícone) e `variacao` (pílula no canto). Sem
 * `variacao`, nada é exibido no canto — nunca uma comparação inventada.
 */
export function StatCard({
  icone,
  rotulo,
  valor,
  detalhe,
  tom = "violeta",
  variacao,
}: {
  icone: ReactNode;
  rotulo: string;
  valor: string;
  detalhe?: ReactNode;
  tom?: TomPastel;
  variacao?: ReactNode;
}) {
  // A ORDEM NO DOM continua a antiga (rótulo, valor, detalhe — é a ordem que o leitor
  // de tela lê e que as telas/testes conferem); a grade só muda a ordem VISUAL:
  // ícone e variação no topo, número grande, rótulo e detalhe embaixo.
  // content-start: numa fileira de cartões, o mais alto (legenda de 2 linhas) estica
  // os vizinhos; sem isso a sobra se repartia entre as linhas da grade e o número
  // descia alguns px. Ancorado no topo, ícone, número e rótulo ficam na mesma altura
  // lado a lado e só a legenda cresce para baixo.
  return (
    <Card className="grid min-w-0 grid-cols-[1fr_auto] content-start items-start gap-x-2 p-5">
      <span
        aria-hidden
        className={`col-start-1 row-start-1 grid h-10 w-10 shrink-0 place-items-center rounded-xl ${TONS_PASTEL[tom]}`}
      >
        {icone}
      </span>
      <span className="col-span-2 row-start-3 mt-2 text-sm font-medium text-zinc-700 dark:text-zinc-200">{rotulo}</span>
      <p className="col-span-2 row-start-2 mt-4 min-w-0 text-[28px] font-bold leading-none tracking-tight text-zinc-900 tabular-nums [overflow-wrap:anywhere] max-sm:text-[24px] dark:text-white sm:text-[32px]">
        {valor}
      </p>
      {detalhe && (
        <p className="col-span-2 row-start-4 mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">{detalhe}</p>
      )}
      {variacao && <div className="col-start-2 row-start-1 justify-self-end">{variacao}</div>}
    </Card>
  );
}

type BotaoProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  /** "neutro" é o nome antigo de "secundario" (mantido por compatibilidade). */
  variante?: "primario" | "neutro" | "secundario" | "ambar" | "perigo" | "fantasma";
  tamanho?: "sm" | "md" | "lg";
};

export const ESTILOS_BOTAO = {
  primario:
    "bg-indigo-600 text-white shadow-pilula hover:bg-indigo-700 disabled:bg-zinc-300 disabled:text-zinc-600 disabled:shadow-none dark:disabled:bg-zinc-700 dark:disabled:text-zinc-400",
  secundario:
    "border border-zinc-200 bg-white text-zinc-800 shadow-cartao hover:border-zinc-300 hover:bg-zinc-50 disabled:text-zinc-400 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100 dark:hover:bg-zinc-800",
  ambar:
    "bg-ouro-400 text-marinho-900 shadow-ambar hover:bg-ouro-500 disabled:bg-zinc-300 disabled:text-zinc-600 disabled:shadow-none",
  perigo:
    "bg-rose-600 text-white hover:bg-rose-700 disabled:bg-zinc-300 disabled:text-zinc-600 dark:disabled:bg-zinc-700",
  fantasma:
    "text-zinc-700 hover:bg-zinc-100 disabled:text-zinc-400 dark:text-zinc-200 dark:hover:bg-zinc-800",
} as const;

/** `sm` no celular (< 640 px) ganha altura mínima de 40 px (alvo de toque: paginação,
 *  "Certificados do pódio", "Escolher planilha"); do sm em diante é o mesmo de antes. */
export const TAMANHOS_BOTAO = {
  sm: "gap-1.5 rounded-lg px-3 py-1.5 text-xs max-sm:min-h-10",
  md: "gap-2 rounded-xl px-4 py-2.5 text-sm",
  lg: "gap-2 rounded-xl px-5 py-3 text-[15px]",
} as const;

export function Botao({ variante = "primario", tamanho = "md", className = "", ...props }: BotaoProps) {
  const estilo = ESTILOS_BOTAO[variante === "neutro" ? "secundario" : variante];
  return (
    <button
      className={`inline-flex items-center justify-center font-semibold transition-colors disabled:cursor-not-allowed ${TAMANHOS_BOTAO[tamanho]} ${estilo} ${className}`}
      {...props}
    />
  );
}

/** Botão redondo só de ícone (busca, notificações, tema). `rotulo` vira o nome acessível. */
export function BotaoIcone({
  rotulo,
  children,
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { rotulo: string }) {
  return (
    <button
      type="button"
      aria-label={rotulo}
      title={rotulo}
      className={`relative grid h-10 w-10 shrink-0 place-items-center rounded-full border border-zinc-200/80 bg-white text-zinc-600 shadow-cartao transition-colors hover:text-indigo-600 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300 dark:hover:text-indigo-300 ${className}`}
      {...props}
    >
      {children}
    </button>
  );
}

export function Badge({
  children,
  tom = "neutro",
}: {
  children: ReactNode;
  tom?: "neutro" | "destaque" | "ok" | "alerta" | "erro" | "info";
}) {
  const tons = {
    neutro: "bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300",
    destaque: "bg-indigo-50 text-indigo-700 dark:bg-indigo-500/15 dark:text-indigo-300",
    ok: "bg-emerald-50 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300",
    alerta: "bg-ouro-50 text-ouro-700 dark:bg-ouro-400/15 dark:text-ouro-300",
    erro: "bg-rose-50 text-rose-700 dark:bg-rose-500/15 dark:text-rose-300",
    info: "bg-sky-50 text-sky-700 dark:bg-sky-500/15 dark:text-sky-300",
  } as const;
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-semibold ${tons[tom]}`}>
      {children}
    </span>
  );
}

/** E-mail que, quando não cabe, quebra de preferência ANTES do "@" (e não deixa uma
 *  letra sozinha na linha de baixo). Use num pai com [overflow-wrap:anywhere]. */
export function EmailQuebravel({ email }: { email: string }) {
  const arroba = email.indexOf("@");
  if (arroba <= 0) return <>{email}</>;
  return <>{email.slice(0, arroba)}<wbr />{email.slice(arroba)}</>;
}

/** Etiqueta discreta (ex.: turma "2º A", itens de premiação). Não quebra linha: numa
 *  coluna estreita, "2º Ano A" virava três linhas de uma palavra. */
export function Chip({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <span
      className={`inline-flex items-center whitespace-nowrap rounded-lg bg-zinc-100 px-2 py-1 text-xs font-semibold text-zinc-700 dark:bg-zinc-800 dark:text-zinc-200 ${className}`}
    >
      {children}
    </span>
  );
}

/** Rótulo de seção em caixa alta (ex.: "PROJETO", "INDICADORES"). Caixa alta só por CSS. */
export function RotuloSecao({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <p className={`text-[11px] font-semibold uppercase tracking-[0.08em] text-zinc-500 dark:text-zinc-400 ${className}`}>
      {children}
    </p>
  );
}

export function Mensagem({ tipo, children }: { tipo: "ok" | "erro"; children: ReactNode }) {
  const estilos =
    tipo === "ok"
      ? "border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-500/20 dark:bg-emerald-500/10 dark:text-emerald-200"
      : "border-rose-200 bg-rose-50 text-rose-800 dark:border-rose-500/20 dark:bg-rose-500/10 dark:text-rose-200";
  // A11y (WCAG 4.1.3 — Status Messages): erro é anunciado com urgência pelo
  // leitor de tela (role=alert ⇒ assertive); sucesso é anunciado sem
  // interromper (role=status ⇒ polite). Aparência inalterada.
  const anuncio =
    tipo === "erro"
      ? ({ role: "alert" } as const)
      : ({ role: "status", "aria-live": "polite" } as const);
  return (
    <div {...anuncio} className={`rounded-xl border px-4 py-2.5 text-sm ${estilos}`}>
      {children}
    </div>
  );
}

export function Carregando({ texto = "Carregando..." }: { texto?: string }) {
  return (
    <div className="flex items-center justify-center gap-2.5 py-16 text-sm text-zinc-500 dark:text-zinc-400">
      <span className="h-5 w-5 animate-spin rounded-full border-2 border-indigo-100 border-t-indigo-600 motion-reduce:animate-none dark:border-zinc-700 dark:border-t-indigo-400" />
      {texto}
    </div>
  );
}

/** Bloco cinza animado para o esqueleto de carregamento (desliga em reduced-motion). */
export function Skeleton({ className = "" }: { className?: string }) {
  return (
    <div
      aria-hidden
      className={`animate-pulse rounded-lg bg-zinc-200/70 motion-reduce:animate-none dark:bg-zinc-800 ${className}`}
    />
  );
}

export function Vazio({
  titulo,
  descricao,
  acao,
  icone: Icone,
}: {
  titulo: string;
  descricao?: string;
  /** Ação opcional (ex.: botão "Tentar de novo" em estados de erro). */
  acao?: ReactNode;
  /** Ícone opcional num círculo pastel. */
  icone?: LucideIcon;
}) {
  // px-5: o Card em volta não tem padding próprio; sem isso, no celular o título e a
  // descrição encostavam nas bordas do cartão (no desktop o max-w-md escondia).
  return (
    <div className="flex flex-col items-center px-5 py-14 text-center">
      {Icone && (
        <span aria-hidden className="mb-4 grid h-14 w-14 place-items-center rounded-full bg-indigo-50 text-indigo-500 dark:bg-indigo-500/15 dark:text-indigo-300">
          <Icone size={24} />
        </span>
      )}
      <p className="text-[15px] font-semibold text-zinc-800 dark:text-zinc-100">{titulo}</p>
      {descricao && <p className="mt-1 max-w-md text-sm text-zinc-500 dark:text-zinc-400">{descricao}</p>}
      {acao && <div className="mt-5 flex justify-center">{acao}</div>}
    </div>
  );
}

/** Estado de erro de carregamento, com "Tentar de novo" (anunciado como alerta). */
export function Erro({
  titulo = "Não foi possível carregar",
  descricao,
  aoTentar,
}: {
  titulo?: string;
  descricao?: string;
  aoTentar?: () => void;
}) {
  return (
    <div role="alert" className="flex flex-col items-center px-5 py-12 text-center">
      <span aria-hidden className="mb-4 grid h-14 w-14 place-items-center rounded-full bg-rose-50 text-rose-500 dark:bg-rose-500/15 dark:text-rose-300">
        <AlertTriangle size={24} />
      </span>
      <p className="text-[15px] font-semibold text-zinc-800 dark:text-zinc-100">{titulo}</p>
      {descricao && <p className="mt-1 max-w-md text-sm text-zinc-500 dark:text-zinc-400">{descricao}</p>}
      {aoTentar && (
        <Botao variante="secundario" className="mt-5" onClick={aoTentar}>
          Tentar de novo
        </Botao>
      )}
    </div>
  );
}

export function rotuloCampo(chave: string, rotulos: Record<string, string>): string {
  return rotulos[chave] ?? chave;
}

/** Elementos que podem receber foco, para a armadilha de foco de Modal/Drawer. */
const FOCAVEIS =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

function prenderFoco(evento: ReactKeyboardEvent<HTMLElement>, caixa: HTMLElement | null) {
  if (evento.key !== "Tab" || !caixa) return;
  // Janela aninhada (Confirmação dentro da gaveta) já tratou este Tab.
  if (evento.isDefaultPrevented()) return;
  const itens = Array.from(caixa.querySelectorAll<HTMLElement>(FOCAVEIS));
  if (itens.length === 0) {
    evento.preventDefault();
    return;
  }
  const primeiro = itens[0];
  const ultimo = itens[itens.length - 1];
  const atual = document.activeElement;
  // Foco na própria caixa (onde a janela abre) ou fora dela: Shift+Tab vai ao
  // último item e Tab ao primeiro. Antes, o Shift+Tab saía da caixa para o véu
  // e, no seguinte, para a página por trás.
  const semItem = atual === caixa || !caixa.contains(atual);
  if (evento.shiftKey && (atual === primeiro || semItem)) {
    evento.preventDefault();
    ultimo.focus();
  } else if (!evento.shiftKey && (atual === ultimo || semItem)) {
    evento.preventDefault();
    primeiro.focus();
  }
}

/** Título da página (h1 do conteúdo): destino do foco quando quem abriu a janela
 *  já não existe. Ganha tabIndex=-1 (focável por script, fora do Tab). */
function focarTituloDaPagina(): void {
  const titulo = document.querySelector<HTMLElement>("main h1") ?? document.querySelector<HTMLElement>("h1");
  if (!titulo) return;
  if (!titulo.hasAttribute("tabindex")) titulo.setAttribute("tabindex", "-1");
  titulo.focus({ preventScroll: true });
}

/**
 * Devolve o foco a quem abriu a janela. Se esse botão sumir logo depois (a linha
 * removida, o "Desligar" que vira "Ligar" quando a lista recarrega), o foco iria
 * parar no <body> e o teclado/leitor de tela voltaria ao início da página: por
 * alguns segundos, se o botão sair do documento com o foco nele, o foco vai para o
 * título da página. Para assim que a pessoa focar outra coisa.
 */
function devolverFoco(origem: HTMLElement | null): void {
  if (!origem || !document.contains(origem)) {
    if (!document.activeElement || document.activeElement === document.body) focarTituloDaPagina();
    return;
  }
  origem.focus();
  let restantes = 25;
  const vigia = window.setInterval(() => {
    // Sem documento (o jsdom de um teste que já terminou some antes dos 5 s de vigia):
    // só para — `document`/`window` aqui dariam ReferenceError e derrubavam a suíte.
    if (typeof document === "undefined") return clearInterval(vigia);
    restantes -= 1;
    const ativo = document.activeElement;
    if (ativo && ativo !== origem && ativo !== document.body) return window.clearInterval(vigia);
    if (!document.contains(origem)) {
      window.clearInterval(vigia);
      if (!ativo || ativo === document.body) focarTituloDaPagina();
      return;
    }
    if (restantes <= 0) window.clearInterval(vigia);
  }, 200);
}

/**
 * Janela modal acessível: role=dialog + aria-modal, título ligado por
 * aria-labelledby, Esc fecha, foco vai para a janela ao abrir, fica preso nela
 * (Tab/Shift+Tab) e volta ao elemento de origem ao fechar. O <h2> e o conteúdo
 * continuam IRMÃOS dentro da mesma caixa (as telas e os testes contam com isso).
 */
export function Modal({
  titulo,
  aberto,
  aoFechar,
  children,
  largura = "max-w-lg",
}: {
  titulo: string;
  aberto: boolean;
  aoFechar: () => void;
  children: ReactNode;
  /** Classe de largura máxima da caixa (padrão max-w-lg). */
  largura?: string;
}) {
  const idTitulo = useId();
  const caixa = useRef<HTMLDivElement>(null);
  const fecharRef = useRef(aoFechar);
  fecharRef.current = aoFechar;
  // Quem abriu, lido no RENDER da abertura (o autoFocus do conteúdo roda antes
  // do efeito daqui e já teria levado o foco para dentro da janela).
  const origemRef = useRef<HTMLElement | null>(null);
  const abertoAntes = useRef(false);
  if (aberto && !abertoAntes.current) origemRef.current = document.activeElement as HTMLElement | null;
  abertoAntes.current = aberto;

  // Trava o scroll do fundo enquanto o modal está aberto (evita "vazar" o
  // rolar por trás no iOS). O cleanup restaura o estado anterior. Esc fecha.
  useEffect(() => {
    if (!aberto) return;
    const anterior = document.body.style.overflow;
    const origem = origemRef.current;
    document.body.style.overflow = "hidden";
    if (caixa.current && !caixa.current.contains(document.activeElement)) caixa.current.focus();
    const aoTecla = (evento: KeyboardEvent) => {
      if (evento.key !== "Escape") return;
      // Marca o Esc como tratado: a gaveta por baixo (Drawer) não fecha junto.
      evento.preventDefault();
      fecharRef.current();
    };
    window.addEventListener("keydown", aoTecla);
    return () => {
      document.body.style.overflow = anterior;
      window.removeEventListener("keydown", aoTecla);
      devolverFoco(origem);
    };
  }, [aberto]);

  if (!aberto) return null;
  return (
    // m-0: dentro de um pai com space-y-*, o margin-top do irmão empurrava o véu.
    <div className="fixed inset-0 z-50 m-0 flex items-center justify-center p-4">
      {/* Véu: fecha no clique, mas fica fora do Tab (tabIndex -1) — irmão da
          caixa, era a porta de saída do Shift+Tab para a página. */}
      <button
        aria-label="Fechar janela"
        tabIndex={-1}
        className="absolute inset-0 bg-marinho-950/50 backdrop-blur-[2px]"
        onClick={aoFechar}
      />
      {/* dvh: no iOS Safari a caixa nunca estoura o viewport visível quando a
          barra de URL aparece/some. overscroll-contain corta o scroll chaining. */}
      <div
        ref={caixa}
        role="dialog"
        aria-modal="true"
        aria-labelledby={idTitulo}
        tabIndex={-1}
        onKeyDown={(e) => prenderFoco(e, caixa.current)}
        className={`relative max-h-[90dvh] w-full ${largura} overflow-y-auto overscroll-contain rounded-3xl border border-zinc-200/80 bg-white p-6 shadow-flutuante focus:outline-none dark:border-zinc-700 dark:bg-zinc-900`}
      >
        <h2 id={idTitulo} className="mb-4 text-lg font-bold tracking-tight text-zinc-900 dark:text-white">
          {titulo}
        </h2>
        {children}
      </div>
    </div>
  );
}

/**
 * Confirmação de ação (destrutiva ou em lote): diz o que vai acontecer ANTES de
 * acontecer. Usa o Modal acessível.
 */
export function Confirmacao({
  titulo,
  aberto,
  aoFechar,
  aoConfirmar,
  rotuloConfirmar = "Confirmar",
  rotuloCancelar = "Cancelar",
  variante = "primario",
  ocupado = false,
  desabilitado = false,
  children,
  largura,
}: {
  titulo: string;
  aberto: boolean;
  aoFechar: () => void;
  aoConfirmar: () => void;
  rotuloConfirmar?: string;
  rotuloCancelar?: string;
  variante?: "primario" | "ambar" | "perigo";
  ocupado?: boolean;
  desabilitado?: boolean;
  children: ReactNode;
  largura?: string;
}) {
  return (
    <Modal titulo={titulo} aberto={aberto} aoFechar={ocupado ? () => undefined : aoFechar} largura={largura}>
      <div className="space-y-4 text-sm text-zinc-600 dark:text-zinc-300">{children}</div>
      <div className="mt-6 flex flex-wrap justify-end gap-2.5">
        <Botao variante="secundario" onClick={aoFechar} disabled={ocupado}>
          {rotuloCancelar}
        </Botao>
        <Botao variante={variante} onClick={aoConfirmar} disabled={ocupado || desabilitado} aria-busy={ocupado}>
          {rotuloConfirmar}
        </Botao>
      </div>
    </Modal>
  );
}

export function Drawer({
  titulo,
  aberto,
  aoFechar,
  children,
}: {
  titulo: string;
  aberto: boolean;
  aoFechar: () => void;
  children: ReactNode;
}) {
  const painel = useRef<HTMLElement>(null);
  const botaoFechar = useRef<HTMLButtonElement>(null);
  // aoFechar por ref: as telas passam uma arrow nova a cada render; refazer o
  // efeito por isso devolveria o foco a quem abriu a cada render.
  const fecharRef = useRef(aoFechar);
  fecharRef.current = aoFechar;
  // Quem abriu a gaveta, lido no RENDER da abertura: os efeitos (e o autoFocus)
  // do conteúdo rodam antes do efeito daqui e já teriam levado o foco para dentro
  // do painel — que some ao fechar, deixando o foco no <body>.
  const origemRef = useRef<HTMLElement | null>(null);
  const abertoAntes = useRef(false);
  if (aberto && !abertoAntes.current) origemRef.current = document.activeElement as HTMLElement | null;
  abertoAntes.current = aberto;

  // Gaveta = diálogo modal: trava o scroll do fundo, leva o foco ao "Fechar"
  // ao abrir (se ainda não estiver dentro), prende o Tab (onKeyDown do painel)
  // e devolve o foco a quem abriu ao fechar.
  useEffect(() => {
    if (!aberto) return;
    const anterior = document.body.style.overflow;
    const origem = origemRef.current;
    document.body.style.overflow = "hidden";
    if (painel.current && !painel.current.contains(document.activeElement)) botaoFechar.current?.focus();
    const aoTecla = (evento: KeyboardEvent) => {
      if (evento.key !== "Escape") return;
      // Esc de uma janela aberta DENTRO da gaveta (ex.: "Gravar a Lista Piloto?")
      // fecha só ela; a gaveta (e a prévia) ficam. Os dois ouvintes estão no
      // window e o da gaveta pode rodar antes: por isso também olha o DOM.
      if (evento.defaultPrevented) return;
      if (painel.current?.querySelector('[role="dialog"][aria-modal="true"]')) return;
      fecharRef.current();
    };
    window.addEventListener("keydown", aoTecla);
    return () => {
      document.body.style.overflow = anterior;
      window.removeEventListener("keydown", aoTecla);
      devolverFoco(origem);
    };
  }, [aberto]);

  if (!aberto) return null;
  return (
    <div className="fixed inset-0 z-50 m-0">
      {/* Véu: fecha no clique, fora do Tab (o "Fechar" do painel é o acessível). */}
      <button
        aria-label="Fechar painel"
        tabIndex={-1}
        className="absolute inset-0 bg-marinho-950/50 backdrop-blur-[2px]"
        onClick={aoFechar}
      />
      {/* tabIndex -1: clique em área sem controle mantém o foco no painel (e o Tab preso). */}
      <aside
        ref={painel}
        role="dialog"
        aria-modal="true"
        aria-label={titulo}
        tabIndex={-1}
        onKeyDown={(e) => prenderFoco(e, painel.current)}
        className="absolute inset-y-0 right-0 flex w-full max-w-md flex-col border-l border-zinc-200 bg-white shadow-flutuante focus:outline-none dark:border-zinc-700 dark:bg-zinc-900"
      >
        <div className="flex items-center justify-between border-b border-zinc-100 px-6 py-4 dark:border-zinc-800">
          <h2 className="text-lg font-bold tracking-tight">{titulo}</h2>
          <button
            ref={botaoFechar}
            aria-label="Fechar"
            className="rounded-lg p-1.5 text-zinc-500 transition-colors hover:bg-zinc-100 hover:text-zinc-800 dark:hover:bg-zinc-800 dark:hover:text-zinc-100"
            onClick={aoFechar}
          >
            <span aria-hidden className="block h-4 w-4 leading-none">✕</span>
          </button>
        </div>
        <div className="flex-1 overflow-y-auto overscroll-contain p-6">{children}</div>
      </aside>
    </div>
  );
}

export function Campo({
  rotulo,
  children,
}: {
  rotulo: string;
  children: ReactNode;
}) {
  return (
    <label className="block text-sm">
      <span className="mb-1.5 block font-medium text-zinc-700 dark:text-zinc-300">{rotulo}</span>
      {children}
    </label>
  );
}

export const estiloInput =
  "w-full rounded-xl border border-zinc-300 bg-white px-3.5 py-2.5 text-sm text-zinc-900 shadow-sm placeholder:text-zinc-400 transition-colors hover:border-zinc-400 focus:border-indigo-500 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100";

/**
 * Classes das abas segmentadas (pílula branca com a aba ativa em violeta), para quem
 * monta a própria lista de abas (ranking, modos da importação) ficar igual a `Abas`.
 * - `lista`: do sm em diante, o visual de sempre (quebra de linha se não couber).
 *   No celular (< 640 px) a lista NÃO quebra em duas linhas: fica numa linha só que
 *   rola de lado, sem barra de rolagem e com sombra na borda do lado em que há abas
 *   escondidas (`.abas-rolaveis` e `.sombra-rolagem-x`, em index.css).
 * - `aba`: no celular a aba não encolhe nem quebra o rótulo, tem 40 px de altura
 *   (alvo de toque) e perde a sombra violeta (a lista que rola cortaria a sombra).
 */
export const classesAbas = {
  lista:
    "abas-rolaveis inline-flex max-w-full flex-wrap gap-1 rounded-2xl border border-zinc-200/80 bg-white p-1 shadow-cartao max-sm:flex-nowrap max-sm:overflow-x-auto max-sm:sombra-rolagem-x dark:border-zinc-800 dark:bg-zinc-900",
  aba: "max-sm:min-h-10 max-sm:shrink-0 max-sm:whitespace-nowrap max-sm:shadow-none",
} as const;

/**
 * Rola SÓ a lista de abas (nunca a página) até `aba` ficar inteira à vista, com uma
 * folga para a vizinha aparecer em parte (pista de que há mais abas). Sem rolagem
 * lateral (desktop, ou todas couberam) não faz nada. Não usa `scrollIntoView`: ele
 * rolaria também a página até a lista — ao abrir a tela, a levaria para baixo.
 */
export function mostrarAbaNaLista(lista: HTMLElement | null, aba: HTMLElement | null, folga = 24): void {
  if (!lista || !aba) return;
  const maximo = lista.scrollWidth - lista.clientWidth;
  if (maximo <= 0) return;
  const caixa = lista.getBoundingClientRect();
  const alvo = aba.getBoundingClientRect();
  let novo = lista.scrollLeft;
  if (alvo.left < caixa.left + folga) novo -= caixa.left + folga - alvo.left;
  else if (alvo.right > caixa.right - folga) novo += alvo.right - (caixa.right - folga);
  else return;
  lista.scrollLeft = Math.max(0, Math.min(maximo, novo));
}

/**
 * Refs da lista e das abas, e a lista rolada até a aba ativa ao montar e a cada troca
 * (clique, setas, Home/End ou mudança vinda de fora). Serve a qualquer lista com
 * `classesAbas.lista`.
 */
export function useAbaAtivaVisivel(indiceAtivo: number) {
  const lista = useRef<HTMLDivElement>(null);
  const abas = useRef<(HTMLButtonElement | null)[]>([]);
  useLayoutEffect(() => {
    mostrarAbaNaLista(lista.current, abas.current[indiceAtivo] ?? null);
  }, [indiceAtivo]);
  return { lista, abas };
}

/**
 * Abas segmentadas (pílula violeta na ativa). role=tablist/tab com aria-selected,
 * foco itinerante e setas ←/→/Home/End. O nome acessível de cada aba é o `rotulo`;
 * `detalhe` (ex.: "Elefante Letrado") aparece ao lado, fora do nome se `detalheNoNome`
 * for falso — assim "Leitura" continua sendo o nome que os testes procuram.
 * No celular a lista é uma linha que rola de lado (ver `classesAbas`).
 */
export function Abas<T extends string>({
  itens,
  valor,
  aoMudar,
  rotulo,
  idPainel,
  className = "",
}: {
  itens: { valor: T; rotulo: string; icone?: LucideIcon; detalhe?: string }[];
  valor: T;
  aoMudar: (valor: T) => void;
  /** Nome do grupo de abas (aria-label do tablist). */
  rotulo: string;
  /** id do painel controlado (aria-controls), quando houver um só painel. */
  idPainel?: string;
  className?: string;
}) {
  const { lista, abas: refs } = useAbaAtivaVisivel(itens.findIndex((item) => item.valor === valor));
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
  return (
    <div ref={lista} role="tablist" aria-label={rotulo} className={`${classesAbas.lista} ${className}`}>
      {itens.map((item, i) => {
        const ativa = item.valor === valor;
        const Icone = item.icone;
        return (
          <button
            key={item.valor}
            ref={(el) => {
              refs.current[i] = el;
            }}
            type="button"
            role="tab"
            aria-selected={ativa}
            aria-controls={idPainel}
            tabIndex={ativa ? 0 : -1}
            onClick={() => aoMudar(item.valor)}
            onKeyDown={(e) => aoTecla(e, i)}
            className={`inline-flex items-center gap-2 rounded-xl px-3.5 py-2 text-sm font-semibold transition-colors ${classesAbas.aba} ${
              ativa
                ? "bg-indigo-600 text-white shadow-pilula"
                : "text-zinc-600 hover:bg-zinc-100 hover:text-zinc-900 dark:text-zinc-300 dark:hover:bg-zinc-800 dark:hover:text-white"
            }`}
          >
            {Icone && <Icone size={16} aria-hidden />}
            {item.rotulo}
            {item.detalhe && (
              <span aria-hidden className={ativa ? "font-medium text-white" : "font-medium text-zinc-500 dark:text-zinc-400"}>
                · {item.detalhe}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}

/** Interruptor liga/desliga acessível (button role="switch"). */
export function Interruptor({
  ligado,
  aoMudar,
  rotulo,
  desabilitado = false,
}: {
  ligado: boolean;
  aoMudar: (ligado: boolean) => void;
  rotulo: string;
  desabilitado?: boolean;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={ligado}
      aria-label={rotulo}
      disabled={desabilitado}
      onClick={() => aoMudar(!ligado)}
      className={`relative inline-flex h-7 w-12 shrink-0 items-center rounded-full transition-colors disabled:cursor-not-allowed disabled:opacity-60 ${
        // Desligado: trilho com ≥ 3:1 contra o cartão (WCAG 1.4.11). zinc-300 dava
        // 1,45:1 no branco e zinc-700 1,68:1 no zinc-900; zinc-400 = 3,22:1, zinc-500 = 3,39:1.
        ligado ? "bg-indigo-600 shadow-pilula" : "bg-zinc-400 dark:bg-zinc-500"
      }`}
    >
      <span
        aria-hidden
        className={`inline-block h-5 w-5 rounded-full bg-white shadow transition-transform ${ligado ? "translate-x-6" : "translate-x-1"}`}
      />
    </button>
  );
}

// ── Avatares e medalhas ────────────────────────────────────────────────────

/** Iniciais (até 2 letras) de um nome. */
export function iniciaisDoNome(nome?: string | null): string {
  const partes = (nome ?? "").trim().split(/\s+/).filter(Boolean);
  if (partes.length === 0) return "?";
  const primeira = partes[0][0] ?? "";
  const ultima = partes.length > 1 ? partes[partes.length - 1][0] ?? "" : "";
  return (primeira + ultima).toUpperCase();
}

// Tons 700 (exceto o violeta da marca): as iniciais brancas ficam acima de 4,5:1 em
// todas as cores (o teal/laranja/esmeralda/azul 600 davam de 3,6 a 4,1:1).
const CORES_AVATAR = [
  "bg-indigo-600",
  "bg-teal-700",
  "bg-orange-700",
  "bg-pink-700",
  "bg-sky-700",
  "bg-emerald-700",
  "bg-violet-700",
  "bg-rose-700",
];

/** Cor estável por pessoa (mesmo id/nome ⇒ mesma cor em todas as telas). */
export function corDoAvatar(chave: string | number): string {
  const texto = String(chave);
  let h = 0;
  for (let i = 0; i < texto.length; i++) h = (h * 31 + texto.charCodeAt(i)) >>> 0;
  return CORES_AVATAR[h % CORES_AVATAR.length];
}

/**
 * Avatar circular com as iniciais. É DECORATIVO (aria-hidden): o nome da pessoa
 * sempre aparece em texto ao lado, então o leitor de tela não ouve "AB Ana Beatriz".
 */
export function Avatar({
  nome,
  chave,
  tamanho = "md",
  className = "",
}: {
  nome?: string | null;
  /** Chave para a cor (id do aluno); sem ela, usa o nome. */
  chave?: string | number;
  tamanho?: "sm" | "md" | "lg" | "xl";
  className?: string;
}) {
  const caixa = {
    sm: "h-8 w-8 text-[11px]",
    md: "h-10 w-10 text-sm",
    lg: "h-14 w-14 text-lg",
    xl: "h-[72px] w-[72px] text-2xl",
  }[tamanho];
  return (
    <span
      aria-hidden
      className={`grid shrink-0 place-items-center rounded-full font-bold text-white ring-2 ring-white dark:ring-zinc-900 ${caixa} ${corDoAvatar(chave ?? nome ?? "?")} ${className}`}
    >
      {iniciaisDoNome(nome)}
    </span>
  );
}

const COR_MEDALHA: Record<1 | 2 | 3, { fundo: string; texto: string }> = {
  1: { fundo: "#F5B942", texto: "#5B3B00" },
  2: { fundo: "#CBD5E9", texto: "#2B3350" },
  3: { fundo: "#E0955A", texto: "#4A2306" },
};

/**
 * Medalha com fita (1º ouro, 2º prata, 3º bronze), em SVG. O texto "Nº lugar" fica
 * para leitor de tela (sr-only); o desenho é aria-hidden.
 */
export function Medalha({
  posicao,
  tamanho = 44,
  semFita = false,
}: {
  posicao: 1 | 2 | 3;
  tamanho?: number;
  semFita?: boolean;
}) {
  const cor = COR_MEDALHA[posicao];
  const altura = semFita ? tamanho : Math.round(tamanho * 1.35);
  return (
    <span className="inline-flex shrink-0">
      <svg aria-hidden width={tamanho} height={altura} viewBox={semFita ? "0 0 44 44" : "0 0 44 60"}>
        {!semFita && (
          <>
            <path d="M8 0 h10 l6 18 h-10 z" fill="#5A4AD4" />
            <path d="M36 0 h-10 l-6 18 h10 z" fill="#6C5CE7" />
          </>
        )}
        <g transform={semFita ? undefined : "translate(0 16)"}>
          <circle cx="22" cy="22" r="21" fill={cor.fundo} />
          <circle cx="22" cy="22" r="16.5" fill="none" stroke="#fff" strokeOpacity="0.55" strokeWidth="2" />
          <text
            x="22"
            y="23"
            textAnchor="middle"
            dominantBaseline="middle"
            fontFamily="Poppins, Inter, sans-serif"
            fontWeight="700"
            fontSize="15"
            fill={cor.texto}
          >
            {posicao}º
          </text>
        </g>
      </svg>
      <span className="sr-only">{posicao}º lugar</span>
    </span>
  );
}

/** Círculo pequeno com a posição (1 ouro, 2 prata, 3 bronze, demais neutro). */
export function PosicaoBolinha({ posicao }: { posicao: number }) {
  const cor =
    posicao === 1
      ? "bg-medalha-ouro text-[#5B3B00]"
      : posicao === 2
        ? "bg-medalha-prata text-[#2B3350]"
        : posicao === 3
          ? "bg-medalha-bronze text-[#4A2306]"
          : "bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300";
  return (
    <span className={`grid h-7 w-7 shrink-0 place-items-center rounded-full text-xs font-bold tabular-nums ${cor}`}>
      {posicao}
    </span>
  );
}

/** Barra de progresso fina (ex.: engajamento por turma). O valor também vai em texto ao lado. */
export function BarraProgresso({
  valor,
  tom = "violeta",
  className = "",
}: {
  /** 0 a 100. */
  valor: number;
  tom?: "violeta" | "teal" | "ambar";
  className?: string;
}) {
  const cor = { violeta: "from-indigo-500 to-indigo-600", teal: "from-teal-400 to-teal-600", ambar: "from-ouro-300 to-ouro-500" }[tom];
  const largura = Math.max(0, Math.min(100, valor));
  return (
    // Largura padrão só sem w-*/basis-* em className: no CSS gerado o w-full vem
    // depois do w-20, e a largura pedida pela tela não valia.
    <span aria-hidden className={`block h-2 ${/(^|\s)(w-|basis-)/.test(className) ? "" : "w-full"} overflow-hidden rounded-full bg-zinc-100 dark:bg-zinc-800 ${className}`}>
      <span className={`block h-full rounded-full bg-gradient-to-r ${cor}`} style={{ width: `${largura}%` }} />
    </span>
  );
}

/** Classes da tabela padrão (cabeçalho em caixa alta, linhas de ~56 px, hover lavanda).
 *  A moldura rola na horizontal quando a tabela não cabe e mostra uma sombra na borda
 *  do lado em que há colunas escondidas (`.sombra-rolagem-x`, em index.css). */
export const classesTabela = {
  moldura: "sombra-rolagem-x relative overflow-x-auto",
  tabela: "w-full text-sm",
  th: "whitespace-nowrap px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-[0.08em] text-zinc-500 dark:text-zinc-400",
  tr: "border-t border-zinc-100 transition-colors hover:bg-zinc-50/80 dark:border-zinc-800 dark:hover:bg-zinc-800/40",
  td: "px-4 py-3.5 text-zinc-700 dark:text-zinc-200",
} as const;
