/**
 * Diagnóstico da Integração Elefante (admin) — ferramenta OFICIAL de investigação
 * e manutenção. Executa a auto-investigação usando a sessão autenticada do robô
 * (sem crawler nem F12) e mostra endpoints, parâmetros, períodos, paginação,
 * estrutura (tipos/chaves, sem dado de criança) e o que MUDOU desde o último
 * inventário. Nada é público; só admin/coordenador acessa.
 *
 * Identidade v2 só na casca (é uma tela técnica, não se gamifica): cartões de 20 px,
 * botão violeta, pílulas de status e datas no horário de Brasília (`dataHora`, como o
 * resto do sistema — antes era o fuso do navegador).
 */
import { AlertTriangle, ArrowLeft, CalendarRange, KeyRound, Layers, PlayCircle, Radar, RefreshCw } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import {
  Badge, Botao, Card, Erro, ESTILOS_BOTAO, IconePastel, PageHeader, TAMANHOS_BOTAO, Vazio, type TomPastel,
} from "../components/ui";
import { useApp } from "../context/AppContext";
import { useMutation } from "../hooks/useMutation";
import { api } from "../lib/api";
import { dataHora } from "../lib/formato";

type Paginacao = {
  formato: string;
  chaves_paginacao: string[];
  lista_em?: string | null;
  itens?: number | null;
};
type Endpoint = {
  nome: string;
  metodo: string;
  rota?: string;
  status: number | null;
  parametros?: string[];
  erro?: string;
  estrutura?: string;
  paginacao?: Paginacao;
};
type Inventario = {
  ok: boolean;
  erro?: string;
  turmas: number;
  auth?: string;
  aceita_datas_personalizadas?: boolean;
  periodos_no_trafego: string[];
  endpoints: Endpoint[];
  gerado_em?: string;
};
type Diff = {
  primeira_vez: boolean;
  novos_endpoints: string[];
  endpoints_sumidos: string[];
  estrutura_mudou: string[];
  avisos: string[];
};
type Resultado = { inventario: Inventario; diff: Diff; anterior_em?: string | null };

/** Status HTTP em pílula: 200 verde; qualquer outro (ou sem resposta) âmbar. */
function BadgeStatus({ status }: { status: number | null }) {
  return <Badge tom={status === 200 ? "ok" : "alerta"}>{status ?? "—"}</Badge>;
}

function Resumo({ icone, tom, rotulo, valor }: { icone: LucideIcon; tom: TomPastel; rotulo: string; valor: string }) {
  return (
    <div className="flex min-w-0 items-center gap-3 rounded-2xl bg-zinc-50 p-4 dark:bg-zinc-800/50">
      <IconePastel icone={icone} tom={tom} tamanho="sm" />
      <div className="min-w-0">
        <p className="text-xs font-medium text-zinc-500 dark:text-zinc-400">{rotulo}</p>
        <p className="break-words text-[15px] font-semibold text-zinc-900 dark:text-white">{valor}</p>
      </div>
    </div>
  );
}

