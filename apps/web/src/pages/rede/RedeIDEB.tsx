/**
 * Parte "Rede municipal" da aba IDEB e SAEB (etapa E8b; plano, 4.6, 4.8, 4.9 e 5.1) — o
 * número OFICIAL da rede, dos arquivos do INEP (nunca a média das escolas), em três
 * blocos:
 *
 *  - IDEB DA REDE MUNICIPAL (2005–AAAA): a série com a meta do 1º ciclo tracejada e o
 *    Brasil nas redes municipais no MESMO gráfico (a mesma rede); a UF, que o arquivo do
 *    INEP só traz na rede pública, fica FORA do gráfico e entra na tabela com o rótulo
 *    "outra rede, só contexto" (e o porquê). Tabela com o Ideb, a meta e "atingiu / não
 *    atingiu" na precisão publicada; a nota do Saeb que entra no Ideb (com o universo do
 *    INEP: só escolas urbanas), N, P e aprovação ficam num "ver mais" desta seção — e
 *    nunca se cruzam com a média da planilha;
 *  - SAEB DO 5º ANO PELA PLANILHA: as médias (LP e MT) da rede, da UF e do Brasil nas
 *    redes municipais, na localização Total (dita na tela); a distribuição por nível
 *    (LP 0–9, MT 0–10) em barras empilhadas, com a tabela equivalente com os níveis nas
 *    LINHAS (cabe no celular) e os cortes dos níveis com a fonte (o Dicionário da
 *    planilha do Saeb 2025);
 *  - CONTEXTO AMOSTRAL: o 2º ano e a taxa de alfabetização de 2021, só da UF e do Brasil,
 *    rotulados "amostral, só contexto" e "não é o ICA".
 *
 * Ordem FIXA (nunca por valor). Sem número: o motivo da fonte ("não divulgado"), nunca 0.
 * Território sem número (o arquivo dele não foi importado) fica fora do gráfico, da legenda e da
 * tabela; a UF e o Brasil sozinhos (referência pública) não contam como número da rede.
 * Cada bloco tem o selo de fonte; cada gráfico, a tabela equivalente; a cor nunca é o
 * único código. Tabelas de largura fixa (sem rolagem lateral).
 */
import { useState } from "react";

import { BarraEmpilhada, GraficoLinha, type SerieLinha } from "../../components/Grafico";
import SeloFonte, { textoFonte } from "../../components/SeloFonte";
import { Badge } from "../../components/ui";
import { numeroBR } from "./ica";
import { Aviso, Bloco, Nota, Seletor, Situacao } from "./IdebBlocos";
import {
  faixaIdeb,
  fonteDe,
  fontesDosNumeros,
  numerosDoTerritorio,
  periodoIDEB,
  textoAusenciaIDEB,
  textoFaixa,
  valorIDEB,
  type DistribuicaoSaeb,
  type EdicaoIdebRede,
  type NumeroIDEB,
  type RespostaIDEB,
  type TerritorioIdeb,
  type TerritorioSaeb,
} from "./ideb";

// A rede em índigo, a meta em cinza TRACEJADA, o Brasil (mesma rede) em verde e a UF nas
// redes municipais (se o arquivo trouxer) em âmbar. A legenda e a tabela dizem o nome.
const COR = { rede: "#6366f1", meta: "#64748b", brasil: "#10b981", uf: "#f59e0b" };
// Onze tons de um índigo só (do claro ao escuro): os níveis 0 a 10 do Saeb do 5º ano em
// ordem, sem "cor boa × cor ruim"; a legenda e a tabela dizem o nível.
const CORES_NIVEIS = ["#eef2ff", "#e0e7ff", "#c7d2fe", "#a5b4fc", "#818cf8", "#6366f1", "#4f46e5", "#4338ca",
  "#3730a3", "#312e81", "#1e1b4b"];
const COMPONENTES = [{ valor: "lp" as const, texto: "Língua Portuguesa" }, { valor: "mt" as const, texto: "Matemática" }];
type Componente = (typeof COMPONENTES)[number]["valor"];

const formatoNivel = (v: number) => `${numeroBR(v, 2)}%`;

/** "a", "a e b", "a, b e c". */
const juntar = (partes: string[]) =>
  partes.length <= 1 ? partes.join("") : `${partes.slice(0, -1).join(", ")} e ${partes[partes.length - 1]}`;

