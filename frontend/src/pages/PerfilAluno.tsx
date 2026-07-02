import { ArrowLeft, TrendingUp } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { Badge, Card, Carregando, Vazio } from "../components/ui";
import { useApp } from "../context/AppContext";
import { api } from "../lib/api";
import { nota } from "../lib/formato";
import type { LinhaCalculo, PerfilAluno as Perfil } from "../lib/types";

function TabelaCalculo({ titulo, linhas, notaFinal }: { titulo: string; linhas: LinhaCalculo[]; notaFinal: number }) {
  return (
    <Card>
      <div className="flex items-center justify-between border-b border-zinc-200 px-4 py-3 dark:border-zinc-800">
        <h3 className="text-sm font-semibold">{titulo}</h3>
        <span className="text-sm font-semibold tabular-nums">{nota(notaFinal)}</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm tabular-nums">
          <thead>
            <tr className="border-b border-zinc-200 text-left text-xs uppercase tracking-wide text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
              <th className="px-4 py-2 font-medium">Indicador</th>
              <th className="px-4 py-2 text-right font-medium">Valor</th>
              <th className="px-4 py-2 text-right font-medium">Referência</th>
              <th className="px-4 py-2 text-right font-medium">Normalizado</th>
              <th className="px-4 py-2 text-right font-medium">Peso</th>
              <th className="px-4 py-2 text-right font-medium">Contribuição</th>
            </tr>
          </thead>
          <tbody>
            {linhas.map((linha) => (
              <tr key={linha.indicador} className="border-b border-zinc-100 last:border-0 dark:border-zinc-800/60">
                <td className="px-4 py-2.5">{linha.indicador}</td>
                <td className="px-4 py-2.5 text-right">{nota(linha.valor)}</td>
                <td className="px-4 py-2.5 text-right text-zinc-500 dark:text-zinc-400">{nota(linha.referencia)}</td>
                <td className="px-4 py-2.5 text-right">{nota(linha.normalizado)}</td>
                <td className="px-4 py-2.5 text-right text-zinc-500 dark:text-zinc-400">{linha.peso}%</td>
                <td className="px-4 py-2.5 text-right font-medium">{nota(linha.contribuicao)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

export default function PerfilAluno() {
  const { id } = useParams();
  const { escolaId } = useApp();
  const [perfil, setPerfil] = useState<Perfil | null>(null);
  const [carregando, setCarregando] = useState(true);

  useEffect(() => {
    if (!escolaId || !id) return;
    setCarregando(true);
    api<Perfil>(`/escolas/${escolaId}/alunos/${id}/perfil`)
      .then(setPerfil)
      .catch(() => setPerfil(null))
      .finally(() => setCarregando(false));
  }, [escolaId, id]);

  if (carregando) return <Carregando />;
  if (!perfil) return <Vazio titulo="Aluno não encontrado" />;

  const { aluno, detalhes } = perfil;
  const pesosGerais = detalhes.geral?.pesos ?? {};

  return (
    <div className="space-y-6">
      <div>
        <Link to="/alunos" className="mb-3 inline-flex items-center gap-1.5 text-sm text-zinc-500 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100">
          <ArrowLeft size={15} /> Alunos
        </Link>
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-xl font-semibold tracking-tight">{aluno.nome}</h1>
          {perfil.posicao && <Badge tom="destaque">{perfil.posicao}º no ranking</Badge>}
          {detalhes.modo_normalizacao && (
            <Badge>Normalização: {detalhes.modo_normalizacao === "auto" ? "automática" : "manual"}</Badge>
          )}
          <Link
            to={`/alunos/${aluno.id}/evolucao`}
            className="inline-flex items-center gap-1 text-sm font-medium text-indigo-600 hover:underline dark:text-indigo-400"
          >
            <TrendingUp size={14} /> Ver evolução
          </Link>
        </div>
        <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">
          {aluno.turma} · {aluno.ano_escolar}
        </p>
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <Card className="p-4">
          <p className="text-xs font-medium uppercase tracking-wide text-zinc-500 dark:text-zinc-400">Nota Matific</p>
          <p className="mt-1 text-2xl font-semibold tabular-nums">{nota(perfil.nota_matific)}</p>
        </Card>
        <Card className="p-4">
          <p className="text-xs font-medium uppercase tracking-wide text-zinc-500 dark:text-zinc-400">Nota Elefante Letrado</p>
          <p className="mt-1 text-2xl font-semibold tabular-nums">{nota(perfil.nota_elefante)}</p>
        </Card>
        <Card className="border-indigo-200 p-4 dark:border-indigo-500/30">
          <p className="text-xs font-medium uppercase tracking-wide text-indigo-600 dark:text-indigo-400">Nota Geral</p>
          <p className="mt-1 text-2xl font-semibold tabular-nums">{nota(perfil.nota_geral)}</p>
        </Card>
      </div>

      {/* Transparência total do cálculo (PRD §45, §54) */}
      <section className="space-y-4">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
          Como esta nota foi calculada
        </h2>
        {detalhes.matific && (
          <TabelaCalculo titulo="Matific" linhas={detalhes.matific.indicadores} notaFinal={detalhes.matific.nota} />
        )}
        {detalhes.elefante && (
          <TabelaCalculo titulo="Elefante Letrado" linhas={detalhes.elefante.indicadores} notaFinal={detalhes.elefante.nota} />
        )}
        {detalhes.geral && (
          <Card className="p-4 text-sm">
            <p className="font-medium">Nota Geral</p>
            <p className="mt-1 tabular-nums text-zinc-600 dark:text-zinc-300">
              Matific {nota(perfil.nota_matific)} × {pesosGerais.matific ?? 0}% + Elefante{" "}
              {nota(perfil.nota_elefante)} × {pesosGerais.elefante ?? 0}% ={" "}
              <span className="font-semibold text-zinc-900 dark:text-zinc-100">{nota(perfil.nota_geral)}</span>
            </p>
          </Card>
        )}
        {!detalhes.matific && !detalhes.elefante && (
          <Vazio titulo="Ainda não há nota calculada para este aluno" descricao="Importe dados das plataformas para gerar a primeira nota." />
        )}
      </section>
    </div>
  );
}
