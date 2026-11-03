/**
 * Comparação entre escolas nas AVALIAÇÕES EXTERNAS — a tabela reutilizável
 * (`TabelaComparacaoEscolas`): uma coluna por série oficial (avaliação × etapa × componente),
 * cada uma numa edição SÓ — a de referência, a mais recente com resultado entre as escolas
 * mostradas. Por escola: valor + edição, ▲/=/▼ contra a rede municipal na MESMA edição
 * (calculado pelo Constela, com tolerância), a situação da meta OFICIAL e a tendência desde a
 * edição anterior. Escolas em ordem alfabética — não é ranking.
 *
 * Mora na tela Avaliações externas (`/rede/avaliacoes-externas`, seção "Todas as escolas na
 * edição mais recente de cada avaliação"), o fluxo principal da Secretaria: por isso fala a
 * língua simples do desenho — "média instável (poucos alunos fizeram a prova)", nunca a sigla
 * técnica; os motivos que o servidor escreve com termo técnico passam por `textoSimples`.
 *
 * A CÉLULA FICA CURTA (o pedido do dono: clareza): valor e edição, ▲/=/▼ com a diferença, meta e
 * situação, a tendência, o selo "média instável". O porquê de faltar a posição ou a tendência não
 * se repete em cada célula: a célula diz "sem comparação com a rede (obs. 1)" ou "sem tendência
 * (obs. 2)" e o texto do servidor fica UMA vez nas "Observações da tabela", sob ela; o porquê que vale
 * para a coluna toda (o IEE, que não tem número da rede) fica no cabeçalho da coluna; a primeira
 * edição não escreve nada na célula (a nota diz o que é a célula sem linha de tendência). A
 * ausência continua por extenso na célula.
 *
 * NÃO MISTURA edições: a escola cujo último resultado da série é de uma edição ANTERIOR à de
 * referência não mostra o valor, a posição, a meta nem a tendência na coluna — a célula diz por
 * extenso "sem resultado em {referência} — o último oficial desta escola é de {edição} (na ficha
 * da escola)". A conclusão da seção (`conclusaoComparacaoAvaliacoes`) conta só a edição de
 * referência de cada série, com `colunasDaComparacao` e `oficiaisNaReferencia` daqui. Com
 * `linkDaEscola`, o nome da escola leva à ficha dela; a escola inativa no cadastro continua
 * listada, com o selo "inativa no cadastro". Sem número oficial em escola nenhuma, a frase diz
 * por quê (o motivo que o catálogo dá a cada avaliação) e as escolas continuam listadas, cada uma
 * com o que falta.
 *
 * (Era a parte de cima da aba antiga "Avaliações externas" da análise, `?ver=avaliacoes`, e
 * depois a aba "Avaliações externas" do Comparar escolas: os sinais de atenção foram para
 * Escolas em acompanhamento.)
 */
import { Link } from "react-router-dom";

import { TabelaRolavel } from "../../components/TabelaRolavel";
import { Badge } from "../../components/ui";
import DetalhesEFontes from "./DetalhesFonte";
import { PosicaoNaRede, SeloNatureza, SituacaoDaMeta, TD, TH, ValorOficial } from "./comum";
import {
  ROTULO_TENDENCIA, diferencaComUnidade, porNome, temPendencia, textoIndisponivel, textoTolerancias, valorComUnidade,
} from "./formato";
import type { IndicadorAnalise, RespostaIndicadoresRede } from "./tipos";
import type { EscolaDiagnostico, OficialDiagnostico, RespostaDiagnostico } from "./tiposDiagnostico";
import { textoSimples } from "../rede/secretaria/oQueMede";

const CINZA = "text-zinc-600 dark:text-zinc-400";
const PRESA = "presa-esquerda-celular"; // index.css: a coluna da escola fica presa no celular

// --- As colunas: uma por série oficial (indicador × etapa × componente) ------------------

