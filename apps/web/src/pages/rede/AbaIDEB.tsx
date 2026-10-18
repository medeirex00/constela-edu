/**
 * Aba "IDEB e SAEB" dos indicadores oficiais (plano, 5.1; etapas E8a e E8b) — o que a
 * Secretaria e o admin global leem do Ideb e do Saeb do 5º ano OFICIAIS do INEP, da
 * rede e por escola, em quatro partes:
 *
 *  - REDE MUNICIPAL (`RedeIDEB`, E8b): o Ideb da rede × a meta e × o Brasil nas redes
 *    municipais (a UF na rede pública, como contexto rotulado de outra rede), o Saeb do
 *    5º ano da planilha com a distribuição por nível e os cortes, e o contexto amostral
 *    do 2º ano. É a parte aberta primeiro quando há número da rede;
 *  - POR ESCOLA (uma edição, 2025 incluída): o Ideb, a meta (2007–2021) com "atingiu / não atingiu"
 *    na precisão publicada (Ideb ≥ meta = atingiu, o empate incluído), a variação desde
 *    a edição anterior e o Saeb de LP e MT — em ORDEM ALFABÉTICA, sem ranking. "Ideb não
 *    divulgado" nunca vira 0; os números gravados antes pelo botão de 1 clique vêm
 *    marcados "sem registro oficial", com a origem e a data à vista no bloco. A
 *    participação por escola não tem coluna: só existiria com a D8 (a tela explica);
 *  - SÉRIE DE UMA ESCOLA: o Ideb com a meta tracejada num gráfico e o Saeb (LP e MT)
 *    noutro — escalas diferentes não se misturam —, com a tabela equivalente (anos nas
 *    LINHAS: cabe no celular sem rolagem lateral) e N, P e aprovação;
 *  - COBERTURA (uma edição): quantas escolas têm Ideb e Saeb, por que as outras não
 *    têm, as escolas sem linha no arquivo, sem código INEP e os códigos do arquivo sem
 *    escola no cadastro, mais as notas do arquivo do INEP.
 *
 * Sempre visíveis: o aviso de comparabilidade da série TODA (o universo e os critérios
 * mudaram ao longo de 2005–2025 — plano, (2).4; não só 2021) e o que ainda falta (a
 * planilha do Saeb 2023, adiada; e o que a base não importou, pelo nome do arquivo) —
 * nunca "aguardando": o texto vem da API. Cada bloco tem o selo de fonte (arquivo,
 * divulgação, data do arquivo).
 * As abas seguem o padrão do `CartaoICA`/`AbaSARESP` (aba → `aria-controls` →
 * `tabpanel` rotulado).
 */
import { type ReactNode, useId, useState } from "react";

import { GraficoLinha, type SerieLinha } from "../../components/Grafico";
import SeloFonte, { textoFonte } from "../../components/SeloFonte";
import { Badge } from "../../components/ui";
import { dataHora } from "../../lib/formato";
import { numeroBR } from "./ica";
import { Aviso, Bloco, Nota, Seletor, Situacao } from "./IdebBlocos";
import RedeIDEB from "./RedeIDEB";
import {
  MOTIVOS_IDEB,
  diferencaIDEB,
  edicaoDe,
  faixaIdeb,
  fonteDe,
  fontesDosNumeros,
  numerosDaEdicao,
  periodoIDEB,
  porNome,
  textoAusenciaIDEB,
  textoSemMeta,
  valorIDEB,
  type CoberturaIDEB,
  type EdicaoIDEB,
  type EscolaIDEB,
  type NumeroIDEB,
  type RespostaIDEB,
} from "./ideb";

// Ideb em índigo e a meta em cinza TRACEJADA; no Saeb, LP em índigo e MT em âmbar. A
// legenda e a tabela dizem o nome (a cor não é o único código).
const COR = { ideb: "#6366f1", meta: "#64748b", lp: "#6366f1", mt: "#f59e0b" };

// --- Células ---------------------------------------------------------------------

/** De onde veio um número "sem registro oficial": o texto da fonte antiga e a data. */
function origemSemRegistro(n: NumeroIDEB): string {
  return `${n.fonte_texto ?? "importação manual, sem fonte registrada"}${
    n.gravado_em ? ` — gravado em ${dataHora(n.gravado_em)}` : ""}`;
}

