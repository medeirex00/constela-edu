/**
 * Ranking Geral — a ORDEM ÚNICA da escola: "Geral (Leitura + Matemática)", a
 * classificação acumulada do ano letivo pela nota geral. Nenhum cálculo muda
 * aqui: a lista vem carimbada de `/ranking` (posições e denominador da API).
 *
 * O desempenho POR MATÉRIA (classificação oficial de Leitura e de Matemática,
 * com o corte "ausência não é zero" e a lista de não aferidos) vive em
 * `components/DesempenhoDimensao` e abre no topo das abas Leitura e Matemática.
 *
 * Esta ordem única segue como padrão porque aposentá-la muda quem sobe ao pódio
 * em toda escola mista — premiações nº 7/8/11 da spec, DECISÃO DE PRODUTO do
 * dono.
 *
 * PERÍODO: o Ranking Geral é sempre a classificação ACUMULADA do ano letivo.
 * Com qualquer outro período global escolhido, a tela avisa e oferece a aba
 * Evolução (a classificação por período), em vez de repetir aqui a mesma
 * tabela daquela aba. O seletor de período fica na tela porque é global (segue
 * o usuário para Leitura, Matemática, Evolução e Premiações).
 *
 * TURNO: o turno global filtra a lista (`?turno=`); com turno, a API renumera
 * as posições dentro do recorte e carimba o denominador do conjunto filtrado.
 *
 * CONTAGEM honesta no cabeçalho da tabela (a posição exibida precisa bater com
 * o número ao lado):
 *   - sem filtro           → "N aluno(s) na classificação";
 *   - com turno            → "N aluno(s) no turno X" (posições do turno);
 *   - turma/série sem turno → "N aluno(s) neste filtro · posição na escola
 *     inteira" (a gestão vê a posição carimbada da escola; o professor já recebe
 *     a lista renumerada nas turmas dele, então o sufixo não se aplica).
 */
import { Download, TrendingUp } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { FiltroTurmaSerie, type AlvoRanking } from "../components/FiltroTurmaSerie";
import { SeletorPeriodo } from "../components/SeletorPeriodo";
import { SeletorTurno } from "../components/SeletorTurno";
import { Badge, Botao, Card, Carregando, Mensagem, PageHeader, Vazio } from "../components/ui";
import { useApp } from "../context/AppContext";
import { useApi } from "../hooks/useApi";
import { apiDownload } from "../lib/api";
import { nota, notaDaMateria, numero } from "../lib/formato";
import { TURNO_SEM, TURNO_TODOS, aplicarTurno, rotuloTurno, turnoEfetivo } from "../lib/turnos";
import type { RankingItem, Turma } from "../lib/types";

