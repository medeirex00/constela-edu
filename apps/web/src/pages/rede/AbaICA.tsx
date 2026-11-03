/**
 * Aba ICA dos indicadores oficiais (plano, 5.1) — o que a Secretaria e o admin
 * global leem além do resumo do cartão:
 *
 *  - a série do ICA (2023 em diante) em linha, com a META da rede tracejada até
 *    2030 e as comparações, cada uma com a SUA rede no nome: SP e Brasil na rede
 *    pública (estadual + municipal), que é como o INEP divulga o ICA — NÃO é a
 *    mesma rede do município —, e SP só nas redes municipais (microdados), a
 *    comparação na mesma rede; eixo por ano, lacuna quando não há resultado (nem
 *    ponto: um ano sem resultado não vira uma reta entre os vizinhos);
 *  - a comparação do último ano em barras, em ORDEM FIXA (nunca por valor);
 *  - a distribuição por nível de LP (0 a 8) em barra empilhada (desde 2024);
 *  - a média de LP contra o corte de 743 pontos;
 *  - participação (regra dos 70%) e nível oficial do município;
 *  - as notas dos próprios arquivos e a variação entre os dois últimos anos, sem
 *    interpretação causal;
 *  - logo abaixo da comparação de 2025 com SP ou RS, a observação do INEP sobre a
 *    tabela de itens dos microdados (texto aprovado em `notaInepItens.ts`) — num
 *    bloco próprio, fora da lista de notas "como publicadas" dos arquivos.
 *
 * Cada bloco tem o selo de fonte (e cada número da tabela, a sua data). "Sem
 * resultado" nunca vira 0; o ICA é da REDE e nada aqui ordena escolas.
 */
import type { ReactNode } from "react";

import { BarraEmpilhada, GraficoLinha, type SerieLinha } from "../../components/Grafico";
import SeloFonte, { SeloNumero, textoDetalhe } from "../../components/SeloFonte";
import {
  MOTIVOS,
  nomeComRede,
  numeroBR,
  percentual,
  type FonteICA,
  type NumeroICA,
  type RespostaICA,
  type TerritorioICA,
} from "./ica";
import { NOTA_INEP_ITENS, notaInepItensSeAplica } from "./notaInepItens";

// Paleta de séries da v2 (>= 3:1 sobre o branco e sobre o fundo escuro): o município no
// violeta da marca, a meta em ardósia TRACEJADA, a UF pública em teal, a UF nas redes
// municipais em âmbar e o Brasil em vermelho. A legenda e a tabela dizem o nome.
const COR = { municipio: "#6C5CE7", meta: "#64748B", ufPublica: "#0D9488", ufMunicipal: "#D97706", brasil: "#DC2626" };

function fontesDe(numeros: (NumeroICA | null | undefined)[]): (FonteICA | null)[] {
  return numeros.flatMap((n) => (n ? [n.fonte, n.detalhe?.fonte ?? null] : []));
}

function serie(nome: string, numeros: NumeroICA[], cor: string, tracejada = false): SerieLinha {
  return { nome, cor, tracejada, pontos: numeros.map((n) => ({ rotulo: String(n.edicao), valor: n.valor })) };
}

/** Faixa do eixo Y em dezenas, com folga — não começa em 0 quando a série é alta. */
function faixaDoEixo(valores: number[]): { minimo: number; maximo: number } {
  const lo = Math.min(...valores);
  const hi = Math.max(...valores);
  return {
    minimo: Math.max(0, Math.floor((lo - 5) / 10) * 10),
    maximo: Math.min(100, Math.ceil((hi + 5) / 10) * 10),
  };
}

const formatoPct = (v: number) => `${v.toLocaleString("pt-BR", { maximumFractionDigits: 2 })}%`;
// Os níveis vêm todos dos microdados, com 2 casas publicadas: 11,20 continua 11,20.
const formatoNivel = (v: number) => `${numeroBR(v, 2)}%`;

function Bloco({ titulo, children }: { titulo: string; children: ReactNode }) {
  return (
    <section className="space-y-2" aria-label={titulo}>
      <h3 className="text-sm font-semibold text-zinc-800 dark:text-zinc-100">{titulo}</h3>
      {children}
    </section>
  );
}

