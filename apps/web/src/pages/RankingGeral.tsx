/**
 * Ranking de desempenho do aluno.
 *
 * DESEMPENHO POR DIMENSÃO (Arquitetura 2): o seletor de MATÉRIA escolhe qual
 * ordenação é exibida. "Leitura" e "Matemática" são a ordenação oficial — cada
 * uma lista SÓ os alunos aferidos naquela matéria (têm dado da plataforma
 * dela), ordenados pela nota dela, com o denominador no cabeçalho e a lista de
 * "ainda não aferidos" logo abaixo. Quem não tem dado NÃO entra com 0,0: ele
 * sai do ranking e aparece na lista de ação, que é onde a coordenação precisa
 * vê-lo.
 *
 * "Geral" continua sendo a ordem única LEGADA (nota geral composta). Ela segue
 * como padrão porque aposentá-la muda quem sobe ao pódio em toda escola mista
 * — premiações nº 7/8/11 da spec, DECISÃO DE PRODUTO do dono.
 *
 * "Todo o histórico" mostra a nota acumulada (tabela Nota); qualquer outro
 * período mostra a CLASSIFICAÇÃO DO PERÍODO — calculada apenas com o que foi
 * feito dentro do intervalo (leituras com data real + ganhos do Matific).
 */
import { Download } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { FiltroTurmaSerie, type AlvoRanking } from "../components/FiltroTurmaSerie";
import { SeletorPeriodo, periodoParaQuery } from "../components/SeletorPeriodo";
import { Badge, Botao, Card, Carregando, Mensagem, PageHeader, Vazio } from "../components/ui";
import { useApp } from "../context/AppContext";
import { useApi } from "../hooks/useApi";
import { apiDownload } from "../lib/api";
import { nota, notaDaMateria, numero } from "../lib/formato";
import { useModulos } from "../hooks/useModulos";
import type { NaoAferidos, RankingItem, Turma } from "../lib/types";

type Visao = "geral" | "leitura" | "matematica";

// `aba` é o rótulo do seletor e `rotulo` o nome da matéria no conteúdo. Os dois
// são distintos de propósito: a tela vive embutida em Rankings.tsx, que já tem
// abas "Geral | Elefante Letrado | Matific", e dois controles com o mesmo nome
// na mesma tela são ambíguos para quem usa (e para leitores de tela).
const MATERIAS: { chave: Visao; rotulo: string; aba: string; modulo: string; dados: string }[] = [
  { chave: "leitura", rotulo: "Leitura", aba: "Desempenho em Leitura",
    modulo: "leitura", dados: "livros_unicos" },
  { chave: "matematica", rotulo: "Matemática", aba: "Desempenho em Matemática",
    modulo: "matematica", dados: "atividades" },
];
const ROTULO_DADOS: Record<string, string> = {
  livros_unicos: "Livros",
  atividades: "Atividades",
};

interface ItemPeriodo {
  posicao: number;
  aluno_id: number;
  nome: string;
  turma: string;
  nota_evolucao: number;
  ganhos: {
    atividades: number;
    estrelas: number;
    livros: number;
    tempo_leitura_min: number;
    acertos: number;
  };
}

