/**
 * AVALIAÇÕES EXTERNAS — `/rede/avaliacoes-externas` (Secretaria e global; guarda `RotaRede`).
 * DESENHO2 §2.3.4.
 *
 * Da conclusão ao detalhe:
 *
 *  1. "Antes de comparar": cada avaliação tem escala e calendário próprios — compare cada uma
 *     com ela mesma (de uma edição para outra) e com a meta, quando houver;
 *  2. "Indicadores disponíveis": um cartão por indicador do catálogo (ICA, SARESP, IEE, Ideb,
 *     Saeb), com a conclusão (o resultado da rede e a situação da meta, ou "por escola" no IEE),
 *     o "O que mede", quem publica, a frequência, a DISPONIBILIDADE (a edição mais recente
 *     importada e quantas há, ou "nenhuma edição oficial importada") e a meta. Indicador
 *     indisponível: o cartão diz o motivo ("ainda não importado"…). Fora dos cartões, à parte,
 *     a Estimativa Constela e os números sem registro oficial (não são resultado oficial);
 *  3. O DETALHE do indicador escolhido ("Ver série histórica e escolas"): o `PorIndicador`
 *     inteiro — série histórica (comparar edições), escolas numa edição (comparar escolas; o
 *     nome leva à ficha da escola), "Detalhes e fontes" —, com a escola num campo do próprio
 *     detalhe (a tela não tem filtros no topo);
 *  4. "Todas as escolas na edição mais recente de cada avaliação": a tabela de comparação entre
 *     escolas (`TabelaComparacaoEscolas`), em ordem alfabética, a ausência por extenso e o nome
 *     levando à ficha da escola (`/rede/escolas/{id}`, com o `?rede=` do global). Cada coluna fica
 *     na edição de referência (a mais recente com resultado entre as escolas): a escola cujo
 *     último resultado é de edição anterior não mostra o número ali — diz o ano dele por extenso
 *     (fica na ficha) —, e a conclusão conta só a edição de referência de cada série. Sem número
 *     oficial em escola nenhuma, a frase diz por quê e as escolas continuam listadas;
 *  5. Recolhidos: os avisos sobre os dados oficiais (cadastro, desatualizado, sem registro…) e
 *     como ler estes números (a metodologia em linguagem simples).
 *
 * Os parâmetros do detalhe vivem na URL (`?indicador=&etapa=&componente=&visao=&edicao=&de=&ate=
 * &abrangencia=&escola=`): os links antigos (`/rede/analise?ver=indicador…` e `?ver=avaliacoes…`)
 * chegam aqui com eles. Quem chega com `?indicador=` vai direto ao detalhe (a página rola até
 * ele) — só nessa chegada e no clique do cartão; mexer nas dimensões do detalhe não rola.
 *
 * Leituras: o catálogo ao abrir (o detalhe lê o indicador escolhido). A tabela das escolas lê o
 * diagnóstico — leitura PESADA — só quando a seção chega perto da tela (ou a pessoa pede): a
 * página inteira já está pronta antes, e a seção diz "carregando" sem travar nada. Só leitura.
 * O link de fonte leva aos arquivos oficiais (`/rede/avaliacoes`); nenhum leva às Análises
 * avançadas nem aos Relatórios.
 */
