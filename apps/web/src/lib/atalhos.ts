/**
 * Atalhos de teclado globais (Web e Desktop):
 *   Ctrl/Cmd+K  → foca a pesquisa global
 *   Alt+1..9    → navega entre as telas principais
 *   Alt+0       → Configurações Gerais (só administrador — ver abaixo)
 */
import { useEffect } from "react";
import { useNavigate } from "react-router-dom";

import { usePerfil } from "../hooks/usePerfil";

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

/** Destinos do teclado para o perfil. Configurações Gerais é só do
 *  administrador (a mesma condição da rota, `RotaAdmin` em App.tsx): para os
 *  demais, Alt+0 não navega e a tecla fica livre para o navegador. */
export function destinosDoTeclado(podeConfigurar: boolean): Record<string, string> {
  if (podeConfigurar) return DESTINOS;
  return Object.fromEntries(Object.entries(DESTINOS).filter(([tecla]) => tecla !== "0"));
}

export function useAtalhosGlobais(): void {
  const navegar = useNavigate();
  const { admin, secretaria } = usePerfil();
  const podeConfigurar = admin && !secretaria;

  useEffect(() => {
    const destinos = destinosDoTeclado(podeConfigurar);
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
  }, [navegar, podeConfigurar]);
}
