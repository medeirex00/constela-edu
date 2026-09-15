import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";

import type { Periodo } from "../components/SeletorPeriodo";
import { ApiError, api, guardarToken, limparToken, loginRequest, obterToken } from "../lib/api";
import { TURNO_TODOS } from "../lib/turnos";
import type { Escola, Usuario } from "../lib/types";

type Tema = "claro" | "escuro";

// Período TEMPORAL global (intervalo de datas). É um contexto único para que a
// escolha do usuário ("01/08 → 20/08", "Este mês", "Ano letivo") ACOMPANHE a
// navegação entre Ranking Geral, Leitura, Matemática, Evolução e Premiações —
// antes cada página tinha seu próprio useState e o filtro "resetava" ao trocar
// de aba (a aba é remontada pela URL `?ver=`). NÃO confundir com TURNO (manhã/
// tarde/noite), que é OUTRO eixo, com a própria chave de persistência abaixo:
// trocar o período não mexe no turno, e vice-versa.
const CHAVE_PERIODO = "sgpe_periodo";
const PERIODO_PADRAO: Periodo = { preset: "ano_letivo" };

function periodoInicial(): Periodo {
  try {
    const salvo = localStorage.getItem(CHAVE_PERIODO);
    if (salvo) {
      const p = JSON.parse(salvo) as Periodo;
      if (p && typeof p.preset === "string") return p;
    }
  } catch {
    // localStorage indisponível/corrompido → cai no padrão
  }
  return PERIODO_PADRAO;
}

// TURNO global (manhã/tarde/noite/integral). Mesma ideia do período: a escolha
// acompanha o usuário entre Ranking Geral, Leitura, Matemática, Evolução e
// Premiações e sobrevive ao reload. Valores (ver lib/turnos.ts): "todos" (não
// filtra), "" (só turmas SEM turno) ou o código do turno. Chave SEPARADA da do
// período — os dois eixos são independentes.
const CHAVE_TURNO = "sgpe_turno";
const TURNO_PADRAO = TURNO_TODOS;

function turnoInicial(): string {
  try {
    const salvo = localStorage.getItem(CHAVE_TURNO);
    // "" é um valor válido ("Sem turno"): só a AUSÊNCIA da chave cai no padrão.
    if (salvo !== null) return salvo;
  } catch {
    // localStorage indisponível → padrão
  }
  return TURNO_PADRAO;
}

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
  // `null` = contexto de REDE INTEIRA ("Toda a Rede Municipal"), usado pela
  // Secretaria: o Dashboard mostra o consolidado da rede em vez de uma escola.
  selecionarEscola: (id: number | null) => void;
  alternarTema: () => void;
  recarregarEscolas: () => Promise<void>;
  // Período TEMPORAL global (ver nota acima) — lido por todas as telas com
  // filtro de data; persiste ao navegar e ao recarregar (localStorage).
  periodo: Periodo;
  definirPeriodo: (p: Periodo) => void;
  // TURNO global (ver nota acima): "todos" | "" (sem turno) | código do turno.
  // Persiste ao navegar e ao recarregar (localStorage, chave própria).
  turno: string;
  definirTurno: (t: string) => void;
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
  const [periodo, setPeriodo] = useState<Periodo>(periodoInicial);
  const [turno, setTurno] = useState<string>(turnoInicial);
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
    // A Secretaria (rede vinculada, não-global) ENTRA no contexto "Toda a Rede
    // Municipal" (escolaId = null): o Dashboard abre no consolidado da rede, e
    // ela escolhe uma escola pelo seletor do topo. Os demais perfis mantêm a
    // escola salva (ou a primeira da lista) como sempre.
    const ehSecretaria = eu.rede_id != null && !eu.is_global;
    setEscolaId((anterior) => {
      if (ehSecretaria) return null;
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

  const selecionarEscola = useCallback((id: number | null) => {
    // Ao trocar a escola, todo o sistema passa a exibir os dados dela (PRD §20).
    // `null` = "Toda a Rede Municipal": limpa a escola salva para não reabrir
    // numa escola específica.
    setEscolaId(id);
    if (id === null) localStorage.removeItem("sgpe_escola");
    else localStorage.setItem("sgpe_escola", String(id));
  }, []);

  const alternarTema = useCallback(() => {
    setTema((atual) => (atual === "claro" ? "escuro" : "claro"));
  }, []);

  const definirPeriodo = useCallback((p: Periodo) => {
    setPeriodo(p);
    try {
      localStorage.setItem(CHAVE_PERIODO, JSON.stringify(p));
    } catch {
      // sem localStorage: mantém só em memória (segue valendo na navegação)
    }
  }, []);

  const definirTurno = useCallback((t: string) => {
    setTurno(t);
    try {
      localStorage.setItem(CHAVE_TURNO, t);
    } catch {
      // sem localStorage: mantém só em memória (segue valendo na navegação)
    }
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
        periodo,
        definirPeriodo,
        turno,
        definirTurno,
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
