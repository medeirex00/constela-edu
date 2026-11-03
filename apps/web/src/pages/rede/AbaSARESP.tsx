/**
 * Aba SARESP dos indicadores oficiais (plano, 5.1; etapa E5) — o que a Secretaria e o
 * admin global leem do SARESP OFICIAL da SEDUC-SP, em três partes:
 *
 *  - REDE MUNICIPAL: as médias por série (2º e 5º ano) e componente (LP, MT), um
 *    gráfico por série/componente, com o Estado na MESMA rede (redes municipais de
 *    SP). O 2º ano NÃO tem linha de 2022 para 2023 (possível quebra de escala —
 *    plano, 4.9 e (1).8): o ponto de 2022 fica solto. A tabela marca os anos em que os
 *    pontos de corte dos níveis estão "a confirmar" — o Constela não inventa corte e
 *    não diz em que nível cai a média. A rede estadual (outra rede) fica à parte,
 *    só como contexto;
 *  - POR ESCOLA: a proficiência OFICIAL (IEE), a participação, o TPS, o IEE e a meta,
 *    em ORDEM ALFABÉTICA — sem ranking, sem "melhor/pior". As médias sem
 *    proveniência oficial (estimativa do Constela) vêm num bloco SEPARADO e
 *    rotulado, nunca na tabela oficial;
 *  - COBERTURA: quantas escolas da rede têm resultado oficial em cada edição, por que
 *    as outras não têm ("sem resultado" nunca é 0), as escolas sem código INEP
 *    (pendência de cadastro) e as do arquivo sem escola no cadastro (pelo código).
 *
 * Cada bloco tem o selo de fonte (arquivo, edição, data do arquivo). As abas seguem o
 * padrão de `CartaoICA` (aba → `aria-controls` → `tabpanel` rotulado).
 */
import { AlertTriangle } from "lucide-react";
import { type ReactNode, useId, useState } from "react";

import { GraficoLinha, type PontoSerie, type SerieLinha } from "../../components/Grafico";
import SeloFonte, { textoFonte } from "../../components/SeloFonte";
import { Badge } from "../../components/ui";
import { numeroBR } from "./ica";
import { classeAba, classeTrilhoAbas } from "./visualIndicadores";
import {
  COMPONENTES,
  ETAPAS,
  MOTIVOS_SARESP,
  ROTULO_COMPONENTE,
  ROTULO_ETAPA,
  ROTULO_NIVEL,
  SIGLA_COMPONENTE,
  media,
  serieDe,
  textoAusencia,
  type CoberturaEdicao,
  type Componente,
  type EdicaoEscola,
  type Etapa,
  type FonteSARESP,
  type LinhaEscola,
  type NumeroSARESP,
  type RespostaSARESP,
  type TerritorioSARESP,
} from "./saresp";

// Mesmas cores da aba do ICA: a rede do município no violeta da marca, o Estado nas redes
// municipais em âmbar. A legenda e a tabela dizem o nome (a cor não é o único código).
const COR = { rede: "#6C5CE7", estado: "#D97706" };

const formatoMedia = (v: number) => numeroBR(v, 1);

function fontesDe(numeros: (NumeroSARESP | null | undefined)[]): (FonteSARESP | null)[] {
  return numeros.map((n) => n?.fonte ?? null);
}

function Bloco({ titulo, children, testId }: { titulo: string; children: ReactNode; testId?: string }) {
  return (
    <section className="space-y-2" aria-label={titulo} data-testid={testId}>
      <h3 className="text-sm font-semibold text-zinc-800 dark:text-zinc-100">{titulo}</h3>
      {children}
    </section>
  );
}

function Aviso({ children, testId }: { children: ReactNode; testId?: string }) {
  return (
    <p className="flex items-start gap-1.5 rounded-lg bg-amber-50 p-2.5 text-xs text-amber-800 dark:bg-amber-500/10 dark:text-amber-300"
       data-testid={testId}>
      <AlertTriangle size={14} className="mt-0.5 shrink-0" />
      <span>{children}</span>
    </p>
  );
}

/** O número com a fonte no título (e para leitor de tela); sem número, o motivo. Com o
 *  corte da edição CONFIRMADO, o nível em que cai a média e a distância até o Adequado
 *  (cálculo do Constela; a distância só quando a média está abaixo do Adequado). */
