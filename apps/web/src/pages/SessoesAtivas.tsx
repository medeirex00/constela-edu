/**
 * Monitor de Sessões Ativas — EXCLUSIVO do Administrador Global.
 *
 * Mostra, em tempo quase real, quem está com o sistema aberto: nome, cargo,
 * escola, status (🟢 online / ⚪ offline), última atividade ("há 2 min") e o
 * último acesso (data/hora). "Online" é decidido no servidor pela janela de
 * presença (heartbeat recente). A tela faz *polling* leve (a cada 15 s) e
 * mantém a tabela na tela enquanto atualiza por baixo — sem piscar.
 */
import { RefreshCw, Search, Users } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { Badge, Botao, Card, Carregando, PageHeader, Vazio, estiloInput } from "../components/ui";
import { useApi } from "../hooks/useApi";
import { dataHora } from "../lib/formato";
import { normalizar } from "../lib/nomes";

interface Sessao {
  id: number;
  nome: string;
  email: string;
  cargo: string;
  is_global: boolean;
  rede_id: number | null;
  escola_id: number | null;
  escola_nome: string | null;
  status: string;
  online: boolean;
  visto_em: string | null;
  ultimo_acesso: string | null;
}

interface Sessoes {
  agora: string;
  limiar_online_seg: number;
  total: number;
  online: number;
  sessoes: Sessao[];
}

type Filtro = "todos" | "online" | "offline";

const INTERVALO_POLL_MS = 15_000;

/** Rótulo do papel — o que o gestor entende, não o enum cru do banco. */
function papel(s: Sessao): string {
  if (s.is_global) return "Admin Global";
  if (s.rede_id != null) return "Secretaria";
  if (s.cargo === "admin") return "Administrador";
  if (s.cargo === "coordenador") return "Coordenador";
  if (s.cargo === "professor") return "Professor";
  return s.cargo;
}

/** "há 2 min" a partir do relógio do SERVIDOR (imune ao relógio do navegador).
 *  Ambos os instantes vêm da API com fuso explícito, então `Date` os lê certo. */
function haQuanto(agoraIso: string, alvoIso: string | null): string {
  if (!alvoIso) return "nunca";
  const seg = Math.max(
    0,
    Math.round((new Date(agoraIso).getTime() - new Date(alvoIso).getTime()) / 1000),
  );
  if (seg < 60) return "agora mesmo";
  const min = Math.round(seg / 60);
  if (min < 60) return `há ${min} min`;
  const h = Math.floor(min / 60);
  if (h < 24) return `há ${h} h`;
  const d = Math.floor(h / 24);
  return d === 1 ? "há 1 dia" : `há ${d} dias`;
}

/** Bolinha de status com legenda (verde pulsante = online, cinza = offline). */
function StatusPresenca({ online }: { online: boolean }) {
  return (
    <span className="inline-flex items-center gap-2">
      <span className="relative flex h-2.5 w-2.5">
        {online && (
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75 motion-reduce:hidden" />
        )}
        <span
          className={`relative inline-flex h-2.5 w-2.5 rounded-full ${
            online ? "bg-emerald-500" : "bg-zinc-300 dark:bg-zinc-600"
          }`}
        />
      </span>
      <span className={online ? "font-medium text-emerald-700 dark:text-emerald-400" : "text-zinc-500 dark:text-zinc-400"}>
        {online ? "Online" : "Offline"}
      </span>
    </span>
  );
}

