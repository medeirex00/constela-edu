/**
 * Atalhos de teclado globais (Web e Desktop):
 *   Ctrl/Cmd+K  → foca a pesquisa global
 *   Alt+1..9    → navega entre as telas principais
 *   Alt+0       → Configurações
 */
import { useEffect } from "react";
import { useNavigate } from "react-router-dom";

const DESTINOS: Record<string, string> = {
  "1": "/",
  "2": "/ranking",
  "3": "/evolucao",
  "4": "/alunos",
  "5": "/importacoes",
  "6": "/conquistas",
  "7": "/insights",
  "8": "/assistente",
  "9": "/relatorios",
  "0": "/configuracoes",
};

export function useAtalhosGlobais(): void {
  const navegar = useNavigate();

  useEffect(() => {
    function aoTeclar(evento: KeyboardEvent) {
      if ((evento.ctrlKey || evento.metaKey) && evento.key.toLowerCase() === "k") {
        evento.preventDefault();
        document.getElementById("pesquisa-global")?.focus();
        return;
      }
      if (evento.altKey && DESTINOS[evento.key]) {
        evento.preventDefault();
        navegar(DESTINOS[evento.key]);
      }
    }
    window.addEventListener("keydown", aoTeclar);
    return () => window.removeEventListener("keydown", aoTeclar);
  }, [navegar]);
}