export default function DiagnosticoElefante() {
  const { escolaId, usuario } = useApp();
  const gestor = Boolean(usuario?.is_global) ||
    ["admin", "coordenador"].includes(usuario?.cargo ?? "");
  const [res, setRes] = useState<Resultado | null>(null);

  const diag = useMutation(async () => {
    const r = await api(`/escolas/${escolaId}/sync/elefante/diagnostico`, { method: "POST" });
    return r as Resultado;
  });

  const executar = async () => {
    const r = await diag.executar();
    if (r) setRes(r);
  };

  if (!gestor) {
    return <Vazio titulo="Acesso restrito"
                  descricao="O diagnóstico da integração é exclusivo de administradores." />;
  }

  const inv = res?.inventario;
  const diff = res?.diff;
  const temMudanca = diff && !diff.primeira_vez &&
    (diff.novos_endpoints.length || diff.endpoints_sumidos.length || diff.estrutura_mudou.length);

  return (
    <div>
      <PageHeader
        titulo="Diagnóstico da Integração Elefante"
        descricao="Ferramenta técnica para verificar se o Constela consegue ler os dados do Elefante Letrado; não é necessária no dia a dia. Investiga a API usando a sessão autenticada do robô e mostra endpoints, parâmetros, períodos, paginação, a estrutura (sem dado de aluno) e o que mudou desde o último diagnóstico."
        acoes={
          <Link
            to="/sincronizacao"
            className={`inline-flex items-center justify-center font-semibold transition-colors ${TAMANHOS_BOTAO.md} ${ESTILOS_BOTAO.secundario}`}
          >
            <ArrowLeft size={15} aria-hidden /> Voltar para Integrações
          </Link>
        }
      />

      <Card className="mb-5 flex flex-wrap items-center gap-4 p-5">
        <IconePastel icone={Radar} tom="violeta" tamanho="lg" />
        <Botao onClick={executar} disabled={diag.enviando} aria-busy={diag.enviando}>
          {diag.enviando
            ? <><RefreshCw size={15} aria-hidden className="animate-spin motion-reduce:animate-none" /> Investigando…</>
            : <><PlayCircle size={16} aria-hidden /> {res ? "Executar de novo" : "Executar diagnóstico"}</>}
        </Botao>
        {res?.inventario.gerado_em && !diag.enviando && (
          <span className="text-sm text-zinc-600 dark:text-zinc-300">
            Gerado em <strong>{dataHora(res.inventario.gerado_em)}</strong>
            {res.anterior_em && <> · anterior: {dataHora(res.anterior_em)}</>}
          </span>
        )}
      </Card>

      {diag.enviando ? (
        <Card>
          <div role="status" className="flex flex-col items-center gap-3 py-14 text-center">
            <span aria-hidden className="h-8 w-8 animate-spin rounded-full border-[3px] border-indigo-100 border-t-indigo-600 motion-reduce:animate-none dark:border-zinc-700 dark:border-t-indigo-400" />
            <p className="text-sm font-medium text-zinc-700 dark:text-zinc-200">
              O robô está logando no Elefante e sondando os endpoints…
            </p>
            <p className="max-w-md text-xs text-zinc-500 dark:text-zinc-400">Pode levar cerca de um minuto.</p>
          </div>
        </Card>
      ) : diag.erro ? (
        <Card>
          <Erro titulo="Não foi possível executar o diagnóstico" descricao={diag.erro.message}
                aoTentar={() => { void executar(); }} />
        </Card>
      ) : !res ? (
        <Card>
          <Vazio icone={Radar} titulo="Nenhum diagnóstico ainda"
                 descricao="Clique em “Executar diagnóstico” para investigar a API do Elefante." />
        </Card>
      ) : !inv?.ok ? (
        <Card>
          <Vazio icone={AlertTriangle} titulo="A investigação não concluiu" descricao={inv?.erro ?? "Tente novamente."} />
        </Card>
      ) : (
        <div className="flex flex-col gap-5">
          {/* Avisos de mudança da API */}
          {diff && (diff.avisos.length > 0) && (
            <Card className={`p-5 ${temMudanca ? "border-ouro-300 dark:border-ouro-400/40" : ""}`}>
              <div className="mb-2 flex items-center gap-3 text-[15px] font-semibold text-zinc-900 dark:text-white">
                <IconePastel icone={AlertTriangle} tom={temMudanca ? "ambar" : "neutro"} tamanho="sm" />
                {temMudanca ? "Mudanças detectadas na API" : "Comparação com o último inventário"}
              </div>
              <ul className="list-inside list-disc space-y-0.5 text-sm text-zinc-700 dark:text-zinc-300">
                {diff.avisos.map((a, i) => <li key={i}>{a}</li>)}
              </ul>
            </Card>
          )}

          {/* Resumo */}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <Resumo icone={Layers} tom="violeta" rotulo="Turmas vistas" valor={`${inv.turmas} turma(s)`} />
            <Resumo icone={KeyRound} tom="azul" rotulo="Autenticação" valor={inv.auth === "jwt" ? "JWT (Bearer)" : "cookie"} />
            <Resumo icone={CalendarRange} tom="teal" rotulo="Aceita datas personalizadas"
                    valor={inv.aceita_datas_personalizadas ? "sim" : "não"} />
            <Resumo icone={RefreshCw} tom="neutro" rotulo="Períodos no tráfego"
                    valor={inv.periodos_no_trafego.join(", ") || "—"} />
          </div>

          {/* Endpoints */}
          {inv.endpoints.map((e) => (
            <Card key={e.nome} className="p-5">
              <div className="mb-2 flex flex-wrap items-center gap-2">
                <span className="rounded-lg bg-indigo-50 px-2 py-0.5 font-mono text-xs font-semibold text-indigo-700 dark:bg-indigo-500/15 dark:text-indigo-300">{e.metodo}</span>
                <span className="font-semibold text-zinc-900 dark:text-white">{e.nome}</span>
                <BadgeStatus status={e.status} />
                {e.rota && <span className="break-all font-mono text-xs text-zinc-500 dark:text-zinc-400">{e.rota}</span>}
              </div>
              {e.erro && (
                <p className="flex items-start gap-1.5 text-sm text-ouro-700 dark:text-ouro-300">
                  <AlertTriangle size={14} aria-hidden className="mt-0.5 shrink-0" /> {e.erro}
                </p>
              )}
              {(e.parametros?.length ?? 0) > 0 && (
                <p className="text-xs text-zinc-500 dark:text-zinc-400">
                  Parâmetros: <span className="font-mono">{e.parametros!.join(", ")}</span>
                </p>
              )}
              {e.paginacao && (
                <p className="text-xs text-zinc-500 dark:text-zinc-400">
                  Paginação: {e.paginacao.formato}
                  {e.paginacao.lista_em && ` · lista em "${e.paginacao.lista_em}"`}
                  {typeof e.paginacao.itens === "number" && ` · ${e.paginacao.itens} item(ns)`}
                  {(e.paginacao.chaves_paginacao.length > 0) &&
                    ` · chaves: ${e.paginacao.chaves_paginacao.join(", ")}`}
                </p>
              )}
              {e.estrutura && (
                <pre className="mt-3 max-h-64 overflow-auto rounded-xl bg-zinc-50 p-3 text-xs text-zinc-700 dark:bg-zinc-950 dark:text-zinc-300">
                  {e.estrutura}
                </pre>
              )}
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
