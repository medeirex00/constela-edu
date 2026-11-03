/**
 * Peças visuais da frente "Pessoas" (alunos, turmas, professores, usuários,
 * livros e revisões) na identidade visual v2 — docs/design/IDENTIDADE-VISUAL-V2.md.
 *
 * Só apresentação: nada aqui decide permissão, filtra dado ou calcula nota. São
 * os pedaços que se repetem nessas telas (barra de filtros em cartão, busca com
 * lupa, <select> NATIVO estilizado, pílula de situação, chip de cargo, avatar com
 * foto, tempo relativo) e que não são genéricos o bastante para o ui.tsx.
 */
import { ChevronDown, Search } from "lucide-react";
import { paraData } from "@constela/core";
import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, SelectHTMLAttributes } from "react";

import { Avatar, Card, Skeleton, TAMANHOS_BOTAO } from "./ui";

/** Barra de filtros: cartão branco com os controles alinhados (padrão das referências). */
export function BarraFiltros({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <Card className={`mb-5 flex flex-wrap items-center gap-3 p-3 sm:p-4 ${className}`}>
      {children}
    </Card>
  );
}

const ESTILO_CONTROLE =
  "w-full rounded-xl border border-zinc-200 bg-white text-sm text-zinc-900 shadow-sm transition-colors placeholder:text-zinc-500 hover:border-zinc-300 focus:border-indigo-500 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100 dark:placeholder:text-zinc-400";

/**
 * Busca com lupa. `rotulo` vira o nome acessível (aria-label) — o placeholder
 * nunca é o único rótulo do campo.
 */
export function CampoBusca({
  rotulo,
  className = "",
  ...props
}: InputHTMLAttributes<HTMLInputElement> & { rotulo: string }) {
  return (
    <span className={`relative block min-w-0 ${className}`}>
      <Search
        size={16}
        aria-hidden
        className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-zinc-400"
      />
      <input aria-label={rotulo} className={`${ESTILO_CONTROLE} py-2.5 pl-10 pr-3.5`} {...props} />
    </span>
  );
}

/**
 * <select> NATIVO com a cara das pílulas brancas (seta própria). Continua sendo o
 * elemento nativo — testes e E2E usam `selectOptions`, e o teclado/leitor de tela
 * do sistema seguem valendo. Dentro de um <label>/Campo o rótulo continua ligado.
 */
export function SelectNativo({
  className = "",
  children,
  ...props
}: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <span className={`relative inline-flex min-w-0 ${className}`}>
      <select
        className={`${ESTILO_CONTROLE} cursor-pointer appearance-none py-2.5 pl-3.5 pr-10 font-medium disabled:cursor-not-allowed disabled:opacity-60`}
        {...props}
      >
        {children}
      </select>
      <ChevronDown
        size={16}
        aria-hidden
        className="pointer-events-none absolute right-3.5 top-1/2 -translate-y-1/2 text-zinc-500"
      />
    </span>
  );
}

/** Cabeçalho de um cartão de lista: título (h2), contagem real e ações à direita. */
export function CabecalhoCartao({
  titulo,
  contagem,
  acoes,
  className = "",
}: {
  titulo: ReactNode;
  /** Ex.: "128 alunos" — sempre um número que veio da API. */
  contagem?: ReactNode;
  acoes?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`flex flex-wrap items-center gap-3 border-b border-zinc-100 px-5 py-4 dark:border-zinc-800 ${className}`}
    >
      <h2 className="text-base font-semibold tracking-tight text-zinc-900 dark:text-white">{titulo}</h2>
      {contagem != null && (
        <span className="rounded-full bg-indigo-50 px-2.5 py-0.5 text-xs font-semibold tabular-nums text-indigo-700 dark:bg-indigo-500/15 dark:text-indigo-300">
          {contagem}
        </span>
      )}
      {acoes && <div className="ml-auto flex flex-wrap items-center gap-2">{acoes}</div>}
    </div>
  );
}

