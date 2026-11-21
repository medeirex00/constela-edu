/**
 * Atalhos de teclado globais (Web e Desktop):
 *   Ctrl/Cmd+K  → foca a pesquisa global
 *   Alt+1..9    → navega entre as telas principais
 *   Alt+0       → Configurações Gerais (só administrador — ver abaixo)
 * A Secretaria tem os SEUS: Alt+1..3 são as três áreas do menu dela (DESENHO3 §1); as
 * demais teclas não navegam (levavam a telas de escola sem uso para ela).
 * Tecla cujo destino o perfil não abre (as guardas de App.tsx, `lib/rotasGuardadas`)
 * também não navega: antes o professor apertava Alt+5 (Importações), Alt+6
 * (Conquistas e Mural) ou Alt+8 (Assistente) e voltava, sem aviso, à Visão geral.
 */
import { useEffect } from "react";
import { useNavigate } from "react-router-dom";

import { useModulos } from "../hooks/useModulos";
import { usePerfil } from "../hooks/usePerfil";
import { podeAbrirRota } from "./rotasGuardadas";

const DESTINOS: Record<string, string> = {
  "1": "/",
  "2": "/ranking",
  "3": "/ranking?ver=evolucao",
  "4": "/alunos",
  "5": "/importacoes",
  "6": "/conquistas",
  "7": "/insights",
  "8": "/assistente",
  "9": "/relatorios",
  "0": "/configuracoes",
};

/** Secretaria: Panorama da Rede, Escolas e Avaliações externas — a ordem do menu dela. */
const DESTINOS_DA_SECRETARIA: Record<string, string> = {
  "1": "/",
  "2": "/rede/escolas",
  "3": "/rede/avaliacoes-externas",
};

/** Destinos do teclado para o perfil. Configurações Gerais é só do
 *  administrador (a mesma condição da rota, `RotaAdmin` em App.tsx): para os
 *  demais, Alt+0 não navega e a tecla fica livre para o navegador. A Secretaria
 *  só tem as três áreas dela; as outras teclas ficam livres. `podeAbrir` (as
 *  guardas de rota do perfil) tira as teclas cujo destino o perfil não abre. */
export function destinosDoTeclado(
  podeConfigurar: boolean,
  secretaria = false,
  podeAbrir: (rota: string) => boolean = () => true,
): Record<string, string> {
  const base = secretaria
    ? DESTINOS_DA_SECRETARIA
    : podeConfigurar
      ? DESTINOS
      : Object.fromEntries(Object.entries(DESTINOS).filter(([tecla]) => tecla !== "0"));
  return Object.fromEntries(Object.entries(base).filter(([, rota]) => podeAbrir(rota)));
}

export function useAtalhosGlobais(): void {
  const navegar = useNavigate();
  const { admin, secretaria, global, rede, gestor } = usePerfil();
  const { modulos } = useModulos();
  const podeConfigurar = admin && !secretaria;
  // A lista de módulos vira texto para o efeito não refazer o ouvinte a cada render.
  const chaveModulos = modulos.join(",");

  useEffect(() => {
    const contratados = chaveModulos.split(",");
    const perfil = { admin, secretaria, global, rede, gestor };
    const destinos = destinosDoTeclado(podeConfigurar, secretaria, (rota) =>
      podeAbrirRota(rota, perfil, (modulo) => contratados.includes(modulo)));
    function aoTeclar(evento: KeyboardEvent) {
      if ((evento.ctrlKey || evento.metaKey) && evento.key.toLowerCase() === "k") {
        evento.preventDefault();
        document.getElementById("pesquisa-global")?.focus();
        return;
      }
      if (evento.altKey && destinos[evento.key]) {
        evento.preventDefault();
        navegar(destinos[evento.key]);
      }
    }
    window.addEventListener("keydown", aoTeclar);
    return () => window.removeEventListener("keydown", aoTeclar);
  }, [navegar, podeConfigurar, admin, secretaria, global, rede, gestor, chaveModulos]);
}
