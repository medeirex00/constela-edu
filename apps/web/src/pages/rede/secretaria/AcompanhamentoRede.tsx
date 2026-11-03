/**
 * ESCOLAS EM ACOMPANHAMENTO — `/rede/acompanhamento` (Secretaria e global; guarda `RotaRede`).
 * DESENHO2 §2.3.2.
 *
 * Onde olhar primeiro: as escolas com ao menos um sinal de ATENÇÃO, em ordem alfabética (não é
 * ranking), cada uma com DOIS blocos separados — "Nas avaliações externas" (meta oficial não
 * atingida, abaixo da rede municipal, queda desde a edição anterior; selo Oficial ou Calculado
 * pelo Constela) e "No Elefante e no Matific (ano letivo)" (selos Plataforma e Calculado pelo
 * Constela: o número vem da plataforma; "abaixo da rede", com a tolerância do Constela, é conta
 * do Constela) — e o botão "Ver a escola" (a escola vai para o contexto e a Visão da Escola
 * abre, como no Painel da Rede).
 * Depois, recolhidos: as escolas sem sinal de atenção e os dados incompletos (os sinais
 * informativos de cadastro, cobertura e proteção). CSV com todos os sinais.
 *
 * O que NÃO entra aqui (é exploratório e mora no Diagnóstico, nas Análises avançadas): níveis
 * (prioritário, acompanhar…), categorias convergente/divergente e as leituras por componente.
 *
 * Uma leitura: o diagnóstico da rede no ANO LETIVO (a parte das plataformas depende da janela;
 * as avaliações são a última edição oficial de cada escola). Só leitura; nenhum dado de aluno.
 */
import { FileDown } from "lucide-react";
import { useLocation, useNavigate } from "react-router-dom";

import { Botao } from "../../../components/ui";
import { useApp } from "../../../context/AppContext";
import { rotuloDasPlataformas, useModulos } from "../../../hooks/useModulos";
import { baixarCsv } from "../../../lib/csvRanking";
import { Recolhivel } from "../../analise/DetalhesFonte";
import { tabelaCsvAcompanhamento } from "../../analise/RelatoriosRede";
import { SeloNatureza, useDiagnostico } from "../../analise/comum";
import { porNome, textoPendencia } from "../../analise/formato";
import type { EstadoDaVisaoEscola } from "../../VisaoEscola";
import type { EscolaDiagnostico, RespostaDiagnostico, SinalDiagnostico } from "../../analise/tiposDiagnostico";
import { conclusaoAcompanhamento, escolasComAtencao } from "./conclusoes";
import { textoSimples } from "./oQueMede";
import {
  CINZA, CabecalhoDaPagina, ComoLer, EstadoDaLeitura, FraseSeparacao, PaginaDaRede, type ContextoDaPagina,
} from "./pecas";
import { ANO_LETIVO, anoDaJanela } from "./useRedeDaPagina";

const deAtencao = (e: EscolaDiagnostico, eixo: "avaliacao" | "plataforma") =>
  e.sinais.filter((s) => s.eixo === eixo && s.direcao === "atencao");

/** "No Elefante e no Matific" — só os módulos contratados (numa rede com um só, um só). */
function noNomeDasPlataformas(mods: { elefante: boolean; matific: boolean }): string {
  if (mods.elefante && !mods.matific) return "No Elefante";
  if (mods.matific && !mods.elefante) return "No Matific";
  return "No Elefante e no Matific";
}

/**
 * O módulo que a rede NÃO contratou não é dado faltando na escola: o servidor manda esse sinal
 * para CADA escola (ele serve ao Diagnóstico e fica no CSV, com o rótulo próprio). Aqui ele sai
 * da lista e da contagem dos dados incompletos; "Como ler" diz uma vez o que a rede não contratou.
 */
const MODULO_NAO_CONTRATADO = "modulo_nao_contratado";

/** O texto já começa pela referência ("IEE 2025: …", referência "IEE 2025")? Então a linha
 *  "Referência" só repetiria o rótulo (a vírgula e o "·" contam como espaço). */
const semPontuacao = (t: string) => t.replace(/[·,]/g, " ").replace(/\s+/g, " ").trim().toLowerCase();
const repeteReferencia = (s: SinalDiagnostico) => semPontuacao(s.texto).startsWith(semPontuacao(s.referencia));

/**
 * O sinal de PLATAFORMA (participação ou uso contra a rede) leva os dois selos: o número é da
 * plataforma, mas "abaixo da rede" é juízo do Constela (tolerância própria) — a mesma operação
 * que, nas avaliações, já vem como Calculado pelo Constela. O servidor manda só "plataforma".
 */
