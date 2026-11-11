/**
 * Selo de FRESCOR dos rankings — "de quando é este número?".
 *
 * O motor ranqueia pelo retrato mais recente de cada aluno sem olhar a idade
 * dele: uma coleta parada há três semanas dá um ranking com a mesma cara de um
 * de ontem. O backend declara a idade (`services/frescor_ranking.py`) e esta
 * peça só a mostra — nenhuma conta de data é feita aqui:
 *
 *   - `em_dia`        → selo neutro com a data do dado e a idade dele;
 *   - `parcial`       → selo + aviso: há aluno com retrato além do limite;
 *   - `desatualizado` → selo + aviso: o dado mais recente passou do limite;
 *   - `sem_dados`     → "sem dados ainda" — ausência, nunca zero.
 *
 * A data é a da última COLETA: o ajuste manual de uma criança (o botão Editar) não a
 * renova; o mais novo que a última coleta aparece à parte ("ajuste manual em …"). O
 * aviso de `parcial` diz que PARTE dos dados é antiga — numa escola sem integração ele
 * acontece sem nenhuma coleta, então o texto não fala em "coleta".
 *
 * O limite (`limite_dias`) vem da resposta: a tela não tem número próprio que
 * possa divergir do backend. Nunca diz "Funcionando": a última sincronização
 * concluída aparece como informação, não como garantia de dado atual.
 *
 * O aviso se chama "Dado com mais de N dias", não "Dados desatualizados": a tela
 * Integrações usa esta palavra com OUTRA régua (a idade da última sincronização
 * pela cadência da agenda — 2 dias na coleta diária). Com o mesmo rótulo, do 3º
 * ao 7º dia uma tela dizia "desatualizado" e a outra não avisava; a idade no
 * selo neutro ("há 3 dias") deixa as duas coerentes sem mudar nenhum limite.
 *
 * Falha ao buscar o frescor NÃO derruba o ranking e não inventa estado: o selo
 * simplesmente não aparece — nem o de outra escola (ver `SeloFrescorDaEscola`).
 */
import { AlertTriangle, CalendarClock } from "lucide-react";

import { useApp } from "../context/AppContext";
import { useApi } from "../hooks/useApi";
import { dataHora, numero } from "../lib/formato";
import type { Dimensao } from "../lib/types";

export type EstadoFrescor = "sem_dados" | "desatualizado" | "parcial" | "em_dia";

/** Forma de `frescor_ranking._bloco` (uma dimensão numa escola). */
export interface BlocoFrescor {
  plataforma: string;
  contratada: boolean;
  estado: EstadoFrescor | null;
  dado_mais_recente_em: string | null;
  dado_mais_antigo_em: string | null;
  dias_desde_dado: number | null;
  alunos_com_dado: number;
  alunos_com_dado_antigo: number;
  /** Dia do ajuste manual (botão Editar) mais novo que a última coleta da escola
   *  (inclusive o de uma criança que a coleta não trouxe): não renova a data do
   *  dado nem o estado — o selo só o menciona. */
  ajuste_manual_mais_recente_em?: string | null;
  ultima_sincronizacao_ok_em: string | null;
  dias_desde_sincronizacao_ok: number | null;
}

/** Forma de `frescor_ranking.frescor_da_escola`. */
export interface Frescor {
  limite_dias: number;
  hoje: string;
  estado: EstadoFrescor;
  dimensoes: Record<Dimensao, BlocoFrescor>;
}

const ROTULO: Record<Dimensao, string> = { leitura: "Leitura", matematica: "Matemática" };
const PLATAFORMA: Record<string, string> = { elefante: "Elefante Letrado", matific: "Matific" };

/** "2026-10-05" → "05/10/2026", sem passar por `Date` (nada de fuso num dia). */
export function dataDoDia(iso: string | null): string {
  if (!iso) return "—";
  const [ano, mes, dia] = iso.slice(0, 10).split("-");
  return ano && mes && dia ? `${dia}/${mes}/${ano}` : iso;
}

function dias(n: number): string {
  return n === 1 ? "1 dia" : `${numero(n)} dias`;
}

/** " (hoje)" / " (há N dias)" a partir de `dias_desde_dado`, que vem pronto do
 *  backend no dia de Brasília. Valor ausente ou negativo (relógio adiantado em
 *  algum lado) não vira texto: melhor não dizer a idade do que inventá-la. */
