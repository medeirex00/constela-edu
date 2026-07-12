/**
 * Ranking Geral. "Todo o histórico" mostra a nota acumulada (tabela Nota);
 * qualquer outro período mostra a CLASSIFICAÇÃO DO PERÍODO — calculada apenas
 * com o que foi feito dentro do intervalo (leituras com data real + ganhos do
 * Matific), usando os mesmos pesos configuráveis.
 */
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { SeletorPeriodo, periodoParaQuery, type Periodo } from "../components/SeletorPeriodo";
import { Badge, Botao, Card, Carregando, PageHeader, Vazio, estiloInput } from "../components/ui";
import { useApp } from "../context/AppContext";
import { useApi } from "../hooks/useApi";
import { nota, numero } from "../lib/formato";
import type { RankingItem, Turma } from "../lib/types";

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
  const { escolaId } = useApp();
  const [periodo, setPeriodo] = useState<Periodo>({ preset: "tudo" });
  const [turmaId, setTurmaId] = useState("");
  const [serie, setSerie] = useState("");

  const porPeriodo = periodo.preset !== "tudo";

  // Cache curto: a lista de turmas do dropdown de filtro muda raramente e é
  // invalidada em Turmas.tsx ao criar/editar/excluir (limparCacheApi).
  const { dados: turmas } = useApi<Turma[]>(
    escolaId ? `/escolas/${escolaId}/turmas` : null, { cacheMs: 60_000 });

  // Filtros comuns às duas classificações.
  const parametros = new URLSearchParams();
  if (turmaId) parametros.set("turma_id", turmaId);
  if (serie) parametros.set("ano_escolar", serie);

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

  const {
    dados: itens,
    erro: erroGeral,
    carregando: carregandoGeral,
    recarregar: recarregarGeral,
  } = useApi<RankingItem[]>(
    escolaId && !porPeriodo ? `/escolas/${escolaId}/ranking?${parametros}` : null,
  );

  const carregando = porPeriodo ? carregandoPeriodo : carregandoGeral;

  const series = useMemo(
    () => Array.from(new Set((turmas ?? []).map((turma) => turma.ano_escolar))).sort(),
    [turmas],
  );

  return (
    <div>
      {!embutido && (
        <PageHeader
          titulo="Ranking Geral"
          descricao="Todo o histórico mostra a nota acumulada; escolha um período para classificar apenas pelo que foi feito no intervalo."
        />
      )}

      <Card className="mb-4 flex flex-wrap items-center gap-2 p-4">
        <SeletorPeriodo valor={periodo} onChange={setPeriodo} />
        <select
          aria-label="Filtrar por turma"
          className={`${estiloInput} w-auto`}
          value={turmaId}
          onChange={(evento) => setTurmaId(evento.target.value)}
        >
          <option value="">Todas as turmas</option>
          {(turmas ?? []).map((turma) => (
            <option key={turma.id} value={turma.id}>{turma.nome}</option>
          ))}
        </select>
        <select
          aria-label="Filtrar por série"
          className={`${estiloInput} w-auto`}
          value={serie}
          onChange={(evento) => setSerie(evento.target.value)}
        >
          <option value="">Todas as séries</option>
          {series.map((valor) => (
            <option key={valor} value={valor}>{valor}</option>
          ))}
        </select>
        {porPeriodo && (
          <Badge tom="destaque">calculado só com o período selecionado</Badge>
        )}
      </Card>

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
          <Vazio titulo="Nenhuma nota calculada ainda" descricao="Importe dados das plataformas para gerar o ranking." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm tabular-nums">
              <thead>
                <tr className="border-b border-zinc-200 text-left text-xs uppercase tracking-wide text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
                  <th className="px-4 py-2 font-medium">#</th>
                  <th className="px-4 py-2 font-medium">Aluno</th>
                  <th className="hidden px-4 py-2 font-medium md:table-cell">Turma</th>
                  <th className="px-4 py-2 text-right font-medium">Matific</th>
                  <th className="px-4 py-2 text-right font-medium">Leitura</th>
                  <th className="px-4 py-2 text-right font-medium">Geral</th>
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
                    <td className="px-4 py-2.5 text-right">{nota(item.nota_matific)}</td>
                    <td className="px-4 py-2.5 text-right">{nota(item.nota_elefante)}</td>
                    <td className="px-4 py-2.5 text-right font-semibold">{nota(item.nota_geral)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
