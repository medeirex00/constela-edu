/**
 * Configuração do Assistente de IA (admin): escolhe o provedor e cola a chave
 * de API pela interface — sem precisar de acesso ao servidor. A chave é
 * gravada cifrada no backend e nunca volta ao navegador.
 */
import { Bot, CheckCircle2, XCircle } from "lucide-react";
import { useEffect, useState } from "react";

import { Botao, Card, Mensagem, estiloInput } from "./ui";
import { useApp } from "../context/AppContext";
import { useApi } from "../hooks/useApi";
import { api } from "../lib/api";

interface ConfigIA {
  provedor: string;
  modelo: string;
  chave_definida: boolean;
}

const PROVEDORES = [
  { valor: "anthropic", rotulo: "Claude (Anthropic) — recomendado" },
  { valor: "openai", rotulo: "OpenAI" },
  { valor: "local", rotulo: "Modo local (sem IA, respostas por regras)" },
];

export default function ConfigAssistenteIA() {
  const { escolaId } = useApp();
  const {
    dados: config,
    erro,
    carregando,
    recarregar,
  } = useApi<ConfigIA>(escolaId ? `/escolas/${escolaId}/assistente/config` : null);
  const [provedor, setProvedor] = useState("local");
  const [apiKey, setApiKey] = useState("");
  const [modelo, setModelo] = useState("");
  const [ocupado, setOcupado] = useState(false);
  const [aviso, setAviso] = useState<{ tipo: "ok" | "erro"; texto: string } | null>(null);

  // Semeia os campos editáveis quando a configuração é carregada.
  useEffect(() => {
    if (!config) return;
    setProvedor(config.provedor);
    setModelo(config.modelo);
  }, [config]);

  // Ao trocar de escola, limpa a chave digitada e qualquer aviso pendente.
  useEffect(() => {
    setAviso(null);
    setApiKey("");
  }, [escolaId]);

  async function salvar() {
    if (!escolaId) return;
    setOcupado(true);
    setAviso(null);
    try {
      await api<ConfigIA>(`/escolas/${escolaId}/assistente/config`, {
        method: "PUT",
        body: JSON.stringify({
          provedor,
          api_key: apiKey.trim() || null,
          modelo: modelo.trim() || null,
        }),
      });
      recarregar();
      setApiKey("");
      setAviso({ tipo: "ok", texto: "Configuração salva." });
    } catch (excecao) {
      setAviso({
        tipo: "erro",
        texto: excecao instanceof Error ? excecao.message : "Não foi possível salvar.",
      });
    } finally {
      setOcupado(false);
    }
  }

  async function testar() {
    if (!escolaId) return;
    setOcupado(true);
    setAviso(null);
    try {
      const r = await api<{ ok: boolean; provedor?: string; erro?: string }>(
        `/escolas/${escolaId}/assistente/config/testar`,
        { method: "POST" },
      );
      setAviso(
        r.ok
          ? { tipo: "ok", texto: `Funcionando! O assistente respondeu pelo provedor "${r.provedor}".` }
          : { tipo: "erro", texto: `O provedor não respondeu: ${r.erro ?? "erro desconhecido"}` },
      );
    } catch (excecao) {
      setAviso({
        tipo: "erro",
        texto: excecao instanceof Error ? excecao.message : "Falha no teste.",
      });
    } finally {
      setOcupado(false);
    }
  }

  if (!carregando && erro) {
    return (
      <Card className="space-y-3 p-5">
        <Mensagem tipo="erro">
          Não foi possível carregar a configuração do assistente: {erro.message}
        </Mensagem>
        <Botao variante="neutro" onClick={recarregar}>
          Tentar de novo
        </Botao>
      </Card>
    );
  }
  if (!config) return null; // carregando

  const trocouProvedor = provedor !== config.provedor;

  return (
    <Card className="space-y-4 p-5">
      <div className="flex items-start gap-2.5">
        <Bot size={18} className="mt-0.5 shrink-0 text-indigo-600 dark:text-indigo-400" />
        <p className="text-sm text-zinc-600 dark:text-zinc-300">
          Com uma chave de API, o assistente vira uma IA de verdade: interpreta a
          pergunta e responde usando os dados da escola. Sem chave, funciona no
          modo local (respostas prontas por regras). A chave fica guardada
          cifrada no servidor e nunca aparece de novo aqui.
        </p>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block text-sm">
          <span className="mb-1 block font-medium">Provedor</span>
          <select
            className={estiloInput}
            value={provedor}
            onChange={(e) => setProvedor(e.target.value)}
            disabled={ocupado}
          >
            {PROVEDORES.map((p) => (
              <option key={p.valor} value={p.valor}>{p.rotulo}</option>
            ))}
          </select>
        </label>
        <label className="block text-sm">
          <span className="mb-1 block font-medium">Modelo (opcional)</span>
          <input
            className={estiloInput}
            placeholder="padrão do provedor"
            value={modelo}
            onChange={(e) => setModelo(e.target.value)}
            disabled={ocupado || provedor === "local"}
          />
        </label>
      </div>

      {provedor !== "local" && (
        <label className="block text-sm">
          <span className="mb-1 flex items-center gap-2 font-medium">
            Chave de API
            {config.chave_definida && !trocouProvedor ? (
              <span className="inline-flex items-center gap-1 text-xs font-normal text-emerald-600 dark:text-emerald-400">
                <CheckCircle2 size={13} /> chave já configurada
              </span>
            ) : (
              <span className="inline-flex items-center gap-1 text-xs font-normal text-amber-600 dark:text-amber-400">
                <XCircle size={13} />
                {trocouProvedor
                  ? "novo provedor: informe a chave dele"
                  : "nenhuma chave salva"}
              </span>
            )}
          </span>
          <input
            type="password"
            className={estiloInput}
            placeholder={config.chave_definida && !trocouProvedor
              ? "deixe em branco para manter a atual"
              : "cole aqui a chave de API"}
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            disabled={ocupado}
            autoComplete="off"
          />
          <span className="mt-1 block text-xs text-zinc-400">
            Para o Claude, crie a chave em console.anthropic.com → API Keys.
            {trocouProvedor && " Por segurança, a chave do provedor anterior não é reaproveitada."}
          </span>
        </label>
      )}

      {aviso && <Mensagem tipo={aviso.tipo}>{aviso.texto}</Mensagem>}

      <div className="flex flex-wrap gap-2">
        <Botao onClick={salvar} disabled={ocupado}>
          {ocupado ? "Salvando..." : "Salvar"}
        </Botao>
        <Botao variante="neutro" onClick={testar} disabled={ocupado}>
          Testar o assistente
        </Botao>
      </div>
    </Card>
  );
}
