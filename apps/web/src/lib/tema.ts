/**
 * Tema claro/escuro: a preferência é guardada no navegador e só vale nas páginas internas,
 * com a sessão aberta. Login, redefinição de senha, telão (/p/…) e vitrine (/rede/p/…) ficam
 * SEMPRE no escuro — depois de sair, ao recarregar e ao abrir o endereço direto — sem apagar
 * a preferência guardada, que volta a valer ao entrar.
 *
 * `public/tema-inicial.js` aplica a MESMA regra antes do primeiro desenho (sem "flash"
 * claro enquanto o JavaScript do app carrega); o teste `tema.test.ts` confere os dois.
 */
import { ehTelaPublica } from "./pwaAtualizacao";

export type Tema = "claro" | "escuro";

/** Telas de entrada e páginas públicas: sem sessão, sempre escuras. O roteador não
 *  diferencia maiúsculas (/LOGIN abre o login), então a regra também não. */
export function telaSempreEscura(caminho: string): boolean {
  const c = caminho.toLowerCase();
  return /^\/(login|redefinir-senha)\/?$/.test(c) || ehTelaPublica(c);
}

/** Token guardado que ainda vale: o JWT com o `exp` no futuro. Vencido (quem reabre o app
 *  no dia seguinte) ou ilegível não conta — a tela vai para o login, que é escuro, sem
 *  passar por um "Abrindo o sistema..." claro. Só lê o payload: serve para pintar a tela,
 *  não para autorizar nada (quem decide a sessão é o /auth/me). */
export function tokenVivo(token: string | null, agoraMs: number = Date.now()): boolean {
  if (!token) return false;
  try {
    const dados = JSON.parse(atob(token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/")));
    return typeof dados.exp === "number" && dados.exp * 1000 > agoraMs;
  } catch {
    return false;
  }
}

/** O `<html>` fica escuro? A preferência só conta com a sessão aberta (ou abrindo, com
 *  token vivo) numa página interna; sem sessão a página interna leva ao login, escuro. */
export function htmlEscuro(caminho: string, preferencia: Tema, comSessao: boolean): boolean {
  if (telaSempreEscura(caminho) || !comSessao) return true;
  return preferencia === "escuro";
}
