/** Linha do tempo e evolução do aluno (PRD §67–§71). */
import { ArrowLeft, BookOpen, CalendarClock, Calculator, LineChart } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { GraficoLinha, useLarguraDoConteiner, type SerieLinha } from "../components/Grafico";
import { SelectNativo } from "../components/PessoasUi";
import {
  Card,
  Erro,
  IconePastel,
  PageHeader,
  Skeleton,
  Variacao,
  Vazio,
} from "../components/ui";
import { useApp } from "../context/AppContext";
import { useApi } from "../hooks/useApi";
import { dataDia, nota, paraData } from "../lib/formato";

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

/** De que plataforma é cada indicador do resumo (o mesmo corte do backend). */
const PLATAFORMA_DO_INDICADOR: Record<string, "matific" | "elefante"> = {
  atividades: "matific",
  estrelas: "matific",
  pontuacao_media: "matific",
  livros_unicos: "elefante",
  tempo_leitura_min: "elefante",
  questoes_tentativas: "elefante",
  questoes_acertos: "elefante",
};

/** Cores das séries por plataforma (identidade v2): Elefante violeta, Matific verde-azulado. */
const COR_ELEFANTE = "#6C5CE7";
const COR_MATIFIC = "#0D9488";

/** "31/10" no fuso de Brasília (a API manda UTC sem marca de fuso). */
function dataCurta(iso: string): string {
  return dataDia(iso, true);
}

/** Abaixo desta largura de contêiner (celular: ~280–335 px), o mini-gráfico desenha na
 *  largura real (1:1) e o texto sai no tamanho nominal — com o viewBox de 500 reduzido a
 *  ~270 px, eixos, datas e valores caíam para ~6 px. O menor contêiner no tablet e no
 *  desktop é ~424 px (duas colunas a partir de 1024 px): ali, o desenho de sempre. */
const LARGURA_CELULAR = 400;

/** Um mini-gráfico por indicador; mede o próprio contêiner para o celular. */
function MiniGrafico({ nome, serieDoGrafico, rotulo }: { nome: string; serieDoGrafico: SerieLinha; rotulo: string }) {
  const { ref, largura } = useLarguraDoConteiner();
  const celular = largura > 0 && largura < LARGURA_CELULAR;
  return (
    <div className="rounded-2xl bg-zinc-50/70 p-3 dark:bg-zinc-800/30">
      <p className="mb-1 text-xs font-semibold text-zinc-700 dark:text-zinc-200">{nome}</p>
      <div ref={ref}>
        <GraficoLinha series={[serieDoGrafico]} altura={185} rotulo={rotulo}
                      larguraViewBox={celular ? largura : undefined} />
      </div>
    </div>
  );
}

/** Série de UM indicador. Ponto sem o valor vira LACUNA na linha (null), nunca 0:
 *  desenhar uma queda a zero onde não houve coleta seria inventar um dado. */
function serie(pontos: PontoLinha[], campo: string, nome: string, cor: string): SerieLinha {
  return {
    nome,
    cor,
    pontos: pontos.map((ponto) => {
      const bruto = ponto[campo];
      const valor = bruto == null || bruto === "" ? null : Number(bruto);
      return { rotulo: dataCurta(ponto.data), valor: valor != null && Number.isFinite(valor) ? valor : null };
    }),
  };
}

