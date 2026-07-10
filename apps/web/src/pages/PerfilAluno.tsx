import { ArrowLeft, BookOpen, TrendingUp } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import AcoesAluno from "../components/AcoesAluno";
import EvolucaoAlunoAba from "../components/EvolucaoAlunoAba";
import HistoricoLeituras from "../components/HistoricoLeituras";
import { Badge, Card, Carregando, Vazio } from "../components/ui";
import { useApp } from "../context/AppContext";
import { useApi } from "../hooks/useApi";
import { nota, numero } from "../lib/formato";
import type { LeituraNiveis, LinhaCalculo, PerfilAluno as Perfil } from "../lib/types";

// Rótulos e ORDEM de exibição da ficha cadastral (planilha de matrículas).
// Só aparecem os campos que a planilha da escola realmente preencheu.
const ROTULOS_FICHA: Record<string, string> = {
  rm: "RM",
  ra: "RA",
  responsavel_completo: "Responsável (nome completo)",
  responsavel: "Responsável",
  telefone: "Telefone",
  endereco: "Endereço",
  bairro: "Bairro",
  matricula: "Matrícula",
  transferencia: "Transferência",
  remanejamento: "Remanejamento",
  rg: "RG",
  cpf: "CPF",
  sus: "SUS",
  sexo: "Sexo",
  raca_cor: "Raça/Cor",
  bolsa_familia: "Bolsa Família",
};

/** Dados cadastrais do aluno vindos da planilha de matrículas (só gestor). */
function FichaCadastral({ ficha }: { ficha: Record<string, string> }) {
  const itens: Array<readonly [string, string]> = [];
  for (const chave of Object.keys(ROTULOS_FICHA)) {
    if (ficha[chave]) itens.push([ROTULOS_FICHA[chave], ficha[chave]] as const);
  }
  // Colunas extras da planilha que ainda não têm rótulo próprio.
  for (const [chave, valor] of Object.entries(ficha)) {
    if (!(chave in ROTULOS_FICHA) && valor) {
      itens.push([chave.replace(/_/g, " "), String(valor)] as const);
    }
  }
  if (itens.length === 0) return null;
  return (
    <section>
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
        Ficha cadastral
      </h2>
      <Card className="p-4">
        <dl className="grid grid-cols-1 gap-x-6 gap-y-3 sm:grid-cols-2">
          {itens.map(([rotulo, valor]) => (
            <div key={rotulo} className="min-w-0">
              <dt className="text-xs uppercase tracking-wide text-zinc-400">{rotulo}</dt>
              <dd className="mt-0.5 break-words text-sm text-zinc-800 dark:text-zinc-100">{valor}</dd>
            </div>
          ))}
        </dl>
      </Card>
    </section>
  );
}