/** Marca "*" do número gravado antes pelo botão de 1 clique (sem prévia nem registro
 *  do arquivo): compacta (cabe no celular), com a origem no título e para leitor de
 *  tela; a legenda vai embaixo da tabela e a origem, à vista no bloco
 *  (`OrigensSemRegistro`). Se a importação oficial recusou trocá-lo por um número
 *  diferente, diz também "≠ arquivo oficial". */
function SemRegistro({ n }: { n: NumeroIDEB | null | undefined }) {
  if (!n || n.proveniencia !== "sem_registro") return null;
  const origem = origemSemRegistro(n);
  return (
    <span className="text-amber-700 dark:text-amber-400" title={`Sem registro oficial: ${origem}`}
          data-testid="ideb-marca-sem-registro">
      <span aria-hidden="true">*</span>
      <span className="sr-only"> (sem registro oficial{n.difere_do_oficial ? ", difere do arquivo oficial" : ""}: {origem})</span>
      {n.difere_do_oficial && (
        <span className="block text-[11px]" aria-hidden="true">≠ arquivo oficial</span>
      )}
    </span>
  );
}

/** O número na precisão publicada, com a fonte no título e para leitor de tela (a
 *  marca "*" quando não tem registro oficial). */
function Valor({ dados, n, casas, forte = false, sufixo = "" }: {
  dados: RespostaIDEB; n: NumeroIDEB; casas: number; forte?: boolean; sufixo?: string;
}) {
  const f = fonteDe(dados, n.fonte_id);
  const fonte = f ? textoFonte(f) : null;
  return (
    <span className={`tabular-nums ${forte ? "font-semibold" : ""}`} title={fonte ? `Fonte: ${fonte}` : undefined}>
      {valorIDEB(n, casas)}{sufixo}
      {fonte && <span className="sr-only"> — fonte: {fonte}</span>}
      <SemRegistro n={n} />
    </span>
  );
}

/** Algum número "sem registro oficial" (para a legenda da marca "*"). */
function temSemRegistro(eds: (EdicaoIDEB | undefined)[]): boolean {
  return eds.some((ed) => ed && [ed.ideb, ed.saeb_lp, ed.saeb_mt].some((n) => n?.proveniencia === "sem_registro"));
}

function LegendaSemRegistro({ mostrar }: { mostrar: boolean }) {
  if (!mostrar) return null;
  return (
    <p className="text-[11px] text-amber-700 dark:text-amber-400" data-testid="ideb-legenda-sem-registro">
      * sem registro oficial: número gravado antes, pelo botão de 1 clique, sem prévia nem registro do arquivo
      (“≠ arquivo oficial” = a importação oficial recusou trocá-lo pelo número diferente do arquivo).
    </p>
  );
}

/** A origem e a data (sem repetição) dos números "sem registro oficial" do bloco, À
 *  VISTA: eles não têm `fonte_id`, então o selo de fonte não os cobre — e no celular
 *  não há o título da marca "*". */
function OrigensSemRegistro({ numeros, testId }: { numeros: (NumeroIDEB | null | undefined)[]; testId: string }) {
  const origens = [...new Set(numeros.flatMap((n) => (n?.proveniencia === "sem_registro" ? [origemSemRegistro(n)] : [])))];
  if (origens.length === 0) return null;
  return (
    <div className="space-y-1 break-words rounded-lg bg-amber-50 p-2.5 text-[11px] text-amber-800 dark:bg-amber-500/10 dark:text-amber-300"
         data-testid={testId}>
      {origens.map((o) => <p key={o}>* Sem registro oficial: {o}</p>)}
    </div>
  );
}

/** O Ideb da edição: o número (ou "Ideb não divulgado"), a meta e a situação, a
 *  variação desde a edição anterior e a marca "sem registro oficial". */
