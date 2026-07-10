/**
 * Storage com a MESMA interface do AsyncStorage (getItem/setItem/removeItem),
 * porém com o VALOR cifrado em repouso (ver ./cifra). É usado tanto pelo
 * persister do React Query (cache das telas) quanto pela sessão salva e pela
 * fila offline — tudo que toca o disco com dado sensível passa por aqui.
 */
import AsyncStorage from "@react-native-async-storage/async-storage";

import { cifrar, decifrar } from "./cifra";

export const armazenamentoCifrado = {
  getItem: async (chave: string): Promise<string | null> => {
    const bruto = await AsyncStorage.getItem(chave);
    return bruto === null ? null : decifrar(bruto);
  },
  setItem: async (chave: string, valor: string): Promise<void> => {
    await AsyncStorage.setItem(chave, await cifrar(valor));
  },
  removeItem: async (chave: string): Promise<void> => {
    await AsyncStorage.removeItem(chave);
  },
};