/** As casas de outro arquivo com a origem: "30,20% — detalhe dos microdados de
 *  10/03/2026". Planilha sem data interna: o nome do arquivo; sem fonte, só o número
 *  (nunca um travessão solto). */
function textoDoDetalhe(d: NonNullable<NumeroICA["detalhe"]>, sufixo = ""): string {
  const origem = textoDetalhe(d.fonte) || (d.fonte ? `no arquivo ${d.fonte.arquivo_nome}` : "");
  return `${numeroBR(d.valor, d.casas_decimais)}${sufixo}${origem ? ` — ${origem}` : ""}`;
}

function Valor({ n, sufixo = "" }: { n: NumeroICA | undefined; sufixo?: string }) {
  if (!n) return <span className="text-zinc-400">—</span>;
  if (n.valor == null) {
    return <span className="text-xs text-zinc-500">{MOTIVOS[n.motivo_ausencia ?? ""] ?? "sem resultado"}</span>;
  }
  return (
    <>
      <span className="font-medium tabular-nums">{numeroBR(n.valor, n.casas_decimais)}{sufixo}</span>
      {n.detalhe ? (
        <span className="block text-[11px] text-zinc-500">{textoDoDetalhe(n.detalhe, sufixo)}</span>
      ) : (
        <SeloNumero fonte={n.fonte} />
      )}
    </>
  );
}

function SerieEMeta({ mun, uf, ufm, br }: {
  mun: TerritorioICA; uf?: TerritorioICA; ufm?: TerritorioICA | null; br?: TerritorioICA;
}) {
  const series = [
    serie(nomeComRede(mun), mun.resultados, COR.municipio),
    serie(`Meta de ${mun.nome}`, mun.metas, COR.meta, true),
    ...(uf?.tem_dados ? [serie(nomeComRede(uf), uf.resultados, COR.ufPublica)] : []),
    ...(ufm?.tem_dados ? [serie(`${nomeComRede(ufm)} — microdados`, ufm.resultados, COR.ufMunicipal)] : []),
    ...(br?.tem_dados ? [serie(nomeComRede(br), br.resultados, COR.brasil)] : []),
  ];
  const valores = series.flatMap((s) => s.pontos.flatMap((p) => (p.valor == null ? [] : [p.valor])));
  // O texto alternativo diz a rede de CADA comparação (não "a mesma rede").
  const comparacoes = series.slice(2).map((s) => s.nome.replace(/ — microdados$/, ""));
  const anos = series.flatMap((s) => s.pontos.map((p) => Number(p.rotulo)));
  if (valores.length === 0 || anos.length === 0) {
    return <p className="text-sm text-zinc-500">Sem resultado importado para a série.</p>;
  }
  const eixoX: string[] = [];
  for (let a = Math.min(...anos); a <= Math.max(...anos); a += 1) eixoX.push(String(a));
  const { minimo, maximo } = faixaDoEixo(valores);
  return (
    <>
      {/* Largura contida: o SVG escala com o container, e numa tela larga as letras
          do eixo ficariam enormes. */}
      <div className="max-w-2xl">
        <GraficoLinha
          series={series} eixoX={eixoX} minimo={minimo} maximo={maximo} altura={220}
          formato={formatoPct}
          rotulo={`ICA de ${mun.nome} (rede municipal) por ano, com a meta tracejada${
            comparacoes.length > 0 ? ` e as comparações: ${comparacoes.join(", ")}` : ""}`}
          tabela="Números do gráfico: ICA e meta por ano"
        />
      </div>
      {minimo > 0 && (
        <p className="text-[11px] text-zinc-500">
          O eixo vertical vai de {minimo}% a {maximo}% (não começa em 0), para a variação ficar legível.
        </p>
      )}
      <SeloFonte titulo="Fontes da série" testId="selo-serie"
                 fontes={fontesDe([...mun.resultados, ...mun.metas, ...(uf?.resultados ?? []),
                                   ...(ufm?.resultados ?? []), ...(br?.resultados ?? [])])} />
    </>
  );
}

