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

interface ConquistaAluno {
  codigo: string;
  nome: string;
  icone: string;
  descricao: string;
  criterio: string;
  unidade: string;
  xp: number;
  raridade: string;
  limite: number;
  progresso: number;
  pct: number;
  faltam: number;
  atingida: boolean;
}

interface Gamificacao {
  xp: number;
  xp_conquistas: number;
  nivel: number;
  xp_para_proximo: number;
  sequencia_semanas: number;
  total_conquistas: number;
  conquistas: ConquistaAluno[];
}

function BarraProgresso({ pct }: { pct: number }) {
  return (
    <div className="h-2 w-full overflow-hidden rounded-full bg-zinc-200 dark:bg-zinc-800">
      <div
        className="h-full rounded-full bg-indigo-600 transition-all dark:bg-indigo-500"
        style={{ width: `${Math.min(100, Math.max(2, pct))}%` }}
      />
    </div>
  );
}

function valorCurto(valor: number): string {
  return Number.isInteger(valor) ? String(valor) : nota(valor);
}

/** "Faltam apenas 7 livros para desbloquear esta conquista." */
function textoFaltam(conquista: ConquistaAluno): string {
  const quanto = valorCurto(conquista.faltam);
  if (conquista.unidade === "%") {
    return `Faltam ${quanto} pontos percentuais para desbloquear esta conquista.`;
  }
  return `Faltam apenas ${quanto} ${conquista.unidade} para desbloquear esta conquista.`;
}

export default function PerfilAluno() {
  const { id } = useParams();
  const { escolaId } = useApp();
  const [perfil, setPerfil] = useState<Perfil | null>(null);
  const [gamificacao, setGamificacao] = useState<Gamificacao | null>(null);
  const [carregando, setCarregando] = useState(true);

  useEffect(() => {
    if (!escolaId || !id) return;
    setCarregando(true);
    api<Perfil>(`/escolas/${escolaId}/alunos/${id}/perfil`)
      .then(setPerfil)
      .catch(() => setPerfil(null))
      .finally(() => setCarregando(false));
    api<Gamificacao>(`/escolas/${escolaId}/gamificacao/alunos/${id}`)
      .then(setGamificacao)
      .catch(() => setGamificacao(null));
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

      {gamificacao && (
        <section>
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
            Conquistas
          </h2>
          <Card className="p-4">
            <div className="mb-4 flex flex-wrap items-center gap-4 text-sm">
              <Badge tom="destaque">Nível {gamificacao.nivel}</Badge>
              <span className="tabular-nums text-zinc-600 dark:text-zinc-300">
                {gamificacao.xp.toLocaleString("pt-BR")} XP
                {gamificacao.xp_conquistas > 0 && (
                  <span className="text-amber-600 dark:text-amber-400"> ({gamificacao.xp_conquistas.toLocaleString("pt-BR")} de conquistas)</span>
                )}
                <span className="text-zinc-400"> · faltam {gamificacao.xp_para_proximo} para o próximo nível</span>
              </span>
              {gamificacao.sequencia_semanas > 0 && (
                <Badge tom="alerta">🔥 {gamificacao.sequencia_semanas} semana{gamificacao.sequencia_semanas > 1 ? "s" : ""} seguidas</Badge>
              )}
              <Link
                to="/conquistas/biblioteca"
                className="ml-auto text-xs font-medium text-indigo-600 hover:underline dark:text-indigo-400"
              >
                Ver a Biblioteca de Conquistas →
              </Link>
            </div>

            {/* Próximas conquistas: as mais perto de desbloquear (§ progresso) */}
            {(() => {
              const proximas = gamificacao.conquistas
                .filter((c) => !c.atingida && c.progresso > 0)
                .sort((a, b) => b.pct - a.pct)
                .slice(0, 3);
              if (proximas.length === 0) return null;
              return (
                <div className="mb-4">
                  <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
                    Próximas conquistas
                  </p>
                  <div className="grid gap-3 lg:grid-cols-3">
                    {proximas.map((conquista) => (
                      <div key={conquista.codigo} className="rounded-lg border border-indigo-200 bg-indigo-50/50 p-3 dark:border-indigo-500/20 dark:bg-indigo-500/5">
                        <div className="flex items-center justify-between gap-2">
                          <p className="truncate text-sm font-semibold">
                            {conquista.icone} {conquista.nome}
                          </p>
                          <span className="shrink-0 text-xs font-semibold tabular-nums text-indigo-700 dark:text-indigo-300">
                            {Math.round(conquista.pct)}%
                          </span>
                        </div>
                        <p className="mb-1.5 mt-0.5 text-xs tabular-nums text-zinc-500 dark:text-zinc-400">
                          {valorCurto(conquista.progresso)} de {valorCurto(conquista.limite)} {conquista.unidade}
                        </p>
                        <BarraProgresso pct={conquista.pct} />
                        <p className="mt-1.5 text-xs text-zinc-500 dark:text-zinc-400">{textoFaltam(conquista)}</p>
                      </div>
                    ))}
                  </div>
                </div>
              );
            })()}

            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {gamificacao.conquistas.map((conquista) => (
                <div
                  key={conquista.codigo}
                  className={`flex items-start gap-2.5 rounded-lg border p-2.5 ${
                    conquista.atingida
                      ? "border-emerald-200 bg-emerald-50/60 dark:border-emerald-500/20 dark:bg-emerald-500/5"
                      : "border-zinc-200 dark:border-zinc-800"
                  }`}
                >
                  <span className={`text-xl leading-none ${conquista.atingida ? "" : "opacity-50"}`}>{conquista.icone}</span>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center justify-between gap-2">
                      <p className={`text-sm font-medium ${conquista.atingida ? "" : "text-zinc-500 dark:text-zinc-400"}`}>
                        {conquista.nome}
                      </p>
                      <span className="shrink-0 text-xs font-semibold text-amber-600 dark:text-amber-400">
                        +{conquista.xp} XP
                      </span>
                    </div>
                    <p className="text-xs text-zinc-500 dark:text-zinc-400">{conquista.descricao}</p>
                    {!conquista.atingida && (
                      <div className="mt-1.5">
                        <BarraProgresso pct={conquista.pct} />
                        <p className="mt-1 text-xs tabular-nums text-zinc-400">
                          {valorCurto(conquista.progresso)} / {valorCurto(conquista.limite)} {conquista.unidade}
                        </p>
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </Card>
        </section>
      )}

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
