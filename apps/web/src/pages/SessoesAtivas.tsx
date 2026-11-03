/**
 * Monitor de Sessões Ativas — EXCLUSIVO do Administrador Global.
 *
 * Mostra, em tempo quase real, quem está com o sistema aberto: nome, cargo,
 * escola, status (🟢 online / ⚪ offline), última atividade ("há 2 min") e o
 * último acesso (data/hora). "Online" é decidido no servidor pela janela de
 * presença (heartbeat recente). A tela faz *polling* leve (a cada 15 s) e
 * mantém a tabela na tela enquanto atualiza por baixo — sem piscar.
 *
 * Identidade v2: KPIs com ícone pastel (só números da resposta), abas
 * segmentadas, tabela com avatar de iniciais, cargo em chip e status em pílula.
 * O "Ao vivo" fica âmbar ("sem conexão") quando a última leitura falhou.
 */
import { Activity, RefreshCw, Search, UserCheck, Users } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import {
  Abas,
  Avatar,
  Botao,
  Card,
  Carregando,
  Chip,
  EmailQuebravel,
  Erro,
  PageHeader,
  StatCard,
  Vazio,
  classesTabela,
  estiloInput,
} from "../components/ui";
import { TabelaRolavel } from "../components/TabelaRolavel";
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

// Tabela no celular (< 640 px): células mais justas, para Usuário e Status caberem
// inteiros no primeiro olhar (o resto vem com a rolagem lateral, com aviso em texto).
const th = `${classesTabela.th} max-sm:px-3`;
const td = "px-4 py-3 max-sm:px-3";
const UM_DIA_MS = 24 * 3600 * 1000;

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

