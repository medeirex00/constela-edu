import { useState, type FormEvent } from "react";
import { Navigate } from "react-router-dom";
import { Eye, EyeOff, Loader2, Lock, Mail } from "lucide-react";

import { LogoHorizontal } from "../components/Logo";
import { Carregando, Mensagem } from "../components/ui";
import { useApp } from "../context/AppContext";

// Classe base dos campos: alto, cantos suaves, foco discreto (borda + leve
// realce do fundo). O anel de foco por teclado vem do :focus-visible global.
const CAMPO =
  "h-12 w-full rounded-xl border border-white/10 bg-white/[0.04] text-[15px] " +
  "text-zinc-100 placeholder:text-zinc-500 outline-none transition-all duration-200 " +
  "focus:border-indigo-500/70 focus:bg-white/[0.06]";

/**
 * Tela de entrada. Visual "premium escuro" deliberado (independe do tema do
 * app: o wrapper força `dark`), no nível de Linear/Vercel/Stripe — sem
 * ilustrações, com fundo discreto, card com profundidade e microinterações
 * curtas. Os efeitos ficam em index.css (prefixo `login-`).
 */
export default function Login() {
  const { usuario, carregando, entrar } = useApp();
  const [email, setEmail] = useState("");
  const [senha, setSenha] = useState("");
  const [mostrarSenha, setMostrarSenha] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [enviando, setEnviando] = useState(false);

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
    <div className="dark login-bg login-fade flex min-h-screen items-center justify-center p-4 sm:p-6">
      <main className="login-surgir w-full max-w-md">
        <h1 className="sr-only">Entrar na Constela Edu</h1>

        <div className="login-card rounded-2xl p-8 sm:p-10">
          {/* Marca + posicionamento institucional */}
          <div className="flex flex-col items-start">
            <LogoHorizontal altura={52} />
            <p className="mt-7 text-[15px] leading-snug text-zinc-300">
              Transformando dados em reconhecimento escolar.
            </p>
          </div>

          <form onSubmit={enviar} noValidate className="mt-10 space-y-6">
            {/* E-mail / usuário */}
            <div className="space-y-2">
              <label htmlFor="login-email" className="block text-sm font-medium text-zinc-300">
                E-mail ou nome de usuário
              </label>
              <div className="relative">
                <Mail
                  aria-hidden
                  className="pointer-events-none absolute left-3.5 top-1/2 h-[18px] w-[18px] -translate-y-1/2 text-zinc-500"
                />
                <input
                  id="login-email"
                  type="text"
                  required
                  autoComplete="username"
                  placeholder="voce@escola.com ou @seu.usuario"
                  className={`${CAMPO} pl-11 pr-4`}
                  value={email}
                  onChange={(evento) => setEmail(evento.target.value)}
                />
              </div>
            </div>

            {/* Senha */}
            <div className="space-y-2">
              <label htmlFor="login-senha" className="block text-sm font-medium text-zinc-300">
                Senha
              </label>
              <div className="relative">
                <Lock
                  aria-hidden
                  className="pointer-events-none absolute left-3.5 top-1/2 h-[18px] w-[18px] -translate-y-1/2 text-zinc-500"
                />
                <input
                  id="login-senha"
                  type={mostrarSenha ? "text" : "password"}
                  required
                  autoComplete="current-password"
                  placeholder="••••••••"
                  className={`${CAMPO} pl-11 pr-11`}
                  value={senha}
                  onChange={(evento) => setSenha(evento.target.value)}
                />
                <button
                  type="button"
                  aria-label={mostrarSenha ? "Esconder senha" : "Mostrar senha"}
                  aria-pressed={mostrarSenha}
                  onClick={() => setMostrarSenha((atual) => !atual)}
                  className="absolute right-2 top-1/2 -translate-y-1/2 rounded-lg p-2 text-zinc-500 transition-colors hover:text-zinc-200"
                >
                  {mostrarSenha ? <EyeOff className="h-[18px] w-[18px]" /> : <Eye className="h-[18px] w-[18px]" />}
                </button>
              </div>
            </div>

            {erro && <Mensagem tipo="erro">{erro}</Mensagem>}

            {/* CTA principal */}
            <button
              type="submit"
              disabled={enviando}
              className="mt-1 flex h-12 w-full items-center justify-center gap-2 rounded-xl bg-indigo-600 text-[15px] font-semibold text-white shadow-lg shadow-indigo-950/40 outline-none transition-all duration-200 hover:-translate-y-px hover:bg-indigo-500 hover:shadow-xl hover:shadow-indigo-900/50 active:translate-y-0 active:scale-[0.99] disabled:cursor-not-allowed disabled:opacity-70 disabled:hover:translate-y-0 motion-reduce:transition-none motion-reduce:hover:translate-y-0 motion-reduce:active:scale-100"
            >
              {enviando ? (
                <>
                  <Loader2 aria-hidden className="h-[18px] w-[18px] animate-spin" />
                  Entrando...
                </>
              ) : (
                "Entrar"
              )}
            </button>
          </form>
        </div>

        {/* Rodapé discreto */}
        <p className="mt-7 text-center text-xs text-zinc-400">
          Plataforma segura&nbsp;·&nbsp;LGPD&nbsp;·&nbsp;Dados protegidos
        </p>
      </main>
    </div>
  );
}
