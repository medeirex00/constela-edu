/**
 * Sessão do astronauta — desenhada para tablet COMPARTILHADO de escola e
 * Wi-Fi que cai:
 *
 *  - Boot com sessão guardada NUNCA cola direto no lobby: mostra "É você,
 *    {nome}?" — a segunda criança do turno não herda a conta da primeira.
 *  - Erro de REDE nunca desloga: só 401/403 limpa o token; sem rede, o
 *    perfil vem do cache local e revalida quando a conexão voltar.
 *  - O aparelho lembra os astronautas que já entraram ("Quem vai jogar?").
 *  - QR (/entrar?qr=…) autentica e também cai no "É você?" (cartões trocados
 *    não logam a criança errada sem aviso); a URL é limpa do histórico.
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
import {
  ehErroDeAutenticacao,
  entrarPorQr,
  meuPerfil,
} from "@constela/quest-core";
import type {
  AstronautaConhecido,
  PerfilQuest,
  SessaoQuest,
} from "@constela/quest-core";

const CHAVE_TOKEN = "quest_token";
const CHAVE_PERFIL = "quest_perfil_cache";
const CHAVE_ASTRONAUTAS = "quest_astronautas";
const MAX_ASTRONAUTAS = 40;

type Estado = "carregando" | "deslogado" | "confirmar" | "logado";

interface ContextoSessao {
  estado: Estado;
  perfil: PerfilQuest | null;
  /** true logo após um login com primeira_vez (dispara a cerimônia). */
  primeiraVez: boolean;
  astronautas: AstronautaConhecido[];
  entrarComSessao(sessao: SessaoQuest): Promise<void>;
  confirmarIdentidade(): void;
  negarIdentidade(): Promise<void>;
  atualizarPerfil(perfil: PerfilQuest): void;
  sair(): Promise<void>;
}

const Contexto = createContext<ContextoSessao | null>(null);

// ---------------------------------------------------------------------------
// Persistência local (cache do perfil + astronautas do aparelho)
// ---------------------------------------------------------------------------

function lerJson<T>(chave: string): T | null {
  try {
    const bruto = localStorage.getItem(chave);
    return bruto ? (JSON.parse(bruto) as T) : null;
  } catch {
    return null;
  }
}

function gravarPerfilCache(perfil: PerfilQuest) {
  localStorage.setItem(CHAVE_PERFIL, JSON.stringify(perfil));
}

export function obterAstronautas(): AstronautaConhecido[] {
  return lerJson<AstronautaConhecido[]>(CHAVE_ASTRONAUTAS) ?? [];
}

function registrarAstronauta(perfil: PerfilQuest) {
  if (!perfil.codigo_login) return;
  const atual: AstronautaConhecido = {
    codigo: perfil.codigo_login,
    nome: perfil.nome,
    cor: (perfil.avatar.cor as string) ?? "#FF4D9D",
  };
  const lista = obterAstronautas().filter((a) => a.codigo !== atual.codigo);
  lista.unshift(atual);
  localStorage.setItem(CHAVE_ASTRONAUTAS,
    JSON.stringify(lista.slice(0, MAX_ASTRONAUTAS)));
}

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
  const [primeiraVez, setPrimeiraVez] = useState(false);
  const [astronautas, setAstronautas] = useState<AstronautaConhecido[]>(
    obterAstronautas,
  );

  const atualizarPerfil = useCallback((novo: PerfilQuest) => {
    setPerfil(novo);
    gravarPerfilCache(novo);
    registrarAstronauta(novo);
    setAstronautas(obterAstronautas());
  }, []);

  const entrarComSessao = useCallback(async (sessao: SessaoQuest) => {
    await guardarToken(sessao.access_token);
    atualizarPerfil(sessao.perfil);
    setPrimeiraVez(sessao.primeira_vez);
    // Quem digitou o código já confirmou "Sou eu!" na entrada
    setEstado("logado");
  }, [atualizarPerfil]);

  const sair = useCallback(async () => {
    await limparToken();
    localStorage.removeItem(CHAVE_PERFIL);
    setPerfil(null);
    setPrimeiraVez(false);
    setEstado("deslogado");
  }, []);

  const confirmarIdentidade = useCallback(() => setEstado("logado"), []);
  const negarIdentidade = useCallback(async () => { await sair(); }, [sair]);

  useEffect(() => {
    configurarApiUmaVez(() => {
      // Disparado pelo cliente HTTP em QUALQUER 401 autenticado
      localStorage.removeItem(CHAVE_PERFIL);
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
          await guardarToken(sessao.access_token);
          atualizarPerfil(sessao.perfil);
          setPrimeiraVez(sessao.primeira_vez);
          setEstado("confirmar"); // cartões trocam de mão: "É você?"
          return;
        } catch {
          /* QR velho/inválido/sem rede: segue para o fluxo normal */
        }
      }

      // 2) Sessão guardada no aparelho → SEMPRE confirmar identidade
      if (localStorage.getItem(CHAVE_TOKEN)) {
        try {
          atualizarPerfil(await meuPerfil());
          setEstado("confirmar");
          return;
        } catch (erro) {
          if (ehErroDeAutenticacao(erro)) {
            await limparToken();
            localStorage.removeItem(CHAVE_PERFIL);
          } else {
            // Wi-Fi caiu ≠ sessão inválida: usa o cache e segue o baile
            const cacheado = lerJson<PerfilQuest>(CHAVE_PERFIL);
            if (cacheado) {
              setPerfil(cacheado);
              setEstado("confirmar");
              return;
            }
            // Sem cache: mantém o token para a próxima tentativa
          }
        }
      }
      setEstado("deslogado");
    })();
  }, [atualizarPerfil]);

  const valor = useMemo(
    () => ({
      estado, perfil, primeiraVez, astronautas,
      entrarComSessao, confirmarIdentidade, negarIdentidade,
      atualizarPerfil, sair,
    }),
    [estado, perfil, primeiraVez, astronautas,
     entrarComSessao, confirmarIdentidade, negarIdentidade,
     atualizarPerfil, sair],
  );

  return <Contexto.Provider value={valor}>{children}</Contexto.Provider>;
}

export function useSessao(): ContextoSessao {
  const contexto = useContext(Contexto);
  if (!contexto) throw new Error("useSessao fora do SessaoProvider");
  return contexto;
}
