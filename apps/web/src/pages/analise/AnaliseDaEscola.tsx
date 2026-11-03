/**
 * Análise de UMA escola — `GET /escolas/{id}/analise`: os indicadores oficiais DA
 * escola (com as referências da rede), o uso das plataformas por série escolar no
 * período e o que não dá para comparar (o ICA é da rede; a relação pede o mesmo
 * ano…). Sem ranking: nenhuma outra escola aparece.
 *
 * Usada em três lugares:
 *  - na Visão da Escola (`AnaliseDaEscola`): o coordenador/admin da escola, a
 *    Secretaria ao entrar numa escola e o admin global. O PROFESSOR não chama a API
 *    (a seção nem aparece) — a mesma regra do backend (`escola_com_indicadores_legiveis`).
 *    A SECRETARIA vê aqui o modo SIMPLES (a Visão da Escola é aberta pela ficha, no fluxo
 *    principal dela: Escolas › ficha › "Ver as turmas"); os demais, o modo completo;
 *  - na aba "Análise detalhada por escola" das Análises avançadas da rede
 *    (`ConteudoAnaliseEscola`, modo completo);
 *  - na ficha da escola da Secretaria (`/rede/escolas/:id`, fluxo principal): só as
 *    avaliações externas, no modo SIMPLES (`simples` + `soAvaliacoes`) — sem sigla
 *    técnica ("TPS"), os textos do servidor em língua simples (`textoSimples`,
 *    `textosDoFluxoPrincipal`), sem o tema da relação estatística, os avisos de cada
 *    indicador recolhidos ("Avisos sobre estes números (N)", fechado: a tabela vem
 *    primeiro) e, sem resultado oficial, o porquê por extenso. O modo completo não muda.
 *
 * A resposta só aparece quando é da escola e do período pedidos agora: ao trocar de
 * escola no seletor do topo, nunca ficam os números da escola anterior.
 *
 * Toda série com meta (a da escola E a da rede de referência) mostra a própria meta, a
 * diferença e a situação — cada linha com a meta DELA, sem cruzar populações.
 */
import { AlertTriangle, Info, School } from "lucide-react";
import type { ReactNode } from "react";

import { SeletorPeriodo, periodoParaQuery, type Periodo } from "../../components/SeletorPeriodo";
import { TabelaRolavel } from "../../components/TabelaRolavel";
import { Badge, Card, Carregando, IconePastel, Mensagem } from "../../components/ui";
import { useApp } from "../../context/AppContext";
import { usePerfil } from "../../hooks/usePerfil";
import { Aviso, Nota } from "../rede/IdebBlocos";
import { textoSimples, textosDoFluxoPrincipal } from "../rede/secretaria/oQueMede";
import DetalhesEFontes, { Recolhivel, type ItemDetalhe } from "./DetalhesFonte";
import { FiltrosAplicados, SemPontoNaEdicao, TD, TH, TITULO_CARTAO, ValorOficial, useApiExata } from "./comum";
import {
  ROTULO_SITUACAO, casasDaDiferenca, diferencaComUnidade, legendaSemRegistro, rotuloComponente, rotuloEtapa,
  rotuloSerie, valorComUnidade,
} from "./formato";
import { CartoesPlataformas, LimitacoesPlataformas, TabelaSeriesPlataformas } from "./Plataformas";
import type { IndicadorDaEscola, PontoAnalise, RespostaAnaliseEscola, SerieAnalise } from "./tipos";

const CINZA = "text-zinc-600 dark:text-zinc-400";

const ANO_LETIVO: Periodo = { preset: "ano_letivo" };

/**
 * A análise de uma escola no ANO LETIVO, com cache curto — a leitura das avaliações externas da
 * Secretaria: a comparação lado a lado (tela Escolas) e a ficha da escola pedem a MESMA URL, e
 * abrir a ficha depois de comparar não refaz a conta. Os números oficiais não dependem do
 * período (cada avaliação tem a sua edição); só a parte das plataformas, que estas telas não usam
 * — por isso `so_avaliacoes`: o servidor não mede a escola e `plataformas` vem nulo.
 */
