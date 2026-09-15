/**
 * Classificação OFICIAL de uma matéria (Arquitetura 2): a lista dos alunos
 * AFERIDOS naquela matéria (têm dado da plataforma dela), ordenados pela nota
 * oficial (0–100) do ano letivo, com o denominador no cabeçalho e, logo abaixo,
 * a lista de quem "ainda não foi aferido". Quem não tem dado NÃO entra com 0,0:
 * sai do ranking e aparece na lista de ação, que é onde a coordenação precisa
 * vê-lo.
 *
 * Extraído do Ranking Geral (que agora fica só com a ordem única) para ser o
 * TOPO das abas Leitura e Matemática. Os filtros (turma/série e o turno global)
 * chegam por props — a tela dona é quem tem os seletores; aqui só se consulta.
 *
 * Endpoints: `/ranking?dimensao=...` e `/nao-aferidos`, ambos com os mesmos
 * filtros (turma_id | ano_escolar, turno). O denominador exibido é o
 * `n_aferidos` carimbado pela API no conjunto filtrado.
 *
 * CARTAZ da matéria (gestão): `/ranking/cartaz?dimensao=...` — pôster em PDF
 * com os alunos aferidos naquela matéria na ESCOLA INTEIRA. Como o cartaz não
 * usa turma, série nem turno, o botão fica desabilitado (com o motivo) quando
 * algum desses filtros está aplicado, para não parecer que baixa o recorte.
 */
import { Download } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { useApp } from "../context/AppContext";
import { useApi } from "../hooks/useApi";
import { usePerfil } from "../hooks/usePerfil";
import { apiDownload } from "../lib/api";
import { nota, numero } from "../lib/formato";
import { TURNO_TODOS, aplicarTurno } from "../lib/turnos";
import type { Dimensao, NaoAferidos, RankingItem } from "../lib/types";
import { Badge, Botao, Card, Carregando, Mensagem, Vazio } from "./ui";

const MATERIAS: Record<Dimensao, { rotulo: string; dados: string; rotuloDados: string }> = {
  leitura: { rotulo: "Leitura", dados: "livros_unicos", rotuloDados: "Livros" },
  matematica: { rotulo: "Matemática", dados: "atividades", rotuloDados: "Atividades" },
};

/** Filtros da classificação: turma OU série (nunca os dois) + turno global. */
export interface FiltrosDimensao {
  turma_id?: string;
  ano_escolar?: string;
  /** Turno global já resolvido pela tela ("todos" | "" | código). */
  turno: string;
}

