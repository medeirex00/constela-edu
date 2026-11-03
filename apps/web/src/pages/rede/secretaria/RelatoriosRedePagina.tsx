/**
 * RELATÓRIOS E EXPORTAÇÕES — `/rede/relatorios` (Secretaria e global; guarda `RotaRede`).
 * DESENHO2 §2.3.6.
 *
 * Dois grupos simples, cada item dizendo O QUE contém e DE QUANDO são os números:
 *
 *  - "Documento para reuniões": o Boletim da rede em PDF (a rota de sempre, `/redes/{id}/
 *    boletim`, pela mesma `apiDownload` do Painel da Rede). Ele e o Ranking dizem o período de
 *    cada parte: alunos do ano letivo corrente, livros do Elefante desde o início da conta de
 *    cada aluno (o contador é vitalício) e Matific no ano letivo — só os módulos contratados;
 *  - "Planilhas (CSV)": Avaliações por escola; Elefante e Matific por escola no período (com o
 *    período e a série, padrão ano letivo e do 1º ao 5º ano — a série vai no "de quando" e no
 *    nome do arquivo); Escolas em acompanhamento (os sinais); e o Ranking da Rede (leva à tela,
 *    que tem o CSV da lista).
 *
 * Os CSV saem de `lib/csvRanking` (";", BOM, proteção contra fórmula) com as MESMAS respostas
 * que as telas mostram — nenhum número calculado aqui; ausência e proteção escritas. O CSV do
 * Diagnóstico exploratório não fica aqui: mora na área avançada (aba Diagnóstico).
 */
import { ClipboardCheck, FileDown, FileSearch, FileText, Flag, FlaskConical, ListOrdered, MonitorSmartphone, Sheet } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { Botao, IconePastel } from "../../../components/ui";
import { rotuloDasPlataformas, useModulos } from "../../../hooks/useModulos";
import { usePerfil } from "../../../hooks/usePerfil";
import { apiDownload } from "../../../lib/api";
import { baixarCsv } from "../../../lib/csvRanking";
import { dataHora } from "../../../lib/formato";
import {
  CLASSE_LINK, CartaoRelatorio, tabelaCsvAcompanhamento, tabelaCsvAvaliacoes, tabelaCsvPlataformas,
} from "../../analise/RelatoriosRede";
import { useDiagnostico, usePlataformasDaRede } from "../../analise/comum";
import { diaBR, rotuloSerie } from "../../analise/formato";
import {
  AvisoOutraRede, CINZA, CabecalhoDaPagina, CampoPeriodo, CampoSerie, PaginaDaRede, TITULO_SECAO, type ContextoDaPagina,
} from "./pecas";
import { ANO_LETIVO, anoDaJanela, useCatalogo, usePeriodoDaPagina, useSerieDaPagina } from "./useRedeDaPagina";

