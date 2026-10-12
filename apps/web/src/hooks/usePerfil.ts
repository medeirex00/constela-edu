import { useApp } from "../context/AppContext";

/**
 * Deriva o PERFIL do usuário a partir de `is_global` / `rede_id` / `cargo` —
 * a FONTE ÚNICA de decisão de papel, usada pelas guardas de rota, pelo menu e
 * pelo Dashboard adaptável. Antes, essa mesma regra estava reescrita em vários
 * lugares (App/Layout/Dashboard); centralizar evita divergência.
 *
 * - global      → Admin Global (acesso irrestrito).
 * - secretaria  → SEDUC: conta com rede vinculada, NÃO global (agrega a rede).
 * - rede        → alcança o painel /rede (SEDUC ou Admin Global).
 * - gestor      → admin/coordenador (ou global): vê telas de gestão.
 * - admin       → administrador (global OU cargo "admin"): o MESMO teste que a
 *                 tela de Configurações Gerais usa e que o backend aplica em
 *                 `exigir_papeis("admin")` (o global sempre passa). A
 *                 coordenação NÃO é admin: não abre Configurações Gerais.
 * - escolaOnly  → opera UMA escola (professor/coordenador/admin sem rede).
 */
export function usePerfil() {
  const { usuario } = useApp();
  const global = Boolean(usuario?.is_global);
  const secretaria = !global && usuario?.rede_id != null;
  const rede = global || usuario?.rede_id != null;
  const gestor = global || ["admin", "coordenador"].includes(usuario?.cargo ?? "");
  const admin = global || usuario?.cargo === "admin";
  const escolaOnly = !global && usuario?.rede_id == null;
  return { global, secretaria, rede, gestor, admin, escolaOnly, cargo: usuario?.cargo ?? null };
}

/** Destino do clique no nome de um aluno nas telas de evolução: a gestão abre
 * a evolução detalhada; o professor abre o perfil (a evolução detalhada é dado
 * de gestão — o servidor responde 403 ao professor). */
export function destinoEvolucaoDoAluno(alunoId: number, gestor: boolean): string {
  return gestor ? `/alunos/${alunoId}/evolucao` : `/alunos/${alunoId}`;
}
