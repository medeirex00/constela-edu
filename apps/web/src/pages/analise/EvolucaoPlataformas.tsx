/**
 * Evolução das plataformas no ano letivo, por bimestre (`GET /redes/{id}/analise/plataformas/
 * evolucao`): para cada bimestre que já começou, a participação e a intensidade da REDE no
 * Elefante (livros novos e minutos por aluno) e no Matific (atividades por aluno), quantas
 * escolas entraram e quantas tinham a coleta parada.
 *
 * Responde UMA pergunta — "o uso está subindo ou caindo ao longo do ano?" — por isso o
 * gráfico é só o da participação (as duas plataformas na MESMA escala, %); as intensidades
 * têm unidades diferentes e ficam na tabela (pô-las no mesmo eixo seria comparar livros com
 * atividades). O bimestre EM ANDAMENTO aparece marcado: os números dele ainda crescem até o
 * fim — lê-lo como queda seria errado. Sem dado (sem coleta, grupo pequeno protegido) é
 * texto, nunca 0, e vira lacuna na linha do gráfico.
 *
 * Dois modos: o da REDE (a tela Elefante e Matific: o gráfico e a tabela da rede e, com uma
 * escola no filtro, a tabela dela embaixo) e o SÓ DA ESCOLA (`soEscola`, a ficha da escola da
 * Secretaria): o gráfico e a tabela da escola, sem a tabela da rede. Na ficha, a leitura é a mais
 * curta possível: a célula sem número diz só "sem dado" ou "protegido" e o porquê aparece UMA vez,
 * numa nota abaixo da tabela (motivos iguais juntos); a escola sem número em NENHUMA célula
 * (protegida, ou sem dado em todos os bimestres) vira uma frase só, com o motivo, no lugar da
 * tabela. O modo da rede não muda.
 */
import { CalendarRange } from "lucide-react";
import type { ReactNode } from "react";

import { GraficoLinha, useLarguraDoConteiner, type SerieLinha } from "../../components/Grafico";
import { TabelaRolavel } from "../../components/TabelaRolavel";
import { Badge, Card, Carregando, IconePastel, Mensagem } from "../../components/ui";
import { Recolhivel } from "./DetalhesFonte";
import { FiltrosAplicados, OPCOES_LEITURA_PESADA, TD, TH, TITULO_CARTAO, useApiExata } from "./comum";
import { coberturaDe, decimal, diaBR, rotuloCobertura, rotuloSerie, textoContagem } from "./formato";
import type { RespostaIndicadoresRede } from "./tipos";
import type { BimestreEvolucao, MotivoNoBimestre, RespostaEvolucao } from "./tiposDiagnostico";
import { textosDoFluxoPrincipal } from "../rede/secretaria/oQueMede";

const CINZA = "text-zinc-600 dark:text-zinc-400";
const COR_ELEFANTE = "#6C5CE7"; // leitura: violeta da marca (a mesma das outras telas)
const COR_MATIFIC = "#0D9488";  // matemática: teal
/** Abaixo disto o gráfico desenha na largura real (texto no tamanho nominal no celular). */
const LARGURA_CELULAR = 400;

const pct = (v: number | null | undefined) => (v == null ? null : `${decimal(v, 1)}%`);
const diaMes = (iso: string | null | undefined) => diaBR(iso)?.slice(0, 5) ?? null;
const eixoDo = (b: BimestreEvolucao) => `${b.numero}º bim.${b.em_andamento ? "*" : ""}`;
/**
 * O nome do bimestre SEM as datas: o backend manda "1º bimestre (02/02 a 22/04)", e a célula e
 * a nota já escrevem as datas (de `inicio`/`fim`) — com o rótulo inteiro, saíam duas vezes. Só
 * as datas do fim saem: "(aproximado: sem calendário oficial de 2027)" fica.
 */
const nomeDo = (b: BimestreEvolucao) => b.rotulo.replace(/\s*\(\d{2}\/\d{2} a \d{2}\/\d{2}\)\s*$/, "");

/** O porquê do "protegido" quando o serviço não manda o texto. */
const TEXTO_PROTEGIDO = "poucos alunos: os números não aparecem, para proteger as crianças";

/**
 * O número que falta, por extenso: "protegido" (grupo com menos de k alunos, ou a média
 * escondida em complemento) ou "sem dado" com o porquê — à vista na tabela da escola; na da
 * rede, na dica e no leitor de tela (a legenda explica). Nunca 0.
 */