export default function EvolucaoAluno() {
  const { id } = useParams();
  const { escolaId } = useApp();
  const [dias, setDias] = useState(30);
  const { dados: dadosEvolucao, erro, carregando, recarregar } = useApi<EvolucaoResposta>(
    escolaId && id ? `/escolas/${escolaId}/alunos/${id}/evolucao?dias=${dias}` : null,
  );

  if (carregando) {
    return (
      <div role="status" className="space-y-6">
        <span className="sr-only">Carregando...</span>
        <Skeleton className="h-8 w-72 max-w-full" />
        <div className="grid grid-cols-2 gap-3 sm:gap-5 lg:grid-cols-4">
          {[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-28 rounded-cartao" />)}
        </div>
        <Skeleton className="h-72 rounded-cartao" />
      </div>
    );
  }
  if (erro) {
    return (
      <Card>
        <Erro descricao={erro.message} aoTentar={recarregar} />
      </Card>
    );
  }
  if (!dadosEvolucao) {
    return (
      <Card>
        <Vazio icone={LineChart} titulo="Aluno não encontrado"
               descricao="Volte à lista de alunos e abra o perfil de novo." />
      </Card>
    );
  }

  const { linha_do_tempo: linha, resumo } = dadosEvolucao;

  // Primeira data COM dado (nas duas plataformas). Se o período escolhido vai
  // mais para trás do que o 1º registro, avisamos: não há histórico anterior —
  // é quando o Constela começou a coletar este aluno (não um bug do gráfico).
  const datas = [...linha.matific, ...linha.elefante]
    .map((ponto) => paraData(ponto.data).getTime())
    .filter((t) => !Number.isNaN(t))
    .sort((a, b) => a - b);
  const primeira = datas[0];
  const faltaHistorico =
    primeira != null && primeira - (Date.now() - dias * 864e5) > 2 * 864e5;
  const primeiraFmt =
    primeira != null ? dataDia(new Date(primeira).toISOString()) : "";

  // Valor do INÍCIO do período. Sem coleta anterior ao início, o backend manda
  // `inicial` = 0 — um zero que ninguém mediu. A API não diz se houve essa coleta;
  // o que dá para PROVAR: se algum indicador da plataforma tem `inicial` diferente
  // de zero, houve uma coleta antes do início (e os zeros dela são medidos). Sem
  // essa prova, a tela não afirma o valor inicial nem mostra a variação.
  const baseComprovada = (plataforma: string | undefined) =>
    plataforma != null &&
    resumo.indicadores.some(
      (i) => PLATAFORMA_DO_INDICADOR[i.indicador] === plataforma && i.inicial !== 0);
  const algumaBase = baseComprovada("matific") || baseComprovada("elefante");
  /** Primeira coleta DENTRO do período, por plataforma (a linha do tempo já vem recortada). */
  const primeiraNoPeriodo = (plataforma: string | undefined): string | null => {
    const pontos = plataforma === "matific" ? linha.matific : plataforma === "elefante" ? linha.elefante : [];
    const tempos = pontos
      .map((ponto) => paraData(ponto.data).getTime())
      .filter((t) => !Number.isNaN(t));
    return tempos.length ? dataCurta(new Date(Math.min(...tempos)).toISOString()) : null;
  };

  return (
    <div className="space-y-6">
      <Link
        to={`/alunos/${id}`}
        className="inline-flex items-center gap-1.5 text-sm font-medium text-zinc-500 transition-colors hover:text-indigo-600 dark:text-zinc-400 dark:hover:text-indigo-300"
      >
        <ArrowLeft size={15} aria-hidden /> Perfil de {dadosEvolucao.nome}
      </Link>
      <PageHeader
        titulo={`Evolução — ${dadosEvolucao.nome}`}
        descricao="Como os números do aluno mudaram no período. Cada coleta das plataformas vira um novo ponto na linha do tempo — o histórico não é reescrito."
        acoes={
          <SelectNativo
            aria-label="Período da evolução"
            className="w-48"
            value={dias}
            onChange={(evento) => setDias(Number(evento.target.value))}
          >
            <option value={7}>Últimos 7 dias</option>
            <option value={30}>Últimos 30 dias</option>
            <option value={90}>Últimos 90 dias</option>
            <option value={365}>Ano inteiro</option>
          </SelectNativo>
        }
      />

      {/* Com coleta comprovada antes do início do período, "não há histórico
          anterior" seria falso: o aviso só aparece sem essa prova. */}
      {faltaHistorico && !algumaBase && (
        <div className="flex items-start gap-3 rounded-2xl border border-indigo-100 bg-indigo-50/70 px-4 py-3 text-sm text-indigo-900 dark:border-indigo-500/30 dark:bg-indigo-500/10 dark:text-indigo-100">
          <CalendarClock size={18} aria-hidden className="mt-0.5 shrink-0 text-indigo-600 dark:text-indigo-300" />
          <p>
            Este aluno tem dados a partir de <b>{primeiraFmt}</b> — foi quando o Constela
            começou a registrar a evolução dele. Não há histórico anterior a essa data
            para exibir; a linha do tempo cresce a cada sincronização.
          </p>
        </div>
      )}

      <section aria-labelledby="titulo-variacao">
        <h2 id="titulo-variacao" className="mb-3 text-base font-semibold tracking-tight">
          Variação no período ({resumo.dias} dias)
        </h2>
        {resumo.indicadores.length === 0 ? (
          <Card>
            <Vazio icone={LineChart} titulo="Sem coletas no período"
                   descricao="Escolha um período maior ou aguarde a próxima sincronização." />
          </Card>
        ) : (
          // Dois cartões por linha já no celular (antes, um por linha: os 7 ocupavam ~1.150 px
          // antes dos gráficos); com número ímpar, o último ocupa a linha inteira no celular.
          <div
            className="grid grid-cols-2 gap-3 sm:gap-5 xl:grid-cols-4 max-sm:[&>*:last-child:nth-child(odd)]:col-span-2"
            data-testid="variacao-no-periodo"
          >
            {resumo.indicadores.map((item) => {
              const sentido = item.variacao > 0 ? "sobe" : item.variacao < 0 ? "desce" : "igual";
              const plataforma = PLATAFORMA_DO_INDICADOR[item.indicador];
              // Indicador fora do mapa: só o próprio `inicial` pode provar a base.
              const comBase = plataforma ? baseComprovada(plataforma) : item.inicial !== 0;
              const primeiraColeta = primeiraNoPeriodo(plataforma);
              // Sem base comprovada e sem coleta no período, o "0" do backend pode não
              // ter sido medido: "—" (sem dado), nunca um 0,0 afirmado.
              const semDado = !comBase && !primeiraColeta && item.atual === 0;
              return (
                // A pílula fica sempre na mesma posição (abaixo do número): antes ela
                // dividia a linha com o título e, nos rótulos longos, descia e
                // desalinhava os números da mesma fileira.
                <Card key={item.indicador} className="flex flex-col p-4 sm:p-5">
                  <p className="text-sm font-medium text-zinc-700 dark:text-zinc-200">
                    {ROTULOS[item.indicador] ?? item.indicador}
                  </p>
                  <p className="mt-3 text-[28px] font-bold leading-none tracking-tight tabular-nums text-zinc-900 dark:text-white">
                    {semDado ? "—" : nota(item.atual)}
                  </p>
                  <div className="mt-2.5 flex flex-wrap items-center gap-x-2 gap-y-1.5">
                    {comBase && (
                      <Variacao sentido={sentido} descricao={`desde o início do período (${nota(item.inicial)})`}>
                        {nota(Math.abs(item.variacao))}
                        {item.percentual !== null && ` (${item.percentual > 0 ? "+" : ""}${item.percentual}%)`}
                      </Variacao>
                    )}
                    <p className="text-xs tabular-nums text-zinc-500 dark:text-zinc-400">
                      {comBase
                        ? `era ${nota(item.inicial)} no início do período`
                        : primeiraColeta
                          ? `sem valor confirmado no início do período (primeira coleta do período em ${primeiraColeta})`
                          : "sem coleta no período"}
                    </p>
                  </div>
                </Card>
              );
            })}
          </div>
        )}
      </section>

      <Card className="p-5">
        <div className="mb-4 flex items-center gap-3">
          <IconePastel icone={Calculator} tom="teal" />
          <div>
            <h2 className="text-base font-semibold tracking-tight">Matific ao longo do tempo</h2>
            <p className="text-xs text-zinc-500 dark:text-zinc-400">
              Um gráfico por indicador — cada um na sua própria escala, com os valores marcados.
            </p>
          </div>
        </div>
        {/* O SVG escala com a largura: em 2 colunas abaixo de 1024 px cada gráfico
            ficava com ~320 px e os números do eixo caíam para ~7 px. Abaixo disso,
            um gráfico por linha. */}
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          {([
            ["atividades", "Atividades"],
            ["estrelas", "Estrelas"],
            ["pontuacao_media", "Pontuação média"],
          ] as const).map(([campo, nome]) => (
            <MiniGrafico key={campo} nome={nome} serieDoGrafico={serie(linha.matific, campo, nome, COR_MATIFIC)}
                         rotulo={`Matific: ${nome} ao longo do tempo`} />
          ))}
        </div>
      </Card>

      <Card className="p-5">
        <div className="mb-4 flex items-center gap-3">
          <IconePastel icone={BookOpen} tom="violeta" />
          <div>
            <h2 className="text-base font-semibold tracking-tight">Elefante Letrado ao longo do tempo</h2>
            <p className="text-xs text-zinc-500 dark:text-zinc-400">
              Um gráfico por indicador — cada um na sua própria escala, com os valores marcados.
            </p>
          </div>
        </div>
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          {([
            ["livros_unicos", "Livros únicos"],
            ["questoes_acertos", "Acertos"],
            ["tempo_leitura_min", "Tempo (min)"],
          ] as const).map(([campo, nome]) => (
            <MiniGrafico key={campo} nome={nome} serieDoGrafico={serie(linha.elefante, campo, nome, COR_ELEFANTE)}
                         rotulo={`Elefante Letrado: ${nome} ao longo do tempo`} />
          ))}
        </div>
      </Card>
    </div>
  );
}
