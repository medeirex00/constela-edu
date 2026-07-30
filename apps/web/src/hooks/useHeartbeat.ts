/**
 * Batimento de presença: enquanto o app está aberto, avisa o servidor que o
 * usuário está online (o Monitor de Sessões Ativas, exclusivo do Admin Global,
 * usa isso). Leve de propósito — uma batida a cada 30 s e uma ao voltar o foco
 * à aba; nunca bate com a aba oculta e engole qualquer erro (presença é
 * best-effort, jamais atrapalha a navegação).
 */
import { useEffect } from "react";

import { api } from "../lib/api";

const INTERVALO_MS = 30_000;

export function useHeartbeat(): void {
  useEffect(() => {
    const bater = () => {
      if (document.visibilityState === "hidden") return;
      // Fire-and-forget: um 401 já redireciona para /login pelo próprio cliente;
      // qualquer outra falha é irrelevante para a presença.
      api("/presenca/heartbeat", { method: "POST" }).catch(() => {});
    };

    bater(); // marca presença imediatamente ao abrir o app
    const timer = window.setInterval(bater, INTERVALO_MS);
    // Ao voltar o foco para a aba, bate na hora (não espera o próximo ciclo).
    const aoVisivel = () => {
      if (document.visibilityState === "visible") bater();
    };
    document.addEventListener("visibilitychange", aoVisivel);

    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", aoVisivel);
    };
  }, []);
}