const ORDEM_INDICADOR = ["iee", "ideb", "saresp", "saeb"];
const ORDEM_ETAPA = ["anos_iniciais", "5_ano", "2_ano"];
const ORDEM_COMPONENTE = ["lp", "mt"];
const ETAPA_CURTA: Record<string, string> = { "2_ano": "2º ano", "5_ano": "5º ano", anos_iniciais: "anos iniciais" };
const COMPONENTE_CURTO: Record<string, { sigla: string; nome: string }> = {
  lp: { sigla: "LP", nome: "Língua Portuguesa" },
  mt: { sigla: "MT", nome: "Matemática" },
};

export interface ColunaDaComparacao {
  chave: string;
  indicador: string;
  etapa: string | null;
  componente: string | null;
  /** A edição de REFERÊNCIA da coluna: a mais recente com resultado entre as escolas mostradas. */
  edicao: number;
}
type Coluna = ColunaDaComparacao;

type ComSerie = Pick<OficialDiagnostico, "indicador" | "etapa" | "componente">;
const chaveSerie = (o: ComSerie) => `${o.indicador}|${o.etapa ?? ""}|${o.componente ?? ""}`;
const posicaoEm = (lista: string[], v: string | null) => {
  const i = v == null ? -1 : lista.indexOf(v);
  return i < 0 ? lista.length : i;
};

/** As colunas que ALGUMA escola tem, na ordem de leitura (IEE, Ideb, SARESP, Saeb), cada uma
 *  com a sua edição de referência — a mais recente com resultado oficial entre estas escolas. */
export function colunasDaComparacao(escolas: EscolaDiagnostico[]): ColunaDaComparacao[] {
  const mapa = new Map<string, Coluna>();
  for (const e of escolas) {
    for (const o of e.oficiais) {
      const chave = chaveSerie(o);
      const coluna = mapa.get(chave);
      if (!coluna) {
        mapa.set(chave, { chave, indicador: o.indicador, etapa: o.etapa, componente: o.componente, edicao: o.edicao });
      } else if (o.edicao > coluna.edicao) {
        coluna.edicao = o.edicao;
      }
    }
  }
  return [...mapa.values()].sort((a, b) =>
    posicaoEm(ORDEM_INDICADOR, a.indicador) - posicaoEm(ORDEM_INDICADOR, b.indicador)
    || posicaoEm(ORDEM_ETAPA, a.etapa) - posicaoEm(ORDEM_ETAPA, b.etapa)
    || posicaoEm(ORDEM_COMPONENTE, a.componente) - posicaoEm(ORDEM_COMPONENTE, b.componente)
    || a.chave.localeCompare(b.chave));
}

/** Os resultados da escola que estão na edição de referência da coluna deles. Os de edição
 *  ANTERIOR ficam de fora (não se misturam com os da edição mais recente): moram na ficha. */
export function oficiaisNaReferencia(e: EscolaDiagnostico, colunas: ColunaDaComparacao[]): OficialDiagnostico[] {
  const referencia = new Map(colunas.map((c) => [c.chave, c.edicao]));
  return e.oficiais.filter((o) => o.edicao === referencia.get(chaveSerie(o)));
}

/** Os indicadores que aparecem como coluna (na ordem da tabela) — a legenda de cada coluna. */
export function indicadoresNaComparacao(dados: RespostaDiagnostico): string[] {
  return [...new Set(colunasDaComparacao(dados.escolas).map((c) => c.indicador))];
}

/** O nome CURTO no cabeçalho (o do catálogo pode ser longo: "Índice de Excelência…"). */
const NOME_CURTO: Record<string, string> = { iee: "IEE", ideb: "Ideb", saresp: "SARESP", saeb: "Saeb" };
function nomeIndicador(chave: string, base: RespostaIndicadoresRede): string {
  return NOME_CURTO[chave] ?? base.indicadores.find((i) => i.chave === chave)?.nome ?? chave.toUpperCase();
}

