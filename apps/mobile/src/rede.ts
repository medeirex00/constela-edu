/**
 * Estado de conectividade reativo. O `onlineManager` do React Query é a fonte
 * única da verdade (alimentado pelo NetInfo em App.tsx); aqui só o expomos como
 * hook para a UI (banner "sem conexão", estados de tela).
 */
import { onlineManager } from "@tanstack/react-query";
import { useSyncExternalStore } from "react";

export function useOnline(): boolean {
  return useSyncExternalStore(
    (aoMudar) => onlineManager.subscribe(aoMudar),
    () => onlineManager.isOnline(),
    () => true,
  );
}
