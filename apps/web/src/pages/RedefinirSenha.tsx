/**
 * Página PÚBLICA de redefinição de senha (a pessoa não consegue entrar).
 *
 * Abre com ?token=... vindo do link gerado por um gestor. Confere o token,
 * deixa a pessoa escolher uma nova senha e a define. O token é de uso único e
 * expira; a senha original nunca é recuperada, apenas substituída.
 */
import { useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { LogoHorizontal } from "../components/Logo";
import { Botao, Carregando, Mensagem } from "../components/ui";
import { useApi } from "../hooks/useApi";
import { ApiError, api } from "../lib/api";

type Estado =
  | { fase: "verificando" }
  | { fase: "invalido" }
  | { fase: "formulario"; nome: string }
  | { fase: "concluido" };

const inputCls =
  "w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 dark:border-zinc-700 dark:bg-zinc-950";

export default function RedefinirSenha() {
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const [senha, setSenha] = useState("");
  const [senha2, setSenha2] = useState("");
  const [erro, setErro] = useState<string | null>(null);
  const [enviando, setEnviando] = useState(false);
  const [concluido, setConcluido] = useState(false);

  // Confere o link no servidor (uso único, expira). Falha transitória de rede é
  // reavaliada pelo retry do hook; token inválido/expirado cai em "invalido".
  const { dados: validacao, carregando } = useApi<{ valido: boolean; nome?: string }>(
    token ? `/auth/redefinir-senha/${encodeURIComponent(token)}` : null);

  const estado: Estado = concluido
    ? { fase: "concluido" }
    : carregando
      ? { fase: "verificando" }
      : validacao?.valido
        ? { fase: "formulario", nome: validacao.nome ?? "" }
        : { fase: "invalido" };

  async function enviar(evento: FormEvent) {
    evento.preventDefault();
    setErro(null);
    if (senha !== senha2) {
      setErro("As senhas não coincidem.");
      return;
    }
    setEnviando(true);
    try {
      await api("/auth/redefinir-senha", {
        method: "POST",
        body: JSON.stringify({ token, nova_senha: senha }),
      });
      setConcluido(true);
    } catch (e) {
      setErro(e instanceof ApiError ? e.message : "Não foi possível redefinir a senha.");
    } finally {
      setEnviando(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <div className="card w-full max-w-sm p-6">
        <div className="mb-6 flex flex-col items-start gap-1.5">
          <LogoHorizontal altura={44} />
          <p className="text-xs text-zinc-500 dark:text-zinc-400">Redefinição de senha</p>
        </div>

        {estado.fase === "verificando" && <Carregando texto="Conferindo o link..." />}

        {estado.fase === "invalido" && (
          <div className="space-y-4">
            <Mensagem tipo="erro">
              Este link é inválido ou expirou. Peça um novo ao administrador da escola.
            </Mensagem>
            <Link
              to="/login"
              className="block text-center text-sm text-indigo-600 hover:underline dark:text-indigo-400"
            >
              Voltar para o login
            </Link>
          </div>
        )}

        {estado.fase === "formulario" && (
          <form onSubmit={enviar} className="space-y-4">
            <p className="text-sm text-zinc-600 dark:text-zinc-300">
              {estado.nome ? <>Olá, <strong>{estado.nome}</strong>! </> : null}
              Escolha uma nova senha (mínimo 8 caracteres).
            </p>
            <label className="block text-sm">
              <span className="mb-1 block font-medium">Nova senha</span>
              <input
                type="password"
                required
                autoComplete="new-password"
                minLength={8}
                className={inputCls}
                value={senha}
                onChange={(e) => setSenha(e.target.value)}
                autoFocus
              />
            </label>
            <label className="block text-sm">
              <span className="mb-1 block font-medium">Repita a nova senha</span>
              <input
                type="password"
                required
                autoComplete="new-password"
                minLength={8}
                className={inputCls}
                value={senha2}
                onChange={(e) => setSenha2(e.target.value)}
              />
            </label>
            {senha2 && senha !== senha2 && (
              <p className="text-xs text-red-600 dark:text-red-400">As senhas não coincidem.</p>
            )}
            {erro && <Mensagem tipo="erro">{erro}</Mensagem>}
            <Botao
              type="submit"
              className="w-full"
              disabled={enviando || senha.length < 8 || senha !== senha2}
            >
              {enviando ? "Salvando..." : "Definir nova senha"}
            </Botao>
          </form>
        )}

        {estado.fase === "concluido" && (
          <div className="space-y-4">
            <Mensagem tipo="ok">
              Senha redefinida! Você já pode entrar com a nova senha.
            </Mensagem>
            <Link to="/login">
              <Botao className="w-full">Ir para o login</Botao>
            </Link>
          </div>
        )}
      </div>
    </div>
  );
}
