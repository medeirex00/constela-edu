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
  useRef,
  useState,
  type ReactNode,
} from "react";

import { aoExpirarSessao } from "../api";
import { esquecerChave } from "../armazenamento/cifra";
import { lerSessao, limparSessao, salvarSessao, type SessaoSalva } from "../armazenamento/sessao";
import { clienteQuery, persistidor } from "../cliente-query";
import {
  descadastrarPendente,
  ligarDescadastroAReconexao,
  registrarParaPush,
  removerRegistroPush,
} from "../notificacoes";

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
  // Muda a cada sessão encerrada: uma resposta da rede que chega DEPOIS do "Sair"
  // (um refresh do boot que estava pendurado) não pode pôr a sessão de volta.
  const geracao = useRef(0);
  const limpezaLocal = useRef<Promise<void> | null>(null);

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
    const desta = geracao.current;
    const [eu, lista] = await Promise.all([
      api<Usuario>("/auth/me"),
      api<Escola[]>("/escolas"),
    ]);
    if (desta !== geracao.current) return; // a sessão acabou enquanto esperava a rede
    const valido = preferidaId !== null && lista.some((escola) => escola.id === preferidaId);
    const escolhido = valido ? preferidaId : lista[0]?.id ?? null;
    setUsuario(eu);
    setEscolas(lista);
    setEscolaId(escolhido);
    // O token registrado fica guardado no aparelho (notificacoes.ts): o "Sair" o
    // encontra mesmo numa abertura sem rede, quando este registro não roda.
    if (escolhido !== null) void registrarParaPush(escolhido);
  }, []);

  // Encerra a sessão LOCAL: estado, sessão salva, cache das telas e chave de
  // cifra (rotacionada para o cache antigo virar ilegível num aparelho partilhado).
  const encerrarLocal = useCallback(() => {
    if (limpezaLocal.current) return limpezaLocal.current;
    geracao.current += 1;
    // Marca o descadastro antes de exibir o formulário da conta seguinte.
    const descadastro = removerRegistroPush();
    setUsuario(null);
    setEscolas([]);
    setEscolaId(null);
    clienteQuery.clear();
    const limpeza = (async () => {
      await Promise.allSettled([limparSessao(), persistidor.removeClient()]);
      await esquecerChave();
      await descadastro;
    })().finally(() => { limpezaLocal.current = null; });
    limpezaLocal.current = limpeza;
    return limpeza;
  }, []);

  useEffect(() => {
    // Token inválido/expirado (401 no cliente HTTP): aí sim desloga de fato — e o
    // aparelho sai do push, como no "Sair".
    aoExpirarSessao(() => {
      void encerrarLocal().catch(() => undefined);
    });

    // Descadastro do push que ficou pendente (saída sem rede): tenta agora e a
    // cada volta da rede.
    void descadastrarPendente();
    const desligarReconexao = ligarDescadastroAReconexao();

    (async () => {
      try {
        if (!(await obterToken())) return; // sem token → tela de login
        const salva = await lerSessao();
        if (salva) {
          // Abre na hora, com o cache: o refresh abaixo segue em segundo plano. A
          // rede pode não responder por minutos (o fetch do React Native não tem
          // tempo-limite) e a tela não espera por ela.
          aplicarSessao(salva);
          setCarregando(false);
        }
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
    return desligarReconexao;
  }, [aplicarSessao, atualizarSessao, encerrarLocal]);

  const entrar = useCallback(
    async (email: string, senha: string) => {
      await limpezaLocal.current;
      const resposta = await loginRequest(email, senha);
      await guardarToken(resposta.access_token);
      await atualizarSessao(null);
    },
    [atualizarSessao],
  );

  // Primeiro a sessão LOCAL (token, dados salvos, tela), que não depende da rede;
  // depois o push: o descadastro fica marcado no aparelho e vai ao servidor em
  // segundo plano (notificacoes.ts) — uma rede pendurada não segura a saída.
  const sair = useCallback(async () => {
    await limparToken();
    await encerrarLocal();
  }, [encerrarLocal]);

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
