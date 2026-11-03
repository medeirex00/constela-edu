/**
 * Diagnóstico exploratório — a aba padrão das Análises avançadas (`/rede/analise`; o
 * `?ver=diagnostico` dos links de antes abre a mesma aba). Por escola, o que as avaliações
 * OFICIAIS e o uso das PLATAFORMAS dizem em Leitura (LP) e em Matemática (MT), lado a lado, e
 * a leitura que dá para fazer disso. É HIPÓTESE EXPLORATÓRIA calculada pelo Constela — a
 * faixa fixa diz isso no topo, com a comparabilidade (anos): hoje as plataformas medem um ano
 * letivo e os resultados oficiais por escola são de edições anteriores (outra coorte).
 *
 * Os níveis (prioritário, acompanhar...), as categorias (convergente/divergente) e as
 * leituras LP/MT só existem AQUI, na área técnica: a página "Escolas em acompanhamento" do
 * fluxo principal mostra só os sinais de atenção, sem níveis nem categorias.
 *
 * Princípios (os mesmos do backend, `GET /redes/{id}/analise/diagnostico`):
 *  - SEM RANKING: escolas em ordem alfabética; o nível de acompanhamento filtra, não ordena;
 *  - SEM DISPERSÃO: com anos diferentes, um gráfico de pontos sugeriria uma relação que não
 *    pode ser medida — a matriz mostra o estado de cada eixo e a categoria, por extenso;
 *  - RASTREÁVEL: cada linha abre (botão com aria-expanded) TODOS os sinais, cada um com o selo
 *    de natureza (Oficial · Plataforma · Calculado pelo Constela · Dados) e a referência, os
 *    números oficiais usados (com a fonte) e as plataformas da janela;
 *  - AUSÊNCIA ≠ ZERO; célula protegida (k) = "protegido".
 * Critérios, limitações e metodologia ficam recolhidos; o CSV leva a mesma tabela. Os
 * alertas do catálogo (cadastro, cobertura, sem registro, estimativas fora das análises), que
 * moravam na antiga Visão geral, ficam na tela Avaliações externas — um lugar só.
 */
import { ChevronDown, FileDown, Stethoscope } from "lucide-react";
import { Fragment, useId, useState } from "react";

import { TabelaRolavel } from "../../components/TabelaRolavel";
import { Badge, Botao, Card, Carregando, IconePastel, Mensagem } from "../../components/ui";
import { baixarCsv } from "../../lib/csvRanking";
import { dataHora } from "../../lib/formato";
import DetalhesEFontes, { Recolhivel } from "./DetalhesFonte";
import { tabelaCsvDiagnostico } from "./RelatoriosRede";
import {
  FaixaHipotese, FiltrosAplicados, PosicaoNaRede, SeloNatureza, TD, TH, TITULO_CARTAO, useDiagnostico,
} from "./comum";
import {
  EXPLICA_NIVEL, ORDEM_NIVEIS, ROTULO_CATEGORIA, ROTULO_ESTADO, ROTULO_NIVEL, avaliacaoPelaBaseGeral, coberturaDe,
  decimal, diaBR, diferencaComUnidade, estadoDoEixo, porNome, rotuloCobertura, textoPendencia,
  textoTolerancias, valorComUnidade,
} from "./formato";
import type { RespostaIndicadoresRede } from "./tipos";
import type {
  CategoriaLeitura, DirecaoSinal, EscolaDiagnostico, EstadoEixo, LeituraComponente, NivelAcompanhamento,
  PlataformasDiagnostico, PosicaoRede, RespostaDiagnostico, SinalDiagnostico,
} from "./tiposDiagnostico";

const CINZA = "text-zinc-600 dark:text-zinc-400";
const PRESA = "presa-esquerda-celular";

