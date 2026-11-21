/**
 * Storage com a MESMA interface do AsyncStorage (getItem/setItem/removeItem),
 * porém com o VALOR cifrado em repouso (ver ./cifra). É usado tanto pelo
 * persister do React Query (cache das telas) quanto pela sessão salva e pela
 * fila offline — tudo que toca o disco com dado sensível passa por aqui.
 */
import AsyncStorage from "@react-native-async-storage/async-storage";

import { cifrar, decifrar } from "./cifra";

let ultimaGravacao = Promise.resolve();

function alterarDisco(alterar: () => Promise<void>): Promise<void> {
  const resultado = ultimaGravacao.then(alterar);
  ultimaGravacao = resultado.catch(() => undefined);
  return resultado;
}

export const armazenamentoCifrado = {
  getItem: async (chave: string): Promise<string | null> => {
    const bruto = await AsyncStorage.getItem(chave);
    return bruto === null ? null : decifrar(bruto);
  },
  setItem: (chave: string, valor: string): Promise<void> =>
    alterarDisco(async () => { await AsyncStorage.setItem(chave, await cifrar(valor)); }),
  removeItem: (chave: string): Promise<void> =>
    alterarDisco(() => AsyncStorage.removeItem(chave)),
};
