/**
 * Cartão do SARESP OFICIAL da SEDUC-SP na tela da rede — etapa E5 dos indicadores
 * oficiais (plano, 5.1). Como o `CartaoICA`, vive fora de `RedeAvaliacoes.tsx` (que só
 * o liga por uma linha), para não conflitar com o trabalho paralelo daquela tela.
 *
 * Lê `GET /redes/{id}/indicadores/saresp` (Secretaria da própria rede e admin global)
 * e mostra a `AbaSARESP` (rede municipal, por escola e cobertura). Sem resultado
 * importado, diz isso — nunca 0. As médias sem proveniência oficial (estimativa do
 * Constela) aparecem mesmo sem o oficial, sempre separadas e rotuladas.
 */
import { AlertTriangle, Info, Landmark } from "lucide-react";

import { Badge, Card, Carregando, Mensagem } from "../../components/ui";
import { useApi } from "../../hooks/useApi";
import AbaSARESP from "./AbaSARESP";
import type { RespostaSARESP } from "./saresp";

export type { RespostaSARESP } from "./saresp";

function Pendencias({ dados, ehGlobal }: { dados: RespostaSARESP; ehGlobal: boolean }) {
  const quem = ehGlobal ? "" : " Quem cadastra o código é o administrador global do Constela.";
  // O admin global cadastra o CODMUN no cartão de importação (o IBGE, no do ICA).
  const ondeCodmun = ehGlobal ? " Cadastre-o no cartão “Importar indicadores oficiais”, mais abaixo." : quem;
  const semSerie = !dados.territorios.some((t) => t.tem_dados);
  const textos: string[] = [];
  if (dados.pendencias.includes("codigo_ibge")) {
    textos.push("A rede não tem o código IBGE do município cadastrado: sem ele, os arquivos oficiais da SEDUC não "
      + "podem ser recortados para a rede." + quem);
  }
  if (dados.pendencias.includes("codigo_municipio_estadual") && semSerie) {
    textos.push("A rede não tem o código do município na SEDUC (CODMUN, que não é o IBGE): sem ele, a série da rede "
      + "municipal (SARESP por município) não pode ser importada." + ondeCodmun);
  }
  if (textos.length === 0) return null;
  return (
    <div className="space-y-1" data-testid="saresp-pendencias">
      {textos.map((t) => (
        <p key={t} className="flex items-start gap-1.5 rounded-lg bg-amber-50 p-2.5 text-xs text-amber-800 dark:bg-amber-500/10 dark:text-amber-300">
          <AlertTriangle size={14} className="mt-0.5 shrink-0" /> {t}
        </p>
      ))}
    </div>
  );
}

export default function CartaoSARESP({ redeId, ehGlobal }: { redeId: number; ehGlobal: boolean }) {
  const { dados, carregando, erro } = useApi<RespostaSARESP>(`/redes/${redeId}/indicadores/saresp`);
  const temAlgo = Boolean(dados && (dados.tem_dados || dados.estimativas.length > 0));
  return (
    <section data-testid="cartao-saresp" aria-label="SARESP oficial da SEDUC-SP">
      <Card className="space-y-4 p-5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="flex items-center gap-2 text-sm font-semibold">
            <Landmark size={16} className="text-indigo-600" /> SARESP — oficial
          </h2>
          <Badge tom="destaque">SEDUC-SP</Badge>
        </div>
        <p className="flex items-start gap-1.5 rounded-lg bg-indigo-50 p-2.5 text-xs text-indigo-800 dark:bg-indigo-500/10 dark:text-indigo-300">
          <Info size={14} className="mt-0.5 shrink-0" />
          <span>
            Avaliação da Secretaria da Educação do Estado de São Paulo, aplicada no 2º e no 5º ano da rede municipal.
            {" "}{dados?.avisos.escala ?? "O SARESP tem escala própria: as médias não se comparam com o Saeb nem com o ICA."}
          </span>
        </p>

        {carregando && !dados ? (
          <Carregando texto="Carregando o SARESP..." />
        ) : erro && !dados ? (
          <Mensagem tipo="erro">Não foi possível carregar o SARESP: {erro.message}</Mensagem>
        ) : dados ? (
          <>
            <Pendencias dados={dados} ehGlobal={ehGlobal} />
            {temAlgo ? (
              <AbaSARESP dados={dados} />
            ) : (
              <p className="rounded-lg border border-dashed border-zinc-300 p-4 text-sm text-zinc-500 dark:border-zinc-700"
                 data-testid="saresp-sem-dado">
                Sem resultado oficial do SARESP importado para a rede.
                {ehGlobal && " Os arquivos abertos da SEDUC (IEE, SARESP por município e por instância) entram pelo "
                  + "cartão “Importar indicadores oficiais”, mais abaixo, com prévia e desfazer — só do administrador global."}
              </p>
            )}
          </>
        ) : null}
      </Card>
    </section>
  );
}