function Falta({ campo, bloco, suprimido, motivo, visivel = false }: {
  campo: string;
  bloco?: MotivoNoBimestre | null;
  suprimido?: boolean;
  motivo?: string | null;
  visivel?: boolean;
}) {
  const protegido = Boolean(suprimido || bloco?.motivo_sem_dado === "suprimido"
    || (bloco?.metricas_protegidas ?? []).includes(campo));
  const porque = protegido
    ? bloco?.texto_sem_dado ?? TEXTO_PROTEGIDO
    : motivo ?? bloco?.texto_sem_dado ?? null;
  const texto = protegido ? "protegido" : visivel && porque ? `sem dado (${porque})` : "sem dado";
  return (
    <span className={`text-[11px] ${CINZA}`} title={porque ?? undefined}>
      {texto}
      {!visivel && porque && <span className="sr-only"> ({porque})</span>}
    </span>
  );
}

/**
 * O número da ESCOLA num bimestre com a coleta parada antes do fim: vale só até a parada —
 * livros e atividades por aluno saem menores e, ao lado do bimestre completo, pareceriam queda.
 * A marca fica à vista (texto, não só cor). A data só aparece se o serviço mandar `coberto_ate`.
 */
function ComColetaParcial({ texto, ate }: { texto: string; ate: string | null }) {
  return (
    <span className="flex flex-col gap-0.5">
      <span>{texto}</span>
      <span className="text-[11px] text-amber-800 dark:text-amber-300" data-coleta-parcial
            title="a coleta parou antes do fim do bimestre: o número vale só até a parada">
        coleta parcial{ate ? ` (até ${ate})` : ""}
      </span>
    </span>
  );
}

function CelulaBimestre({ b }: { b: BimestreEvolucao }) {
  const de = diaMes(b.inicio), ate = diaMes(b.fim);
  return (
    <span className="flex flex-col gap-0.5">
      <span className="flex flex-wrap items-center gap-1.5">
        <span>{nomeDo(b)}</span>
        {b.em_andamento && <Badge tom="alerta">em andamento</Badge>}
      </span>
      {de && ate && <span className={`text-[11px] font-normal ${CINZA}`}>{de} a {ate}</span>}
    </span>
  );
}

/** A participação de uma plataforma num bimestre (da rede, ou da escola no modo só da escola). */
type ParticipacaoNoBimestre = (b: BimestreEvolucao, p: "elefante" | "matific") => number | null;

const participacaoDaRede: ParticipacaoNoBimestre = (b, p) => b.rede?.[p]?.participacao_pct ?? null;

function GraficoParticipacao({ bimestres, comElefante, comMatific, onde = "na rede", participacao = participacaoDaRede }: {
  bimestres: BimestreEvolucao[]; comElefante: boolean; comMatific: boolean;
  /** "na rede" ou "na escola" (o título e o texto do gráfico). */
  onde?: string;
  participacao?: ParticipacaoNoBimestre;
}) {
  const { ref, largura } = useLarguraDoConteiner();
  const eixoX = bimestres.map(eixoDo);
  const series: SerieLinha[] = [
    ...(comElefante ? [{ nome: "Elefante — participação", cor: COR_ELEFANTE,
      pontos: bimestres.map((b) => ({ rotulo: eixoDo(b), valor: participacao(b, "elefante") })) }] : []),
    ...(comMatific ? [{ nome: "Matific — participação", cor: COR_MATIFIC,
      pontos: bimestres.map((b) => ({ rotulo: eixoDo(b), valor: participacao(b, "matific") })) }] : []),
  ];
  const andamento = bimestres.find((b) => b.em_andamento);
  const descricao = series.map((s) => `${s.nome}: ${s.pontos.map((p, i) =>
    `${bimestres[i].rotulo} ${p.valor == null ? "sem dado" : pct(p.valor)}`).join(", ")}`).join("; ");
  return (
    <figure className="space-y-1" data-testid="grafico-evolucao">
      <figcaption className="text-sm font-semibold text-zinc-800 dark:text-zinc-100">
        Participação {onde}, por bimestre
      </figcaption>
      <div ref={ref} className="max-w-2xl">
        <GraficoLinha series={series} eixoX={eixoX} minimo={0} maximo={100} altura={190}
                      formato={(v) => pct(v) ?? ""}
                      larguraViewBox={largura > 0 && largura < LARGURA_CELULAR ? largura : undefined}
                      rotulo={`Participação ${onde} por bimestre — ${descricao}${andamento
                        ? `. O ${andamento.rotulo} está em andamento: os números ainda crescem até o fim.` : ""}`} />
      </div>
      {andamento && (
        <p className={`text-xs ${CINZA}`} data-testid="nota-em-andamento">
          * {nomeDo(andamento)} em andamento{diaMes(andamento.fim) ? ` (até ${diaMes(andamento.fim)})` : ""}: os números
          ainda crescem até o fim do bimestre — não leia a diferença como queda.
        </p>
      )}
    </figure>
  );
}

