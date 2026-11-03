/**
 * Configuração do Assistente de IA.
 *
 * Provedor EXTERNO (Claude/Anthropic ou OpenAI) é do Admin Global (P9): ele envia
 * os dados da escola, pseudonimizados, para servidores fora do país. Só o Admin
 * Global escolhe o provedor externo, o modelo e cola a chave de API (gravada
 * cifrada no backend, nunca volta ao navegador). O admin da escola VÊ o estado e
 * pode DESLIGAR — voltar ao modo local, sem rede — e testar o assistente. O
 * backend recusa (403) o resto; esta tela só não oferece o que ele recusaria.
 */
import { AlertTriangle, CheckCircle2, ChevronDown, Globe, Power, ShieldCheck, XCircle } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";

import { Botao, Card, Confirmacao, Mensagem, Skeleton, estiloInput } from "./ui";
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

const NOME_PROVEDOR: Record<string, string> = {
  anthropic: "Claude (Anthropic)",
  openai: "OpenAI",
  local: "Modo local",
};

const AVISO_DADOS_FORA =
  "Com um provedor externo, as perguntas e os dados da escola (turmas, notas, " +
  "índices e alertas) vão para servidores da empresa escolhida, fora do país. " +
  "Saem pseudonimizados: nome, RA e e-mail de aluno são trocados ou retirados antes.";

/**
 * `cabecalho`: o cabeçalho do cartão (ícone pastel + título + descrição), passado pela
 * tela que o hospeda — em Configurações ele fica DENTRO do cartão, como nos outros
 * blocos. O cartão não repete o ícone do robô por conta própria.
 */
