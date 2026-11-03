/**
 * A REDE de cada tela principal da Secretaria (DESENHO2 §2.3) e o PERÍODO das plataformas
 * dessas telas.
 *
 * Rede: a Secretaria usa a dela (`usuario.rede_id`); o admin global usa a do `?rede=`, senão a
 * dele, senão a primeira em ordem alfabética — o mesmo padrão da Análise educacional (com o
 * seletor "Rede analisada" quando há mais de uma). Os links entre as telas novas levam o
 * `?rede=` do global (`link`): ele não cai em outra rede ao trocar de tela.
 *
 * Período: as telas novas abrem SEMPRE no ano letivo (o padrão do desenho) e não no período
 * global do sistema — o Panorama diz "no ano letivo", e uma escolha de "Este mês" feita na
 * área avançada não pode mudar isso por baixo. Onde há seletor (Elefante e Matific, a aba
 * das plataformas no Comparar escolas, o CSV das plataformas), a escolha fica na URL
 * (`?periodo=&inicio=&fim=`): recarregar ou compartilhar o link mantém o recorte.
 */
import { useCallback } from "react";
import { useSearchParams } from "react-router-dom";

import { PRESETS_PERIODO, type Periodo } from "../../../components/SeletorPeriodo";
import { useApp } from "../../../context/AppContext";
import { useApi } from "../../../hooks/useApi";
import { usePerfil } from "../../../hooks/usePerfil";
import type { ApiError } from "../../../lib/api";
import { useApiExata } from "../../analise/comum";
import { porNome } from "../../analise/formato";
import type { JanelaAnalise, RespostaIndicadoresRede } from "../../analise/tipos";
import type { DashboardRede, DestaquesRede } from "../comum";

export interface RedeResumo {
  id: number;
  nome: string;
}

export interface RedeDaPagina {
  redeId: number | null;
  /** O nome da rede escolhida quando já se sabe (o global, pela lista); a Secretaria lê com
   *  `useNomeDaRede`. */
  nomeRede: string | null;
  /** Só do admin global (a Secretaria não lista redes). */
  redes: RedeResumo[] | null;
  global: boolean;
  carregando: boolean;
  erro: ApiError | null;
  /** A sessão ainda abrindo (o perfil decide se há rede). */
  semSessao: boolean;
  trocarRede: (id: number) => void;
  /** O caminho de outra tela nova com o `?rede=` do global (a Secretaria não precisa). */
  link: (caminho: string, extras?: Record<string, string | null | undefined>) => string;
  /**
   * Só do global: a rede que o Painel da Rede (`/rede`) e o Ranking da Rede (`/rede/ranking`)
   * abrem — eles ainda não escolhem rede (`EnvolucroRede`: a rede da conta, senão a primeira da
   * lista do servidor). As telas novas avisam quando ela não é a rede escolhida aqui.
   */
  redeDoPainel: { id: number; nome: string | null } | null;
}