/** Uma linha da tabela da escola: o bimestre e a escola nele (null = a escola não veio). */
interface EscolaNoBimestreDaTabela {
  b: BimestreEvolucao;
  e: BimestreEvolucao["escolas"][number] | null;
}

/** A participação da ESCOLA num bimestre — sem o bimestre de coleta parcial: o número dele vale
 *  só até a parada e, na linha, pareceria queda (a tabela mostra o número, com a marca). */
function participacaoDaEscola(escolaId: number): ParticipacaoNoBimestre {
  return (b, p) => {
    const e = b.escolas.find((x) => x.id === escolaId);
    const bloco = e?.[p];
    if (!bloco || bloco.coleta_parcial || coberturaDe(e?.cobertura, p) === "coleta_parcial") return null;
    return bloco.participacao_pct ?? null;
  };
}

type Plataforma = "elefante" | "matific";
const NOME_PLATAFORMA: Record<Plataforma, string> = { elefante: "Elefante", matific: "Matific" };

/** Uma coluna da tabela da escola: a plataforma, o campo do serviço e o número já escrito. */
interface ColunaDaEscola {
  p: Plataforma;
  campo: string;
  titulo: string;
  valor: (e: EscolaNoBimestreDaTabela["e"]) => string | null;
}
const COLUNAS_DA_ESCOLA: ColunaDaEscola[] = [
  { p: "elefante", campo: "participacao_pct", titulo: "Elefante: participação", valor: (e) => pct(e?.elefante?.participacao_pct) },
  { p: "elefante", campo: "livros_por_aluno", titulo: "Livros novos/aluno", valor: (e) => decimal(e?.elefante?.livros_por_aluno) },
  { p: "matific", campo: "participacao_pct", titulo: "Matific: participação", valor: (e) => pct(e?.matific?.participacao_pct) },
  { p: "matific", campo: "atividades_por_aluno", titulo: "Atividades/aluno", valor: (e) => decimal(e?.matific?.atividades_por_aluno) },
];
const colunasDaEscola = (comElefante: boolean, comMatific: boolean) =>
  COLUNAS_DA_ESCOLA.filter((c) => (c.p === "elefante" ? comElefante : comMatific));

/**
 * Na ficha, os motivos de falta que são PROTEÇÃO (poucos alunos) — os mesmos que a situação de uso
 * da ficha, lá em cima, chama de "Protegido (poucos alunos)" (`situacaoDeUso.ts`): a célula diz
 * "protegido", como a situação, e não "sem dado".
 */
const MOTIVOS_PROTEGIDOS_NA_FICHA = new Set(["suprimido", "poucos_alunos_medidos", "series_suprimidas"]);

/** A falta de UM número da escola na ficha: "protegido" ou "sem dado", e o porquê (quando há). */
interface FaltaDaEscola { protegido: boolean; porque: string | null }

function faltaDaEscola(e: EscolaNoBimestreDaTabela["e"], p: Plataforma, campo: string): FaltaDaEscola {
  const bloco = e?.[p];
  if (e?.suprimido || MOTIVOS_PROTEGIDOS_NA_FICHA.has(bloco?.motivo_sem_dado ?? "")
      || (bloco?.metricas_protegidas ?? []).includes(campo)) {
    return { protegido: true, porque: bloco?.texto_sem_dado ?? TEXTO_PROTEGIDO };
  }
  // Sem número: a situação da coleta (curta) quando não está em dia; senão o texto do serviço.
  const situacao = coberturaDe(e?.cobertura, p);
  return { protegido: false, porque: (situacao && situacao !== "ok" ? rotuloCobertura(situacao) : null)
    ?? bloco?.texto_sem_dado ?? null };
}

