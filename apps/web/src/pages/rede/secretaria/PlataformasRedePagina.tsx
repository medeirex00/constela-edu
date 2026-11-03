/**
 * ELEFANTE E MATIFIC — `/rede/plataformas` (Secretaria e global; guarda `RotaRede`). O nome
 * segue os módulos contratados ("Elefante Letrado", "Matific" ou "Elefante e Matific").
 * DESENHO2 §2.3.5.
 *
 * Mostra quanto e como as crianças usam as plataformas — não é avaliação oficial de
 * aprendizagem. De cima para baixo:
 *
 *  1. No período e na série (padrão: ano letivo, do 1º ao 5º ano; os seletores desta tela ficam
 *     na URL, `?periodo=&serie=` — o link antigo `?ver=plataformas&serie=2` chega com a série):
 *     a conclusão em uma frase, "Vale aqui", os cartões das plataformas (`CartoesPlataformas`) e
 *     "O que cada número mede";
 *  2. Evolução no ano letivo, por bimestre (`EvolucaoPlataformas`): a rede na mesma série e, se
 *     escolhida no recorte da própria evolução, uma escola (tabela à parte, `?escola=`);
 *  3. Totais acumulados (`/redes/{id}/dashboard`), cada um com o período certo — Elefante:
 *     acumulado desde o início da conta de cada aluno (o contador da plataforma é vitalício);
 *     Matific: no ano letivo —, o cadastro da rede à parte e a média das notas do Constela;
 *  4. "Sobre os dados", recolhido: até onde as coletas cobrem, em quais séries falta dado e as
 *     limitações.
 *
 * Leituras: as plataformas no período, a evolução, o painel da rede (totais) e o catálogo (os
 * nomes das escolas na cobertura e as avaliações de cada série). Nenhum dado de aluno: tudo
 * chega agregado e já protegido pelo servidor (grupo pequeno = "protegido", nunca 0).
 */
import { BookOpen, Calculator, CalendarRange, MonitorSmartphone, Rows3, Sigma } from "lucide-react";
import type { ReactNode } from "react";
import { useSearchParams } from "react-router-dom";

import { TabelaRolavel } from "../../../components/TabelaRolavel";
import { Card, Carregando, IconePastel } from "../../../components/ui";
import { useApi } from "../../../hooks/useApi";
import { rotuloDasPlataformas, useModulos } from "../../../hooks/useModulos";
import { nota, numero, tempoLeitura } from "../../../lib/formato";
import { Recolhivel } from "../../analise/DetalhesFonte";
import EvolucaoPlataformas from "../../analise/EvolucaoPlataformas";
import { CartoesPlataformas, CoberturaDasColetas } from "../../analise/Plataformas";
import { FiltrosAplicados, SeloNatureza, Seletor, TD, TH, usePlataformasDaRede } from "../../analise/comum";
import { porNome, rotuloSerie } from "../../analise/formato";
import type {
  IndicadorAnalise, MetricasElefante, MetricasMatific, RespostaIndicadoresRede, RespostaPlataformas,
} from "../../analise/tipos";
import { AvisoTotaisParciais, type DashboardRede } from "../comum";
import { conclusaoPlataformas } from "./conclusoes";
import {
  FRASE_PLATAFORMA, METRICAS_ELEFANTE, METRICAS_MATIFIC, textosDoFluxoPrincipal, type MetricaExplicada,
} from "./oQueMede";
import {
  CINZA, CabecalhoDaPagina, CampoPeriodo, CampoSerie, EstadoDaLeitura, LinkVer, PaginaDaRede, TITULO_SECAO,
  type ContextoDaPagina,
} from "./pecas";
import { SERIES_DA_REDE, periodoParaUrl, useCatalogo, usePeriodoDaPagina, useSerieDaPagina } from "./useRedeDaPagina";

// --- O que cada número mede ----------------------------------------------------------------