/** "SARESP 5º ano · LP" (a sigla com o nome por extenso para o leitor de tela). */
function CabecalhoColuna({ c, base }: { c: Coluna; base: RespostaIndicadoresRede }) {
  const comp = c.componente ? COMPONENTE_CURTO[c.componente] : null;
  // IEE e Ideb são sempre dos anos iniciais (a escola inteira): o nome basta.
  const etapa = c.etapa && c.etapa !== "anos_iniciais" ? ETAPA_CURTA[c.etapa] ?? c.etapa.replace(/_/g, " ") : null;
  return (
    <>
      {nomeIndicador(c.indicador, base)}
      {etapa && <> {etapa}</>}
      {comp && <> · <abbr title={comp.nome} className="no-underline">{comp.sigla}</abbr></>}
    </>
  );
}

const unidadeDe = (chave: string, base: RespostaIndicadoresRede) =>
  base.indicadores.find((i) => i.chave === chave)?.unidade ?? null;

// --- As notas da tabela: cada explicação longa UMA vez, sob a tabela ------------------------
//
// O porquê de faltar a posição ou a tendência vinha por extenso em CADA célula ("o IEE é um
// índice por escola: …" em todas as escolas, "sem tendência: primeira edição …" em quase todas).
// Agora a célula diz só o essencial curto — "sem comparação com a rede (obs. 1)", "sem tendência
// (obs. 2)" — e o texto do servidor (em língua simples) fica UMA vez nas "Observações da tabela". O
// porquê que vale para a COLUNA toda (o IEE, que não tem número da rede; a rede sem resultado
// na edição) sobe para o cabeçalho dela. A primeira edição não escreve nada na célula: a nota
// diz, uma vez, o que quer dizer a célula sem linha de tendência. Nada some: só deixa de repetir.

/** "Primeira edição com número oficial: não há anterior para comparar" (o texto do servidor). */
const PRIMEIRA_EDICAO = /^primeira edi[çc][ãa]o/i;

/** O que falta na célula, em curto, com o número da nota que diz o porquê (null: sem porquê). */
interface FaltaNaCelula {
  rotulo: string;
  nota: number | null;
}

interface PlanoDaCelula {
  /** Sem posição contra a rede (e o porquê não é o do cabeçalho da coluna). */
  posicao: FaltaNaCelula | null;
  /** Sem tendência por um porquê próprio (não a primeira edição nem o mesmo da posição). */
  tendencia: FaltaNaCelula | null;
}

interface NotasDaTabela {
  /** As explicações longas, cada uma UMA vez, na ordem de leitura (nota N = textos[N − 1]). */
  textos: string[];
  /** A nota no cabeçalho da coluna cujo porquê de "sem comparação" vale para a coluna toda. */
  daColuna: Map<string, number>;
  /** Por célula (`escola|coluna`): o que ela diz, em curto, quando falta a posição ou a tendência. */
  celulas: Map<string, PlanoDaCelula>;
  /** Os textos de primeira edição (a célula fica sem linha de tendência). */
  primeiraEdicao: string[];
}

const resultadoNaColuna = (e: EscolaDiagnostico, c: Coluna) => e.oficiais.find((x) => chaveSerie(x) === c.chave);

/** O porquê de "sem comparação com a rede" que vale para a COLUNA toda: todas as escolas dela na
 *  edição de referência sem posição e com o MESMO porquê — o IEE (não existe número da rede), a
 *  rede sem resultado nessa edição. A média instável fica de fora da conta: ela é da escola, não
 *  da coluna (e uma coluna só de médias instáveis não sobe nada para o cabeçalho). */
function motivoDaColuna(naReferencia: OficialDiagnostico[]): string | null {
  const estaveis = naReferencia.filter((o) => !o.instavel);
  if (estaveis.length === 0 || estaveis.some((o) => o.posicao_rede)) return null;
  const motivos = new Set(estaveis.map((o) => textoSimples(o.motivo_sem_comparacao)));
  const [motivo] = motivos;
  return motivos.size === 1 && motivo ? motivo : null;
}

