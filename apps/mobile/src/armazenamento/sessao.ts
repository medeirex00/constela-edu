/**
 * Sessão salva (cifrada) para o BOOT OFFLINE: guarda usuário, escolas e a
 * escola ativa da última sincronização. Ao abrir o app SEM rede, restauramos
 * daqui — em vez de forçar uma chamada de rede que, ao falhar, deslogava o
 * usuário indevidamente.
 */
import type { Escola, Usuario } from "@constela/core";

import { armazenamentoCifrado } from "./armazenamentoCifrado";

const CHAVE = "constela_sessao_v1";

export interface SessaoSalva {
  usuario: Usuario;
  escolas: Escola[];
  escolaId: number | null;
}

export async function salvarSessao(sessao: SessaoSalva): Promise<void> {
  await armazenamentoCifrado.setItem(CHAVE, JSON.stringify(sessao));
}

export async function lerSessao(): Promise<SessaoSalva | null> {
  const bruto = await armazenamentoCifrado.getItem(CHAVE);
  if (!bruto) return null;
  try {
    return JSON.parse(bruto) as SessaoSalva;
  } catch {
    return null;
  }
}

export async function limparSessao(): Promise<void> {
  await armazenamentoCifrado.removeItem(CHAVE);
}
