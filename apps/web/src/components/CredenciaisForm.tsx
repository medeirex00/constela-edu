/**
 * Formulário de credenciais de UMA plataforma (Matific / Elefante), reutilizado
 * pelo painel de Sincronização e pelo assistente de onboarding.
 *
 * A senha é enviada uma única vez, cifrada no servidor (Fernet) e NUNCA volta
 * ao navegador. Salvar já valida a conexão; o resultado (ok/erro) é mostrado
 * aqui mesmo. Também permite testar de novo e desconectar (remove a credencial).
 */
import { ChevronDown, KeyRound, ShieldCheck, Unplug } from "lucide-react";
import { useId, useState, type FormEvent } from "react";

import { useMutation } from "../hooks/useMutation";
import { api } from "../lib/api";
import { CaixaAviso } from "./CaixaAviso";
import { Botao, Campo, Confirmacao, Mensagem, estiloInput } from "./ui";

interface EscolaExterna {
  id: string;
  nome?: string;
}

interface ResultadoTeste {
  ok: boolean;
  mensagem: string;
  codigo?: string | null;
  /** Escolas que a conta enxerga na plataforma (sem segredo; opcional). */
  escolas_externas?: EscolaExterna[] | null;
  escola_vinculada?: EscolaExterna | null;
  escola_confere?: boolean | null;
  aviso_escola?: string | null;
}

const descreverEscola = (e: EscolaExterna) => (e.nome ? `${e.nome} (${e.id})` : e.id);

export interface CredenciaisFormProps {
  /** Prefixo da API por escola, ex.: `/escolas/1/sync`. */
  base: string;
  plataforma: string;
  nome: string;
  /** `credencial_status`: nao_configurada | nao_validada | valida | invalida |
   *  expirada | ilegivel (a senha salva não abre mais: só o recadastro resolve). */
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
  const [urlLogin, setUrlLogin] = useState("");
  const [avancado, setAvancado] = useState(false);
  const [confirmarDesconexao, setConfirmarDesconexao] = useState(false);
  const [resultado, setResultado] = useState<ResultadoTeste | null>(null);
  const idAvancado = useId();
  const configurada = status !== "nao_configurada";
  // A senha salva não abre com a chave atual do servidor: testar não adianta, só
  // salvar de novo (com a senha digitada outra vez).
  const ilegivel = status === "ilegivel";

