/** Arquitetura única de consumo de API — leitura (useApi) e ação (useMutation). */
export { useApi, limparCacheApi } from "./useApi";
export type {
  Buscador,
  FonteApi,
  OpcoesUseApi,
  ResultadoUseApi,
} from "./useApi";
export { useMutation } from "./useMutation";
export type {
  OpcoesUseMutation,
  ResultadoUseMutation,
} from "./useMutation";
