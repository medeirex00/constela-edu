import { useState, type FormEvent } from "react";
import { Navigate } from "react-router-dom";

import { Botao, Carregando, Mensagem } from "../components/ui";
import { useApp } from "../context/AppContext";

export default function Login() {
  const { usuario, carregando, entrar } = useApp();
  const [email, setEmail] = useState("");
  const [senha, setSenha] = useState("");
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
    <div className="flex min-h-screen items-center justify-center px-4">
      <div className="card w-full max-w-sm p-6">
        <div className="mb-6 flex items-center gap-2.5">
          <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-indigo-600 text-base font-bold text-white">
            C
          </span>
          <div className="leading-tight">
            <p className="font-semibold tracking-tight">Constela Edu</p>
            <p className="text-xs text-zinc-500 dark:text-zinc-400">Gestão e Premiação Escolar</p>
          </div>
        </div>

        <form onSubmit={enviar} className="space-y-4">
          <label className="block text-sm">
            <span className="mb-1 block font-medium">E-mail</span>
            <input
              type="email"
              required
              autoComplete="username"
              className="w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 dark:border-zinc-700 dark:bg-zinc-950"
              value={email}
              onChange={(evento) => setEmail(evento.target.value)}
            />
          </label>
          <label className="block text-sm">
            <span className="mb-1 block font-medium">Senha</span>
            <input
              type="password"
              required
              autoComplete="current-password"
              className="w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 dark:border-zinc-700 dark:bg-zinc-950"
              value={senha}
              onChange={(evento) => setSenha(evento.target.value)}
            />
          </label>
          {erro && <Mensagem tipo="erro">{erro}</Mensagem>}
          <Botao type="submit" className="w-full" disabled={enviando}>
            {enviando ? "Entrando..." : "Entrar"}
          </Botao>
        </form>
      </div>
    </div>
  );
}