/** Comparação do último ano do município, em ORDEM FIXA (município, SP, Brasil). */
function Comparacao({ ano, territorios }: { ano: number; territorios: TerritorioICA[] }) {
  const linhas = territorios.map((t) => ({ t, n: t.resultados.find((r) => r.edicao === ano) }));
  return (
    <>
      <ul className="max-w-2xl space-y-2" aria-label={`ICA em ${ano}, na ordem fixa: município, estado e Brasil`}>
        {linhas.map(({ t, n }) => (
          <li key={`${t.abrangencia}-${t.rede_ensino}`} className="text-xs">
            <div className="flex items-center gap-2">
              <span className="w-32 shrink-0 truncate text-zinc-600 dark:text-zinc-300 sm:w-48" title={nomeComRede(t)}>
                {nomeComRede(t)}
              </span>
              {n?.valor != null ? (
                <>
                  <div className="h-4 flex-1 overflow-hidden rounded bg-zinc-100 dark:bg-zinc-800" aria-hidden="true">
                    <div className="h-full rounded bg-indigo-500" style={{ width: `${n.valor}%` }} />
                  </div>
                  <span className="w-14 text-right font-medium tabular-nums">{percentual(n)}</span>
                </>
              ) : (
                <span className="text-zinc-500">
                  {n ? (MOTIVOS[n.motivo_ausencia ?? ""] ?? "sem resultado") : "sem resultado importado"}
                </span>
              )}
            </div>
            {n?.valor != null && (
              <p className="pl-[8.5rem] text-[11px] text-zinc-500 sm:pl-[12.5rem]">
                {n.detalhe ? textoDoDetalhe(n.detalhe, "%") : <SeloNumero fonte={n.fonte} />}
              </p>
            )}
          </li>
        ))}
      </ul>
      <p className="text-[11px] text-zinc-500">A barra vai de 0 a 100%. A ordem é fixa — não é ranking.</p>
      <SeloFonte titulo={`Fontes da comparação de ${ano}`} fontes={fontesDe(linhas.map((l) => l.n))} />
    </>
  );
}

function Niveis({ mun, ufm }: { mun: TerritorioICA; ufm?: TerritorioICA | null }) {
  const barras = [mun, ...(ufm ? [ufm] : [])].flatMap((t) =>
    (t.distribuicao_niveis ?? []).map((d) => ({
      rotulo: `${nomeComRede(t)} — ${d.edicao}`,
      segmentos: d.niveis.map((n) => ({ nome: `Nível ${n.nivel}`, valor: n.valor })),
    })));
  const numeros = [mun, ...(ufm ? [ufm] : [])].flatMap((t) =>
    (t.distribuicao_niveis ?? []).flatMap((d) => d.niveis));
  if (barras.length === 0) {
    return (
      <p className="text-sm text-zinc-500">
        Sem distribuição por nível importada. Ela vem dos microdados do INEP (desde 2024; o arquivo de 2023 não traz).
      </p>
    );
  }
  return (
    <>
      <div className="max-w-2xl">
        <BarraEmpilhada barras={barras} formato={formatoNivel}
                        rotulo="Percentual de alunos em cada nível de Língua Portuguesa (0 a 8), por ano" />
      </div>
      <p className="text-[11px] text-zinc-500">
        Níveis 0 a 8 da escala de Língua Portuguesa do 2º ano. Cada barra soma cerca de 100% (arredondamento do INEP).
      </p>
      <SeloFonte titulo="Fontes dos níveis" testId="selo-niveis" fontes={fontesDe(numeros)} />
    </>
  );
}

function Variacao({ mun }: { mun: TerritorioICA }) {
  const com = mun.resultados.filter((r) => r.valor != null);
  if (com.length < 2) return null;
  const [a, b] = com.slice(-2);
  const nivel0 = (ano: number) =>
    mun.distribuicao_niveis?.find((d) => d.edicao === ano)?.niveis.find((n) => n.nivel === "0");
  const n0a = nivel0(a.edicao);
  const n0b = nivel0(b.edicao);
  return (
    <p className="rounded-lg bg-zinc-50 p-2.5 text-xs text-zinc-600 dark:bg-zinc-800/50 dark:text-zinc-300"
       data-testid="ica-variacao">
      De {a.edicao} para {b.edicao}, o ICA de {mun.nome} foi de {percentual(a)} para {percentual(b)}
      {n0a?.valor != null && n0b?.valor != null
        ? `, e o percentual de alunos no nível 0 foi de ${numeroBR(n0a.valor, n0a.casas_decimais)}% para ${numeroBR(n0b.valor, n0b.casas_decimais)}%`
        : ""}
      . Os números descrevem a variação; não indicam a causa dela.
    </p>
  );
}

