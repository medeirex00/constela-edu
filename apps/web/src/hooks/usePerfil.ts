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
 * - escolaOnly  → opera UMA escola (professor/coordenador/admin sem rede).
 */
export function usePerfil() {
  const { usuario } = useApp();
  const global = Boolean(usuario?.is_global);
  const secretaria = !global && usuario?.rede_id != null;
  const rede = global || usuario?.rede_id != null;
  const gestor = global || ["admin", "coordenador"].includes(usuario?.cargo ?? "");
  const escolaOnly = !global && usuario?.rede_id == null;
  return { global, secretaria, rede, gestor, escolaOnly, cargo: usuario?.cargo ?? null };
}