export default function ConfigAssistenteIA({ cabecalho }: { cabecalho?: ReactNode } = {}) {
  const { escolaId, usuario } = useApp();
  const ehGlobal = Boolean(usuario?.is_global);
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
  const [confirmandoDesligar, setConfirmandoDesligar] = useState(false);

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

  async function gravar(
    corpo: { provedor: string; api_key: string | null; modelo: string | null },
    sucesso: string,
  ) {
    if (!escolaId) return;
    setOcupado(true);
    setAviso(null);
    try {
      await api<ConfigIA>(`/escolas/${escolaId}/assistente/config`, {
        method: "PUT",
        body: JSON.stringify(corpo),
      });
      recarregar();
      setApiKey("");
      setAviso({ tipo: "ok", texto: sucesso });
    } catch (excecao) {
      setAviso({
        tipo: "erro",
        texto: excecao instanceof Error ? excecao.message : "Não foi possível salvar.",
      });
    } finally {
      setOcupado(false);
    }
  }

  function salvar() {
    void gravar(
      { provedor, api_key: apiKey.trim() || null, modelo: modelo.trim() || null },
      "Configuração salva.",
    );
  }

  async function desligar() {
    await gravar(
      { provedor: "local", api_key: null, modelo: null },
      "IA externa desligada. O assistente voltou ao modo local.",
    );
    setConfirmandoDesligar(false);
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
      <Card className="space-y-4 p-5 sm:p-6">
        {cabecalho}
        <Mensagem tipo="erro">
          Não foi possível carregar a configuração do assistente: {erro.message}
        </Mensagem>
        <Botao variante="secundario" onClick={recarregar}>
          Tentar de novo
        </Botao>
      </Card>
    );
  }
  if (!config) {
    // Carregando: o esqueleto do cartão (antes a seção ficava vazia sob o título).
    return (
      <Card className="space-y-3 p-5 sm:p-6" aria-busy="true">
        {cabecalho}
        <span className="sr-only">Carregando a configuração do assistente…</span>
        <Skeleton className="h-6 w-48" />
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-2/3" />
        <Skeleton className="h-10 w-40" />
      </Card>
    );
  }

  const botaoTestar = (
    <Botao variante="secundario" onClick={testar} disabled={ocupado}>
      Testar o assistente
    </Botao>
  );

  // Admin da escola: vê o estado, desliga e testa. Ligar/configurar é do global.
  if (!ehGlobal) {
    const externo = config.provedor !== "local";
    return (
      <Card className="space-y-4 p-5 sm:p-6">
        {cabecalho}
        <div className="flex flex-wrap items-center gap-3">
          <ChipEstado externo={externo} />
        </div>
        <div className="space-y-3 text-sm text-zinc-600 dark:text-zinc-300">
          <p>
            <span className="font-semibold text-zinc-800 dark:text-zinc-100">Provedor em uso: </span>
            {NOME_PROVEDOR[config.provedor] ?? config.provedor}
            {externo && config.modelo ? ` — modelo ${config.modelo}` : ""}
            {/* chave_definida=false também quando a cifra salva não abre mais
                (DATA_ENCRYPTION_KEY trocada): não é "sem chave salva". */}
            {externo && (config.chave_definida
              ? " (chave configurada)"
              : " (sem chave utilizável: o assistente responde no modo local)")}
          </p>
          {externo ? (
            <>
              <AvisoDadosFora />
              <p>
                A IA externa foi ligada pelo Admin Global. Você pode desligá-la: o
                assistente volta ao modo local e a chave salva é apagada.
              </p>
            </>
          ) : (
            <p>
              O assistente responde no modo local: por regras, no próprio servidor, sem
              enviar dados para fora. Ligar uma IA externa (Claude ou OpenAI) é exclusivo
              do Admin Global, porque ela envia dados da escola para fora do país.
            </p>
          )}
        </div>

        {aviso && <Mensagem tipo={aviso.tipo}>{aviso.texto}</Mensagem>}

        <div className="flex flex-wrap gap-2.5 border-t border-zinc-100 pt-4 dark:border-zinc-800">
          {externo && (
            // Ação que DESLIGA: neutra com acento vermelho (não o violeta de "seguir").
            <Botao variante="secundario" onClick={() => setConfirmandoDesligar(true)} disabled={ocupado}
                   className="!text-rose-700 hover:!border-rose-200 hover:!bg-rose-50 dark:!text-rose-300 dark:hover:!bg-rose-500/10">
              <Power size={15} aria-hidden />
              {ocupado ? "Desligando..." : "Desligar a IA externa"}
            </Botao>
          )}
          {botaoTestar}
        </div>

        <Confirmacao
          titulo="Desligar a IA externa?"
          aberto={confirmandoDesligar}
          aoFechar={() => setConfirmandoDesligar(false)}
          aoConfirmar={() => void desligar()}
          rotuloConfirmar={ocupado ? "Desligando..." : "Desligar"}
          variante="perigo"
          ocupado={ocupado}
        >
          <p>
            O assistente volta ao modo local (nenhum dado sai do servidor) e a chave salva é
            apagada. Só o Admin Global pode religá-la.
          </p>
        </Confirmacao>
      </Card>
    );
  }

  const trocouProvedor = provedor !== config.provedor;

  return (
    <Card className="space-y-5 p-5 sm:p-6">
      {cabecalho}
      <div className="space-y-2">
        <ChipEstado externo={config.provedor !== "local"} />
        <p className="text-sm text-zinc-600 dark:text-zinc-300">
          Com uma chave de API, o assistente vira uma IA de verdade: interpreta a
          pergunta e responde usando os dados da escola. Sem chave, funciona no
          modo local (respostas prontas por regras). A chave fica guardada
          cifrada no servidor e nunca aparece de novo aqui. Só o Admin Global
          liga e configura a IA externa; o administrador da escola vê o estado e
          pode desligá-la.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <label className="block text-sm">
          <span className="mb-1.5 block font-medium text-zinc-700 dark:text-zinc-300">Provedor</span>
          {/* Select NATIVO com a seta da v2: espaço à direita (pr-10) para o texto não
              encostar na seta e reticências quando o rótulo não cabe (celular). */}
          <span className="relative block">
            <select
              className={`${estiloInput} cursor-pointer appearance-none truncate pr-10 disabled:cursor-not-allowed`}
              value={provedor}
              onChange={(e) => setProvedor(e.target.value)}
              disabled={ocupado}
            >
              {PROVEDORES.map((p) => (
                <option key={p.valor} value={p.valor}>{p.rotulo}</option>
              ))}
            </select>
            <ChevronDown
              size={16}
              aria-hidden
              className="pointer-events-none absolute right-3.5 top-1/2 -translate-y-1/2 text-zinc-500 dark:text-zinc-400"
            />
          </span>
        </label>
        <label className="block text-sm">
          <span className="mb-1.5 block font-medium text-zinc-700 dark:text-zinc-300">Modelo (opcional)</span>
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
        <>
          <AvisoDadosFora />
          <label className="block text-sm">
            <span className="mb-1.5 flex flex-wrap items-center gap-2 font-medium text-zinc-700 dark:text-zinc-300">
              Chave de API
              {config.chave_definida && !trocouProvedor ? (
                <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-xs font-semibold text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300">
                  <CheckCircle2 size={13} aria-hidden /> chave já configurada
                </span>
              ) : (
                <span className="inline-flex items-center gap-1 rounded-full bg-ouro-50 px-2 py-0.5 text-xs font-semibold text-ouro-700 dark:bg-ouro-400/15 dark:text-ouro-300">
                  <XCircle size={13} aria-hidden />
                  {trocouProvedor
                    ? "novo provedor: informe a chave dele"
                    : "nenhuma chave utilizável: informe a chave de API"}
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
            <span className="mt-1.5 block text-xs text-zinc-500 dark:text-zinc-400">
              Para o Claude, crie a chave em console.anthropic.com → API Keys.
              {trocouProvedor && " Por segurança, a chave do provedor anterior não é reaproveitada."}
            </span>
          </label>
        </>
      )}

      {aviso && <Mensagem tipo={aviso.tipo}>{aviso.texto}</Mensagem>}

      <div className="flex flex-wrap justify-end gap-2.5 border-t border-zinc-100 pt-4 dark:border-zinc-800">
        {botaoTestar}
        <Botao onClick={salvar} disabled={ocupado}>
          {ocupado ? "Salvando..." : "Salvar"}
        </Botao>
      </div>
    </Card>
  );
}

/** Estado em uma pílula: modo local (verde) ou IA externa ligada (âmbar). */
function ChipEstado({ externo }: { externo: boolean }) {
  return externo ? (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-ouro-50 px-3 py-1 text-xs font-semibold text-ouro-700 dark:bg-ouro-400/15 dark:text-ouro-300">
      <Globe size={13} aria-hidden /> IA externa ligada
    </span>
  ) : (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-3 py-1 text-xs font-semibold text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300">
      <ShieldCheck size={13} aria-hidden /> Modo local: nada sai do servidor
    </span>
  );
}

/** O aviso de dados fora do país como destaque (antes era um texto âmbar miúdo). */
function AvisoDadosFora() {
  return (
    <div className="flex items-start gap-3 rounded-2xl border border-ouro-200 bg-ouro-50 p-4 text-sm text-ouro-700 dark:border-ouro-400/30 dark:bg-ouro-400/10 dark:text-ouro-300">
      <AlertTriangle size={18} className="mt-0.5 shrink-0" aria-hidden />
      <p>{AVISO_DADOS_FORA}</p>
    </div>
  );
}