import { AlertTriangle, ArrowRight, BookOpenText, FileSearch, GitCompareArrows, Table2 } from "lucide-react";
import { useCallback, useEffect, useId, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { Botao, Card, IconePastel } from "../../../components/ui";
import { usePerfil } from "../../../hooks/usePerfil";
import { TabelaComparacaoEscolas } from "../../analise/AvaliacoesExternas";
import DetalhesEFontes, { Recolhivel } from "../../analise/DetalhesFonte";
import PorIndicador from "../../analise/PorIndicador";
import { CLASSE_LINK } from "../../analise/RelatoriosRede";
import { MiniTendencia, SeloNatureza, useDiagnostico } from "../../analise/comum";
import { MARCA_SEM_REGISTRO, TEXTO_SEM_REGISTRO, porNome, textoIndisponivel } from "../../analise/formato";
import type { AlertaAnalise, IndicadorAnalise, RespostaIndicadoresRede } from "../../analise/tipos";
import { Nota } from "../IdebBlocos";
import { conclusaoComparacaoAvaliacoes, conclusaoIndicador } from "./conclusoes";
import { explicacaoDe, textoSimples, textosDoFluxoPrincipal } from "./oQueMede";
import {
  CINZA, CabecalhoDaPagina, ComoLer, EstadoDaLeitura, PaginaDaRede, TITULO_SECAO, type ContextoDaPagina,
} from "./pecas";
import { ANO_LETIVO, useCatalogo } from "./useRedeDaPagina";

const numeroOuNull = (v: string | null): number | null => {
  if (v == null || v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
};

/** As dimensões do detalhe que um indicador novo não herda do anterior. */
const DIMENSOES_LIMPAS = { etapa: null, componente: null, de: null, ate: null, edicao: null, visao: null, abrangencia: null };

/**
 * A disponibilidade do indicador nesta rede, em uma linha: "edição mais recente importada: 2025
 * (2 edições: 2024 e 2025)" — ou "nenhuma edição oficial importada" (o motivo fica no topo do
 * cartão). Só conta edição com número OFICIAL (a do catálogo): estimativa e número sem registro
 * não entram.
 */
function textoDisponibilidade(ind: Pick<IndicadorAnalise, "edicoes" | "edicao_mais_recente">): string {
  const edicoes = [...new Set(ind.edicoes)].sort((a, b) => a - b);
  const ultima = ind.edicao_mais_recente ?? edicoes[edicoes.length - 1] ?? null;
  if (ultima == null) return "nenhuma edição oficial importada";
  const quantas = edicoes.length <= 1 ? "a única"
    : edicoes.length === 2 ? `2 edições: ${edicoes[0]} e ${edicoes[1]}`
      : `${edicoes.length} edições, de ${edicoes[0]} a ${edicoes[edicoes.length - 1]}`;
  return `edição mais recente importada: ${ultima} (${quantas})`;
}

function CartaoIndicador({ ind, c, aberto, aoAbrir, idDetalhe }: {
  ind: IndicadorAnalise;
  c: RespostaIndicadoresRede;
  aberto: boolean;
  aoAbrir: () => void;
  idDetalhe: string;
}) {
  const ex = explicacaoDe(ind.chave);
  const sigla = ex?.sigla ?? ind.nome;
  const destaque = c.destaques.find((d) => d.indicador === ind.chave && d.valor != null) ?? null;
  const idTitulo = useId();
  return (
    <article
      aria-labelledby={idTitulo}
      data-testid={`indicador-cartao-${ind.chave}`}
      className={`flex min-w-0 flex-col gap-2.5 rounded-2xl border p-5 ${
        !ind.disponivel
          ? "border-dashed border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900"
          : aberto
            ? "border-indigo-400 bg-indigo-50/60 ring-1 ring-indigo-400 dark:border-indigo-500/50 dark:bg-indigo-500/10"
            : "border-zinc-200/70 bg-zinc-50/70 dark:border-zinc-800 dark:bg-zinc-800/40"
      }`}>
      <h3 id={idTitulo} className="break-words text-[15px] font-semibold text-zinc-900 dark:text-white">
        {sigla}
        {ex && sigla !== ex.nomeCompleto && (
          <span className={`block text-xs font-normal ${CINZA}`}>{ex.nomeCompleto}</span>
        )}
      </h3>
      {ind.disponivel ? (
        <>
          <p className="text-sm font-semibold text-zinc-900 dark:text-white" data-testid={`indicador-conclusao-${ind.chave}`}>
            {conclusaoIndicador(ind, c)}
          </p>
          {/* A rede edição a edição, em miniatura (a linha quebra no ano sem resultado). */}
          {destaque && (
            <MiniTendencia serie={destaque.serie} rotulo={destaque.rotulo} casas={destaque.casas} unidade={destaque.unidade} />
          )}
        </>
      ) : (
        <p className="text-sm font-medium text-amber-800 dark:text-amber-300" data-testid={`indicador-indisponivel-${ind.chave}`}>
          Ainda não disponível: {textoSimples(textoIndisponivel(ind))}.
        </p>
      )}
      {ex && (
        <p className="text-xs text-zinc-700 dark:text-zinc-200" data-o-que-mede>
          <span className="font-semibold">O que mede:</span> {ex.oQueMede} {ex.abrangencia}
        </p>
      )}
      <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-0.5 text-xs text-zinc-600 dark:text-zinc-300">
        <dt className="font-medium">Quem publica</dt><dd className="break-words">{ind.orgao}</dd>
        <dt className="font-medium">Frequência</dt><dd className="break-words">{ex?.frequencia ?? "conforme o órgão"}</dd>
        <dt className="font-medium">Disponibilidade</dt>
        <dd className="break-words" data-testid={`indicador-disponibilidade-${ind.chave}`}>{textoDisponibilidade(ind)}</dd>
        <dt className="font-medium">Meta</dt>
        <dd className="break-words">{ex?.meta ?? (ind.tem_meta ? "Com meta" : "Sem meta")}</dd>
      </dl>
      <div className="mt-auto flex flex-wrap items-center justify-between gap-2 pt-1">
        <SeloNatureza natureza="oficial" />
        {ind.disponivel && (
          <button type="button" onClick={aoAbrir} aria-controls={idDetalhe}
                  aria-label={`Ver série histórica e escolas — ${sigla}`}
                  className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs font-semibold text-indigo-700 transition-colors hover:bg-indigo-50 dark:text-indigo-300 dark:hover:bg-indigo-500/10">
            Ver série histórica e escolas <ArrowRight size={12} aria-hidden />
          </button>
        )}
      </div>
    </article>
  );
}

const ROTULO_ALERTA: Record<string, string> = {
  cadastro: "Cadastro",
  desatualizado: "Desatualizado",
  insuficiente: "Dados insuficientes",
  sem_registro: "Sem registro oficial",
  ausente: "Sem dado",
};
/** Alertas que levam às escolas do indicador (o motivo de cada escola está lá). */
const ALERTAS_COM_ESCOLAS = new Set(["insuficiente", "sem_registro"]);

function AvisosDosDados({ alertas, c, aoVerEscolas }: {
  alertas: AlertaAnalise[];
  c: RespostaIndicadoresRede;
  aoVerEscolas: (chave: string, edicao: number) => void;
}) {
  return (
    <ul className="space-y-2" data-testid="alertas-analise">
      {alertas.map((a, i) => {
        // Em ordem de nome (sem cara de ranking).
        const nomes = porNome(a.escolas.map((id) => ({ nome: c.escolas.find((e) => e.id === id)?.nome ?? `escola ${id}` })))
          .map((e) => e.nome);
        const ind = a.indicador ? c.indicadores.find((x) => x.chave === a.indicador) : undefined;
        const podeVer = ALERTAS_COM_ESCOLAS.has(a.tipo) && ind && ind.disponivel && ind.por_escola
          && ind.edicao_mais_recente != null;
        return (
          <li key={`${a.tipo}-${i}`} className="flex items-start gap-2 rounded-xl border border-ouro-200 bg-ouro-50 px-3 py-2.5 text-zinc-800 dark:border-ouro-400/25 dark:bg-ouro-400/10 dark:text-zinc-100">
            <AlertTriangle size={14} aria-hidden className="mt-0.5 shrink-0 text-ouro-700 dark:text-ouro-300" />
            <div className="min-w-0 break-words">
              <span className="font-semibold">{ROTULO_ALERTA[a.tipo] ?? a.tipo}:</span> {textoSimples(a.texto)}
              {nomes.length > 0 && <span className="mt-0.5 block">{nomes.join(", ")}</span>}
              {podeVer && (
                <button type="button" onClick={() => aoVerEscolas(ind.chave, ind.edicao_mais_recente as number)}
                        className="mt-1 inline-flex items-center gap-1 font-semibold text-indigo-700 hover:underline dark:text-indigo-300">
                  ver as escolas de {explicacaoDe(ind.chave)?.sigla ?? ind.nome} {ind.edicao_mais_recente}
                  <ArrowRight size={12} aria-hidden />
                </button>
              )}
            </div>
          </li>
        );
      })}
    </ul>
  );
}

/** A tabela das escolas (só monta quando a seção é pedida): o diagnóstico no ano letivo — o
 *  MESMO pedido das outras telas, que dividem a leitura — e o catálogo que a página já tem. */
function TabelaDasEscolas({ c, ctx }: { c: RespostaIndicadoresRede; ctx: ContextoDaPagina }) {
  const diagnostico = useDiagnostico(ctx.redeId, ANO_LETIVO);
  const diag = diagnostico.dados && diagnostico.dados.rede.id === ctx.redeId ? diagnostico.dados : null;
  return (
    <EstadoDaLeitura dados={diag} erro={diagnostico.erro} oQue="as escolas">
      {(d) => (
        <>
          {/* Sem número oficial em escola nenhuma, a própria tabela diz por quê (sem repetir aqui). */}
          {d.escolas.some((e) => e.oficiais.length > 0) && (
            <>
              <p className="text-base font-semibold text-zinc-900 dark:text-white" data-testid="conclusao-escolas-avaliacoes">
                {conclusaoComparacaoAvaliacoes(d)}
              </p>
              {/* A natureza à vista, junto da conclusão: o resultado é oficial; a posição contra a
                  rede é conta do Constela, com tolerância. */}
              <p className={`flex flex-wrap items-center gap-x-2 gap-y-1 text-xs ${CINZA}`} data-testid="natureza-escolas">
                <SeloNatureza natureza="oficial" />
                <span className="min-w-0 break-words">resultados e metas oficiais</span>
                <SeloNatureza natureza="calculado" />
                <span className="min-w-0 break-words">
                  acima ou abaixo da rede municipal na mesma edição (diferença pequena conta como “na média”)
                </span>
              </p>
            </>
          )}
          <TabelaComparacaoEscolas dados={d} base={c} linkDaEscola={(id) => ctx.link(`/rede/escolas/${id}`)} />
        </>
      )}
    </EstadoDaLeitura>
  );
}

/**
 * "Todas as escolas na edição mais recente de cada avaliação". O diagnóstico é leitura pesada:
 * a tabela só é pedida quando a seção chega perto da tela (ou a pessoa pede antes) — quem só
 * olha os cartões não espera por ela, e a página nunca fica travada.
 */
function TodasAsEscolas({ c, ctx }: { c: RespostaIndicadoresRede; ctx: ContextoDaPagina }) {
  const ref = useRef<HTMLElement>(null);
  const [pedida, setPedida] = useState(false);
  const idTitulo = useId();
  useEffect(() => {
    if (pedida) return undefined;
    // Navegador sem o observador: lê logo (a seção diz "carregando"; o resto da página já está pronto).
    if (typeof IntersectionObserver === "undefined") {
      setPedida(true);
      return undefined;
    }
    const el = ref.current;
    if (!el) return undefined;
    const observador = new IntersectionObserver((entradas) => {
      if (entradas.some((e) => e.isIntersecting)) setPedida(true);
    }, { rootMargin: "300px 0px" });
    observador.observe(el);
    return () => observador.disconnect();
  }, [pedida]);
  return (
    <section ref={ref} aria-labelledby={idTitulo} data-testid="todas-as-escolas">
      <Card className="space-y-4 p-5 sm:p-6">
        <h2 id={idTitulo} className={TITULO_SECAO}>
          <IconePastel icone={Table2} tom="violeta" tamanho="sm" />
          <span className="min-w-0 break-words">Todas as escolas na edição mais recente de cada avaliação</span>
        </h2>
        <p className={`text-sm ${CINZA}`}>
          Uma linha por escola da rede, em ordem alfabética (não é ranking). Cada coluna é uma avaliação na edição
          mais recente com resultado entre as escolas, com o ano em cada célula; a escola sem resultado nessa edição
          diz de quando é o último oficial dela, que fica na ficha da escola. Compare cada escola com a rede municipal
          na mesma edição e com ela mesma — cada avaliação tem escala própria. O nome da escola abre a ficha dela.
        </p>
        {pedida ? <TabelaDasEscolas c={c} ctx={ctx} /> : (
          <div className="flex flex-wrap items-center gap-3" data-testid="escolas-a-carregar">
            <p className={`min-w-0 text-sm ${CINZA}`}>As escolas aparecem quando esta parte da página fica à vista.</p>
            <Botao type="button" variante="secundario" tamanho="sm" onClick={() => setPedida(true)}>
              Mostrar as escolas agora
            </Botao>
          </div>
        )}
      </Card>
    </section>
  );
}

function Conteudo({ c, ctx }: { c: RespostaIndicadoresRede; ctx: ContextoDaPagina }) {
  const [params, setParams] = useSearchParams();
  const { global } = usePerfil();
  const idDetalhe = useId();
  const atualizar = useCallback((mudancas: Record<string, string | null>) => {
    const prox = new URLSearchParams(params);
    for (const [k, v] of Object.entries(mudancas)) {
      if (v == null || v === "") prox.delete(k);
      else prox.set(k, v);
    }
    setParams(prox, { replace: true });
  }, [params, setParams]);

  const aberto = c.indicadores.find((i) => i.chave === params.get("indicador")) ?? null;
  const escolaUrl = numeroOuNull(params.get("escola"));
  // Só vale escola DESTA rede (um link antigo de outra rede não filtra nada).
  const escolaId = escolaUrl != null && c.escolas.some((e) => e.id === escolaUrl) ? escolaUrl : null;

  // Rolar até o detalhe é PEDIDO (a chegada com ?indicador=, o clique num cartão ou num aviso),
  // não resto da URL: depois de rolar, mexer nas dimensões do detalhe não rola de novo.
  const refDetalhe = useRef<HTMLDivElement>(null);
  const pedidoRolar = useRef(params.has("indicador"));
  const chaveAberta = aberto?.chave ?? null;
  const pedido = params.toString();
  useEffect(() => {
    if (!pedidoRolar.current || chaveAberta == null) return;
    pedidoRolar.current = false;
    refDetalhe.current?.scrollIntoView?.({ block: "start" });
  }, [chaveAberta, pedido]);

  function abrir(chave: string, extras: Record<string, string | null> = {}) {
    const mudancas = { indicador: chave, ...DIMENSOES_LIMPAS, ...extras };
    const prox = new URLSearchParams(params);
    for (const [k, v] of Object.entries(mudancas)) {
      if (v == null || v === "") prox.delete(k);
      else prox.set(k, v);
    }
    // O mesmo detalhe já aberto (a URL não muda, o efeito não roda): rola agora.
    if (prox.toString() === params.toString()) {
      refDetalhe.current?.scrollIntoView?.({ block: "start" });
      return;
    }
    pedidoRolar.current = true;
    atualizar(mudancas);
  }

  // O detalhe abre no MESMO recorte que o cartão mostra: o destaque da rede é a etapa ×
  // componente de edição mais nova (não necessariamente a primeira, o padrão da API). Sem
  // destaque, fica o padrão da API.
  const recorteDoCartao = (chave: string): Record<string, string | null> => {
    const d = c.destaques.find((x) => x.indicador === chave && x.valor != null);
    return { etapa: d?.etapa ?? null, componente: d?.componente ?? null };
  };
  // Os avisos de "metodologia" falam da relação entre avaliações e plataformas — esta tela não
  // mostra plataformas, e o "Antes de comparar" do topo já orienta a leitura.
  const alertas = c.alertas.filter((a) => a.tipo !== "metodologia");

  const semRegistro = c.sem_registro_oficial ?? [];
  const sigla = aberto ? explicacaoDe(aberto.chave)?.sigla ?? aberto.nome : null;
  // A metodologia em língua simples e sem a da relação estatística (essa mora nas Análises
  // avançadas, aba Relação, com o método completo).
  const metodologia = textosDoFluxoPrincipal(c.metodologia_resumo);

  return (
    <div className="space-y-6">
      <ComoLer titulo="Antes de comparar" testId="antes-de-comparar">
        <p>
          Cada avaliação tem escala e calendário próprios: um resultado do SARESP e um do Ideb não se comparam. Compare
          cada uma com ela mesma — de uma edição para outra — e com a meta, quando houver.
        </p>
      </ComoLer>

      <section className="space-y-4" aria-label="Indicadores disponíveis">
        <h2 className={TITULO_SECAO}>Indicadores disponíveis</h2>
        {c.indicadores.length === 0 ? (
          <p className={`text-sm ${CINZA}`}>Nenhum indicador oficial no catálogo da rede.</p>
        ) : (
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3" data-testid="indicadores-disponiveis">
            {c.indicadores.map((ind) => (
              <CartaoIndicador key={ind.chave} ind={ind} c={c} aberto={aberto?.chave === ind.chave}
                               aoAbrir={() => abrir(ind.chave, recorteDoCartao(ind.chave))} idDetalhe={idDetalhe} />
            ))}
          </div>
        )}
        {c.destaques.length > 0 && (
          // A fonte dos resultados da rede nos cartões: só sob demanda (nenhum cartão cita arquivo).
          <DetalhesEFontes
            itens={c.destaques.map((d) => ({ rotulo: `${d.rotulo} (${d.edicao})`, fonte_id: d.fonte_id ?? null }))}
            fontes={c.fontes} testId="detalhes-fontes-destaques" />
        )}
        {c.estimativas.length > 0 && (
          <Nota testId="estimativas-fora">
            Fora dos resultados oficiais, à parte: Estimativa Constela (calculada pelo Constela, não é resultado
            oficial) — {c.estimativas.map((e) => `${e.nome} (${e.edicoes.join(", ")})`).join("; ")}.
          </Nota>
        )}
        {semRegistro.length > 0 && (
          <Nota testId="sem-registro-fora">
            <span className="font-semibold">{MARCA_SEM_REGISTRO} Sem registro oficial:</span>{" "}
            {semRegistro.map((s) => `${s.nome} (${s.edicoes.join(", ")})`).join("; ")}. É o {TEXTO_SEM_REGISTRO}: não é
            a Estimativa Constela; aparece marcado com {MARCA_SEM_REGISTRO} na série histórica e nas escolas, e fica fora
            dos resultados da rede nos cartões.
          </Nota>
        )}
      </section>

      <div ref={refDetalhe} id={idDetalhe} className="scroll-mt-4" data-testid="avaliacoes-detalhe">
        {aberto && aberto.disponivel ? (
          <PorIndicador redeId={ctx.redeId} base={c} params={params} atualizar={atualizar} escolaId={escolaId}
                        titulo={`Série histórica e escolas — ${sigla}`} semEscolha simples
                        linkDaEscola={(id) => ctx.link(`/rede/escolas/${id}`)}
                        campoEscola={{
                          aoMudar: (id) => atualizar({ escola: id == null ? null : String(id),
                                                       ...(id == null ? { abrangencia: null } : {}) }),
                        }} />
        ) : (
          <Card className="p-5 sm:p-6">
            <p className={`text-sm ${CINZA}`} data-testid="detalhe-vazio">
              {aberto
                ? `${sigla}: ${textoSimples(textoIndisponivel(aberto))}.`
                : "Escolha “Ver série histórica e escolas” num indicador acima para ver a série da rede, os resultados "
                  + "de cada escola numa edição e as fontes."}
            </p>
          </Card>
        )}
      </div>

      <TodasAsEscolas c={c} ctx={ctx} />

      <div className="space-y-3">
        {alertas.length > 0 && (
          <Recolhivel titulo={`Avisos sobre os dados oficiais (${alertas.length})`} testId="avisos-dados-oficiais"
                      icone={<AlertTriangle size={14} className="shrink-0 text-zinc-500" aria-hidden />}>
            <AvisosDosDados alertas={alertas} c={c}
                            aoVerEscolas={(chave, edicao) => abrir(chave, { visao: "escolas", edicao: String(edicao) })} />
          </Recolhivel>
        )}
        {metodologia.length > 0 && (
          <Recolhivel titulo="Como ler estes números" testId="metodologia-resumo"
                      icone={<BookOpenText size={14} className="shrink-0 text-zinc-500" aria-hidden />}>
            <ul className="list-disc space-y-1 pl-4">
              {metodologia.map((t) => <li key={t}>{t}</li>)}
            </ul>
          </Recolhivel>
        )}
      </div>

      <div className="flex flex-wrap gap-2" data-testid="links-avaliacoes">
        <Link to={ctx.link("/rede/escolas")} className={CLASSE_LINK}>
          <GitCompareArrows size={15} aria-hidden /> Escolas: comparar lado a lado
        </Link>
        {/* A fonte de cada número (o global também importa ali). */}
        <Link to="/rede/avaliacoes" className={CLASSE_LINK}>
          <FileSearch size={15} aria-hidden /> {global ? "Importações e fontes" : "Arquivos oficiais de cada número"}
        </Link>
      </div>
    </div>
  );
}

function Avaliacoes({ ctx }: { ctx: ContextoDaPagina }) {
  const catalogo = useCatalogo(ctx.redeId);
  return (
    <div className="min-w-0 space-y-6">
      <CabecalhoDaPagina
        titulo="Avaliações externas"
        descricao="Os resultados oficiais da rede e das escolas (INEP e SEDUC-SP): o que cada avaliação mede, de quando é e como está a rede."
        nomeRede={catalogo.dados?.rede.nome ?? null}
        ctx={ctx}
      />
      <EstadoDaLeitura dados={catalogo.dados} erro={catalogo.erro} oQue="as avaliações externas">
        {(c) => <Conteudo c={c} ctx={ctx} />}
      </EstadoDaLeitura>
    </div>
  );
}

export default function AvaliacoesExternasRede() {
  return (
    <PaginaDaRede titulo="Avaliações externas">
      {(ctx) => <Avaliacoes key={ctx.redeId} ctx={ctx} />}
    </PaginaDaRede>
  );
}