  const salvar = useMutation(async () => {
    const extra = urlLogin.trim() ? { url_login: urlLogin.trim() } : undefined;
    const r = await api<ResultadoTeste>(`${base}/credenciais/${plataforma}`, {
      method: "PUT",
      body: JSON.stringify({ usuario, senha, ...(extra ? { extra } : {}) }),
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
    setConfirmarDesconexao(false);
  }, { aoSucesso: aoMudar });

  // O erro de "Desconectar" aparece dentro da confirmação (que fica aberta).
  const erro = salvar.erro ?? testar.erro;
  const podeSalvar = !salvar.enviando && Boolean(usuario) && Boolean(senha);

  // <form>: Enter envia "Salvar e validar" e o gerenciador de senhas reconhece o
  // par usuário/senha. preventDefault: nada de recarregar a página.
  function aoEnviar(evento: FormEvent<HTMLFormElement>) {
    evento.preventDefault();
    if (podeSalvar) void salvar.executar();
  }

  return (
    <>
      <form className="grid gap-3.5 sm:max-w-md" onSubmit={aoEnviar} noValidate>
        {ilegivel && (
          <Mensagem tipo="erro">
            A senha salva do {nome} não pode mais ser lida pelo servidor (a chave que a
            protegia foi trocada). Informe usuário e senha de novo e clique em “Salvar e
            validar”.
          </Mensagem>
        )}
        <Campo rotulo={`Usuário do ${nome}`}>
          <input
            className={estiloInput}
            value={usuario}
            name="usuario"
            autoComplete="off"
            placeholder="e-mail ou login usado na plataforma"
            onChange={(e) => setUsuario(e.target.value)}
          />
        </Campo>
        <Campo rotulo={`Senha do ${nome}`}>
          <input
            className={estiloInput}
            type="password"
            value={senha}
            name="senha"
            autoComplete="new-password"
            placeholder={ilegivel
              ? "digite a senha de novo"
              : configurada ? "•••••• (preencha só para trocar)" : "senha de acesso"}
            onChange={(e) => setSenha(e.target.value)}
          />
        </Campo>

        <p className="flex items-start gap-2 rounded-xl bg-zinc-50 px-3 py-2.5 text-xs text-zinc-600 dark:bg-zinc-800/50 dark:text-zinc-400">
          <KeyRound size={14} aria-hidden className="mt-0.5 shrink-0 text-indigo-500" />
          A senha é cifrada no servidor e nunca é exibida de novo — serve apenas para
          o sistema baixar os relatórios por você.
        </p>

        <div>
          <button
            type="button"
            aria-expanded={avancado}
            aria-controls={avancado ? idAvancado : undefined}
            className="inline-flex items-center gap-1 rounded-lg text-xs font-semibold text-indigo-700 hover:underline dark:text-indigo-300"
            onClick={() => setAvancado((v) => !v)}
          >
            {avancado ? "Ocultar opções avançadas" : "Opções avançadas"}
            <ChevronDown size={14} aria-hidden className={`transition-transform ${avancado ? "rotate-180" : ""}`} />
          </button>
          {avancado && (
            <div id={idAvancado} className="mt-2">
              <Campo rotulo="Endereço de login (opcional)">
                <input
                  className={estiloInput}
                  value={urlLogin}
                  placeholder="ex.: https://…/login — só se o padrão não funcionar"
                  onChange={(e) => setUrlLogin(e.target.value)}
                />
                <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
                  Se a validação disser que não encontrou o formulário de login, cole
                  aqui o endereço exato da página de login da plataforma.
                </p>
              </Campo>
            </div>
          )}
        </div>

        <div className="flex flex-wrap gap-2">
          <Botao type="submit" disabled={!podeSalvar}>
            <ShieldCheck size={15} aria-hidden />
            {salvar.enviando ? "Validando…" : "Salvar e validar"}
          </Botao>
          <Botao type="button" variante="secundario" disabled={testar.enviando || !configurada || ilegivel}
            onClick={() => testar.executar()}>
            {testar.enviando ? "Testando…" : "Testar conexão"}
          </Botao>
          {configurada && (
            <button type="button" disabled={desconectar.enviando}
              className="inline-flex items-center justify-center gap-2 rounded-xl px-4 py-2.5 text-sm font-semibold text-rose-700 transition-colors hover:bg-rose-50 disabled:cursor-not-allowed disabled:text-zinc-400 dark:text-rose-300 dark:hover:bg-rose-500/10"
              onClick={() => { desconectar.limparErro(); setConfirmarDesconexao(true); }}>
              <Unplug size={15} aria-hidden />
              {desconectar.enviando ? "Removendo…" : "Desconectar"}
            </button>
          )}
        </div>

        {resultado && (
          <Mensagem tipo={resultado.ok ? "ok" : "erro"}>{resultado.mensagem}</Mensagem>
        )}
        {resultado?.ok && resultado.escolas_externas && resultado.escolas_externas.length > 0 && (
          // Para o gestor conferir que a credencial é DESTA escola (sem segredo).
          <p className="text-sm text-zinc-600 dark:text-zinc-300">
            Escola(s) que esta conta enxerga na plataforma:{" "}
            <strong>{resultado.escolas_externas.map(descreverEscola).join("; ")}</strong>
            {resultado.escola_vinculada && (
              <> · vinculada a esta escola: {descreverEscola(resultado.escola_vinculada)}</>
            )}
          </p>
        )}
        {resultado?.ok && resultado.aviso_escola && (
          <CaixaAviso tom="alerta" role="status">
            <p>{resultado.aviso_escola}</p>
          </CaixaAviso>
        )}
        {erro && <Mensagem tipo="erro">{erro.message}</Mensagem>}
      </form>

      {/* Desconectar apaga a credencial salva: diz o que acontece ANTES. Fica FORA
          do <form> (os botões do modal não podem virar "submit" do formulário). */}
      <Confirmacao
        titulo={`Desconectar a escola da plataforma ${nome}?`}
        aberto={confirmarDesconexao}
        aoFechar={() => setConfirmarDesconexao(false)}
        aoConfirmar={() => { void desconectar.executar(); }}
        rotuloConfirmar="Sim, desconectar"
        variante="perigo"
        ocupado={desconectar.enviando}
      >
        <p>
          O acesso salvo (usuário e senha) desta escola é removido do servidor. Sem ele, nenhuma
          coleta da {nome} acontece — nem a automática, nem a manual — até alguém cadastrar o
          acesso de novo.
        </p>
        <p>Nenhum dado já coletado é apagado.</p>
        {desconectar.erro && <Mensagem tipo="erro">{desconectar.erro.message}</Mensagem>}
      </Confirmacao>
    </>
  );
}