export function DesempenhoDimensao({ dimensao, filtros }: {
  dimensao: Dimensao;
  filtros: FiltrosDimensao;
}) {
  const { escolaId } = useApp();
  // O cartaz (pôster) é documento de vitrine — só gestão (admin/coordenador/
  // Admin Global), a mesma regra do cartaz do Ranking Geral.
  const { gestor } = usePerfil();
  const materia = MATERIAS[dimensao];
  const [baixandoCartaz, setBaixandoCartaz] = useState(false);
  const [erroCartaz, setErroCartaz] = useState("");

  // Mesmos filtros nas duas consultas: quem está no ranking e quem ainda não
  // foi aferido são as duas metades do MESMO recorte.
  const parametros = new URLSearchParams();
  if (filtros.turma_id) parametros.set("turma_id", filtros.turma_id);
  if (filtros.ano_escolar) parametros.set("ano_escolar", filtros.ano_escolar);
  aplicarTurno(parametros, filtros.turno);
  const parametrosRanking = new URLSearchParams(parametros);
  parametrosRanking.set("dimensao", dimensao);

  const { dados: itens, erro, carregando, recarregar } = useApi<RankingItem[]>(
    escolaId ? `/escolas/${escolaId}/ranking?${parametrosRanking}` : null,
  );
  // Visão OPERACIONAL: quem ainda NÃO foi aferido na matéria. Não é ranking (não
  // tem nota nem posição de propósito) — é a contrapartida obrigatória do corte
  // "ausência não é zero": ao sair da lista, a criança não pode sumir da tela.
  const { dados: naoAferidos } = useApi<NaoAferidos>(
    escolaId ? `/escolas/${escolaId}/nao-aferidos?${parametros}` : null,
  );
  const semDado = naoAferidos?.dimensoes.find((d) => d.dimensao === dimensao);
  const lista = itens ?? [];

  // O cartaz é sempre da escola inteira: com turma, série ou turno aplicado ele
  // NÃO corresponde à lista da tela, então o botão desabilita e diz por quê.
  const comFiltro = Boolean(filtros.turma_id || filtros.ano_escolar)
    || filtros.turno !== TURNO_TODOS;
  const cartazIndisponivel = comFiltro
    ? "O cartaz é da escola inteira: tire os filtros de turma, série e turno para baixar."
    : lista.length === 0
      ? `Ainda não há alunos aferidos em ${materia.rotulo} para o cartaz.`
      : "";
  // Um erro antigo do cartaz perde o contexto quando o filtro muda.
  const chaveFiltros = `${filtros.turma_id ?? ""}|${filtros.ano_escolar ?? ""}|${filtros.turno}`;
  useEffect(() => { setErroCartaz(""); }, [chaveFiltros, dimensao]);

  async function baixarCartaz() {
    if (!escolaId) return;
    setBaixandoCartaz(true);
    setErroCartaz("");
    try {
      await apiDownload(`/escolas/${escolaId}/ranking/cartaz?dimensao=${dimensao}`);
    } catch (excecao) {
      setErroCartaz(excecao instanceof Error ? excecao.message : "Não foi possível gerar o cartaz.");
    } finally {
      setBaixandoCartaz(false);
    }
  }

  return (
    <div>
      <div className="mb-1 flex flex-wrap items-center gap-2">
        <h2 className="text-sm font-semibold text-zinc-700 dark:text-zinc-300">
          Classificação oficial — {materia.rotulo}
        </h2>
        {gestor && (
          <Botao
            variante="neutro"
            onClick={baixarCartaz}
            disabled={baixandoCartaz || cartazIndisponivel !== ""}
            title={cartazIndisponivel
              || `Gera um pôster em PDF com os alunos aferidos em ${materia.rotulo} na escola inteira`}
            className="ml-auto"
          >
            <Download size={15} />
            {baixandoCartaz ? "Gerando cartaz…" : `Baixar cartaz de ${materia.rotulo}`}
          </Botao>
        )}
      </div>
      {erroCartaz && <div className="mb-2"><Mensagem tipo="erro">{erroCartaz}</Mensagem></div>}
      <p className="mb-3 text-xs text-zinc-500 dark:text-zinc-400">
        Nota oficial (0–100) do ano letivo. Só entram os alunos com dado da
        plataforma de {materia.rotulo}; quem ainda não tem dado aparece abaixo,
        sem nota e sem posição.
      </p>

      <Card>
        {carregando ? (
          <Carregando />
        ) : erro ? (
          <Vazio titulo="Não foi possível carregar a classificação oficial" descricao={erro.message}
                 acao={<Botao variante="neutro" onClick={recarregar}>Tentar de novo</Botao>} />
        ) : lista.length === 0 ? (
          <Vazio titulo={`Nenhum aluno aferido em ${materia.rotulo} ainda`}
                 descricao="Importe ou sincronize os dados da plataforma para gerar a classificação." />
        ) : (
          <div className="overflow-x-auto">
            {/* O DENOMINADOR precisa estar visível: sem ele, um "3º" em Leitura
                e um "3º" em Matemática parecem comparáveis, e não são. Vem da
                API (conjunto filtrado), não da contagem local. */}
            <p className="border-b border-zinc-100 px-4 py-2 text-xs text-zinc-500 dark:border-zinc-800/60 dark:text-zinc-400">
              {numero(lista[0]?.n_aferidos ?? lista.length)} alunos aferidos em {materia.rotulo}
            </p>
            <table className="w-full text-sm tabular-nums">
              <thead>
                <tr className="border-b border-zinc-200 text-left text-xs uppercase tracking-wide text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
                  <th className="px-4 py-2 font-medium">#</th>
                  <th className="px-4 py-2 font-medium">Aluno</th>
                  <th className="hidden px-4 py-2 font-medium md:table-cell">Turma</th>
                  <th className="px-4 py-2 text-right font-medium">Nota de {materia.rotulo}</th>
                  <th className="hidden px-4 py-2 text-right font-medium sm:table-cell">{materia.rotuloDados}</th>
                  <th className="hidden px-4 py-2 text-right font-medium sm:table-cell">Adoção</th>
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
                    <td className="px-4 py-2.5 text-right font-semibold">{nota(item.nota ?? 0)}</td>
                    <td className="hidden px-4 py-2.5 text-right text-zinc-500 dark:text-zinc-400 sm:table-cell">
                      {numero(item.dados?.[materia.dados] ?? 0)}
                    </td>
                    <td className="hidden px-4 py-2.5 text-right text-zinc-500 dark:text-zinc-400 sm:table-cell">
                      {item.adocao == null ? "—" : `${Math.round(item.adocao)}%`}
                    </td>
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
      {semDado && semDado.alunos.length > 0 && (
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
