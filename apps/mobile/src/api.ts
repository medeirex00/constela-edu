/**
 * Adaptador Mobile do cliente compartilhado (@sgpe/core).
 *
 * Decisões de plataforma:
 *   - token no SecureStore (armazenamento cifrado do sistema — nunca em
 *     texto plano no AsyncStorage);
 *   - sessão expirada → notifica o contexto de autenticação (callback);
 *   - base da API vem de EXPO_PUBLIC_API_URL (inline no build) — no
 *     emulador Android use http://10.0.2.2:8000, em aparelho físico o IP
 *     da máquina na rede local, em produção a URL pública do servidor.
 */
import { configurarApi } from "@sgpe/core";
import * as SecureStore from "expo-secure-store";

const CHAVE_TOKEN = "sgpe_token";

let avisarSessaoExpirada: () => void = () => undefined;

export function aoExpirarSessao(callback: () => void): void {
  avisarSessaoExpirada = callback;
}

export const BASE_API =
  process.env.EXPO_PUBLIC_API_URL ?? "http://10.0.2.2:8000/api/v1";

configurarApi({
  base: BASE_API,
  armazenamento: {
    obter: () => SecureStore.getItemAsync(CHAVE_TOKEN),
    guardar: (token) => SecureStore.setItemAsync(CHAVE_TOKEN, token),
    remover: () => SecureStore.deleteItemAsync(CHAVE_TOKEN),
  },
  aoExpirarSessao: () => avisarSessaoExpirada(),
});

export { api, apiUpload, loginRequest, obterToken, guardarToken, limparToken, ApiError } from "@sgpe/core";