/** Gráfico de barras horizontais dos livros concluídos por faixa (PRD §38). */
function LeituraPorNivel({ dados }: { dados: LeituraNiveis }) {
  const maxQtd = Math.max(1, ...dados.faixas.map((f) => f.quantidade));
  return (
    <Card className="p-4">
      <div className="mb-3 flex flex-wrap items-center gap-x-6 gap-y-1 text-sm">
        <span className="flex items-center gap-1.5 font-medium">
          <BookOpen size={15} className="text-indigo-500" /> Leitura por nível de dificuldade
        </span>
        <span className="text-zinc-500 dark:text-zinc-400">
          {numero(dados.total_livros)} livro{dados.total_livros === 1 ? "" : "s"} ·{" "}
          <span className="font-medium text-indigo-600 dark:text-indigo-400">
            {numero(dados.pontos_dificuldade)} pontos de dificuldade
          </span>
        </span>
        {dados.faixa_predominante && (
          <span className="ml-auto">
            <Badge tom="destaque">Predominante: {dados.faixa_predominante}</Badge>
          </span>
        )}
      </div>

      {dados.total_livros === 0 ? (
        <p className="py-4 text-center text-sm text-zinc-400">
          Nenhum livro registrado ainda. Informe os livros por nível na tela Elefante Letrado
          ou importe um relatório.
        </p>
      ) : (
        <div className="space-y-2">
          {dados.faixas.map((faixa) => (
            <div key={faixa.codigo} className="flex items-center gap-3 text-sm">
              <span className="w-24 shrink-0 truncate text-zinc-600 dark:text-zinc-300">{faixa.nome}</span>
              <div className="flex-1">
                <div className="h-5 overflow-hidden rounded-md bg-zinc-100 dark:bg-zinc-800">
                  <div
                    className="flex h-full items-center justify-end rounded-md bg-indigo-500 px-1.5 text-xs font-medium text-white transition-all dark:bg-indigo-500"
                    style={{ width: `${Math.max(faixa.quantidade ? 8 : 0, (faixa.quantidade / maxQtd) * 100)}%` }}
                  >
                    {faixa.quantidade > 0 ? faixa.quantidade : ""}
                  </div>
                </div>
              </div>
              <span className="w-28 shrink-0 text-right tabular-nums text-xs text-zinc-500 dark:text-zinc-400">
                {faixa.percentual}% · {numero(faixa.pontos)} pts
              </span>
            </div>
          ))}
          <p className="pt-1 text-xs text-zinc-400">
            Pontos por livro: {dados.faixas.map((f) => `${f.nome} = ${numero(f.pontos_por_livro)}`).join(" · ")}.
            Configuráveis em Métricas.
          </p>
        </div>
      )}
    </Card>
  );
}

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
  const { escolaId, usuario } = useApp();
  const navegar = useNavigate();
  // Professor vê a versão SUPERFICIAL: notas, posição e gamificação — sem
  // histórico de leituras, evolução detalhada nem ações de gestão.
  const gestor = Boolean(usuario?.is_global) ||
    ["admin", "coordenador"].includes(usuario?.cargo ?? "");
  const [aba, setAba] = useState<"perfil" | "historico" | "evolucao">("perfil");

  // Leitura via hook único: cuida de cancelamento, timeout e retry. Fica
  // ocioso (null) enquanto escolaId/id não existirem.
  const podeBuscar = Boolean(escolaId && id);
  const {
    dados: perfil,
    erro: erroPerfil,
    carregando,
    recarregar: recarregarPerfil,
  } = useApi<Perfil>(podeBuscar ? `/escolas/${escolaId}/alunos/${id}/perfil` : null);
  const { dados: gamificacao, recarregar: recarregarGamificacao } = useApi<Gamificacao>(
    podeBuscar ? `/escolas/${escolaId}/gamificacao/alunos/${id}` : null,
  );

  // Refaz as duas buscas após uma ação de gestão (editar, trocar turma…).
  const recarregar = () => {
    recarregarPerfil();
    recarregarGamificacao();
  };

  if (carregando) return <Carregando />;
  // Não engole o erro: mostra estado discreto em vez de "Aluno não encontrado".
  if (erroPerfil) return <Vazio titulo="Não foi possível carregar" descricao={erroPerfil.message} />;
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
          {gestor && (
            <Link
              to={`/alunos/${aluno.id}/evolucao`}
              className="inline-flex items-center gap-1 text-sm font-medium text-indigo-600 hover:underline dark:text-indigo-400"
            >
              <TrendingUp size={14} /> Ver evolução
            </Link>
          )}
          {gestor && escolaId && (
            <span className="ml-auto">
              {/* Editar dados, trocar turma, arquivar, excluir — direto da ficha */}
              <AcoesAluno
                aluno={aluno}
                escolaId={escolaId}
                aoMudar={recarregar}
                aoExcluir={() => navegar("/alunos")}
                mostrarVisualizar={false}
              />
            </span>
          )}
        </div>
        <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">
          {aluno.turma} · {aluno.ano_escolar}
        </p>
      </div>

      <div role="tablist" className="flex flex-wrap gap-1 border-b border-zinc-200 dark:border-zinc-800">
        {/* Professor: só a aba Perfil (histórico e evolução detalhada são de gestão) */}
        {([["perfil", "Perfil"], ["historico", "Histórico de Leituras"], ["evolucao", "Evolução"]] as const)
          .filter(([chave]) => gestor || chave === "perfil")
          .map(([chave, rotulo]) => (
          <button
            key={chave}
            role="tab"
            aria-selected={aba === chave}
            onClick={() => setAba(chave)}
            className={`-mb-px border-b-2 px-3 py-2 text-sm font-medium transition-colors ${
              aba === chave
                ? "border-indigo-600 text-zinc-900 dark:text-zinc-50"
                : "border-transparent text-zinc-500 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100"
            }`}
          >
            {rotulo}
          </button>
        ))}
      </div>

      {gestor && aba === "historico" && escolaId && id && (
        <HistoricoLeituras escolaId={escolaId} alunoId={id} />
      )}

      {gestor && aba === "evolucao" && escolaId && id && (
        <EvolucaoAlunoAba escolaId={escolaId} alunoId={id} />
      )}

      {aba === "perfil" && (
        <>
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

      {perfil.ficha && Object.keys(perfil.ficha).length > 0 && (
        <FichaCadastral ficha={perfil.ficha} />
      )}

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

      {perfil.leitura_niveis && (
        <section>
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
            Leitura por nível
          </h2>
          <LeituraPorNivel dados={perfil.leitura_niveis} />
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
        </>
      )}
    </div>
  );
}