/** Pílula de status com legenda (verde pulsante = online, cinza = offline). */
function StatusPresenca({ online }: { online: boolean }) {
  return (
    <span className={`inline-flex items-center gap-2 rounded-full px-2.5 py-1 text-xs ${
      online ? "bg-emerald-50 dark:bg-emerald-500/15" : "bg-zinc-100 dark:bg-zinc-800"}`}>
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
      <span className={online ? "font-semibold text-emerald-700 dark:text-emerald-300" : "font-medium text-zinc-600 dark:text-zinc-300"}>
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

  // Vistos nas últimas 24 h pelo relógio do SERVIDOR, entre as contas LISTADAS (o
  // backend limita a lista; quando corta, o detalhe do cartão diz isso).
  const vistos24h = useMemo(() => {
    if (!dados) return 0;
    const agora = new Date(dados.agora).getTime();
    return dados.sessoes.filter((s) =>
      s.visto_em != null && agora - new Date(s.visto_em).getTime() <= UM_DIA_MS).length;
  }, [dados]);
  const listaCortada = Boolean(dados && dados.sessoes.length < dados.total);

  const abas: { valor: Filtro; rotulo: string }[] = [
    { valor: "todos", rotulo: "Todos" },
    { valor: "online", rotulo: "Apenas online" },
    { valor: "offline", rotulo: "Apenas offline" },
  ];
  // A última leitura falhou, mas há dados anteriores na tela: o "Ao vivo" não pode mentir.
  const semConexao = Boolean(erro && dados);

  return (
    <div className="space-y-6">
      <PageHeader
        titulo="Sessões Ativas"
        descricao="Quem está com o sistema aberto agora. Atualiza sozinho a cada poucos segundos — “online” é presença recente, não apenas o último login."
        acoes={
          <>
            <span
              className={`inline-flex items-center gap-2 rounded-full px-3 py-1.5 text-xs font-semibold ${
                semConexao
                  ? "bg-ouro-50 text-ouro-700 dark:bg-ouro-400/15 dark:text-ouro-300"
                  : "bg-emerald-50 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300"}`}
              title={semConexao ? "A última atualização falhou; mostrando a leitura anterior" : undefined}
            >
              <span className="relative flex h-2 w-2">
                {!semConexao && (
                  <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75 motion-reduce:hidden" />
                )}
                <span className={`relative inline-flex h-2 w-2 rounded-full ${semConexao ? "bg-ouro-500" : "bg-emerald-500"}`} />
              </span>
              {semConexao ? "Sem conexão — última leitura" : "Ao vivo"}
            </span>
            <Botao variante="secundario" onClick={recarregar} disabled={carregando}>
              <RefreshCw size={14} aria-hidden className={carregando ? "animate-spin motion-reduce:animate-none" : ""} /> Atualizar
            </Botao>
          </>
        }
      />

      {/* KPIs: números da resposta (só a janela de 24 h é contada aqui). */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 sm:gap-5 max-sm:[&>*:last-child:nth-child(odd)]:col-span-2">
        <StatCard icone={<Activity size={20} />} tom="verde" rotulo="Online agora"
                  valor={dados ? String(dados.online) : "…"} detalhe="presença recente no sistema" />
        <StatCard icone={<Users size={20} />} tom="violeta" rotulo="Contas cadastradas"
                  valor={dados ? String(dados.total) : "…"} detalhe="todas as contas do sistema" />
        <StatCard icone={<UserCheck size={20} />} tom="azul" rotulo="Vistos nas últimas 24 h"
                  valor={dados ? String(vistos24h) : "…"}
                  detalhe={listaCortada ? `entre as ${dados?.sessoes.length} contas listadas` : "pela última atividade"} />
      </div>

      <Card className="p-5 sm:p-6">
        <div className="mb-4 flex flex-wrap items-center gap-3">
          {/* Filtros por status (abas segmentadas acessíveis). */}
          <Abas itens={abas} valor={filtro} aoMudar={setFiltro} rotulo="Filtrar por status" />
          {/* Busca por nome */}
          <div className="relative w-full sm:ml-auto sm:w-64">
            <Search size={15} aria-hidden className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-zinc-400" />
            <input
              aria-label="Buscar por nome"
              className={`${estiloInput} pl-9`}
              placeholder="Buscar por nome…"
              value={busca}
              onChange={(e) => setBusca(e.target.value)}
            />
          </div>
        </div>

        {carregando && !dados ? (
          <Carregando texto="Carregando sessões…" />
        ) : erro && !dados ? (
          <Erro titulo="Não foi possível carregar" descricao={erro.message} aoTentar={recarregar} />
        ) : lista.length === 0 ? (
          <Vazio
            icone={Users}
            titulo="Ninguém por aqui"
            descricao={
              busca || filtro !== "todos"
                ? "Nenhum usuário corresponde ao filtro atual."
                : "Nenhum usuário cadastrado ainda."
            }
          />
        ) : (
          // 4 colunas (eram 6): o cargo leva a escola embaixo e a última atividade leva o
          // último acesso embaixo. Com 6 colunas a tabela passava da largura do cartão em
          // tablets (820 px) e o "Último acesso" ficava escondido na rolagem lateral.
          // Nada saiu: cada dado continua na tela, uma vez só.
          // Celular (< 640 px): a tabela rola de lado dentro do cartão com o aviso em texto
          // acima dela ("Deslize..."), não só a sombra; o avatar (decorativo) some e a
          // célula do usuário tem base de 9,5rem, então o e-mail cabe sem quebrar no "@" e
          // a pílula de Status não encosta na borda.
          <TabelaRolavel rotulo="Sessões: tabela completa">
            <table className={classesTabela.tabela}>
              <thead>
                <tr>
                  <th scope="col" className={th}>Usuário</th>
                  <th scope="col" className={th}>Status</th>
                  <th scope="col" className={th}>Cargo e escola</th>
                  <th scope="col" className={th}>Última atividade</th>
                </tr>
              </thead>
              <tbody>
                {lista.map((s) => (
                  <tr key={s.id} className={classesTabela.tr}>
                    <td className={td}>
                      <div className="flex items-center gap-3">
                        {/* Mesma chave de cor (o id) da barra lateral, de Minha conta e de Usuários. */}
                        <Avatar nome={s.nome} chave={s.id} tamanho="sm" className="hidden sm:grid" />
                        <div className="min-w-0 max-sm:min-w-[9.5rem]">
                          <div className="truncate font-semibold text-zinc-900 dark:text-zinc-100" title={s.nome}>{s.nome}</div>
                          <div className="max-w-[10rem] text-xs text-zinc-500 [overflow-wrap:anywhere] lg:max-w-[13rem] dark:text-zinc-400"><EmailQuebravel email={s.email} /></div>
                        </div>
                      </div>
                    </td>
                    <td className={td}><StatusPresenca online={s.online} /></td>
                    <td className={td}>
                      <Chip className={s.is_global ? "!bg-indigo-50 !text-indigo-700 dark:!bg-indigo-500/15 dark:!text-indigo-300" : ""}>
                        {papel(s)}
                      </Chip>
                      {/* min-w: o nome da escola quebra em 2 linhas, não numa palavra por linha. */}
                      <span className="mt-1 block min-w-[8rem] text-xs leading-snug text-zinc-600 dark:text-zinc-300">
                        {s.escola_nome ?? (s.is_global ? "Todas (global)" : "—")}
                      </span>
                    </td>
                    <td className={td}>
                      <span className="block whitespace-nowrap text-zinc-700 dark:text-zinc-200">
                        {dados ? haQuanto(dados.agora, s.visto_em) : "—"}
                      </span>
                      <span className="mt-0.5 block text-xs text-zinc-500 dark:text-zinc-400">
                        <span className="whitespace-nowrap">Último acesso:</span>{" "}
                        <span className="whitespace-nowrap">{dataHora(s.ultimo_acesso)}</span>
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TabelaRolavel>
        )}
      </Card>
    </div>
  );
}