export function urlAnaliseNoAnoLetivo(escolaId: number | null | undefined): string | null {
  return escolaId == null ? null
    : `/escolas/${escolaId}/analise?${periodoParaQuery(ANO_LETIVO)}&so_avaliacoes=true`;
}
export const OPCOES_ANALISE_DA_ESCOLA = { cacheMs: 60_000 } as const;

/** O modo de cada lugar: o COMPLETO (Visão da Escola da coordenação e do admin global, Análises
 *  avançadas) e o SIMPLES (o fluxo principal da Secretaria: a ficha da escola e a Visão da Escola
 *  aberta por ela). Só a forma dos textos muda — os números são os mesmos. */
interface Modo {
  simples: boolean;
  /** O selo do IEE calculado com médias de TPS = 0. */
  tpsZero: string;
  /** Os textos do servidor (avisos, motivos, ausências). */
  texto: (t: string) => string;
  /** A reescrita do motivo da falta em `ValorOficial` (no completo, nenhuma: o texto de sempre). */
  traduzir?: (t: string) => string;
}
const MODO_COMPLETO: Modo = { simples: false, tpsZero: "calculado com médias de TPS = 0", texto: (t) => t };
const MODO_SIMPLES: Modo = {
  simples: true, tpsZero: "calculado com médias instáveis", texto: textoSimples, traduzir: textoSimples,
};

const PAPEL: Record<string, string> = {
  principal: "esta escola",
  referencia: "referência",
  contexto: "outra rede — só contexto",
};

const ORDEM_PAPEL: Record<string, number> = { principal: 0, referencia: 1, contexto: 2 };

/** A unidade do indicador da escola (o endpoint 5 não manda o catálogo inteiro). */
function unidadeDe(ind: IndicadorDaEscola): string | null {
  return ind.unidade ?? (ind.chave === "ica" ? "%" : null);
}

/**
 * O bloco de um indicador: o título é h4 (sob o h3 "Indicadores oficiais da escola"),
 * para o leitor de tela anunciar a hierarquia certa — h3 na ficha da escola, onde o cartão
 * "Avaliações externas da escola" é o h2 e não há o h3 do meio.
 */
function BlocoIndicador({ titulo, children, testId, nivel = 4 }: {
  titulo: string; children: ReactNode; testId?: string; nivel?: 3 | 4;
}) {
  const Titulo = nivel === 3 ? "h3" : "h4";
  return (
    <section className="space-y-2" aria-label={titulo} data-testid={testId}>
      <Titulo className="text-sm font-semibold text-zinc-800 dark:text-zinc-100">{titulo}</Titulo>
      {children}
    </section>
  );
}

/** "meta 60% · −2 p.p. · não atingiu a meta" — a meta DA linha, a diferença e a situação. */
function MetaDoPonto({ p, unidade }: { p: PontoAnalise; unidade: string | null }) {
  if (p.meta == null) return null;
  const dif = p.diferenca_meta == null
    ? null
    : diferencaComUnidade(p.diferenca_meta, p.diferenca_casas ?? casasDaDiferenca(p.casas, p.meta_casas), unidade);
  return (
    <span className={`block text-xs ${CINZA}`}>
      meta {valorComUnidade(p.meta, p.meta_casas ?? p.casas, unidade, p.operador_meta)}
      {dif ? ` · ${dif}` : ""}
      {p.situacao_meta ? ` · ${ROTULO_SITUACAO[p.situacao_meta]}` : ""}
    </span>
  );
}

/** "5º ano · Língua Portuguesa" — o recorte de uma série (o rótulo da série é o da escola). */
function recorteDe(s: SerieAnalise): string {
  return [rotuloEtapa(s.etapa), rotuloComponente(s.componente)].filter(Boolean).join(" · ");
}