/** O valor de UMA célula da escola: o número (com a marca da coleta parcial) ou a falta. Na ficha
 *  (`curta`), a falta é só a palavra — o porquê fica na nota abaixo da tabela (e na dica). */
function ValorDaEscola({ e, c, curta }: { e: EscolaNoBimestreDaTabela["e"]; c: ColunaDaEscola; curta: boolean }) {
  const texto = c.valor(e);
  if (texto == null) {
    if (curta) {
      const f = faltaDaEscola(e, c.p, c.campo);
      return (
        <span className={`text-[11px] ${CINZA}`} title={f.porque ?? undefined} data-falta={f.protegido ? "protegido" : "sem-dado"}>
          {f.protegido ? "protegido" : "sem dado"}
        </span>
      );
    }
    // Sem número: a situação da coleta (curta) quando não está em dia; senão o
    // texto do serviço; a escola de poucos alunos é "protegido".
    const situacao = coberturaDe(e?.cobertura, c.p);
    const motivo = situacao && situacao !== "ok" ? rotuloCobertura(situacao) : e?.[c.p]?.texto_sem_dado ?? null;
    return <Falta campo={c.campo} bloco={e?.[c.p]} suprimido={e?.suprimido} motivo={motivo} visivel />;
  }
  // Com número e a coleta parada antes do fim do bimestre: o número leva a marca
  // (o serviço manda o número E `coleta_parcial`, sem motivo de falta).
  const parcial = Boolean(e?.[c.p]?.coleta_parcial) || coberturaDe(e?.cobertura, c.p) === "coleta_parcial";
  return parcial ? <ComColetaParcial texto={texto} ate={diaMes(e?.[c.p]?.coberto_ate)} /> : <>{texto}</>;
}

/** A tabela de UMA escola por bimestre: participação e intensidade, com o porquê de cada falta
 *  (na célula; na ficha, `curta`, numa nota abaixo). */
