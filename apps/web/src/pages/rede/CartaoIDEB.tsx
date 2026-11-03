/**
 * Cartão do IDEB e do SAEB OFICIAIS do INEP da rede municipal e por escola na tela da
 * rede — etapas E8a e E8b dos indicadores oficiais (plano, 5.1). Como o `CartaoICA` e o `CartaoSARESP`, vive fora
 * de `RedeAvaliacoes.tsx` (que só o liga por uma linha), para não conflitar com o
 * trabalho paralelo daquela tela.
 *
 * Lê `GET /redes/{id}/indicadores/ideb` (Secretaria da própria rede e admin global) e
 * mostra a `AbaIDEB` (rede municipal, por escola, série de uma escola e cobertura). Sem resultado
 * importado, diz isso — nunca 0. Os números gravados antes pelo botão de 1 clique
 * aparecem mesmo sem a importação oficial, sempre marcados "sem registro oficial".
 */
import { AlertTriangle, Info, Landmark } from "lucide-react";

import { Card, Carregando, Mensagem } from "../../components/ui";
import { useApi } from "../../hooks/useApi";
import AbaIDEB from "./AbaIDEB";
import { CabecalhoIndicador } from "./visualIndicadores";
import type { RespostaIDEB } from "./ideb";

export type { RespostaIDEB } from "./ideb";

export default function CartaoIDEB({ redeId, ehGlobal }: { redeId: number; ehGlobal: boolean }) {
  const { dados, carregando, erro } = useApi<RespostaIDEB>(`/redes/${redeId}/indicadores/ideb`);
  return (
    <section data-testid="cartao-ideb" aria-label="IDEB e SAEB oficiais do INEP da rede e por escola">
      <Card className="space-y-4 p-5 sm:p-6">
        <CabecalhoIndicador icone={Landmark} tom="teal" fonte="INEP" titulo="IDEB e SAEB — oficial" />
        <p className="flex items-start gap-1.5 rounded-xl bg-indigo-50 p-3 text-xs text-indigo-800 dark:bg-indigo-500/10 dark:text-indigo-300">
          <Info size={14} className="mt-0.5 shrink-0" aria-hidden="true" />
          <span>
            Índice de Desenvolvimento da Educação Básica (Ideb) e Saeb do 5º ano da rede municipal e por escola (anos
            iniciais), dos arquivos oficiais do INEP — a rede comparada com o Brasil na mesma rede.
            {" "}{dados?.avisos.escala ?? "O Saeb do 5º ano tem escala própria: não se compara com o SARESP nem com o ICA."}
          </span>
        </p>

        {carregando && !dados ? (
          <Carregando texto="Carregando o Ideb e o Saeb..." />
        ) : erro && !dados ? (
          <Mensagem tipo="erro">Não foi possível carregar o Ideb e o Saeb: {erro.message}</Mensagem>
        ) : dados ? (
          <>
            {dados.pendencias.includes("codigo_ibge") && (
              <p className="flex items-start gap-1.5 rounded-lg bg-amber-50 p-2.5 text-xs text-amber-800 dark:bg-amber-500/10 dark:text-amber-300"
                 data-testid="ideb-pendencias">
                <AlertTriangle size={14} className="mt-0.5 shrink-0" aria-hidden="true" />
                A rede não tem o código IBGE do município cadastrado: sem ele, o arquivo oficial do Ideb não pode ser
                recortado para a rede.
                {!ehGlobal && " Quem cadastra o código é o administrador global do Constela."}
              </p>
            )}
            {dados.tem_dados ? (
              <AbaIDEB dados={dados} />
            ) : (
              <p className="rounded-lg border border-dashed border-zinc-300 p-4 text-sm text-zinc-500 dark:border-zinc-700"
                 data-testid="ideb-sem-dado">
                Sem resultado do Ideb e do Saeb importado para a rede.
                {ehGlobal && " O arquivo do INEP entra pelo pacote que a linha de comando “preparar” gera nesta máquina, "
                  + "no cartão “Importar indicadores oficiais”, mais abaixo, com prévia e desfazer — só do administrador global."}
              </p>
            )}
          </>
        ) : null}
      </Card>
    </section>
  );
}