/** As séries agrupadas pelo recorte (etapa × componente), na ordem em que chegam; dentro
 *  de cada grupo, a escola primeiro, depois a referência e o contexto. */
function gruposDeSeries(series: SerieAnalise[]): { recorte: string; series: SerieAnalise[] }[] {
  const grupos: { recorte: string; series: SerieAnalise[] }[] = [];
  for (const s of series) {
    const recorte = recorteDe(s);
    const g = grupos.find((x) => x.recorte === recorte);
    if (g) g.series.push(s);
    else grupos.push({ recorte, series: [s] });
  }
  for (const g of grupos) g.series.sort((a, b) => (ORDEM_PAPEL[a.papel] ?? 3) - (ORDEM_PAPEL[b.papel] ?? 3));
  return grupos;
}

/** No fluxo principal (celular), a tabela larga rola dentro do cartão, com o aviso "Deslize…";
 *  no completo, a moldura de sempre. */
function Moldura({ simples, rotulo, children }: { simples: boolean; rotulo: string; children: ReactNode }) {
  return simples
    ? <TabelaRolavel rotulo={rotulo}>{children}</TabelaRolavel>
    : <div className="relative overflow-x-auto">{children}</div>;
}

function IndicadorEscola({ ind, modo, nivel }: { ind: IndicadorDaEscola; modo: Modo; nivel?: 3 | 4 }) {
  const grupos = gruposDeSeries(ind.series);
  const series = grupos.flatMap((g) => g.series);
  const edicoes = [...new Set(series.flatMap((s) => s.pontos.map((p) => p.edicao)))].sort((a, b) => b - a);
  const unidade = unidadeDe(ind);
  const comCabecalho = grupos.length > 1 || grupos.some((g) => g.recorte !== "");
  const semRegistro = legendaSemRegistro(series.flatMap((s) => s.pontos));
  const legenda = semRegistro ? modo.texto(semRegistro) : null;
  const quebras = (ind.quebras ?? []).map((q) =>
    `Entre ${q.entre[0]} e ${q.entre[1]}${q.etapa ? ` (${rotuloEtapa(q.etapa)})` : ""}: ${q.texto}`);
  const avisos = [...new Set([...ind.avisos, ...quebras].map(modo.texto).filter(Boolean))];
  const comInstavel = series.some((s) => s.pontos.some((p) => p.instavel || p.tps_zero));
  return (
    <BlocoIndicador titulo={ind.nome} testId={`analise-escola-indicador-${ind.chave}`} nivel={nivel}>
      {/* O modo completo: os avisos abertos, antes da tabela (como sempre). O simples os recolhe,
          depois da tabela. */}
      {!modo.simples && avisos.length > 0 && (
        <Aviso><ul className="list-disc space-y-0.5 pl-4">{avisos.map((a) => <li key={a}>{a}</li>)}</ul></Aviso>
      )}
      {series.length === 0 || edicoes.length === 0 ? (
        <p className={`text-sm ${CINZA}`}>Sem número oficial desta escola importado.</p>
      ) : (
        <Moldura simples={modo.simples} rotulo={`${ind.nome}: tabela completa`}>
          <table className="w-full text-xs">
            <caption className="sr-only">{ind.nome}: esta escola e as referências por edição</caption>
            <thead>
              <tr className={`border-b border-zinc-200 dark:border-zinc-800 ${CINZA}`}>
                <th className={TH} scope="col">Escola ou referência</th>
                {edicoes.map((e) => <th key={e} className={TH} scope="col">{e}</th>)}
              </tr>
            </thead>
            {grupos.map((g) => (
            <tbody key={g.recorte || "unico"}>
              {comCabecalho && (
                <tr className="bg-zinc-50 dark:bg-zinc-800/40">
                  <th scope="rowgroup" colSpan={edicoes.length + 1} className={`${TD} text-left font-medium`}>
                    {g.recorte || ind.nome}
                  </th>
                </tr>
              )}
              {g.series.map((s) => (
                <tr key={`${s.id}-${g.recorte}`} className="border-b border-zinc-100 last:border-0 dark:border-zinc-800/60">
                  <th scope="row" className={`${TD} min-w-[9rem] text-left font-normal`}>
                    <span className="block break-words">{s.rotulo}</span>
                    <span className={`block text-xs ${CINZA}`}>
                      {PAPEL[s.papel] ?? s.papel}
                      {!s.comparavel && s.motivo_nao_comparavel ? `: ${modo.texto(s.motivo_nao_comparavel)}` : ""}
                    </span>
                  </th>
                  {edicoes.map((e) => {
                    const p = s.pontos.find((x) => x.edicao === e);
                    return (
                      <td key={e} className={TD}>
                        {p ? <ValorOficial {...p} unidade={unidade} traduzir={modo.traduzir} /> : <SemPontoNaEdicao />}
                        {p?.instavel && <span className="block"><Badge tom="alerta">média instável</Badge></span>}
                        {p?.tps_zero && <span className="block"><Badge tom="alerta">{modo.tpsZero}</Badge></span>}
                        {p && <MetaDoPonto p={p} unidade={unidade} />}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
            ))}
          </table>
        </Moldura>
      )}
      {modo.simples && comInstavel && (
        <p className={`text-xs ${CINZA}`} data-testid="legenda-instavel">
          Média instável: poucos alunos fizeram a prova — o número vale, mas compare com cuidado.
        </p>
      )}
      {legenda && <p className={`text-xs ${CINZA}`} data-testid="legenda-sem-registro">{legenda}</p>}
      {/* O modo simples (o fluxo principal da Secretaria): os mesmos avisos, em língua simples, num
          recolhível FECHADO por indicador — a tabela da escola e a rede de referência ficam à vista,
          sem a lista longa na frente; o número entre parênteses diz quantos há. */}
      {modo.simples && avisos.length > 0 && (
        <Recolhivel titulo={`Avisos sobre estes números (${avisos.length})`} testId={`avisos-indicador-${ind.chave}`}
                    icone={<AlertTriangle size={14} className="shrink-0 text-zinc-500" aria-hidden />}>
          <ul className="list-disc space-y-1 pl-4">{avisos.map((a) => <li key={a}>{a}</li>)}</ul>
        </Recolhivel>
      )}
    </BlocoIndicador>
  );
}

/**
 * Avaliação oficial e plataformas aparecem PERTO aqui (uma seção embaixo da outra) e nunca
 * entram na mesma conta: a frase diz de quando é cada lado. Só com os dois lados (a última
 * edição com número da ESCOLA e o período das plataformas); o ano das plataformas é o do
 * ano letivo das escolas, ou o do fim da janela.
 */
function FrasePeriodosDiferentes({ dados }: { dados: RespostaAnaliseEscola }) {
  const pl = dados.plataformas;
  const edicoes = dados.indicadores.flatMap((ind) => ind.series
    .filter((s) => s.papel === "principal")
    .flatMap((s) => s.pontos.filter((p) => p.valor != null).map((p) => p.edicao)));
  if (!pl || edicoes.length === 0) return null;
  const ultima = Math.max(...edicoes);
  const anoPlataformas = pl.janela.ano_letivo ?? (Number((pl.janela.fim ?? pl.janela.inicio ?? "").slice(0, 4)) || null);
  const periodo = pl.janela.rotulo.toLowerCase();
  return (
    <Nota testId="frase-periodos-diferentes">
      {anoPlataformas != null && ultima < anoPlataformas
        ? `As avaliações oficiais são de outras edições (até ${ultima}) e as plataformas, do período escolhido `
          + `(${periodo}): são medidas e períodos diferentes — não se comparam diretamente.`
        : `As avaliações oficiais (edições até ${ultima}) e as plataformas (${periodo}) são medidas diferentes, `
          + "cada uma com o seu calendário — não se comparam diretamente."}
    </Nota>
  );
}

/** A escola tem ALGUM número oficial dela (série principal com valor)? */
export function temResultadoOficial(dados: RespostaAnaliseEscola): boolean {
  return dados.indicadores.some((ind) => ind.series.some((s) => s.papel === "principal"
    && s.pontos.some((p) => p.valor != null)));
}

const PORQUE_REIMPORTAR = "o código INEP da escola foi cadastrado ou mudou depois da importação: os arquivos "
  + "oficiais precisam ser importados de novo — quem importa é o administrador global";

/** Quando TODAS as edições da escola faltam pelo mesmo motivo, a frase dele (pelo código do
 *  servidor em `motivo_ausencia`); motivos diferentes ficam na frase geral — cada edição diz o seu
 *  na tabela da avaliação. */
const PORQUE_DO_MOTIVO: Record<string, string> = {
  fora_do_arquivo: "a escola não aparece nos arquivos oficiais importados",
  nao_divulgado: "os arquivos oficiais importados não divulgam número desta escola",
  participacao_baixa: "nas edições importadas, a participação da escola na prova ficou abaixo do mínimo da fonte",
  cadastrado_depois_da_importacao: PORQUE_REIMPORTAR,
  codigo_inep_alterado: PORQUE_REIMPORTAR,
};

/**
 * Por que a escola não tem resultado oficial, por extenso (o modo simples diz; nunca um 0). O
 * servidor manda SEMPRE os indicadores da escola (`indicadores_da_escola`): cada um com a série
 * DELA (a principal) — sem ponto nenhum quando nenhuma edição importada a traz; com pontos sem
 * valor (e o motivo) quando a edição foi importada e não tem número dela — e a rede municipal como
 * referência só quando há ponto. Então o porquê sai do conteúdo das séries, não da lista vazia:
 *  - sem código INEP no cadastro (o aviso próprio, no topo);
 *  - a série da escola sem ponto nenhum e a rede sem número NAS AVALIAÇÕES POR ESCOLA: nenhuma
 *    edição importada delas traz resultados (da escola ou da rede);
 *  - a série da escola sem ponto, a rede com número nas avaliações por escola: as edições
 *    importadas não trazem a escola;
 *  - a série da escola com pontos sem valor: o motivo comum a todos, ou a frase geral.
 * O ICA só existe para a rede (não tem série da escola): o número dele não diz nada sobre a escola
 * ter ficado fora dos arquivos — a rede com número só conta nos indicadores por escola.
 */
export function porqueSemResultadoOficial(dados: RespostaAnaliseEscola): string {
  if (dados.escola.pendencia === "sem_codigo_inep") {
    return "a escola está sem código INEP no cadastro, e os arquivos oficiais não casam com ela";
  }
  // Só os indicadores que existem POR ESCOLA (com a série da escola); o ICA, só da rede, fica fora.
  const porEscola = dados.indicadores.filter((ind) => ind.series.some((s) => s.papel === "principal"));
  const series = porEscola.flatMap((ind) => ind.series);
  const daEscola = series.filter((s) => s.papel === "principal").flatMap((s) => s.pontos);
  if (daEscola.length === 0) {
    // A referência da escola é só a rede municipal (o servidor não manda outra).
    const redeComNumero = series.some((s) => s.papel !== "principal" && s.pontos.some((p) => p.valor != null));
    return redeComNumero
      ? "as edições importadas trazem resultados da rede municipal, mas nenhum desta escola"
      : "nenhuma edição importada das avaliações com resultado por escola (SARESP, IEE, Ideb, Saeb) traz "
        + "resultados desta escola nem da rede municipal";
  }
  const porques = new Set(daEscola.map((p) => PORQUE_DO_MOTIVO[p.motivo_ausencia ?? ""] ?? null));
  const [unico] = porques;
  if (porques.size === 1 && unico) return unico;
  return "as edições importadas não trazem número desta escola; cada avaliação, abaixo, diz o motivo de cada edição";
}

/** O conteúdo da análise de uma escola (só apresentação), a partir da resposta da API. */
export function ConteudoAnaliseEscola({ dados, serie, simples = false, soAvaliacoes = false }: {
  dados: RespostaAnaliseEscola;
  serie?: number | null;
  /** O fluxo principal da Secretaria (a ficha da escola e a Visão da Escola dela): sem sigla
   *  técnica, os textos do servidor em língua simples, sem o tema da relação estatística, os avisos
   *  de cada indicador num recolhível fechado e, sem resultado oficial, o porquê por extenso. Sem
   *  ele (os demais perfis na Visão da Escola, as Análises avançadas), o conteúdo de sempre. */
  simples?: boolean;
  /** Só as avaliações externas (a ficha mostra as plataformas à parte, com o seletor dela): sem
   *  o uso das plataformas nem a frase dos períodos; os indicadores sobem um nível (h3, sob o h2
   *  do cartão da ficha) e só entram os que existem para a escola (o ICA é só da rede: o porquê
   *  fica em "O que não dá para comparar aqui"). */
  soAvaliacoes?: boolean;
}) {
  const modo = simples ? MODO_SIMPLES : MODO_COMPLETO;
  const pl = dados.plataformas;
  const semInep = dados.escola.pendencia === "sem_codigo_inep";
  // O cadastro sem INEP já tem o aviso próprio, no topo: não se repete na lista. No modo simples,
  // a relação estatística (assunto das Análises avançadas) não entra.
  const indisponiveis = dados.comparacoes_indisponiveis
    .filter((c) => !(semInep && c.tema === "cadastro") && !(simples && c.tema === "relacao"))
    .map((c) => ({ ...c, texto: modo.texto(c.texto) }))
    .filter((c) => c.texto);
  const indicadores = soAvaliacoes
    ? dados.indicadores.filter((ind) => ind.series.some((s) => s.papel === "principal"))
    : dados.indicadores;
  const itens: ItemDetalhe[] = indicadores.flatMap((ind) => ind.series.flatMap((s) => s.pontos.map((p) => ({
    rotulo: `${ind.nome}${recorteDe(s) ? ` (${recorteDe(s)})` : ""} ${p.edicao} — ${s.rotulo}`, fonte_id: p.fonte_id,
  }))));
  // Sem resultado oficial nenhum, o modo simples diz por quê numa frase (o cadastro sem INEP já tem
  // o aviso próprio, acima).
  const semResultado = simples && !semInep && !temResultadoOficial(dados);
  return (
    <div className="space-y-5">
      {semInep && (
        <Aviso testId="analise-escola-sem-inep">
          A escola está sem código INEP no cadastro: os arquivos oficiais não casam com ela, e os indicadores da
          escola ficam sem número. Quem cadastra o código é o administrador global do Constela.
        </Aviso>
      )}
      {!dados.rede && !indisponiveis.some((c) => c.tema === "sem_rede") && (
        <Nota>A escola não está vinculada a uma rede: sem as referências da rede.</Nota>
      )}

      <section className="space-y-3" aria-label="Indicadores oficiais da escola">
        {!soAvaliacoes && (
          <h3 className="text-[15px] font-semibold text-zinc-900 dark:text-white">Indicadores oficiais da escola</h3>
        )}
        <FiltrosAplicados>Não usam período nem série: cada avaliação tem edição própria.</FiltrosAplicados>
        {semResultado && (
          <p className="text-sm text-zinc-700 dark:text-zinc-200" data-testid="avaliacoes-escola-sem-resultado">
            Esta escola ainda não tem resultado oficial no Constela: {porqueSemResultadoOficial(dados)}.
          </p>
        )}
        {indicadores.length === 0 ? (
          !semResultado && (
            <p className={`text-sm ${CINZA}`} data-testid="analise-escola-sem-indicadores">
              Nenhum indicador oficial importado para esta escola.
            </p>
          )
        ) : indicadores.map((ind) => (
          <IndicadorEscola key={ind.chave} ind={ind} modo={modo} nivel={soAvaliacoes ? 3 : 4} />
        ))}
      </section>

      {!soAvaliacoes && <FrasePeriodosDiferentes dados={dados} />}

      {!soAvaliacoes && (
        <section className="space-y-3" aria-label="Uso das plataformas por série">
          <h3 className="text-[15px] font-semibold text-zinc-900 dark:text-white">Uso das plataformas por série</h3>
          {pl ? (
            <>
              <FiltrosAplicados testId="analise-escola-filtros">
                {serie != null
                  ? `Vale aqui: período (${pl.janela.rotulo}) e série (${rotuloSerie(serie)}).`
                  : `Vale aqui: o período (${pl.janela.rotulo}). A tabela mostra cada série do 1º ao 5º ano.`}
              </FiltrosAplicados>
              <CartoesPlataformas alunos={pl.alunos} elefante={pl.elefante} matific={pl.matific} modulos={pl.modulos}
                                  suprimido={pl.suprimido} textoSupressao={pl.texto_supressao}
                                  textoBlocos={pl.texto_blocos} nivelTitulo={4} />
              <TabelaSeriesPlataformas series={pl.series} modulos={pl.modulos} serieFiltro={serie}
                                       legenda={`Uso das plataformas por série — ${dados.escola.nome}`} />
              <LimitacoesPlataformas limitacoes={simples ? textosDoFluxoPrincipal(pl.limitacoes) : pl.limitacoes} />
            </>
          ) : (
            <p className={`text-sm ${CINZA}`}>Sem dado de plataforma desta escola no período.</p>
          )}
        </section>
      )}

      {indisponiveis.length > 0 && (
        <section className="space-y-2" aria-label="O que não dá para comparar" data-testid="analise-escola-indisponiveis">
          <h3 className="text-[15px] font-semibold text-zinc-900 dark:text-white">O que não dá para comparar aqui</h3>
          <ul className="space-y-1.5">
            {indisponiveis.map((c) => (
              <li key={c.tema} className="flex items-start gap-1.5 text-xs text-zinc-600 dark:text-zinc-300">
                <Info size={13} className="mt-0.5 shrink-0 text-zinc-500" aria-hidden />
                <span className="min-w-0 break-words">{c.texto}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <DetalhesEFontes itens={itens} fontes={dados.fontes} testId="detalhes-fontes-escola" />
    </div>
  );
}

/** Seção da Visão da Escola. O professor não vê e a API nem é chamada. */
export default function AnaliseDaEscola({ escolaId }: { escolaId: number | null }) {
  const { gestor, secretaria } = usePerfil();
  const { periodo, definirPeriodo } = useApp();
  const pode = gestor || secretaria;
  const url = pode && escolaId ? `/escolas/${escolaId}/analise?${periodoParaQuery(periodo)}` : null;
  const { dados, carregando, erro } = useApiExata<RespostaAnaliseEscola>(url);
  if (!pode || !escolaId) return null;
  const daEscola = dados && dados.escola.id === escolaId ? dados : null;
  return (
    <section className="mt-6" data-testid="analise-escola" aria-label="Análise educacional da escola">
      <Card className="space-y-6 p-6">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className={TITULO_CARTAO}>
              <IconePastel icone={School} tom="violeta" tamanho="sm" /> Análise educacional da escola
            </h2>
            {daEscola && (
              <p className={`mt-1 break-words pl-11 text-xs ${CINZA}`} data-testid="analise-escola-nome">
                {daEscola.escola.nome}
              </p>
            )}
          </div>
          <SeletorPeriodo valor={periodo} onChange={definirPeriodo} />
        </div>
        {carregando && !daEscola ? (
          <Carregando texto="Carregando a análise da escola..." />
        ) : erro && !daEscola ? (
          <Mensagem tipo="erro">Não foi possível carregar a análise da escola: {erro.message}</Mensagem>
        ) : daEscola ? (
          <ConteudoAnaliseEscola dados={daEscola} simples={secretaria} />
        ) : null}
      </Card>
    </section>
  );
}
