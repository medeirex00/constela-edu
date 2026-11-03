/**
 * Ranking de TURMAS — as turmas da escola ordenadas pela MÉDIA das notas
 * oficiais (0–100) dos alunos aferidos numa matéria (Leitura ou Matemática).
 *
 * Fonte: `GET /escolas/{id}/ranking/turmas?dimensao=` — a ORDEM e a POSIÇÃO
 * saem do backend (`rankings._ordem_turmas`: média → aferidos → nome → id), e
 * esta tela só exibe. Antes ela ordenava o `/resumo-escola` no navegador, com
 * desempate próprio (`localeCompare`) e a turma da Fase junto: duas ordens para
 * a mesma pergunta. A média é a MESMA do resumo da escola (só sobre quem tem
 * dado da plataforma — quem não tem dado não entra como zero); só entram turmas
 * que concorrem (1º ao 5º ano) com pelo menos um aluno aferido na matéria.
 *
 * O turno global vai para a API (`?turno=`), que recorta e renumera. Só gestão
 * (coordenador/admin/global) vê esta categoria — o professor enxerga só o
 * ranking de alunos. O selo de frescor diz de quando é o dado.
 *
 * Identidade visual v2 (referência "Desempenho por turma" da Visão Geral): posição
 * em pílula com as cores de medalha, barra da média (0–100) e barra da adoção
 * (aferidos ÷ alunos da turma) — ambas com o número ao lado; as barras são só
 * reforço visual. A da média leva a cor da matéria; a dos aferidos é neutra
 * (ardósia): o âmbar é da premiação e o ouro-400 claro não tinha 3:1 no branco.
 *
 * Celular (< 640 px): a MÉDIA (o que ordena) fica presa à direita da tabela que rola,
 * só com o número (a barra é reforço visual e sai nessa largura); a coluna Série sai
 * quando TODA turma já traz a série no nome ("3º Ano A" × "3º Ano"), para caberem
 * posição, turma, turno e média sem rolar. No desktop nada muda.
 */
import { BookOpen, Calculator, LayoutGrid } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import {
  AcoesRanking,
  BarraFiltrosRanking,
  CabecalhoCartao,
  DescricaoRanking,
  EsqueletoRanking,
  PosicaoRanking,
  tabelaRanking as t,
} from "../components/RankingUi";
import { SeloFrescor, type Frescor } from "../components/SeloFrescor";
import { MolduraPilula, estiloSelectPilula } from "../components/SeletorPilula";
import { SeletorTurno } from "../components/SeletorTurno";
import { TabelaRolavel } from "../components/TabelaRolavel";
import { BarraProgresso, Card, Chip, Erro, PageHeader, Vazio } from "../components/ui";
import { useApp } from "../context/AppContext";
import { useApi } from "../hooks/useApi";
import { useModulos } from "../hooks/useModulos";
import { usePerfil } from "../hooks/usePerfil";
import { nomeArquivoCsv, type TabelaCsv } from "../lib/csvRanking";
import { nota, numero } from "../lib/formato";
import { TURNO_SEM, TURNO_TODOS, aplicarTurno, rotuloTurno, turnoEfetivo } from "../lib/turnos";
import type { Dimensao, Turma } from "../lib/types";

// Forma de `routers/rankings.py::ranking_turmas` (só o que a tela lê).
interface TurmaRanqueada {
  posicao: number;
  turma_id: number;
  nome: string;
  ano_escolar: string;
  turno: string | null;
  media: number;
  n_aferidos: number;
  total_alunos: number;
}
/** Só para a Secretaria: turma fora da ordem para proteger as crianças (menos de 3
 *  alunos com dado, ou o complemento que protege outra turma). Sem posição nem média. */
interface TurmaOculta {
  turma_id: number;
  nome: string;
  ano_escolar: string;
  motivo: "grupo_pequeno" | "complementar";
  texto: string;
}
interface RankingTurmasResposta {
  dimensao: Dimensao;
  itens: TurmaRanqueada[];
  frescor: Frescor;
  ocultas?: TurmaOculta[];
}