export default function RankingGeral({ embutido = false }: { embutido?: boolean } = {}) {
  const { escolaId, usuario, periodo, definirPeriodo, turno, definirTurno } = useApp();
  const [params, setParams] = useSearchParams();
  const [alvo, setAlvo] = useState<AlvoRanking>({});
  const [baixandoCartaz, setBaixandoCartaz] = useState(false);
  const [erroCartaz, setErroCartaz] = useState("");

  // O cartaz (pôster) é documento de vitrine — só gestão (admin/coordenador/rede).
  const gestor = Boolean(usuario?.is_global) || ["admin", "coordenador"].includes(usuario?.cargo ?? "");

  // Período ≠ ano letivo: a classificação por período é a aba Evolução.
  const porPeriodo = periodo.preset !== "ano_letivo";

  // Cache curto: a lista de turmas do dropdown de filtro muda raramente e é
  // invalidada em Turmas.tsx ao criar/editar/excluir (limparCacheApi).
  const { dados: turmas } = useApi<Turma[]>(
    escolaId ? `/escolas/${escolaId}/turmas` : null, { cacheMs: 60_000 });
  // Turno persistido que não existe nesta escola conta como "todos" na
  // consulta (sem sobrescrever a escolha guardada).
  const turnoAtivo = turnoEfetivo(turno, turmas);

  // Filtros: uma turma específica OU uma série consolidada (todas as turmas do
  // ano) — nunca os dois ao mesmo tempo — e o turno global.
  const parametros = new URLSearchParams();
  if (alvo.turma_id) parametros.set("turma_id", alvo.turma_id);
  if (alvo.ano_escolar) parametros.set("ano_escolar", alvo.ano_escolar);
  aplicarTurno(parametros, turnoAtivo);

  const { dados: itens, erro, carregando, recarregar } = useApi<RankingItem[]>(
    escolaId ? `/escolas/${escolaId}/ranking?${parametros}` : null,
  );
  const lista = itens ?? [];

  const comTurmaOuSerie = Boolean(alvo.turma_id || alvo.ano_escolar);
  const comTurno = turnoAtivo !== TURNO_TODOS;
  // Denominador carimbado pela API (conjunto filtrado quando há recorte) ou,
  // na falta dele, o tamanho da lista.
  const totalDaApi = numero(lista[0]?.n_aferidos ?? lista.length);
  let contagem: string;
  if (comTurno) {
    // Posições renumeradas pela API dentro do turno (e da turma/série, se houver).
    // "Sem turno" não é nome de turno: vira "em turmas sem turno".
    const recorteTurno = turnoAtivo === TURNO_SEM
      ? "em turmas sem turno" : `no turno ${rotuloTurno(turnoAtivo)}`;
    contagem = comTurmaOuSerie
      ? `${totalDaApi} aluno(s) neste filtro, ${recorteTurno}`
      : `${totalDaApi} aluno(s) ${recorteTurno}`;
  } else if (comTurmaOuSerie) {
    // Sem turno, a gestão recebe a posição carimbada da ESCOLA: o número ao lado
    // é só quantos alunos o filtro mostra, e a tela diz isso.
    contagem = gestor
      ? `${numero(lista.length)} aluno(s) neste filtro · posição na escola inteira`
      : `${numero(lista.length)} aluno(s) neste filtro`;
  } else {
    contagem = `${totalDaApi} aluno(s) na classificação`;
  }

  // O cartaz é sempre da escola inteira; ao mudar período/filtro, um erro antigo
  // do cartaz perde o contexto — limpa para não ficar pendurado na tela.
  useEffect(() => { setErroCartaz(""); }, [periodo, alvo, turnoAtivo]);

  // Troca para a aba Evolução mantendo os demais parâmetros da URL (a tela
  // vive embutida em Rankings.tsx, que deriva a aba de `?ver=`).
  function irParaEvolucao() {
    const prox = new URLSearchParams(params);
    prox.set("ver", "evolucao");
    setParams(prox);
  }

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
          descricao="Classificação acumulada do ano letivo pela nota geral (Leitura + Matemática). Filtre por turma, série ou turno."
        />
      )}

      <Card className="mb-4 flex flex-wrap items-center gap-2 p-4">
        <SeletorPeriodo valor={periodo} onChange={definirPeriodo} />
        <FiltroTurmaSerie turmas={turmas ?? []} valor={alvo} onChange={setAlvo} />
        <SeletorTurno turmas={turmas ?? []} valor={turno} onChange={definirTurno} />
        {gestor && (
          <Botao
            onClick={baixarCartaz}
            // O cartaz é sempre da escola inteira (classificação do ano); não
            // depende dos filtros de turma/série/turno. Só desabilita por
            // escola vazia quando NENHUM filtro está aplicado.
            disabled={baixandoCartaz
              || (!comTurmaOuSerie && !comTurno && lista.length === 0)}
            title="Gera um pôster em PDF com todos os alunos da escola (não usa os filtros de turma, série ou turno)"
            className="ml-auto"
          >
            <Download size={15} /> {baixandoCartaz ? "Gerando cartaz…" : "Baixar cartaz"}
          </Botao>
        )}
      </Card>

      {erroCartaz && <div className="mb-4"><Mensagem tipo="erro">{erroCartaz}</Mensagem></div>}

      {/* Período ≠ ano letivo: NÃO repetimos aqui a tabela da aba Evolução
          (era a mesma consulta, duplicada). O aviso aponta para lá. */}
      {porPeriodo && (
        <div
          role="status"
          className="mb-4 flex flex-wrap items-center gap-3 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900 dark:border-amber-500/20 dark:bg-amber-500/10 dark:text-amber-100"
        >
          <span>
            O Ranking Geral é a classificação acumulada do ano letivo.
            A classificação por período fica na aba Evolução.
          </span>
          <Botao variante="neutro" onClick={irParaEvolucao} className="ml-auto">
            <TrendingUp size={15} /> Ver a aba Evolução
          </Botao>
        </div>
      )}

      <Card>
        {carregando ? (
          <Carregando />
        ) : erro ? (
          <Vazio titulo="Não foi possível carregar" descricao={erro.message}
                 acao={<Botao variante="neutro" onClick={recarregar}>Tentar de novo</Botao>} />
        ) : lista.length === 0 ? (
          <Vazio
            titulo="Nenhuma nota calculada ainda"
            descricao="Importe dados das plataformas para gerar o ranking." />
        ) : (
          <div className="overflow-x-auto">
            {/* Nome da ordem + contagem coerente com a posição exibida (ver
                "CONTAGEM honesta" no topo do arquivo). */}
            <p className="border-b border-zinc-100 px-4 py-2 text-xs text-zinc-500 dark:border-zinc-800/60 dark:text-zinc-400">
              Geral (Leitura + Matemática) · {contagem}
            </p>
            <table className="w-full text-sm tabular-nums">
              <thead>
                <tr className="border-b border-zinc-200 text-left text-xs uppercase tracking-wide text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
                  <th className="px-4 py-2 font-medium">#</th>
                  <th className="px-4 py-2 font-medium">Aluno</th>
                  <th className="hidden px-4 py-2 font-medium md:table-cell">Turma</th>
                  <th className="px-4 py-2 text-right font-medium">Matemática</th>
                  <th className="px-4 py-2 text-right font-medium">Leitura</th>
                  <th className="px-4 py-2 text-right font-medium">Geral</th>
                </tr>
              </thead>
              <tbody>
                {lista.map((item) => (
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
                    {/* Ordem única: a lista não corta por aferido, então
                        `nota_matific`/`nota_elefante` chegam 0,0 tanto para quem
                        não tem snapshot da plataforma quanto para quem tem e não
                        produziu. O item carimba `aferido_*` (existência do
                        snapshot), e `notaDaMateria` separa os dois: "—" no
                        primeiro caso, "0,0" no segundo. */}
                    <td className="px-4 py-2.5 text-right">
                      {notaDaMateria(item.nota_matific, item.aferido_matematica)}
                    </td>
                    <td className="px-4 py-2.5 text-right">
                      {notaDaMateria(item.nota_elefante, item.aferido_leitura)}
                    </td>
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