const TOM_NIVEL: Record<NivelAcompanhamento, "erro" | "alerta" | "info" | "neutro"> = {
  prioritario: "erro", acompanhar: "alerta", oportunidade: "info", dados_insuficientes: "neutro", sem_sinal: "neutro",
};
const TOM_ESTADO: Record<EstadoEixo, "ok" | "alerta" | "neutro" | "info"> = {
  favoravel: "ok", atencao: "alerta", misto: "info", sem_dado: "neutro",
};
const TOM_CATEGORIA: Record<CategoriaLeitura, "ok" | "alerta" | "erro" | "info" | "neutro" | "destaque"> = {
  convergente_favoravel: "ok", convergente_atencao: "erro", divergente_uso_alto: "alerta",
  divergente_uso_baixo: "destaque", inconclusiva: "neutro",
};
const ROTULO_DIRECAO: Record<DirecaoSinal, string> = { atencao: "Atenção", favoravel: "Favorável", informativo: "Informativo" };
const TOM_DIRECAO: Record<DirecaoSinal, "alerta" | "ok" | "neutro"> = { atencao: "alerta", favoravel: "ok", informativo: "neutro" };
const EIXOS: { chave: SinalDiagnostico["eixo"]; rotulo: string }[] = [
  { chave: "avaliacao", rotulo: "Avaliações oficiais" },
  { chave: "plataforma", rotulo: "Plataformas" },
  { chave: "dados", rotulo: "Dados e cadastro" },
];

/** A comparabilidade dos anos, por extenso. Quem decide "mesmo ano" é o BACKEND, leitura a
 *  leitura (só os sinais com direção, um ano letivo só e o período dentro dele): a faixa só
 *  conta as leituras — a edição mais recente da rede ser do ano das plataformas NÃO basta
 *  (a atenção de uma escola pode vir de outra edição). */
function textoComparabilidade(d: RespostaDiagnostico): string {
  const { avaliacao_mais_recente: a, plataforma: p } = d.resumo.anos;
  if (a == null) return "Ainda não há resultado oficial por escola importado: as leituras ficam sem o lado da avaliação.";
  if (p == null) return `Resultados oficiais até ${a}; sem plataforma medida no período: as leituras ficam sem o lado do uso.`;
  const leituras = d.escolas.flatMap((e) => [e.leituras?.lp, e.leituras?.mt]);
  const mesmoAno = leituras.filter((l) => l?.comparabilidade === "mesmo_ano").length;
  const exploratorias = leituras.filter((l) => l?.comparabilidade === "exploratoria").length;
  if (mesmoAno === 0) {
    return `Resultados oficiais até ${a} e uso das plataformas no ano letivo de ${p}: nenhuma leitura junta avaliação e `
      + "plataformas do mesmo ano letivo — outra edição e outra coorte de alunos. É leitura exploratória: não mede a "
      + "mesma população nem o mesmo período.";
  }
  return `Em ${mesmoAno} leitura(s), avaliação oficial e plataformas são do mesmo ano letivo (${p}): ainda assim é `
    + "associação entre as duas coisas, nunca causa."
    + (exploratorias ? ` Nas outras ${exploratorias}, anos diferentes (outra edição e outra coorte): leitura exploratória.` : "");
}

function Eixo({ rotulo, estado, nota }: { rotulo: string; estado: EstadoEixo; nota?: string | null }) {
  return (
    <span className="flex flex-wrap items-center gap-1">
      <span className={CINZA}>{rotulo}:</span>
      <Badge tom={TOM_ESTADO[estado]}>{ROTULO_ESTADO[estado]}</Badge>
      {nota && <span className={`text-[11px] ${CINZA}`}>{nota}</span>}
    </span>
  );
}

function CelulaLeitura({ l }: { l: LeituraComponente | undefined }) {
  if (!l) return <span className={CINZA}>— sem leitura</span>;
  return (
    <div className="min-w-[11rem] space-y-1">
      <Eixo rotulo="Avaliação" estado={estadoDoEixo(l.avaliacao)}
            nota={avaliacaoPelaBaseGeral(l) ? "(pelos indicadores gerais: IEE/Ideb)" : null} />
      <Eixo rotulo="Plataforma" estado={estadoDoEixo(l.plataforma)} />
      <p className="pt-0.5"><Badge tom={TOM_CATEGORIA[l.categoria] ?? "neutro"}>{ROTULO_CATEGORIA[l.categoria] ?? l.categoria}</Badge></p>
    </div>
  );
}