function TabelaDaEscola({ nome, linhas, colunas, curta = false }: {
  nome: string;
  linhas: EscolaNoBimestreDaTabela[];
  colunas: ColunaDaEscola[];
  curta?: boolean;
}) {
  return (
    <TabelaRolavel rotulo={`${nome} por bimestre: tabela completa`}>
      <table className="w-full text-xs" data-testid="tabela-evolucao-escola">
        <caption className="sr-only">{nome}: participação e intensidade por bimestre</caption>
        <thead>
          <tr className={`border-b border-zinc-200 align-bottom dark:border-zinc-800 ${CINZA}`}>
            <th className={TH} scope="col">Bimestre</th>
            {colunas.map((c) => <th key={`${c.p}-${c.campo}`} className={TH} scope="col">{c.titulo}</th>)}
          </tr>
        </thead>
        <tbody>
          {linhas.map(({ b, e }) => (
            <tr key={b.numero} className="border-b border-zinc-100 align-top last:border-0 dark:border-zinc-800/60">
              <th scope="row" className={`${TD} min-w-[8rem] text-left font-medium`}><CelulaBimestre b={b} /></th>
              {colunas.map((c) => (
                <td key={`${c.p}-${c.campo}`} className={TD}><ValorDaEscola e={e} c={c} curta={curta} /></td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </TabelaRolavel>
  );
}

/** Um motivo de falta da ficha e ONDE ele vale (plataforma → bimestres). */
interface GrupoDeFalta extends FaltaDaEscola { onde: Map<Plataforma, Set<number>> }

/**
 * As faltas da escola na ficha, juntas por motivo (o mesmo rótulo e o mesmo porquê = um grupo, na
 * ordem em que aparecem na tabela), e se ALGUMA célula tem número.
 */
function faltasDaFicha(linhas: EscolaNoBimestreDaTabela[], colunas: ColunaDaEscola[]) {
  let algumNumero = false;
  const grupos = new Map<string, GrupoDeFalta>();
  for (const { b, e } of linhas) {
    for (const c of colunas) {
      if (c.valor(e) != null) { algumNumero = true; continue; }
      const f = faltaDaEscola(e, c.p, c.campo);
      const chave = `${f.protegido ? "protegido" : "sem dado"}|${f.porque ?? ""}`;
      const grupo = grupos.get(chave) ?? { ...f, onde: new Map<Plataforma, Set<number>>() };
      grupos.set(chave, grupo);
      const bims = grupo.onde.get(c.p) ?? new Set<number>();
      grupo.onde.set(c.p, bims.add(b.numero));
    }
  }
  return { algumNumero, grupos: [...grupos.values()] };
}

/** "2º bimestre", "1º e 3º bimestres", "todos os bimestres" (de `total` bimestres na tabela). */
function textoBimestres(numeros: number[], total: number): string {
  if (total > 1 && numeros.length === total) return "todos os bimestres";
  const o = numeros.map((n) => `${n}º`);
  return o.length === 1 ? `${o[0]} bimestre` : `${o.slice(0, -1).join(", ")} e ${o[o.length - 1]} bimestres`;
}

/** "Elefante, 2º bimestre; Matific, todos os bimestres" — as plataformas com os mesmos bimestres
 *  juntas ("Elefante e Matific, 1º bimestre"). `semBimestresQuandoTodos`: só a plataforma quando o
 *  motivo vale em todos (a frase de cima já diz os bimestres). */
function textoOnde(onde: Map<Plataforma, Set<number>>, total: number, semBimestresQuandoTodos = false): string {
  const juntos = new Map<string, { plataformas: Plataforma[]; numeros: number[] }>();
  for (const p of ["elefante", "matific"] as const) {
    const bims = onde.get(p);
    if (!bims) continue;
    const numeros = [...bims].sort((a, b) => a - b);
    const chave = numeros.join(",");
    const grupo = juntos.get(chave) ?? { plataformas: [], numeros };
    grupo.plataformas.push(p);
    juntos.set(chave, grupo);
  }
  return [...juntos.values()].map(({ plataformas, numeros }) => {
    const quem = plataformas.map((p) => NOME_PLATAFORMA[p]).join(" e ");
    return semBimestresQuandoTodos && numeros.length === total ? quem : `${quem}, ${textoBimestres(numeros, total)}`;
  }).join("; ");
}

/** "protegido: poucos alunos…" / "sem dado: sem coleta no período" / "sem dado". */
const textoDaFalta = (g: FaltaDaEscola) => `${g.protegido ? "protegido" : "sem dado"}${g.porque ? `: ${g.porque}` : ""}`;

/**
 * A escola SEM número em nenhuma célula (protegida, ou sem dado em todos os bimestres e métricas):
 * uma frase só, com o motivo uma vez, no lugar da tabela. Motivos diferentes (ex.: o Elefante sem
 * coleta e o Matific protegido) viram uma lista curta, um por linha.
 */
function EscolaSemNumero({ grupos, bimestres, ano }: { grupos: GrupoDeFalta[]; bimestres: BimestreEvolucao[]; ano: number }) {
  const primeiro = bimestres[0].numero, ultimo = bimestres[bimestres.length - 1].numero;
  const quando = bimestres.length === 1 ? `no ${primeiro}º bimestre` : `do ${primeiro}º ao ${ultimo}º bimestre`;
  const frase = `Nenhum número desta escola ${quando} do ano letivo de ${ano}`;
  return grupos.length === 1 ? (
    <p className="text-sm text-zinc-700 dark:text-zinc-200" data-testid="evolucao-escola-sem-numero">
      {frase} — {textoDaFalta(grupos[0])}.
    </p>
  ) : (
    <div className="space-y-1 text-sm text-zinc-700 dark:text-zinc-200" data-testid="evolucao-escola-sem-numero">
      <p>{frase}:</p>
      <ul className="list-disc space-y-0.5 pl-5">
        {grupos.map((g) => (
          <li key={`${g.protegido}|${g.porque ?? ""}`}>
            {textoOnde(g.onde, bimestres.length, true)} — {textoDaFalta(g)}.
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Na ficha, abaixo da tabela: o porquê de cada falta UMA vez (motivos iguais juntos, com onde
 *  valem). As faltas sem porquê ficam só na célula ("sem dado") e na legenda. */
function MotivosDasFaltas({ grupos, total }: { grupos: GrupoDeFalta[]; total: number }) {
  const comPorque = grupos.filter((g) => g.porque);
  if (comPorque.length === 0) return null;
  const item = (g: GrupoDeFalta) => `${textoOnde(g.onde, total)} — ${textoDaFalta(g)}`;
  return (
    <div className={`space-y-0.5 text-xs ${CINZA}`} data-testid="motivos-evolucao-escola">
      {comPorque.length === 1 ? (
        <p>Por que falta número: {item(comPorque[0])}.</p>
      ) : (
        <>
          <p>Por que faltam números:</p>
          <ul className="list-disc space-y-0.5 pl-4">
            {comPorque.map((g) => <li key={`${g.protegido}|${g.porque}`}>{item(g)}.</li>)}
          </ul>
        </>
      )}
    </div>
  );
}

export default function EvolucaoPlataformas({
  redeId, base, serie, escolaId, modulos, recorte, jaExplicadas, soEscola = false, nomeEscola,
}: {
  redeId: number;
  /** As limitações que a tela já mostra em outro lugar ("Sobre os dados" da tela Elefante e
   *  Matific: as mesmas do uso no período, que o serviço repete aqui) — saem desta lista, que
   *  fica só com as da evolução por bimestre (sem a mesma frase duas vezes na página). */
  jaExplicadas?: readonly string[] | null;
  /** Os campos que escolhem a série e a escola DESTA evolução (a tela Elefante e Matific não
   *  tem filtros no topo): ficam sob o título, antes da linha "Vale aqui". */
  recorte?: ReactNode;
  /** O catálogo (o nome da escola do filtro). A tela Elefante e Matific mostra só a rede e
   *  monta a evolução sem esperar o catálogo. */
  base?: RespostaIndicadoresRede | null;
  serie: number | null;
  escolaId: number | null;
  /** Os módulos contratados (da leitura das plataformas, quando já chegou): esconde a coluna
   *  do que a rede não tem; sem eles, as duas aparecem (com "sem dado"). */
  modulos?: { elefante: boolean; matific: boolean };
  /** SÓ A ESCOLA (a ficha da escola): o gráfico e a tabela da escola de `escolaId`, sem a tabela
   *  nem o gráfico da rede. Quem chama já confirmou que a escola é da rede. */
  soEscola?: boolean;
  /** O nome da escola no modo só da escola (a ficha já o tem; sem ele, o do catálogo). */
  nomeEscola?: string | null;
}) {
  const q = new URLSearchParams();
  if (serie != null) q.set("serie", String(serie));
  if (escolaId != null) q.set("escola_id", String(escolaId));
  // Na ficha, só a escola: o servidor não mede a rede inteira (a supressão continua a da rede,
  // então os números dela são os mesmos da evolução da rede).
  if (soEscola && escolaId != null) q.set("so_escola", "true");
  const url = `/redes/${redeId}/analise/plataformas/evolucao${q.toString() ? `?${q.toString()}` : ""}`;
  // O servidor mede as plataformas uma vez POR BIMESTRE já começado (4 medições no fim do ano):
  // 60 s, sem repetir sozinho e com cache curto (ver OPCOES_LEITURA_PESADA).
  const { dados, erro } = useApiExata<RespostaEvolucao>(url, OPCOES_LEITURA_PESADA);
  // Os módulos da própria evolução (o backend manda); sem eles, os da leitura das plataformas.
  const mods = dados?.modulos ?? modulos;
  const comElefante = mods?.elefante ?? true;
  const comMatific = mods?.matific ?? true;
  const doCatalogo = escolaId != null ? base?.escolas.find((e) => e.id === escolaId) ?? null : null;
  const escola = soEscola && escolaId != null
    ? { id: escolaId, nome: nomeEscola ?? doCatalogo?.nome ?? "a escola" }
    : doCatalogo;
  const bimestres = [...(dados?.bimestres ?? [])].sort((a, b) => a.numero - b.numero);
  const daEscola: EscolaNoBimestreDaTabela[] = escola
    ? bimestres.map((b) => ({ b, e: b.escolas.find((x) => x.id === escola.id) ?? null }))
    : [];
  const temValor = bimestres.some((b) => b.rede?.elefante?.participacao_pct != null || b.rede?.matific?.participacao_pct != null);
  const participacaoEscola = escola ? participacaoDaEscola(escola.id) : null;
  const temValorEscola = participacaoEscola != null
    && bimestres.some((b) => participacaoEscola(b, "elefante") != null || participacaoEscola(b, "matific") != null);
  // Bimestre com número na tabela mas fora do gráfico da escola (coleta parcial): a nota diz.
  const parcialForaDoGrafico = daEscola.some(({ e }) => (["elefante", "matific"] as const).some((p) =>
    e?.[p]?.participacao_pct != null && (Boolean(e[p]?.coleta_parcial) || coberturaDe(e.cobertura, p) === "coleta_parcial")));
  const colunas = colunasDaEscola(comElefante, comMatific);
  // Na ficha: as faltas juntas por motivo (a nota abaixo da tabela) e se a escola tem ALGUM número
  // (sem nenhum, a frase só no lugar da tabela).
  const ficha = soEscola ? faltasDaFicha(daEscola, colunas) : null;
  // A evolução mora no fluxo principal (a tela Elefante e Matific, a ficha da escola): as
  // limitações em língua simples, sem as frases da relação estatística, e sem repetir as que
  // "Sobre os dados" já traz.
  const limitacoes = textosDoFluxoPrincipal((dados?.limitacoes ?? []).filter((t) => !jaExplicadas?.includes(t)));
  const serieTexto = serie != null ? rotuloSerie(serie) : "1º ao 5º ano";
  const comoLer = limitacoes.length > 0 && (
    <Recolhivel titulo="Como ler a evolução (limitações)" testId="limitacoes-evolucao">
      <ul className="list-disc space-y-1 pl-4">{limitacoes.map((t) => <li key={t}>{t}</li>)}</ul>
    </Recolhivel>
  );

  return (
    <Card className="space-y-4 p-6">
      <h2 className={`${TITULO_CARTAO} flex-wrap`}>
        <IconePastel icone={CalendarRange} tom="azul" tamanho="sm" /> Evolução no ano letivo, por bimestre
      </h2>
      {recorte}
      <FiltrosAplicados testId="filtros-evolucao">
        {soEscola ? `Vale aqui: a escola e a série (${serieTexto}).` : `Vale aqui: série (${serieTexto}).`} O período
        não se aplica: cada ponto é um bimestre do ano letivo{dados ? ` ${dados.ano_letivo}` : ""}.
        {!soEscola && escola ? ` A escola do filtro (${escola.nome}) aparece numa tabela própria, abaixo da rede.` : ""}
      </FiltrosAplicados>
      {erro && !dados ? (
        <Mensagem tipo="erro">Não foi possível carregar a evolução por bimestre: {erro.message}</Mensagem>
      ) : !dados ? (
        <Carregando texto="Carregando a evolução por bimestre..." />
      ) : bimestres.length === 0 ? (
        <p className={`text-sm ${CINZA}`} data-testid="evolucao-vazia">
          Nenhum bimestre do ano letivo começou ainda: não há evolução para mostrar.
        </p>
      ) : soEscola && escola && participacaoEscola && ficha && !ficha.algumNumero && ficha.grupos.length > 0 ? (
        // Nenhum número em nenhuma célula: a frase (com o motivo, uma vez) no lugar da tabela inteira
        // repetindo a mesma frase longa em cada célula.
        <>
          <div data-testid="evolucao-escola">
            <EscolaSemNumero grupos={ficha.grupos} bimestres={bimestres} ano={dados.ano_letivo} />
          </div>
          {comoLer}
        </>
      ) : soEscola && escola && participacaoEscola ? (
        <>
          {bimestres.length >= 2 && temValorEscola && (comElefante || comMatific) && (
            <GraficoParticipacao bimestres={bimestres} comElefante={comElefante} comMatific={comMatific}
                                 onde="na escola" participacao={participacaoEscola} />
          )}
          <div className="space-y-2" data-testid="evolucao-escola">
            <TabelaDaEscola nome={escola.nome} linhas={daEscola} colunas={colunas} curta />
            {ficha && <MotivosDasFaltas grupos={ficha.grupos} total={daEscola.length} />}
          </div>
          <p className={`text-xs ${CINZA}`} data-testid="legenda-evolucao">
            Cada bimestre tem a sua janela (participação e médias por aluno sobre os alunos que a plataforma conhece
            naquele bimestre). “Sem dado” e “protegido” não são zero (protegido: grupo com menos de{" "}
            {dados.k_minimo} alunos, para proteger as crianças). O número marcado “coleta parcial” vale só até a parada
            da coleta: não o leia como queda.
            {parcialForaDoGrafico ? " No gráfico, o bimestre com a coleta parcial fica de fora (o número está na tabela)." : ""}
          </p>
          {comoLer}
        </>
      ) : (
        <>
          {bimestres.length >= 2 && temValor && (comElefante || comMatific) && (
            <GraficoParticipacao bimestres={bimestres} comElefante={comElefante} comMatific={comMatific} />
          )}
          <TabelaRolavel rotulo="Evolução da rede por bimestre: tabela completa">
            <table className="w-full text-xs" data-testid="tabela-evolucao-rede">
              <caption className="sr-only">
                Rede municipal por bimestre: participação e intensidade de cada plataforma e as escolas com dado
              </caption>
              <thead>
                <tr className={`border-b border-zinc-200 align-bottom dark:border-zinc-800 ${CINZA}`}>
                  <th className={TH} scope="col">Bimestre</th>
                  {comElefante && <>
                    <th className={TH} scope="col">Elefante: participação</th>
                    <th className={TH} scope="col">Livros novos/aluno</th>
                    <th className={TH} scope="col">Min/aluno</th>
                  </>}
                  {comMatific && <>
                    <th className={TH} scope="col">Matific: participação</th>
                    <th className={TH} scope="col">Atividades/aluno</th>
                  </>}
                  <th className={TH} scope="col">Escolas com dado</th>
                  <th className={TH} scope="col">Coleta parcial</th>
                </tr>
              </thead>
              <tbody>
                {bimestres.map((b) => {
                  if (!b.rede) return null;                 // só a escola: a rede não foi medida
                  const { elefante: el, matific: ma, suprimido } = b.rede;
                  const falta = (campo: string, bloco: MotivoNoBimestre | null) =>
                    <Falta campo={campo} bloco={bloco} suprimido={suprimido} />;
                  return (
                    <tr key={b.numero} className="border-b border-zinc-100 align-top last:border-0 dark:border-zinc-800/60"
                        data-em-andamento={b.em_andamento || undefined}>
                      <th scope="row" className={`${TD} min-w-[8rem] text-left font-medium`}><CelulaBimestre b={b} /></th>
                      {comElefante && <>
                        <td className={TD}>{pct(el?.participacao_pct) ?? falta("participacao_pct", el)}</td>
                        <td className={TD}>{decimal(el?.livros_por_aluno) ?? falta("livros_por_aluno", el)}</td>
                        <td className={TD}>{decimal(el?.minutos_por_aluno, 1) ?? falta("minutos_por_aluno", el)}</td>
                      </>}
                      {comMatific && <>
                        <td className={TD}>{pct(ma?.participacao_pct) ?? falta("participacao_pct", ma)}</td>
                        <td className={TD}>{decimal(ma?.atividades_por_aluno) ?? falta("atividades_por_aluno", ma)}</td>
                      </>}
                      {/* Rede protegida: o serviço manda a contagem 0 (não null) — escrever "Elefante 0"
                          seria um zero falso (várias escolas têm dado). */}
                      <td className={TD}>
                        {suprimido ? falta("escolas", null) : textoContagem(b.rede.escolas_com_dado) ?? <Falta campo="escolas" />}
                      </td>
                      <td className={TD}>{textoContagem(b.rede.escolas_parciais) ?? "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </TabelaRolavel>

          {escola && (
            <div className="space-y-2" data-testid="evolucao-escola">
              <h3 className="break-words text-[15px] font-semibold text-zinc-900 dark:text-white">{escola.nome}, por bimestre</h3>
              <TabelaDaEscola nome={escola.nome} linhas={daEscola} colunas={colunas} />
            </div>
          )}

          <p className={`text-xs ${CINZA}`} data-testid="legenda-evolucao">
            Cada bimestre tem a sua janela (participação e médias por aluno sobre os alunos que a plataforma conhece
            naquele bimestre). “Sem dado” não é zero: inclui escola sem coleta no bimestre e grupo com menos de{" "}
            {dados.k_minimo} alunos, protegido. Escola com a coleta parada antes do fim do bimestre fica fora da soma da
            rede, salvo se cobrir ao menos 90% dele.
            {escola ? " Na tabela da escola, o número marcado “coleta parcial” vale só até a parada da coleta: não o leia como queda." : ""}
          </p>
          {comoLer}
        </>
      )}
    </Card>
  );
}