function Medias({ territorios, corte }: { territorios: TerritorioICA[]; corte: number }) {
  const anos = [...new Set(territorios.flatMap((t) => (t.media_lp ?? []).map((m) => m.edicao)))]
    .sort((x, y) => x - y);
  if (anos.length === 0) {
    return <p className="text-sm text-zinc-500">Sem média de LP importada (vem dos microdados do INEP).</p>;
  }
  const mun = territorios[0];
  const ultima = [...(mun.media_lp ?? [])].reverse().find((m) => m.valor != null);
  const distancia = ultima?.valor != null ? Math.round((ultima.valor - corte) * 100) / 100 : null;
  return (
    <>
      <table className="w-full text-sm">
        <caption className="sr-only">Média de Língua Portuguesa por ano, na escala do Saeb</caption>
        <thead>
          <tr className="text-left text-xs text-zinc-500">
            <th className="py-1 pr-3 font-medium">Território</th>
            {anos.map((a) => <th key={a} className="py-1 pr-3 font-medium">{a}</th>)}
          </tr>
        </thead>
        <tbody>
          {territorios.map((t) => {
            const porAno = new Map((t.media_lp ?? []).map((m) => [m.edicao, m]));
            return (
              <tr key={`${t.abrangencia}-${t.rede_ensino}`} className="border-t border-zinc-100 align-top dark:border-zinc-800">
                <th scope="row" className="py-1.5 pr-3 text-left font-normal">{nomeComRede(t)}</th>
                {anos.map((a) => <td key={a} className="py-1.5 pr-3"><Valor n={porAno.get(a)} /></td>)}
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="text-[11px] text-zinc-500" data-testid="ica-corte">
        Corte do ICA: {corte} pontos na escala do Saeb — é alfabetizado o aluno com {corte} ou mais.
        {ultima?.valor != null && distancia != null
          ? ` A média de ${mun.nome} em ${ultima.edicao} (${numeroBR(ultima.valor, ultima.casas_decimais)}) está ${numeroBR(Math.abs(distancia), 2)} ponto(s) ${distancia < 0 ? "abaixo" : distancia > 0 ? "acima" : "em cima"} do corte.`
          : ""}
        {" "}A média é da rede inteira: não diz quantos alunos passaram do corte.
      </p>
      <SeloFonte titulo="Fontes das médias" fontes={fontesDe(territorios.flatMap((t) => t.media_lp ?? []))} />
    </>
  );
}

function ParticipacaoENivel({ mun, legenda }: { mun: TerritorioICA; legenda: RespostaICA["legenda_nivel"] }) {
  if (mun.participacao.length === 0 && mun.nivel.length === 0) return null;
  return (
    <>
      <ul className="space-y-1 text-xs text-zinc-600 dark:text-zinc-300">
        {mun.participacao.map((p) => (
          <li key={`p${p.edicao}`}>
            Participação em {p.edicao}:{" "}
            {p.valor == null ? (MOTIVOS[p.motivo_ausencia ?? ""] ?? "sem resultado") : (
              <span className="font-medium tabular-nums">{percentual(p)}</span>
            )}
          </li>
        ))}
        {mun.nivel.map((n) => {
          const faixa = legenda.find((l) => l.nivel === n.valor);
          return (
            <li key={`n${n.edicao}`}>
              Nível oficial do município em {n.edicao}:{" "}
              {n.valor == null ? (MOTIVOS[n.motivo_ausencia ?? ""] ?? "sem nível oficial")
                : `${n.valor}${faixa ? ` (${faixa.faixa} de alfabetizados)` : ""}`}
            </li>
          );
        })}
      </ul>
      <p className="text-[11px] text-zinc-500">
        Com participação abaixo de 70%, o INEP não divulga o resultado do município. O nível é o campo oficial do
        INEP — o Constela não o calcula.
      </p>
      <SeloFonte titulo="Fontes da participação e do nível" fontes={fontesDe([...mun.participacao, ...mun.nivel])} />
    </>
  );
}

/** A observação do INEP sobre a tabela de itens (texto aprovado, sem mudar uma
 *  palavra). Informativa: não é aviso de erro nem diz que o número mudou. */
function NotaInepItens() {
  const nota = NOTA_INEP_ITENS;
  return (
    <aside aria-label="Observação do INEP sobre os microdados"
           className="max-w-2xl space-y-1.5 rounded-lg border border-zinc-200 bg-zinc-50 p-3 text-xs text-zinc-600 dark:border-zinc-800 dark:bg-zinc-800/50 dark:text-zinc-300"
           data-testid="ica-nota-inep-itens">
      <p className="font-semibold text-zinc-800 dark:text-zinc-100" data-testid="ica-nota-inep-itens-titulo">
        {nota.titulo}
      </p>
      <p data-testid="ica-nota-inep-itens-texto">{nota.texto}</p>
      <p>
        <a href={nota.link.href} target="_blank" rel="noopener noreferrer"
           className="font-medium text-indigo-600 underline underline-offset-2 hover:text-indigo-700 dark:text-indigo-400 dark:hover:text-indigo-300">
          {nota.link.rotulo}
          <span className="sr-only"> (abre em nova aba)</span>
        </a>
      </p>
    </aside>
  );
}

function Notas({ fontes }: { fontes: FonteICA[] }) {
  const notas = fontes.flatMap((f) => (f.notas ?? []).map((nota) => ({ nota, arquivo: f.arquivo_nome })));
  const unicas = notas.filter((n, i) => notas.findIndex((m) => m.nota === n.nota) === i);
  if (unicas.length === 0) return null;
  return (
    <ul className="list-disc space-y-1 pl-5 text-xs text-zinc-600 dark:text-zinc-400" data-testid="ica-notas">
      {unicas.map((n) => (
        <li key={n.nota}>{n.nota} <span className="text-zinc-400">({n.arquivo})</span></li>
      ))}
    </ul>
  );
}

export default function AbaICA({ dados }: { dados: RespostaICA }) {
  const mun = dados.territorios.find((t) => t.abrangencia === "municipio");
  const uf = dados.territorios.find((t) => t.abrangencia === "uf");
  const br = dados.territorios.find((t) => t.abrangencia === "brasil");
  const ufm = dados.uf_municipal?.tem_dados ? dados.uf_municipal : null;
  if (!mun) return null;
  const anoComparacao = mun.destaque?.resultado.edicao;
  const comparados = [mun, ...(uf ? [uf] : []), ...(ufm ? [ufm] : []), ...(br ? [br] : [])];
  return (
    <div className="space-y-6" data-testid="aba-ica">
      <p className="text-xs text-zinc-500" data-testid="ica-aviso-redes">
        Indicador da REDE municipal (o INEP não publica por escola). SP e Brasil aparecem na rede pública (estadual e
        municipal), que é como o INEP divulga o ICA — essa não é a mesma rede do município. A comparação na mesma rede
        é “São Paulo (redes municipais)”, que vem dos microdados.
      </p>
      <Bloco titulo="Série do ICA e meta da rede">
        <SerieEMeta mun={mun} uf={uf} ufm={ufm} br={br} />
      </Bloco>
      {anoComparacao != null && (
        <Bloco titulo={`Comparação em ${anoComparacao}`}>
          <Comparacao ano={anoComparacao} territorios={comparados} />
        </Bloco>
      )}
      {/* A regra olha a UF da rede pública E a das redes municipais (as duas estão em
          `comparados`); fora da lista de notas "como publicadas". */}
      {notaInepItensSeAplica(anoComparacao, comparados) && <NotaInepItens />}
      <Bloco titulo="Distribuição por nível de Língua Portuguesa">
        <Niveis mun={mun} ufm={ufm} />
        <Variacao mun={mun} />
      </Bloco>
      <Bloco titulo="Média de Língua Portuguesa">
        <Medias territorios={[mun, ...(ufm ? [ufm] : []), ...(uf ? [uf] : [])]}
                corte={dados.corte_alfabetizado ?? 743} />
      </Bloco>
      {(mun.participacao.length > 0 || mun.nivel.length > 0) && (
        <Bloco titulo="Participação e nível oficial">
          <ParticipacaoENivel mun={mun} legenda={dados.legenda_nivel} />
        </Bloco>
      )}
      {dados.fontes.some((f) => (f.notas ?? []).length > 0) && (
        <Bloco titulo="Notas dos arquivos oficiais (como publicadas)">
          <Notas fontes={dados.fontes} />
        </Bloco>
      )}
    </div>
  );
}
