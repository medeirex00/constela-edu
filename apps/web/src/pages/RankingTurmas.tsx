/**
 * Ranking de TURMAS — as turmas da escola ordenadas pela MÉDIA das notas
 * oficiais (0–100) dos alunos aferidos numa matéria (Leitura ou Matemática).
 *
 * Fonte: `GET /escolas/{id}/resumo-escola` (a mesma visão por turma de "Visão
 * da Escola"): cada turma traz `media_leitura`/`n_leitura` e `media_matematica`/
 * `n_matematica`, já calculadas SÓ sobre quem tem dado da plataforma — quem não
 * tem dado não entra como zero. A ordenação é feita aqui, no cliente, e só
 * entram turmas com pelo menos um aluno aferido na matéria escolhida (uma turma
 * sem ninguém medido não tem média para competir).
 *
 * Nenhum cálculo novo: é a média que o backend já devolve, posta em ordem.
 * O turno global filtra as turmas (`Turma.turno`, via o cadastro de turmas —
 * o resumo não traz o turno). Só gestão (coordenador/admin/global) vê esta
 * categoria — o professor enxerga só o ranking de alunos.
 */
import { Users } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { SeletorTurno } from "../components/SeletorTurno";
import { Badge, Botao, Card, Carregando, PageHeader, Vazio, estiloInput } from "../components/ui";
import { useApp } from "../context/AppContext";
import { useApi } from "../hooks/useApi";
import { useModulos } from "../hooks/useModulos";
import { nota, numero } from "../lib/formato";
import { TURNO_TODOS, chaveTurno, rotuloTurno, turnoEfetivo } from "../lib/turnos";
import type { Dimensao, Turma } from "../lib/types";

// Forma real de `services/evolucao.py::_monta_resumo_turma` (só o que a tela lê).
interface ResumoTurma {
  turma: { id: number; nome: string; ano_escolar: string };
  total_alunos: number;
  media_leitura?: number;
  n_leitura?: number;
  media_matematica?: number;
  n_matematica?: number;
  // Chaves históricas (mesmos números das acima, mantidas por compatibilidade).
  media_elefante?: number;
  media_matific?: number;
}
interface ResumoEscola {
  escola: { id: number; nome: string };
  turmas: ResumoTurma[];
}

const MATERIAS: { chave: Dimensao; rotulo: string }[] = [
  { chave: "leitura", rotulo: "Leitura" },
  { chave: "matematica", rotulo: "Matemática" },
];

function mediaDa(t: ResumoTurma, materia: Dimensao): number {
  return materia === "leitura"
    ? (t.media_leitura ?? t.media_elefante ?? 0)
    : (t.media_matematica ?? t.media_matific ?? 0);
}
function aferidosDa(t: ResumoTurma, materia: Dimensao): number {
  return (materia === "leitura" ? t.n_leitura : t.n_matematica) ?? 0;
}