function ListaDeSinais({ sinais }: { sinais: SinalDiagnostico[] }) {
  return (
    <ul className="space-y-2">
      {sinais.map((s) => (
        <li key={`${s.codigo}-${s.referencia}-${s.texto}`}
            className="flex flex-wrap items-start gap-x-2 gap-y-1 text-sm text-zinc-800 dark:text-zinc-100">
          {s.eixo === "plataforma" ? (
            <>
              <SeloNatureza natureza="plataforma" />
              <SeloNatureza natureza="calculado" />
            </>
          ) : <SeloNatureza natureza={s.natureza} />}
          <span className="min-w-0 flex-1 break-words">
            {textoSimples(s.texto)}
            {!repeteReferencia(s) && <span className={`block text-xs ${CINZA}`}>Referência: {s.referencia}</span>}
          </span>
        </li>
      ))}
    </ul>
  );
}

function BlocoSinais({ titulo, sinais, vazio, testId }: {
  titulo: string; sinais: SinalDiagnostico[]; vazio: string; testId: string;
}) {
  return (
    <section className="min-w-0 space-y-2 rounded-2xl border border-zinc-200/70 bg-zinc-50/70 p-4 dark:border-zinc-800 dark:bg-zinc-800/40"
             aria-label={titulo} data-testid={testId}>
      <h4 className="text-sm font-semibold text-zinc-900 dark:text-white">{titulo}</h4>
      {sinais.length > 0 ? <ListaDeSinais sinais={sinais} /> : <p className={`text-xs ${CINZA}`}>{vazio}</p>}
    </section>
  );
}

function Conteudo({ d, aoVerEscola, mods }: {
  d: RespostaDiagnostico;
  aoVerEscola: (id: number) => void;
  mods: { elefante: boolean; matific: boolean };
}) {
  const escolas = porNome(d.escolas);
  const comAtencao = escolasComAtencao(d);
  const semAtencao = escolas.filter((e) => !comAtencao.some((x) => x.id === e.id));
  const comDadosIncompletos = escolas
    .map((e) => ({ e, sinais: e.sinais.filter((s) => s.eixo === "dados" && s.codigo !== MODULO_NAO_CONTRATADO) }))
    .filter((x) => x.sinais.length > 0 || x.e.pendencias.length > 0);
  const anoPlataforma = anoDaJanela(d.janela) ?? d.resumo.anos.plataforma;
  const anoAvaliacao = d.resumo.anos.avaliacao_mais_recente;
  const tituloPlataformas = `${noNomeDasPlataformas(mods)} (ano letivo${anoPlataforma != null ? ` de ${anoPlataforma}` : ""})`;
  const n = comAtencao.length;
  const conclusao = conclusaoAcompanhamento(d);
  // Rede com um só módulo: o outro não é "dado faltando" em cada escola — diz uma vez.
  const naoContratado = mods.elefante && !mods.matific ? "A rede não contratou o Matific: não há sinal de plataforma para Matemática."
    : mods.matific && !mods.elefante ? "A rede não contratou o Elefante: não há sinal de plataforma para Leitura." : null;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-lg font-semibold text-zinc-900 dark:text-white" data-testid="acompanhamento-conclusao">{conclusao}</p>
        <Botao variante="secundario" onClick={() => baixarCsv(tabelaCsvAcompanhamento(d))}>
          <FileDown size={15} aria-hidden /> Exportar sinais (CSV)
        </Botao>
      </div>

      <ComoLer testId="como-ler-acompanhamento">
        <ul className="list-disc space-y-0.5 pl-4 text-sm">
          <li>Um sinal indica onde olhar primeiro. Não é diagnóstico nem nota da escola.</li>
          <li>
            Nas avaliações externas: meta oficial não atingida, resultado abaixo da rede municipal ou queda desde a
            edição anterior.
          </li>
          <li>
            {noNomeDasPlataformas(mods)}: participação ou uso abaixo da rede municipal no ano letivo. O número é da
            plataforma; a comparação com a rede é do Constela (diferença pequena conta como “na média”).
          </li>
          <li>As duas fontes são de períodos diferentes: os sinais de uma e de outra não se somam.</li>
          {naoContratado && <li data-testid="modulo-nao-contratado">{naoContratado}</li>}
        </ul>
      </ComoLer>
      <FraseSeparacao anoAvaliacao={anoAvaliacao} anoPlataforma={anoPlataforma} />

      {n > 0 && (
        <ul className="space-y-4" data-testid="lista-acompanhamento">
          {comAtencao.map((e) => (
            <li key={e.id} className="card space-y-3 p-5" data-testid={`acompanhamento-escola-${e.id}`}>
              <div className="flex flex-wrap items-start justify-between gap-2">
                <h3 className="min-w-0 break-words text-[15px] font-semibold text-zinc-900 dark:text-white">{e.nome}</h3>
                <Botao variante="secundario" tamanho="sm" onClick={() => aoVerEscola(e.id)}
                       aria-label={`Ver a escola ${e.nome}`}>
                  Ver a escola
                </Botao>
              </div>
              <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                <BlocoSinais titulo="Nas avaliações externas" sinais={deAtencao(e, "avaliacao")} testId="bloco-avaliacoes"
                             vazio="Nenhum sinal de atenção nas avaliações externas." />
                <BlocoSinais titulo={tituloPlataformas} sinais={deAtencao(e, "plataforma")} testId="bloco-plataformas"
                             vazio="Nenhum sinal de atenção no uso das plataformas." />
              </div>
            </li>
          ))}
        </ul>
      )}

      <div className="space-y-3">
        <Recolhivel titulo={`Escolas sem sinal de atenção (${semAtencao.length})`} testId="escolas-sem-sinal">
          {semAtencao.length === 0 ? (
            <p>Todas as escolas têm algum sinal de atenção.</p>
          ) : (
            <>
              <ul className="list-disc space-y-0.5 pl-4">{semAtencao.map((e) => <li key={e.id}>{e.nome}</li>)}</ul>
              <p>
                Sem sinal não quer dizer sem problema: pode faltar meta oficial, comparação com a rede ou dado da
                plataforma — veja os dados incompletos.
              </p>
            </>
          )}
        </Recolhivel>
        <Recolhivel titulo={`Dados incompletos (${comDadosIncompletos.length} escola${comDadosIncompletos.length === 1 ? "" : "s"})`}
                    testId="dados-incompletos">
          {comDadosIncompletos.length === 0 ? (
            <p>Nenhuma escola com dado faltando nesta leitura.</p>
          ) : (
            <ul className="space-y-3">
              {comDadosIncompletos.map(({ e, sinais }) => (
                <li key={e.id} className="space-y-1.5" data-testid={`dados-incompletos-${e.id}`}>
                  <p className="font-semibold text-zinc-800 dark:text-zinc-100">{e.nome}</p>
                  {e.pendencias.length > 0 && (
                    <p>Cadastro: {e.pendencias.map(textoPendencia).join("; ")}.</p>
                  )}
                  {sinais.length > 0 && <ListaDeSinais sinais={sinais} />}
                </li>
              ))}
            </ul>
          )}
        </Recolhivel>
      </div>
    </div>
  );
}