const numeroOuNull = (v: string | null): number | null => {
  if (v == null || v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
};

/** Monta "caminho?a=1&b=2" (o caminho pode já trazer consulta). Valor vazio não entra. */
export function comConsulta(caminho: string, extras: Record<string, string | null | undefined>): string {
  const [base, consulta = ""] = caminho.split("?");
  const q = new URLSearchParams(consulta);
  for (const [k, v] of Object.entries(extras)) {
    if (v == null || v === "") q.delete(k);
    else q.set(k, v);
  }
  const texto = q.toString();
  return texto ? `${base}?${texto}` : base;
}

export function useRedeDaPagina(): RedeDaPagina {
  const { usuario } = useApp();
  const { global } = usePerfil();
  const [params, setParams] = useSearchParams();
  // O admin global escolhe a rede (GET /redes devolve todas); a Secretaria usa a dela.
  const { dados: redes, carregando, erro } = useApi<RedeResumo[]>(global ? "/redes" : null);
  const redeUrl = numeroOuNull(params.get("rede"));
  const redeId = global
    ? (redes?.find((r) => r.id === redeUrl)?.id
      ?? redes?.find((r) => r.id === usuario?.rede_id)?.id
      ?? (redes ? porNome(redes)[0]?.id : undefined)
      ?? null)
    : usuario?.rede_id ?? null;

  const trocarRede = useCallback((id: number) => {
    const prox = new URLSearchParams(params);
    prox.set("rede", String(id));
    // A escola e o indicador de uma rede não valem na outra.
    prox.delete("escola");
    setParams(prox, { replace: true });
  }, [params, setParams]);

  const link = useCallback((caminho: string, extras: Record<string, string | null | undefined> = {}) =>
    comConsulta(caminho, { ...extras, ...(global && redeId != null ? { rede: String(redeId) } : {}) }),
  [global, redeId]);
  // A mesma regra do `EnvolucroRede` (rede/comum.tsx): a da conta ou a PRIMEIRA da lista, na
  // ordem do servidor (não a ordem alfabética daqui).
  const idDoPainel = global ? usuario?.rede_id ?? redes?.[0]?.id ?? null : null;
  const redeDoPainel = idDoPainel != null
    ? { id: idDoPainel, nome: redes?.find((r) => r.id === idDoPainel)?.nome ?? null } : null;

  return {
    redeId,
    nomeRede: global ? redes?.find((r) => r.id === redeId)?.nome ?? null : null,
    redes: global ? redes : null,
    global,
    // Sem a lista ainda (inclusive no 1º render, antes do pedido sair) é carregando.
    carregando: global && (carregando || (!redes && !erro)),
    erro: global ? erro : null,
    semSessao: !usuario,
    trocarRede,
    link,
    redeDoPainel,
  };
}

/**
 * O catálogo da análise (`/redes/{id}/analise/indicadores`): o nome da rede, os indicadores
 * oficiais com a disponibilidade, os destaques, as escolas e os alertas. Leitura leve, a mesma
 * da Análise educacional; só entrega a resposta DESTA rede.
 */
export function useCatalogo(redeId: number) {
  const r = useApiExata<RespostaIndicadoresRede>(`/redes/${redeId}/analise/indicadores`);
  return { ...r, dados: r.dados && r.dados.rede.id === redeId ? r.dados : null };
}

/**
 * O nome da rede para o cabeçalho: o que a página já sabe (o global, pela lista de redes);
 * senão, `GET /redes` — leitura leve, que para a Secretaria devolve só a rede dela.
 */
export function useNomeDaRede(redeId: number, conhecido: string | null): string | null {
  const { dados } = useApi<RedeResumo[]>(conhecido == null ? "/redes" : null);
  return conhecido ?? dados?.find((r) => r.id === redeId)?.nome ?? null;
}

/**
 * O painel da rede (`/redes/{id}/dashboard`): TODAS as escolas cadastradas (ativas ou não,
 * com ou sem alunos), o cadastro de cada uma e os totais (`escolas`, `escolas_ativas`). Só a
 * resposta DESTA rede; cache curto (o Panorama e a ficha da escola leem o mesmo).
 */
export function useDashboardDaRede(redeId: number) {
  const r = useApiExata<DashboardRede>(`/redes/${redeId}/dashboard`, { cacheMs: 60_000 });
  return { ...r, dados: r.dados && r.dados.rede_id === redeId ? r.dados : null };
}

/**
 * As ESCOLAS EM DESTAQUE (`/redes/{id}/destaques`, DESENHO3 §6): as mesmas da vitrine
 * pública, pelo mesmo critério, com o `escola_id` (para levar à ficha). Só leitura.
 */
export function useDestaques(redeId: number) {
  return useApiExata<DestaquesRede>(`/redes/${redeId}/destaques`);
}

/** O ano letivo de uma janela das plataformas (o do serviço; senão, o ano do início). */
export function anoDaJanela(janela: JanelaAnalise | null | undefined): number | null {
  if (!janela) return null;
  if (janela.ano_letivo != null) return janela.ano_letivo;
  const ano = Number(janela.inicio?.slice(0, 4));
  return Number.isFinite(ano) && ano > 0 ? ano : null;
}

// --- Período das plataformas nas telas novas ----------------------------------------------

export const ANO_LETIVO: Periodo = { preset: "ano_letivo" };

const PRESETS_VALIDOS = new Set<string>([...PRESETS_PERIODO.map((p) => p.valor), "dia"]);

/** O período da URL (`?periodo=&inicio=&fim=`); sem ele (ou inválido), o ano letivo. */
export function periodoDaUrl(params: URLSearchParams): Periodo {
  const preset = params.get("periodo");
  if (!preset || !PRESETS_VALIDOS.has(preset)) return ANO_LETIVO;
  if (preset === "personalizado") {
    return { preset, inicio: params.get("inicio") ?? undefined, fim: params.get("fim") ?? undefined };
  }
  if (preset === "dia") return { preset, inicio: params.get("inicio") ?? undefined };
  return { preset };
}

/** Os parâmetros de URL de um período (o ano letivo, padrão, não vai para a URL). */
export function periodoParaUrl(p: Periodo): Record<string, string | null> {
  if (p.preset === "ano_letivo") return { periodo: null, inicio: null, fim: null };
  return {
    periodo: p.preset,
    inicio: p.preset === "personalizado" || p.preset === "dia" ? p.inicio ?? null : null,
    fim: p.preset === "personalizado" ? p.fim ?? null : null,
  };
}

// --- Série das plataformas nas telas novas ------------------------------------------------

/** As séries das plataformas (do 1º ao 5º ano). */
export const SERIES_DA_REDE = [1, 2, 3, 4, 5];

/**
 * A SÉRIE das plataformas na tela (`?serie=`, só do 1º ao 5º ano; sem ela ou inválida, todas) e
 * como trocá-la — o recorte que a aba antiga das plataformas tinha (cartões, escolas, CSV). Na
 * URL: o link antigo `/rede/analise?ver=plataformas&serie=2` chega com ela.
 */
export function useSerieDaPagina(): [number | null, (s: number | null) => void] {
  const [params, setParams] = useSearchParams();
  const v = numeroOuNull(params.get("serie"));
  const serie = v != null && SERIES_DA_REDE.includes(v) ? v : null;
  const definir = useCallback((s: number | null) => {
    const prox = new URLSearchParams(params);
    if (s == null) prox.delete("serie");
    else prox.set("serie", String(s));
    setParams(prox, { replace: true });
  }, [params, setParams]);
  return [serie, definir];
}

/** O período da tela (na URL) e como trocá-lo — sem mexer no período global do sistema. */
export function usePeriodoDaPagina(): [Periodo, (p: Periodo) => void] {
  const [params, setParams] = useSearchParams();
  const periodo = periodoDaUrl(params);
  const definir = useCallback((p: Periodo) => {
    setParams(new URLSearchParams(comConsulta(`?${params.toString()}`, periodoParaUrl(p)).split("?")[1] ?? ""),
              { replace: true });
  }, [params, setParams]);
  return [periodo, definir];
}
