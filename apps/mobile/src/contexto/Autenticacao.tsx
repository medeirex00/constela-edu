/** Sessão do app: login, escola ativa, registro de push e logout. */
import {
  api,
  guardarToken,
  limparToken,
  loginRequest,
  obterToken,
  type Escola,
  type Usuario,
} from "@sgpe/core";
import AsyncStorage from "@react-native-async-storage/async-storage";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";

import { aoExpirarSessao } from "../api";
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
const CHAVE_ESCOLA = "sgpe_escola";

export function ProvedorAutenticacao({ children }: { children: ReactNode }) {
  const [usuario, setUsuario] = useState<Usuario | null>(null);
  const [escolas, setEscolas] = useState<Escola[]>([]);
  const [escolaId, setEscolaId] = useState<number | null>(null);
  const [carregando, setCarregando] = useState(true);
  const [tokenPush, setTokenPush] = useState<string | null>(null);

  const carregarSessao = useCallback(async () => {
    const [eu, lista] = await Promise.all([
      api<Usuario>("/auth/me"),
      api<Escola[]>("/escolas"),
    ]);
    setUsuario(eu);
    setEscolas(lista);
    const salvo = Number(await AsyncStorage.getItem(CHAVE_ESCOLA));
    const valido = lista.some((escola) => escola.id === salvo);
    const escolhido = valido ? salvo : lista[0]?.id ?? null;
    setEscolaId(escolhido);
    if (escolhido !== null) {
      await AsyncStorage.setItem(CHAVE_ESCOLA, String(escolhido));
      registrarParaPush(escolhido).then(setTokenPush);
    }
  }, []);

  useEffect(() => {
    aoExpirarSessao(() => {
      setUsuario(null);
      setEscolaId(null);
    });
    (async () => {
      try {
        if (await obterToken()) await carregarSessao();
      } catch {
        await limparToken();
      } finally {
        setCarregando(false);
      }
    })();
  }, [carregarSessao]);

  const entrar = useCallback(
    async (email: string, senha: string) => {
      const resposta = await loginRequest(email, senha);
      await guardarToken(resposta.access_token);
      await carregarSessao();
    },
    [carregarSessao],
  );

  const sair = useCallback(async () => {
    if (escolaId !== null) await removerRegistroPush(escolaId, tokenPush);
    await limparToken();
    setUsuario(null);
    setEscolaId(null);
    setTokenPush(null);
  }, [escolaId, tokenPush]);

  const selecionarEscola = useCallback((id: number) => {
    setEscolaId(id);
    AsyncStorage.setItem(CHAVE_ESCOLA, String(id));
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
