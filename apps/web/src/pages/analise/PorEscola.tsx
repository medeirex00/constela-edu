/**
 * Análise detalhada por escola (aba `?ver=escola` das Análises avançadas; Secretaria e admin
 * global): a escola do filtro da página → os indicadores oficiais dela (séries, com as
 * referências da rede), as plataformas por série e o que não dá para comparar. É o mesmo
 * conteúdo que a coordenação vê na Visão da Escola. Para comparar as escolas entre si, o
 * lugar é "Comparar escolas" (fluxo principal), não aqui.
 */
import { School } from "lucide-react";

import { periodoParaQuery } from "../../components/SeletorPeriodo";
import { Card, Carregando, IconePastel, Mensagem, Vazio } from "../../components/ui";
import { useApp } from "../../context/AppContext";
import { ConteudoAnaliseEscola } from "./AnaliseDaEscola";
import { TITULO_CARTAO, useApiExata } from "./comum";
import type { RespostaAnaliseEscola, RespostaIndicadoresRede } from "./tipos";

export default function PorEscola({ base, escolaId, serie }: {
  base: RespostaIndicadoresRede;
  escolaId: number | null;
  serie: number | null;
}) {
  const { periodo } = useApp();
  const escola = escolaId != null ? base.escolas.find((e) => e.id === escolaId) ?? null : null;
  const url = escola ? `/escolas/${escola.id}/analise?${periodoParaQuery(periodo)}` : null;
  const { dados, carregando, erro } = useApiExata<RespostaAnaliseEscola>(url);

  if (!escola) {
    return (
      <Card className="p-6">
        <Vazio icone={School} titulo="Escolha uma escola"
               descricao="Use o filtro Escola, acima: aparecem os indicadores oficiais da escola (com as referências da rede), o uso das plataformas por série e o que não dá para comparar." />
      </Card>
    );
  }
  const daEscola = dados && dados.escola.id === escola.id ? dados : null;
  return (
    <Card className="space-y-5 p-6" >
      <h2 className={`${TITULO_CARTAO} min-w-0`}>
        <IconePastel icone={School} tom="violeta" tamanho="sm" />
        <span className="break-words" data-testid="por-escola-nome">{escola.nome}</span>
      </h2>
      {erro && !daEscola ? (
        <Mensagem tipo="erro">Não foi possível carregar a análise da escola: {erro.message}</Mensagem>
      ) : !daEscola ? (
        carregando || url ? <Carregando texto="Carregando a análise da escola..." /> : null
      ) : (
        <ConteudoAnaliseEscola dados={daEscola} serie={serie} />
      )}
    </Card>
  );
}