function Acompanhamento({ ctx }: { ctx: ContextoDaPagina }) {
  const { redeId } = ctx;
  const diagnostico = useDiagnostico(redeId, ANO_LETIVO);
  const diag = diagnostico.dados && diagnostico.dados.rede.id === redeId ? diagnostico.dados : null;
  const { selecionarEscola } = useApp();
  const navegar = useNavigate();
  const { leitura, matematica } = useModulos();
  const mods = diag?.modulos ?? { elefante: leitura, matific: matematica };
  const { pathname, search } = useLocation();
  // A escola vai para o contexto (o backend autoriza: é da rede) e a Visão da Escola abre —
  // o mesmo caminho do Painel da Rede —, com o "Voltar" para ESTA lista (e o ?rede= do global).
  const verEscola = (id: number) => {
    selecionarEscola(id);
    const volta: EstadoDaVisaoEscola = {
      voltar: { caminho: `${pathname}${search}`, texto: "Voltar para Escolas em acompanhamento" },
    };
    navegar("/escola", { state: volta });
  };
  const nomePlataformas = rotuloDasPlataformas([...(mods.elefante ? ["leitura"] : []), ...(mods.matific ? ["matematica"] : [])]);
  return (
    <div className="min-w-0 space-y-6">
      <CabecalhoDaPagina
        titulo="Escolas em acompanhamento"
        descricao={`Onde olhar primeiro: as escolas com algum sinal de atenção nas avaliações externas ou no uso do ${nomePlataformas}.`}
        nomeRede={diag?.rede.nome ?? null}
        ctx={ctx}
      />
      <EstadoDaLeitura dados={diag} erro={diagnostico.erro} oQue="as escolas em acompanhamento">
        {(d) => <Conteudo d={d} aoVerEscola={verEscola} mods={mods} />}
      </EstadoDaLeitura>
    </div>
  );
}

export default function AcompanhamentoRede() {
  return (
    <PaginaDaRede titulo="Escolas em acompanhamento">
      {(ctx) => <Acompanhamento key={ctx.redeId} ctx={ctx} />}
    </PaginaDaRede>
  );
}
