/**
 * Assistente Pedagógico (PRD §155–§172): chat que responde somente sobre
 * os dados desta escola. O frontend nunca fala com o modelo — apenas com
 * o backend, que monta o contexto e registra a conversa.
 *
 * Identidade v2: bolha do assistente em cartão branco com o ícone em quadrado
 * pastel, bolha do usuário em pílula violeta, sugestões como chips com ícone e a
 * lista de conversas como "destaques recentes". No estreito (< 1024 px) a lista
 * de conversas vira um painel recolhível acima do chat — UMA lista só no DOM — e o
 * "Nova conversa" fica no cabeçalho, sempre à mão.
 */
import {
  Bot,
  ChevronDown,
  History,
  MessageSquare,
  MessageSquarePlus,
  School,
  Send,
  Sparkles,
  TrendingUp,
  Trophy,
  Users,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Botao, Card, Carregando, IconePastel, PageHeader, estiloInput } from "../components/ui";
import { useApp } from "../context/AppContext";
import { useApi } from "../hooks/useApi";
import { api } from "../lib/api";
import { dataHora } from "../lib/formato";

interface Conversa {
  id: number;
  titulo: string;
  provedor: string;
  created_at: string;
}

interface Mensagem {
  papel: "usuario" | "assistente";
  conteudo: string;
}

const SUGESTOES: { texto: string; icone: LucideIcon }[] = [
  { texto: "Quem são os 3 melhores do Matific?", icone: Trophy },
  { texto: "Quem mais evoluiu este mês?", icone: TrendingUp },
  { texto: "Quais alunos precisam de atenção?", icone: Sparkles },
  { texto: "Como estão as turmas?", icone: Users },
];

/** O nome do provedor em linguagem de gente (antes aparecia o valor cru). */
const NOME_PROVEDOR: Record<string, string> = {
  anthropic: "Claude (Anthropic)",
  openai: "OpenAI",
  local: "Modo local",
};

