/** Gamificação (PRD §64, §79–§84): mural, destaques e ranking de XP. */
import { Flame, Medal, Sparkles } from "lucide-react";
import { Link } from "react-router-dom";

import { Badge, Card, Carregando, PageHeader, Vazio } from "../components/ui";
import { useApp } from "../context/AppContext";
import { useApi } from "../hooks/useApi";
import { dataHora, nota, numero } from "../lib/formato";

interface Destaque {
  aluno_id: number;
  nome: string;
  turma: string;
  nota_evolucao: number;
  ganhos: Record<string, number>;
}

interface Mural {
  destaques: { dia: Destaque | null; semana: Destaque | null; mes: Destaque | null };
  eventos: { tipo: string; icone: string; texto: string; data: string }[];
}

interface ItemXp {
  posicao: number;
  aluno_id: number;
  nome: string;
  turma: string;
  xp: number;
  nivel: number;
  conquistas: number;
}

function CartaoDestaque({ titulo, destaque }: { titulo: string; destaque: Destaque | null }) {
  return (
    <Card className="p-4">
      <p className="text-xs font-medium uppercase tracking-wide text-zinc-500 dark:text-zinc-400">{titulo}</p>
      {destaque ? (
        <div className="mt-2">
          <Link
            to={`/alunos/${destaque.aluno_id}/evolucao`}
            className="text-lg font-semibold hover:text-indigo-600 dark:hover:text-indigo-400"
          >
            {destaque.nome}
          </Link>
          <p className="text-xs text-zinc-500 dark:text-zinc-400">{destaque.turma}</p>
          <p className="mt-1 text-sm tabular-nums text-emerald-600 dark:text-emerald-400">
            evolução {nota(destaque.nota_evolucao)}
          </p>
        </div>
      ) : (
        <p className="mt-2 text-sm text-zinc-400">Sem destaque no período.</p>
      )}
    </Card>
  );
}

export default function Conquistas() {
  const { escolaId } = useApp();
  const {
    dados: mural,
    erro: erroMural,
    carregando: carregandoMural,
  } = useApi<Mural>(escolaId ? `/escolas/${escolaId}/gamificacao/mural` : null);
  const {
    dados: rankingXp,
    erro: erroRanking,
    carregando: carregandoRanking,
  } = useApi<ItemXp[]>(escolaId ? `/escolas/${escolaId}/gamificacao/ranking-xp` : null);

  return (
    <div className="space-y-6">
      <PageHeader
        titulo="Conquistas e Mural"
        descricao="Destaques, medalhas e XP — tudo derivado dos dados reais e recalculado automaticamente."
        acoes={
          <Link
            to="/conquistas/biblioteca"
            className="inline-flex items-center justify-center gap-2 rounded-lg bg-indigo-600 px-3.5 py-2 text-sm font-medium text-white transition-colors hover:bg-indigo-500"
          >
            🏅 Biblioteca de Conquistas
          </Link>
        }
      />

      <div className="grid gap-3 sm:grid-cols-3">
        <CartaoDestaque titulo="🌟 Aluno do Dia" destaque={mural?.destaques.dia ?? null} />
        <CartaoDestaque titulo="🏅 Aluno da Semana" destaque={mural?.destaques.semana ?? null} />
        <CartaoDestaque titulo="🏆 Aluno do Mês" destaque={mural?.destaques.mes ?? null} />
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <div className="flex items-center gap-2 border-b border-zinc-200 px-4 py-3 dark:border-zinc-800">
            <Sparkles size={15} className="text-indigo-500" />
            <h3 className="text-sm font-semibold">Mural da escola</h3>
          </div>
          {carregandoMural ? (
            <Carregando />
          ) : erroMural ? (
            <Vazio titulo="Não foi possível carregar" descricao={erroMural.message} />
          ) : !mural || mural.eventos.length === 0 ? (
            <Vazio titulo="Nada por aqui ainda" descricao="Importe dados para movimentar o mural." />
          ) : (
            <ul className="divide-y divide-zinc-100 dark:divide-zinc-800/60">
              {mural.eventos.map((evento, indice) => (
                <li key={indice} className="flex items-start gap-3 px-4 py-3">
                  <span className="text-lg leading-none">{evento.icone}</span>
                  <div>
                    <p className="text-sm">{evento.texto}</p>
                    <p className="text-xs text-zinc-400">{dataHora(evento.data)}</p>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card>
          <div className="flex items-center gap-2 border-b border-zinc-200 px-4 py-3 dark:border-zinc-800">
            <Flame size={15} className="text-amber-500" />
            <h3 className="text-sm font-semibold">Ranking de XP</h3>
          </div>
          {carregandoRanking ? (
            <Carregando />
          ) : erroRanking ? (
            <Vazio titulo="Não foi possível carregar" descricao={erroRanking.message} />
          ) : (rankingXp ?? []).length === 0 ? (
            <Vazio titulo="Nenhum aluno com XP" />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm tabular-nums">
                <thead>
                  <tr className="border-b border-zinc-200 text-left text-xs uppercase tracking-wide text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
                    <th className="px-4 py-2 font-medium">#</th>
                    <th className="px-4 py-2 font-medium">Aluno</th>
                    <th className="px-4 py-2 text-right font-medium">Nível</th>
                    <th className="px-4 py-2 text-right font-medium">XP</th>
                    <th className="px-4 py-2 text-right font-medium">
                      <Medal size={13} className="inline" />
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {(rankingXp ?? []).map((item) => (
                    <tr key={item.aluno_id} className="border-b border-zinc-100 last:border-0 dark:border-zinc-800/60">
                      <td className="px-4 py-2.5">
                        {item.posicao <= 3 ? <Badge tom="alerta">{item.posicao}º</Badge> : `${item.posicao}º`}
                      </td>
                      <td className="px-4 py-2.5">
                        <Link to={`/alunos/${item.aluno_id}`} className="font-medium hover:text-indigo-600 dark:hover:text-indigo-400">
                          {item.nome}
                        </Link>
                        <span className="ml-2 text-xs text-zinc-400">{item.turma}</span>
                      </td>
                      <td className="px-4 py-2.5 text-right">
                        <Badge tom="destaque">Nv {item.nivel}</Badge>
                      </td>
                      <td className="px-4 py-2.5 text-right font-semibold">{numero(item.xp)}</td>
                      <td className="px-4 py-2.5 text-right">{item.conquistas}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
