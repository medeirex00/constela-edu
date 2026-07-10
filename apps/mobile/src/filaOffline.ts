/**
 * Fila de ESCRITAS offline. O app é primariamente de consulta, mas as escritas
 * que existirem (ex.: registrar o aparelho para push) não podem se perder
 * quando o celular está sem rede. Uma ação disparada offline é persistida
 * (cifrada) e reenviada automaticamente quando a conexão volta.
 *
 * Fluxo:
 *   - `enviarOuEnfileirar`: tenta agora; se falhar por REDE/servidor, enfileira;
 *     erro 4xx (cliente) é definitivo e propaga (repetir não resolveria).
 *   - `processarFila`: drena em ordem (FIFO); para no 1º erro de rede (tenta na
 *     próxima reconexão) e descarta itens com erro 4xx permanente.
 *   - `ligarFilaAReconexao`: assina o onlineManager e drena quando a rede volta.
 */
import { ApiError, api } from "@constela/core";
import { onlineManager } from "@tanstack/react-query";

import { armazenamentoCifrado } from "./armazenamento/armazenamentoCifrado";

const CHAVE = "constela_fila_offline_v1";

interface ItemFila {
  id: string;
  caminho: string;
  metodo: string;
  corpo: string | null;
}

let processando = false;
let sequencia = 0;

function permanente(erro: unknown): boolean {
  // 4xx = erro do cliente (inclui 401/403/422): repetir não resolve.
  return erro instanceof ApiError && erro.status >= 400 && erro.status < 500;
}

async function ler(): Promise<ItemFila[]> {
  const bruto = await armazenamentoCifrado.getItem(CHAVE);
  if (!bruto) return [];
  try {
    return JSON.parse(bruto) as ItemFila[];
  } catch {
    return [];
  }
}

async function gravar(itens: ItemFila[]): Promise<void> {
  if (itens.length === 0) {
    await armazenamentoCifrado.removeItem(CHAVE);
    return;
  }
  await armazenamentoCifrado.setItem(CHAVE, JSON.stringify(itens));
}

async function enfileirar(caminho: string, metodo: string, corpo: unknown): Promise<void> {
  const itens = await ler();
  itens.push({
    // Sem Math.random (indisponível de forma estável): timestamp + contador.
    id: `${Date.now()}_${sequencia++}`,
    caminho,
    metodo,
    corpo: corpo === undefined ? null : JSON.stringify(corpo),
  });
  await gravar(itens);
}

export async function enviarOuEnfileirar(
  caminho: string, metodo: string, corpo?: unknown,
): Promise<void> {
  if (!onlineManager.isOnline()) {
    await enfileirar(caminho, metodo, corpo);
    return;
  }
  try {
    await api(caminho, {
      method: metodo,
      body: corpo === undefined ? undefined : JSON.stringify(corpo),
    });
  } catch (erro) {
    if (permanente(erro)) throw erro;
    await enfileirar(caminho, metodo, corpo); // rede/servidor: tenta depois
  }
}

export async function processarFila(): Promise<void> {
  if (processando || !onlineManager.isOnline()) return;
  processando = true;
  try {
    let itens = await ler();
    while (itens.length > 0) {
      const item = itens[0];
      try {
        await api(item.caminho, { method: item.metodo, body: item.corpo ?? undefined });
      } catch (erro) {
        if (!permanente(erro)) break; // rede caiu de novo: mantém e sai
        // erro permanente: descarta o item e segue para o próximo
      }
      itens = itens.slice(1);
      await gravar(itens);
    }
  } finally {
    processando = false;
  }
}

/** Liga a fila à reconexão automática. Devolve a função para cancelar. */
export function ligarFilaAReconexao(): () => void {
  return onlineManager.subscribe((online) => {
    if (online) void processarFila();
  });
}
