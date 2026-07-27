/** Linha do tempo e evolução do aluno (PRD §67–§71). */
import { ArrowDown, ArrowLeft, ArrowUp, Minus } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { GraficoLinha } from "../components/Grafico";
import { Card, Carregando, PageHeader, Vazio } from "../components/ui";
import { useApp } from "../context/AppContext";
import { useApi } from "../hooks/useApi";
import { nota } from "../lib/formato";

interface PontoLinha {
  data: string;
  [indicador: string]: string | number;
}

interface EvolucaoResposta {
  aluno_id: number;
  nome: string;
  linha_do_tempo: { matific: PontoLinha[]; elefante: PontoLinha[] };
  resumo: {
    dias: number;
    indicadores: {
      indicador: string;
      inicial: number;
      atual: number;
      variacao: number;
      percentual: number | null;
    }[];
  };
}

const ROTULOS: Record<string, string> = {
  atividades: "Atividades",
  estrelas: "Estrelas",
  pontuacao_media: "Pontuação média",
  livros_unicos: "Livros únicos",
  tempo_leitura_min: "Tempo de leitura (min)",
  questoes_tentativas: "Questões respondidas",
  questoes_acertos: "Acertos",
};

function dataCurta(iso: string): string {
  return new Date(iso).toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" });
}

function serie(pontos: PontoLinha[], campo: string, nome: string) {
  return {
    nome,
    pontos: pontos.map((ponto) => ({
      rotulo: dataCurta(ponto.data),
      valor: Number(ponto[campo] ?? 0),
    })),
  };
}

export default function EvolucaoAluno() {
  const { id } = useParams();
  const { escolaId } = useApp();
  const [dias, setDias] = useState(30);
  const { dados: dadosEvolucao, erro, carregando } = useApi<EvolucaoResposta>(
    escolaId && id ? `/escolas/${escolaId}/alunos/${id}/evolucao?dias=${dias}` : null,
  );

  if (carregando) return <Carregando />;
  if (erro) return <Vazio titulo="Não foi possível carregar" descricao={erro.message} />;
  if (!dadosEvolucao) return <Vazio titulo="Aluno não encontrado" />;

  const { linha_do_tempo: linha, resumo } = dadosEvolucao;

  // Primeira data COM dado (nas duas plataformas). Se o período escolhido vai
  // mais para trás do que o 1º registro, avisamos: não há histórico anterior —
  // é quando o Constela começou a coletar este aluno (não um bug do gráfico).
  const datas = [...linha.matific, ...linha.elefante]
    .map((ponto) => new Date(ponto.data).getTime())
    .filter((t) => !Number.isNaN(t))
    .sort((a, b) => a - b);
  const primeira = datas[0];
  const faltaHistorico =
    primeira != null && primeira - (Date.now() - dias * 864e5) > 2 * 864e5;
  const primeiraFmt =
    primeira != null ? new Date(primeira).toLocaleDateString("pt-BR") : "";

  return (
    <div className="space-y-6">
      <div>
        <Link
          to={`/alunos/${id}`}
          className="mb-3 inline-flex items-center gap-1.5 text-sm text-zinc-500 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100"
        >
          <ArrowLeft size={15} /> Perfil de {dadosEvolucao.nome}
        </Link>
        <PageHeader
          titulo={`Evolução — ${dadosEvolucao.nome}`}
          descricao="Histórico imutável: cada importação gera um novo ponto na linha do tempo."
          acoes={
            <select
              aria-label="Período da evolução"
              className="rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-900"
              value={dias}
              onChange={(evento) => setDias(Number(evento.target.value))}
            >
              <option value={7}>Últimos 7 dias</option>
              <option value={30}>Últimos 30 dias</option>
              <option value={90}>Últimos 90 dias</option>
              <option value={365}>Ano inteiro</option>
            </select>
          }
        />
      </div>

      {faltaHistorico && (
        <div className="rounded-lg border border-indigo-200 bg-indigo-50/60 px-4 py-2.5 text-xs text-indigo-800 dark:border-indigo-500/30 dark:bg-indigo-500/10 dark:text-indigo-200">
          Este aluno tem dados a partir de <b>{primeiraFmt}</b> — foi quando o Constela
          começou a registrar a evolução dele. Não há histórico anterior a essa data
          para exibir; a linha do tempo cresce a cada sincronização.
        </div>
      )}

      <Card className="p-4">
        <h3 className="mb-3 text-sm font-semibold">Variação no período ({resumo.dias} dias)</h3>
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
          {resumo.indicadores.map((item) => (
            <div key={item.indicador} className="rounded-lg border border-zinc-200 p-3 dark:border-zinc-800">
              <p className="text-xs text-zinc-500 dark:text-zinc-400">{ROTULOS[item.indicador] ?? item.indicador}</p>
              <div className="mt-1 flex items-baseline gap-2">
                <span className="text-lg font-semibold tabular-nums">{nota(item.atual)}</span>
                <span
                  className={`flex items-center gap-0.5 text-xs font-medium tabular-nums ${
                    item.variacao > 0
                      ? "text-emerald-600 dark:text-emerald-400"
                      : item.variacao < 0
                        ? "text-red-600 dark:text-red-400"
                        : "text-zinc-400"
                  }`}
                >
                  {item.variacao > 0 ? <ArrowUp size={12} /> : item.variacao < 0 ? <ArrowDown size={12} /> : <Minus size={12} />}
                  {nota(Math.abs(item.variacao))}
                  {item.percentual !== null && ` (${item.percentual > 0 ? "+" : ""}${item.percentual}%)`}
                </span>
              </div>
            </div>
          ))}
        </div>
      </Card>

      <Card className="p-4">
        <h3 className="mb-1 text-sm font-semibold">Matific ao longo do tempo</h3>
        <p className="mb-3 text-xs text-zinc-500 dark:text-zinc-400">
          Um gráfico por indicador — cada um na sua própria escala, com os valores marcados.
        </p>
        <div className="grid gap-6 sm:grid-cols-2">
          {([
            ["atividades", "Atividades"],
            ["estrelas", "Estrelas"],
            ["pontuacao_media", "Pontuação média"],
          ] as const).map(([campo, nome]) => (
            <div key={campo}>
              <p className="mb-1 text-xs font-medium text-zinc-600 dark:text-zinc-300">{nome}</p>
              <GraficoLinha series={[serie(linha.matific, campo, nome)]} altura={185} />
            </div>
          ))}
        </div>
      </Card>

      <Card className="p-4">
        <h3 className="mb-1 text-sm font-semibold">Elefante Letrado ao longo do tempo</h3>
        <p className="mb-3 text-xs text-zinc-500 dark:text-zinc-400">
          Um gráfico por indicador — cada um na sua própria escala, com os valores marcados.
        </p>
        <div className="grid gap-6 sm:grid-cols-2">
          {([
            ["livros_unicos", "Livros únicos"],
            ["questoes_acertos", "Acertos"],
            ["tempo_leitura_min", "Tempo (min)"],
          ] as const).map(([campo, nome]) => (
            <div key={campo}>
              <p className="mb-1 text-xs font-medium text-zinc-600 dark:text-zinc-300">{nome}</p>
              <GraficoLinha series={[serie(linha.elefante, campo, nome)]} altura={185} />
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}