/** As plataformas da escola na janela (protegido e sem dado escritos), com a posição contra a rede. */
function ResumoPlataformas({ p }: { p: PlataformasDiagnostico | null }) {
  if (!p) return <p className={CINZA}>Sem dado de plataforma desta escola na janela.</p>;
  if (p.suprimido) {
    return (
      <p className={CINZA}>
        Protegido: {p.texto_supressao ?? "poucos alunos — os números não aparecem, para proteger as crianças"}.
      </p>
    );
  }
  const linha = (nome: string, chave: "elefante" | "matific", partes: (string | null)[],
                 pos: { participacao: PosicaoRede | null; intensidade: PosicaoRede | null } | null,
                 motivo: string | null | undefined, suprimido: boolean, textoSupressao?: string | null) => {
    const cobertura = rotuloCobertura(coberturaDe(p.cobertura, chave));
    const ultima = diaBR(coberturaDe(p.ultima_coleta, chave));
    return (
      <li key={chave} className="space-y-0.5">
        <p>
          <span className="font-semibold">{nome}:</span>{" "}
          {suprimido
            ? <span className={CINZA}>protegido — {textoSupressao ?? "poucos alunos: os números não aparecem, para proteger as crianças"}</span>
            : partes.filter(Boolean).join(" · ") || <span className={CINZA}>sem dado na janela</span>}
        </p>
        {!suprimido && pos && (pos.participacao || pos.intensidade) && (
          <p className="flex flex-wrap gap-x-3 gap-y-0.5">
            {pos.participacao && <span>participação: <PosicaoNaRede posicao={pos.participacao} /></span>}
            {pos.intensidade && <span>intensidade: <PosicaoNaRede posicao={pos.intensidade} /></span>}
          </p>
        )}
        {!suprimido && pos && !pos.participacao && !pos.intensidade && motivo && (
          <p className={CINZA}>Sem comparação com a rede: {motivo}</p>
        )}
        {(cobertura || ultima) && (
          <p className={CINZA}>{[cobertura, ultima ? `última coleta ${ultima}` : null].filter(Boolean).join(" · ")}</p>
        )}
      </li>
    );
  };
  const pct = (v: number | null | undefined, r: string) => (v == null ? null : `${decimal(v, 1)}% ${r}`);
  const e = p.elefante, m = p.matific;
  return (
    <ul className="space-y-2">
      {e ? linha("Elefante", "elefante", [
        pct(e.participacao_pct, "de participação"),
        e.livros_por_aluno == null ? null : `${decimal(e.livros_por_aluno)} livros novos/aluno`,
        e.minutos_por_aluno == null ? null : `${decimal(e.minutos_por_aluno, 1)} min/aluno`,
        pct(e.taxa_acerto_pct, "de acerto"),
      ], { participacao: e.posicao_participacao, intensidade: e.posicao_intensidade },
      e.motivo_sem_comparacao ?? e.motivo_posicao_participacao ?? e.motivo_posicao_intensidade, e.suprimido,
      e.texto_supressao ?? e.texto_sem_dado)
        : <li className={CINZA}>Elefante: módulo não contratado.</li>}
      {m ? linha("Matific", "matific", [
        pct(m.participacao_pct, "de participação"),
        m.atividades_por_aluno == null ? null : `${decimal(m.atividades_por_aluno)} atividades/aluno`,
        m.desempenho_medio == null ? null : `desempenho ${decimal(m.desempenho_medio)} de 5`,
      ], { participacao: m.posicao_participacao, intensidade: m.posicao_intensidade },
      m.motivo_sem_comparacao ?? m.motivo_posicao_participacao ?? m.motivo_posicao_intensidade, m.suprimido,
      m.texto_supressao ?? m.texto_sem_dado)
        : <li className={CINZA}>Matific: módulo não contratado.</li>}
    </ul>
  );
}

