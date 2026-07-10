/**
 * Cifra simétrica para o CACHE EM REPOUSO (LGPD: dados de crianças ficam no
 * aparelho). A chave de 256 bits é gerada pelo CSPRNG do sistema (expo-crypto)
 * e guardada no SecureStore (Keystore/Keychain do SO, cifrado por hardware
 * quando disponível) — nunca no AsyncStorage em texto plano. O conteúdo é
 * cifrado com AES-256-CBC e um IV aleatório por gravação.
 *
 * Falha graciosa: se a chave sumir (app reinstalado) ou o dado corromper,
 * `decifrar` devolve null e o cache é simplesmente re-sincronizado na próxima
 * conexão — nunca quebra o app.
 */
import CryptoJS from "crypto-js";
import * as Crypto from "expo-crypto";
import * as SecureStore from "expo-secure-store";

const CHAVE_SECURESTORE = "constela_cache_chave_v1";

// A chave fica em memória após o 1º acesso (evita ir ao SecureStore a cada
// leitura/escrita do cache).
let chaveMemo: CryptoJS.lib.WordArray | null = null;

function bytesParaHex(bytes: Uint8Array): string {
  let hex = "";
  for (let i = 0; i < bytes.length; i++) {
    hex += bytes[i].toString(16).padStart(2, "0");
  }
  return hex;
}

async function bytesAleatorios(n: number): Promise<CryptoJS.lib.WordArray> {
  const bytes = await Crypto.getRandomBytesAsync(n); // CSPRNG do sistema
  return CryptoJS.enc.Hex.parse(bytesParaHex(bytes));
}

async function obterChave(): Promise<CryptoJS.lib.WordArray> {
  if (chaveMemo) return chaveMemo;
  let b64 = await SecureStore.getItemAsync(CHAVE_SECURESTORE);
  if (!b64) {
    b64 = CryptoJS.enc.Base64.stringify(await bytesAleatorios(32)); // 256 bits
    await SecureStore.setItemAsync(CHAVE_SECURESTORE, b64);
  }
  chaveMemo = CryptoJS.enc.Base64.parse(b64);
  return chaveMemo;
}

export async function cifrar(texto: string): Promise<string> {
  const chave = await obterChave();
  const iv = await bytesAleatorios(16); // IV imprevisível por gravação (CSPRNG)
  const cifrado = CryptoJS.AES.encrypt(texto, chave, {
    iv,
    mode: CryptoJS.mode.CBC,
    padding: CryptoJS.pad.Pkcs7,
  });
  // Formato: base64(iv) ":" base64(ciphertext). O IV não é secreto.
  return `${CryptoJS.enc.Base64.stringify(iv)}:${cifrado.toString()}`;
}

export async function decifrar(blob: string): Promise<string | null> {
  try {
    const sep = blob.indexOf(":");
    if (sep < 0) return null;
    const iv = CryptoJS.enc.Base64.parse(blob.slice(0, sep));
    const chave = await obterChave();
    const bytes = CryptoJS.AES.decrypt(blob.slice(sep + 1), chave, {
      iv,
      mode: CryptoJS.mode.CBC,
      padding: CryptoJS.pad.Pkcs7,
    });
    const texto = bytes.toString(CryptoJS.enc.Utf8);
    return texto.length ? texto : null;
  } catch {
    return null; // chave trocada / dado corrompido: trata como "sem cache"
  }
}

/** Rotaciona a chave (logout): o cache antigo vira ilegível. Chamar no `sair`. */
export async function esquecerChave(): Promise<void> {
  chaveMemo = null;
  await SecureStore.deleteItemAsync(CHAVE_SECURESTORE);
}
