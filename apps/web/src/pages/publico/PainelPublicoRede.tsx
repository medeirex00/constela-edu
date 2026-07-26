/**
 * Vitrine PÚBLICA da Secretaria (sem login) — as MELHORES ESCOLAS da rede em
 * leitura e matemática. Feita para telão/link aberto: sem nenhum dado de criança,
 * só escolas + a métrica. Decisão de produto do dono (top 5 escolas, não alunos).
 */
import { BookOpen, Calculator } from "lucide-react";
import { useParams } from "react-router-dom";

import { Carregando } from "../../components/ui";
import { useApi } from "../../hooks/useApi";
import { nota } from "../../lib/formato";

interface TopEscola { nome: string; valor: number }
interface PainelPublico { rede_nome: string; top_leitura: TopEscola[]; top_matematica: TopEscola[] }

const MEDALHA = ["🥇", "🥈", "🥉"];

function Coluna({ titulo, icone, escolas }: {
  titulo: string; icone: React.ReactNode; escolas: TopEscola[];
}) {
  return (
    <div className="flex-1 rounded-2xl border border-zinc-200 bg-white p-6 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
      <h2 className="mb-4 flex items-center justify-center gap-2 text-xl font-bold text-indigo-700 dark:text-indigo-300">
        {icone} {titulo}
      </h2>
      {escolas.length === 0 ? (
        <p className="py-6 text-center text-sm text-zinc-500">Sem dados ainda.</p>
      ) : (
        <ol className="space-y-2">
          {escolas.map((e, i) => (
            <li key={e.nome}
                className={`flex items-center gap-3 rounded-xl px-4 py-3 ${
                  i < 3 ? "bg-amber-50 dark:bg-amber-500/10" : "bg-zinc-50 dark:bg-zinc-800/50"}`}>
              <span className="w-8 text-center text-xl font-bold tabular-nums">
                {i < 3 ? MEDALHA[i] : `${i + 1}º`}
              </span>
              <span className="flex-1 truncate text-base font-semibold">{e.nome}</span>
              <span className="text-lg font-bold tabular-nums text-indigo-600 dark:text-indigo-400">
                {nota(e.valor)}
              </span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

export default function PainelPublicoRede() {
  const { token } = useParams<{ token: string }>();
  const { dados, erro, carregando } = useApi<PainelPublico>(
    token ? `/publico/rede/${token}` : null);

  if (carregando && !dados) return <Carregando texto="Carregando o painel..." />;
  if (erro || !dados) {
    return (
      <div className="flex min-h-screen items-center justify-center p-8 text-center">
        <p className="text-lg text-zinc-500">
          Painel público não encontrado ou desativado.
        </p>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gradient-to-b from-indigo-50 to-white px-4 py-10 dark:from-zinc-950 dark:to-zinc-900">
      <div className="mx-auto max-w-4xl">
        <header className="mb-8 text-center">
          <p className="text-sm font-semibold uppercase tracking-widest text-indigo-500">
            Secretaria de Educação
          </p>
          <h1 className="mt-1 text-3xl font-extrabold text-zinc-800 dark:text-zinc-100">
            {dados.rede_nome}
          </h1>
          <p className="mt-2 text-zinc-500">Escolas em destaque da nossa rede</p>
        </header>

        <div className="flex flex-col gap-6 md:flex-row">
          <Coluna titulo="Leitura" icone={<BookOpen size={22} />} escolas={dados.top_leitura} />
          <Coluna titulo="Matemática" icone={<Calculator size={22} />} escolas={dados.top_matematica} />
        </div>

        <footer className="mt-10 text-center text-xs text-zinc-400">
          Constela Edu — celebrando o esforço de cada escola. Sem dados individuais de estudantes.
        </footer>
      </div>
    </div>
  );
}
