import { useState, useSyncExternalStore, type FormEvent } from "react";
import { Navigate } from "react-router-dom";
import { Eye, EyeOff, Loader2, Lock, Mail } from "lucide-react";

import { MolduraEntrada } from "../components/MolduraEntrada";
import { Carregando, Mensagem } from "../components/ui";
import { useApp } from "../context/AppContext";

// Classe base dos campos: altos (48 px, bom alvo de toque), cantos de 12 px e o
// mesmo foco violeta do resto do sistema. O anel de foco por teclado vem do
// :focus-visible global.
const CAMPO =
  "h-12 w-full rounded-xl border border-zinc-300 bg-white text-[15px] text-zinc-900 " +
  "placeholder:text-zinc-500 transition-colors duration-200 hover:border-zinc-400 " +
  "focus:border-indigo-500 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-100 dark:placeholder:text-zinc-400";

/** Exemplo no campo de usuário. No celular (< 640 px, o `sm` do Tailwind) o exemplo
 *  inteiro não cabe e saía cortado ("voce@escola.com ou @seu.us"); lá vai a versão
 *  curta — o rótulo acima já explica o formato. É só o atributo que muda (um campo só). */
const EXEMPLO_USUARIO = "voce@escola.com ou @seu.usuario";
const EXEMPLO_USUARIO_CELULAR = "e-mail ou @usuario";
const MEDIA_CELULAR = "(max-width: 639.98px)";

function assinarCelular(aoMudar: () => void): () => void {
  const consulta = window.matchMedia?.(MEDIA_CELULAR);
  if (!consulta) return () => undefined;
  if (consulta.addEventListener) {
    consulta.addEventListener("change", aoMudar);
    return () => consulta.removeEventListener("change", aoMudar);
  }
  // Safari < 14 só tem addListener.
  consulta.addListener(aoMudar);
  return () => consulta.removeListener(aoMudar);
}
const ehCelular = () => window.matchMedia?.(MEDIA_CELULAR).matches ?? false;

/**
 * Tela de entrada na identidade v2: painel marinho com o logotipo oficial e uma
 * frase curta, ao lado do cartão branco do formulário (ver `MolduraEntrada`). Os
 * rótulos ("E-mail ou nome de usuário", "Senha"), o autocomplete, o h1 e o fluxo
 * (redireciona para / quando já há sessão; mostra o erro da API) não mudaram.
 */
export default function Login() {
  const { usuario, carregando, entrar } = useApp();
  const [email, setEmail] = useState("");
  const [senha, setSenha] = useState("");
  const [mostrarSenha, setMostrarSenha] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [enviando, setEnviando] = useState(false);
  const celular = useSyncExternalStore(assinarCelular, ehCelular, () => false);

  if (carregando) return <Carregando texto="Abrindo o sistema..." />;
  if (usuario) return <Navigate to="/" replace />;

  async function enviar(evento: FormEvent) {
    evento.preventDefault();
    setErro(null);
    setEnviando(true);
    try {
      await entrar(email, senha);
    } catch (excecao) {
      setErro(excecao instanceof Error ? excecao.message : "Falha no login.");
    } finally {
      setEnviando(false);
    }
  }

  return (
    <MolduraEntrada>
      <h1 className="sr-only">Entrar na Constela Edu</h1>

      <div>
        <p className="text-2xl font-bold tracking-tight text-zinc-900 dark:text-white">Boas-vindas!</p>
        <p className="mt-1.5 text-sm text-zinc-500 dark:text-zinc-400">
          Use o acesso que a sua escola criou para você.
        </p>
      </div>

      <form onSubmit={enviar} noValidate className="mt-8 space-y-5">
        {/* E-mail / usuário */}
        <div className="space-y-2">
          <label htmlFor="login-email" className="block text-sm font-medium text-zinc-700 dark:text-zinc-300">
            E-mail ou nome de usuário
          </label>
          <div className="relative">
            <Mail
              aria-hidden
              className="pointer-events-none absolute left-3.5 top-1/2 h-[18px] w-[18px] -translate-y-1/2 text-zinc-400"
            />
            <input
              id="login-email"
              type="text"
              required
              autoComplete="username"
              placeholder={celular ? EXEMPLO_USUARIO_CELULAR : EXEMPLO_USUARIO}
              className={`${CAMPO} pl-11 pr-4`}
              value={email}
              onChange={(evento) => setEmail(evento.target.value)}
            />
          </div>
        </div>

        {/* Senha */}
        <div className="space-y-2">
          <label htmlFor="login-senha" className="block text-sm font-medium text-zinc-700 dark:text-zinc-300">
            Senha
          </label>
          <div className="relative">
            <Lock
              aria-hidden
              className="pointer-events-none absolute left-3.5 top-1/2 h-[18px] w-[18px] -translate-y-1/2 text-zinc-400"
            />
            <input
              id="login-senha"
              type={mostrarSenha ? "text" : "password"}
              required
              autoComplete="current-password"
              placeholder="••••••••"
              className={`${CAMPO} pl-11 pr-12`}
              value={senha}
              onChange={(evento) => setSenha(evento.target.value)}
            />
            <button
              type="button"
              aria-label={mostrarSenha ? "Esconder senha" : "Mostrar senha"}
              aria-pressed={mostrarSenha}
              onClick={() => setMostrarSenha((atual) => !atual)}
              className="absolute right-1.5 top-1/2 grid h-9 w-9 -translate-y-1/2 place-items-center rounded-lg text-zinc-500 transition-colors hover:bg-zinc-100 hover:text-zinc-800 dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-zinc-100"
            >
              {mostrarSenha
                ? <EyeOff aria-hidden className="h-[18px] w-[18px]" />
                : <Eye aria-hidden className="h-[18px] w-[18px]" />}
            </button>
          </div>
        </div>

        {erro && <Mensagem tipo="erro">{erro}</Mensagem>}

        {/* CTA principal: violeta da marca com a sombra de pílula. */}
        <button
          type="submit"
          disabled={enviando}
          className="!mt-7 flex h-12 w-full items-center justify-center gap-2 rounded-xl bg-indigo-600 text-[15px] font-semibold text-white shadow-pilula transition-all duration-200 hover:-translate-y-px hover:bg-indigo-700 active:translate-y-0 active:scale-[0.99] disabled:cursor-not-allowed disabled:opacity-70 disabled:hover:translate-y-0 motion-reduce:transition-none motion-reduce:hover:translate-y-0 motion-reduce:active:scale-100"
        >
          {enviando ? (
            <>
              <Loader2 aria-hidden className="h-[18px] w-[18px] animate-spin motion-reduce:animate-none" />
              Entrando...
            </>
          ) : (
            "Entrar"
          )}
        </button>
      </form>
    </MolduraEntrada>
  );
}
