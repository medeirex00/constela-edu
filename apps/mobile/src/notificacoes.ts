/**
 * Notificações push (Expo): pede permissão, obtém o token do aparelho e o
 * registra no backend. Melhor esforço — sem permissão ou sem projectId do
 * EAS o app segue funcionando normalmente, apenas sem push.
 *
 * Tirar o aparelho do push (no "Sair" e na sessão expirada) NÃO depende da rede
 * na hora nem do login:
 *   - o token registrado fica guardado no aparelho (SecureStore), não só na
 *     memória: o app que abriu sem rede (e não se registrou de novo) ainda sabe
 *     qual token tirar;
 *   - o pedido vai para /dispositivos/descadastrar, que só pede o token do
 *     aparelho (o JWT já foi apagado, ou venceu);
 *   - se não der agora (sem rede, servidor fora), o descadastro fica PENDENTE e é
 *     repetido quando a rede volta e na próxima abertura do app;
 *   - o registro que ainda estava a caminho do servidor no "Sair" pode ser
 *     processado DEPOIS do descadastro: quando a resposta dele chega e a sessão já
 *     acabou, o descadastro é marcado de novo.
 * Os dois ficam no SecureStore, fora do armazenamento cifrado do cache: o "Sair"
 * troca a chave do cache (esquecerChave) e o que estivesse lá ficaria ilegível.
 */
import { ApiError, api, obterToken } from "@constela/core";
import { onlineManager } from "@tanstack/react-query";
import Constants from "expo-constants";
import * as Device from "expo-device";
import * as Notifications from "expo-notifications";
import * as SecureStore from "expo-secure-store";
import { Platform } from "react-native";

import { enviarOuEnfileirar, enviarPelaApi, type EnvioDaFila } from "./filaOffline";

Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowBanner: true,
    shouldShowList: true,
    shouldPlaySound: false,
    shouldSetBadge: false,
  }),
});

interface RegistroPush {
  escolaId: number;
  token: string;
}

/** O último registro deste aparelho no servidor (escola e token do Expo). */
const CHAVE_REGISTRO = "constela_push_registro_v1";
/** Descadastro pedido e ainda não confirmado pelo servidor. */
const CHAVE_DESCADASTRO = "constela_push_descadastro_v1";

// A sequência protege as duas chaves e as tentativas de descadastro. A fila de
// registros ordena os POSTs da abertura e da reconexão. O logout pode marcar e
// enviar o descadastro enquanto espera a resposta de um desses POSTs.
let ultimoPasso: Promise<unknown> = Promise.resolve();
let ultimoRegistro: Promise<void> = Promise.resolve();
let geracaoPush = 0;

function emSequencia<T>(passo: () => Promise<T>): Promise<T> {
  const resultado = ultimoPasso.then(passo);
  ultimoPasso = resultado.catch(() => undefined);
  return resultado;
}

async function lerRegistro(chave: string): Promise<RegistroPush | null> {
  const bruto = await SecureStore.getItemAsync(chave);
  if (!bruto) return null;
  try {
    const valor = JSON.parse(bruto) as Partial<RegistroPush>;
    return typeof valor.token === "string" && typeof valor.escolaId === "number"
      ? { escolaId: valor.escolaId, token: valor.token }
      : null;
  } catch {
    return null;
  }
}

export async function registrarParaPush(escolaId: number): Promise<string | null> {
  try {
    if (!Device.isDevice) return null; // emulador sem serviços de push
    const desta = geracaoPush;
    const tokenDaSessao = await obterToken();
    if (!tokenDaSessao) return null;

    const { status: atual } = await Notifications.getPermissionsAsync();
    let status = atual;
    if (status !== "granted") {
      ({ status } = await Notifications.requestPermissionsAsync());
    }
    if (status !== "granted") return null;

    if (Platform.OS === "android") {
      await Notifications.setNotificationChannelAsync("default", {
        name: "Constela Edu",
        importance: Notifications.AndroidImportance.DEFAULT,
      });
    }

    const projectId = Constants.expoConfig?.extra?.eas?.projectId as string | undefined;
    const { data: token } = await Notifications.getExpoPushTokenAsync(
      projectId ? { projectId } : undefined,
    );
    if (await obterToken() !== tokenDaSessao || desta !== geracaoPush) return null;

    await enviarOuEnfileirar(`/escolas/${escolaId}/dispositivos`, "POST", {
      token_push: token,
      plataforma: Platform.OS === "ios" ? "ios" : "android",
    }, { tokenDaSessao, enviar: enviarRegistroPush });
    return token;
  } catch {
    return null; // push é opcional — nunca bloqueia o uso do app
  }
}

