/**
 * Peças comuns das telas principais da Secretaria (DESENHO2 §2.3), todas da identidade V2
 * (Card, PageHeader, IconePastel, Badge de `components/ui.tsx`; o seletor e os selos de
 * `pages/analise/comum.tsx`):
 *
 *  - `PaginaDaRede`: resolve a rede (Secretaria = a dela; global = `?rede=`/a primeira) e cuida
 *    dos estados sem rede, carregando e erro — sempre com o h1 da página (uma página, um título);
 *  - `CabecalhoDaPagina`: o h1, a frase da página, o nome da rede e o seletor "Rede analisada";
 *  - `OQueMede`, `FraseSeparacao`, `ComoLer`: os textos que explicam (§1.1, §1.4);
 *  - `CampoPeriodo`: o período da tela (padrão: ano letivo), com as datas do personalizado;
 *  - `CampoSerie`: a série das plataformas (padrão: do 1º ao 5º ano);
 *  - `AvisoOutraRede`: o aviso do global quando o Painel/Ranking da Rede abre outra rede;
 *  - `EstadoDaLeitura`: carregando/erro de UMA leitura dentro de um bloco (um bloco com erro
 *    não derruba a página).
 */
import { ArrowRight, Info, Landmark, Settings2 } from "lucide-react";
import type { ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";

import { DatasDoPeriodo, PRESETS_PERIODO, type Periodo } from "../../../components/SeletorPeriodo";
import { Botao, Card, Carregando, Erro, Mensagem, PageHeader, Vazio, estiloInput } from "../../../components/ui";
import type { ApiError } from "../../../lib/api";
import { Seletor } from "../../analise/comum";
import { porNome, rotuloSerie } from "../../analise/formato";
import { fraseSeparacao } from "./oQueMede";
import { SERIES_DA_REDE, useRedeDaPagina, type RedeDaPagina } from "./useRedeDaPagina";

export const CINZA = "text-zinc-600 dark:text-zinc-400";

/** Título de seção (h2) das telas novas: o mesmo peso dos cartões da análise. */
export const TITULO_SECAO = "flex items-center gap-3 text-[17px] font-semibold tracking-tight text-zinc-900 dark:text-white";

/** Link com cara de ação (o "Ver …" dos cartões): texto violeta e a seta. */
export const CLASSE_LINK_ACAO = "inline-flex items-center gap-1 rounded-lg text-sm font-semibold text-indigo-700 "
  + "hover:underline dark:text-indigo-300";

/** O que a página recebe da `PaginaDaRede`. */
export interface ContextoDaPagina {
  redeId: number;
  /** O nome da rede quando já se sabe (o global, pela lista); senão `null` (ver `useNomeDaRede`). */
  nomeRede: string | null;
  global: boolean;
  /** O caminho de outra tela nova com o `?rede=` do global. */
  link: RedeDaPagina["link"];
  /** O seletor "Rede analisada" (só o global com mais de uma rede). */
  seletorRede: ReactNode;
  /** Só do global: a rede que o Painel da Rede e o Ranking da Rede abrem (ver `AvisoOutraRede`). */
  redeDoPainel: RedeDaPagina["redeDoPainel"];
}

/**
 * O envelope de toda tela principal da Secretaria. `children` só roda com a rede resolvida, e
 * a página monta com `key` da rede: trocar de rede recomeça as leituras (nada da rede anterior
 * aparece sob o nome da nova).
 */
export function PaginaDaRede({ titulo, children }: {
  titulo: string;
  children: (ctx: ContextoDaPagina) => ReactNode;
}) {
  const r = useRedeDaPagina();
  const navegar = useNavigate();
  if (r.redeId == null) {
    // Sessão ainda abrindo ou a lista do global a caminho: carregando (sem h1 provisório, que
    // seria trocado pelo da página logo depois).
    if (r.semSessao || r.carregando) return <Carregando texto="Carregando a rede..." />;
    if (r.erro) {
      return (
        <div className="space-y-4">
          <PageHeader titulo={titulo} />
          <Card className="p-2"><Erro titulo="Não foi possível carregar as redes" descricao={r.erro.message} /></Card>
        </div>
      );
    }
    return (
      <div className="space-y-4">
        <PageHeader titulo={titulo} />
        <Card>
          <Vazio
            icone={Landmark}
            titulo="Nenhuma rede disponível"
            descricao={r.global
              ? "Ainda não há redes cadastradas. Crie a primeira para ver os números da rede."
              : "Sua conta não está vinculada a uma rede/Secretaria."}
            acao={r.global ? (
              <Botao onClick={() => navegar("/rede/gerenciar")}>
                <Settings2 size={15} aria-hidden /> Gerenciar redes
              </Botao>
            ) : undefined}
          />
        </Card>
      </div>
    );
  }
  const seletorRede = r.redes && r.redes.length > 1 ? (
    <Seletor rotulo="Rede analisada" valor={String(r.redeId)} aoMudar={(v) => r.trocarRede(Number(v))}>
      {porNome(r.redes).map((rede) => <option key={rede.id} value={rede.id}>{rede.nome}</option>)}
    </Seletor>
  ) : null;
  return (
    <>
      {children({
        redeId: r.redeId, nomeRede: r.nomeRede, global: r.global, link: r.link, seletorRede, redeDoPainel: r.redeDoPainel,
      })}
    </>
  );
}

/**
 * O admin global, numa rede que NÃO é a que o Painel da Rede e o Ranking da Rede abrem (eles
 * ainda não escolhem rede): o aviso diz qual rede a tela de destino mostra — o link nunca leva
 * a outra rede em silêncio (e uma meta ou a vitrine não vão para a rede errada sem aviso). Para
 * a Secretaria, e para o global na mesma rede, nada.
 */
export function AvisoOutraRede({ ctx, tela }: { ctx: ContextoDaPagina; tela: string }) {
  const p = ctx.redeDoPainel;
  if (!ctx.global || !p || p.id === ctx.redeId) return null;
  return (
    <span className="block text-xs font-medium text-amber-800 dark:text-amber-300" data-testid="aviso-outra-rede">
      {tela} abre {p.nome ? `a rede “${p.nome}”` : "a rede padrão da sua conta"}, não a escolhida aqui: ele ainda
      não troca de rede.
    </span>
  );
}

/** O h1 da tela, a frase que diz para que ela serve, o nome da rede e (global) o seletor. */
export function CabecalhoDaPagina({ titulo, descricao, nomeRede, ctx, depois }: {
  titulo: string;
  descricao: ReactNode;
  nomeRede: string | null;
  ctx: ContextoDaPagina;
  /** O que vem logo abaixo do nome da rede (ex.: o selo de frescor). */
  depois?: ReactNode;
}) {
  return (
    <div>
      <PageHeader titulo={titulo} descricao={descricao} acoes={ctx.seletorRede || undefined} />
      {(nomeRede || depois) && (
        <div className="-mt-4 space-y-2">
          {nomeRede && (
            <p className="flex items-center gap-2 text-sm font-medium text-zinc-600 dark:text-zinc-300"
               data-testid="secretaria-rede-nome">
              <Landmark size={15} aria-hidden className="shrink-0 text-indigo-500" />
              <span className="min-w-0 break-words">{nomeRede}</span>
            </p>
          )}
          {depois}
        </div>
      )}
    </div>
  );
}

/** "O que mede: …" — a frase simples de cada indicador ou métrica (DESENHO2 §1.1). */
export function OQueMede({ texto, className = "" }: { texto: string; className?: string }) {
  return (
    <p className={`text-xs text-zinc-700 dark:text-zinc-200 ${className}`} data-o-que-mede>
      <span className="font-semibold">O que mede:</span> {texto}
    </p>
  );
}

/** Caixa informativa ("Como ler", "Antes de comparar"): ícone, título curto e o texto. */
export function ComoLer({ titulo = "Como ler", children, testId }: {
  titulo?: string;
  children: ReactNode;
  testId?: string;
}) {
  return (
    <div className="flex items-start gap-2.5 rounded-2xl border border-indigo-100 bg-indigo-50/60 px-4 py-3 text-sm text-zinc-800 dark:border-indigo-500/20 dark:bg-indigo-500/10 dark:text-zinc-100"
         data-testid={testId}>
      <Info size={16} aria-hidden className="mt-0.5 shrink-0 text-indigo-600 dark:text-indigo-300" />
      <div className="min-w-0 space-y-1 break-words">
        <p className="font-semibold">{titulo}</p>
        {children}
      </div>
    </div>
  );
}

/** A frase padrão quando avaliações externas e plataformas aparecem perto (DESENHO2 §1.4). */
export function FraseSeparacao({ anoAvaliacao, anoPlataforma }: {
  anoAvaliacao: number | null | undefined;
  anoPlataforma: number | null | undefined;
}) {
  return (
    <p className={`flex items-start gap-1.5 text-xs ${CINZA}`} data-testid="frase-separacao">
      <Info size={13} aria-hidden className="mt-0.5 shrink-0" />
      <span className="min-w-0 break-words">{fraseSeparacao(anoAvaliacao, anoPlataforma)}</span>
    </p>
  );
}

/** "Ver …" — o link de um cartão para a tela do detalhe (o nome acessível começa pelo texto). */
export function LinkVer({ para, children }: { para: string; children: ReactNode }) {
  return (
    <Link to={para} className={CLASSE_LINK_ACAO}>
      {children} <ArrowRight size={14} aria-hidden />
    </Link>
  );
}

/**
 * O PERÍODO da tela (os mesmos presets do sistema, e as datas do personalizado e do dia) — sem
 * mexer no período global: a tela abre no ano letivo e a escolha fica na URL.
 */
export function CampoPeriodo({ periodo, aoMudar }: { periodo: Periodo; aoMudar: (p: Periodo) => void }) {
  const estiloData = `${estiloInput} min-w-0 shrink-0 basis-44 dark:[color-scheme:dark]`;
  return (
    <div className="flex flex-wrap items-end gap-3" data-testid="campo-periodo">
      <Seletor rotulo="Período" valor={periodo.preset} aoMudar={(v) => aoMudar({ ...periodo, preset: v })}>
        {PRESETS_PERIODO.map((p) => <option key={p.valor} value={p.valor}>{p.rotulo}</option>)}
      </Seletor>
      <DatasDoPeriodo valor={periodo} onChange={aoMudar} estilo={estiloData}
                      classeAte="pb-3 text-sm text-zinc-500 dark:text-zinc-400" />
    </div>
  );
}

/** A SÉRIE das plataformas (vazio = do 1º ao 5º ano), ao lado do período. */
export function CampoSerie({ serie, aoMudar }: { serie: number | null; aoMudar: (s: number | null) => void }) {
  return (
    <Seletor rotulo="Série" valor={serie == null ? "" : String(serie)} aoMudar={(v) => aoMudar(v ? Number(v) : null)}>
      <option value="">1º ao 5º ano</option>
      {SERIES_DA_REDE.map((s) => <option key={s} value={s}>{rotuloSerie(s)}</option>)}
    </Seletor>
  );
}

/** Carregando ou erro de UMA leitura dentro de um bloco; com os dados, o conteúdo. */
export function EstadoDaLeitura<T>({ dados, erro, oQue, children }: {
  dados: T | null;
  erro: ApiError | null;
  /** "o uso das plataformas" — entra em "Carregando …" e "Não foi possível carregar …". */
  oQue: string;
  children: (dados: T) => ReactNode;
}) {
  if (erro && !dados) return <Mensagem tipo="erro">Não foi possível carregar {oQue}: {erro.message}</Mensagem>;
  if (!dados) return <Carregando texto={`Carregando ${oQue}...`} />;
  return <>{children(dados)}</>;
}
