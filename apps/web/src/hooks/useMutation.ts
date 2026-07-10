/**
 * Companheiro imperativo do `useApi`, para AÇÕES disparadas por evento
 * (POST/PATCH/DELETE em botões e formulários). Padroniza o `enviando`, o
 * tratamento de erro e o cancelamento ao desmontar — no lugar do típico
 * `try/setOcupado/catch(ApiError)` copiado em cada tela.
 *
 *   const salvar = useMutation((corpo) =>
 *     api(`/escolas/${id}/usuarios`, { method: "POST", body: JSON.stringify(corpo) }),
 *     { aoSucesso: recarregar });
 *   <Botao disabled={salvar.enviando} onClick={() => salvar.executar(dados)} />
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError } from "../lib/api";

export interface OpcoesUseMutation<TArg, TRes> {
  aoSucesso?: (resultado: TRes, argumento: TArg) => void;
  aoErro?: (erro: ApiError, argumento: TArg) => void;
}

export interface ResultadoUseMutation<TArg, TRes> {
  /** Dispara a ação; resolve com o resultado, ou `undefined` se falhar. */
  executar: (argumento: TArg) => Promise<TRes | undefined>;
  enviando: boolean;
  erro: ApiError | null;
  limparErro: () => void;
}

export function useMutation<TArg = void, TRes = unknown>(
  acao: (argumento: TArg, sinal: AbortSignal) => Promise<TRes>,
  opcoes: OpcoesUseMutation<TArg, TRes> = {},
): ResultadoUseMutation<TArg, TRes> {
  const [enviando, setEnviando] = useState(false);
  const [erro, setErro] = useState<ApiError | null>(null);

  const montado = useRef(true);
  const refAcao = useRef(acao);
  refAcao.current = acao;
  const refOpcoes = useRef(opcoes);
  refOpcoes.current = opcoes;

  useEffect(() => {
    montado.current = true;
    return () => {
      montado.current = false;
    };
  }, []);

  const executar = useCallback(async (argumento: TArg): Promise<TRes | undefined> => {
    const controller = new AbortController();
    setEnviando(true);
    setErro(null);
    try {
      const resultado = await refAcao.current(argumento, controller.signal);
      if (montado.current) {
        refOpcoes.current.aoSucesso?.(resultado, argumento);
      }
      return resultado;
    } catch (bruto) {
      const apiErro = bruto instanceof ApiError
        ? bruto
        : new ApiError(0, "Falha de conexão. Verifique a internet e tente de novo.");
      if (montado.current) {
        setErro(apiErro);
        refOpcoes.current.aoErro?.(apiErro, argumento);
      }
      return undefined;
    } finally {
      if (montado.current) setEnviando(false);
    }
  }, []);

  const limparErro = useCallback(() => setErro(null), []);

  return { executar, enviando, erro, limparErro };
}
