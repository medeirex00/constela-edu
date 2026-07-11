/**
 * Formulário de credenciais de UMA plataforma (Matific / Elefante), reutilizado
 * pelo painel de Sincronização e pelo assistente de onboarding.
 *
 * A senha é enviada uma única vez, cifrada no servidor (Fernet) e NUNCA volta
 * ao navegador. Salvar já valida a conexão; o resultado (ok/erro) é mostrado
 * aqui mesmo. Também permite testar de novo e desconectar (remove a credencial).
 */
import { KeyRound } from "lucide-react";
import { useState } from "react";

import { useMutation } from "../hooks/useMutation";
import { api } from "../lib/api";
import { Botao, Campo, Mensagem, estiloInput } from "./ui";

interface ResultadoTeste {
  ok: boolean;
  mensagem: string;
  codigo?: string | null;
}

export interface CredenciaisFormProps {
  /** Prefixo da API por escola, ex.: `/escolas/1/sync`. */
  base: string;
  plataforma: string;
  nome: string;
  /** `credencial_status`: nao_configurada | nao_validada | valida | invalida. */
  status: string;
  /** Recarrega o status no componente pai após qualquer mudança. */
  aoMudar?: () => void;
  /** Disparado quando a credencial é validada com sucesso (onboarding avança). */
  aoValidado?: () => void;
}

export function CredenciaisForm({
  base, plataforma, nome, status, aoMudar, aoValidado,
}: CredenciaisFormProps) {
  const [usuario, setUsuario] = useState("");
  const [senha, setSenha] = useState("");
  const [resultado, setResultado] = useState<ResultadoTeste | null>(null);
  const configurada = status !== "nao_configurada";

  const salvar = useMutation(async () => {
    const r = await api<ResultadoTeste>(`${base}/credenciais/${plataforma}`, {
      method: "PUT",
      body: JSON.stringify({ usuario, senha }),
    });
    setResultado(r);
    setSenha("");
    if (r.ok) aoValidado?.();
    return r;
  }, { aoSucesso: aoMudar });

  const testar = useMutation(async () => {
    const r = await api<ResultadoTeste>(
      `${base}/credenciais/${plataforma}/testar`, { method: "POST" });
    setResultado(r);
    if (r.ok) aoValidado?.();
    return r;
  }, { aoSucesso: aoMudar });

  const desconectar = useMutation(async () => {
    await api(`${base}/credenciais/${plataforma}`, { method: "DELETE" });
    setResultado(null);
    setUsuario("");
  }, { aoSucesso: aoMudar });

  const erro = salvar.erro ?? testar.erro ?? desconectar.erro;

  return (
    <div className="grid gap-3 sm:max-w-md">
      <Campo rotulo={`Usuário da ${nome}`}>
        <input
          className={estiloInput}
          value={usuario}
          autoComplete="off"
          placeholder="e-mail ou login usado na plataforma"
          onChange={(e) => setUsuario(e.target.value)}
        />
      </Campo>
      <Campo rotulo={`Senha da ${nome}`}>
        <input
          className={estiloInput}
          type="password"
          value={senha}
          autoComplete="new-password"
          placeholder={configurada ? "•••••• (preencha só para trocar)" : "senha de acesso"}
          onChange={(e) => setSenha(e.target.value)}
        />
      </Campo>

      <p className="flex items-start gap-1.5 text-xs text-zinc-500 dark:text-zinc-400">
        <KeyRound size={13} className="mt-0.5 shrink-0" />
        A senha é cifrada no servidor e nunca é exibida de novo — serve apenas para
        o sistema baixar os relatórios por você.
      </p>

      <div className="flex flex-wrap gap-2">
        <Botao disabled={salvar.enviando || !usuario || !senha} onClick={() => salvar.executar()}>
          {salvar.enviando ? "Validando…" : "Salvar e validar"}
        </Botao>
        <Botao variante="neutro" disabled={testar.enviando || !configurada}
          onClick={() => testar.executar()}>
          {testar.enviando ? "Testando…" : "Testar conexão"}
        </Botao>
        {configurada && (
          <Botao variante="neutro" disabled={desconectar.enviando}
            onClick={() => desconectar.executar()}>
            {desconectar.enviando ? "Removendo…" : "Desconectar"}
          </Botao>
        )}
      </div>

      {resultado && (
        <Mensagem tipo={resultado.ok ? "ok" : "erro"}>{resultado.mensagem}</Mensagem>
      )}
      {erro && <Mensagem tipo="erro">{erro.message}</Mensagem>}
    </div>
  );
}