/** As notas da tabela e o que cada célula diz, na ordem de leitura (os cabeçalhos, depois as
 *  escolas linha a linha): o mesmo texto ganha sempre o mesmo número. */
function notasDaTabela(escolas: EscolaDiagnostico[], colunas: Coluna[]): NotasDaTabela {
  const textos: string[] = [];
  const numero = (texto: string) => {
    const i = textos.indexOf(texto);
    if (i >= 0) return i + 1;
    textos.push(texto);
    return textos.length;
  };
  const daColuna = new Map<string, number>();
  for (const c of colunas) {
    const naReferencia = escolas.map((e) => resultadoNaColuna(e, c))
      .filter((o): o is OficialDiagnostico => o != null && o.edicao === c.edicao);
    const motivo = motivoDaColuna(naReferencia);
    if (motivo) daColuna.set(c.chave, numero(motivo));
  }
  const celulas = new Map<string, PlanoDaCelula>();
  const primeiraEdicao: string[] = [];
  for (const e of escolas) {
    for (const c of colunas) {
      const o = resultadoNaColuna(e, c);
      if (!o || o.edicao !== c.edicao) continue;               // ausência ou edição anterior: por extenso
      const motivoPosicao = textoSimples(o.motivo_sem_comparacao);
      const notaDaColuna = daColuna.get(c.chave);
      const noCabecalho = notaDaColuna != null && motivoPosicao === textos[notaDaColuna - 1];
      let posicao: FaltaNaCelula | null = o.posicao_rede || noCabecalho ? null
        : { rotulo: "sem comparação com a rede", nota: motivoPosicao ? numero(motivoPosicao) : null };
      let tendencia: FaltaNaCelula | null = null;
      const motivoTendencia = textoSimples(o.motivo_sem_tendencia);
      if (!(o.tendencia && o.anterior) && motivoTendencia) {
        if (o.motivo_sem_tendencia === o.motivo_sem_comparacao) {
          // O MESMO porquê da posição (a média instável): uma linha, a mesma nota.
          if (posicao) posicao = { ...posicao, rotulo: "sem comparação com a rede nem tendência" };
        } else if (PRIMEIRA_EDICAO.test(motivoTendencia)) {
          if (!primeiraEdicao.includes(motivoTendencia)) primeiraEdicao.push(motivoTendencia);
        } else {
          tendencia = { rotulo: "sem tendência", nota: numero(motivoTendencia) };
        }
      }
      celulas.set(`${e.id}|${c.chave}`, { posicao, tendencia });
    }
  }
  return { textos, daColuna, celulas, primeiraEdicao };
}

/** "(obs. 2)": o porquê está, uma vez, nas observações sob a tabela. */
function RefNota({ n }: { n: number }) {
  return <span className="whitespace-nowrap font-semibold" data-ref-nota={n}>(obs. {n})</span>;
}

/** "sem comparação com a rede (obs. 1)" — o que falta, em curto, e onde está o porquê. */
function TextoDaFalta({ falta }: { falta: FaltaNaCelula }) {
  return <>{falta.rotulo}{falta.nota != null && <> <RefNota n={falta.nota} /></>}</>;
}

const comPonto = (t: string) => (/[.!?]$/.test(t) ? t : `${t}.`);

/** As notas sob a tabela: cada explicação longa uma vez, com o número que as células citam. */
function NotasSobATabela({ notas }: { notas: NotasDaTabela }) {
  if (notas.textos.length === 0 && notas.primeiraEdicao.length === 0) return null;
  return (
    <div className="space-y-1" data-testid="notas-comparacao">
      <p className="font-semibold text-zinc-700 dark:text-zinc-200">Observações da tabela</p>
      <ul className="space-y-0.5">
        {notas.textos.map((t, i) => (
          <li key={`nota-${i + 1}`} data-nota={i + 1}>
            <span className="font-semibold">Obs. {i + 1}</span> — {comPonto(t)}
          </li>
        ))}
        {notas.primeiraEdicao.map((t) => (
          <li key={`primeira-${t}`} data-nota-primeira-edicao>Célula sem linha de tendência — {comPonto(t)}</li>
        ))}
      </ul>
    </div>
  );
}