type TomSituacao = "ok" | "neutro" | "alerta" | "erro" | "info";

const TONS_SITUACAO: Record<TomSituacao, { pilula: string; ponto: string }> = {
  ok: {
    pilula: "bg-emerald-50 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300",
    ponto: "bg-emerald-500",
  },
  neutro: {
    pilula: "bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300",
    ponto: "bg-zinc-400",
  },
  alerta: {
    pilula: "bg-ouro-50 text-ouro-700 dark:bg-ouro-400/15 dark:text-ouro-300",
    ponto: "bg-ouro-500",
  },
  erro: {
    pilula: "bg-rose-50 text-rose-700 dark:bg-rose-500/15 dark:text-rose-300",
    ponto: "bg-rose-500",
  },
  info: {
    pilula: "bg-sky-50 text-sky-700 dark:bg-sky-500/15 dark:text-sky-300",
    ponto: "bg-sky-500",
  },
};

/** Pílula de situação com ponto colorido. O texto diz a situação (a cor só reforça). */
export function PilulaSituacao({ tom, children }: { tom: TomSituacao; children: ReactNode }) {
  const estilo = TONS_SITUACAO[tom];
  return (
    <span className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-1 text-xs font-semibold ${estilo.pilula}`}>
      <span aria-hidden className={`h-1.5 w-1.5 rounded-full ${estilo.ponto}`} />
      {children}
    </span>
  );
}

/** Situação de uma CONTA de acesso, com o rótulo legível (nunca o valor cru do banco). */
export function situacaoDaConta(status: string | null | undefined): { tom: TomSituacao; texto: string } {
  const valor = status ?? "ativo";
  if (valor === "ativo") return { tom: "ok", texto: "Ativo" };
  if (valor === "inativo") return { tom: "neutro", texto: "Inativo" };
  if (valor === "excluido") return { tom: "erro", texto: "Excluído" };
  return { tom: "neutro", texto: valor.charAt(0).toUpperCase() + valor.slice(1) };
}

const CORES_CARGO: Record<string, string> = {
  admin: "bg-indigo-50 text-indigo-700 dark:bg-indigo-500/15 dark:text-indigo-300",
  coordenador: "bg-teal-50 text-teal-700 dark:bg-teal-500/15 dark:text-teal-300",
  professor: "bg-sky-50 text-sky-700 dark:bg-sky-500/15 dark:text-sky-300",
};

/** Chip de cargo com cor por papel (o texto continua sendo o rótulo do cargo). */
export function ChipCargo({ cargo, children }: { cargo: string; children: ReactNode }) {
  return (
    <span
      className={`inline-flex items-center rounded-lg px-2 py-1 text-xs font-semibold ${
        CORES_CARGO[cargo] ?? "bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-200"
      }`}
    >
      {children}
    </span>
  );
}

/** Chip violeta de nível de leitura (ex.: "D", "K"), usado nas listas de livros e leituras. */
export function ChipNivel({ children }: { children: ReactNode }) {
  return (
    <span className="inline-flex min-w-[2rem] items-center justify-center rounded-lg bg-indigo-50 px-2 py-1 text-xs font-bold text-indigo-700 dark:bg-indigo-500/15 dark:text-indigo-300">
      {children}
    </span>
  );
}

/**
 * Avatar de aluno: a foto quando existe, senão as iniciais com cor estável. É
 * decorativo (o nome sempre aparece em texto ao lado).
 */
export function AvatarAluno({
  nome,
  chave,
  foto,
  tamanho = "md",
}: {
  nome: string;
  chave?: string | number;
  foto?: string | null;
  tamanho?: "sm" | "md" | "lg" | "xl";
}) {
  if (foto) {
    const caixa = { sm: "h-8 w-8", md: "h-10 w-10", lg: "h-14 w-14", xl: "h-[72px] w-[72px]" }[tamanho];
    return (
      <img
        src={foto}
        alt=""
        aria-hidden
        className={`${caixa} shrink-0 rounded-full object-cover ring-2 ring-white dark:ring-zinc-900`}
      />
    );
  }
  return <Avatar nome={nome} chave={chave} tamanho={tamanho} />;
}

const FUSO_BR = "America/Sao_Paulo";

/**
 * "há 2 dias" a partir de um horário da API (UTC sem sufixo, mesma regra do
 * `paraData` do pacote compartilhado), com a data completa no horário de Brasília
 * para o `title`. Datas com mais de 30 dias aparecem por extenso.
 */
export function tempoRelativo(
  iso: string | null | undefined,
  agora: number = Date.now(),
): { texto: string; completo: string } | null {
  if (!iso) return null;
  const data = paraData(iso);
  if (Number.isNaN(data.getTime())) return null;
  const completo = data.toLocaleString("pt-BR", { timeZone: FUSO_BR, dateStyle: "short", timeStyle: "short" });
  const minutos = Math.floor((agora - data.getTime()) / 60000);
  let texto: string;
  if (minutos < 1) texto = "agora há pouco";
  else if (minutos < 60) texto = `há ${minutos} min`;
  else if (minutos < 60 * 24) texto = `há ${Math.floor(minutos / 60)} h`;
  else if (minutos < 60 * 48) texto = "ontem";
  else if (minutos < 60 * 24 * 30) texto = `há ${Math.floor(minutos / (60 * 24))} dias`;
  else texto = data.toLocaleDateString("pt-BR", { timeZone: FUSO_BR });
  return { texto, completo };
}

/** Botão destrutivo de contorno (para barras de ação em massa sobre fundo claro). */
export function BotaoContornoPerigo({
  className = "",
  tamanho = "sm",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { tamanho?: "sm" | "md" }) {
  return (
    <button
      type="button"
      className={`inline-flex items-center justify-center border border-rose-200 bg-white font-semibold text-rose-700 transition-colors hover:border-rose-300 hover:bg-rose-50 disabled:cursor-not-allowed disabled:opacity-60 dark:border-rose-500/30 dark:bg-zinc-900 dark:text-rose-300 dark:hover:bg-rose-500/10 ${TAMANHOS_BOTAO[tamanho]} ${className}`}
      {...props}
    />
  );
}

/** Esqueleto de lista/tabela enquanto carrega (anuncia "Carregando…" ao leitor de tela). */
export function EsqueletoLista({ linhas = 6, texto = "Carregando..." }: { linhas?: number; texto?: string }) {
  return (
    <div role="status" className="space-y-3 p-5">
      <span className="sr-only">{texto}</span>
      {Array.from({ length: linhas }, (_, i) => (
        <div key={i} className="flex items-center gap-3">
          <Skeleton className="h-9 w-9 rounded-full" />
          <Skeleton className="h-4 flex-1" />
          <Skeleton className="hidden h-4 w-24 sm:block" />
        </div>
      ))}
    </div>
  );
}

/**
 * Copia com fallback: em http na rede local (celular) o clipboard moderno não
 * existe — sem o fallback o botão falharia em silêncio e a pessoa fecharia a
 * janela achando que copiou uma senha/link de uso único.
 */
export function copiarTexto(texto: string, aoCopiar: () => void) {
  const legado = () => {
    const area = document.createElement("textarea");
    area.value = texto;
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    try {
      if (document.execCommand("copy")) aoCopiar();
    } finally {
      document.body.removeChild(area);
    }
  };
  if (navigator.clipboard) {
    navigator.clipboard.writeText(texto).then(aoCopiar).catch(legado);
  } else {
    legado();
  }
}

/** Classe do checkbox nativo no tom da marca (mantém o elemento nativo e o rótulo). */
export const estiloCheckbox =
  "h-4 w-4 shrink-0 cursor-pointer rounded border-zinc-300 accent-indigo-600 dark:border-zinc-600";
