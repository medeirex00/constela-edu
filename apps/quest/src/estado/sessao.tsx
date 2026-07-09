/**
 * Sessão do astronauta: boot, login (código+PIN ou QR do cartão) e logout.
 *
 * O cliente HTTP vem do @constela/core com adaptadores web (localStorage +
 * volta para a tela de entrada em 401). O QR do cartão chega como
 * /entrar?qr=… — consumido no boot e removido da URL (não fica no histórico).
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import type { ReactNode } from "react";

import { configurarApi, guardarToken, limparToken } from "@constela/core";
import { entrarPorQr, meuPerfil } from "@constela/quest-core";
import type { PerfilQuest, SessaoQuest } from "@constela/quest-core";

const CHAVE_TOKEN = "quest_token";

type Estado = "carregando" | "deslogado" | "logado";

interface ContextoSessao {
  estado: Estado;
  perfil: PerfilQuest | null;
  entrarComSessao(sessao: SessaoQuest): Promise<void>;
  atualizarPerfil(perfil: PerfilQuest): void;
  sair(): Promise<void>;
}

const Contexto = createContext<ContextoSessao | null>(null);

let apiConfigurada = false;

function configurarApiUmaVez(aoExpirar: () => void) {
  if (apiConfigurada) return;
  apiConfigurada = true;
  configurarApi({
    base: "/api/v1",
    armazenamento: {
      obter: () => localStorage.getItem(CHAVE_TOKEN),
      guardar: (token) => localStorage.setItem(CHAVE_TOKEN, token),
      remover: () => localStorage.removeItem(CHAVE_TOKEN),
    },
    aoExpirarSessao: aoExpirar,
  });
}

export function SessaoProvider({ children }: { children: ReactNode }) {
  const [estado, setEstado] = useState<Estado>("carregando");
  const [perfil, setPerfil] = useState<PerfilQuest | null>(null);

  const entrarComSessao = useCallback(async (sessao: SessaoQuest) => {
    await guardarToken(sessao.access_token);
    setPerfil(sessao.perfil);
    setEstado("logado");
  }, []);

  const sair = useCallback(async () => {
    await limparToken();
    setPerfil(null);
    setEstado("deslogado");
  }, []);

  useEffect(() => {
    configurarApiUmaVez(() => {
      setPerfil(null);
      setEstado("deslogado");
    });

    (async () => {
      // 1) Cartão apontado para a câmera: /entrar?qr=…
      const url = new URL(window.location.href);
      const qr = url.searchParams.get("qr");
      if (qr) {
        window.history.replaceState({}, "", "/");
        try {
          const sessao = await entrarPorQr(qr);
          await entrarComSessao(sessao);
          return;
        } catch {
          /* QR velho/inválido: segue para o fluxo normal */
        }
      }
      // 2) Sessão guardada no aparelho
      if (localStorage.getItem(CHAVE_TOKEN)) {
        try {
          setPerfil(await meuPerfil());
          setEstado("logado");
          return;
        } catch {
          await limparToken();
        }
      }
      setEstado("deslogado");
    })();
  }, [entrarComSessao]);

  const valor = useMemo(
    () => ({ estado, perfil, entrarComSessao, atualizarPerfil: setPerfil, sair }),
    [estado, perfil, entrarComSessao, sair],
  );

  return <Contexto.Provider value={valor}>{children}</Contexto.Provider>;
}

export function useSessao(): ContextoSessao {
  const contexto = useContext(Contexto);
  if (!contexto) throw new Error("useSessao fora do SessaoProvider");
  return contexto;
}