/** Uma célula: o número oficial e a edição; a posição (calculada) ou "sem comparação com a rede"
 *  com a nota do porquê; a meta oficial; a tendência desde a edição anterior ou "sem tendência"
 *  com a nota. Resultado de edição ANTERIOR à de referência da coluna: nada disso — só a ausência
 *  por extenso, com o ano do último oficial da escola (as edições não se misturam na coluna). */
function CelulaOficial({ o, unidade, referencia, plano }: {
  o: OficialDiagnostico;
  unidade: string | null;
  /** A edição de referência desta coluna (a mais recente com resultado entre as escolas). */
  referencia: number;
  /** O que a célula diz, em curto, quando falta a posição ou a tendência (`notasDaTabela`). */
  plano?: PlanoDaCelula;
}) {
  if (o.edicao < referencia) {
    return (
      <div className="min-w-[9.5rem]" data-edicao-anterior>
        <ValorOficial valor={null} casas={null}
                      texto_ausencia={`sem resultado em ${referencia} — o último oficial desta escola é de ${o.edicao} `
                        + "(na ficha da escola)"} />
      </div>
    );
  }
  // Cada número na precisão publicada dele: a rede na dela, a diferença na menor das duas.
  const rede = o.valor_rede == null ? null : valorComUnidade(o.valor_rede, o.casas_rede ?? o.casas, unidade);
  const detalhe = rede == null ? null
    : o.diferenca_rede == null
      ? `(rede ${rede})`
      : `(${diferencaComUnidade(o.diferenca_rede, o.casas_diferenca ?? o.casas, unidade)}; rede ${rede})`;
  return (
    <div className="min-w-[9.5rem] space-y-1">
      <p className="flex flex-wrap items-center gap-1.5">
        <span className="text-sm font-semibold tabular-nums text-zinc-900 dark:text-white">
          {valorComUnidade(o.valor, o.casas, unidade)}
        </span>
        <span className="rounded-md bg-zinc-100 px-1.5 py-0.5 text-[11px] font-semibold text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">
          {o.edicao}
        </span>
        {o.instavel
          ? <Badge tom="alerta">média instável</Badge>
          // IEE calculado com médias de TPS = 0 (poucos alunos fizeram a prova): o número vale,
          // mas não gera tendência. No fluxo principal, sem a sigla técnica.
          : o.tps_zero && <Badge tom="alerta">calculado com médias instáveis</Badge>}
      </p>
      {o.posicao_rede
        ? <PosicaoNaRede posicao={o.posicao_rede} detalhe={detalhe} />
        : plano?.posicao && (
          // O porquê fica nas notas (ou no cabeçalho, quando vale para a coluna toda).
          <p className={`text-[11px] leading-tight ${CINZA}`} data-sem-comparacao>
            <TextoDaFalta falta={plano.posicao} />
          </p>
        )}
      {o.situacao_meta && (
        <p className="flex flex-wrap items-center gap-1 text-[11px] text-zinc-600 dark:text-zinc-300">
          {o.meta != null && <span>meta {valorComUnidade(o.meta, o.meta_casas ?? o.casas, unidade)}</span>}
          <SituacaoDaMeta situacao={o.situacao_meta} diferenca={null} casas={o.casas} />
        </p>
      )}
      {o.tendencia && o.anterior ? (
        <p className={`text-[11px] ${CINZA}`}>
          {ROTULO_TENDENCIA[o.tendencia]} desde {o.anterior.edicao} ({valorComUnidade(o.anterior.valor, o.anterior.casas ?? o.casas, unidade)})
        </p>
      ) : plano?.tendencia && (
        // Sem tendência por um porquê próprio (quebra de escala, a edição anterior instável…):
        // ele fica nas notas. A primeira edição não escreve nada (a nota diz o que é).
        <p className={`text-[11px] leading-tight ${CINZA}`} data-sem-tendencia>
          <TextoDaFalta falta={plano.tendencia} />
        </p>
      )}
    </div>
  );
}