export default function SessoesAtivas() {
  const [filtro, setFiltro] = useState<Filtro>("todos");
  const [busca, setBusca] = useState("");

  // Sem cache: o monitor quer sempre o estado atual. tentativas=0 para não
  // arrastar o polling em caso de falha transitória (o próximo ciclo tenta).
  const { dados, erro, carregando, recarregar } = useApi<Sessoes>(
    "/presenca/sessoes",
    { tentativas: 0 },
  );

  // Polling leve: atualiza em segundo plano; useApi mantém `dados` na tela
  // durante a rebusca (sem piscar a tabela).
  useEffect(() => {
    const timer = window.setInterval(recarregar, INTERVALO_POLL_MS);
    return () => window.clearInterval(timer);
  }, [recarregar]);

  const lista = useMemo(() => {
    const alvo = normalizar(busca.trim());
    return (dados?.sessoes ?? [])
      .filter((s) =>
        filtro === "todos" ? true : filtro === "online" ? s.online : !s.online)
      .filter((s) => !alvo || normalizar(s.nome).includes(alvo));
  }, [dados, filtro, busca]);

  const abas: { chave: Filtro; rotulo: string }[] = [
    { chave: "todos", rotulo: "Todos" },
    { chave: "online", rotulo: "Apenas online" },
    { chave: "offline", rotulo: "Apenas offline" },
  ];

  return (
    <div>
      <PageHeader
        titulo="Sessões Ativas"
        descricao="Quem está com o sistema aberto agora. Atualiza sozinho a cada poucos segundos — “online” é presença recente, não apenas o último login."
      />

      <Card className="mb-4 flex flex-wrap items-center gap-3 p-4">
        {/* Resumo online/total */}
        <span className="inline-flex items-center gap-2 text-sm">
          <Users size={16} className="text-zinc-400" />
          {dados ? (
            <span>
              <strong className="text-emerald-600 dark:text-emerald-400">{dados.online}</strong>
              {" online"} · <strong>{dados.total}</strong> no total
            </span>
          ) : (
            <span className="text-zinc-400">Carregando…</span>
          )}
        </span>

        {/* Filtros por status */}
        <div
          role="tablist"
          aria-label="Filtrar por status"
          className="inline-flex flex-wrap gap-1 rounded-lg border border-zinc-200 bg-zinc-100 p-1 dark:border-zinc-800 dark:bg-zinc-900/60"
        >
          {abas.map((aba) => (
            <button
              key={aba.chave}
              type="button"
              role="tab"
              aria-selected={filtro === aba.chave}
              onClick={() => setFiltro(aba.chave)}
              className={`rounded-md px-3 py-1 text-sm font-medium transition-colors ${
                filtro === aba.chave
                  ? "bg-white text-indigo-700 shadow-sm dark:bg-zinc-800 dark:text-indigo-300"
                  : "text-zinc-600 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100"
              }`}
            >
              {aba.rotulo}
            </button>
          ))}
        </div>

        {/* Busca por nome */}
        <div className="relative flex items-center">
          <Search size={14} className="pointer-events-none absolute left-3 text-zinc-400" />
          <input
            aria-label="Buscar por nome"
            className={`${estiloInput} w-auto pl-8`}
            placeholder="Buscar por nome…"
            value={busca}
            onChange={(e) => setBusca(e.target.value)}
          />
        </div>

        {/* Atualização ao vivo + botão manual */}
        <div className="ml-auto inline-flex items-center gap-3">
          <span className="inline-flex items-center gap-1.5 text-xs text-zinc-500 dark:text-zinc-400">
            <span className="relative flex h-2 w-2">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75 motion-reduce:hidden" />
              <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-500" />
            </span>
            Ao vivo
          </span>
          <Botao variante="neutro" onClick={recarregar} disabled={carregando}>
            <RefreshCw size={14} className={carregando ? "animate-spin" : ""} /> Atualizar
          </Botao>
        </div>
      </Card>

      <Card>
        {carregando && !dados ? (
          <Carregando texto="Carregando sessões…" />
        ) : erro ? (
          <Vazio
            titulo="Não foi possível carregar"
            descricao={erro.message}
            acao={<Botao variante="neutro" onClick={recarregar}>Tentar de novo</Botao>}
          />
        ) : lista.length === 0 ? (
          <Vazio
            titulo="Ninguém por aqui"
            descricao={
              busca || filtro !== "todos"
                ? "Nenhum usuário corresponde ao filtro atual."
                : "Nenhum usuário cadastrado ainda."
            }
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-zinc-200 text-left text-xs uppercase tracking-wide text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
                  <th className="px-4 py-2 font-medium">Status</th>
                  <th className="px-4 py-2 font-medium">Usuário</th>
                  <th className="hidden px-4 py-2 font-medium sm:table-cell">Cargo</th>
                  <th className="hidden px-4 py-2 font-medium md:table-cell">Escola</th>
                  <th className="px-4 py-2 font-medium">Última atividade</th>
                  <th className="hidden px-4 py-2 font-medium lg:table-cell">Último acesso</th>
                </tr>
              </thead>
              <tbody>
                {lista.map((s) => (
                  <tr
                    key={s.id}
                    className="border-b border-zinc-100 last:border-0 dark:border-zinc-800/60"
                  >
                    <td className="px-4 py-2.5"><StatusPresenca online={s.online} /></td>
                    <td className="px-4 py-2.5">
                      <div className="font-medium">{s.nome}</div>
                      <div className="text-xs text-zinc-400">{s.email}</div>
                      {/* Cargo aparece aqui no celular (a coluna própria some) */}
                      <div className="mt-0.5 sm:hidden">
                        <Badge tom={s.is_global ? "destaque" : "neutro"}>{papel(s)}</Badge>
                      </div>
                    </td>
                    <td className="hidden px-4 py-2.5 sm:table-cell">
                      <Badge tom={s.is_global ? "destaque" : "neutro"}>{papel(s)}</Badge>
                    </td>
                    <td className="hidden px-4 py-2.5 text-zinc-500 dark:text-zinc-400 md:table-cell">
                      {s.escola_nome ?? (s.is_global ? "Todas (global)" : "—")}
                    </td>
                    <td className="px-4 py-2.5 text-zinc-600 dark:text-zinc-300">
                      {dados ? haQuanto(dados.agora, s.visto_em) : "—"}
                    </td>
                    <td className="hidden px-4 py-2.5 text-zinc-500 dark:text-zinc-400 lg:table-cell">
                      {dataHora(s.ultimo_acesso)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
