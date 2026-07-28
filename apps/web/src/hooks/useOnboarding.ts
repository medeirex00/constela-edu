import { useApp } from "../context/AppContext";
import { useApi } from "./useApi";

interface EscolaStatus {
  lista_piloto_importada: boolean;
  // demais campos de /sync/status são ignorados aqui
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
 */
export function useOnboarding(): EstadoOnboarding {
  const { usuario, escolaId } = useApp();
  const gestor = Boolean(usuario?.is_global) ||
    ["admin", "coordenador"].includes(usuario?.cargo ?? "");
  const secretaria = !usuario?.is_global && usuario?.rede_id != null;
  const podeConfigurar = gestor && !secretaria;

  const { dados, carregando } = useApi<EscolaStatus>(
    podeConfigurar && escolaId ? `/escolas/${escolaId}/sync/status` : null,
  );

  const conhecido = dados != null;
  return {
    podeConfigurar,
    precisaConfigurar: podeConfigurar && conhecido && !dados.lista_piloto_importada,
    carregando: podeConfigurar && Boolean(escolaId) && !conhecido && carregando,
  };
}
