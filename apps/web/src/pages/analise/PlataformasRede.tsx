/**
 * "Escolas no período" — a tabela das plataformas por escola (`TabelaEscolasNoPeriodo`), a lista
 * da tela Escolas (`/rede/escolas`): uma linha por escola, em ORDEM ALFABÉTICA (não é ranking),
 * com participação, livros novos, minutos e acerto do Elefante; participação, atividades e
 * desempenho do Matific; e a situação da coleta de cada uma. A escola com poucos alunos aparece
 * como "protegido" (texto) e a métrica sem dado diz isso — nunca 0. Nada de aluno: tudo chega
 * agregado e já protegido pelo backend.
 *
 * Na tela Escolas, o nome leva à ficha da escola (`linkDaEscola`), a coluna "Comparar" marca de 2
 * a 4 escolas para a comparação lado a lado (`comparar`) e a escola INATIVA no cadastro leva o selo
 * "inativa no cadastro" (`inativas`, do painel da rede — a resposta das plataformas não traz o
 * cadastro). Sem essas props, a tabela é só leitura.
 *
 * (Era a parte de baixo da aba antiga das plataformas da análise, `?ver=plataformas`, que virou
 * a tela `/rede/plataformas`.)
 */
import { Link } from "react-router-dom";

import { TabelaRolavel } from "../../components/TabelaRolavel";
import { Badge } from "../../components/ui";
import { TEXTO_SUPRESSAO_PADRAO } from "./Plataformas";
import { TD, TH } from "./comum";
import { decimal, diaBR, numeroProtegido, porNome, rotuloCobertura } from "./formato";
import type { EscolaPlataformas, MetricasElefante, MetricasMatific, RespostaPlataformas } from "./tipos";

const CINZA = "text-zinc-600 dark:text-zinc-400";
const PRESA = "presa-esquerda-celular"; // index.css: a coluna da escola fica presa no celular

export const pct = (v: number | null | undefined) => (v == null ? null : `${decimal(v, 1)}%`);
const inteiro = (n: number) => n.toLocaleString("pt-BR");

/** Métrica nula: "protegido" quando escondida para proteger (`numeroProtegido`); senão "sem dado". Nunca 0. */
export function Valor({ texto, campo, bloco }: {
  texto: string | null; campo: string; bloco: MetricasElefante | MetricasMatific;
}) {
  if (texto != null) return <>{texto}</>;
  const protegido = numeroProtegido(bloco, campo);
  return (
    <span className={`text-[11px] ${CINZA}`} title={protegido ? bloco.texto_metricas_protegidas ?? undefined : undefined}>
      {protegido ? "protegido" : "sem dado"}
    </span>
  );
}

/** A situação da coleta de uma escola numa plataforma ("coleta parcial (até 20/09)"). */
export function Coleta({ e, p }: { e: EscolaPlataformas; p: "elefante" | "matific" }) {
  const situacao = e.cobertura?.[p] ?? null;
  const rotulo = rotuloCobertura(situacao);
  if (!rotulo) return <span className={CINZA}>—</span>;
  const ate = situacao === "coleta_parcial" ? diaBR(e.coberto_ate?.[p] ?? null) : null;
  const atencao = situacao != null && situacao !== "ok";
  return (
    <span className={atencao ? "text-amber-800 dark:text-amber-300" : undefined}>
      {rotulo}{ate ? ` (até ${ate})` : ""}
    </span>
  );
}

/** O bloco de uma plataforma sem número nenhum na escola: o porquê, uma vez (não 4 "sem dado"). */
export function semDadoDo(m: MetricasElefante | MetricasMatific | null, situacao: string | null | undefined): string | null {
  if (!m) return rotuloCobertura(situacao) ?? "sem dado no período";
  if (m.participacao_pct == null && (m.texto_sem_dado || m.motivo_sem_dado)) {
    return m.texto_sem_dado ?? rotuloCobertura(situacao) ?? "sem dado no período";
  }
  return null;
}

/** O selo da escola INATIVA no cadastro (o mesmo texto da tabela das Avaliações externas): a
 *  escola continua na lista — são todas as escolas da rede —, mas não passa por uma escola em
 *  funcionamento. Não diz nada sobre uso. */
export function SeloInativaNoCadastro() {
  return <span data-escola-inativa><Badge tom="neutro">inativa no cadastro</Badge></span>;
}

/** Para onde o nome da escola leva (a ficha) e o estado da navegação (de onde ela veio). */
export interface LinkDaEscola {
  para: string;
  estado?: unknown;
}

