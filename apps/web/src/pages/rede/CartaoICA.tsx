/**
 * Cartão do Indicador Criança Alfabetizada (ICA) OFICIAL do INEP — etapa E2 dos
 * indicadores oficiais (plano, seção 5.1). Vive fora de `RedeAvaliacoes.tsx` (que
 * só o liga por uma linha) para não conflitar com o trabalho paralelo daquela tela.
 *
 * O que o cartão garante:
 *  - é o número da REDE municipal — o INEP não publica ICA por escola (o aviso
 *    aparece SEMPRE) e nada aqui ordena escolas;
 *  - capa = arquivo oficial mais recente (ex. sintético: "30% (2025) × meta 32%
 *    (−2 p.p.)"), na mesma precisão — a PUBLICADA, que a API informa (27,90 continua
 *    27,90); as casas decimais de outro arquivo aparecem como detalhe, com a data do
 *    arquivo de origem;
 *  - todo número tem o selo de fonte (INEP, arquivo de <data>);
 *  - sem dado é "sem resultado importado" — nunca 0; importado SEM resultado
 *    oficial (o INEP não divulgou) diz isso, com o motivo;
 *  - na comparação, a meta vem com o ano dela (os territórios podem estar em anos
 *    diferentes).
 *
 * E3: com dado importado, uma segunda aba ("Série, níveis e média de LP", `AbaICA`)
 * traz o gráfico da série com a meta tracejada, SP e Brasil na rede pública (cada
 * comparação com a sua rede no nome) e SP nas redes municipais, os níveis 0–8 e a
 * média de LP. As casas decimais dos microdados aparecem como "detalhe dos
 * microdados de <data>". O selo é o `SeloFonte` reutilizável. As abas seguem o
 * padrão de `RelatoriosArea` (aba → `aria-controls` → `tabpanel` rotulado).
 */
import { AlertTriangle, Info, Landmark } from "lucide-react";
import { useId, useState } from "react";

import SeloFonte, { ehMicrodados, textoDetalhe } from "../../components/SeloFonte";
import { Badge, Card, Carregando, Mensagem } from "../../components/ui";
import { useApi } from "../../hooks/useApi";
import AbaICA from "./AbaICA";
import ImportarICA from "./ImportarICA";
import {
  MOTIVOS,
  numeroBR,
  percentual,
  pontosPercentuais,
  type ComparacaoICA,
  type NumeroICA,
  type RespostaICA,
  type TerritorioICA,
} from "./ica";

export type { FonteICA, RespostaICA } from "./ica";
export { numeroBR, pontosPercentuais } from "./ica";
export { diaDoArquivo } from "../../components/SeloFonte";

const REDE_DO_TERRITORIO: Record<string, string> = {
  municipio: "rede municipal",
  uf: "rede pública",
  brasil: "rede pública",
};

function Situacao({ c }: { c: ComparacaoICA | null }) {
  if (!c) return null;
  if (c.situacao === "atingiu") return <Badge tom="ok">atingiu a meta</Badge>;
  if (c.situacao === "nao_atingiu") return <Badge tom="alerta">não atingiu a meta</Badge>;
  return <Badge>empate na precisão divulgada — a confirmar</Badge>;
}

/** As casas decimais de outro arquivo, com a data dele: "26,18 no arquivo de
 *  22/04/2024"; dos microdados, "30,20 — detalhe dos microdados de 10/03/2026"
 *  (exemplos sintéticos). */
function Detalhe({ n }: { n: NumeroICA | undefined }) {
  if (!n?.detalhe) return null;
  const origem = textoDetalhe(n.detalhe.fonte);
  return (
    <span className="block text-[11px] text-zinc-500">
      {numeroBR(n.detalhe.valor, n.detalhe.casas_decimais)}
      {origem ? `${ehMicrodados(n.detalhe.fonte) ? " — " : " "}${origem}` : ""}
    </span>
  );
}

