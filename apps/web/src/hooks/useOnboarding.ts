import { useApp } from "../context/AppContext";
import { useApi } from "./useApi";

/** GET /escolas/{id}/sync/onboarding — só o sinal do "Comece aqui". */
interface EscolaOnboarding {
  lista_piloto_importada: boolean;
}

export interface EstadoOnboarding {
  /** O usuário pode fazer a configuração inicial (admin/coordenador, não Secretaria)? */
  podeConfigurar: boolean;
  /** A escola ainda precisa da configuração inicial ("Comece aqui")? */
  precisaConfigurar: boolean;
  /** Ainda descobrindo o estado (não decidir a tela enquanto verdadeiro). */
  carregando: boolean;
}

/**
 * Estado da configuração inicial da escola selecionada.
 *
 * A escola é considerada CONFIGURADA quando já tem a Lista Piloto importada
 * (turmas/alunos). Esse sinal vive na ESCOLA — não no navegador —, então a
 * persistência é automática: uma vez configurada, sair e entrar de novo NÃO
 * reabre o fluxo de "Comece aqui".
 *
 * Só vale para quem opera a escola (admin/coordenador). A Secretaria acompanha
 * a rede, mas não configura escolas, e o professor entra numa escola que o
 * coordenador já preparou — para ambos, `precisaConfigurar` é sempre falso.
 *
 * Lê o endpoint LEVE `/sync/onboarding` (uma consulta), não o `/sync/status`
 * inteiro — o mais caro da API, que a barra lateral pagava a cada montagem só
 * por este booleano. O `/sync/status` fica com a tela de Integrações (e o
 * "Comece aqui", que usa os demais campos).
 */
export function useOnboarding(): EstadoOnboarding {
  const { usuario, escolaId } = useApp();
  const gestor = Boolean(usuario?.is_global) ||
    ["admin", "coordenador"].includes(usuario?.cargo ?? "");
  const secretaria = !usuario?.is_global && usuario?.rede_id != null;
  const podeConfigurar = gestor && !secretaria;

  const { dados, carregando } = useApi<EscolaOnboarding>(
    podeConfigurar && escolaId ? `/escolas/${escolaId}/sync/onboarding` : null,
  );

  const conhecido = dados != null;
  return {
    podeConfigurar,
    precisaConfigurar: podeConfigurar && conhecido && !dados.lista_piloto_importada,
    carregando: podeConfigurar && Boolean(escolaId) && !conhecido && carregando,
  };
}