function Media({ n }: { n: NumeroSARESP | null | undefined }) {
  if (!n) return <span className="text-xs text-zinc-400">sem resultado</span>;
  if (n.valor == null) return <span className="text-xs text-zinc-500">{textoAusencia(n)}</span>;
  const fonte = n.fonte ? textoFonte(n.fonte) : null;
  const distancia = n.nivel?.distancia_adequado;
  return (
    <span className="tabular-nums" title={fonte ? `Fonte: ${fonte}` : undefined}>
      {media(n)}
      {n.nivel?.nivel && (
        <span className="block text-[11px] text-zinc-500">
          nível {ROTULO_NIVEL[n.nivel.nivel] ?? n.nivel.nivel}
          {distancia != null && distancia > 0 && `, a ${numeroBR(distancia, 1)} pontos do Adequado`}
          {" "}(cálculo do Constela)
        </span>
      )}
      {fonte && <span className="sr-only"> — fonte: {fonte}</span>}
    </span>
  );
}

// --- Rede municipal ------------------------------------------------------------

/**
 * Os pontos da série com a QUEBRA de escala: entre `de` e `para` entra um ponto SEM
 * valor e fora do eixo — a lacuna documentada do `GraficoLinha` (valor nulo / ponto
 * fora do eixo quebram a linha). Assim 2022 continua visível, mas solto.
 */
function pontos(numeros: NumeroSARESP[], quebras: { de: number; para: number }[]): PontoSerie[] {
  const saida: PontoSerie[] = [];
  for (const n of [...numeros].sort((a, b) => a.edicao - b.edicao)) {
    const q = quebras.find((x) => x.para === n.edicao);
    if (q && saida.length > 0) saida.push({ rotulo: `quebra ${q.de}-${q.para}`, valor: null });
    saida.push({ rotulo: String(n.edicao), valor: n.valor });
  }
  return saida;
}

/** Faixa do eixo por série (as duas disciplinas e os dois territórios na mesma). */
function faixa(valores: number[]): { minimo: number; maximo: number } {
  return {
    minimo: Math.max(0, Math.floor((Math.min(...valores) - 10) / 10) * 10),
    maximo: Math.ceil((Math.max(...valores) + 10) / 10) * 10,
  };
}

function GraficosDaRede({ dados, rede, estado }: {
  dados: RespostaSARESP; rede: TerritorioSARESP; estado?: TerritorioSARESP;
}) {
  const anos = dados.edicoes_rede;
  if (anos.length === 0) return <p className="text-sm text-zinc-500">Sem a série da rede importada.</p>;
  const eixoX: string[] = [];
  for (let a = Math.min(...anos); a <= Math.max(...anos); a += 1) eixoX.push(String(a));
  const comEstado = Boolean(estado?.tem_dados);
  return (
    <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
      {ETAPAS.flatMap((etapa) => {
        const quebras = dados.quebras_de_escala.filter((q) => q.etapa === etapa);
        const valores = COMPONENTES
          .flatMap((c) => [...serieDe(rede, etapa, c), ...(comEstado ? serieDe(estado, etapa, c) : [])])
          .flatMap((n) => (n.valor == null ? [] : [n.valor]));
        return COMPONENTES.map((comp) => {
          const titulo = `${ROTULO_ETAPA[etapa]} — ${ROTULO_COMPONENTE[comp]}`;
          const series: SerieLinha[] = [
            { nome: rede.rotulo, cor: COR.rede, pontos: pontos(serieDe(rede, etapa, comp), quebras) },
            ...(comEstado && estado
              ? [{ nome: estado.rotulo, cor: COR.estado, pontos: pontos(serieDe(estado, etapa, comp), quebras) }]
              : []),
          ];
          const quebraNoEixo = quebras.filter((q) => eixoX.includes(String(q.de)) && eixoX.includes(String(q.para)));
          const { minimo, maximo } = valores.length > 0 ? faixa(valores) : { minimo: 0, maximo: 300 };
          return (
            <figure key={`${etapa}-${comp}`} className="space-y-1" data-testid={`saresp-grafico-${etapa}-${comp}`}>
              <figcaption className="text-xs font-medium text-zinc-700 dark:text-zinc-200">{titulo}</figcaption>
              <GraficoLinha
                series={series} eixoX={eixoX} minimo={minimo} maximo={maximo} altura={200}
                formato={formatoMedia}
                rotulo={`${titulo}: média do SARESP por ano — ${series.map((s) => s.nome).join(" e ")}${
                  quebraNoEixo.map((q) => `. Sem linha de ${q.de} para ${q.para} (possível quebra de escala)`).join("")}`}
                tabela={`Números do gráfico: ${titulo}`}
              />
              {quebraNoEixo.map((q) => (
                <p key={q.de} className="text-[11px] text-amber-700 dark:text-amber-400" data-testid="saresp-quebra">
                  Sem linha de {q.de} para {q.para}: possível quebra de escala no {ROTULO_ETAPA[etapa]}.
                </p>
              ))}
            </figure>
          );
        });
      })}
    </div>
  );
}