function ListaDoQueMede({ titulo, metricas, testId }: { titulo: string; metricas: MetricaExplicada[]; testId: string }) {
  return (
    <section className="min-w-0 space-y-1.5" aria-label={titulo} data-testid={testId}>
      <h4 className="text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">{titulo}</h4>
      <dl className="space-y-1.5 text-xs">
        {metricas.map((m) => (
          <div key={m.chave} data-o-que-mede>
            <dt className="inline font-semibold text-zinc-800 dark:text-zinc-100">{m.rotulo}: </dt>
            <dd className="inline text-zinc-700 dark:text-zinc-200">{m.oQueMede}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

// --- Totais acumulados (painel da rede) ---------------------------------------------------

function Total({ rotulo, valor, detalhe }: { rotulo: string; valor: ReactNode; detalhe?: ReactNode }) {
  return (
    <div className="min-w-0 rounded-2xl bg-zinc-50 px-4 py-3 dark:bg-zinc-800/50">
      <p className={`text-xs font-medium ${CINZA}`}>{rotulo}</p>
      <p className="mt-0.5 break-words text-xl font-bold tabular-nums tracking-tight text-zinc-900 dark:text-white">{valor}</p>
      {detalhe && <p className={`mt-0.5 text-xs ${CINZA}`}>{detalhe}</p>}
    </div>
  );
}

/** O total que falta: "protegido" quando a Secretaria não vê a matéria (grupo pequeno), senão
 *  "sem dado" — escrito, nunca 0 nem "—" mudo. */
function Falta({ protegido }: { protegido: boolean }) {
  return <span className={`text-sm font-medium ${CINZA}`}>{protegido ? "protegido (poucos alunos)" : "sem dado"}</span>;
}

function TotaisAcumulados({ d }: { d: DashboardRede }) {
  const t = d.totais;
  const mods = d.modulos ?? ["leitura", "matematica"];
  const ocultaLeitura = (t.grupo_pequeno?.leitura ?? 0) > 0;
  const ocultaMatematica = (t.grupo_pequeno?.matematica ?? 0) > 0;
  // Nada medido (nenhum aluno com dado da plataforma): o servidor manda 0, não null — aqui é
  // "sem dado" por extenso (livros, tempo, atividades, estrelas e a média), nunca 0.
  const semElefante = !t.ativos_elefante;
  const semMatific = !t.ativos_matific;
  // A média de cada plataforma tem o próprio denominador: os alunos COM NOTA dela, nas escolas.
  const comNota = (campo: "alunos_com_nota_elefante" | "alunos_com_nota_matific") =>
    (d.escolas.length === 0 ? null : d.escolas.reduce((soma, e) => soma + (e[campo] ?? 0), 0));
  const semNotaElefante = semElefante || comNota("alunos_com_nota_elefante") === 0;
  const semNotaMatific = semMatific || comNota("alunos_com_nota_matific") === 0;
  const semNotaNenhuma = (!mods.includes("leitura") || semNotaElefante) && (!mods.includes("matematica") || semNotaMatific);
  const ou = (v: number | null | undefined, fmt: (n: number) => string, protegido: boolean, semMedida: boolean): ReactNode =>
    (v == null ? <Falta protegido={protegido} /> : semMedida ? <Falta protegido={false} /> : fmt(v));
  // A média interna de cada plataforma contratada (o Panorama antigo mostrava as duas): sem
  // número, por extenso.
  const mediaDe = (v: number | null | undefined, protegido: boolean, semMedida: boolean) =>
    (v == null ? (protegido ? "protegido" : "sem dado") : semMedida ? "sem dado" : nota(v));
  const porPlataforma = [
    ...(mods.includes("leitura") ? [`Elefante ${mediaDe(t.media_elefante, ocultaLeitura, semNotaElefante)}`] : []),
    ...(mods.includes("matematica") ? [`Matific ${mediaDe(t.media_matific, ocultaMatematica, semNotaMatific)}`] : []),
  ];
  return (
    <div className="space-y-5" data-testid="totais-gerais">
      {/* O cadastro não é uso das plataformas: fica à parte, sem o selo Plataforma. */}
      <section className="min-w-0 space-y-2" aria-label="Cadastro da rede" data-testid="totais-cadastro">
        <h3 className="text-sm font-semibold text-zinc-900 dark:text-white">
          Cadastro da rede <span className={`font-normal ${CINZA}`}>— matrículas e escolas (não é uso das plataformas)</span>
        </h3>
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-3">
          <Total rotulo="Alunos" valor={numero(t.alunos)} detalhe={`${numero(t.escolas)} escolas · ${numero(t.turmas)} turmas`} />
          <Total rotulo="Professores" valor={numero(t.professores)} detalhe="na rede" />
          <Total rotulo="Escolas ativas" valor={numero(t.escolas_ativas)}
                 detalhe={`situação “ativa” no cadastro, de ${numero(t.escolas)} cadastradas — não indica uso das plataformas`} />
        </div>
      </section>
      <section className="min-w-0 space-y-3" aria-label="Nas plataformas" data-testid="totais-plataformas">
        <h3 className="flex flex-wrap items-center gap-2 text-sm font-semibold text-zinc-900 dark:text-white">
          Nas plataformas <SeloNatureza natureza="plataforma" />
        </h3>
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          {/* Um percentual com o rótulo que diz de quê (os "Alunos com dados" de cada plataforma, abaixo,
              são contagens — o mesmo rótulo para as duas coisas confundia). */}
          <Total rotulo="Com dado de alguma plataforma" valor={`${nota(t.adocao)}%`}
                 detalhe={`${numero(t.alunos_com_dados)} de ${numero(t.alunos)} alunos`} />
        </div>
        <div className={`grid grid-cols-1 gap-4 ${mods.includes("leitura") && mods.includes("matematica") ? "lg:grid-cols-2" : ""}`}>
          {mods.includes("leitura") && (
            <section className="min-w-0 space-y-2" aria-label="Elefante Letrado, acumulado desde o início" data-testid="totais-elefante">
              <h4 className="flex flex-wrap items-center gap-2 text-sm font-semibold text-zinc-900 dark:text-white">
                <IconePastel icone={BookOpen} tom="violeta" tamanho="sm" /> Elefante Letrado (leitura)
                <span className={`text-xs font-normal ${CINZA}`}>desde o início</span>
              </h4>
              <div className="grid grid-cols-2 gap-3">
                <Total rotulo="Livros lidos" valor={ou(t.livros, numero, ocultaLeitura, semElefante)}
                       detalhe="títulos únicos, desde o início no Elefante" />
                <Total rotulo="Tempo de leitura" valor={ou(t.tempo_leitura_min, tempoLeitura, ocultaLeitura, semElefante)}
                       detalhe="o mínimo registrado, desde o início no Elefante" />
                <Total rotulo="Alunos com dados" valor={numero(t.ativos_elefante)} detalhe="na última coleta do Elefante" />
              </div>
            </section>
          )}
          {mods.includes("matematica") && (
            <section className="min-w-0 space-y-2" aria-label="Matific no ano letivo" data-testid="totais-matific">
              <h4 className="flex flex-wrap items-center gap-2 text-sm font-semibold text-zinc-900 dark:text-white">
                <IconePastel icone={Calculator} tom="teal" tamanho="sm" /> Matific (matemática)
                <span className={`text-xs font-normal ${CINZA}`}>no ano letivo</span>
              </h4>
              <div className="grid grid-cols-2 gap-3">
                <Total rotulo="Atividades" valor={ou(t.atividades, numero, ocultaMatematica, semMatific)} detalhe="no ano letivo" />
                <Total rotulo="Estrelas" valor={ou(t.estrelas, numero, ocultaMatematica, semMatific)} detalhe="no ano letivo" />
                <Total rotulo="Alunos com dados" valor={numero(t.ativos_matific)} detalhe="na última coleta do Matific" />
              </div>
            </section>
          )}
        </div>
      </section>
      <AvisoTotaisParciais totais={t} />
      {/* A média interna (0–100) era um número do Panorama antigo: fica, com o que ela é — a nota
          do Constela, cada aluno comparado com os colegas da própria escola; NÃO compara escolas
          (o índice do Ranking da Rede é que compara). */}
      <p className={`flex flex-wrap items-center gap-x-2 gap-y-1 text-xs ${CINZA}`} data-testid="media-interna">
        <SeloNatureza natureza="calculado" />
        <span className="min-w-0 break-words">
          Média das notas do Constela (0 a 100): {t.media_geral == null || semNotaNenhuma ? "sem dado" : nota(t.media_geral)}
          {porPlataforma.length > 0 && ` (${porPlataforma.join(" · ")})`}. É a nota atual que o Constela calcula para cada
          aluno a partir do uso de cada plataforma, comparando-o com os colegas da própria escola — não é avaliação de
          aprendizagem e não serve para comparar escolas.
        </span>
      </p>
    </div>
  );
}

// --- Em quais séries há lacunas (plataformas × avaliações oficiais) -------------------------

/** A etapa oficial de cada série escolar (as outras séries não têm avaliação própria). */
const ETAPA_DA_SERIE: Record<number, string> = { 2: "2_ano", 5: "5_ano" };

const comDado = (m: MetricasElefante | MetricasMatific | null | undefined) =>
  Boolean(m && !m.motivo_sem_dado && !m.texto_sem_dado && m.participacao_pct != null);

function oficiaisDaSerie(serie: number, indicadores: IndicadorAnalise[]): string[] {
  const etapa = ETAPA_DA_SERIE[serie];
  if (!etapa) return [];
  return indicadores
    .filter((i) => i.disponivel && i.etapas.includes(etapa))
    .map((i) => `${i.nome}${i.por_escola ? "" : " (só da rede)"}`);
}

/**
 * EM QUAIS SÉRIES FALTA DADO: por série, quantas escolas mostradas têm número de cada
 * plataforma no período (a série oculta por poucos alunos fica contada à parte) e quais
 * avaliações oficiais existem para ela. Só contagem de ESCOLAS — nenhum aluno.
 */
function LacunasPorSerie({ dados, base, serie }: {
  dados: RespostaPlataformas; base: RespostaIndicadoresRede | null; serie: number | null;
}) {
  const visiveis = dados.escolas.filter((e) => !e.suprimido);
  const escondidas = dados.escolas.length - visiveis.length;
  const comElefante = dados.modulos.elefante;
  const comMatific = dados.modulos.matific;
  const indicadores = base?.indicadores ?? [];
  const anosIniciais = indicadores.filter((i) => i.disponivel && i.etapas.includes("anos_iniciais"));
  // Com uma série escolhida, a leitura das plataformas só traz ela: o quadro mostra só ela
  // (as outras sairiam com "0 escolas", um zero falso).
  const linhas = SERIES_DA_REDE.filter((s) => serie == null || s === serie).map((s) => {
    const celulas = visiveis.flatMap((e) => e.series.filter((c) => c.serie === s));
    const ocultas = celulas.filter((c) => c.suprimido).length;
    const abertas = celulas.filter((c) => !c.suprimido);
    return {
      serie: s, escolas: celulas.length, ocultas, abertas: abertas.length,
      elefante: abertas.filter((c) => comDado(c.elefante)).length,
      matific: abertas.filter((c) => comDado(c.matific)).length,
      oficiais: oficiaisDaSerie(s, indicadores),
    };
  });
  const cobertura = (com: number, abertas: number) => {
    if (abertas === 0) return <span className={CINZA}>—</span>;
    const falta = abertas - com;
    return (
      <>
        {com} de {abertas}
        {falta > 0 && <>{" "}<span className="font-medium text-amber-800 dark:text-amber-300">· falta em {falta}</span></>}
      </>
    );
  };
  return (
    <section className="space-y-2" aria-label="Em quais séries há lacunas" data-testid="lacunas-por-serie">
      <h3 className="flex items-center gap-2 text-sm font-semibold text-zinc-800 dark:text-zinc-100">
        <Rows3 size={14} className="shrink-0 text-zinc-500" aria-hidden /> Em quais séries há lacunas
      </h3>
      <TabelaRolavel rotulo="Em quais séries há lacunas: tabela completa">
        <table className="w-full text-xs" data-testid="tabela-lacunas-serie">
          <caption className="sr-only">Por série: escolas com dado de cada plataforma no período e as avaliações oficiais</caption>
          <thead>
            <tr className={`border-b border-zinc-200 dark:border-zinc-800 ${CINZA}`}>
              <th className={TH} scope="col">Série</th>
              <th className={TH} scope="col">Escolas com a série</th>
              {comElefante && <th className={TH} scope="col">Elefante: escolas com dado</th>}
              {comMatific && <th className={TH} scope="col">Matific: escolas com dado</th>}
              <th className={TH} scope="col">Avaliação oficial da série</th>
            </tr>
          </thead>
          <tbody>
            {linhas.map((l) => (
              <tr key={l.serie} className="border-b border-zinc-100 last:border-0 dark:border-zinc-800/60">
                <th scope="row" className={`${TD} text-left font-medium`}>{rotuloSerie(l.serie)}</th>
                <td className={TD}>
                  {l.escolas}
                  {l.ocultas > 0 && <>{" "}<span className={CINZA}>({l.ocultas} com a série oculta: poucos alunos)</span></>}
                </td>
                {comElefante && <td className={TD}>{cobertura(l.elefante, l.abertas)}</td>}
                {comMatific && <td className={TD}>{cobertura(l.matific, l.abertas)}</td>}
                <td className={`${TD} min-w-[10rem]`}>
                  {l.oficiais.length > 0
                    ? l.oficiais.join("; ")
                    : <span className={CINZA}>nenhuma avaliação oficial própria desta série</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </TabelaRolavel>
      <p className={CINZA}>
        “Falta em N”: escolas com a série e sem número da plataforma no período (sem coleta, sem conta ou poucos
        alunos medidos) — falta não é zero.
        {anosIniciais.length > 0 && ` ${anosIniciais.map((i) => i.nome).join(" e ")} valem para os anos iniciais`
          + " inteiros (1º ao 5º ano), não para uma série."}
        {escondidas > 0 && ` ${escondidas} escola(s) com poucos alunos não entram neste quadro, para proteger as crianças.`}
      </p>
    </section>
  );
}

// --- A tela --------------------------------------------------------------------------------

function NoPeriodo({ p, serie }: { p: RespostaPlataformas; serie: number | null }) {
  const r = p.rede;
  return (
    <>
      <p className="text-base font-semibold text-zinc-900 dark:text-white" data-testid="conclusao-plataformas">
        {conclusaoPlataformas(p, serie)}
      </p>
      <FiltrosAplicados testId="recorte-plataformas">
        Vale aqui: período ({p.janela.rotulo}) e série ({serie != null ? rotuloSerie(serie) : "1º ao 5º ano"}). Valem
        também para a evolução por bimestre, abaixo; os totais acumulados não mudam.
      </FiltrosAplicados>
      <CartoesPlataformas alunos={r.alunos} elefante={r.elefante} matific={r.matific} modulos={p.modulos}
                          suprimido={r.suprimido} textoSupressao={r.texto_supressao} textoBlocos={r.texto_blocos}
                          nivelTitulo={3} />
      {(p.modulos.elefante || p.modulos.matific) && (
        <div className="space-y-2 rounded-2xl border border-zinc-200/70 p-4 dark:border-zinc-800" data-testid="o-que-cada-numero-mede">
          <p className="text-sm font-semibold text-zinc-900 dark:text-white">O que cada número mede</p>
          <div className={`grid grid-cols-1 gap-4 ${p.modulos.elefante && p.modulos.matific ? "md:grid-cols-2" : ""}`}>
            {p.modulos.elefante && <ListaDoQueMede titulo="Elefante Letrado" metricas={METRICAS_ELEFANTE} testId="o-que-mede-elefante" />}
            {p.modulos.matific && <ListaDoQueMede titulo="Matific" metricas={METRICAS_MATIFIC} testId="o-que-mede-matific" />}
          </div>
          <p className={`text-xs ${CINZA}`}>
            Participação e médias por aluno contam só os alunos que a plataforma conhece no período (Elefante: com
            conta; Matific: com dado no período). Quem fica fora não conta como zero.
          </p>
        </div>
      )}
    </>
  );
}

function SobreOsDados({ p, base, serie }: { p: RespostaPlataformas; base: RespostaIndicadoresRede | null; serie: number | null }) {
  // Em língua simples e sem as frases da relação estatística (assunto das Análises avançadas).
  const limitacoes = textosDoFluxoPrincipal(p.limitacoes);
  return (
    <Recolhivel titulo="Sobre os dados (coletas, lacunas e limitações)" testId="sobre-os-dados">
      <div className="space-y-4">
        <section className="space-y-1" aria-label="Até onde as coletas cobrem">
          <h3 className="text-sm font-semibold text-zinc-800 dark:text-zinc-100">Até onde as coletas cobrem</h3>
          <CoberturaDasColetas cobertura={p.cobertura} escolas={base?.escolas ?? []} escolasPlataformas={p.escolas} />
        </section>
        <LacunasPorSerie dados={p} base={base} serie={serie} />
        {limitacoes.length > 0 && (
          <section className="space-y-1" aria-label="Limitações" data-testid="limitacoes-plataformas">
            <h3 className="text-sm font-semibold text-zinc-800 dark:text-zinc-100">Limitações</h3>
            <ul className="list-disc space-y-1 pl-4">{limitacoes.map((t) => <li key={t}>{t}</li>)}</ul>
          </section>
        )}
      </div>
    </Recolhivel>
  );
}

const numeroOuNull = (v: string | null): number | null => {
  if (v == null || v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
};

/**
 * O recorte só da EVOLUÇÃO: uma escola (a tabela dela aparece abaixo da rede). A série é a da
 * tela (no topo, junto do período) — vale para os cartões do período e para a evolução.
 */
function RecorteDaEvolucao({ base, escolaId, aoMudar }: {
  base: RespostaIndicadoresRede | null;
  escolaId: number | null;
  aoMudar: (m: Record<string, string | null>) => void;
}) {
  return (
    <div className="flex flex-wrap items-end gap-3" data-testid="recorte-evolucao">
      <Seletor rotulo="Escola" valor={escolaId == null ? "" : String(escolaId)} desabilitado={!base}
               aoMudar={(v) => aoMudar({ escola: v || null })}>
        <option value="">Só a rede</option>
        {porNome(base?.escolas ?? []).map((e) => <option key={e.id} value={e.id}>{e.nome}</option>)}
      </Seletor>
    </div>
  );
}

function Plataformas({ ctx }: { ctx: ContextoDaPagina }) {
  const { redeId } = ctx;
  const [params, setParams] = useSearchParams();
  const [periodo, definirPeriodo] = usePeriodoDaPagina();
  const [serie, definirSerie] = useSerieDaPagina();
  const catalogo = useCatalogo(redeId);
  const plataformas = usePlataformasDaRede(redeId, serie, periodo);
  const painel = useApi<DashboardRede>(`/redes/${redeId}/dashboard`);
  const painelDaRede = painel.dados && painel.dados.rede_id === redeId ? painel.dados : null;
  const { modulos } = useModulos();
  const plat = plataformas.dados;
  const nome = plat
    ? rotuloDasPlataformas([...(plat.modulos.elefante ? ["leitura"] : []), ...(plat.modulos.matific ? ["matematica"] : [])])
    : rotuloDasPlataformas(modulos);
  // O recorte da evolução vive na URL; só vale escola DESTA rede.
  const escolaUrl = numeroOuNull(params.get("escola"));
  const escolaEvolucao = escolaUrl != null && catalogo.dados?.escolas.some((e) => e.id === escolaUrl) ? escolaUrl : null;
  const mudarRecorte = (m: Record<string, string | null>) => {
    const prox = new URLSearchParams(params);
    for (const [k, v] of Object.entries(m)) {
      if (v == null) prox.delete(k);
      else prox.set(k, v);
    }
    setParams(prox, { replace: true });
  };

  return (
    <div className="min-w-0 space-y-6">
      <CabecalhoDaPagina titulo={nome} descricao={FRASE_PLATAFORMA} nomeRede={catalogo.dados?.rede.nome ?? null} ctx={ctx} />

      <Card className="space-y-4 p-5 sm:p-6">
        <h2 className={TITULO_SECAO}>
          <IconePastel icone={MonitorSmartphone} tom="azul" tamanho="sm" /> Uso das plataformas no período
        </h2>
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div className="flex flex-wrap items-end gap-3">
            <CampoPeriodo periodo={periodo} aoMudar={definirPeriodo} />
            <CampoSerie serie={serie} aoMudar={definirSerie} />
          </div>
          <SeloNatureza natureza="plataforma" />
        </div>
        <EstadoDaLeitura dados={plat} erro={plataformas.erro} oQue="o uso das plataformas">
          {(p) => <NoPeriodo p={p} serie={serie} />}
        </EstadoDaLeitura>
      </Card>

      {/* Com uma escola no link, a evolução espera o catálogo dizer se ela é DESTA rede (senão
          leria a rede e, logo depois, a escola — duas medições pesadas). */}
      {escolaUrl != null && !catalogo.dados && !catalogo.erro ? (
        <Card className="p-5 sm:p-6"><Carregando texto="Carregando a evolução por bimestre..." /></Card>
      ) : (
        <EvolucaoPlataformas redeId={redeId} base={catalogo.dados} serie={serie} escolaId={escolaEvolucao}
                             modulos={plat?.modulos} jaExplicadas={plat?.limitacoes}
                             recorte={<RecorteDaEvolucao base={catalogo.dados} escolaId={escolaEvolucao} aoMudar={mudarRecorte} />} />
      )}

      <Card className="space-y-4 p-5 sm:p-6">
        <h2 className={TITULO_SECAO}>
          <IconePastel icone={Sigma} tom="violeta" tamanho="sm" /> Totais acumulados
        </h2>
        {/* Cada plataforma com o seu período: o contador do Elefante é vitalício (não zera na
            virada do ano); o do Matific é cortado no ano letivo. */}
        <p className={`text-xs ${CINZA}`} data-testid="totais-quando">
          Pela coleta mais recente de cada aluno (não mudam com o período nem com a série escolhidos acima). Elefante:
          acumulado desde o início da conta de cada aluno na plataforma. Matific: no ano letivo.
        </p>
        <EstadoDaLeitura dados={painelDaRede} erro={painel.erro} oQue="os totais acumulados">
          {(d) => <TotaisAcumulados d={d} />}
        </EstadoDaLeitura>
      </Card>

      {plat && <SobreOsDados p={plat} base={catalogo.dados} serie={serie} />}

      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        {/* A tela Escolas (a lista de todas, no mesmo período e série desta tela; a ficha e o lado a lado). */}
        <LinkVer para={ctx.link("/rede/escolas", { ...periodoParaUrl(periodo), serie: serie == null ? null : String(serie) })}>
          Escolas › {nome}
        </LinkVer>
        <span className={`flex items-center gap-1.5 text-xs ${CINZA}`}>
          <CalendarRange size={13} aria-hidden /> Os números de cada escola no mesmo período e série — e, marcando de 2 a 4,
          lado a lado.
        </span>
      </div>
    </div>
  );
}

export default function PlataformasRedePagina() {
  return (
    <PaginaDaRede titulo="Elefante e Matific">
      {(ctx) => <Plataformas key={ctx.redeId} ctx={ctx} />}
    </PaginaDaRede>
  );
}