/** As tolerâncias que valem para os números OFICIAIS (as das plataformas ficam no diagnóstico). */
function toleranciasOficiais(t: Record<string, number | string> | undefined) {
  return textoTolerancias(Object.fromEntries(Object.entries(t ?? {}).filter(([k]) => /ideb|iee|saresp|saeb/.test(k))));
}

/** O nome da escola: com `linkDaEscola`, o link para a ficha dela; sem ele, o texto. */
function NomeDaEscola({ e, linkDaEscola }: { e: EscolaDiagnostico; linkDaEscola?: (escolaId: number) => string }) {
  if (!linkDaEscola) return <span className="break-words">{e.nome}</span>;
  return (
    <Link to={linkDaEscola(e.id)}
          className="break-words font-medium text-indigo-700 underline-offset-2 hover:underline dark:text-indigo-300">
      {e.nome}
    </Link>
  );
}

const semCodigoInep = (e: EscolaDiagnostico) => temPendencia(e.pendencias, "sem_codigo_inep") || !e.codigo_inep;

/** Escola INATIVA no cadastro (o diagnóstico manda o `status` de cada escola). Ela continua na
 *  lista — são todas as escolas da rede —, mas com o selo, para não passar por uma escola em
 *  funcionamento. Sem `status` (resposta mais antiga), nada é marcado. */
const inativaNoCadastro = (e: EscolaDiagnostico) => e.status != null && e.status !== "ativa";

function SeloInativa() {
  return <span data-escola-inativa><Badge tom="neutro">inativa no cadastro</Badge></span>;
}

const porOrdemDeLeitura = (a: { chave: string }, b: { chave: string }) =>
  posicaoEm(ORDEM_INDICADOR, a.chave) - posicaoEm(ORDEM_INDICADOR, b.chave);

/** O que o catálogo diz de cada avaliação por escola, para a rede sem número oficial em escola
 *  nenhuma: a importada (com número só fora das escolas) e o motivo de cada indisponível, como o
 *  catálogo o escreve, em linguagem simples. */
function motivoDaAvaliacao(i: IndicadorAnalise): string {
  return i.disponivel
    ? "os arquivos importados não trazem número oficial de nenhuma escola da rede"
    : textoSimples(textoIndisponivel(i));
}

/**
 * Nenhuma escola com número oficial: a frase diz por quê e TODAS as escolas continuam listadas,
 * cada uma com o que falta — nunca uma tabela vazia nem escolas sumidas. O porquê vem do catálogo:
 * nenhuma avaliação por escola importada, ou as importadas não trazem número destas escolas; se
 * alguma está indisponível por OUTRO motivo (só números gravados antes, sem o registro do arquivo;
 * só a Estimativa Constela; rede sem código IBGE), uma linha por avaliação com o motivo dela —
 * nunca "nada foi importado" quando o motivo é outro.
 */
