/**
 * Página PÚBLICA de redefinição de senha (a pessoa não consegue entrar).
 *
 * Abre com ?token=... vindo do link gerado por um gestor. Confere o token,
 * deixa a pessoa escolher uma nova senha e a define. O token é de uso único e
 * expira; a senha original nunca é recuperada, apenas substituída.
 *
 * Identidade v2: a mesma moldura do Login (painel marinho + cartão branco), com os
 * campos e o botão do sistema. O "Ir para o login" é um LINK com cara de botão (antes
 * era um botão dentro de um link — interativo dentro de interativo).
 */
import { useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { KeyRound } from "lucide-react";

import { MolduraEntrada } from "../components/MolduraEntrada";
import {
  Botao, Campo, Carregando, ESTILOS_BOTAO, IconePastel, Mensagem, TAMANHOS_BOTAO, estiloInput,
} from "../components/ui";
import { useApi } from "../hooks/useApi";
import { ApiError, api } from "../lib/api";

type Estado =
  | { fase: "verificando" }
  | { fase: "invalido" }
  | { fase: "formulario"; nome: string }
  | { fase: "concluido" };

/** Link com o visual do botão primário (sem aninhar <button> em <a>). */
const LINK_BOTAO = `inline-flex w-full items-center justify-center font-semibold transition-colors ${TAMANHOS_BOTAO.lg} ${ESTILOS_BOTAO.primario}`;

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
    <MolduraEntrada>
      <div className="mb-7 flex items-center gap-3">
        <IconePastel icone={KeyRound} tom="violeta" tamanho="lg" />
        <div className="min-w-0">
          <h1 className="text-2xl font-bold tracking-tight text-zinc-900 dark:text-white">Redefinição de senha</h1>
          <p className="mt-0.5 text-sm text-zinc-500 dark:text-zinc-400">Link de uso único, gerado por quem administra a sua conta.</p>
        </div>
      </div>

      {estado.fase === "verificando" && <Carregando texto="Conferindo o link..." />}

      {estado.fase === "invalido" && (
        <div className="space-y-5">
          <Mensagem tipo="erro">
            {/* Genérico: a conta da Secretaria (e a global) recebe o link do Administrador
                Global, não da escola; o GET do link não diz de quem é a conta. */}
            Este link é inválido ou expirou. Peça um novo a quem administra a sua conta (na escola, o
            administrador da escola; na Secretaria, o Administrador Global da plataforma).
          </Mensagem>
          <Link
            to="/login"
            className="block rounded-lg text-center text-sm font-semibold text-indigo-700 hover:underline dark:text-indigo-300"
          >
            Voltar para o login
          </Link>
        </div>
      )}

      {estado.fase === "formulario" && (
        <form onSubmit={enviar} className="space-y-5">
          <p className="text-sm text-zinc-600 dark:text-zinc-300">
            {estado.nome ? <>Olá, <strong className="font-semibold text-zinc-900 dark:text-white">{estado.nome}</strong>! </> : null}
            Escolha uma nova senha (mínimo 8 caracteres).
          </p>
          <Campo rotulo="Nova senha">
            <input
              type="password"
              required
              autoComplete="new-password"
              minLength={8}
              className={`${estiloInput} h-12`}
              value={senha}
              onChange={(e) => setSenha(e.target.value)}
              autoFocus
            />
          </Campo>
          <Campo rotulo="Repita a nova senha">
            <input
              type="password"
              required
              autoComplete="new-password"
              minLength={8}
              className={`${estiloInput} h-12`}
              value={senha2}
              onChange={(e) => setSenha2(e.target.value)}
            />
          </Campo>
          {senha2 && senha !== senha2 && (
            <p className="text-xs font-medium text-rose-600 dark:text-rose-400">As senhas não coincidem.</p>
          )}
          {erro && <Mensagem tipo="erro">{erro}</Mensagem>}
          <Botao
            type="submit"
            tamanho="lg"
            className="w-full"
            disabled={enviando || senha.length < 8 || senha !== senha2}
          >
            {enviando ? "Salvando..." : "Definir nova senha"}
          </Botao>
        </form>
      )}

      {estado.fase === "concluido" && (
        <div className="space-y-5">
          <Mensagem tipo="ok">
            Senha redefinida! Você já pode entrar com a nova senha.
          </Mensagem>
          <Link to="/login" className={LINK_BOTAO}>
            Ir para o login
          </Link>
        </div>
      )}
    </MolduraEntrada>
  );
}