/** A coluna "Comparar": as escolas marcadas e o limite (a comparação lado a lado cabe 4). */
export interface EscolhaParaComparar {
  marcadas: number[];
  limite: number;
  aoAlternar: (escolaId: number) => void;
  /** O id do texto VISÍVEL da tela (perto do resumo das marcadas) que diz por que as outras caixas
   *  travaram — `porqueCaixaTravada`. Com o limite cheio, cada caixa travada aponta para ele
   *  (`aria-describedby`): o leitor de tela lê o porquê, e quem toca no celular o vê escrito. */
  idPorqueTravada: string;
}

/** O porquê da caixa travada, por extenso (o mesmo texto na tela, no leitor de tela e no `title`). */
export const porqueCaixaTravada = (limite: number) =>
  `Chegou ao máximo de ${limite} escolas: para marcar outra, desmarque uma.`;

/** A caixa "Comparar" de uma escola: com o limite cheio, as outras ficam travadas — o porquê vai
 *  ligado à caixa (`aria-describedby`), não só no `title` (que o toque e o leitor de tela não mostram). */
function CaixaComparar({ e, comparar }: { e: EscolaPlataformas; comparar: EscolhaParaComparar }) {
  const marcada = comparar.marcadas.includes(e.escola_id);
  const cheio = !marcada && comparar.marcadas.length >= comparar.limite;
  return (
    // O rótulo inteiro é a área de toque (44 px), não só a caixinha.
    <label className={`inline-flex min-h-[2.75rem] min-w-[2.75rem] items-center justify-center ${cheio ? "cursor-not-allowed" : "cursor-pointer"}`}
           title={cheio ? porqueCaixaTravada(comparar.limite) : undefined}>
      <input type="checkbox" className="h-4 w-4 accent-indigo-600" checked={marcada} disabled={cheio}
             aria-describedby={cheio ? comparar.idPorqueTravada : undefined}
             onChange={() => comparar.aoAlternar(e.escola_id)} />
      <span className="sr-only">Comparar {e.nome}</span>
    </label>
  );
}

/**
 * "Escolas no período" — a tabela reutilizável (a lista da tela Escolas, `/rede/escolas`): todas
 * as escolas em ordem alfabética, com as métricas das duas plataformas e a coleta de cada uma.
 */
