/**
 * Ranking Geral. "Todo o histórico" mostra a nota acumulada (tabela Nota);
 * qualquer outro período mostra a CLASSIFICAÇÃO DO PERÍODO — calculada apenas
 * com o que foi feito dentro do intervalo (leituras com data real + ganhos do
 * Matific), usando os mesmos pesos configuráveis.
 */
import { Download } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { FiltroTurmaSerie, type AlvoRanking } from "../components/FiltroTurmaSerie";
import { SeletorPeriodo, periodoParaQuery, type Periodo } from "../components/SeletorPeriodo";
import { Badge, Botao, Card, Carregando, Mensagem, PageHeader, Vazio } from "../components/ui";
import { useApp } from "../context/AppContext";
import { useApi } from "../hooks/useApi";
import { apiDownload } from "../lib/api";
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
  const { escolaId, usuario } = useApp();
  const [periodo, setPeriodo] = useState<Periodo>({ preset: "ano_letivo" });
  const [alvo, setAlvo] = useState<AlvoRanking>({});
  const [baixandoCartaz, setBaixandoCartaz] = useState(false);
  const [erroCartaz, setErroCartaz] = useState("");

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

  const {
    dados: itens,
    erro: erroGeral,
    carregando: carregandoGeral,
    recarregar: recarregarGeral,
  } = useApi<RankingItem[]>(
    escolaId && !porPeriodo ? `/escolas/${escolaId}/ranking?${parametros}` : null,
  );

  const carregando = porPeriodo ? carregandoPeriodo : carregandoGeral;

  // O cartaz é sempre da escola inteira; ao mudar período/filtro, um erro antigo
  // do cartaz perde o contexto — limpa para não ficar pendurado na tela.
  useEffect(() => { setErroCartaz(""); }, [periodo, alvo]);

  // Baixa o cartaz do Ranking Geral (PDF de vitrine, com TODOS os alunos).
  async function baixarCartaz() {
    if (!escolaId) return;
    setBaixandoCartaz(true);
    setErroCartaz("");
    try {
      await apiDownload(`/escolas/${escolaId}/ranking/cartaz`);
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
          descricao="Todo o histórico mostra a nota acumulada; escolha um período para classificar apenas pelo que foi feito no intervalo."
        />
      )}

      <Card className="mb-4 flex flex-wrap items-center gap-2 p-4">
        <SeletorPeriodo valor={periodo} onChange={setPeriodo} />
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
