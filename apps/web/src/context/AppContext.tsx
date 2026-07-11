import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";

import { ApiError, api, guardarToken, limparToken, loginRequest, obterToken } from "../lib/api";
import type { Escola, Usuario } from "../lib/types";

type Tema = "claro" | "escuro";

interface AppContexto {
  usuario: Usuario | null;
  escolas: Escola[];
  escolaId: number | null;
  escolaAtual: Escola | null;
  tema: Tema;
  carregando: boolean;
  // Falha TRANSITÓRIA ao abrir a sessão (rede/5xx), com o token preservado —
  // a UI mostra "reconectar" em vez de deslogar.
  falhaSessao: boolean;
  tentarReconectar: () => void;
  entrar: (email: string, senha: string) => Promise<void>;
  sair: () => void;
  selecionarEscola: (id: number) => void;
  alternarTema: () => void;
  recarregarEscolas: () => Promise<void>;
}

const Contexto = createContext<AppContexto | null>(null);

function temaInicial(): Tema {
  const salvo = localStorage.getItem("sgpe_tema");
  if (salvo === "claro" || salvo === "escuro") return salvo;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "escuro" : "claro";
}

export function AppProvider({ children }: { children: ReactNode }) {
  const [usuario, setUsuario] = useState<Usuario | null>(null);
  const [escolas, setEscolas] = useState<Escola[]>([]);
  const [escolaId, setEscolaId] = useState<number | null>(() => {
    const salvo = localStorage.getItem("sgpe_escola");
    return salvo ? Number(salvo) : null;
  });
  const [tema, setTema] = useState<Tema>(temaInicial);
  const [carregando, setCarregando] = useState(true);
  const [falhaSessao, setFalhaSessao] = useState(false);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", tema === "escuro");
    localStorage.setItem("sgpe_tema", tema);
  }, [tema]);

  const carregarSessao = useCallback(async () => {
    const [eu, lista] = await Promise.all([
      api<Usuario>("/auth/me"),
      api<Escola[]>("/escolas"),
    ]);
    setUsuario(eu);
    setEscolas(lista);
    setEscolaId((anterior) => {
      const valido = anterior !== null && lista.some((escola) => escola.id === anterior);
      const escolhido = valido ? anterior : lista[0]?.id ?? null;
      if (escolhido !== null) localStorage.setItem("sgpe_escola", String(escolhido));
      return escolhido;
    });
  }, []);

  // Abre a sessão a partir do token guardado. Distingue sessão INVÁLIDA
  // (401 → desloga) de falha TRANSITÓRIA (rede/5xx/timeout — cold start do
  // backend, deploy, blip): o transitório é retentado com backoff e, se
  // persistir, MANTÉM o token e sinaliza `falhaSessao` (a UI oferece
  // reconectar). Antes, qualquer erro apagava o token e forçava novo login.
  const iniciarSessao = useCallback(async () => {
    setFalhaSessao(false); // limpa antes do early-return: "Tentar de novo" sem
    if (!obterToken()) {   // token deve cair em /login, não travar em Reconectar
      setCarregando(false);
      return;
    }
    setCarregando(true);
    const atrasosMs = [500, 1500, 3000];
    for (let tentativa = 0; ; tentativa++) {
      try {
        await carregarSessao();
        setFalhaSessao(false);
        setCarregando(false);
        return;
      } catch (erro) {
        if (erro instanceof ApiError && erro.status === 401) {
          limparToken(); // sessão realmente inválida (o core já redireciona)
          setCarregando(false);
          return;
        }
        if (tentativa >= atrasosMs.length) {
          setFalhaSessao(true); // transitório persistente: token preservado
          setCarregando(false);
          return;
        }
        await new Promise((resolver) => setTimeout(resolver, atrasosMs[tentativa]));
      }
    }
  }, [carregarSessao]);

  useEffect(() => {
    void iniciarSessao();
  }, [iniciarSessao]);

  const entrar = useCallback(
    async (email: string, senha: string) => {
      const resposta = await loginRequest(email, senha);
      guardarToken(resposta.access_token);
      await carregarSessao();
    },
    [carregarSessao],
  );

  const sair = useCallback(() => {
    limparToken();
    setUsuario(null);
    window.location.href = "/login";
  }, []);

  const selecionarEscola = useCallback((id: number) => {
    // Ao trocar a escola, todo o sistema passa a exibir os dados dela (PRD §20)
    setEscolaId(id);
    localStorage.setItem("sgpe_escola", String(id));
  }, []);

  const alternarTema = useCallback(() => {
    setTema((atual) => (atual === "claro" ? "escuro" : "claro"));
  }, []);

  const recarregarEscolas = useCallback(async () => {
    setEscolas(await api<Escola[]>("/escolas"));
  }, []);

  const escolaAtual = escolas.find((escola) => escola.id === escolaId) ?? null;

  return (
    <Contexto.Provider
      value={{
        usuario,
        escolas,
        escolaId,
        escolaAtual,
        tema,
        carregando,
        falhaSessao,
        tentarReconectar: iniciarSessao,
        entrar,
        sair,
        selecionarEscola,
        alternarTema,
        recarregarEscolas,
      }}
    >
      {children}
    </Contexto.Provider>
  );
}

export function useApp(): AppContexto {
  const contexto = useContext(Contexto);
  if (!contexto) throw new Error("useApp deve ser usado dentro de AppProvider");
  return contexto;
}