function idade(n: number | null): string {
  if (n == null || n < 0) return "";
  return n === 0 ? " (hoje)" : ` (há ${dias(n)})`;
}

function LinhaDimensao({ dimensao, bloco, limite }: {
  dimensao: Dimensao; bloco: BlocoFrescor; limite: number;
}) {
  const nome = `${ROTULO[dimensao]} (${PLATAFORMA[bloco.plataforma] ?? bloco.plataforma})`;
  const sync = bloco.ultima_sincronizacao_ok_em
    ? `Última sincronização com dado aplicado: ${dataHora(bloco.ultima_sincronizacao_ok_em)}.`
    : "Nenhuma sincronização automática concluída — o dado veio por importação.";

  if (bloco.estado === "sem_dados") {
    return (
      <p className="flex items-center gap-1.5 text-xs text-zinc-500 dark:text-zinc-400">
        <CalendarClock size={13} aria-hidden className="shrink-0 text-zinc-400" /> {nome}: sem dados ainda.
      </p>
    );
  }

  const selo = (
    // Pílula discreta da identidade v2 (é o "atualizado em…" das referências, mas com
    // a data e a idade do DADO — nunca um "Atualizado" genérico).
    <span
      className="inline-flex max-w-full items-center gap-1.5 rounded-full border border-zinc-200/80 bg-white px-3 py-1 text-xs font-medium text-zinc-600 shadow-cartao dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300 dark:shadow-none"
      title={sync}
    >
      <CalendarClock size={13} aria-hidden className="shrink-0 text-indigo-500 dark:text-indigo-300" />
      {nome}: dados de {dataDoDia(bloco.dado_mais_recente_em)}{idade(bloco.dias_desde_dado)}
      {bloco.ajuste_manual_mais_recente_em
        ? `; ajuste manual em ${dataDoDia(bloco.ajuste_manual_mais_recente_em)}` : null}
    </span>
  );

  if (bloco.estado === "em_dia") return <div>{selo}</div>;

  const aviso = bloco.estado === "desatualizado"
    ? <>
        Dado com mais de {dias(limite)}: o mais recente é de{" "}
        {dataDoDia(bloco.dado_mais_recente_em)}{idade(bloco.dias_desde_dado)}. Este ranking
        pode não refletir a situação atual.
      </>
    : <>
        Parte dos dados é antiga: {numero(bloco.alunos_com_dado_antigo)} de {numero(bloco.alunos_com_dado)} aluno(s)
        têm o último dado de antes de {dias(limite)} atrás (o mais antigo é de{" "}
        {dataDoDia(bloco.dado_mais_antigo_em)}) — a posição deles reflete um retrato antigo.
      </>;

  return (
    <div className="space-y-1">
      {selo}
      <p
        role="status"
        className="flex items-start gap-2 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-relaxed text-amber-800 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200"
      >
        <AlertTriangle size={14} className="mt-0.5 shrink-0" aria-hidden />
        <span>{aviso} {sync}</span>
      </p>
    </div>
  );
}

/** Selo apresentacional: recebe o bloco `frescor` já carregado. */
export function SeloFrescor({ frescor, dimensoes }: {
  frescor: Frescor | null | undefined;
  /** Quais dimensões este ranking usa (só as contratadas aparecem). */
  dimensoes: Dimensao[];
}) {
  if (!frescor) return null;
  const linhas = dimensoes
    .map((d) => [d, frescor.dimensoes?.[d]] as const)
    .filter(([, bloco]) => bloco?.contratada && bloco.estado);
  if (linhas.length === 0) return null;
  return (
    <div aria-label="Data dos dados" className="mb-3 space-y-1.5">
      {linhas.map(([d, bloco]) => (
        <LinhaDimensao key={d} dimensao={d} bloco={bloco!} limite={frescor.limite_dias} />
      ))}
    </div>
  );
}

/** Selo que busca o frescor da escola selecionada (`/ranking/frescor`).
 *
 *  Uma instância POR ESCOLA (`key`): as telas de ranking não são remontadas na
 *  troca de escola, e o `useApi` guarda o último `dados` ao mudar de URL e ao
 *  falhar. Sem a chave, o selo "em dia" da escola A ficava no ranking da B
 *  enquanto a busca corria — e para sempre se ela falhasse —, uma garantia de
 *  dado atual justamente onde a coleta pode estar parada. */