function CelulaIdeb({ dados, ed }: { dados: RespostaIDEB; ed: EdicaoIDEB }) {
  const n = ed.ideb;
  return (
    <div className="space-y-0.5 break-words hyphens-auto">
      {n && n.valor != null ? <Valor dados={dados} n={n} casas={1} forte />
        : <span className="text-xs text-zinc-500">{n ? "Ideb não divulgado" : (MOTIVOS_IDEB[ed.motivo ?? ""] ?? "sem resultado")}</span>}
      {ed.meta && (
        <span className="block text-[11px] text-zinc-500">
          meta {ed.meta.valor != null ? <Valor dados={dados} n={ed.meta} casas={1} /> : "não divulgada"}
        </span>
      )}
      {ed.comparacao_meta && <span className="block"><Situacao c={ed.comparacao_meta} /></span>}
      {ed.variacao_ideb && (
        <span className="block text-[11px] text-zinc-500">
          {diferencaIDEB(ed.variacao_ideb.diferenca, ed.variacao_ideb.casas_decimais)} desde {ed.variacao_ideb.desde}
        </span>
      )}
    </div>
  );
}

function CelulaSaeb({ dados, n }: { dados: RespostaIDEB; n: NumeroIDEB | null }) {
  return (
    <div className="break-words hyphens-auto">
      {n && n.valor != null ? <Valor dados={dados} n={n} casas={2} />
        : <span className="text-xs text-zinc-500">{textoAusenciaIDEB(n)}</span>}
    </div>
  );
}

/** As três células (Ideb, LP, MT) — ou o motivo de não haver nenhuma, numa só. LP e MT
 *  sem número pelo MESMO motivo viram uma célula só ("Saeb não divulgado"): no celular,
 *  "não divulgado" não cabe numa coluna estreita. */
function CelulasDaEdicao({ dados, linha, ed }: { dados: RespostaIDEB; linha: EscolaIDEB; ed: EdicaoIDEB | undefined }) {
  if (!linha.codigo_inep) {
    return (
      <td colSpan={3} className="py-1.5 text-xs text-zinc-500">
        <Badge tom="alerta">sem código INEP</Badge>{" "}
        Pendência de cadastro: sem o código INEP, a escola não casa com o arquivo oficial.
      </td>
    );
  }
  if (!ed || !ed.no_arquivo) {
    return (
      <td colSpan={3} className="py-1.5 text-xs text-zinc-500">
        Sem resultado: {MOTIVOS_IDEB[ed?.motivo ?? ""] ?? "sem resultado"}.
      </td>
    );
  }
  const lp = ed.saeb_lp, mt = ed.saeb_mt;
  const semSaeb = lp?.valor == null && mt?.valor == null && textoAusenciaIDEB(lp) === textoAusenciaIDEB(mt);
  return (
    <>
      <td className="py-1.5 pr-2"><CelulaIdeb dados={dados} ed={ed} /></td>
      {semSaeb ? (
        <td colSpan={2} className="py-1.5 text-xs text-zinc-500">Saeb {textoAusenciaIDEB(lp)}</td>
      ) : (
        <>
          <td className="py-1.5 pr-2"><CelulaSaeb dados={dados} n={lp} /></td>
          <td className="py-1.5"><CelulaSaeb dados={dados} n={mt} /></td>
        </>
      )}
    </>
  );
}

/** Tabela de 4 colunas, LARGURA FIXA: cabe em ~300 px (celular, dentro do cartão) sem
 *  rolagem lateral; no computador, não passa de 48rem (leitura da linha). */
function TabelaQuatro({ legenda, primeira, children }: { legenda: string; primeira: string; children: ReactNode }) {
  return (
    <table className="w-full max-w-3xl table-fixed text-sm">
      <caption className="sr-only">{legenda}</caption>
      <colgroup>
        <col className="w-[36%]" />
        <col className="w-[26%]" />
        <col className="w-[19%]" />
        <col className="w-[19%]" />
      </colgroup>
      <thead>
        <tr className="text-left text-xs text-zinc-500">
          <th scope="col" className="py-1 pr-2 font-medium">{primeira}</th>
          <th scope="col" className="py-1 pr-2 font-medium">Ideb</th>
          <th scope="col" className="py-1 pr-2 font-medium"><abbr title="Saeb do 5º ano — Língua Portuguesa" className="no-underline">Saeb LP</abbr></th>
          <th scope="col" className="py-1 font-medium"><abbr title="Saeb do 5º ano — Matemática" className="no-underline">Saeb MT</abbr></th>
        </tr>
      </thead>
      <tbody>{children}</tbody>
    </table>
  );
}

