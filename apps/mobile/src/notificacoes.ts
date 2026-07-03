/**
 * Notificações push (Expo): pede permissão, obtém o token do aparelho e o
 * registra no backend. Melhor esforço — sem permissão ou sem projectId do
 * EAS o app segue funcionando normalmente, apenas sem push.
 */
import { api } from "@constela/core";
import Constants from "expo-constants";
import * as Device from "expo-device";
import * as Notifications from "expo-notifications";
import { Platform } from "react-native";

Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowAlert: true,
    shouldPlaySound: false,
    shouldSetBadge: false,
  }),
});

export async function registrarParaPush(escolaId: number): Promise<string | null> {
  try {
    if (!Device.isDevice) return null; // emulador sem serviços de push

    const { status: atual } = await Notifications.getPermissionsAsync();
    let status = atual;
    if (status !== "granted") {
      ({ status } = await Notifications.requestPermissionsAsync());
    }
    if (status !== "granted") return null;

    if (Platform.OS === "android") {
      await Notifications.setNotificationChannelAsync("default", {
        name: "SGPE",
        importance: Notifications.AndroidImportance.DEFAULT,
      });
    }

    const projectId = Constants.expoConfig?.extra?.eas?.projectId as string | undefined;
    const { data: token } = await Notifications.getExpoPushTokenAsync(
      projectId ? { projectId } : undefined,
    );

    await api(`/escolas/${escolaId}/dispositivos`, {
      method: "POST",
      body: JSON.stringify({
        token_push: token,
        plataforma: Platform.OS === "ios" ? "ios" : "android",
      }),
    });
    return token;
  } catch {
    return null; // push é opcional — nunca bloqueia o uso do app
  }
}

export async function removerRegistroPush(escolaId: number, token: string | null): Promise<void> {
  if (!token) return;
  try {
    await api(`/escolas/${escolaId}/dispositivos/remover`, {
      method: "POST",
      body: JSON.stringify({ token_push: token }),
    });
  } catch {
    /* logout continua mesmo se a remoção falhar */
  }
}
