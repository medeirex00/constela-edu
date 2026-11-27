import type { Usuario } from "../lib/types";

export const ROTA_DEMO_CARAGUA = "/rede/demonstracao-caragua";

/** O servidor autoriza a consulta. Aqui a mesma regra mantém a entrada fora dos outros perfis. */
export function podeVerDemoCaragua(usuario: Usuario | null): boolean {
  return usuario != null && !usuario.is_global && usuario.rede_id != null && usuario.escola_id == null
    && usuario.username?.toLowerCase().trim().replace(/^@+/, "") === "ifsp2026sec";
}