/** Um número oficial do território, na precisão publicada, com a fonte no título e para
 *  leitor de tela; sem número, o motivo da fonte (nunca 0). */
function Valor({ dados, n, casas, forte = false, sufixo = "" }: {
  dados: RespostaIDEB; n: NumeroIDEB | null | undefined; casas: number; forte?: boolean; sufixo?: string;
}) {
  if (!n || n.valor == null) {
    return <span className="text-xs text-zinc-500">{n ? textoAusenciaIDEB(n) : "—"}</span>;
  }
  const f = fonteDe(dados, n.fonte_id);
  const fonte = f ? textoFonte(f) : null;
  return (
    <span className={`tabular-nums ${forte ? "font-semibold" : ""}`} title={fonte ? `Fonte: ${fonte}` : undefined}>
      {valorIDEB(n, casas)}{sufixo}
      {fonte && <span className="sr-only"> — fonte: {fonte}</span>}
    </span>
  );
}

function SemDado({ texto, testId }: { texto: string; testId?: string }) {
  return (
    <p className="rounded-lg border border-dashed border-zinc-300 p-3 text-sm text-zinc-500 dark:border-zinc-700"
       data-testid={testId}>
      {texto}
    </p>
  );
}

/** Larguras das colunas: a primeira fixa, as demais divididas (tabela de largura fixa). */
function Colunas({ primeira, n }: { primeira: number; n: number }) {
  const resto = n > 0 ? (100 - primeira) / n : 0;
  return (
    <colgroup>
      <col style={{ width: `${primeira}%` }} />
      {Array.from({ length: n }, (_, i) => <col key={i} style={{ width: `${resto}%` }} />)}
    </colgroup>
  );
}

// --- Ideb da rede municipal ----------------------------------------------------------

/** O nome curto da coluna: "Rede municipal", "Brasil (redes municipais)", "São Paulo
 *  (rede pública)" — e, no contexto de outra rede, o rótulo disso logo abaixo. */
function CabecalhoTerritorio({ t }: { t: TerritorioIdeb }) {
  const curto = t.chave === "rede_municipal" ? "Rede municipal"
    : t.chave === "uf_rede_publica" ? `${t.nome} (rede pública)` : `${t.nome} (redes municipais)`;
  return (
    <th scope="col" className="break-words py-1 pr-2 font-medium" title={t.rotulo}>
      {curto}
      {t.contexto && (
        <span className="block text-[10px] font-normal text-amber-700 dark:text-amber-400">
          {t.rotulo_contexto ?? "outra rede, só contexto"}
        </span>
      )}
    </th>
  );
}

function CelulaIdebTerritorio({ dados, t, ed }: { dados: RespostaIDEB; t: TerritorioIdeb; ed: EdicaoIdebRede | undefined }) {
  if (!ed) return <td className="py-1.5 pr-2 text-xs text-zinc-400">—</td>;
  return (
    <td className="break-words py-1.5 pr-2">
      {ed.ideb && ed.ideb.valor != null ? (
        <Valor dados={dados} n={ed.ideb} casas={1} forte={t.chave === "rede_municipal"} />
      ) : (
        <span className="text-xs text-zinc-500">
          {!ed.ideb ? "—" : ed.ideb.motivo_ausencia === "nao_divulgado" ? "Ideb não divulgado" : textoAusenciaIDEB(ed.ideb)}
        </span>
      )}
      {ed.meta && (
        <span className="block text-[11px] text-zinc-500">
          meta {ed.meta.valor != null ? <Valor dados={dados} n={ed.meta} casas={1} /> : "não divulgada"}
        </span>
      )}
      {/* A situação da META só na rede do município: a comparação é a dela. */}
      {t.chave === "rede_municipal" && ed.comparacao_meta && (
        <span className="block"><Situacao c={ed.comparacao_meta} /></span>
      )}
    </td>
  );
}