function TabelaDaRede({ dados, territorios, legenda }: {
  dados: RespostaSARESP; territorios: TerritorioSARESP[]; legenda: string;
}) {
  const anos = dados.edicoes_rede;
  // Edições cujos pontos de corte (de qualquer série/componente) estão a confirmar.
  const aConfirmar = new Set(dados.niveis.edicoes_a_confirmar);
  return (
    <div className="relative overflow-x-auto">
      <table className="w-full text-sm">
        <caption className="sr-only">{legenda}</caption>
        <thead>
          <tr className="text-left text-xs text-zinc-500">
            <th scope="col" className="py-1 pr-3 font-medium">Série e componente</th>
            <th scope="col" className="py-1 pr-3 font-medium">Rede</th>
            {anos.map((a) => (
              <th key={a} scope="col" className="py-1 pr-3 font-medium tabular-nums">
                {a}
                {aConfirmar.has(a) && (
                  <abbr title="Pontos de corte dos níveis a confirmar nesta edição" className="no-underline"> *</abbr>
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {ETAPAS.flatMap((etapa) => COMPONENTES.flatMap((comp) => territorios.map((t, i) => {
            const porAno = new Map(serieDe(t, etapa, comp).map((n) => [n.edicao, n]));
            return (
              <tr key={`${etapa}-${comp}-${t.chave}`}
                  className={`${i === 0 ? "border-t border-zinc-200 dark:border-zinc-700" : ""} align-top`}>
                {i === 0 && (
                  <th scope="rowgroup" rowSpan={territorios.length} className="py-1.5 pr-3 text-left text-xs font-medium">
                    {ROTULO_ETAPA[etapa]} · {ROTULO_COMPONENTE[comp]}
                  </th>
                )}
                <td className="py-1.5 pr-3 text-xs text-zinc-600 dark:text-zinc-300">{t.rotulo}</td>
                {anos.map((a) => (
                  <td key={a} className="py-1.5 pr-3">
                    {porAno.has(a) ? <Media n={porAno.get(a)} />
                      : <span className="text-xs text-zinc-400">sem resultado</span>}
                  </td>
                ))}
              </tr>
            );
          })))}
        </tbody>
      </table>
    </div>
  );
}

/** Título do bloco dos níveis: "a confirmar" só enquanto houver corte a confirmar. */
function tituloNiveis(dados: RespostaSARESP): string {
  const base = "Níveis de proficiência do SARESP";
  if (dados.niveis.edicoes_a_confirmar.length === 0) return base;
  const algumConfirmado = dados.niveis.cortes.some((c) => c.situacao === "confirmado");
  return `${base} — ${algumConfirmado ? "parte a confirmar" : "a confirmar"}`;
}

function Niveis({ dados }: { dados: RespostaSARESP }) {
  const edicoes = [...new Set(dados.niveis.cortes.map((c) => c.edicao))].sort((a, b) => a - b);
  const corte = (edicao: number, etapa: Etapa, comp: Componente) =>
    dados.niveis.cortes.find((c) => c.edicao === edicao && c.etapa === etapa && c.componente === comp);
  // A fonte de cada corte CONFIRMADO (o "a confirmar" não tem fonte a citar).
  const fontesDosCortes = [...new Set(dados.niveis.cortes
    .filter((c) => c.situacao === "confirmado" && c.basico != null)
    .map((c) => c.fonte))];
  return (
    <>
      <p className="text-xs text-zinc-600 dark:text-zinc-300">{dados.niveis.aviso}</p>
      <div className="relative overflow-x-auto">
        <table className="w-full text-sm">
          <caption className="sr-only">Pontos de corte dos níveis do SARESP por edição</caption>
          <thead>
            <tr className="text-left text-xs text-zinc-500">
              <th scope="col" className="py-1 pr-3 font-medium">Edição</th>
              {ETAPAS.flatMap((e) => COMPONENTES.map((c) => (
                <th key={`${e}-${c}`} scope="col" className="py-1 pr-3 font-medium">
                  {ROTULO_ETAPA[e]} {SIGLA_COMPONENTE[c]}
                </th>
              )))}
            </tr>
          </thead>
          <tbody>
            {edicoes.map((ed) => (
              <tr key={ed} className="border-t border-zinc-100 dark:border-zinc-800">
                <th scope="row" className="py-1.5 pr-3 text-left font-normal tabular-nums">{ed}</th>
                {ETAPAS.flatMap((e) => COMPONENTES.map((c) => {
                  const k = corte(ed, e, c);
                  return (
                    <td key={`${e}-${c}`} className="py-1.5 pr-3 text-xs">
                      {k && k.situacao === "confirmado" && k.basico != null
                        ? <span title={`Fonte: ${k.fonte}`}>
                            {`Básico ${numeroBR(k.basico, 0)} · Adequado ${numeroBR(k.adequado ?? 0, 0)} · Avançado ${numeroBR(k.avancado ?? 0, 0)}`}
                          </span>
                        : <span className="text-zinc-500">a confirmar</span>}
                    </td>
                  );
                }))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {fontesDosCortes.length > 0 && (
        <p className="text-[11px] text-zinc-500" data-testid="saresp-niveis-fonte">
          Fonte dos pontos de corte confirmados: {fontesDosCortes.join("; ")}.
        </p>
      )}
      <p className="text-[11px] text-zinc-500">
        Níveis do SARESP: {dados.niveis.rotulos.map((r) => r.rotulo).join(", ")}. Os dados abertos não trazem
        quantos alunos estão em cada nível.
      </p>
    </>
  );
}

function OutrasRedes({ dados, territorios }: { dados: RespostaSARESP; territorios: TerritorioSARESP[] }) {
  if (territorios.length === 0) return null;
  const comDados = territorios.filter((t) => t.tem_dados);
  return (
    <details className="rounded-lg border border-zinc-200 p-3 text-sm dark:border-zinc-800" data-testid="saresp-outras-redes">
      <summary className="cursor-pointer text-xs font-medium text-zinc-600 dark:text-zinc-300">
        Rede estadual — outra rede, só como contexto
      </summary>
      <div className="mt-2 space-y-2">
        <p className="text-xs text-zinc-500">
          A rede estadual não é a rede municipal: estes números não servem para comparar a rede do município.
        </p>
        {territorios.filter((t) => !t.tem_dados).map((t) => (
          <p key={t.chave} className="text-xs text-zinc-500">{t.rotulo}: sem resultado de 2º e 5º ano nos arquivos importados.</p>
        ))}
        {comDados.length > 0 && (
          <>
            <TabelaDaRede dados={dados} territorios={comDados} legenda="Médias do SARESP da rede estadual (outra rede)" />
            <SeloFonte titulo="Fontes da rede estadual"
                       fontes={comDados.flatMap((t) => t.series.flatMap((s) => fontesDe(s.numeros)))} />
          </>
        )}
      </div>
    </details>
  );
}

function ParteRede({ dados }: { dados: RespostaSARESP }) {
  const rede = dados.territorios.find((t) => t.chave === "rede_municipal");
  const estado = dados.territorios.find((t) => t.chave === "estado_redes_municipais");
  const outras = dados.territorios.filter((t) => !t.mesma_rede);
  if (!rede || !rede.tem_dados) {
    return (
      <p className="rounded-lg border border-dashed border-zinc-300 p-4 text-sm text-zinc-500 dark:border-zinc-700"
         data-testid="saresp-rede-sem-resultado">
        Sem a série da rede municipal importada (SARESP por município).
      </p>
    );
  }
  const mesmaRede = [rede, ...(estado?.tem_dados ? [estado] : [])];
  return (
    <div className="space-y-6">
      <Aviso testId="saresp-aviso-2ano">
        {dados.quebras_de_escala.filter((q) => q.etapa === "2_ano").map((q) => q.motivo)[0]}{" "}
        {dados.avisos.segundo_ano_x_ica}
      </Aviso>
      <Bloco titulo={`Médias da rede municipal por série e componente${estado?.tem_dados ? ", com o Estado na mesma rede" : ""}`}>
        <p className="text-xs text-zinc-500">{dados.avisos.comparacao}</p>
        <GraficosDaRede dados={dados} rede={rede} estado={estado} />
        <TabelaDaRede dados={dados} territorios={mesmaRede}
                      legenda="Médias do SARESP da rede municipal e do Estado (redes municipais), por ano" />
        {dados.niveis.edicoes_a_confirmar.length > 0 && (
          <p className="text-[11px] text-zinc-500" data-testid="saresp-anos-a-confirmar">
            * Pontos de corte dos níveis a confirmar em {dados.niveis.edicoes_a_confirmar.join(", ")}: o Constela não diz
            em que nível cai cada média.
          </p>
        )}
        <SeloFonte titulo="Fontes da série da rede" testId="saresp-selo-rede"
                   fontes={mesmaRede.flatMap((t) => t.series.flatMap((s) => fontesDe(s.numeros)))} />
      </Bloco>
      <Bloco titulo={tituloNiveis(dados)} testId="saresp-niveis">
        <Niveis dados={dados} />
      </Bloco>
      <OutrasRedes dados={dados} territorios={outras} />
    </div>
  );
}

// --- Por escola ----------------------------------------------------------------

function Percentual({ n }: { n: NumeroSARESP | null | undefined }) {
  if (!n || n.valor == null) return <span className="text-xs text-zinc-500">{textoAusencia(n)}</span>;
  return <span className="tabular-nums">{numeroBR(n.valor, n.casas_decimais ?? 1)}%</span>;
}

function Indice({ n }: { n: NumeroSARESP | null | undefined }) {
  if (!n || n.valor == null) return <span className="text-xs text-zinc-500">{textoAusencia(n)}</span>;
  return <span className="tabular-nums">{numeroBR(n.valor, n.casas_decimais ?? 2)}</span>;
}

function Tps({ n }: { n: NumeroSARESP | null | undefined }) {
  if (!n || n.valor == null) return <span className="text-xs text-zinc-500">{textoAusencia(n)}</span>;
  return n.valor >= 1 ? <span>atingiu</span> : (
    <span>não atingiu <span className="block text-[11px] text-amber-700 dark:text-amber-400">média instável</span></span>
  );
}

function SimNao({ n }: { n: NumeroSARESP | null | undefined }) {
  if (!n || n.valor == null) return <span className="text-xs text-zinc-500">{textoAusencia(n)}</span>;
  return <span>{n.valor >= 1 ? "sim" : "não"}</span>;
}

const COLUNAS_ESCOLA = 10;

function LinhaDaEscola({ linha, ed }: { linha: LinhaEscola; ed: EdicaoEscola | undefined }) {
  const nome = (
    <th scope="row" className="py-1.5 pr-3 text-left font-normal">
      {linha.nome}
      {linha.status !== "ativa" && <span className="text-xs text-zinc-500"> (inativa)</span>}
    </th>
  );
  if (!linha.codigo_inep) {
    return (
      <tr className="border-t border-zinc-100 align-top dark:border-zinc-800">
        {nome}
        <td colSpan={COLUNAS_ESCOLA} className="py-1.5 text-xs text-zinc-500">
          <Badge tom="alerta">sem código INEP</Badge>{" "}
          Pendência de cadastro: sem o código INEP, a escola não casa com o arquivo oficial.
        </td>
      </tr>
    );
  }
  if (!ed || !ed.no_arquivo) {
    // O motivo é o da API (o mesmo da cobertura) e a estimativa é a DESTA edição.
    return (
      <tr className="border-t border-zinc-100 align-top dark:border-zinc-800">
        {nome}
        <td colSpan={COLUNAS_ESCOLA} className="py-1.5 text-xs text-zinc-500">
          Sem resultado oficial: {MOTIVOS_SARESP[ed?.motivo ?? ""] ?? "sem resultado"}.
          {ed?.tem_estimativa && " Há uma estimativa do Constela desta edição (não oficial), no bloco abaixo."}
        </td>
      </tr>
    );
  }
  const p = ed.proficiencia;
  return (
    <tr className="border-t border-zinc-100 align-top dark:border-zinc-800">
      {nome}
      <td className="py-1.5 pr-3"><Media n={p["2_ano"].lp} /></td>
      <td className="py-1.5 pr-3"><Media n={p["2_ano"].mt} /></td>
      <td className="py-1.5 pr-3"><Percentual n={ed.participacao["2_ano"]} /></td>
      <td className="py-1.5 pr-3"><Media n={p["5_ano"].lp} /></td>
      <td className="py-1.5 pr-3"><Media n={p["5_ano"].mt} /></td>
      <td className="py-1.5 pr-3"><Percentual n={ed.participacao["5_ano"]} /></td>
      <td className="py-1.5 pr-3 text-xs"><Tps n={ed.tps} /></td>
      <td className="py-1.5 pr-3"><Indice n={ed.iee} /></td>
      <td className="py-1.5 pr-3"><Indice n={ed.meta} /></td>
      <td className="py-1.5 text-xs"><SimNao n={ed.icm} /></td>
    </tr>
  );
}

function rotuloEdicao(e: number): string {
  return `SARESP ${e} (IEE ${e}-${e + 1})`;
}

function Estimativas({ dados }: { dados: RespostaSARESP }) {
  if (dados.estimativas.length === 0) return null;
  // Ordem por NOME, como a tabela oficial (sem acento e sem caixa); no empate, a ordem
  // da API (edição mais nova primeiro). A tela não depende da ordem da API.
  const lista = [...dados.estimativas]
    .sort((a, b) => a.nome.localeCompare(b.nome, "pt-BR", { sensitivity: "base" }));
  return (
    <section className="space-y-2 rounded-lg border border-amber-300 p-3 dark:border-amber-500/40"
             aria-label="Estimativas do Constela — não oficiais" data-testid="saresp-estimativas">
      <h3 className="flex flex-wrap items-center gap-2 text-sm font-semibold text-zinc-800 dark:text-zinc-100">
        Estimativas do Constela — não oficiais <Badge tom="alerta">estimativa</Badge>
      </h3>
      <p className="text-xs text-zinc-600 dark:text-zinc-300">{dados.avisos.estimativa}</p>
      <div className="relative overflow-x-auto">
        <table className="w-full text-sm">
          <caption className="sr-only">Médias estimadas pelo Constela ou importadas à mão, por escola, em ordem alfabética</caption>
          <thead>
            <tr className="text-left text-xs text-zinc-500">
              <th scope="col" className="py-1 pr-3 font-medium">Escola</th>
              <th scope="col" className="py-1 pr-3 font-medium">Edição</th>
              <th scope="col" className="py-1 pr-3 font-medium">Série</th>
              <th scope="col" className="py-1 pr-3 font-medium">Componente</th>
              <th scope="col" className="py-1 pr-3 font-medium">Média estimada</th>
              <th scope="col" className="py-1 font-medium">De onde veio</th>
            </tr>
          </thead>
          <tbody>
            {lista.map((e) => (
              <tr key={`${e.escola_id}-${e.edicao}-${e.etapa}-${e.componente}`}
                  className="border-t border-zinc-100 align-top dark:border-zinc-800">
                <th scope="row" className="py-1.5 pr-3 text-left font-normal">{e.nome}</th>
                <td className="py-1.5 pr-3 tabular-nums">{e.edicao}</td>
                <td className="py-1.5 pr-3">{e.etapa ? ROTULO_ETAPA[e.etapa] : "série não informada"}</td>
                <td className="py-1.5 pr-3">{ROTULO_COMPONENTE[e.componente ?? ""] ?? e.componente ?? "—"}</td>
                <td className="py-1.5 pr-3 tabular-nums">{numeroBR(e.valor, e.casas_decimais ?? 1)} (estimativa)</td>
                <td className="py-1.5 text-xs text-zinc-500">{e.fonte_texto ?? "importação manual, sem fonte registrada"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function ParteEscolas({ dados }: { dados: RespostaSARESP }) {
  const edicoes = dados.escolas.edicoes;
  const [escolhida, setEscolhida] = useState<number | null>(null);
  const edicao = escolhida ?? edicoes[0];
  const idSeletor = useId();
  if (edicoes.length === 0) {
    return (
      <div className="space-y-4">
        <p className="rounded-lg border border-dashed border-zinc-300 p-4 text-sm text-zinc-500 dark:border-zinc-700"
           data-testid="saresp-escolas-sem-resultado">
          Sem resultado oficial por escola importado (arquivo do IEE).
        </p>
        <Estimativas dados={dados} />
      </div>
    );
  }
  // Ordem por NOME — sem ranking (a API já manda assim; a tela não depende disso).
  const porEscola = [...dados.escolas.linhas]
    .sort((a, b) => a.nome.localeCompare(b.nome, "pt-BR", { sensitivity: "base" }))
    .map((l) => ({ l, ed: l.por_edicao.find((e) => e.edicao === edicao) }));
  const numeros = porEscola.flatMap(({ ed }) => (ed ? [
    ...ETAPAS.flatMap((et) => COMPONENTES.map((c) => ed.proficiencia[et][c])),
    ed.participacao["2_ano"], ed.participacao["5_ano"], ed.tps, ed.iee, ed.meta, ed.icm,
  ] : []));
  const aConfirmar = dados.niveis.edicoes_a_confirmar.includes(edicao);
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-3">
        <label htmlFor={idSeletor} className="text-xs text-zinc-600 dark:text-zinc-300">
          Edição
          <select id={idSeletor} value={edicao} onChange={(e) => setEscolhida(Number(e.target.value))}
                  className="ml-2 rounded-lg border border-zinc-300 bg-white px-2 py-1 text-sm dark:border-zinc-700 dark:bg-zinc-900">
            {edicoes.map((e) => <option key={e} value={e}>{rotuloEdicao(e)}</option>)}
          </select>
        </label>
      </div>
      <Bloco titulo={`Proficiência oficial por escola — ${rotuloEdicao(edicao)}`} testId="saresp-escolas">
        <p className="text-xs text-zinc-500">
          {dados.avisos.sem_ranking} A proficiência por escola vem do arquivo do Índice de Excelência Educacional (IEE)
          da SEDUC-SP. {dados.avisos.tps}
          {aConfirmar && " Nível em que cai cada média e distância até o Adequado: a confirmar onde o ponto de corte desta edição não foi conferido."}
        </p>
        <div className="relative overflow-x-auto">
          <table className="w-full min-w-[56rem] text-sm">
            <caption className="sr-only">
              Proficiência oficial do SARESP {edicao} por escola, em ordem alfabética (não é ranking)
            </caption>
            <thead>
              <tr className="text-left text-xs text-zinc-500">
                <th scope="col" className="py-1 pr-3 font-medium">Escola</th>
                <th scope="col" className="py-1 pr-3 font-medium">2º ano LP</th>
                <th scope="col" className="py-1 pr-3 font-medium">2º ano MT</th>
                <th scope="col" className="py-1 pr-3 font-medium">Participação 2º ano</th>
                <th scope="col" className="py-1 pr-3 font-medium">5º ano LP</th>
                <th scope="col" className="py-1 pr-3 font-medium">5º ano MT</th>
                <th scope="col" className="py-1 pr-3 font-medium">Participação 5º ano</th>
                <th scope="col" className="py-1 pr-3 font-medium">Participação mínima (TPS)</th>
                <th scope="col" className="py-1 pr-3 font-medium">IEE</th>
                <th scope="col" className="py-1 pr-3 font-medium">Meta do IEE</th>
                <th scope="col" className="py-1 font-medium">Cumpriu a meta</th>
              </tr>
            </thead>
            <tbody>
              {porEscola.map(({ l, ed }) => <LinhaDaEscola key={l.escola_id} linha={l} ed={ed} />)}
            </tbody>
          </table>
        </div>
        <SeloFonte titulo={`Fontes da tabela por escola (${edicao})`} testId="saresp-selo-escolas"
                   fontes={fontesDe(numeros)} />
      </Bloco>
      <Estimativas dados={dados} />
    </div>
  );
}

// --- Cobertura -----------------------------------------------------------------

function CoberturaDaEdicao({ c }: { c: CoberturaEdicao }) {
  return (
    <section className="space-y-2 rounded-lg border border-zinc-200 p-3 dark:border-zinc-800"
             aria-label={`Cobertura — ${rotuloEdicao(c.edicao)}`} data-testid={`saresp-cobertura-${c.edicao}`}>
      <h3 className="text-sm font-semibold text-zinc-800 dark:text-zinc-100">{rotuloEdicao(c.edicao)}</h3>
      <p className="text-sm text-zinc-700 dark:text-zinc-200">
        <b className="tabular-nums">{c.com_resultado}</b> de <b className="tabular-nums">{c.total_escolas}</b> escolas
        da rede com resultado oficial.
      </p>
      {c.sem_resultado.length > 0 && (
        <div>
          <p className="text-xs font-medium text-zinc-600 dark:text-zinc-300">
            Sem resultado oficial ({c.sem_resultado.length}) — sem resultado não é zero:
          </p>
          <ul className="list-disc pl-5 text-xs text-zinc-600 dark:text-zinc-400">
            {c.sem_resultado.map((s) => (
              <li key={s.escola_id}>
                {s.nome}: {MOTIVOS_SARESP[s.motivo] ?? "sem resultado"}
                {s.tem_estimativa && " (há estimativa do Constela, não oficial)"}
              </li>
            ))}
          </ul>
        </div>
      )}
      {c.sem_inep.length > 0 && (
        <div>
          <p className="text-xs font-medium text-amber-800 dark:text-amber-300">
            Sem código INEP no cadastro ({c.sem_inep.length}) — pendência de cadastro:
          </p>
          <ul className="list-disc pl-5 text-xs text-zinc-600 dark:text-zinc-400">
            {c.sem_inep.map((s) => <li key={s.escola_id}>{s.nome}</li>)}
          </ul>
          <p className="text-[11px] text-zinc-500">
            Sem o código, a escola não casa com os arquivos oficiais. O código é cadastrado pelo administrador global,
            em Gestão de redes; depois, é preciso reimportar o arquivo oficial da edição.
          </p>
        </div>
      )}
      {c.fora_do_cadastro.length > 0 && (
        <div>
          <p className="text-xs font-medium text-zinc-600 dark:text-zinc-300">
            No arquivo oficial, sem escola com esse código no cadastro ({c.fora_do_cadastro.length}):
          </p>
          <ul className="list-disc pl-5 text-xs text-zinc-600 dark:text-zinc-400">
            {c.fora_do_cadastro.map((f) => (
              <li key={`${f.codigo_inep}-${f.cie}`}>
                INEP {f.codigo_inep ?? "—"} · CIE {f.cie ?? "—"}{f.nome_no_arquivo ? ` — “${f.nome_no_arquivo}”, como está no arquivo` : ""}
              </li>
            ))}
          </ul>
          <p className="text-[11px] text-zinc-500">
            O Constela casa as escolas só pelo código INEP, nunca pelo nome. Se uma delas for uma escola da rede sem código
            no cadastro, cadastre o código (Gestão de redes) e reimporte o arquivo oficial desta edição.
          </p>
        </div>
      )}
      <SeloFonte fontes={[c.fonte]} />
    </section>
  );
}

function ParteCobertura({ dados }: { dados: RespostaSARESP }) {
  if (dados.cobertura.length === 0) {
    return <p className="text-sm text-zinc-500">Sem arquivo oficial por escola importado: não há cobertura a mostrar.</p>;
  }
  return (
    <div className="space-y-3">
      {dados.cobertura.map((c) => <CoberturaDaEdicao key={c.edicao} c={c} />)}
    </div>
  );
}

// --- A aba ---------------------------------------------------------------------

const PARTES = [["rede", "Rede municipal"], ["escolas", "Por escola"], ["cobertura", "Cobertura"]] as const;
type Parte = (typeof PARTES)[number][0];

export default function AbaSARESP({ dados }: { dados: RespostaSARESP }) {
  const [parte, setParte] = useState<Parte>("rede");
  const idBase = useId();
  const idAba = (chave: string) => `${idBase}-aba-${chave}`;
  const idPainel = `${idBase}-painel`;
  return (
    <div className="space-y-4" data-testid="aba-saresp">
      <div role="tablist" aria-label="Partes do SARESP" className={classeTrilhoAbas}>
        {PARTES.map(([chave, rotulo]) => (
          <button key={chave} id={idAba(chave)} type="button" role="tab" aria-selected={parte === chave}
                  aria-controls={idPainel} onClick={() => setParte(chave)}
                  className={classeAba(parte === chave)}>
            {rotulo}
          </button>
        ))}
      </div>
      <div role="tabpanel" id={idPainel} aria-labelledby={idAba(parte)} className="space-y-4">
        {parte === "rede" && <ParteRede dados={dados} />}
        {parte === "escolas" && <ParteEscolas dados={dados} />}
        {parte === "cobertura" && <ParteCobertura dados={dados} />}
      </div>
    </div>
  );
}
