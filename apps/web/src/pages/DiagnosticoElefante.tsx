/**
 * Diagnóstico da Integração Elefante (admin) — ferramenta OFICIAL de investigação
 * e manutenção. Executa a auto-investigação usando a sessão autenticada do robô
 * (sem crawler nem F12) e mostra endpoints, parâmetros, períodos, paginação,
 * estrutura (tipos/chaves, sem dado de criança) e o que MUDOU desde o último
 * inventário. Nada é público; só admin/coordenador acessa.
 */
import { AlertTriangle, PlayCircle, Radar, RefreshCw } from "lucide-react";
import { useState } from "react";

import { Card, Carregando, PageHeader, Vazio } from "../components/ui";
import { useApp } from "../context/AppContext";
import { useMutation } from "../hooks/useMutation";
import { api } from "../lib/api";

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

function BadgeStatus({ status }: { status: number | null }) {
  const ok = status === 200;
  const cor = ok
    ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300"
    : "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300";
  return <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${cor}`}>{status ?? "—"}</span>;
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
        descricao="Investiga a API do Elefante usando a sessão autenticada do robô — sem crawler nem F12. Mostra endpoints, parâmetros, períodos, paginação, a estrutura (sem dado de aluno) e o que mudou desde o último diagnóstico."
      />

      <Card className="mb-4 flex flex-wrap items-center gap-3 p-4">
        <button
          type="button"
          onClick={executar}
          disabled={diag.enviando}
          className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
        >
          {diag.enviando
            ? <><RefreshCw size={15} className="animate-spin" /> Investigando…</>
            : <><PlayCircle size={16} /> {res ? "Executar de novo" : "Executar diagnóstico"}</>}
        </button>
        {res?.inventario.gerado_em && !diag.enviando && (
          <span className="inline-flex items-center gap-1.5 text-xs text-zinc-500 dark:text-zinc-400">
            <Radar size={13} /> Gerado em {new Date(res.inventario.gerado_em).toLocaleString("pt-BR")}
            {res.anterior_em && ` · anterior: ${new Date(res.anterior_em).toLocaleString("pt-BR")}`}
          </span>
        )}
      </Card>

      {diag.enviando ? (
        <Card>
          <div className="flex flex-col items-center gap-2 py-10 text-center">
            <Carregando />
            <p className="text-sm text-zinc-500 dark:text-zinc-400">
              O robô está logando no Elefante e sondando os endpoints…
            </p>
            <p className="max-w-md text-xs text-zinc-400">Pode levar cerca de um minuto.</p>
          </div>
        </Card>
      ) : diag.erro ? (
        <Vazio titulo="Não foi possível executar o diagnóstico" descricao={diag.erro.message} />
      ) : !res ? (
        <Vazio titulo="Nenhum diagnóstico ainda"
               descricao="Clique em “Executar diagnóstico” para investigar a API do Elefante." />
      ) : !inv?.ok ? (
        <Vazio titulo="A investigação não concluiu" descricao={inv?.erro ?? "Tente novamente."} />
      ) : (
        <div className="flex flex-col gap-4">
          {/* Avisos de mudança da API */}
          {diff && (diff.avisos.length > 0) && (
            <Card className={`p-4 ${temMudanca ? "border-amber-300 dark:border-amber-700" : ""}`}>
              <div className="mb-1 flex items-center gap-2 text-sm font-medium">
                <AlertTriangle size={15} className={temMudanca ? "text-amber-500" : "text-zinc-400"} />
                {temMudanca ? "Mudanças detectadas na API" : "Comparação com o último inventário"}
              </div>
              <ul className="list-inside list-disc text-sm text-zinc-600 dark:text-zinc-300">
                {diff.avisos.map((a, i) => <li key={i}>{a}</li>)}
              </ul>
            </Card>
          )}

          {/* Resumo */}
          <Card className="flex flex-wrap gap-x-6 gap-y-1 p-4 text-sm">
            <span><b>{inv.turmas}</b> turma(s) vistas</span>
            <span>Autenticação: <b>{inv.auth === "jwt" ? "JWT (Bearer)" : "cookie"}</b></span>
            <span>Aceita datas personalizadas: <b>{inv.aceita_datas_personalizadas ? "sim" : "não"}</b></span>
            <span>Períodos no tráfego: <b>{inv.periodos_no_trafego.join(", ") || "—"}</b></span>
          </Card>

          {/* Endpoints */}
          {inv.endpoints.map((e) => (
            <Card key={e.nome} className="p-4">
              <div className="mb-2 flex flex-wrap items-center gap-2">
                <span className="rounded bg-zinc-100 px-1.5 py-0.5 font-mono text-xs dark:bg-zinc-800">{e.metodo}</span>
                <span className="font-medium">{e.nome}</span>
                <BadgeStatus status={e.status} />
                {e.rota && <span className="font-mono text-xs text-zinc-400">{e.rota}</span>}
              </div>
              {e.erro && <p className="text-sm text-amber-600 dark:text-amber-400">⚠️ {e.erro}</p>}
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
                <pre className="mt-2 max-h-64 overflow-auto rounded bg-zinc-50 p-2 text-xs text-zinc-700 dark:bg-zinc-900 dark:text-zinc-300">
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