export function SeloFrescorDaEscola({ dimensoes }: { dimensoes: Dimensao[] }) {
  const { escolaId } = useApp();
  if (!escolaId) return null;
  return <SeloBuscado key={escolaId} escolaId={escolaId} dimensoes={dimensoes} />;
}

function SeloBuscado({ escolaId, dimensoes }: { escolaId: number; dimensoes: Dimensao[] }) {
  const { dados, erro } = useApi<Frescor>(
    `/escolas/${escolaId}/ranking/frescor`, { cacheMs: 60_000, tentativas: 0 });
  if (erro) return null;
  return <SeloFrescor frescor={dados} dimensoes={dimensoes} />;
}

/** Forma de `GET /redes/{id}/ranking/frescor` (um bloco `Frescor` por escola). */
export interface FrescorRede {
  limite_dias: number;
  hoje: string;
  escolas: (Frescor & { escola_id: number; nome: string })[];
}

/** Frescor da REDE para os painéis da Secretaria (`/redes/{id}/ranking/frescor`).
 *
 *  Com `escolaId`: o selo daquela escola (o panorama de UMA escola da rede).
 *  Sem: a faixa de datas do dado entre as escolas, por dimensão, e — quando há —
 *  quais escolas passaram do limite (ou têm parte dos dados antiga). As médias e os
 *  totais do painel somam escolas com dados de dias diferentes; sem isto, a
 *  escola parada há três semanas entrava na média com a mesma cara das outras.
 *  Falha ao buscar: nada aparece (não derruba o painel nem inventa estado).
 *  Uma instância por rede/escola (`key`), pela mesma razão de `SeloFrescorDaEscola`. */
export function SeloFrescorDaRede({ redeId, escolaId, dimensoes }: {
  redeId: number; escolaId?: number; dimensoes: Dimensao[];
}) {
  return <SeloDaRede key={`${redeId}:${escolaId ?? "rede"}`} redeId={redeId}
                     escolaId={escolaId} dimensoes={dimensoes} />;
}

function SeloDaRede({ redeId, escolaId, dimensoes }: {
  redeId: number; escolaId?: number; dimensoes: Dimensao[];
}) {
  const { dados, erro } = useApi<FrescorRede>(
    `/redes/${redeId}/ranking/frescor`, { cacheMs: 60_000, tentativas: 0 });
  if (erro || !dados) return null;
  if (escolaId != null) {
    const daEscola = dados.escolas.find((e) => e.escola_id === escolaId);
    return <SeloFrescor frescor={daEscola} dimensoes={dimensoes} />;
  }
  const faixas = dimensoes.map((d) => {
    const dias = dados.escolas
      .map((e) => e.dimensoes?.[d])
      .filter((b) => b?.contratada && b.estado && b.estado !== "sem_dados" && b.dado_mais_recente_em)
      .map((b) => b!.dado_mais_recente_em!.slice(0, 10))
      .sort();
    return { d, de: dias[0] ?? null, ate: dias[dias.length - 1] ?? null };
  }).filter((f) => f.de);
  const atrasadas = dados.escolas.filter((e) => dimensoes.some((d) => {
    const b = e.dimensoes?.[d];
    return b?.contratada && (b.estado === "desatualizado" || b.estado === "parcial");
  }));
  if (faixas.length === 0) return null;
  return (
    <div aria-label="Data dos dados" className="space-y-1.5">
      {faixas.map(({ d, de, ate }) => (
        <p key={d} className="flex items-center gap-1.5 text-xs font-medium text-zinc-600 dark:text-zinc-300">
          <CalendarClock size={13} aria-hidden className="shrink-0 text-indigo-500 dark:text-indigo-300" />
          {ROTULO[d]}: dados das escolas {de === ate ? `de ${dataDoDia(de)}` : `de ${dataDoDia(de)} a ${dataDoDia(ate)}`}
        </p>
      ))}
      {atrasadas.length > 0 && (
        <p
          role="status"
          className="flex items-start gap-2 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-relaxed text-amber-800 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200"
        >
          <AlertTriangle size={14} className="mt-0.5 shrink-0" aria-hidden />
          <span>
            {numero(atrasadas.length)} escola(s) com dado de mais de {dias(dados.limite_dias)} (ou parte
            dos dados antiga) entram nestes números com um retrato antigo: {atrasadas.map((e) => e.nome).join("; ")}.
          </span>
        </p>
      )}
    </div>
  );
}