function SemResultadoOficial({ escolas, base, linkDaEscola }: {
  escolas: EscolaDiagnostico[];
  base: RespostaIndicadoresRede;
  linkDaEscola?: (escolaId: number) => string;
}) {
  if (escolas.length === 0) {
    return <p className={`text-sm ${CINZA}`} data-testid="comparacao-vazia">A rede não tem escolas cadastradas.</p>;
  }
  const porEscola = base.indicadores.filter((i) => i.por_escola).sort(porOrdemDeLeitura);
  const outroMotivo = porEscola.some((i) =>
    !i.disponivel && i.motivo_indisponivel != null && i.motivo_indisponivel !== "sem_importacao");
  const importadas = porEscola.filter((i) => i.disponivel).map((i) => nomeIndicador(i.chave, base));
  const porque = importadas.length === 0
    ? "nenhuma avaliação com resultado por escola (IEE, Ideb, SARESP ou Saeb) foi importada para esta rede."
    : `as avaliações importadas (${importadas.join(", ")}) não trazem número oficial de nenhuma escola da rede.`;
  return (
    <div className="space-y-3" data-testid="comparacao-vazia">
      {outroMotivo ? (
        <>
          <p className="text-sm text-zinc-700 dark:text-zinc-200">
            Nenhuma escola da rede tem resultado oficial importado ainda. Sem número oficial não há o que comparar. O
            que falta em cada avaliação com resultado por escola:
          </p>
          <ul className="list-disc space-y-1 pl-5 text-sm text-zinc-700 dark:text-zinc-200"
              data-testid="motivos-sem-resultado">
            {porEscola.map((i) => (
              <li key={i.chave}>
                <span className="font-semibold">{nomeIndicador(i.chave, base)}</span>: {motivoDaAvaliacao(i)}.
              </li>
            ))}
          </ul>
          <p className="text-sm text-zinc-700 dark:text-zinc-200">Abaixo, todas as escolas, cada uma com o que falta.</p>
        </>
      ) : (
        <p className="text-sm text-zinc-700 dark:text-zinc-200">
          Nenhuma escola da rede tem resultado oficial importado ainda: {porque} Sem número oficial não há o que
          comparar. Abaixo, todas as escolas, cada uma com o que falta.
        </p>
      )}
      <ul className="divide-y divide-zinc-100 rounded-xl border border-zinc-200/70 dark:divide-zinc-800/60 dark:border-zinc-800"
          data-testid="escolas-sem-resultado">
        {escolas.map((e) => (
          <li key={e.id} className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5 px-3 py-2 text-sm">
            <span className="min-w-0">
              <NomeDaEscola e={e} linkDaEscola={linkDaEscola} />
              {inativaNoCadastro(e) && <> <SeloInativa /></>}
            </span>
            <span className={`text-xs ${CINZA}`}>
              {semCodigoInep(e) ? "sem código INEP no cadastro" : "sem resultado oficial importado"}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * A tabela de comparação entre escolas, com a legenda e "Detalhes e fontes": uma coluna por
 * série oficial que ALGUMA escola tem, na edição de referência dela; sem número nessa edição, a
 * ausência por extenso (nunca 0). Com `linkDaEscola` (o caminho da ficha, com o `?rede=` do
 * global), o nome da escola é um link.
 */
export function TabelaComparacaoEscolas({ dados, base, linkDaEscola }: {
  dados: RespostaDiagnostico;
  base: RespostaIndicadoresRede;
  linkDaEscola?: (escolaId: number) => string;
}) {
  const escolas = porNome(dados.escolas);
  const colunas = colunasDaComparacao(escolas);
  if (colunas.length === 0) return <SemResultadoOficial escolas={escolas} base={base} linkDaEscola={linkDaEscola} />;
  const tolerancias = toleranciasOficiais(dados.criterios?.tolerancias);
  const notas = notasDaTabela(escolas, colunas);
  // A fonte só dos números que a tabela mostra (os de edição anterior ficam na ficha da escola).
  const itensFonte = escolas.flatMap((e) => oficiaisNaReferencia(e, colunas).map((o) => ({
    rotulo: `${e.nome} — ${nomeIndicador(o.indicador, base)}${o.etapa && o.etapa !== "anos_iniciais"
      ? ` ${ETAPA_CURTA[o.etapa] ?? o.etapa}` : ""}`
      + `${o.componente ? ` ${COMPONENTE_CURTO[o.componente]?.sigla ?? o.componente}` : ""} (${o.edicao})`,
    fonte_id: o.fonte_id,
  })));
  return (
    <div className="space-y-3">
      <TabelaRolavel rotulo="Comparação entre escolas: tabela completa">
        <table className="w-full text-xs" data-testid="tabela-comparacao-escolas">
          <caption className="sr-only">
            Cada avaliação na edição mais recente com resultado entre as escolas, por escola (ordem alfabética), com a
            posição contra a rede municipal na mesma edição, a meta oficial e a tendência; a escola sem resultado
            nessa edição diz o ano do último oficial dela; o porquê de faltar a posição ou a tendência está nas
            notas sob a tabela
          </caption>
          <thead>
            <tr className={`border-b border-zinc-200 align-bottom dark:border-zinc-800 ${CINZA}`}>
              <th className={`${TH} ${PRESA}`} scope="col">Escola</th>
              {colunas.map((c) => {
                const nota = notas.daColuna.get(c.chave);
                return (
                  <th key={c.chave} className={TH} scope="col">
                    <span data-nome-coluna><CabecalhoColuna c={c} base={base} /></span>
                    {nota != null && (
                      // O porquê que vale para a coluna toda (o IEE não tem número da rede): uma vez, aqui.
                      <span className="mt-0.5 block text-[11px] font-normal leading-tight" data-nota-coluna>
                        sem comparação com a rede <RefNota n={nota} />
                      </span>
                    )}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {escolas.map((e) => {
              const semInep = semCodigoInep(e);
              return (
                <tr key={e.id} className="border-b border-zinc-100 align-top last:border-0 dark:border-zinc-800/60">
                  <th scope="row" className={`${TD} ${PRESA} min-w-[9rem] text-left font-medium`}>
                    <NomeDaEscola e={e} linkDaEscola={linkDaEscola} />
                    {inativaNoCadastro(e) && <> <SeloInativa /></>}
                  </th>
                  {colunas.map((c) => {
                    const o = resultadoNaColuna(e, c);
                    return (
                      <td key={c.chave} className={TD}>
                        {o ? <CelulaOficial o={o} unidade={unidadeDe(o.indicador, base)} referencia={c.edicao}
                                            plano={notas.celulas.get(`${e.id}|${c.chave}`)} />
                          : <ValorOficial valor={null} casas={null}
                                          texto_ausencia={semInep ? "sem código INEP no cadastro" : "sem resultado oficial"} />}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </TabelaRolavel>
      <div className={`space-y-1.5 text-xs ${CINZA}`} data-testid="legenda-comparacao">
        <NotasSobATabela notas={notas} />
        <p className="flex flex-wrap items-center gap-1.5">
          <span>
            <span aria-hidden>▲ </span>acima · <span aria-hidden>= </span>na média · <span aria-hidden>▼ </span>abaixo:
            a escola comparada com a rede municipal na MESMA edição —
          </span>
          <SeloNatureza natureza="calculado" />
          <span>
            {tolerancias.length > 0
              ? `diferença pequena conta como “na média” (menor que: ${tolerancias.join("; ")}).`
              : "diferença pequena conta como “na média”."}
            {" "}Média instável (poucos alunos fizeram a prova) não é comparada. “Subiu” ou “caiu” compara com a
            edição anterior da mesma avaliação, quando a escala não mudou.
          </span>
        </p>
        <p data-testid="legenda-edicao-de-referencia">
          Cada coluna fica numa edição só — a mais recente com resultado entre as escolas; o ano está em cada
          célula. Quando o último resultado de uma escola é de uma edição anterior, a célula não mostra o número: diz
          o ano dele, e o resultado fica na ficha da escola.
        </p>
        <p className="flex flex-wrap items-center gap-1.5">
          <span>A meta e a situação são as oficiais</span>
          <SeloNatureza natureza="oficial" />
          <span>
            (IEE: a meta de cada escola, da SEDUC-SP; Ideb: metas só até 2021). Escolas em ordem alfabética — não é
            ranking.
          </span>
        </p>
      </div>
      <DetalhesEFontes itens={itensFonte} fontes={dados.fontes} testId="detalhes-fontes-comparacao" />
    </div>
  );
}
