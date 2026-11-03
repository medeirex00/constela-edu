/**
 * Montagens de TESTE para as peças da análise que saíram de `/rede/analise` (Análises
 * avançadas) e hoje vivem nas telas da Secretaria: os cartões, a cobertura e as limitações
 * das plataformas (tela Elefante e Matific) e o detalhe de um indicador — série histórica e
 * escolas numa edição (tela Avaliações externas). Os testes que protegiam essas peças pela
 * antiga Visão geral e pela aba "Avaliações externas" agora as conferem DIRETO, com o mesmo
 * arranjo e os filtros na URL como a página os passa — sem depender de qual tela as hospeda.
 * Não é arquivo de teste (o vitest só roda `*.test.tsx`).
 */
import { useSearchParams } from "react-router-dom";

import { CartoesPlataformas, CoberturaDasColetas, LimitacoesPlataformas } from "../pages/analise/Plataformas";
import PorIndicador from "../pages/analise/PorIndicador";
import { useApiExata } from "../pages/analise/comum";
import type { EscolaDaRede, RespostaIndicadoresRede, RespostaPlataformas } from "../pages/analise/tipos";

/** Os cartões, a cobertura e as limitações das plataformas, como a antiga Visão geral os
 *  montava (o recorte da rede, ou o de uma escola). */
export function PlataformasNoPeriodo({ dados, escolas, escolaId = null }: {
  dados: RespostaPlataformas;
  escolas: EscolaDaRede[];
  escolaId?: number | null;
}) {
  const recorte = escolaId != null ? dados.escolas.find((e) => e.escola_id === escolaId) ?? null : dados.rede;
  if (!recorte) return <p>sem recorte</p>;
  return (
    <>
      <CartoesPlataformas alunos={recorte.alunos} elefante={recorte.elefante} matific={recorte.matific}
                          modulos={dados.modulos} suprimido={recorte.suprimido}
                          textoSupressao={recorte.texto_supressao} textoBlocos={recorte.texto_blocos}
                          nivelTitulo={3} />
      <CoberturaDasColetas cobertura={dados.cobertura} escolas={escolas} escolasPlataformas={dados.escolas} />
      <LimitacoesPlataformas limitacoes={dados.limitacoes} />
    </>
  );
}

/** O detalhe de um indicador como a página o monta: o catálogo da rede 1 (lido da API), os
 *  filtros na URL e um filtro "Escola" (o da página). */
export function IndicadorEmDetalhe() {
  const [params, setParams] = useSearchParams();
  const { dados } = useApiExata<RespostaIndicadoresRede>("/redes/1/analise/indicadores");
  if (!dados) return <p>carregando o catálogo</p>;
  const atualizar = (mudancas: Record<string, string | null>) => {
    const prox = new URLSearchParams(params);
    for (const [k, v] of Object.entries(mudancas)) {
      if (v == null || v === "") prox.delete(k);
      else prox.set(k, v);
    }
    setParams(prox, { replace: true });
  };
  const escola = params.get("escola");
  return (
    <>
      <label>
        Escola
        <select value={escola ?? ""} onChange={(e) => atualizar({ escola: e.target.value || null })}>
          <option value="">Toda a rede</option>
          {dados.escolas.map((e) => <option key={e.id} value={e.id}>{e.nome}</option>)}
        </select>
      </label>
      <PorIndicador redeId={1} base={dados} params={params} atualizar={atualizar}
                    escolaId={escola ? Number(escola) : null} titulo="Série histórica e escolas numa edição" />
    </>
  );
}
