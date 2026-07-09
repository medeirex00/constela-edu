/**
 * Sessão do astronauta — decisão de produto (09/07/2026): a conta NÃO fica
 * salva no aparelho. O token vive só em MEMÓRIA:
 *
 *  - ao Sair (ou recarregar/fechar), a sessão some e a criança entra de novo
 *    pelo código — nada de "guardar o usuário";
 *  - trocar de conta é sempre do zero: nenhuma mudança de uma conta (cor,
 *    constelação, apelido) vaza para a próxima;
 *  - QR (/entrar?qr=…) autentica e passa pelo "É você?" (cartões trocam de
 *    mão); a URL é limpa do histórico.
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
import { entrarPorQr } from "@constela/quest-core";
import type { PerfilQuest, SessaoQuest } from "@constela/quest-core";

type Estado = "carregando" | "deslogado" | "confirmar" | "logado";

interface ContextoSessao {
  estado: Estado;
  perfil: PerfilQuest | null;
  /** true logo após um login com primeira_vez (dispara a cerimônia). */
  primeiraVez: boolean;
  entrarComSessao(sessao: SessaoQuest): Promise<void>;
  confirmarIdentidade(): void;
  negarIdentidade(): Promise<void>;
  atualizarPerfil(perfil: PerfilQuest): void;
  sair(): Promise<void>;
}

const Contexto = createContext<ContextoSessao | null>(null);

// Token SÓ em memória — some ao recarregar/fechar (a conta nunca fica salva).
let tokenEmMemoria: string | null = null;
let apiConfigurada = false;

function configurarApiUmaVez(aoExpirar: () => void) {
  if (apiConfigurada) return;
  apiConfigurada = true;
  configurarApi({
    base: "/api/v1",
    armazenamento: {
      obter: () => tokenEmMemoria,
      guardar: (token) => { tokenEmMemoria = token; },
      remover: () => { tokenEmMemoria = null; },
    },
    aoExpirarSessao: aoExpirar,
  });
}

export function SessaoProvider({ children }: { children: ReactNode }) {
  const [estado, setEstado] = useState<Estado>("carregando");
  const [perfil, setPerfil] = useState<PerfilQuest | null>(null);
  const [primeiraVez, setPrimeiraVez] = useState(false);

  const entrarComSessao = useCallback(async (sessao: SessaoQuest) => {
    await guardarToken(sessao.access_token);
    setPerfil(sessao.perfil);
    setPrimeiraVez(sessao.primeira_vez);
    setEstado("logado");           // a criança já confirmou "Sou eu!" na entrada
  }, []);

  const sair = useCallback(async () => {
    await limparToken();
    setPerfil(null);
    setPrimeiraVez(false);
    setEstado("deslogado");
  }, []);

  const confirmarIdentidade = useCallback(() => setEstado("logado"), []);
  const negarIdentidade = useCallback(async () => { await sair(); }, [sair]);

  useEffect(() => {
    configurarApiUmaVez(() => {
      setPerfil(null);
      setEstado("deslogado");
    });

    (async () => {
      // Único caminho automático: cartão apontado para a câmera (/entrar?qr=…)
      const url = new URL(window.location.href);
      const qr = url.searchParams.get("qr");
      if (qr) {
        window.history.replaceState({}, "", "/");
        try {
          const sessao = await entrarPorQr(qr);
          await guardarToken(sessao.access_token);
          setPerfil(sessao.perfil);
          setPrimeiraVez(sessao.primeira_vez);
          setEstado("confirmar");  // cartões trocam de mão: "É você?"
          return;
        } catch {
          /* QR velho/inválido/sem rede: cai no login normal */
        }
      }
      setEstado("deslogado");
    })();
  }, []);

  const atualizarPerfil = useCallback((novo: PerfilQuest) => setPerfil(novo), []);

  const valor = useMemo(
    () => ({
      estado, perfil, primeiraVez,
      entrarComSessao, confirmarIdentidade, negarIdentidade,
      atualizarPerfil, sair,
    }),
    [estado, perfil, primeiraVez, entrarComSessao, confirmarIdentidade,
     negarIdentidade, atualizarPerfil, sair],
  );

  return <Contexto.Provider value={valor}>{children}</Contexto.Provider>;
}

export function useSessao(): ContextoSessao {
  const contexto = useContext(Contexto);
  if (!contexto) throw new Error("useSessao fora do SessaoProvider");
  return contexto;
}