export default function Assistente() {
  const { escolaId, escolas } = useApp();
  const [conversaId, setConversaId] = useState<number | null>(null);
  const [mensagens, setMensagens] = useState<Mensagem[]>([]);
  const [pergunta, setPergunta] = useState("");
  const [aguardando, setAguardando] = useState(false);
  const [erroAbrir, setErroAbrir] = useState("");
  const [listaAberta, setListaAberta] = useState(false);
  const mensagensRef = useRef<HTMLDivElement | null>(null);

  // Leitura pela arquitetura única: só busca quando há escola (senão, ocioso).
  const {
    dados: conversas,
    erro: erroConversas,
    carregando: carregandoConversas,
    recarregar: recarregarConversas,
  } = useApi<Conversa[]>(escolaId ? `/escolas/${escolaId}/assistente/conversas` : null);
  const { dados: status } = useApi<{ provedor: string }>(
    escolaId ? `/escolas/${escolaId}/assistente/status` : null,
  );
  const provedor = status?.provedor ?? "";
  const nomeEscola = escolas.find((e) => e.id === escolaId)?.nome;

  // Ao trocar de escola, fecha a conversa aberta (pertence à escola anterior).
  useEffect(() => {
    setConversaId(null);
    setMensagens([]);
    setErroAbrir("");
  }, [escolaId]);

  // Leva a conversa à última mensagem rolando SÓ a caixa das mensagens. Antes era um
  // scrollIntoView no fim da lista, que também rolava a janela: a página já abria
  // rolada, com o título escondido sob o cabeçalho. Sem mensagens, nada a rolar.
  useEffect(() => {
    const caixa = mensagensRef.current;
    if (!caixa || (mensagens.length === 0 && !aguardando)) return;
    caixa.scrollTop = caixa.scrollHeight;
  }, [mensagens, aguardando]);

  function novaConversa() {
    setConversaId(null);
    setMensagens([]);
    setErroAbrir("");
  }

  async function abrirConversa(id: number) {
    if (!escolaId) return;
    setErroAbrir("");
    try {
      const detalhe = await api<{ id: number; mensagens: Mensagem[] }>(
        `/escolas/${escolaId}/assistente/conversas/${id}`,
      );
      setConversaId(detalhe.id);
      setMensagens(detalhe.mensagens);
      setListaAberta(false);
    } catch (excecao) {
      // Não engolir: antes o clique virava no-op silencioso. Agora surfaça o
      // erro (o usuário pode clicar de novo para tentar).
      setErroAbrir(
        excecao instanceof Error ? excecao.message : "Não consegui abrir esta conversa. Tente de novo.",
      );
    }
  }

  async function enviar(texto?: string) {
    const conteudo = (texto ?? pergunta).trim();
    if (!escolaId || !conteudo || aguardando) return;
    setPergunta("");
    setMensagens((atuais) => [...atuais, { papel: "usuario", conteudo }]);
    setAguardando(true);
    try {
      const resposta = await api<{ conversa_id: number; resposta: string; provedor: string }>(
        `/escolas/${escolaId}/assistente`,
        {
          method: "POST",
          body: JSON.stringify({ pergunta: conteudo, conversa_id: conversaId }),
        },
      );
      setConversaId(resposta.conversa_id);
      setMensagens((atuais) => [...atuais, { papel: "assistente", conteudo: resposta.resposta }]);
      recarregarConversas();
    } catch (excecao) {
      setMensagens((atuais) => [
        ...atuais,
        {
          papel: "assistente",
          conteudo: excecao instanceof Error ? `Erro: ${excecao.message}` : "Não consegui responder agora.",
        },
      ]);
    } finally {
      setAguardando(false);
    }
  }

  const lista = conversas ?? [];

  return (
    <div className="space-y-5">
      <PageHeader
        titulo="Assistente Pedagógico"
        descricao="Pergunte sobre os dados desta escola. As respostas usam apenas o que está no sistema, e toda conversa fica registrada."
        acoes={
          <>
            {provedor && (
              <span className="inline-flex items-center gap-1.5 rounded-full bg-indigo-50 px-3 py-1.5 text-xs font-semibold text-indigo-700 dark:bg-indigo-500/15 dark:text-indigo-300">
                <Bot size={14} aria-hidden /> {NOME_PROVEDOR[provedor] ?? provedor}
              </span>
            )}
            <Botao variante="secundario" onClick={novaConversa}>
              <MessageSquarePlus size={15} aria-hidden /> Nova conversa
            </Botao>
          </>
        }
      />

      {/* Qual escola o chat consulta (o Admin Global troca de escola no topo). */}
      {nomeEscola && (
        <p className="-mt-3 inline-flex items-center gap-2 rounded-full border border-zinc-200 bg-white px-3 py-1.5 text-xs font-medium text-zinc-600 shadow-cartao dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-300">
          <School size={14} aria-hidden className="text-indigo-600 dark:text-indigo-300" />
          Consultando os dados de <b className="text-zinc-900 dark:text-white">{nomeEscola}</b>
        </p>
      )}

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-[260px,1fr]">
        <Card className={`${nomeEscola ? "lg:max-h-[min(calc(70dvh-3rem),680px)]" : "lg:max-h-[min(70dvh,680px)]"} lg:overflow-y-auto`}>
          {/* No estreito, a lista fica recolhida atrás deste botão (só abaixo de lg). */}
          <button
            type="button"
            onClick={() => setListaAberta((v) => !v)}
            aria-expanded={listaAberta}
            aria-controls="lista-conversas"
            className="flex w-full items-center gap-3 p-4 text-left lg:hidden"
          >
            <IconePastel icone={History} tom="violeta" tamanho="sm" />
            <span className="text-sm font-semibold text-zinc-900 dark:text-white">Conversas anteriores ({lista.length})</span>
            <ChevronDown size={16} aria-hidden className={`ml-auto text-zinc-400 transition-transform ${listaAberta ? "rotate-180" : ""}`} />
          </button>
          <div id="lista-conversas" className={`${listaAberta ? "block" : "hidden"} border-t border-zinc-100 dark:border-zinc-800 lg:block lg:border-0`}>
            <p className="hidden px-4 pb-2 pt-4 text-[11px] font-semibold uppercase tracking-[0.08em] text-zinc-500 dark:text-zinc-400 lg:block">
              Conversas
            </p>
            {erroAbrir && (
              <p className="mx-3 mt-3 rounded-xl bg-rose-50 p-3 text-xs text-rose-700 dark:bg-rose-500/10 dark:text-rose-300" role="alert">{erroAbrir}</p>
            )}
            {erroConversas ? (
              <p className="p-4 text-xs text-rose-700 dark:text-rose-300" role="alert">{erroConversas.message}</p>
            ) : carregandoConversas && !conversas ? (
              <p className="p-4 text-xs text-zinc-500 dark:text-zinc-400">Carregando as conversas…</p>
            ) : lista.length === 0 ? (
              <p className="p-4 text-xs text-zinc-500 dark:text-zinc-400">Suas conversas aparecerão aqui.</p>
            ) : (
              <ul className="space-y-0.5 p-2">
                {lista.map((conversa) => {
                  const ativa = conversa.id === conversaId;
                  return (
                    <li key={conversa.id}>
                      <button
                        type="button"
                        aria-current={ativa ? "true" : undefined}
                        className={`flex w-full items-center gap-3 rounded-xl px-2.5 py-2 text-left transition-colors ${
                          ativa ? "bg-indigo-50 dark:bg-indigo-500/15" : "hover:bg-zinc-50 dark:hover:bg-zinc-800/60"
                        }`}
                        onClick={() => abrirConversa(conversa.id)}
                      >
                        <IconePastel icone={MessageSquare} tom={ativa ? "violeta" : "neutro"} tamanho="sm" />
                        <span className="min-w-0">
                          <span className="block truncate text-sm font-semibold text-zinc-800 dark:text-zinc-100" title={conversa.titulo}>{conversa.titulo}</span>
                          <span className="block text-xs text-zinc-500 dark:text-zinc-400">{dataHora(conversa.created_at)}</span>
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </Card>

        {/* dvh: no celular, o teclado virtual não cobre o campo de pergunta. A linha
            "Consultando os dados de…" ocupa ~3 rem acima do chat: a altura a desconta,
            para a tela continuar cabendo na janela do notebook sem rolar. */}
        <Card className={`flex ${nomeEscola ? "h-[calc(70dvh-3rem)]" : "h-[70dvh]"} min-h-[420px] flex-col`}>
          <div
            ref={mensagensRef}
            className="flex-1 scroll-smooth space-y-4 overflow-y-auto p-4 sm:p-5"
            aria-live="polite"
          >
            {mensagens.length === 0 && !aguardando && (
              <div className="flex h-full flex-col items-center justify-center gap-5 text-center">
                <span aria-hidden className="grid h-16 w-16 place-items-center rounded-2xl bg-indigo-600 text-white shadow-pilula">
                  <Bot size={30} />
                </span>
                <div>
                  <p className="text-lg font-semibold tracking-tight text-zinc-900 dark:text-white">Em que posso ajudar hoje?</p>
                  <p className="mx-auto mt-1 max-w-sm text-sm text-zinc-500 dark:text-zinc-400">
                    Sou o assistente do Constela Edu. Respondo apenas com os dados desta escola — rankings,
                    evolução, alertas e turmas.
                  </p>
                </div>
                <div className="flex max-w-xl flex-wrap justify-center gap-2">
                  {SUGESTOES.map(({ texto, icone: Icone }) => (
                    <button
                      key={texto}
                      type="button"
                      className="inline-flex items-center gap-2 rounded-full border border-indigo-100 bg-indigo-50/60 px-3.5 py-2 text-xs font-semibold text-indigo-700 transition-colors hover:border-indigo-200 hover:bg-indigo-50 dark:border-indigo-500/20 dark:bg-indigo-500/10 dark:text-indigo-300"
                      onClick={() => enviar(texto)}
                    >
                      <Icone size={14} aria-hidden />
                      {texto}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {mensagens.map((mensagem, indice) =>
              mensagem.papel === "usuario" ? (
                <div key={indice} className="flex justify-end">
                  <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-indigo-600 px-4 py-2.5 text-sm text-white shadow-pilula">
                    {mensagem.conteudo}
                  </div>
                </div>
              ) : (
                <div key={indice} className="flex items-start gap-2.5">
                  <IconePastel icone={Bot} tom="violeta" tamanho="sm" className="mt-0.5" />
                  <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-tl-md border border-zinc-200 bg-white px-4 py-2.5 text-sm text-zinc-800 shadow-cartao dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-100">
                    {mensagem.conteudo}
                  </div>
                </div>
              ),
            )}
            {aguardando && <Carregando texto="Consultando os dados..." />}
          </div>

          <form
            className="flex gap-2 border-t border-zinc-100 p-3 dark:border-zinc-800 sm:p-4"
            onSubmit={(evento) => {
              evento.preventDefault();
              enviar();
            }}
          >
            <input
              aria-label="Sua pergunta"
              className={`${estiloInput} rounded-full px-4`}
              placeholder="Pergunte algo sobre os dados da escola..."
              value={pergunta}
              onChange={(evento) => setPergunta(evento.target.value)}
              disabled={aguardando}
            />
            <Botao type="submit" aria-label="Enviar pergunta" title="Enviar pergunta"
                   className="!rounded-full !px-3.5" disabled={aguardando || !pergunta.trim()}>
              <Send size={16} aria-hidden />
            </Botao>
          </form>
        </Card>
      </div>
    </div>
  );
}
