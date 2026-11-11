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
 *
 * Toda alteração do disco (acrescentar um item, tirar o item enviado) passa por
 * `emOrdem`, uma de cada vez: ler-alterar-gravar não pode se intercalar com outro,
 * senão a gravação de um apaga o que o outro acabou de pôr (uma escrita que falhou
 * e entrou na fila enquanto a drenagem enviava um item antigo sumia do disco).
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
// Fim da última alteração do disco da fila: a próxima só começa depois dela.
let ultimaAlteracao: Promise<void> = Promise.resolve();

/** Executa `alterar` depois de todas as alterações anteriores da fila. */
function emOrdem(alterar: () => Promise<void>): Promise<void> {
  const resultado = ultimaAlteracao.then(alterar);
  ultimaAlteracao = resultado.catch(() => undefined);
  return resultado;
}

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

function enfileirar(caminho: string, metodo: string, corpo: unknown): Promise<void> {
  // Sem Math.random (indisponível de forma estável): timestamp + contador.
  const item: ItemFila = {
    id: `${Date.now()}_${sequencia++}`,
    caminho,
    metodo,
    corpo: corpo === undefined ? null : JSON.stringify(corpo),
  };
  return emOrdem(async () => {
    const itens = await ler();
    itens.push(item);
    await gravar(itens);
  });
}

/** Tira da fila SÓ o item enviado (pelo id), relendo o disco: o que entrou na
 *  fila enquanto ele estava em voo continua lá. */
function retirar(id: string): Promise<void> {
  return emOrdem(async () => {
    const itens = await ler();
    await gravar(itens.filter((item) => item.id !== id));
  });
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
    for (;;) {
      // Relê a cabeça da fila a cada volta: inclui o que chegou durante a drenagem.
      const [item] = await ler();
      if (!item) break;
      try {
        await api(item.caminho, { method: item.metodo, body: item.corpo ?? undefined });
      } catch (erro) {
        if (!permanente(erro)) break; // rede caiu de novo: mantém e sai
        // erro permanente: descarta o item e segue para o próximo
      }
      await retirar(item.id);
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