export default function RankingTurmas({ embutido = false }: { embutido?: boolean } = {}) {
  const { escolaId, turno, definirTurno } = useApp();
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
  const { dados: resumo, erro, carregando, recarregar } = useApi<ResumoEscola>(
    escolaId ? `/escolas/${escolaId}/resumo-escola` : null,
  );
  const turnoAtivo = turnoEfetivo(turno, turmas);

  // id da turma → turno (o resumo não traz o turno; o cadastro traz).
  const turnoPorId = useMemo(() => {
    const mapa = new Map<number, string | null>();
    (turmas ?? []).forEach((t) => mapa.set(t.id, t.turno));
    return mapa;
  }, [turmas]);

  const linhas = useMemo(() => {
    if (!resumo || !materia) return [];
    return resumo.turmas
      .filter((t) => aferidosDa(t, materia) > 0)
      // Só filtra por turno com o cadastro carregado (sem ele não há como saber
      // o turno de cada turma; melhor mostrar todas do que esconder tudo).
      .filter((t) => turnoAtivo === TURNO_TODOS || !turmas
        || chaveTurno(turnoPorId.get(t.turma.id)) === turnoAtivo)
      .sort((a, b) =>
        mediaDa(b, materia) - mediaDa(a, materia)
        || aferidosDa(b, materia) - aferidosDa(a, materia)
        || a.turma.nome.localeCompare(b.turma.nome))
      .map((t, i) => ({
        posicao: i + 1,
        id: t.turma.id,
        nome: t.turma.nome,
        serie: t.turma.ano_escolar,
        turno: turnoPorId.get(t.turma.id) ?? null,
        media: mediaDa(t, materia),
        aferidos: aferidosDa(t, materia),
        total: t.total_alunos,
      }));
  }, [resumo, materia, turnoAtivo, turmas, turnoPorId]);

  return (
    <div>
      {!embutido && (
        <PageHeader
          titulo="Ranking de Turmas"
          descricao="Turmas ordenadas pela média das notas oficiais dos alunos aferidos em cada matéria."
        />
      )}

      <Card className="mb-4 flex flex-wrap items-center gap-3 p-4">
        {materias.length > 1 && (
          <select
            aria-label="Matéria"
            className={`${estiloInput} w-auto`}
            value={materia ?? ""}
            onChange={(e) => setMateriaSel(e.target.value as Dimensao)}
          >
            {materias.map((m) => <option key={m.chave} value={m.chave}>{m.rotulo}</option>)}
          </select>
        )}
        <SeletorTurno turmas={turmas ?? []} valor={turno} onChange={definirTurno} />
        <span className="inline-flex items-center gap-1.5 text-xs text-zinc-500 dark:text-zinc-400">
          <Users size={13} /> Média das notas oficiais (0–100) dos alunos aferidos em {rotuloMateria};
          só entram turmas com pelo menos um aluno aferido.
        </span>
      </Card>

      <Card>
        {!materia ? (
          <Vazio titulo="Nenhuma matéria contratada" descricao="O ranking de turmas depende de um módulo de Leitura ou Matemática." />
        ) : carregando ? (
          <Carregando />
        ) : erro ? (
          <Vazio titulo="Não foi possível carregar" descricao={erro.message}
                 acao={<Botao variante="neutro" onClick={recarregar}>Tentar de novo</Botao>} />
        ) : linhas.length === 0 ? (
          <Vazio titulo={`Nenhuma turma com alunos aferidos em ${rotuloMateria}`}
                 descricao="Importe ou sincronize os dados da plataforma; turmas sem nenhum aluno medido não entram." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm tabular-nums">
              <thead>
                <tr className="border-b border-zinc-200 text-left text-xs uppercase tracking-wide text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
                  <th className="px-4 py-2 font-medium">Posição</th>
                  <th className="px-4 py-2 font-medium">Turma</th>
                  <th className="hidden px-4 py-2 font-medium sm:table-cell">Série</th>
                  <th className="hidden px-4 py-2 font-medium sm:table-cell">Turno</th>
                  <th className="px-4 py-2 text-right font-medium">Média de {rotuloMateria}</th>
                  <th className="px-4 py-2 text-right font-medium">Alunos aferidos</th>
                </tr>
              </thead>
              <tbody>
                {linhas.map((l) => (
                  <tr key={l.id} className="border-b border-zinc-100 last:border-0 dark:border-zinc-800/60">
                    <td className="px-4 py-2.5">
                      {l.posicao <= 3 ? <Badge tom="destaque">{l.posicao}º</Badge> : `${l.posicao}º`}
                    </td>
                    <td className="px-4 py-2.5">
                      <Link to={`/turmas/${l.id}`} className="font-medium hover:text-indigo-600 dark:hover:text-indigo-400">
                        {l.nome}
                      </Link>
                    </td>
                    <td className="hidden px-4 py-2.5 text-zinc-500 dark:text-zinc-400 sm:table-cell">{l.serie}</td>
                    <td className="hidden px-4 py-2.5 text-zinc-500 dark:text-zinc-400 sm:table-cell">
                      {turmas ? rotuloTurno(l.turno) : "—"}
                    </td>
                    <td className="px-4 py-2.5 text-right font-semibold">{nota(l.media)}</td>
                    <td className="px-4 py-2.5 text-right text-zinc-500 dark:text-zinc-400">
                      {numero(l.aferidos)} de {numero(l.total)}
                    </td>
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