export function TabelaEscolasNoPeriodo({ dados, linkDaEscola, comparar, inativas }: {
  dados: RespostaPlataformas;
  /** O nome da escola vira link (a ficha da escola). */
  linkDaEscola?: (escolaId: number) => LinkDaEscola;
  /** A coluna "Comparar" (caixa de seleção por escola). */
  comparar?: EscolhaParaComparar;
  /** As escolas INATIVAS no cadastro (pelo painel da rede): o selo ao lado do nome. Sem o painel
   *  (carregando ou com erro), vazio — nenhum selo inventado. */
  inativas?: ReadonlySet<number>;
}) {
  const comElefante = dados.modulos.elefante;
  const comMatific = dados.modulos.matific;
  const escolas = porNome(dados.escolas);
  const colunasElefante = comElefante ? 5 : 0;
  const colunasMatific = comMatific ? 4 : 0;
  if (escolas.length === 0) {
    return <p className={`text-sm ${CINZA}`}>Nenhuma escola da rede neste recorte.</p>;
  }
  if (!comElefante && !comMatific) {
    return <p className={`text-sm ${CINZA}`}>A rede não tem módulo de plataforma contratado.</p>;
  }
  return (
    <div className="space-y-2">
      <TabelaRolavel rotulo="Escolas no período: tabela completa">
        <table className="w-full text-xs" data-testid="tabela-escolas-periodo">
          <caption className="sr-only">
            Escolas da rede em ordem alfabética: uso do Elefante e do Matific no período e a situação da coleta
          </caption>
          <thead>
            <tr className={`border-b border-zinc-200/70 dark:border-zinc-800 ${CINZA}`}>
              <th className={`${TH} ${PRESA} align-bottom`} scope="col" rowSpan={2}>Escola</th>
              {comparar && <th className={`${TH} align-bottom text-center`} scope="col" rowSpan={2}>Comparar</th>}
              <th className={`${TH} align-bottom`} scope="col" rowSpan={2}>Alunos</th>
              {comElefante && <th className={`${TH} text-indigo-700 dark:text-indigo-300`} scope="colgroup" colSpan={colunasElefante}>Elefante Letrado</th>}
              {comMatific && <th className={`${TH} text-teal-700 dark:text-teal-300`} scope="colgroup" colSpan={colunasMatific}>Matific</th>}
            </tr>
            <tr className={`border-b border-zinc-200 align-bottom dark:border-zinc-800 ${CINZA}`}>
              {comElefante && <>
                <th className={TH} scope="col">Participação</th>
                <th className={TH} scope="col">Livros novos/aluno</th>
                <th className={TH} scope="col">Min/aluno</th>
                <th className={TH} scope="col">Acerto</th>
                <th className={TH} scope="col">Coleta</th>
              </>}
              {comMatific && <>
                <th className={TH} scope="col">Participação</th>
                <th className={TH} scope="col">Atividades/aluno</th>
                <th className={TH} scope="col">Desempenho (0–5)</th>
                <th className={TH} scope="col">Coleta</th>
              </>}
            </tr>
          </thead>
          <tbody>
            {escolas.map((e) => {
              const semElefante = semDadoDo(e.elefante, e.cobertura?.elefante);
              const semMatific = semDadoDo(e.matific, e.cobertura?.matific);
              const link = linkDaEscola?.(e.escola_id);
              return (
                <tr key={e.escola_id} data-testid={`escola-periodo-${e.escola_id}`}
                    className="border-b border-zinc-100 align-top last:border-0 dark:border-zinc-800/60">
                  <th scope="row" className={`${TD} ${PRESA} min-w-[9rem] text-left font-medium`}>
                    {link ? (
                      <Link to={link.para} state={link.estado}
                            className="break-words rounded text-indigo-700 underline-offset-2 hover:underline dark:text-indigo-300">
                        {e.nome}
                      </Link>
                    ) : <span className="break-words">{e.nome}</span>}
                    {inativas?.has(e.escola_id) && <span className="mt-0.5 block"><SeloInativaNoCadastro /></span>}
                  </th>
                  {comparar && (
                    <td className="py-0 text-center align-middle" data-testid="celula-comparar">
                      <CaixaComparar e={e} comparar={comparar} />
                    </td>
                  )}
                  {e.suprimido ? (
                    // Escola com poucos alunos: nenhum número (nem a coleta) — protegido, por extenso.
                    <td colSpan={1 + colunasElefante + colunasMatific} className={`${TD} ${CINZA}`} data-testid="escola-protegida">
                      Protegido: {e.texto_supressao ?? TEXTO_SUPRESSAO_PADRAO}.
                    </td>
                  ) : (
                    <>
                      <td className={TD}>{e.alunos == null ? <span className={CINZA}>—</span> : inteiro(e.alunos)}</td>
                      {comElefante && (semElefante ? (
                        <>
                          <td colSpan={4} className={`${TD} ${CINZA}`}>Sem dado: {semElefante}</td>
                          <td className={TD}><Coleta e={e} p="elefante" /></td>
                        </>
                      ) : e.elefante && (
                        <>
                          <td className={TD}><Valor texto={pct(e.elefante.participacao_pct)} campo="participacao_pct" bloco={e.elefante} /></td>
                          <td className={TD}><Valor texto={decimal(e.elefante.livros_por_aluno)} campo="livros_por_aluno" bloco={e.elefante} /></td>
                          <td className={TD}><Valor texto={decimal(e.elefante.minutos_por_aluno, 1)} campo="minutos_por_aluno" bloco={e.elefante} /></td>
                          <td className={TD}><Valor texto={pct(e.elefante.taxa_acerto_pct)} campo="taxa_acerto_pct" bloco={e.elefante} /></td>
                          <td className={TD}><Coleta e={e} p="elefante" /></td>
                        </>
                      ))}
                      {comMatific && (semMatific ? (
                        <>
                          <td colSpan={3} className={`${TD} ${CINZA}`}>Sem dado: {semMatific}</td>
                          <td className={TD}><Coleta e={e} p="matific" /></td>
                        </>
                      ) : e.matific && (
                        <>
                          <td className={TD}><Valor texto={pct(e.matific.participacao_pct)} campo="participacao_pct" bloco={e.matific} /></td>
                          <td className={TD}><Valor texto={decimal(e.matific.atividades_por_aluno)} campo="atividades_por_aluno" bloco={e.matific} /></td>
                          <td className={TD}><Valor texto={decimal(e.matific.desempenho_medio)} campo="desempenho_medio" bloco={e.matific} /></td>
                          <td className={TD}><Coleta e={e} p="matific" /></td>
                        </>
                      ))}
                    </>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      </TabelaRolavel>
      <p className={`text-xs ${CINZA}`} data-testid="legenda-escolas-periodo">
        Escolas em ordem alfabética — não é ranking. Participação e médias por aluno: sobre os alunos que a plataforma
        conhece no período (Elefante: com conta; Matific: com dado no período); quem fica fora não conta como zero.
        “Protegido”: poucos alunos (menos de {dados.k_minimo}) — os números não aparecem, para proteger as crianças.
        “Sem dado” não é zero. Acerto e desempenho dependem da dificuldade do conteúdo: compare com cuidado.
      </p>
    </div>
  );
}