export default function RankingGeral({ embutido = false }: { embutido?: boolean } = {}) {
  const { escolaId, usuario, periodo, definirPeriodo } = useApp();
  const [alvo, setAlvo] = useState<AlvoRanking>({});
  const [visao, setVisao] = useState<Visao>("geral");
  const [baixandoCartaz, setBaixandoCartaz] = useState(false);
  const [erroCartaz, setErroCartaz] = useState("");
  // Matéria só existe para quem contratou o módulo (SaaS): a cascata é
  // CONTRATO → DADO, então a rede que não assinou não vê a aba nem a lista.
  const { tem } = useModulos();
  const materias = MATERIAS.filter((m) => tem(m.modulo));
  const materia = MATERIAS.find((m) => m.chave === visao) ?? null;

  // O cartaz (pôster) é documento de vitrine — só gestão (admin/coordenador/rede).
  const gestor = Boolean(usuario?.is_global) || ["admin", "coordenador"].includes(usuario?.cargo ?? "");

  // "Ano letivo" mostra a classificação ACUMULADA (nota geral Matific+Leitura);
  // os períodos mais curtos mostram só o que foi feito no intervalo (evolução).
  const porPeriodo = periodo.preset !== "ano_letivo";

  // Cache curto: a lista de turmas do dropdown de filtro muda raramente e é
  // invalidada em Turmas.tsx ao criar/editar/excluir (limparCacheApi).
  const { dados: turmas } = useApi<Turma[]>(
    escolaId ? `/escolas/${escolaId}/turmas` : null, { cacheMs: 60_000 });

  // Filtros comuns às duas classificações: uma turma específica OU uma série
  // consolidada (todas as turmas do ano) — nunca os dois ao mesmo tempo.
  const parametros = new URLSearchParams();
  if (alvo.turma_id) parametros.set("turma_id", alvo.turma_id);
  if (alvo.ano_escolar) parametros.set("ano_escolar", alvo.ano_escolar);

  // Classificação do período: só o que foi feito dentro do intervalo.
  const queryPeriodo = new URLSearchParams(periodoParaQuery(periodo));
  parametros.forEach((v, k) => queryPeriodo.set(k, v));

  const {
    dados: itensPeriodo,
    erro: erroPeriodo,
    carregando: carregandoPeriodo,
    recarregar: recarregarPeriodo,
  } = useApi<ItemPeriodo[]>(
    escolaId && porPeriodo ? `/escolas/${escolaId}/ranking-evolucao?${queryPeriodo}` : null,
  );

  const parametrosGeral = new URLSearchParams(parametros);
  if (materia) parametrosGeral.set("dimensao", materia.chave);

  const {
    dados: itens,
    erro: erroGeral,
    carregando: carregandoGeral,
    recarregar: recarregarGeral,
  } = useApi<RankingItem[]>(
    escolaId && !porPeriodo ? `/escolas/${escolaId}/ranking?${parametrosGeral}` : null,
  );

  // Visão OPERACIONAL: quem ainda NÃO foi aferido na matéria. Não é ranking (não
  // tem nota nem posição de propósito) — é a contrapartida obrigatória do corte
  // "ausência não é zero": ao sair da lista, a criança não pode sumir da tela.
  const { dados: naoAferidos } = useApi<NaoAferidos>(
    escolaId && !porPeriodo && materia
      ? `/escolas/${escolaId}/nao-aferidos?${parametros}` : null,
  );
  const semDado = naoAferidos?.dimensoes.find((d) => d.dimensao === materia?.chave);

  const carregando = porPeriodo ? carregandoPeriodo : carregandoGeral;

  // O cartaz é sempre da escola inteira; ao mudar período/filtro, um erro antigo
  // do cartaz perde o contexto — limpa para não ficar pendurado na tela.
  useEffect(() => { setErroCartaz(""); }, [periodo, alvo, visao]);

  // Baixa o cartaz do Ranking Geral (PDF de vitrine, com TODOS os alunos).
  async function baixarCartaz() {
    if (!escolaId) return;
    setBaixandoCartaz(true);
    setErroCartaz("");
    try {
      // O cartaz acompanha a matéria escolhida: pôster de Leitura, de
      // Matemática, ou o geral LEGADO quando a visão é "Geral".
      await apiDownload(`/escolas/${escolaId}/ranking/cartaz`
        + (materia ? `?dimensao=${materia.chave}` : ""));
    } catch (excecao) {
      setErroCartaz(excecao instanceof Error ? excecao.message : "Não foi possível gerar o cartaz.");
    } finally {
      setBaixandoCartaz(false);
    }
  }

  return (
    <div>
      {!embutido && (
        <PageHeader
          titulo="Ranking Geral"
          descricao="Escolha a matéria para ver o desempenho dela (cada aluno é medido pelo que faz naquela matéria). Escolha um período para classificar apenas pelo que foi feito no intervalo."
        />
      )}

      <Card className="mb-4 flex flex-wrap items-center gap-2 p-4">
        {!porPeriodo && materias.length > 0 && (
          <div role="tablist" aria-label="Matéria"
               className="inline-flex gap-1 rounded-lg border border-zinc-200 bg-zinc-100 p-1 dark:border-zinc-800 dark:bg-zinc-900/60">
            {([{ chave: "geral" as Visao, aba: "Nota geral (legado)" },
               ...materias]).map((m) => (
              <button
                key={m.chave}
                role="tab"
                aria-selected={visao === m.chave}
                onClick={() => setVisao(m.chave as Visao)}
                className={`rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
                  visao === m.chave
                    ? "bg-white text-zinc-900 shadow-sm dark:bg-zinc-800 dark:text-zinc-100"
                    : "text-zinc-500 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100"
                }`}
              >
                {m.aba}
              </button>
            ))}
          </div>
        )}
        <SeletorPeriodo valor={periodo} onChange={definirPeriodo} />
        <FiltroTurmaSerie turmas={turmas ?? []} valor={alvo} onChange={setAlvo} />
        {porPeriodo && (
          <Badge tom="destaque">calculado só com o período selecionado</Badge>
        )}
        {gestor && (
          <Botao
            onClick={baixarCartaz}
            // O cartaz é sempre da escola inteira; não depende dos filtros de
            // turma/série (só exige a visão "Ano letivo"). Só desabilita por
            // escola vazia quando NENHUM filtro está aplicado.
            disabled={baixandoCartaz || porPeriodo || (!alvo.turma_id && !alvo.ano_escolar && (itens ?? []).length === 0)}
            title={porPeriodo
              ? "O cartaz usa o Ranking Geral do ano — selecione “Ano letivo”."
              : "Gera um pôster em PDF com todos os alunos da escola (não usa os filtros de turma/série)"}
            className="ml-auto"
          >
            <Download size={15} /> {baixandoCartaz ? "Gerando cartaz…" : "Baixar cartaz"}
          </Botao>
        )}
      </Card>

      {erroCartaz && <div className="mb-4"><Mensagem tipo="erro">{erroCartaz}</Mensagem></div>}

      <Card>
        {carregando ? (
          <Carregando />
        ) : porPeriodo ? (
          erroPeriodo ? (
            <Vazio titulo="Não foi possível carregar" descricao={erroPeriodo.message}
                   acao={<Botao variante="neutro" onClick={recarregarPeriodo}>Tentar de novo</Botao>} />
          ) : !itensPeriodo || itensPeriodo.length === 0 ? (
            <Vazio titulo="Sem atividades no período" descricao="Ajuste o período ou importe novos relatórios." />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm tabular-nums">
                <thead>
                  <tr className="border-b border-zinc-200 text-left text-xs uppercase tracking-wide text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
                    <th className="px-4 py-2 font-medium">#</th>
                    <th className="px-4 py-2 font-medium">Aluno</th>
                    <th className="hidden px-4 py-2 font-medium md:table-cell">Turma</th>
                    <th className="px-4 py-2 font-medium">Feito no período</th>
                    <th className="px-4 py-2 text-right font-medium">Nota do período</th>
                  </tr>
                </thead>
                <tbody>
                  {itensPeriodo.map((item) => (
                    <tr key={item.aluno_id} className="border-b border-zinc-100 last:border-0 dark:border-zinc-800/60">
                      <td className="px-4 py-2.5">
                        {item.posicao <= 3 ? <Badge tom="destaque">{item.posicao}º</Badge> : `${item.posicao}º`}
                      </td>
                      <td className="px-4 py-2.5">
                        <Link to={`/alunos/${item.aluno_id}`} className="font-medium hover:text-indigo-600 dark:hover:text-indigo-400">
                          {item.nome}
                        </Link>
                      </td>
                      <td className="hidden px-4 py-2.5 text-zinc-500 dark:text-zinc-400 md:table-cell">{item.turma}</td>
                      <td className="px-4 py-2.5 text-xs text-zinc-600 dark:text-zinc-300">
                        {[
                          item.ganhos.livros > 0 && `${numero(item.ganhos.livros)} livro(s)`,
                          item.ganhos.atividades > 0 && `${numero(item.ganhos.atividades)} atividade(s)`,
                          item.ganhos.estrelas > 0 && `${numero(item.ganhos.estrelas)} estrela(s)`,
                          item.ganhos.acertos > 0 && `${numero(item.ganhos.acertos)} acerto(s)`,
                        ]
                          .filter(Boolean)
                          .join(" · ") || "sem atividades"}
                      </td>
                      <td className="px-4 py-2.5 text-right font-semibold">{nota(item.nota_evolucao)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        ) : erroGeral ? (
          <Vazio titulo="Não foi possível carregar" descricao={erroGeral.message}
                 acao={<Botao variante="neutro" onClick={recarregarGeral}>Tentar de novo</Botao>} />
        ) : (itens ?? []).length === 0 ? (
          <Vazio
            titulo={materia
              ? `Nenhum aluno aferido em ${materia.rotulo} ainda`
              : "Nenhuma nota calculada ainda"}
            descricao="Importe dados das plataformas para gerar o ranking." />
        ) : (
          <div className="overflow-x-auto">
            {materia && (
              // O DENOMINADOR precisa estar visível: sem ele, um "3º" em
              // Leitura e um "3º" em Matemática parecem comparáveis, e não são.
              <p className="border-b border-zinc-100 px-4 py-2 text-xs text-zinc-500 dark:border-zinc-800/60 dark:text-zinc-400">
                {numero((itens ?? [])[0]?.n_aferidos ?? (itens ?? []).length)} alunos aferidos em {materia.rotulo}
              </p>
            )}
            <table className="w-full text-sm tabular-nums">
              <thead>
                <tr className="border-b border-zinc-200 text-left text-xs uppercase tracking-wide text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
                  <th className="px-4 py-2 font-medium">#</th>
                  <th className="px-4 py-2 font-medium">Aluno</th>
                  <th className="hidden px-4 py-2 font-medium md:table-cell">Turma</th>
                  {materia ? (
                    <>
                      <th className="px-4 py-2 text-right font-medium">Nota de {materia.rotulo}</th>
                      <th className="hidden px-4 py-2 text-right font-medium sm:table-cell">
                        {ROTULO_DADOS[materia.dados]}
                      </th>
                      <th className="hidden px-4 py-2 text-right font-medium sm:table-cell">Adoção</th>
                    </>
                  ) : (
                    <>
                      <th className="px-4 py-2 text-right font-medium">Matific</th>
                      <th className="px-4 py-2 text-right font-medium">Leitura</th>
                      <th className="px-4 py-2 text-right font-medium">Geral</th>
                    </>
                  )}
                </tr>
              </thead>
              <tbody>
                {(itens ?? []).map((item) => (
                  <tr key={item.aluno_id} className="border-b border-zinc-100 last:border-0 dark:border-zinc-800/60">
                    <td className="px-4 py-2.5">
                      {item.posicao <= 3 ? <Badge tom="destaque">{item.posicao}º</Badge> : `${item.posicao}º`}
                    </td>
                    <td className="px-4 py-2.5">
                      <Link to={`/alunos/${item.aluno_id}`} className="font-medium hover:text-indigo-600 dark:hover:text-indigo-400">
                        {item.nome}
                      </Link>
                    </td>
                    <td className="hidden px-4 py-2.5 text-zinc-500 dark:text-zinc-400 md:table-cell">{item.turma}</td>
                    {materia ? (
                      <>
                        <td className="px-4 py-2.5 text-right font-semibold">{nota(item.nota ?? 0)}</td>
                        <td className="hidden px-4 py-2.5 text-right text-zinc-500 dark:text-zinc-400 sm:table-cell">
                          {numero(item.dados?.[materia.dados] ?? 0)}
                        </td>
                        <td className="hidden px-4 py-2.5 text-right text-zinc-500 dark:text-zinc-400 sm:table-cell">
                          {item.adocao == null ? "—" : `${Math.round(item.adocao)}%`}
                        </td>
                      </>
                    ) : (
                      <>
                        {/* Aba LEGADA: a lista não corta por aferido, então
                            `nota_matific`/`nota_elefante` chegam 0,0 tanto para
                            quem não tem snapshot da plataforma quanto para quem
                            tem e não produziu. O item carimba `aferido_*`
                            (existência do snapshot), e `notaDaMateria` separa os
                            dois: "—" no primeiro caso, "0,0" no segundo. */}
                        <td className="px-4 py-2.5 text-right">
                          {notaDaMateria(item.nota_matific, item.aferido_matematica)}
                        </td>
                        <td className="px-4 py-2.5 text-right">
                          {notaDaMateria(item.nota_elefante, item.aferido_leitura)}
                        </td>
                        <td className="px-4 py-2.5 text-right font-semibold">{nota(item.nota_geral)}</td>
                      </>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {/* NÃO é rodapé decorativo: é a lista de ação da coordenação. Quem nunca
          foi alcançado deixou de aparecer em último lugar com 0,0 (a leitura
          mais injusta que o sistema produzia) e passa a aparecer aqui, sem nota
          e sem posição — porque não há o que medir, não porque foi mal. */}
      {materia && semDado && semDado.alunos.length > 0 && (
        <Card className="mt-4">
          <div className="border-b border-zinc-200 px-4 py-3 dark:border-zinc-800">
            <h3 className="text-sm font-semibold">
              Ainda não aferidos em {materia.rotulo} ({numero(semDado.alunos.length)})
            </h3>
            <p className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">
              Sem dado importado desta plataforma. Não entram no ranking nem na
              média — ausência não é nota zero.
            </p>
          </div>
          <ul className="divide-y divide-zinc-100 dark:divide-zinc-800/60">
            {semDado.alunos.map((aluno) => (
              <li key={aluno.aluno_id} className="flex items-center gap-3 px-4 py-2.5 text-sm">
                <Link to={`/alunos/${aluno.aluno_id}`}
                      className="min-w-0 flex-1 truncate font-medium hover:text-indigo-600 dark:hover:text-indigo-400">
                  {aluno.nome}
                </Link>
                <span className="shrink-0 text-xs text-zinc-400">{aluno.turma}</span>
                <span className="w-6 shrink-0 text-right text-zinc-300 dark:text-zinc-600">—</span>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}
