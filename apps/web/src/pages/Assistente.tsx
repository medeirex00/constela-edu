/**
 * Assistente Pedagógico (PRD §155–§172): chat que responde somente sobre
 * os dados desta escola. O frontend nunca fala com o modelo — apenas com
 * o backend, que monta o contexto e registra a conversa.
 */
import { Bot, MessageSquarePlus, Send } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { Badge, Botao, Card, Carregando, PageHeader, estiloInput } from "../components/ui";
import { useApp } from "../context/AppContext";
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

const SUGESTOES = [
  "Quem mais evoluiu este mês?",
  "Quais alunos precisam de atenção?",
  "Como estão as turmas?",
];

export default function Assistente() {
  const { escolaId } = useApp();
  const [conversas, setConversas] = useState<Conversa[]>([]);
  const [conversaId, setConversaId] = useState<number | null>(null);
  const [mensagens, setMensagens] = useState<Mensagem[]>([]);
  const [pergunta, setPergunta] = useState("");
  const [aguardando, setAguardando] = useState(false);
  const [provedor, setProvedor] = useState("");
  const fimRef = useRef<HTMLDivElement | null>(null);

  const carregarConversas = useCallback(() => {
    if (!escolaId) return;
    api<Conversa[]>(`/escolas/${escolaId}/assistente/conversas`)
      .then(setConversas)
      .catch(() => setConversas([]));
  }, [escolaId]);

  useEffect(() => {
    carregarConversas();
    setConversaId(null);
    setMensagens([]);
    if (!escolaId) return;
    api<{ provedor: string }>(`/escolas/${escolaId}/assistente/status`)
      .then((s) => setProvedor(s.provedor))
      .catch(() => setProvedor(""));
  }, [escolaId, carregarConversas]);

  useEffect(() => {
    fimRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [mensagens, aguardando]);

  async function abrirConversa(id: number) {
    if (!escolaId) return;
    const detalhe = await api<{ id: number; mensagens: Mensagem[] }>(
      `/escolas/${escolaId}/assistente/conversas/${id}`,
    ).catch(() => null);
    if (detalhe) {
      setConversaId(detalhe.id);
      setMensagens(detalhe.mensagens);
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
      carregarConversas();
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

  return (
    <div>
      <PageHeader
        titulo="Assistente Pedagógico"
        descricao="Pergunte sobre os dados desta escola. As respostas usam apenas o que está no sistema, e toda conversa fica registrada."
        acoes={provedor ? <Badge tom="destaque">provedor: {provedor}</Badge> : undefined}
      />

      <div className="grid gap-4 lg:grid-cols-[240px,1fr]">
        <Card className="hidden max-h-[70vh] overflow-y-auto lg:block">
          <div className="border-b border-zinc-200 p-3 dark:border-zinc-800">
            <Botao
              variante="neutro"
              className="w-full"
              onClick={() => {
                setConversaId(null);
                setMensagens([]);
              }}
            >
              <MessageSquarePlus size={15} /> Nova conversa
            </Botao>
          </div>
          {conversas.length === 0 ? (
            <p className="p-3 text-xs text-zinc-400">Suas conversas aparecerão aqui.</p>
          ) : (
            <ul>
              {conversas.map((conversa) => (
                <li key={conversa.id}>
                  <button
                    className={`w-full px-3 py-2 text-left text-sm hover:bg-zinc-50 dark:hover:bg-zinc-800/60 ${
                      conversa.id === conversaId ? "bg-indigo-50 dark:bg-indigo-500/10" : ""
                    }`}
                    onClick={() => abrirConversa(conversa.id)}
                  >
                    <p className="truncate font-medium">{conversa.titulo}</p>
                    <p className="text-xs text-zinc-400">{dataHora(conversa.created_at)}</p>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card className="flex h-[70vh] flex-col">
          <div className="flex-1 space-y-3 overflow-y-auto p-4">
            {mensagens.length === 0 && !aguardando && (
              <div className="flex h-full flex-col items-center justify-center gap-4 text-center">
                <span className="flex h-12 w-12 items-center justify-center rounded-full bg-indigo-50 text-indigo-600 dark:bg-indigo-500/10 dark:text-indigo-400">
                  <Bot size={22} />
                </span>
                <p className="max-w-sm text-sm text-zinc-500 dark:text-zinc-400">
                  Sou o assistente do Constela Edu. Respondo apenas com os dados desta escola — rankings,
                  evolução, alertas e turmas.
                </p>
                <div className="flex flex-wrap justify-center gap-2">
                  {SUGESTOES.map((sugestao) => (
                    <button
                      key={sugestao}
                      className="rounded-full border border-zinc-300 px-3 py-1.5 text-xs hover:bg-zinc-50 dark:border-zinc-700 dark:hover:bg-zinc-800"
                      onClick={() => enviar(sugestao)}
                    >
                      {sugestao}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {mensagens.map((mensagem, indice) => (
              <div
                key={indice}
                className={`flex ${mensagem.papel === "usuario" ? "justify-end" : "justify-start"}`}
              >
                <div
                  className={`max-w-[85%] whitespace-pre-wrap rounded-2xl px-4 py-2.5 text-sm ${
                    mensagem.papel === "usuario"
                      ? "bg-indigo-600 text-white"
                      : "bg-zinc-100 text-zinc-800 dark:bg-zinc-800 dark:text-zinc-100"
                  }`}
                >
                  {mensagem.conteudo}
                </div>
              </div>
            ))}
            {aguardando && <Carregando texto="Consultando os dados..." />}
            <div ref={fimRef} />
          </div>

          <form
            className="flex gap-2 border-t border-zinc-200 p-3 dark:border-zinc-800"
            onSubmit={(evento) => {
              evento.preventDefault();
              enviar();
            }}
          >
            <input
              aria-label="Sua pergunta"
              className={estiloInput}
              placeholder="Pergunte algo sobre os dados da escola..."
              value={pergunta}
              onChange={(evento) => setPergunta(evento.target.value)}
              disabled={aguardando}
            />
            <Botao type="submit" disabled={aguardando || !pergunta.trim()}>
              <Send size={15} />
            </Botao>
          </form>
        </Card>
      </div>
    </div>
  );
}