function Participacao({ dados }: { dados: RespostaIDEB }) {
  if (dados.participacao.disponivel) return null;
  return (
    <p className="text-[11px] text-zinc-500" data-testid="ideb-participacao">
      <b className="font-medium">Participação por escola: sem coluna.</b> {dados.participacao.texto}
    </p>
  );
}

function BlocoSemRegistro({ dados }: { dados: RespostaIDEB }) {
  const s = dados.sem_registro_oficial;
  if (s.total === 0) return null;
  const porEdicao = Object.entries(s.por_edicao).map(([ed, n]) => `${n} em ${ed}`).join(", ");
  return (
    <Aviso testId="ideb-sem-registro">
      <p>{dados.avisos.sem_registro}</p>
      <p>
        Nesta rede: {s.total} número(s) sem registro oficial ({porEdicao}).
        {s.difere_do_oficial > 0
          && ` ${s.difere_do_oficial} ${s.difere_do_oficial === 1 ? "difere" : "diferem"} do arquivo oficial: `
            + "a troca pelo número do arquivo foi recusada na importação."}
      </p>
    </Aviso>
  );
}

// --- Por escola --------------------------------------------------------------------

function opcoesDeEdicao(dados: RespostaIDEB) {
  return [...dados.edicoes].reverse().map((e) => ({ valor: e, texto: String(e) }));
}

function SemEscolas() {
  return (
    <p className="rounded-lg border border-dashed border-zinc-300 p-4 text-sm text-zinc-500 dark:border-zinc-700"
       data-testid="ideb-sem-escolas">
      Nenhuma escola da rede com resultado importado do Ideb por escola (o número da rede está na parte “Rede
      municipal”).
    </p>
  );
}

function ParteEscolas({ dados, edicao, aoMudarEdicao }: {
  dados: RespostaIDEB; edicao: number | undefined; aoMudarEdicao: (e: number) => void;
}) {
  if (edicao == null) return <SemEscolas />;
  // Ordem por NOME — sem ranking (a API já manda assim; a tela não depende disso).
  const porEscola = porNome(dados.escolas).map((l) => ({ l, ed: edicaoDe(l, edicao) }));
  const semMeta = porEscola.map(({ ed }) => ed?.sem_meta).find(Boolean) ?? null;
  const textoMeta = textoSemMeta(edicao, semMeta, dados.anos_meta);
  return (
    <div className="space-y-3">
      <Seletor rotulo="Edição" valor={edicao} opcoes={opcoesDeEdicao(dados)} aoMudar={aoMudarEdicao} />
      <Bloco titulo={`Ideb e Saeb do 5º ano por escola — ${edicao}`} testId="ideb-escolas">
        <p className="text-xs text-zinc-500">{dados.avisos.sem_ranking} {dados.avisos.ausencia}</p>
        <p className="text-xs text-zinc-500" data-testid="ideb-metas-edicao">
          {dados.anos_meta.includes(edicao)
            ? dados.avisos.precisao
            : `Metas: ${textoMeta ?? "sem meta nesta edição"} — nada é comparado.`}
        </p>
        <TabelaQuatro primeira="Escola"
                      legenda={`Ideb e Saeb do 5º ano em ${edicao} por escola, em ordem alfabética (não é ranking)`}>
          {porEscola.map(({ l, ed }) => (
            <tr key={l.escola_id} className="border-t border-zinc-100 align-top dark:border-zinc-800">
              <th scope="row" className="break-words py-1.5 pr-2 text-left font-normal">
                {l.nome}
                {l.status !== "ativa" && <span className="text-xs text-zinc-500"> (inativa)</span>}
              </th>
              <CelulasDaEdicao dados={dados} linha={l} ed={ed} />
            </tr>
          ))}
        </TabelaQuatro>
        <LegendaSemRegistro mostrar={temSemRegistro(porEscola.map(({ ed }) => ed))} />
        <Participacao dados={dados} />
        <SeloFonte titulo={`Fontes da tabela por escola (${edicao})`} testId="ideb-selo-escolas"
                   fontes={fontesDosNumeros(dados, porEscola.flatMap(({ ed }) => numerosDaEdicao(ed)))} />
        <OrigensSemRegistro testId="ideb-origens-escolas" numeros={porEscola.flatMap(({ ed }) => numerosDaEdicao(ed))} />
      </Bloco>
      <BlocoSemRegistro dados={dados} />
    </div>
  );
}