function Celula({ n }: { n: NumeroICA | undefined }) {
  if (!n) return <span className="text-zinc-400">—</span>;
  if (n.valor == null) {
    return <span className="text-xs text-zinc-500">{MOTIVOS[n.motivo_ausencia ?? ""] ?? "sem resultado"}</span>;
  }
  return (
    <>
      <span className="font-medium tabular-nums">{percentual(n)}</span>
      <Detalhe n={n} />
    </>
  );
}

/** Importado, mas sem resultado oficial: o motivo do resultado mais recente. */
function semResultadoOficial(t: TerritorioICA): string {
  const ultimo = [...t.resultados].reverse().find((r) => r.valor == null);
  const motivo = ultimo ? MOTIVOS[ultimo.motivo_ausencia ?? ""] : undefined;
  return `O INEP não divulgou resultado do ICA para ${t.nome}${ultimo && motivo ? ` — ${ultimo.edicao}: ${motivo}` : ""}.`;
}

function Capa({ t, legenda }: { t: TerritorioICA; legenda: RespostaICA["legenda_nivel"] }) {
  const d = t.destaque;
  if (!d) {
    // "Nada importado" ≠ "importado, e o INEP não divulgou resultado".
    return (
      <p className="rounded-lg border border-dashed border-zinc-300 p-4 text-sm text-zinc-500 dark:border-zinc-700"
         data-testid="ica-sem-resultado">
        {t.tem_dados ? semResultadoOficial(t) : `Sem resultado importado do ICA para ${t.nome}.`}
      </p>
    );
  }
  const c = d.comparacao;
  const nivel = t.nivel.find((n) => n.edicao === d.resultado.edicao && n.valor != null);
  const faixa = nivel ? legenda.find((l) => l.nivel === nivel.valor) : undefined;
  const participacao = t.participacao.find((p) => p.edicao === d.resultado.edicao && p.valor != null);
  return (
    <div className="space-y-2">
      <p className="text-sm text-zinc-700 dark:text-zinc-200" data-testid="ica-capa">
        <span className="text-3xl font-semibold tabular-nums tracking-tight">{percentual(d.resultado)}</span>
        {` (${d.resultado.edicao})`}
        {d.meta?.valor != null && ` × meta ${percentual(d.meta)}`}
        {c && ` (${pontosPercentuais(c.diferenca_pp, c.casas_decimais)})`}
      </p>
      <div className="flex flex-wrap items-center gap-2 text-xs text-zinc-500">
        <Situacao c={c} />
        {c?.diferenca_pp_detalhe != null && (
          <span>no detalhe: {pontosPercentuais(c.diferenca_pp_detalhe, c.casas_decimais_detalhe ?? 2)}</span>
        )}
        {nivel?.valor != null && (
          <span>
            Nível oficial {nivel.valor} ({nivel.edicao}){faixa ? ` — ${faixa.faixa} de alfabetizados` : ""}
          </span>
        )}
        {participacao && <span>Participação {percentual(participacao)} ({participacao.edicao})</span>}
      </div>
    </div>
  );
}

