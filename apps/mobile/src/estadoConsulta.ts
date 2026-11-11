/**
 * Estado de uma tela que lê UMA consulta (useQuery): a decisão única entre
 * "carregando", "erro", "sem dados salvos" e "dados", usada pelo Painel, pelo
 * Ranking e pelo Perfil do aluno.
 *
 * Erro do servidor (403, 404, 500, servidor fora) é ERRO, com a mensagem que o
 * cliente da API já traduz — nunca "sem dados no período" nem o texto de quem está
 * sem internet. Sem rede de verdade, a consulta do app (offlineFirst) fica PAUSADA,
 * sem erro: aí sim é "sem dados salvos" e vale o texto de "conecte-se".
 */
import { ApiError } from "@constela/core";

export type EstadoConsulta<T> =
  | { tipo: "carregando" }
  | { tipo: "erro"; mensagem: string }
  | { tipo: "semDados" }
  /** `aviso`: a última atualização falhou; os dados são os últimos salvos. */
  | { tipo: "dados"; dados: T; aviso: string | null };

export const MENSAGEM_ERRO_PADRAO = "Não foi possível carregar agora. Tente de novo.";

/** Mensagem para quem usa: a do servidor (ou a de falta de conexão), nunca o texto
 *  técnico de uma exceção qualquer. */
export function mensagemDoErro(erro: unknown): string {
  return erro instanceof ApiError && erro.message ? erro.message : MENSAGEM_ERRO_PADRAO;
}

export function estadoDaConsulta<T>(consulta: {
  data: T | undefined;
  isLoading: boolean;
  isError: boolean;
  error: unknown;
}): EstadoConsulta<T> {
  if (consulta.data !== undefined) {
    return {
      tipo: "dados",
      dados: consulta.data,
      aviso: consulta.isError ? mensagemDoErro(consulta.error) : null,
    };
  }
  if (consulta.isError) return { tipo: "erro", mensagem: mensagemDoErro(consulta.error) };
  if (consulta.isLoading) return { tipo: "carregando" };
  return { tipo: "semDados" };
}