/** O detalhe de uma escola: todos os sinais (natureza + referência), leituras, números e fontes. */
function DetalheEscola({ e, base, fontes }: {
  e: EscolaDiagnostico; base: RespostaIndicadoresRede; fontes: RespostaDiagnostico["fontes"];
}) {
  const unidade = (chave: string) => base.indicadores.find((i) => i.chave === chave)?.unidade ?? null;
  const nomeInd = (chave: string) => base.indicadores.find((i) => i.chave === chave)?.nome ?? chave.toUpperCase();
  return (
    <div className="space-y-4 text-xs text-zinc-800 dark:text-zinc-100">
      <div className="space-y-1">
        <p className="flex flex-wrap items-center gap-2">
          <span className="font-semibold">Acompanhamento:</span>
          <Badge tom={TOM_NIVEL[e.acompanhamento.nivel]}>{ROTULO_NIVEL[e.acompanhamento.nivel]}</Badge>
          <SeloNatureza natureza="hipotese" />
        </p>
        {e.acompanhamento.motivos.length > 0 && (
          <ul className="list-disc space-y-0.5 pl-4">{e.acompanhamento.motivos.map((t) => <li key={t}>{t}</li>)}</ul>
        )}
      </div>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        {(["lp", "mt"] as const).map((c) => {
          const l = e.leituras?.[c];
          if (!l) return null;
          return (
            <div key={c} className="space-y-1 rounded-xl bg-white p-3 dark:bg-zinc-900" data-testid={`leitura-${c}`}>
              <p className="font-semibold">{c === "lp" ? "Leitura (LP)" : "Matemática (MT)"}</p>
              <p>{l.texto}</p>
              {l.categoria === "inconclusiva" && l.motivo && <p className={CINZA}>Por que é inconclusiva: {l.motivo}</p>}
              <p className={CINZA} data-testid={`comparabilidade-${c}`}>
                {l.texto_comparabilidade ?? (
                  `Avaliação ${l.anos?.avaliacao ?? "—"} × plataformas ${l.anos?.plataforma ?? "—"}: ${
                    l.comparabilidade === "mesmo_ano" ? "mesmo ano — associação, nunca causa."
                      : l.comparabilidade === "exploratoria" ? "leitura exploratória (anos e coortes diferentes)."
                        : "falta um dos lados — não há o que comparar."}`)}
              </p>
            </div>
          );
        })}
      </div>

      <div className="space-y-2">
        <p className="font-semibold">Todos os sinais ({e.sinais.length})</p>
        {e.sinais.length === 0 ? (
          <p className={CINZA}>Nenhum sinal para esta escola.</p>
        ) : EIXOS.map(({ chave, rotulo }) => {
          const doEixo = e.sinais.filter((s) => s.eixo === chave);
          if (doEixo.length === 0) return null;
          return (
            <div key={chave} className="space-y-1">
              <p className={`text-[11px] font-semibold uppercase tracking-wide ${CINZA}`}>{rotulo}</p>
              <ul className="space-y-1.5" data-testid={`sinais-${chave}`}>
                {doEixo.map((s) => (
                  <li key={`${s.codigo}-${s.referencia}-${s.texto}`} className="flex flex-wrap items-start gap-x-2 gap-y-1"
                      data-testid="sinal">
                    {/* Plataforma: o número vem dela; o "abaixo da rede" é critério do Constela. */}
                    {s.eixo === "plataforma" ? (
                      <>
                        <SeloNatureza natureza="plataforma" />
                        <SeloNatureza natureza="calculado" />
                      </>
                    ) : <SeloNatureza natureza={s.natureza} />}
                    <Badge tom={TOM_DIRECAO[s.direcao]}>{ROTULO_DIRECAO[s.direcao]}</Badge>
                    <span className="min-w-0 flex-1 break-words">
                      {s.texto}
                      <span className={`block ${CINZA}`}>Referência: {s.referencia}</span>
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          );
        })}
      </div>

      <div className="space-y-1">
        <p className="font-semibold">Números oficiais usados (a última edição de cada série)</p>
        {e.oficiais.length === 0 ? (
          <p className={CINZA}>Nenhum número oficial desta escola.</p>
        ) : (
          <ul className="space-y-0.5" data-testid="oficiais-escola">
            {e.oficiais.map((o) => (
              <li key={`${o.indicador}-${o.etapa}-${o.componente}`}>
                <span className="font-medium">{o.rotulo || nomeInd(o.indicador)}</span>: {valorComUnidade(o.valor, o.casas, unidade(o.indicador))}
                {" "}({o.edicao})
                {o.valor_rede != null && ` · rede ${valorComUnidade(o.valor_rede, o.casas_rede ?? o.casas, unidade(o.indicador))}`}
                {o.diferenca_rede != null
                  && ` (${diferencaComUnidade(o.diferenca_rede, o.casas_diferenca ?? o.casas, unidade(o.indicador))})`}
                {o.instavel ? " · média instável (TPS = 0)" : o.tps_zero && " · calculado com médias de TPS = 0"}
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="space-y-1">
        <p className="font-semibold">Plataformas na janela</p>
        <ResumoPlataformas p={e.plataformas} />
      </div>

      {e.pendencias.length > 0 && (
        <p><span className="font-semibold">Pendências: </span>{e.pendencias.map(textoPendencia).join("; ")}.</p>
      )}

      {e.oficiais.length > 0 && (
        <DetalhesEFontes fontes={fontes} testId={`fontes-diagnostico-${e.id}`}
                         itens={e.oficiais.map((o) => ({ rotulo: `${o.rotulo || nomeInd(o.indicador)} (${o.edicao})`, fonte_id: o.fonte_id }))} />
      )}
    </div>
  );
}

function LinhaEscola({ e, base, fontes, inicialAberta }: {
  e: EscolaDiagnostico; base: RespostaIndicadoresRede; fontes: RespostaDiagnostico["fontes"]; inicialAberta: boolean;
}) {
  const [aberta, setAberta] = useState(inicialAberta);
  const idDetalhe = useId();
  return (
    <Fragment>
      <tr className="border-b border-zinc-100 align-top dark:border-zinc-800/60" data-testid={`diagnostico-escola-${e.id}`}>
        <th scope="row" className={`${TD} ${PRESA} min-w-[10rem] text-left font-medium`}>
          <span className="block break-words">{e.nome}</span>
          {/* O nome acessível COMEÇA pelo texto visível (quem usa comando de voz diz "Ver
              sinais") e diz de qual escola é (uma linha por escola, todas iguais à vista). */}
          <button type="button" aria-expanded={aberta} aria-controls={aberta ? idDetalhe : undefined}
                  onClick={() => setAberta((a) => !a)}
                  aria-label={`${aberta ? "Esconder" : "Ver"} sinais (${e.sinais.length}) — ${e.nome}`}
                  className="mt-1 inline-flex min-h-[2rem] items-center gap-1 rounded-lg px-1.5 text-[11px] font-semibold text-indigo-700 transition-colors hover:bg-indigo-50 dark:text-indigo-300 dark:hover:bg-indigo-500/10">
            {aberta ? "Esconder" : "Ver"} sinais ({e.sinais.length})
            <ChevronDown size={13} aria-hidden className={`transition-transform duration-200 ${aberta ? "rotate-180" : ""}`} />
          </button>
        </th>
        <td className={TD}><CelulaLeitura l={e.leituras?.lp} /></td>
        <td className={TD}><CelulaLeitura l={e.leituras?.mt} /></td>
        <td className={TD}>
          <Badge tom={TOM_NIVEL[e.acompanhamento.nivel]}>{ROTULO_NIVEL[e.acompanhamento.nivel] ?? e.acompanhamento.nivel}</Badge>
        </td>
      </tr>
      {aberta && (
        <tr id={idDetalhe} className="border-b border-zinc-100 bg-zinc-50/70 dark:border-zinc-800/60 dark:bg-zinc-800/30"
            data-testid={`detalhe-escola-${e.id}`}>
          <td colSpan={4} className="px-3 py-4">
            {/* Quando a tabela rola de lado (celular, tablet e telas estreitas), o detalhe fica
                preso à esquerda e na largura da ÁREA VISÍVEL da tabela — 100cqw é a largura do
                cartão (o contêiner, ver o Card abaixo), menos o recuo e o degradê de 40 px da
                borda que rola: o texto quebra onde se vê, sem ler de lado nem sob o degradê. */}
            <div className="sticky left-3 max-w-[calc(100cqw-4rem)]">
              <DetalheEscola e={e} base={base} fontes={fontes} />
            </div>
          </td>
        </tr>
      )}
    </Fragment>
  );
}

function ResumoCategorias({ porCategoria }: { porCategoria: RespostaDiagnostico["resumo"]["por_categoria"] }) {
  const partes = (["lp", "mt"] as const).map((c) => {
    const itens = Object.entries(porCategoria?.[c] ?? {}).filter(([, n]) => (n ?? 0) > 0)
      .map(([cat, n]) => `${ROTULO_CATEGORIA[cat as CategoriaLeitura] ?? cat}: ${n}`);
    return { c, itens };
  }).filter((x) => x.itens.length > 0);
  if (partes.length === 0) return null;
  return (
    <ul className={`space-y-0.5 text-xs ${CINZA}`} data-testid="resumo-categorias">
      {partes.map(({ c, itens }) => (
        <li key={c}><span className="font-semibold">{c === "lp" ? "Leitura (LP)" : "Matemática (MT)"}:</span> {itens.join(" · ")}</li>
      ))}
    </ul>
  );
}

function Conteudo({ d, base, escolaId }: { d: RespostaDiagnostico; base: RespostaIndicadoresRede; escolaId: number | null }) {
  const [nivel, setNivel] = useState<NivelAcompanhamento | null>(null);
  const escolas = porNome(d.escolas);
  const visiveis = nivel ? escolas.filter((e) => e.acompanhamento.nivel === nivel) : escolas;
  const contagem = (n: NivelAcompanhamento) =>
    d.resumo?.por_nivel?.[n] ?? escolas.filter((e) => e.acompanhamento.nivel === n).length;
  const tolerancias = textoTolerancias(d.criterios?.tolerancias);
  const chip = (ativo: boolean) => `inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-semibold transition-colors ${
    ativo
      ? "border-indigo-500 bg-indigo-600 text-white dark:border-indigo-400"
      : "border-zinc-200 bg-white text-zinc-700 hover:border-indigo-300 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-200"}`;

  return (
    <div className="space-y-5">
      <Card className="space-y-4 p-6">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <h2 className={`${TITULO_CARTAO} flex-wrap`}>
            <IconePastel icone={Stethoscope} tom="ambar" tamanho="sm" /> Avaliação oficial × uso das plataformas, por escola
          </h2>
          <Botao variante="secundario" tamanho="sm" onClick={() => baixarCsv(tabelaCsvDiagnostico(d))}>
            <FileDown size={14} aria-hidden /> Exportar diagnóstico (CSV)
          </Botao>
        </div>
        <FaixaHipotese>
          <p data-testid="comparabilidade">{textoComparabilidade(d)}</p>
          <p>Escolas em ordem alfabética — não é ranking. Nenhum gráfico de pontos: com anos diferentes ele sugeriria uma relação que não dá para medir.</p>
        </FaixaHipotese>
        <FiltrosAplicados testId="filtros-diagnostico">
          Vale aqui: o período ({d.janela.rotulo.toLowerCase()}), só para o lado das plataformas. Série e escola não se
          aplicam: o diagnóstico olha a escola inteira, em todas as escolas da rede. Gerado em {dataHora(d.gerado_em)}.
        </FiltrosAplicados>
        <p className="text-xs text-zinc-700 dark:text-zinc-200" data-testid="resumo-diagnostico">
          {d.resumo.escolas_total} escola(s) · {d.resumo.escolas_com_oficial} com número oficial ·{" "}
          {d.resumo.escolas_com_plataforma} com plataforma medida na janela.
        </p>
        <div className="space-y-2">
          <div className="flex flex-wrap gap-2" role="group" aria-label="Filtrar pelo nível de acompanhamento" data-testid="chips-nivel">
            <button type="button" aria-pressed={nivel == null} onClick={() => setNivel(null)} className={chip(nivel == null)}>
              Todas ({escolas.length})
            </button>
            {ORDEM_NIVEIS.map((n) => (
              <button key={n} type="button" aria-pressed={nivel === n} onClick={() => setNivel(nivel === n ? null : n)}
                      className={chip(nivel === n)} title={EXPLICA_NIVEL[n]}>
                {ROTULO_NIVEL[n]} ({contagem(n)})
              </button>
            ))}
          </div>
          {nivel && (
            <p className={`text-xs ${CINZA}`} data-testid="explica-nivel">
              <span className="font-semibold">{ROTULO_NIVEL[nivel]}:</span> {EXPLICA_NIVEL[nivel]}.
            </p>
          )}
          <ResumoCategorias porCategoria={d.resumo.por_categoria} />
        </div>
      </Card>

      {/* Contêiner de consulta: o detalhe expandido mede a área visível da tabela (100cqw). */}
      <Card className="space-y-3 p-6 [container-type:inline-size]">
        {visiveis.length === 0 ? (
          <p className={`text-sm ${CINZA}`} data-testid="diagnostico-vazio">
            {escolas.length === 0 ? "A rede não tem escolas cadastradas." : "Nenhuma escola neste nível."}
          </p>
        ) : (
          <TabelaRolavel rotulo="Diagnóstico por escola: tabela completa">
            <table className="w-full text-xs" data-testid="tabela-diagnostico">
              <caption className="sr-only">
                Diagnóstico exploratório por escola, em ordem alfabética: o estado da avaliação oficial e do uso da
                plataforma em Leitura e em Matemática, a categoria de cada um e o nível de acompanhamento
              </caption>
              <thead>
                <tr className={`border-b border-zinc-200 align-bottom dark:border-zinc-800 ${CINZA}`}>
                  <th className={`${TH} ${PRESA}`} scope="col">Escola</th>
                  <th className={TH} scope="col">Leitura (LP) · Elefante</th>
                  <th className={TH} scope="col">Matemática (MT) · Matific</th>
                  <th className={TH} scope="col">Acompanhamento</th>
                </tr>
              </thead>
              <tbody>
                {visiveis.map((e) => (
                  <LinhaEscola key={e.id} e={e} base={base} fontes={d.fontes} inicialAberta={e.id === escolaId} />
                ))}
              </tbody>
            </table>
          </TabelaRolavel>
        )}
        <p className={`text-xs ${CINZA}`}>
          Cada linha abre todos os sinais da escola, com a natureza de cada um (Oficial · Plataforma · Calculado pelo
          Constela · Dados) e a referência — dá para chegar ao número de origem.
        </p>
      </Card>

      <Recolhivel titulo="Critérios do diagnóstico" testId="criterios-diagnostico">
        <ul className="list-disc space-y-1 pl-4">
          {(d.criterios?.regras ?? []).map((t) => <li key={t}>{t}</li>)}
          {tolerancias.length > 0 && <li>“Na média” = diferença menor que a tolerância: {tolerancias.join("; ")}.</li>}
          {d.criterios?.n_minimo_escolas_comparacao != null && (
            <li>A posição de uma plataforma contra a rede só é calculada com ao menos {d.criterios.n_minimo_escolas_comparacao} escolas
              com a métrica e a coleta da escola em dia.</li>
          )}
        </ul>
        <p className="font-semibold">Os níveis de acompanhamento</p>
        <ul className="list-disc space-y-0.5 pl-4">
          {ORDEM_NIVEIS.map((n) => <li key={n}><span className="font-medium">{ROTULO_NIVEL[n]}:</span> {EXPLICA_NIVEL[n]}.</li>)}
        </ul>
      </Recolhivel>
      {d.limitacoes.length > 0 && (
        <Recolhivel titulo="Limitações (o que esta leitura não diz)" testId="limitacoes-diagnostico">
          <ul className="list-disc space-y-1 pl-4">{d.limitacoes.map((t) => <li key={t}>{t}</li>)}</ul>
        </Recolhivel>
      )}
      {d.metodologia.length > 0 && (
        <Recolhivel titulo="Como o diagnóstico é feito (metodologia)" testId="metodologia-diagnostico">
          <ul className="list-disc space-y-1 pl-4">{d.metodologia.map((t) => <li key={t}>{t}</li>)}</ul>
        </Recolhivel>
      )}
    </div>
  );
}

export default function Diagnostico({ redeId, base, escolaId }: {
  redeId: number;
  base: RespostaIndicadoresRede;
  escolaId: number | null;
}) {
  const diagnostico = useDiagnostico(redeId);
  const dados = diagnostico.dados && diagnostico.dados.rede.id === redeId ? diagnostico.dados : null;
  if (diagnostico.erro && !dados) {
    return (
      <Card className="space-y-4 p-6">
        <FaixaHipotese />
        <Mensagem tipo="erro">Não foi possível carregar o diagnóstico: {diagnostico.erro.message}</Mensagem>
      </Card>
    );
  }
  if (!dados) return <Card className="p-6"><Carregando texto="Carregando o diagnóstico..." /></Card>;
  return <Conteudo d={dados} base={base} escolaId={escolaId} />;
}

