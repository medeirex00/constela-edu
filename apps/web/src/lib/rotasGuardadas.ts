/**
 * Espelho das GUARDAS DE ROTA de `App.tsx` (RotaGestao, RotaEscolaOp,
 * RotaAdmin, RotaRede, RotaGlobal, RotaModulo), para quem precisa saber ANTES
 * de navegar se o perfil abre a tela — hoje o sino de notificações: um aviso
 * que aponta para uma tela barrada fica sem clique, em vez de levar a um
 * redirecionamento mudo para o Dashboard.
 *
 * A tabela repete, rota por rota, o que `App.tsx` declara (mesmas guardas,
 * mesma ordem de aninhamento); `test/LayoutNotificacoesRotas.test.tsx` lê o `App.tsx` e falha
 * se as duas divergirem. Rota fora da tabela não tem guarda (abre para todos).
 */

/** O mesmo recorte de `usePerfil()` que as guardas de `App.tsx` consultam. */
export interface PerfilDaRota {
  global: boolean;
  secretaria: boolean;
  rede: boolean;
  gestor: boolean;
  admin: boolean;
}

export type Guarda = "RotaGestao" | "RotaEscolaOp" | "RotaAdmin" | "RotaRede" | "RotaGlobal";

export interface RotaGuardada {
  caminho: string;
  /** Guardas de perfil, de fora para dentro (todas precisam passar). */
  guardas: Guarda[];
  /** `RotaModulo`: o módulo precisa estar contratado. */
  modulo?: string;
}

export const ROTAS_GUARDADAS: RotaGuardada[] = [
  { caminho: "/rede", guardas: ["RotaRede"] },
  { caminho: "/rede/gerenciar", guardas: ["RotaGlobal"] },
  { caminho: "/rede/avaliacoes", guardas: ["RotaRede"] },
  { caminho: "/rede/ranking", guardas: ["RotaRede"] },
  { caminho: "/comparador", guardas: ["RotaGestao"] },
  { caminho: "/escola", guardas: ["RotaGestao"] },
  { caminho: "/turmas", guardas: ["RotaGestao"] },
  { caminho: "/turmas/:id", guardas: ["RotaGestao"] },
  { caminho: "/professores", guardas: ["RotaGestao"] },
  { caminho: "/metricas", guardas: ["RotaGestao"] },
  { caminho: "/configuracoes", guardas: ["RotaGestao", "RotaAdmin"] },
  { caminho: "/configuracoes/conquistas", guardas: ["RotaGestao"] },
  { caminho: "/matific", guardas: ["RotaGestao"], modulo: "matematica" },
  { caminho: "/elefante", guardas: ["RotaGestao"], modulo: "leitura" },
  { caminho: "/livros", guardas: ["RotaGestao"], modulo: "leitura" },
  { caminho: "/comecar", guardas: ["RotaEscolaOp"] },
  { caminho: "/importacoes", guardas: ["RotaEscolaOp"] },
  { caminho: "/sincronizacao", guardas: ["RotaEscolaOp"] },
  { caminho: "/revisoes-identidade", guardas: ["RotaEscolaOp"] },
  { caminho: "/diagnostico-elefante", guardas: ["RotaEscolaOp"], modulo: "leitura" },
  { caminho: "/conquistas", guardas: ["RotaGestao"] },
  { caminho: "/assistente", guardas: ["RotaGestao"] },
  { caminho: "/painel-publico", guardas: ["RotaGestao"] },
  { caminho: "/simulador", guardas: ["RotaGestao"] },
  { caminho: "/escolas", guardas: ["RotaGlobal"] },
  { caminho: "/sessoes", guardas: ["RotaGlobal"] },
];

/** O mesmo teste de cada guarda em `App.tsx`. */
const PASSA: Record<Guarda, (p: PerfilDaRota) => boolean> = {
  RotaGestao: (p) => p.gestor,
  RotaEscolaOp: (p) => p.gestor && !p.secretaria,
  RotaAdmin: (p) => p.admin && !p.secretaria,
  RotaRede: (p) => p.rede,
  RotaGlobal: (p) => p.global,
};

function segmentos(caminho: string): string[] {
  return caminho.split(/[?#]/)[0].split("/").filter(Boolean);
}

function casa(padrao: string, caminho: string): boolean {
  const a = segmentos(padrao);
  const b = segmentos(caminho);
  return a.length === b.length && a.every((s, i) => s.startsWith(":") || s === b[i]);
}

/** O perfil abre esta rota? `false` quando alguma guarda de `App.tsx` o
 *  mandaria de volta ao Dashboard. Rota sem guarda: `true`. */
export function podeAbrirRota(
  rota: string,
  perfil: PerfilDaRota,
  temModulo: (modulo: string) => boolean,
): boolean {
  const guardada = ROTAS_GUARDADAS.find((r) => casa(r.caminho, rota));
  if (!guardada) return true;
  if (!guardada.guardas.every((g) => PASSA[g](perfil))) return false;
  return guardada.modulo ? temModulo(guardada.modulo) : true;
}
