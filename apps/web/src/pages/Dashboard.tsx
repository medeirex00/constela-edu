import {
  BookOpen,
  Calculator,
  Clock3,
  GraduationCap,
  School,
  Star,
  Users,
} from "lucide-react";
import { Link } from "react-router-dom";

import { Badge, Card, Carregando, StatCard, Vazio } from "../components/ui";
import { useApp } from "../context/AppContext";
import { useApi } from "../hooks/useApi";
import { nota, numero, tempoLeitura } from "../lib/formato";
import type { Dashboard as DadosDashboard } from "../lib/types";

export default function Dashboard() {
  const { escolaId, escolas, selecionarEscola } = useApp();
  const { dados, erro, carregando } = useApi<DadosDashboard>(
    escolaId ? `/escolas/${escolaId}/dashboard` : null);

  return (
    <div className="space-y-6">
      {/* Cartão centralizado ESCOLA — troca todos os dados do sistema (PRD §20, §48) */}
      <Card className="mx-auto max-w-md p-5 text-center">
        <p className="text-xs font-semibold uppercase tracking-widest text-zinc-500 dark:text-zinc-400">
          Escola
        </p>
        <select
          aria-label="Selecionar escola"
          className="mt-2 w-full rounded-lg border border-zinc-300 bg-white px-3 py-2.5 text-center text-base font-semibold dark:border-zinc-700 dark:bg-zinc-950"
          value={escolaId ?? ""}
          onChange={(evento) => selecionarEscola(Number(evento.target.value))}
        >
          {escolas.map((escola) => (
            <option key={escola.id} value={escola.id}>
              {escola.nome}
            </option>
          ))}
        </select>
        {dados && (
          <p className="mt-2 text-xs text-zinc-500 dark:text-zinc-400">
            Ano letivo {dados.escola.ano_letivo_ativo}
          </p>
        )}
      </Card>

      {carregando && <Carregando texto="Atualizando indicadores..." />}

      {!carregando && erro && (
        <Vazio titulo="Não foi possível carregar os indicadores" descricao={erro.message} />
      )}

      {!carregando && dados && (
        <>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
            <StatCard icone={<GraduationCap size={15} />} rotulo="Alunos" valor={numero(dados.total_alunos)} />
            <StatCard icone={<Users size={15} />} rotulo="Turmas" valor={numero(dados.total_turmas)} />
            <StatCard icone={<School size={15} />} rotulo="Professores" valor={numero(dados.total_professores)} />
            <StatCard icone={<Star size={15} />} rotulo="Média geral" valor={nota(dados.media_geral)} detalhe="escala 0–100" />
            <StatCard icone={<Calculator size={15} />} rotulo="Atividades Matific" valor={numero(dados.total_atividades)} />
            <StatCard icone={<BookOpen size={15} />} rotulo="Livros lidos" valor={numero(dados.total_livros)} detalhe="títulos únicos" />
            <StatCard icone={<Clock3 size={15} />} rotulo="Tempo de leitura" valor={tempoLeitura(dados.tempo_leitura_min)} />
          </div>

          <Card>
            <div className="flex items-center justify-between border-b border-zinc-200 px-4 py-3 dark:border-zinc-800">
              <h2 className="text-sm font-semibold">Top 10 — Ranking Geral</h2>
              <Link to="/ranking" className="text-sm font-medium text-indigo-600 hover:underline dark:text-indigo-400">
                Ver ranking completo
              </Link>
            </div>
            {dados.top10.length === 0 ? (
              <Vazio
                titulo="Ainda não há notas calculadas"
                descricao="Importe dados das plataformas ou cadastre alunos para começar."
              />
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm tabular-nums">
                  <thead>
                    <tr className="border-b border-zinc-200 text-left text-xs uppercase tracking-wide text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
                      <th className="px-4 py-2 font-medium">#</th>
                      <th className="px-4 py-2 font-medium">Aluno</th>
                      <th className="hidden px-4 py-2 font-medium sm:table-cell">Turma</th>
                      <th className="px-4 py-2 text-right font-medium">Nota geral</th>
                    </tr>
                  </thead>
                  <tbody>
                    {dados.top10.map((item) => (
                      <tr key={item.aluno_id} className="border-b border-zinc-100 last:border-0 dark:border-zinc-800/60">
                        <td className="px-4 py-2.5">
                          {item.posicao <= 3 ? <Badge tom="destaque">{item.posicao}º</Badge> : `${item.posicao}º`}
                        </td>
                        <td className="px-4 py-2.5">
                          <Link to={`/alunos/${item.aluno_id}`} className="font-medium hover:text-indigo-600 dark:hover:text-indigo-400">
                            {item.nome}
                          </Link>
                        </td>
                        <td className="hidden px-4 py-2.5 text-zinc-500 dark:text-zinc-400 sm:table-cell">{item.turma}</td>
                        <td className="px-4 py-2.5 text-right font-semibold">{nota(item.nota_geral)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        </>
      )}
    </div>
  );
}