function Relatorios({ ctx }: { ctx: ContextoDaPagina }) {
  const { redeId } = ctx;
  const { global } = usePerfil();
  const catalogo = useCatalogo(redeId);
  const diagnostico = useDiagnostico(redeId, ANO_LETIVO);
  const [periodo, definirPeriodo] = usePeriodoDaPagina();
  const [serie, definirSerie] = useSerieDaPagina();
  const plataformas = usePlataformasDaRede(redeId, serie, periodo);
  const diag = diagnostico.dados && diagnostico.dados.rede.id === redeId ? diagnostico.dados : null;
  const base = catalogo.dados;
  const plat = plataformas.dados;
  // O nome segue os módulos CONTRATADOS (o da leitura das plataformas; antes dela, os da conta):
  // numa rede só com o Matific, a planilha não promete o Elefante.
  const { modulos } = useModulos();
  const nomePlataformas = plat
    ? rotuloDasPlataformas([...(plat.modulos.elefante ? ["leitura"] : []), ...(plat.modulos.matific ? ["matematica"] : [])])
    : rotuloDasPlataformas(modulos);
  const comElefante = plat ? plat.modulos.elefante : modulos.includes("leitura");
  const comMatific = plat ? plat.modulos.matific : modulos.includes("matematica");
  const contemPlataformas = [
    "Uma linha por escola: alunos",
    comElefante ? "participação, livros novos, minutos e acerto do Elefante" : null,
    comMatific ? "participação, atividades e desempenho do Matific" : null,
    "a situação da coleta.",
  ].filter(Boolean).join("; ");
  // O Boletim e o Ranking leem o retrato das plataformas, que NÃO é todo do ano letivo: os
  // alunos são os do ano letivo corrente e o Matific é cortado nele, mas o contador de livros
  // do Elefante é vitalício (desde o início da conta de cada aluno). Só o módulo contratado.
  const periodoDoRetrato = [
    "alunos do ano letivo corrente",
    comElefante ? "livros do Elefante acumulados desde o início da conta de cada aluno" : null,
    comMatific ? "Matific no ano letivo" : null,
  ].filter(Boolean).join("; ");
  const [baixando, setBaixando] = useState(false);
  const [erroBoletim, setErroBoletim] = useState<string | null>(null);

  async function baixarBoletim() {
    setBaixando(true);
    setErroBoletim(null);
    try {
      await apiDownload(`/redes/${redeId}/boletim`);
    } catch (e) {
      setErroBoletim(e instanceof Error ? e.message : "Não foi possível gerar o boletim.");
    } finally {
      setBaixando(false);
    }
  }

  const edicoes = diag ? [...new Set(diag.escolas.flatMap((e) => e.oficiais.map((o) => o.edicao)))].sort() : [];
  const quandoAval = diagnostico.erro && !diag ? "não foi possível carregar as avaliações por escola."
    : !diag ? "carregando…"
      : edicoes.length === 0 ? "nenhuma escola tem resultado oficial importado ainda."
        : `a última edição com número oficial de cada escola (${edicoes.length === 1
          ? `edição ${edicoes[0]}` : `edições de ${edicoes[0]} a ${edicoes[edicoes.length - 1]}`}).`;
  // A última coleta só das plataformas contratadas.
  const ultima = plat ? [
    comElefante && plat.cobertura.ultima_coleta.elefante ? `Elefante ${diaBR(plat.cobertura.ultima_coleta.elefante)}` : null,
    comMatific && plat.cobertura.ultima_coleta.matific ? `Matific ${diaBR(plat.cobertura.ultima_coleta.matific)}` : null,
  ].filter(Boolean).join(", ") : "";
  const quandoPlat = plataformas.erro && !plat ? "não foi possível carregar as plataformas."
    : !plat ? "carregando…"
      : `${plat.janela.rotulo.toLowerCase()}${plat.janela.inicio && plat.janela.fim
        ? ` (${diaBR(plat.janela.inicio)} a ${diaBR(plat.janela.fim)})` : ""}; série: ${serie != null
        ? rotuloSerie(serie) : "1º ao 5º ano"}; última coleta: ${ultima || "nenhuma registrada"}.`;
  const anoPlat = diag ? anoDaJanela(diag.janela) ?? diag.resumo.anos.plataforma : null;
  const quandoAcomp = diagnostico.erro && !diag ? "não foi possível carregar os sinais."
    : !diag ? "carregando…"
      : `avaliações: a última edição oficial de cada escola${diag.resumo.anos.avaliacao_mais_recente != null
        ? ` (até ${diag.resumo.anos.avaliacao_mais_recente})` : ""}; plataformas: ano letivo${anoPlat != null ? ` de ${anoPlat}` : ""}. `
        + `Gerado em ${dataHora(diag.gerado_em)}.`;

  return (
    <div className="min-w-0 space-y-6">
      <CabecalhoDaPagina
        titulo="Relatórios e exportações"
        descricao="Para levar os números a uma reunião ou a uma planilha: cada item diz o que contém e de quando são os números."
        nomeRede={base?.rede.nome ?? diag?.rede.nome ?? null}
        ctx={ctx}
      />

      <section className="space-y-3" aria-label="Documento para reuniões" data-testid="grupo-documento">
        <h2 className={TITULO_SECAO}>
          <IconePastel icone={FileText} tom="violeta" tamanho="sm" /> Documento para reuniões
        </h2>
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <CartaoRelatorio
            testId="relatorio-boletim" icone={FileDown} tom="violeta" titulo="Boletim da rede (PDF)"
            contem="O retrato do uso das plataformas na rede: a diferença entre escolas, as escolas que pedem atenção pelo critério de uso, a ordem das escolas pelo índice do Constela e as que ficam fora da comparação. Não traz as avaliações oficiais."
            quando={`${periodoDoRetrato}; calculado na hora do download.`}
            erro={erroBoletim}
            acao={(
              <Botao onClick={baixarBoletim} disabled={baixando}>
                <FileDown size={15} aria-hidden /> {baixando ? "Gerando..." : "Baixar boletim (PDF)"}
              </Botao>
            )} />
        </div>
      </section>

      <section className="space-y-3" aria-label="Planilhas (CSV)" data-testid="grupo-planilhas">
        <h2 className={TITULO_SECAO}>
          <IconePastel icone={Sheet} tom="teal" tamanho="sm" /> Planilhas (CSV)
        </h2>
        <p className={`text-xs ${CINZA}`}>Abrem no Excel em português (separador “;”). Sem dado e protegido saem escritos — nunca 0.</p>
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <CartaoRelatorio
            testId="relatorio-avaliacoes" icone={ClipboardCheck} tom="violeta" titulo="Avaliações por escola (CSV)"
            contem="Uma linha por escola e avaliação: o resultado oficial com a edição, a meta e a situação oficiais, a rede municipal na mesma edição, a diferença e a posição (calculadas pelo Constela) e se subiu ou caiu desde a edição anterior."
            quando={quandoAval}
            erro={diagnostico.erro && !diag ? diagnostico.erro.message : null}
            acao={(
              <Botao variante="secundario" disabled={!diag || !base}
                     onClick={() => diag && base && baixarCsv(tabelaCsvAvaliacoes(diag, base))}>
                <FileDown size={15} aria-hidden /> Exportar avaliações (CSV)
              </Botao>
            )} />
          <CartaoRelatorio
            testId="relatorio-plataformas" icone={MonitorSmartphone} tom="azul"
            titulo={`${nomePlataformas} por escola no período (CSV)`}
            contem={contemPlataformas}
            quando={quandoPlat}
            erro={plataformas.erro && !plat ? plataformas.erro.message : null}
            acao={(
              <div className="flex w-full flex-col gap-3">
                <div className="flex flex-wrap items-end gap-3">
                  <CampoPeriodo periodo={periodo} aoMudar={definirPeriodo} />
                  <CampoSerie serie={serie} aoMudar={definirSerie} />
                </div>
                <div>
                  <Botao variante="secundario" disabled={!plat}
                         onClick={() => plat && baixarCsv(tabelaCsvPlataformas(plat, undefined, serie))}>
                    <FileDown size={15} aria-hidden /> Exportar plataformas (CSV)
                  </Botao>
                </div>
              </div>
            )} />
          <CartaoRelatorio
            testId="relatorio-acompanhamento" icone={Flag} tom="ambar" titulo="Escolas em acompanhamento (CSV)"
            contem="Uma linha por sinal: a escola, onde ele aparece (avaliações externas, Elefante e Matific ou dados incompletos), se é de atenção, favorável ou informativo, a natureza e a referência."
            quando={quandoAcomp}
            erro={diagnostico.erro && !diag ? diagnostico.erro.message : null}
            acao={(
              <Botao variante="secundario" disabled={!diag} onClick={() => diag && baixarCsv(tabelaCsvAcompanhamento(diag))}>
                <FileDown size={15} aria-hidden /> Exportar sinais (CSV)
              </Botao>
            )} />
          <CartaoRelatorio
            testId="relatorio-ranking" icone={ListOrdered} tom="teal" titulo="Ranking da Rede"
            contem={(
              <>
                A ordem das escolas pelo índice das plataformas (geral, leitura, matemática e engajamento). A planilha da
                lista sai na própria tela.
                <AvisoOutraRede ctx={ctx} tela="O Ranking da Rede" />
              </>
            )}
            quando={`${periodoDoRetrato}.`}
            acao={<Link to="/rede/ranking" className={CLASSE_LINK}><ListOrdered size={15} aria-hidden /> Abrir o Ranking da Rede</Link>} />
        </div>
      </section>

      <div className={`space-y-1.5 text-xs ${CINZA}`} data-testid="outros-arquivos">
        <p className="flex flex-wrap items-center gap-1.5">
          <FileSearch size={14} aria-hidden className="shrink-0 text-indigo-500" />
          <span>
            Os arquivos oficiais de cada número:{" "}
            <Link to="/rede/avaliacoes" className="font-medium text-indigo-700 hover:underline dark:text-indigo-400">
              {global ? "importações e fontes" : "fontes e arquivos oficiais"}
            </Link>.
          </span>
        </p>
        <p className="flex flex-wrap items-center gap-1.5">
          <FlaskConical size={14} aria-hidden className="shrink-0 text-indigo-500" />
          <span>
            A planilha do diagnóstico exploratório fica nas{" "}
            <Link to={ctx.link("/rede/analise")} className="font-medium text-indigo-700 hover:underline dark:text-indigo-400">
              Análises avançadas
            </Link>.
          </span>
        </p>
      </div>
    </div>
  );
}

export default function RelatoriosRedePagina() {
  return (
    <PaginaDaRede titulo="Relatórios e exportações">
      {(ctx) => <Relatorios key={ctx.redeId} ctx={ctx} />}
    </PaginaDaRede>
  );
}