/** Turmas que a Secretaria não vê no ranking, com o motivo (nunca uma posição inventada). */
function TurmasProtegidas({ ocultas, materia }: { ocultas: TurmaOculta[]; materia: string }) {
  return (
    <div className="border-t border-zinc-100 px-5 py-4 dark:border-zinc-800 sm:px-6">
      <p className="text-sm font-semibold text-zinc-800 dark:text-zinc-100">Fora do ranking para proteger as crianças</p>
      <p className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">
        Turmas com menos de 3 alunos com dado em {materia} (ou só 1 ou 2 com resultado acima de zero, ou cujo
        número permitiria descobrir o de outra turma assim) não recebem posição nem média.
      </p>
      <ul className="mt-2.5 flex flex-wrap gap-2" aria-label="Turmas protegidas">
        {ocultas.map((o) => (
          <li key={o.turma_id} title={o.texto}>
            <Chip>{o.nome}</Chip>
            <span className="sr-only">: {o.texto}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * Barra da adoção (aferidos ÷ alunos), em ardósia (#64748B, a "meta" da paleta D22):
 * 4,8:1 no branco e > 3:1 sobre a trilha. Só reforço visual: o "N de M" vai ao lado.
 */
function BarraAferidos({ valor }: { valor: number }) {
  const largura = Math.max(0, Math.min(100, valor));
  return (
    <span aria-hidden className="block h-2 w-full flex-1 overflow-hidden rounded-full bg-zinc-100 dark:bg-zinc-800">
      <span className="block h-full rounded-full bg-slate-500 dark:bg-slate-400" style={{ width: `${largura}%` }} />
    </span>
  );
}

/** Texto comparável: sem acento, minúsculo, "º"/"°" como "o", espaços simples. */
const comparavel = (texto: string) =>
  texto.normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/[º°]/g, "o")
    .toLowerCase().replace(/\s+/g, " ").trim();

/** A série já aparece no nome da turma ("3º Ano A" traz "3º Ano")? Como palavra inteira:
 *  "1º Ano" não está em "11º Ano A", nem a série "3" em "Turma 13". */
function serieEstaNoNome(nome: string, serie: string | null | undefined): boolean {
  const s = comparavel(serie ?? "");
  if (s === "") return false;
  const escapada = s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return new RegExp(`(^|[^a-z0-9])${escapada}($|[^a-z0-9])`).test(comparavel(nome));
}

const MATERIAS: { chave: Dimensao; rotulo: string }[] = [
  { chave: "leitura", rotulo: "Leitura" },
  { chave: "matematica", rotulo: "Matemática" },
];

export default function RankingTurmas({ embutido = false, alvoAcoes }: {
  embutido?: boolean;
  /** Espaço de ações do cabeçalho da tela Ranking (os botões vão para lá). */
  alvoAcoes?: HTMLElement | null;
} = {}) {
  const { escolaId, turno, definirTurno } = useApp();
  const { secretaria } = usePerfil();
  // Matéria só existe para quem contratou o módulo (SaaS).
  const { tem } = useModulos();
  const materias = MATERIAS.filter((m) => tem(m.chave));
  const [materiaSel, setMateriaSel] = useState<Dimensao | null>(null);
  const materia: Dimensao | null =
    materiaSel && materias.some((m) => m.chave === materiaSel)
      ? materiaSel
      : materias[0]?.chave ?? null;
  const rotuloMateria = MATERIAS.find((m) => m.chave === materia)?.rotulo ?? "";

  const { dados: turmas } = useApi<Turma[]>(
    escolaId ? `/escolas/${escolaId}/turmas` : null, { cacheMs: 60_000 });
  const turnoAtivo = turnoEfetivo(turno, turmas);
  const parametros = new URLSearchParams();
  if (materia) parametros.set("dimensao", materia);
  aplicarTurno(parametros, turnoAtivo);
  const { dados: ranking, erro, carregando, recarregar } = useApi<RankingTurmasResposta>(
    escolaId && materia ? `/escolas/${escolaId}/ranking/turmas?${parametros}` : null,
  );
  // A ordem e a posição são as da API — nada é reordenado aqui.
  const linhas = ranking?.itens ?? [];
  const ocultas = ranking?.ocultas ?? [];
  const tom = materia === "matematica" ? "teal" : "violeta";
  // Série repetida no nome de TODAS as turmas: no celular a coluna sai (nenhum dado
  // some — está no nome). Basta uma turma sem a série no nome para a coluna ficar.
  const ocultarSerie = linhas.length > 0 && linhas.every((l) => serieEstaNoNome(l.nome, l.ano_escolar))
    ? "max-sm:hidden" : "";

  const recorteTurno = turnoAtivo !== TURNO_TODOS
    ? (turnoAtivo === TURNO_SEM ? "turmas sem turno" : rotuloTurno(turnoAtivo)) : "";
  const csv: TabelaCsv | null = !materia || carregando || erro || linhas.length === 0 ? null : {
    nomeArquivo: nomeArquivoCsv(`ranking-turmas-${rotuloMateria}${recorteTurno ? `-${recorteTurno}` : ""}`),
    cabecalho: ["Posição", "Turma", "Série", "Turno", `Média de ${rotuloMateria}`, "Alunos aferidos", "Alunos da turma"],
    linhas: linhas.map((l) => [
      l.posicao, l.nome, l.ano_escolar, rotuloTurno(l.turno), nota(l.media), l.n_aferidos, l.total_alunos,
    ]),
  };

  // Ranking de turmas não tem lote de certificados (é de aluno): só exportar.
  const acoes = <AcoesRanking alvo={alvoAcoes} embutido={embutido} csv={csv} />;

  return (
    <div>
      {embutido ? acoes : (
        <PageHeader
          titulo="Ranking de Turmas"
          descricao={<DescricaoRanking periodo="Ano letivo · média das notas oficiais" dimensoes={materia ? [materia] : []} />}
          acoes={acoes}
        />
      )}

      <BarraFiltrosRanking>
        {materias.length > 1 && (
          <MolduraPilula icone={materia === "matematica" ? Calculator : BookOpen}>
            <select
              aria-label="Matéria"
              className={estiloSelectPilula}
              value={materia ?? ""}
              onChange={(e) => setMateriaSel(e.target.value as Dimensao)}
            >
              {materias.map((m) => <option key={m.chave} value={m.chave}>{m.rotulo}</option>)}
            </select>
          </MolduraPilula>
        )}
        <SeletorTurno turmas={turmas ?? []} valor={turno} onChange={definirTurno} />
      </BarraFiltrosRanking>

      {materia && <SeloFrescor frescor={ranking?.frescor} dimensoes={[materia]} />}

      <Card className="overflow-hidden">
        <CabecalhoCartao
          icone={LayoutGrid}
          tom={tom}
          titulo={materia ? `Desempenho por turma · ${rotuloMateria}` : "Desempenho por turma"}
          subtitulo={
            <>
              Média das notas oficiais (0–100) dos alunos aferidos em {rotuloMateria};
              só entram turmas do 1º ao 5º ano com pelo menos um aluno aferido.
            </>
          }
        />
        {!materia ? (
          <Vazio icone={LayoutGrid} titulo="Nenhuma matéria contratada" descricao="O ranking de turmas depende de um módulo de Leitura ou Matemática." />
        ) : carregando ? (
          <EsqueletoRanking podio={false} />
        ) : erro ? (
          <Erro titulo="Não foi possível carregar" descricao={erro.message} aoTentar={recarregar} />
        ) : linhas.length === 0 && ocultas.length > 0 ? (
          <TurmasProtegidas ocultas={ocultas} materia={rotuloMateria} />
        ) : linhas.length === 0 ? (
          <Vazio icone={LayoutGrid} titulo={`Nenhuma turma com alunos aferidos em ${rotuloMateria}`}
                 descricao="Importe ou sincronize os dados da plataforma; turmas sem nenhum aluno medido não entram." />
        ) : null}
        {materia && !carregando && !erro && linhas.length > 0 && (
          <TabelaRolavel rotulo={`Desempenho por turma · ${rotuloMateria}: tabela completa`}>
            <table className="w-full text-sm tabular-nums sm:min-w-[680px]">
              <thead className={t.thead}>
                <tr>
                  <th scope="col" className={t.th}>Posição</th>
                  <th scope="col" className={t.th}>Turma</th>
                  <th scope="col" className={`${t.th} ${ocultarSerie}`}>Série</th>
                  <th scope="col" className={t.th}>Turno</th>
                  <th scope="col" className={`${t.th} ${t.thPresa} ${t.thQuebraCelular}`}>Média de {rotuloMateria}</th>
                  <th scope="col" className={t.th}>Alunos aferidos</th>
                </tr>
              </thead>
              <tbody>
                {linhas.map((l) => (
                  <tr key={l.turma_id} className={t.tr}>
                    <td className={t.td}><PosicaoRanking posicao={l.posicao} /></td>
                    {/* Turma, série e turno numa linha só ("2º Ano A", não "2º Ano / A"); as
                        barras abrem mão de largura antes desses rótulos curtos. */}
                    <td className={t.tdCurto}>
                      {/* A Secretaria vê só o agregado: o detalhe da turma (alunos nominais) é
                          bloqueado para ela, então o nome não vira link. */}
                      {secretaria ? (
                        <span className="font-semibold text-zinc-900 dark:text-zinc-100">{l.nome}</span>
                      ) : (
                        <Link
                          to={`/turmas/${l.turma_id}`}
                          className="font-semibold text-zinc-900 hover:text-indigo-700 hover:underline dark:text-zinc-100 dark:hover:text-indigo-300"
                        >
                          {l.nome}
                        </Link>
                      )}
                    </td>
                    <td className={`${t.tdCurto} text-zinc-500 dark:text-zinc-400 ${ocultarSerie}`}>{l.ano_escolar}</td>
                    <td className={t.tdCurto}><Chip>{rotuloTurno(l.turno)}</Chip></td>
                    <td className={`${t.td} ${t.tdPresa}`}>
                      <span className="flex items-center gap-3 sm:min-w-[8rem]">
                        <BarraProgresso valor={l.media} tom={tom} className="flex-1 max-sm:hidden" />
                        <span className="w-12 text-right text-[15px] font-bold text-zinc-900 dark:text-white">{nota(l.media)}</span>
                      </span>
                    </td>
                    <td className={t.td}>
                      <span className="flex min-w-[8rem] items-center gap-3">
                        <BarraAferidos valor={l.total_alunos > 0 ? (l.n_aferidos / l.total_alunos) * 100 : 0} />
                        <span className="whitespace-nowrap text-right text-zinc-600 dark:text-zinc-300">
                          {numero(l.n_aferidos)} de {numero(l.total_alunos)}
                        </span>
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TabelaRolavel>
        )}
        {materia && !carregando && !erro && linhas.length > 0 && ocultas.length > 0 && (
          <TurmasProtegidas ocultas={ocultas} materia={rotuloMateria} />
        )}
      </Card>
    </div>
  );
}