function TabelaSerie({ t }: { t: TerritorioICA }) {
  const anos = [...new Set([...t.resultados, ...t.metas].map((n) => n.edicao))].sort((a, b) => a - b);
  if (anos.length === 0) return null;
  const resultado = new Map(t.resultados.map((n) => [n.edicao, n]));
  const meta = new Map(t.metas.map((n) => [n.edicao, n]));
  const comp = new Map(t.comparacoes.map((c) => [c.edicao, c]));
  return (
    <table className="w-full text-sm">
      <caption className="sr-only">ICA de {t.nome}: resultado e meta por ano</caption>
      <thead>
        <tr className="text-left text-xs text-zinc-500">
          <th className="py-1 pr-3 font-medium">Ano</th>
          <th className="py-1 pr-3 font-medium">Resultado</th>
          <th className="py-1 pr-3 font-medium">Meta</th>
          <th className="py-1 font-medium">Diferença</th>
        </tr>
      </thead>
      <tbody>
        {anos.map((ano) => {
          const c = comp.get(ano);
          return (
            <tr key={ano} className="border-t border-zinc-100 align-top dark:border-zinc-800">
              <td className="py-1.5 pr-3 tabular-nums">{ano}</td>
              <td className="py-1.5 pr-3"><Celula n={resultado.get(ano)} /></td>
              <td className="py-1.5 pr-3"><Celula n={meta.get(ano)} /></td>
              <td className="py-1.5 tabular-nums">
                {c ? pontosPercentuais(c.diferenca_pp, c.casas_decimais) : "—"}
                {c?.diferenca_pp_detalhe != null && (
                  <span className="block text-[11px] text-zinc-500">
                    {pontosPercentuais(c.diferenca_pp_detalhe, c.casas_decimais_detalhe ?? 2)} no detalhe
                  </span>
                )}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

/** Mesma rede de ensino em cada nível, em ORDEM FIXA (nunca por valor). */
function Comparacao({ territorios }: { territorios: TerritorioICA[] }) {
  const anos = [...new Set(territorios.flatMap((t) => t.resultados.map((r) => r.edicao)))].sort((a, b) => a - b);
  if (anos.length === 0) return null;
  return (
    <table className="w-full text-sm">
      <caption className="sr-only">ICA do município, do estado e do Brasil</caption>
      <thead>
        <tr className="text-left text-xs text-zinc-500">
          <th className="py-1 pr-3 font-medium">Território</th>
          {anos.map((a) => <th key={a} className="py-1 pr-3 font-medium">{a}</th>)}
          <th className="py-1 font-medium">Meta (ano do último resultado)</th>
        </tr>
      </thead>
      <tbody>
        {territorios.map((t) => {
          const porAno = new Map(t.resultados.map((r) => [r.edicao, r]));
          return (
            <tr key={t.abrangencia} className="border-t border-zinc-100 align-top dark:border-zinc-800">
              <td className="py-1.5 pr-3">
                {t.nome} <span className="text-xs text-zinc-500">({REDE_DO_TERRITORIO[t.abrangencia]})</span>
              </td>
              {anos.map((a) => <td key={a} className="py-1.5 pr-3"><Celula n={porAno.get(a)} /></td>)}
              <td className="py-1.5">
                {t.destaque?.meta ? (
                  // Cada território pode estar num ano diferente: a meta diz o dela.
                  <span className="flex flex-wrap items-center gap-1.5">
                    <span className="tabular-nums">{percentual(t.destaque.meta)} ({t.destaque.meta.edicao})</span>
                    <Situacao c={t.destaque.comparacao} />
                  </span>
                ) : t.tem_dados ? "—" : <span className="text-xs text-zinc-500">sem resultado importado</span>}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

/** A aba "Resumo" (e o cartão inteiro, quando ainda não há abas). */
function Resumo({ dados, municipio }: { dados: RespostaICA; municipio: TerritorioICA | undefined }) {
  return (
    <>
      {municipio && <Capa t={municipio} legenda={dados.legenda_nivel} />}
      {municipio && <TabelaSerie t={municipio} />}
      {dados.tem_dados && <Comparacao territorios={dados.territorios} />}
      <SeloFonte fontes={dados.fontes} testId="ica-selo" />
    </>
  );
}

const ABAS = [["resumo", "Resumo"], ["detalhes", "Série, níveis e média de LP"]] as const;
type Aba = (typeof ABAS)[number][0];

/** `aoMudar` (opcional): avisa a página quando a importação do ICA muda algo da rede —
 *  inclusive o código IBGE, que as outras importações oficiais também usam. */
export default function CartaoICA({ redeId, ehGlobal, aoMudar }: {
  redeId: number; ehGlobal: boolean; aoMudar?: () => void;
}) {
  const { dados, carregando, erro, recarregar } = useApi<RespostaICA>(`/redes/${redeId}/indicadores/ica`);
  const municipio = dados?.territorios.find((t) => t.abrangencia === "municipio");
  const [aba, setAba] = useState<Aba>("resumo");
  const comAbas = Boolean(dados?.tem_dados && municipio);
  // Ids estáveis da aba e do painel (aria-controls / aria-labelledby).
  const idBase = useId();
  const idAba = (chave: string) => `${idBase}-aba-${chave}`;
  const idPainel = `${idBase}-painel`;

  return (
    <section data-testid="cartao-ica" aria-label="Indicador Criança Alfabetizada oficial do INEP">
    <Card className="space-y-4 p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="flex items-center gap-2 text-sm font-semibold">
          <Landmark size={16} className="text-indigo-600" /> Indicador Criança Alfabetizada (ICA) — oficial
        </h2>
        <Badge tom="destaque">INEP</Badge>
      </div>
      <p className="flex items-start gap-1.5 rounded-lg bg-indigo-50 p-2.5 text-xs text-indigo-800 dark:bg-indigo-500/10 dark:text-indigo-300">
        <Info size={14} className="mt-0.5 shrink-0" />
        <span>
          {dados?.aviso_rede ?? "O ICA é o indicador da REDE municipal: o INEP não publica o ICA por escola."}
          {" "}Percentual de alunos do 2º ano com 743 pontos ou mais na escala Saeb de Língua Portuguesa.
        </span>
      </p>

      {carregando && !dados ? (
        <Carregando texto="Carregando o ICA..." />
      ) : erro && !dados ? (
        <Mensagem tipo="erro">Não foi possível carregar o ICA: {erro.message}</Mensagem>
      ) : dados ? (
        <>
          {dados.pendencia === "codigo_ibge" && (
            <p className="flex items-start gap-1.5 rounded-lg bg-amber-50 p-2.5 text-xs text-amber-800 dark:bg-amber-500/10 dark:text-amber-300">
              <AlertTriangle size={14} className="mt-0.5 shrink-0" />
              A rede não tem o código IBGE do município cadastrado: sem ele, o ICA do município não pode
              ser recortado do arquivo do INEP. Sem resultado importado.
              {!ehGlobal && " Quem cadastra o código é o administrador global do Constela."}
            </p>
          )}
          {comAbas && (
            <div role="tablist" aria-label="Partes do ICA"
                 className="flex flex-wrap gap-1 border-b border-zinc-200 dark:border-zinc-800">
              {ABAS.map(([chave, rotulo]) => (
                <button key={chave} id={idAba(chave)} type="button" role="tab" aria-selected={aba === chave}
                        aria-controls={idPainel} onClick={() => setAba(chave)}
                        className={`-mb-px border-b-2 px-3 py-2 text-sm font-medium transition-colors ${
                          aba === chave
                            ? "border-indigo-600 text-zinc-900 dark:text-zinc-50"
                            : "border-transparent text-zinc-500 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100"
                        }`}>
                  {rotulo}
                </button>
              ))}
            </div>
          )}
          {comAbas ? (
            <div role="tabpanel" id={idPainel} aria-labelledby={idAba(aba)} className="space-y-4">
              {aba === "detalhes" ? <AbaICA dados={dados} /> : <Resumo dados={dados} municipio={municipio} />}
            </div>
          ) : (
            <Resumo dados={dados} municipio={municipio} />
          )}
        </>
      ) : null}

      {ehGlobal && (
        <ImportarICA redeId={redeId} redeNome={dados?.rede_nome ?? `#${redeId}`}
                     semCodigoIbge={dados?.pendencia === "codigo_ibge"}
                     aoMudar={() => { recarregar(); aoMudar?.(); }} />
      )}
    </Card>
    </section>
  );
}