/** O registro do login e o da fila offline seguem a mesma ordem no aparelho. */
export function enviarRegistroPush(envio: EnvioDaFila): Promise<void> {
  const escola = /^\/escolas\/(\d+)\/dispositivos$/.exec(envio.caminho);
  if (!escola) return enviarPelaApi(envio);
  let token: unknown;
  try {
    token = (JSON.parse(envio.corpo ?? "{}") as { token_push?: unknown } | null)?.token_push;
  } catch {
    return Promise.resolve();
  }
  if (typeof token !== "string" || !token) return Promise.resolve();

  const registro = { escolaId: Number(escola[1]), token };
  const desta = geracaoPush;
  const resultado = ultimoRegistro.then(async () => {
    const pendenteAnterior = await emSequencia(async () => {
      if (await obterToken() !== envio.tokenDaSessao || desta !== geracaoPush) return undefined;

      // Suspende o descadastro antigo enquanto o POST reassocia o aparelho. Se
      // a rede falhar, o pedido antigo volta a ficar pendente.
      const anterior = await lerRegistro(CHAVE_DESCADASTRO);
      await SecureStore.setItemAsync(CHAVE_REGISTRO, JSON.stringify(registro));
      await SecureStore.deleteItemAsync(CHAVE_DESCADASTRO);
      return anterior;
    });
    if (pendenteAnterior === undefined) return;

    let registrado = false;
    try {
      await enviarPelaApi(envio);
      registrado = true;
    } finally {
      const encerrou = await obterToken() !== envio.tokenDaSessao || desta !== geracaoPush;
      const retirar = encerrou ? registro : registrado ? null : pendenteAnterior;
      if (retirar) {
        await emSequencia(() => SecureStore.setItemAsync(CHAVE_DESCADASTRO, JSON.stringify(retirar)));
        // Um novo registro só sai depois desta tentativa. Assim um descadastro
        // antigo nunca invalida um registro confirmado da conta seguinte.
        await descadastrarPendente();
      }
    }
  });
  ultimoRegistro = resultado.catch(() => undefined);
  return resultado;
}

/** Erro que repetir não resolve: o servidor recusou o pedido (4xx), exceto
 *  tempo esgotado (408) e excesso de tentativas (429), que passam. */
function recusaDefinitiva(erro: unknown): boolean {
  return (
    erro instanceof ApiError &&
    erro.status >= 400 &&
    erro.status < 500 &&
    erro.status !== 408 &&
    erro.status !== 429
  );
}

/** Tempo-limite do pedido de descadastro. O fetch do React Native não tem limite
 *  (o OkHttp do Android sai com connect/read/write 0): uma conexão que não responde
 *  prenderia a tentativa, e com ela o próximo registro ou descadastro, por minutos. */
export const LIMITE_DESCADASTRO_MS = 8_000;

/** Tenta o descadastro pendente (se houver). Sem rede, com o servidor fora ou sem
 *  resposta no tempo-limite, ele continua pendente para a próxima tentativa. Não
 *  lança. */
export function descadastrarPendente(): Promise<void> {
  const tentativa = emSequencia(async () => {
    const pendente = await lerRegistro(CHAVE_DESCADASTRO);
    if (!pendente || !onlineManager.isOnline()) return;
    const controle = new AbortController();
    const relogio = setTimeout(() => controle.abort(), LIMITE_DESCADASTRO_MS);
    try {
      await api(`/escolas/${pendente.escolaId}/dispositivos/descadastrar`, {
        method: "POST",
        body: JSON.stringify({ token_push: pendente.token }),
        signal: controle.signal,
      });
    } catch (erro) {
      if (!recusaDefinitiva(erro)) return; // rede/servidor/tempo: tenta de novo depois
    } finally {
      clearTimeout(relogio);
    }
    // Feito (ou recusado de vez): este token não está mais registrado por nós.
    await SecureStore.deleteItemAsync(CHAVE_DESCADASTRO);
    const registro = await lerRegistro(CHAVE_REGISTRO);
    if (registro?.token === pendente.token) await SecureStore.deleteItemAsync(CHAVE_REGISTRO);
  });
  return tentativa.catch(() => undefined);
}

/** Tira este aparelho do push (no "Sair" e na sessão expirada): marca o
 *  descadastro como pendente (no aparelho) e dispara a tentativa na rede em
 *  SEGUNDO PLANO — quem chama não espera o servidor. Não lança: a saída da conta
 *  segue mesmo se o servidor não responder. */
export async function removerRegistroPush(): Promise<void> {
  geracaoPush += 1;
  try {
    const marcado = await emSequencia(async () => {
      const registro = await lerRegistro(CHAVE_REGISTRO);
      if (!registro) return false; // este aparelho não está registrado
      await SecureStore.setItemAsync(CHAVE_DESCADASTRO, JSON.stringify(registro));
      return true;
    });
    if (marcado) void descadastrarPendente();
  } catch {
    /* logout continua mesmo se a remoção falhar */
  }
}

/** Repete o descadastro pendente quando a rede volta. Devolve a função para
 *  cancelar. */
export function ligarDescadastroAReconexao(): () => void {
  return onlineManager.subscribe((online) => {
    if (online) void descadastrarPendente();
  });
}