function BlocoIdeb({ dados }: { dados: RespostaIDEB }) {
  const rede = dados.rede_municipal;
  const ideb = rede.ideb;
  const mun = ideb.territorios.find((t) => t.chave === "rede_municipal");
  if (!mun || !mun.tem_dados) {
    return (
      <Bloco titulo="Ideb da rede municipal" testId="ideb-rede">
        <SemDado testId="ideb-rede-sem-dado"
                 texto="Sem o Ideb da rede municipal importado (arquivo do Ideb por município do INEP)." />
      </Bloco>
    );
  }
  // Só os territórios com número: sem o arquivo da UF ou do Brasil, nada de coluna vazia,
  // de legenda com série que não está no gráfico, nem de aviso sobre o que esse arquivo traz.
  const territorios = ideb.territorios.filter((t) => t.chave === "rede_municipal" || t.tem_dados);
  const mesmas = territorios.filter((t) => t.mesma_rede && t.chave !== "rede_municipal");
  const contextos = territorios.filter((t) => !t.mesma_rede);
  const eixoX = ideb.edicoes.map(String);
  const periodo = periodoIDEB(ideb.edicoes);
  const pontos = (t: TerritorioIdeb, campo: "ideb" | "meta") =>
    t.serie.filter((e) => campo === "ideb" || e.meta).map((e) => ({ rotulo: String(e.edicao), valor: e[campo]?.valor ?? null }));
  const series: SerieLinha[] = [
    { nome: mun.rotulo, cor: COR.rede, pontos: pontos(mun, "ideb") },
    { nome: `Meta de ${mun.nome} (1º ciclo)`, cor: COR.meta, tracejada: true, pontos: pontos(mun, "meta") },
    ...mesmas.map((t) => ({ nome: t.rotulo, cor: t.abrangencia === "brasil" ? COR.brasil : COR.uf, pontos: pontos(t, "ideb") })),
  ];
  const valores = series.flatMap((s) => s.pontos.flatMap((p) => (p.valor == null ? [] : [p.valor])));
  const { minimo, maximo } = faixaIdeb(valores);
  // A legenda diz só o que o gráfico desenha (a série sem número fica fora dele).
  const comMeta = series[1].pontos.some((p) => p.valor != null);
  const legenda = juntar(["Ideb da rede", ...(comMeta ? ["meta (tracejada)"] : []), ...mesmas.map((t) => t.rotulo)])
    + (mesmas.length ? " — a mesma rede" : "");
  const semMeta = [...new Set(mun.serie.filter((e) => e.sem_meta === "depois_do_1o_ciclo").map((e) => e.edicao))];
  const fontes = fontesDosNumeros(dados, territorios.flatMap(numerosDoTerritorio));
  return (
    <Bloco titulo={`Ideb da rede municipal (${periodo})`} testId="ideb-rede">
      <p className="text-xs text-zinc-500">{rede.avisos.mesma_rede}</p>
      {contextos.map((t) => (
        <Aviso key={t.chave} testId="ideb-rede-contexto">
          <p>
            <b className="font-medium">{t.rotulo}: {t.rotulo_contexto ?? "outra rede, só contexto"}.</b>{" "}
            {ideb.texto_uf_sem_rede_municipal ?? t.motivo_contexto}
          </p>
        </Aviso>
      ))}
      <figure className="min-w-0 max-w-2xl space-y-1" data-testid="ideb-rede-grafico">
        <figcaption className="text-xs font-medium text-zinc-700 dark:text-zinc-200">{legenda}</figcaption>
        <GraficoLinha series={series} eixoX={eixoX} minimo={minimo} maximo={maximo} altura={200}
                      formato={(v) => numeroBR(v, 1)}
                      rotulo={`Ideb de ${mun.rotulo} por edição, de ${periodo}${comMeta ? ", com a meta do 1º ciclo tracejada" : ""}${
                        mesmas.length ? ` e ${juntar(mesmas.map((t) => t.rotulo))} (mesma rede)` : ""}`} />
      </figure>
      <p className="text-[11px] text-zinc-500">
        Sem número numa edição, a linha quebra (nunca vai a 0).
        {contextos.length > 0 && ` ${contextos.map((t) => t.rotulo).join(" e ")} não entra no gráfico: é outra rede — `
          + "aparece só na tabela, como contexto."}
      </p>
      <table className="w-full max-w-3xl table-fixed text-sm">
        <caption className="sr-only">
          Ideb por edição: {territorios.map((t) => `${t.rotulo}${t.contexto ? " (outra rede, só contexto)" : ""}`).join("; ")}
        </caption>
        <Colunas primeira={16} n={territorios.length} />
        <thead>
          <tr className="text-left text-xs text-zinc-500">
            <th scope="col" className="py-1 pr-2 font-medium">Edição</th>
            {territorios.map((t) => <CabecalhoTerritorio key={t.chave} t={t} />)}
          </tr>
        </thead>
        <tbody>
          {ideb.edicoes.map((edicao) => (
            <tr key={edicao} className="border-t border-zinc-100 align-top dark:border-zinc-800">
              <th scope="row" className="py-1.5 pr-2 text-left font-normal tabular-nums">{edicao}</th>
              {territorios.map((t) => (
                <CelulaIdebTerritorio key={t.chave} dados={dados} t={t} ed={t.serie.find((e) => e.edicao === edicao)} />
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="text-[11px] text-zinc-500" data-testid="ideb-rede-metas">
        {dados.avisos.precisao}
        {semMeta.length > 0 && ` Em ${semMeta.join(" e ")}, o INEP não definiu meta do Ideb (as metas do 1º ciclo vão `
          + `até ${ideb.anos_meta.length ? Math.max(...ideb.anos_meta) : 2021}) — nada é comparado.`}
      </p>
      <details className="text-xs" data-testid="ideb-rede-nota-saeb">
        <summary className="cursor-pointer text-zinc-500">Nota do Saeb no Ideb, N, P e aprovação da rede municipal</summary>
        <p className="mt-1 text-[11px] text-zinc-600 dark:text-zinc-300" data-testid="ideb-rede-universo">
          <b className="font-medium">Universo da nota do Saeb no Ideb:</b> {mun.universo_saeb.rotulo}
        </p>
        <table className="mt-1 w-full table-fixed text-xs">
          <caption className="sr-only">
            Nota do Saeb que entra no Ideb (só escolas urbanas), N, P e aprovação de {mun.rotulo}, por edição
          </caption>
          <Colunas primeira={16} n={3} />
          <thead>
            <tr className="text-left text-zinc-500">
              <th scope="col" className="py-1 pr-2 font-medium">Edição</th>
              <th scope="col" className="py-1 pr-2 font-medium">Nota do Saeb no Ideb (LP · MT)</th>
              <th scope="col" className="py-1 pr-2 font-medium"><abbr title="Nota média padronizada" className="no-underline">N</abbr> · <abbr title="Indicador de rendimento" className="no-underline">P</abbr></th>
              <th scope="col" className="py-1 font-medium">Aprovação 1º ao 5º</th>
            </tr>
          </thead>
          <tbody>
            {mun.serie.map((e) => (
              <tr key={e.edicao} className="border-t border-zinc-100 align-top dark:border-zinc-800">
                <th scope="row" className="py-1 pr-2 text-left font-normal tabular-nums">{e.edicao}</th>
                <td className="break-words py-1 pr-2">
                  <Valor dados={dados} n={e.nota_saeb.lp} casas={2} /> · <Valor dados={dados} n={e.nota_saeb.mt} casas={2} />
                </td>
                <td className="break-words py-1 pr-2">
                  <Valor dados={dados} n={e.nota_n} casas={6} /> · <Valor dados={dados} n={e.rendimento_p} casas={6} />
                </td>
                <td className="py-1"><Valor dados={dados} n={e.aprovacao} casas={1} sufixo="%" /></td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="mt-1 text-[11px] text-zinc-500">{rede.avisos.universo} O Ideb é N × P.</p>
      </details>
      <SeloFonte titulo="Fontes do Ideb da rede, da UF e do Brasil" testId="ideb-rede-selo" fontes={fontes} />
    </Bloco>
  );
}

// --- Saeb do 5º ano (planilha) ------------------------------------------------------------

function nomeCurtoSaeb(t: TerritorioSaeb): string {
  return t.chave === "rede_municipal" ? "Rede municipal" : `${t.nome} (redes municipais)`;
}

function numerosSaeb(t: TerritorioSaeb): (NumeroIDEB | null)[] {
  return t.edicoes.flatMap((e) => [e.media.lp, e.media.mt, ...e.niveis.lp.niveis, ...e.niveis.mt.niveis]);
}

/** A tabela equivalente às barras, com os níveis nas LINHAS (cabe no celular). */
function TabelaNiveis({ legenda, colunas, faixas }: {
  legenda: string; colunas: { titulo: string; dist: DistribuicaoSaeb | undefined }[];
  faixas: { nivel: number; inicio: number | null; fim: number | null }[];
}) {
  return (
    <table className="mt-1 w-full table-fixed text-xs">
      <caption className="sr-only">{legenda}</caption>
      <Colunas primeira={34} n={colunas.length} />
      <thead>
        <tr className="text-left text-zinc-500">
          <th scope="col" className="py-1 pr-2 font-medium">Nível (pontos)</th>
          {colunas.map((c) => <th key={c.titulo} scope="col" className="break-words py-1 pr-2 font-medium">{c.titulo}</th>)}
        </tr>
      </thead>
      <tbody>
        {faixas.map((f) => (
          <tr key={f.nivel} className="border-t border-zinc-100 dark:border-zinc-800">
            <th scope="row" className="break-words py-1 pr-2 text-left font-normal">
              Nível {f.nivel} <span className="text-zinc-500">({textoFaixa(f)})</span>
            </th>
            {colunas.map((c) => {
              const n = c.dist?.niveis.find((x) => x.nivel === f.nivel);
              return (
                <td key={c.titulo} className="py-1 pr-2 tabular-nums">
                  {n && n.valor != null ? formatoNivel(n.valor)
                    : <span className="text-zinc-500">{n ? textoAusenciaIDEB(n) : "—"}</span>}
                </td>
              );
            })}
          </tr>
        ))}
        <tr className="border-t border-zinc-200 dark:border-zinc-700">
          <th scope="row" className="py-1 pr-2 text-left font-normal text-zinc-500">Soma</th>
          {colunas.map((c) => (
            <td key={c.titulo} className="py-1 pr-2 tabular-nums text-zinc-500">
              {c.dist?.soma != null ? formatoNivel(c.dist.soma) : "—"}
            </td>
          ))}
        </tr>
      </tbody>
    </table>
  );
}

function BlocoSaeb({ dados }: { dados: RespostaIDEB }) {
  const rede = dados.rede_municipal;
  const saeb = rede.saeb;
  const [componente, setComponente] = useState<Componente>("lp");
  const mun = saeb.territorios.find((t) => t.chave === "rede_municipal");
  if (!mun || !mun.tem_dados) {
    // O que falta, sem afirmar o que existe: a UF e o Brasil podem estar na base (a planilha que
    // outra rede importou), e a planilha desta rede pode não trazer o município.
    const importadas = saeb.edicoes_importadas_rede ?? [];
    const comReferencia = saeb.territorios.some((t) => t.chave !== "rede_municipal" && t.tem_dados);
    const texto = importadas.length > 0
      ? `A planilha de resultados do Saeb importada para esta rede (${juntar(importadas.map(String))}) não traz número `
        + "da rede municipal (dependência municipal, localização Total)."
      : comReferencia
        ? "Sem a planilha de resultados do Saeb importada para esta rede (médias e níveis da rede municipal)."
        : "Sem a planilha de resultados do Saeb importada (médias e níveis da rede, do estado e do Brasil).";
    return (
      <Bloco titulo="Saeb do 5º ano da rede (planilha do INEP)" testId="ideb-saeb-rede">
        <SemDado testId="ideb-saeb-rede-sem-dado" texto={texto} />
      </Bloco>
    );
  }
  const outros = saeb.territorios.filter((t) => t.chave !== "rede_municipal");
  const periodo = periodoIDEB(saeb.edicoes);
  const ultima = saeb.edicoes[saeb.edicoes.length - 1];
  const nomeComp = COMPONENTES.find((c) => c.valor === componente)?.texto ?? componente;
  const faixas = saeb.regua[componente];
  const barras = [
    ...mun.edicoes.map((e) => ({ rotulo: `${mun.rotulo} — ${e.edicao}`, dist: e.niveis[componente] })),
    ...outros.map((t) => ({
      rotulo: `${t.rotulo} — ${ultima}`, dist: t.edicoes.find((x) => x.edicao === ultima)?.niveis[componente],
    })),
  ];
  const fontes = fontesDosNumeros(dados, saeb.territorios.flatMap(numerosSaeb));
  return (
    <Bloco titulo={`Saeb do 5º ano da rede — planilha do INEP (${periodo})`} testId="ideb-saeb-rede">
      <p className="text-xs text-zinc-500">{rede.avisos.saeb_planilha}</p>
      <p className="text-xs text-zinc-700 dark:text-zinc-200" data-testid="ideb-saeb-localizacao">
        Localização: <b className="font-medium">{saeb.rotulo_localizacao}</b>. Comparação na mesma dependência: as redes
        municipais.
      </p>
      <table className="w-full max-w-3xl table-fixed text-sm">
        <caption className="sr-only">
          Média do Saeb do 5º ano (Língua Portuguesa e Matemática), localização Total, por edição: {saeb.territorios.map((t) => t.rotulo).join("; ")}
        </caption>
        <Colunas primeira={16} n={saeb.territorios.length} />
        <thead>
          <tr className="text-left text-xs text-zinc-500">
            <th scope="col" className="py-1 pr-2 font-medium">Edição</th>
            {saeb.territorios.map((t) => (
              <th key={t.chave} scope="col" className="break-words py-1 pr-2 font-medium" title={t.rotulo}>{nomeCurtoSaeb(t)}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {saeb.edicoes.map((ed) => (
            <tr key={ed} className="border-t border-zinc-100 align-top dark:border-zinc-800">
              <th scope="row" className="py-1.5 pr-2 text-left font-normal tabular-nums">{ed}</th>
              {saeb.territorios.map((t) => {
                const e = t.edicoes.find((x) => x.edicao === ed);
                return (
                  <td key={t.chave} className="break-words py-1.5 pr-2 text-xs">
                    {e ? (
                      <>
                        <span className="block"><abbr title="Língua Portuguesa" className="no-underline">LP</abbr>{" "}
                          <Valor dados={dados} n={e.media.lp} casas={2} forte={t.chave === "rede_municipal"} /></span>
                        <span className="block"><abbr title="Matemática" className="no-underline">MT</abbr>{" "}
                          <Valor dados={dados} n={e.media.mt} casas={2} forte={t.chave === "rede_municipal"} /></span>
                      </>
                    ) : <span className="text-zinc-400">—</span>}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="text-[11px] text-zinc-500" data-testid="ideb-saeb-2023">{rede.avisos.saeb_2023}</p>

      <div className="space-y-2 pt-1" data-testid="ideb-saeb-niveis">
        <h4 className="text-xs font-semibold text-zinc-700 dark:text-zinc-200">Distribuição por nível — {nomeComp}</h4>
        <Seletor rotulo="Componente" valor={componente} opcoes={COMPONENTES} aoMudar={setComponente} />
        <div className="max-w-2xl">
          <BarraEmpilhada tabela={false} cores={CORES_NIVEIS} formato={formatoNivel}
                          rotulo={`Percentual de alunos do 5º ano em cada nível de ${nomeComp} (0 a ${faixas.length - 1}): a rede por edição e, em ${ultima}, o estado e o Brasil nas redes municipais`}
                          barras={barras.map((b) => ({
                            rotulo: b.rotulo,
                            segmentos: (b.dist?.niveis ?? []).map((n) => ({ nome: `Nível ${n.nivel}`, valor: n.valor })),
                          }))} />
        </div>
        <p className="text-[11px] text-zinc-500">{rede.avisos.niveis}</p>
        <details className="text-xs">
          <summary className="cursor-pointer text-zinc-500">Ver os números do gráfico ({nomeComp})</summary>
          <p className="mt-1 font-medium text-zinc-600 dark:text-zinc-300">{mun.rotulo}, por edição</p>
          <TabelaNiveis legenda={`Percentual de alunos em cada nível de ${nomeComp}: ${mun.rotulo} por edição`}
                        faixas={faixas}
                        colunas={mun.edicoes.map((e) => ({ titulo: String(e.edicao), dist: e.niveis[componente] }))} />
          <p className="mt-2 font-medium text-zinc-600 dark:text-zinc-300">Em {ultima}, nas redes municipais</p>
          <TabelaNiveis legenda={`Percentual de alunos em cada nível de ${nomeComp} em ${ultima}: a rede, o estado e o Brasil nas redes municipais`}
                        faixas={faixas}
                        colunas={saeb.territorios.map((t) => ({
                          titulo: t.chave === "rede_municipal" ? "Rede" : t.nome,
                          dist: t.edicoes.find((e) => e.edicao === ultima)?.niveis[componente],
                        }))} />
        </details>
        <details className="text-xs" data-testid="ideb-saeb-cortes">
          <summary className="cursor-pointer text-zinc-500">Cortes dos níveis do Saeb do 5º ano (fonte)</summary>
          <table className="mt-1 w-full table-fixed text-xs">
            <caption className="sr-only">Cortes dos níveis do Saeb do 5º ano, em pontos da escala do Saeb</caption>
            <Colunas primeira={20} n={2} />
            <thead>
              <tr className="text-left text-zinc-500">
                <th scope="col" className="py-1 pr-2 font-medium">Nível</th>
                <th scope="col" className="py-1 pr-2 font-medium">Língua Portuguesa</th>
                <th scope="col" className="py-1 font-medium">Matemática</th>
              </tr>
            </thead>
            <tbody>
              {saeb.regua.mt.map((f) => {
                const lp = saeb.regua.lp.find((x) => x.nivel === f.nivel);
                return (
                  <tr key={f.nivel} className="border-t border-zinc-100 dark:border-zinc-800">
                    <th scope="row" className="py-1 pr-2 text-left font-normal">{f.nivel}</th>
                    <td className="py-1 pr-2">{lp ? textoFaixa(lp) : "— (a escala de LP vai até o nível 9)"}</td>
                    <td className="py-1">{textoFaixa(f)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <p className="mt-1 text-[11px] text-zinc-500">Fonte dos cortes: {saeb.regua.fonte}</p>
          <p className="text-[11px] text-zinc-500">{saeb.regua.texto_outras_edicoes}</p>
        </details>
      </div>
      <SeloFonte titulo="Fontes do Saeb da rede, do estado e do Brasil" testId="ideb-saeb-rede-selo" fontes={fontes} />
    </Bloco>
  );
}

// --- Contexto amostral -------------------------------------------------------------------

function BlocoAmostral({ dados }: { dados: RespostaIDEB }) {
  const c = dados.contexto_amostral;
  if (!c.tem_dados) return null;
  const linhas = c.territorios.flatMap((t) => t.edicoes.map((e) => ({ t, e })));
  const fontes = fontesDosNumeros(dados, linhas.flatMap(({ e }) => [e.media.lp, e.media.mt, e.tx_alfabetizado]));
  return (
    <Bloco titulo={`Contexto amostral — Saeb do 2º ano (${periodoIDEB(c.edicoes)})`} testId="ideb-amostral">
      <p><Badge tom="neutro">amostral, só contexto</Badge> <Badge tom="alerta">não é o ICA</Badge></p>
      <Nota testId="ideb-amostral-aviso">
        <p>{c.aviso}</p>
        <p>{c.nao_e_ica}</p>
      </Nota>
      <table className="w-full max-w-3xl table-fixed text-sm">
        <caption className="sr-only">Saeb do 2º ano (amostral): médias e taxa de alfabetização do estado e do Brasil</caption>
        <Colunas primeira={34} n={3} />
        <thead>
          <tr className="text-left text-xs text-zinc-500">
            <th scope="col" className="py-1 pr-2 font-medium">Território (amostral)</th>
            <th scope="col" className="py-1 pr-2 font-medium">Média 2º ano LP</th>
            <th scope="col" className="py-1 pr-2 font-medium">Média 2º ano MT</th>
            <th scope="col" className="py-1 font-medium">Taxa de alfabetização do Saeb</th>
          </tr>
        </thead>
        <tbody>
          {linhas.map(({ t, e }) => (
            <tr key={`${t.chave}-${e.edicao}`} className="border-t border-zinc-100 align-top dark:border-zinc-800">
              <th scope="row" className="break-words py-1.5 pr-2 text-left font-normal">
                {t.nome} (redes municipais), {e.edicao}
              </th>
              <td className="py-1.5 pr-2"><Valor dados={dados} n={e.media.lp} casas={2} /></td>
              <td className="py-1.5 pr-2"><Valor dados={dados} n={e.media.mt} casas={2} /></td>
              <td className="py-1.5"><Valor dados={dados} n={e.tx_alfabetizado} casas={2} sufixo="%" /></td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="text-[11px] text-zinc-500">
        As médias do 2º ano estão na escala do 2º ano do Saeb (outra escala): não se comparam com o 5º ano.
      </p>
      <SeloFonte titulo="Fontes do contexto amostral" testId="ideb-amostral-selo" fontes={fontes} />
    </Bloco>
  );
}

export default function RedeIDEB({ dados }: { dados: RespostaIDEB }) {
  return (
    <div className="space-y-6" data-testid="ideb-parte-rede">
      <BlocoIdeb dados={dados} />
      <BlocoSaeb dados={dados} />
      <BlocoAmostral dados={dados} />
    </div>
  );
}
