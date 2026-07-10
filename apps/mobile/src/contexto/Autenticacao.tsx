/** Sessão do app: login, escola ativa, registro de push e logout — com boot
 *  offline (restaura a última sessão salva cifrada e NÃO desloga quando está
 *  apenas sem rede; só desloga em token inválido/expirado). */
import {
  api,
  guardarToken,
  limparToken,
  loginRequest,
  obterToken,
  type Escola,
  type Usuario,
} from "@constela/core";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";

import { aoExpirarSessao } from "../api";
import { esquecerChave } from "../armazenamento/cifra";
import { lerSessao, limparSessao, salvarSessao, type SessaoSalva } from "../armazenamento/sessao";
import { clienteQuery, persistidor } from "../cliente-query";
import { registrarParaPush, removerRegistroPush } from "../notificacoes";

interface ContextoAutenticacao {
  usuario: Usuario | null;
  escolas: Escola[];
  escolaId: number | null;
  carregando: boolean;
  entrar: (email: string, senha: string) => Promise<void>;
  sair: () => Promise<void>;
  selecionarEscola: (id: number) => void;
}

const Contexto = createContext<ContextoAutenticacao | null>(null);

export function ProvedorAutenticacao({ children }: { children: ReactNode }) {
  const [usuario, setUsuario] = useState<Usuario | null>(null);
  const [escolas, setEscolas] = useState<Escola[]>([]);
  const [escolaId, setEscolaId] = useState<number | null>(null);
  const [carregando, setCarregando] = useState(true);
  const [tokenPush, setTokenPush] = useState<string | null>(null);

  // Toda mudança de sessão é persistida CIFRADA — é o que permite o boot offline.
  useEffect(() => {
    if (usuario) void salvarSessao({ usuario, escolas, escolaId });
  }, [usuario, escolas, escolaId]);

  const aplicarSessao = useCallback((s: SessaoSalva) => {
    setUsuario(s.usuario);
    setEscolas(s.escolas);
    setEscolaId(s.escolaId);
  }, []);

  // Refresh a partir da REDE. Mantém a escola atual se ainda válida.
  const atualizarSessao = useCallback(async (preferidaId: number | null) => {
    const [eu, lista] = await Promise.all([
      api<Usuario>("/auth/me"),
      api<Escola[]>("/escolas"),
    ]);
    const valido = preferidaId !== null && lista.some((escola) => escola.id === preferidaId);
    const escolhido = valido ? preferidaId : lista[0]?.id ?? null;
    setUsuario(eu);
    setEscolas(lista);
    setEscolaId(escolhido);
    if (escolhido !== null) registrarParaPush(escolhido).then(setTokenPush);
  }, []);

  // Encerra a sessão LOCAL: estado, sessão salva, cache das telas e chave de
  // cifra (rotacionada para o cache antigo virar ilegível num aparelho partilhado).
  const encerrarLocal = useCallback(async () => {
    setUsuario(null);
    setEscolas([]);
    setEscolaId(null);
    setTokenPush(null);
    clienteQuery.clear();
    await Promise.allSettled([limparSessao(), persistidor.removeClient()]);
    await esquecerChave();
  }, []);

  useEffect(() => {
    // Token inválido/expirado (401 no cliente HTTP): aí sim desloga de fato.
    aoExpirarSessao(() => {
      void limparToken();
      void encerrarLocal();
    });

    (async () => {
      try {
        if (!(await obterToken())) return; // sem token → tela de login
        const salva = await lerSessao();
        if (salva) aplicarSessao(salva); // abre offline na hora, com o cache
        // Refresh da rede. Se falhar por ESTAR OFFLINE, seguimos com o cache
        // (o catch não desloga); só o 401 (acima) encerra a sessão.
        await atualizarSessao(salva?.escolaId ?? null);
      } catch {
        // Falha de rede: mantém a sessão salva (se houver). Sem sessão salva e
        // sem rede, o usuário fica na tela de login e conecta quando puder.
      } finally {
        setCarregando(false);
      }
    })();
  }, [aplicarSessao, atualizarSessao, encerrarLocal]);

  const entrar = useCallback(
    async (email: string, senha: string) => {
      const resposta = await loginRequest(email, senha);
      await guardarToken(resposta.access_token);
      await atualizarSessao(null);
    },
    [atualizarSessao],
  );

  const sair = useCallback(async () => {
    if (escolaId !== null) await removerRegistroPush(escolaId, tokenPush);
    await limparToken();
    await encerrarLocal();
  }, [escolaId, tokenPush, encerrarLocal]);

  const selecionarEscola = useCallback((id: number) => {
    setEscolaId(id); // o efeito de persistência salva a sessão com a nova escola
  }, []);

  return (
    <Contexto.Provider
      value={{ usuario, escolas, escolaId, carregando, entrar, sair, selecionarEscola }}
    >
      {children}
    </Contexto.Provider>
  );
}

export function useAutenticacao(): ContextoAutenticacao {
  const contexto = useContext(Contexto);
  if (!contexto) {
    throw new Error("useAutenticacao deve ser usado dentro de ProvedorAutenticacao");
  }
  return contexto;
}