// --- Série de uma escola -------------------------------------------------------------

function faixaSaeb(valores: number[]): { minimo: number; maximo: number } {
  return {
    minimo: Math.max(0, Math.floor((Math.min(...valores) - 10) / 10) * 10),
    maximo: Math.ceil((Math.max(...valores) + 10) / 10) * 10,
  };
}

function ParteSerie({ dados }: { dados: RespostaIDEB }) {
  const comDado = porNome(dados.escolas).filter((l) => l.serie.some((e) => e.no_arquivo));
  const [escolhida, setEscolhida] = useState<number | null>(null);
  const escola = comDado.find((l) => l.escola_id === escolhida) ?? comDado[0];
  if (!escola) return <SemEscolas />;
  const eixoX = dados.edicoes.map(String);
  const serie = escola.serie;
  const ideb: SerieLinha[] = [
    { nome: "Ideb observado", cor: COR.ideb,
      pontos: serie.map((e) => ({ rotulo: String(e.edicao), valor: e.ideb?.valor ?? null })) },
    { nome: "Meta do Ideb (1º ciclo)", cor: COR.meta, tracejada: true,
      pontos: serie.filter((e) => e.meta).map((e) => ({ rotulo: String(e.edicao), valor: e.meta?.valor ?? null })) },
  ];
  const saeb: SerieLinha[] = [
    { nome: "Língua Portuguesa", cor: COR.lp,
      pontos: serie.map((e) => ({ rotulo: String(e.edicao), valor: e.saeb_lp?.valor ?? null })) },
    { nome: "Matemática", cor: COR.mt,
      pontos: serie.map((e) => ({ rotulo: String(e.edicao), valor: e.saeb_mt?.valor ?? null })) },
  ];
  const valores = (s: SerieLinha[]) => s.flatMap((x) => x.pontos.flatMap((p) => (p.valor == null ? [] : [p.valor])));
  const fIdeb = faixaIdeb(valores(ideb));
  const fSaeb = valores(saeb).length ? faixaSaeb(valores(saeb)) : { minimo: 0, maximo: 300 };
  const periodo = periodoIDEB(eixoX);
  const fontes = fontesDosNumeros(dados, serie.flatMap(numerosDaEdicao));
  return (
    <div className="space-y-4">
      <Seletor rotulo="Escola" valor={escola.escola_id}
               opcoes={comDado.map((l) => ({ valor: l.escola_id, texto: l.nome }))}
               aoMudar={setEscolhida} />
      <Bloco titulo={`Série de ${escola.nome} (${periodo})`} testId="ideb-serie">
        <div className="grid gap-5 lg:grid-cols-2">
          <figure className="min-w-0 space-y-1" data-testid="ideb-grafico-ideb">
            <figcaption className="text-xs font-medium text-zinc-700 dark:text-zinc-200">Ideb e meta (tracejada)</figcaption>
            <GraficoLinha series={ideb} eixoX={eixoX} minimo={fIdeb.minimo} maximo={fIdeb.maximo} altura={200}
                          formato={(v) => numeroBR(v, 1)}
                          rotulo={`Ideb de ${escola.nome} por edição, de ${periodo}, com a meta do 1º ciclo tracejada`} />
          </figure>
          <figure className="min-w-0 space-y-1" data-testid="ideb-grafico-saeb">
            <figcaption className="text-xs font-medium text-zinc-700 dark:text-zinc-200">
              Saeb do 5º ano — Língua Portuguesa e Matemática
            </figcaption>
            <GraficoLinha series={saeb} eixoX={eixoX} minimo={fSaeb.minimo} maximo={fSaeb.maximo} altura={200}
                          formato={(v) => numeroBR(v, 2)}
                          rotulo={`Saeb do 5º ano de ${escola.nome} por edição, de ${periodo}: Língua Portuguesa e Matemática`} />
          </figure>
        </div>
        <p className="text-[11px] text-zinc-500">
          Sem número numa edição, a linha quebra (nunca vai a 0). O Ideb e o Saeb da rede municipal, comparados na
          mesma rede, estão na parte “Rede municipal”.
        </p>
        <TabelaQuatro primeira="Edição" legenda={`Números dos gráficos: Ideb, meta e Saeb do 5º ano de ${escola.nome}, por edição`}>
          {serie.map((ed) => (
            <tr key={ed.edicao} className="border-t border-zinc-100 align-top dark:border-zinc-800">
              <th scope="row" className="py-1.5 pr-2 text-left font-normal tabular-nums">{ed.edicao}</th>
              <CelulasDaEdicao dados={dados} linha={escola} ed={ed} />
            </tr>
          ))}
        </TabelaQuatro>
        <LegendaSemRegistro mostrar={temSemRegistro(serie)} />
        <details className="text-xs" data-testid="ideb-n-p-aprovacao">
          <summary className="cursor-pointer text-zinc-500">N, P e aprovação por edição</summary>
          <table className="mt-1 w-full table-fixed text-xs">
            <caption className="sr-only">N, P e taxa de aprovação de {escola.nome} por edição</caption>
            <thead>
              <tr className="text-left text-zinc-500">
                <th scope="col" className="py-1 pr-2 font-medium">Edição</th>
                <th scope="col" className="py-1 pr-2 font-medium"><abbr title="Nota média padronizada" className="no-underline">N</abbr></th>
                <th scope="col" className="py-1 pr-2 font-medium"><abbr title="Indicador de rendimento" className="no-underline">P</abbr></th>
                <th scope="col" className="py-1 font-medium">Aprovação 1º ao 5º</th>
              </tr>
            </thead>
            <tbody>
              {serie.map((ed) => (
                <tr key={ed.edicao} className="border-t border-zinc-100 dark:border-zinc-800">
                  <th scope="row" className="py-1 pr-2 text-left font-normal tabular-nums">{ed.edicao}</th>
                  {[ed.nota_n, ed.rendimento_p].map((n, i) => (
                    <td key={i} className="break-words py-1 pr-2">
                      {n && n.valor != null ? <Valor dados={dados} n={n} casas={6} />
                        : <span className="text-zinc-500">{textoAusenciaIDEB(n, "—")}</span>}
                    </td>
                  ))}
                  <td className="py-1">
                    {ed.aprovacao.anos_iniciais && ed.aprovacao.anos_iniciais.valor != null
                      ? <Valor dados={dados} n={ed.aprovacao.anos_iniciais} casas={1} sufixo="%" />
                      : <span className="text-zinc-500">{textoAusenciaIDEB(ed.aprovacao.anos_iniciais, "—")}</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-1 text-[11px] text-zinc-500">
            O Ideb é N × P: N vem do Saeb (LP e MT) e P, das taxas de aprovação do 1º ao 5º ano.
          </p>
        </details>
        <SeloFonte titulo={`Fontes da série de ${escola.nome}`} testId="ideb-selo-serie" fontes={fontes} />
        <OrigensSemRegistro testId="ideb-origens-serie" numeros={serie.flatMap(numerosDaEdicao)} />
      </Bloco>
    </div>
  );
}

// --- Cobertura ---------------------------------------------------------------------

function Lista({ titulo, children, alerta = false }: { titulo: string; children: ReactNode; alerta?: boolean }) {
  return (
    <div>
      <p className={`text-xs font-medium ${alerta ? "text-amber-800 dark:text-amber-300" : "text-zinc-600 dark:text-zinc-300"}`}>
        {titulo}
      </p>
      <ul className="list-disc break-words pl-5 text-xs text-zinc-600 dark:text-zinc-400">{children}</ul>
    </div>
  );
}

function motivoCobertura(motivo: string): string {
  return motivo === "nao_divulgado" ? "Ideb não divulgado" : (MOTIVOS_IDEB[motivo] ?? "sem resultado");
}

function CoberturaDaEdicao({ dados, c }: { dados: RespostaIDEB; c: CoberturaIDEB }) {
  const fonte = fonteDe(dados, c.fonte_id);
  const notas = fonte?.notas ?? [];
  return (
    <section className="space-y-2 rounded-lg border border-zinc-200 p-3 dark:border-zinc-800"
             aria-label={`Cobertura — ${c.edicao}`} data-testid={`ideb-cobertura-${c.edicao}`}>
      <p className="text-sm text-zinc-700 dark:text-zinc-200">
        <b className="tabular-nums">{c.com_ideb}</b> de <b className="tabular-nums">{c.total_escolas}</b> escolas da rede
        com Ideb em {c.edicao}; <b className="tabular-nums">{c.com_saeb}</b> com Saeb do 5º ano.
      </p>
      {!c.arquivo_importado && (
        <p className="text-xs text-zinc-500">
          Nenhum arquivo oficial do Ideb importado para {c.edicao}: só há números sem registro oficial (1 clique), e não dá
          para saber quais códigos do arquivo ficaram fora do cadastro.
        </p>
      )}
      {c.sem_resultado.length > 0 && (
        <Lista titulo={`Sem Ideb (${c.sem_resultado.length}) — sem resultado não é zero:`}>
          {c.sem_resultado.map((s) => <li key={s.escola_id}>{s.nome}: {motivoCobertura(s.motivo)}</li>)}
        </Lista>
      )}
      {c.sem_linha_no_arquivo.length > 0 && (
        <Lista titulo={`Com código INEP, sem linha no arquivo oficial (${c.sem_linha_no_arquivo.length}):`}>
          {c.sem_linha_no_arquivo.map((s) => <li key={s.escola_id}>{s.nome} (INEP {s.codigo_inep})</li>)}
        </Lista>
      )}
      {c.sem_inep.length > 0 && (
        <Lista alerta titulo={`Sem código INEP no cadastro (${c.sem_inep.length}) — pendência de cadastro:`}>
          {c.sem_inep.map((s) => <li key={s.escola_id}>{s.nome}</li>)}
        </Lista>
      )}
      {c.fora_do_cadastro.length > 0 && (
        <>
          <Lista titulo={`No arquivo oficial, sem escola com esse código no cadastro (${c.fora_do_cadastro.length}):`}>
            {c.fora_do_cadastro.map((f) => (
              <li key={f.codigo_inep ?? f.nome_no_arquivo}>
                INEP {f.codigo_inep ?? "—"}{f.nome_no_arquivo ? ` — “${f.nome_no_arquivo}”, como está no arquivo` : ""}
              </li>
            ))}
          </Lista>
          <p className="text-[11px] text-zinc-500">
            O Constela casa as escolas só pelo código INEP, nunca pelo nome. Se uma delas for uma escola da rede sem código
            no cadastro, cadastre o código (Gestão de redes) e reimporte o arquivo oficial.
          </p>
        </>
      )}
      <SeloFonte fontes={[fonte]} />
      {notas.length > 0 && (
        <details className="text-xs">
          <summary className="cursor-pointer text-zinc-500">Notas do arquivo oficial do INEP</summary>
          <ul className="mt-1 list-disc break-words pl-5 text-[11px] text-zinc-500">
            {notas.map((n) => <li key={n}>{n}</li>)}
          </ul>
        </details>
      )}
    </section>
  );
}

function ParteCobertura({ dados, edicao, aoMudarEdicao }: {
  dados: RespostaIDEB; edicao: number | undefined; aoMudarEdicao: (e: number) => void;
}) {
  if (edicao == null) return <SemEscolas />;
  const c = dados.cobertura.find((x) => x.edicao === edicao);
  return (
    <div className="space-y-3">
      <Seletor rotulo="Edição" valor={edicao} opcoes={opcoesDeEdicao(dados)} aoMudar={aoMudarEdicao} />
      {c ? <CoberturaDaEdicao dados={dados} c={c} />
        : <p className="text-sm text-zinc-500">Sem cobertura para esta edição.</p>}
    </div>
  );
}

// --- A aba ---------------------------------------------------------------------------

/** O que ainda falta: o ADIADO (a planilha do Saeb 2023) à vista; o que esta base não
 *  importou, a um toque (a lista é longa no celular). Nunca "aguardando". */
function Pendentes({ dados }: { dados: RespostaIDEB }) {
  if (dados.pendentes.length === 0) return null;
  const adiados = dados.pendentes.filter((p) => p.situacao === "adiado");
  const semImportacao = dados.pendentes.filter((p) => p.situacao !== "adiado");
  return (
    <Nota testId="ideb-pendentes">
      {adiados.map((p) => <p key={p.chave}>{p.texto}</p>)}
      {semImportacao.length > 0 && (
        <details data-testid="ideb-pendentes-sem-importacao">
          <summary className="cursor-pointer font-medium">
            Arquivos oficiais ainda não importados nesta rede ({semImportacao.length})
          </summary>
          <ul className="mt-1 list-disc pl-4">
            {semImportacao.map((p) => <li key={p.chave}>{p.texto}</li>)}
          </ul>
        </details>
      )}
    </Nota>
  );
}

const PARTES = [["rede", "Rede municipal"], ["escolas", "Por escola"], ["serie", "Série de uma escola"],
  ["cobertura", "Cobertura"]] as const;
type Parte = (typeof PARTES)[number][0];

export default function AbaIDEB({ dados }: { dados: RespostaIDEB }) {
  // Abre na parte com número: a rede quando há número DELA (o oficial do município); senão, por
  // escola. Sem número de escola, a rede de novo se houver a referência (o estado e o Brasil) —
  // a UF e o Brasil sozinhos nunca passam à frente das escolas: não são número da rede.
  const rede = dados.rede_municipal;
  const temReferencia = rede.ideb.tem_dados || rede.saeb.tem_dados || dados.contexto_amostral.tem_dados;
  const temRede = rede.tem_dados || (!dados.tem_dados_escolas && temReferencia);
  const [parte, setParte] = useState<Parte>(temRede ? "rede" : "escolas");
  const [escolhida, setEscolhida] = useState<number | null>(null);
  const edicao = escolhida ?? dados.edicoes[dados.edicoes.length - 1];
  const idBase = useId();
  const idAba = (chave: string) => `${idBase}-aba-${chave}`;
  const idPainel = `${idBase}-painel`;
  // A nota de 2021 segue a série TODA, como o período do aviso: as escolas, a rede e o Saeb.
  const comPandemia = [dados.edicoes, rede.ideb.edicoes, rede.saeb.edicoes].some((eds) => eds.includes(2021));
  return (
    <div className="space-y-4" data-testid="aba-ideb">
      <Aviso testId="ideb-aviso-comparabilidade">
        <p>
          {dados.avisos.comparabilidade}
          {comPandemia && ` ${dados.avisos.pandemia}`}
        </p>
      </Aviso>
      <Pendentes dados={dados} />
      <div role="tablist" aria-label="Partes do IDEB e do SAEB"
           className="flex flex-wrap gap-1 border-b border-zinc-200 dark:border-zinc-800">
        {PARTES.map(([chave, rotulo]) => (
          <button key={chave} id={idAba(chave)} type="button" role="tab" aria-selected={parte === chave}
                  aria-controls={idPainel} onClick={() => setParte(chave)}
                  className={`-mb-px border-b-2 px-3 py-2 text-sm font-medium transition-colors ${
                    parte === chave
                      ? "border-indigo-600 text-zinc-900 dark:text-zinc-50"
                      : "border-transparent text-zinc-500 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100"
                  }`}>
            {rotulo}
          </button>
        ))}
      </div>
      <div role="tabpanel" id={idPainel} aria-labelledby={idAba(parte)} className="space-y-4">
        {parte === "rede" && <RedeIDEB dados={dados} />}
        {parte === "escolas" && <ParteEscolas dados={dados} edicao={edicao} aoMudarEdicao={setEscolhida} />}
        {parte === "serie" && <ParteSerie dados={dados} />}
        {parte === "cobertura" && <ParteCobertura dados={dados} edicao={edicao} aoMudarEdicao={setEscolhida} />}
      </div>
    </div>
  );
}
