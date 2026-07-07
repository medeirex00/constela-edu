/**
 * Importações (PRD §15–§16, §50–§52): envio de PDF ou texto colado,
 * prévia com erros ANTES de gravar e correspondência de nomes com
 * confirmação de duplicatas prováveis.
 */
import { CheckCircle2, FileUp, History, Sparkles, UserPlus } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import {
  Badge,
  Botao,
  Campo,
  Card,
  Carregando,
  Mensagem,
  PageHeader,
  Vazio,
  estiloInput,
} from "../components/ui";
import { useApp } from "../context/AppContext";
import { api, apiUpload } from "../lib/api";
import { dataHora } from "../lib/formato";
import type { Analise, Importacao, LinhaAnalise, ResultadoImportacao, Turma } from "../lib/types";

const ROTULOS_DADOS: Record<string, string> = {
  atividades: "Atividades",
  pontuacao_media: "Média",
  estrelas: "Estrelas",
  livros_unicos: "Livros",
  tempo_leitura_min: "Tempo (min)",
  questoes_tentativas: "Questões",
  questoes_acertos: "Acertos",
  livros_por_nivel: "Níveis",
  livro: "Livro",
  nivel: "Nível",
};

function resumoDados(dados: Record<string, unknown>): string {
  return Object.entries(dados)
    .map(([chave, valor]) => {
      const rotulo = ROTULOS_DADOS[chave] ?? chave;
      if (chave === "livros_por_nivel" && valor && typeof valor === "object") {
        const pares = Object.entries(valor as Record<string, number>)
          .map(([codigo, qtd]) => `${codigo}:${qtd}`)
          .join(" ");
        return `${rotulo}: ${pares || "—"}`;
      }
      return `${rotulo}: ${valor}`;
    })
    .join(" · ");
}

type Acao = { tipo: "importar"; alunoId: number } | { tipo: "criar"; turmaId: number | null } | { tipo: "ignorar" };

function acaoInicial(linha: LinhaAnalise): Acao {
  const c = linha.correspondencia;
  if (c && c.aluno_id && (c.status === "exato" || c.status === "provavel")) {
    return { tipo: "importar", alunoId: c.aluno_id };
  }
  return { tipo: "ignorar" };
}

export default function Importacoes() {
  const { escolaId, usuario } = useApp();
  const podeImportar = usuario?.is_global || ["admin", "coordenador"].includes(usuario?.cargo ?? "");

  const [texto, setTexto] = useState("");
  const [plataforma, setPlataforma] = useState("");
  const [arquivo, setArquivo] = useState<File | null>(null);
  const inputArquivo = useRef<HTMLInputElement | null>(null);

  const [analise, setAnalise] = useState<Analise | null>(null);
  const [acoes, setAcoes] = useState<Acao[]>([]);
  const [turmas, setTurmas] = useState<Turma[]>([]);
  const [turmaEmMassa, setTurmaEmMassa] = useState<number | null>(null);
  const [historico, setHistorico] = useState<Importacao[] | null>(null);
  const [ocupado, setOcupado] = useState(false);
  const [erro, setErro] = useState("");
  const [resultado, setResultado] = useState<ResultadoImportacao | null>(null);

  const carregarHistorico = useCallback(() => {
    if (!escolaId) return;
    api<Importacao[]>(`/escolas/${escolaId}/importacoes`)
      .then(setHistorico)
      .catch(() => setHistorico([]));
  }, [escolaId]);

  useEffect(() => {
    carregarHistorico();
    if (!escolaId) return;
    api<Turma[]>(`/escolas/${escolaId}/turmas`).then(setTurmas).catch(() => setTurmas([]));
  }, [escolaId, carregarHistorico]);

  async function analisar() {
    if (!escolaId) return;
    setOcupado(true);
    setErro("");
    setResultado(null);
    try {
      const dados = new FormData();
      if (arquivo) dados.append("arquivo", arquivo);
      else dados.append("texto", texto);
      if (plataforma) dados.append("plataforma", plataforma);
      const resposta = await apiUpload<Analise>(`/escolas/${escolaId}/importacoes/analisar`, dados);
      setAnalise(resposta);
      setAcoes(resposta.linhas.map(acaoInicial));
    } catch (excecao) {
      setErro(excecao instanceof Error ? excecao.message : "Falha ao analisar o relatório.");
    } finally {
      setOcupado(false);
    }
  }

  async function confirmar() {
    if (!escolaId || !analise) return;
    setOcupado(true);
    setErro("");
    try {
      const linhas = analise.linhas
        .map((linha, indice) => ({ linha, acao: acoes[indice] }))
        .filter(({ linha, acao }) => acao.tipo !== "ignorar" && linha.erros.length === 0)
        .map(({ linha, acao }) => ({
          nome: linha.nome,
          dados: linha.dados,
          aluno_id: acao.tipo === "importar" ? acao.alunoId : null,
          criar_em_turma_id: acao.tipo === "criar" ? acao.turmaId : null,
        }));
      if (linhas.length === 0) {
        setErro(
          naoEncontrados.length > 0
            ? "Os alunos deste relatório ainda não estão cadastrados. Use “Criar todos nesta turma” acima (ou escolha um destino em cada linha) antes de importar."
            : "Nenhuma linha marcada para importar. Escolha um destino em cada linha.",
        );
        return;
      }
      const resposta = await api<ResultadoImportacao>(
        `/escolas/${escolaId}/importacoes/confirmar`,
        {
          method: "POST",
          body: JSON.stringify({
            plataforma: analise.plataforma,
            formato: analise.formato,
            tipo: analise.tipo,
            arquivo_token: analise.arquivo_token,
            arquivo_nome: analise.arquivo_nome,
            linhas,
          }),
        },
      );
      setResultado(resposta);
      setAnalise(null);
      setTexto("");
      setArquivo(null);
      if (inputArquivo.current) inputArquivo.current.value = "";
      carregarHistorico();
    } catch (excecao) {
      setErro(excecao instanceof Error ? excecao.message : "Falha ao confirmar a importação.");
    } finally {
      setOcupado(false);
    }
  }

  function definirAcao(indice: number, valor: string) {
    setAcoes((atuais) =>
      atuais.map((acao, i) => {
        if (i !== indice) return acao;
        if (valor === "ignorar") return { tipo: "ignorar" };
        if (valor === "criar") return { tipo: "criar", turmaId: turmaEmMassa ?? turmas[0]?.id ?? null };
        return { tipo: "importar", alunoId: Number(valor) };
      }),
    );
  }

  /** Marca TODOS os alunos não encontrados para serem criados na turma dada. */
  function criarTodosNaoEncontrados(turmaId: number) {
    if (!analise) return;
    setAcoes((atuais) =>
      atuais.map((acao, i) => {
        const linha = analise.linhas[i];
        if (linha.erros.length === 0 && linha.correspondencia?.status === "nao_encontrado") {
          return { tipo: "criar", turmaId };
        }
        return acao;
      }),
    );
  }

  // Estatísticas da prévia para os controles em massa e a contagem final.
  const linhasValidas = analise ? analise.linhas.filter((l) => l.erros.length === 0) : [];
  const naoEncontrados = analise
    ? analise.linhas.filter(
        (l) => l.erros.length === 0 && l.correspondencia?.status === "nao_encontrado",
      )
    : [];
  const totalSelecionados = analise
    ? acoes.filter((a, i) => a.tipo !== "ignorar" && analise.linhas[i]?.erros.length === 0).length
    : 0;
  const turmaAlvo = turmaEmMassa ?? turmas[0]?.id ?? null;

  const tomCorrespondencia = { exato: "ok", provavel: "alerta", nao_encontrado: "neutro" } as const;
  const rotuloCorrespondencia = {
    exato: "Encontrado",
    provavel: "Confirme o aluno",
    nao_encontrado: "Não encontrado",
  } as const;

  return (
    <div>
      <PageHeader
        titulo="Importações"
        descricao="Envie o relatório exportado da plataforma (PDF) ou cole o texto. Nada é gravado antes da sua confirmação."
      />

      {!podeImportar && (
        <div className="mb-4">
          <Mensagem tipo="erro">Somente administradores e coordenadores podem importar dados.</Mensagem>
        </div>
      )}

      {resultado && (
        <Card className="mb-4 p-4">
          <div className="flex items-start gap-2">
            <CheckCircle2 size={18} className="mt-0.5 text-emerald-600" />
            <div>
              <p className="text-sm font-medium">{resultado.mensagem}</p>
              {resultado.avisos.length > 0 && (
                <ul className="mt-1 list-inside list-disc text-xs text-amber-700 dark:text-amber-300">
                  {resultado.avisos.map((aviso) => (
                    <li key={aviso}>{aviso}</li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </Card>
      )}

      {podeImportar && !analise && (
        <Card className="mb-6 p-5">
          <div className="grid gap-4 sm:grid-cols-2">
            <Campo rotulo="Plataforma">
              <select className={estiloInput} value={plataforma} onChange={(e) => setPlataforma(e.target.value)}>
                <option value="">Detectar automaticamente</option>
                <option value="matific">Matific</option>
                <option value="elefante">Elefante Letrado</option>
              </select>
            </Campo>
            <Campo rotulo="Arquivo (PDF, TXT ou CSV)">
              <input
                ref={inputArquivo}
                type="file"
                accept=".pdf,.txt,.csv,.tsv"
                className={`${estiloInput} file:mr-3 file:rounded-md file:border-0 file:bg-indigo-50 file:px-3 file:py-1 file:text-indigo-700 dark:file:bg-indigo-500/10 dark:file:text-indigo-300`}
                onChange={(e) => setArquivo(e.target.files?.[0] ?? null)}
              />
            </Campo>
          </div>
          <div className="mt-4">
            <Campo rotulo="Ou cole aqui o texto copiado do relatório">
              <textarea
                className={`${estiloInput} min-h-[140px] font-mono text-xs`}
                placeholder={"Nome do aluno\tAtividades finalizadas\tPontuação média\tEstrelas\nAna Beatriz Souza\t42\t85,5\t120"}
                value={texto}
                onChange={(e) => setTexto(e.target.value)}
              />
            </Campo>
          </div>
          {erro && <div className="mt-3"><Mensagem tipo="erro">{erro}</Mensagem></div>}
          <div className="mt-4 flex justify-end">
            <Botao onClick={analisar} disabled={ocupado || (!arquivo && !texto.trim())}>
              <Sparkles size={15} /> {ocupado ? "Analisando..." : "Analisar e ver prévia"}
            </Botao>
          </div>
        </Card>
      )}

      {analise && (
        <Card className="mb-6">
          <div className="flex flex-wrap items-center gap-2 border-b border-zinc-200 px-4 py-3 dark:border-zinc-800">
            <FileUp size={16} className="text-zinc-400" />
            <span className="text-sm font-medium">Prévia da importação</span>
            <Badge tom="destaque">{analise.plataforma === "matific" ? "Matific" : "Elefante Letrado"}</Badge>
            {analise.formato === "leituras" && <Badge>uma linha por livro</Badge>}
            {analise.estrategia === "posicional" && <Badge tom="alerta">colunas por posição — confira</Badge>}
          </div>

          {/* Resumo da detecção automática (o usuário não precisa informar a plataforma) */}
          <div className="border-b border-zinc-200 bg-indigo-50/50 px-4 py-3 text-sm dark:border-zinc-800 dark:bg-indigo-500/5">
            <p className="font-medium text-indigo-800 dark:text-indigo-300">
              {analise.mensagem_deteccao || "Arquivo analisado."}
            </p>
            <p className="mt-0.5 text-zinc-600 dark:text-zinc-300">
              {analise.total_alunos} aluno{analise.total_alunos === 1 ? "" : "s"} encontrado
              {analise.total_alunos === 1 ? "" : "s"} · {analise.total_linhas} registro
              {analise.total_linhas === 1 ? "" : "s"} ·{" "}
              {analise.total_erros === 0 && analise.total_avisos === 0
                ? "nenhum problema detectado"
                : `${analise.total_erros} erro(s), ${analise.total_avisos} aviso(s) — detalhes abaixo`}
            </p>
          </div>

          {analise.erros_gerais.length > 0 && (
            <div className="space-y-2 p-4">
              {analise.erros_gerais.map((mensagem) => (
                <Mensagem key={mensagem} tipo="erro">{mensagem}</Mensagem>
              ))}
            </div>
          )}

          {/* Ação em massa: criar de uma vez todos os alunos ainda não cadastrados */}
          {naoEncontrados.length > 0 && (
            <div className="flex flex-wrap items-center gap-2 border-b border-amber-200 bg-amber-50 px-4 py-3 text-sm dark:border-amber-500/20 dark:bg-amber-500/10">
              <UserPlus size={16} className="text-amber-600 dark:text-amber-400" />
              <span className="text-amber-800 dark:text-amber-200">
                <strong>{naoEncontrados.length}</strong> aluno(s) deste relatório ainda não
                estão cadastrados nesta escola.
              </span>
              {turmas.length === 0 ? (
                <span className="text-amber-800 dark:text-amber-200">
                  Crie uma turma primeiro em{" "}
                  <Link to="/turmas" className="font-medium underline">Turmas</Link>.
                </span>
              ) : (
                <div className="ml-auto flex flex-wrap items-center gap-2">
                  <select
                    aria-label="Turma para os novos alunos"
                    className="rounded-lg border border-amber-300 bg-white px-2 py-1.5 text-sm dark:border-amber-500/30 dark:bg-zinc-900"
                    value={turmaAlvo ?? ""}
                    onChange={(e) => setTurmaEmMassa(Number(e.target.value))}
                  >
                    {turmas.map((turma) => (
                      <option key={turma.id} value={turma.id}>{turma.nome}</option>
                    ))}
                  </select>
                  <Botao
                    variante="primario"
                    onClick={() => turmaAlvo && criarTodosNaoEncontrados(turmaAlvo)}
                  >
                    <UserPlus size={15} /> Criar todos nesta turma
                  </Botao>
                </div>
              )}
            </div>
          )}

          {analise.linhas.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-zinc-200 text-left text-xs uppercase tracking-wide text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
                    <th className="px-4 py-2 font-medium">Nome no relatório</th>
                    <th className="px-4 py-2 font-medium">Dados</th>
                    <th className="px-4 py-2 font-medium">Correspondência</th>
                    <th className="px-4 py-2 font-medium">Destino</th>
                  </tr>
                </thead>
                <tbody>
                  {analise.linhas.map((linha, indice) => {
                    const acao = acoes[indice];
                    const correspondencia = linha.correspondencia;
                    return (
                      <tr key={linha.numero} className="border-b border-zinc-100 align-top last:border-0 dark:border-zinc-800/60">
                        <td className="px-4 py-2.5 font-medium">{linha.nome || <em className="text-zinc-400">sem nome</em>}</td>
                        <td className="px-4 py-2.5 text-xs text-zinc-600 dark:text-zinc-300">
                          {resumoDados(linha.dados) || "—"}
                          {linha.erros.map((mensagem) => (
                            <p key={mensagem} className="mt-1 text-red-600 dark:text-red-400">{mensagem}</p>
                          ))}
                          {linha.avisos.map((mensagem) => (
                            <p key={mensagem} className="mt-1 text-amber-600 dark:text-amber-400">{mensagem}</p>
                          ))}
                        </td>
                        <td className="px-4 py-2.5">
                          {correspondencia && (
                            <div className="space-y-1">
                              <Badge tom={tomCorrespondencia[correspondencia.status]}>
                                {rotuloCorrespondencia[correspondencia.status]}
                              </Badge>
                              {correspondencia.status === "provavel" && (
                                <p className="text-xs text-zinc-500 dark:text-zinc-400">
                                  {correspondencia.aluno_nome} ({correspondencia.similaridade}%)
                                </p>
                              )}
                            </div>
                          )}
                        </td>
                        <td className="px-4 py-2.5">
                          {linha.erros.length > 0 ? (
                            <span className="text-xs text-zinc-400">linha com erro — não será importada</span>
                          ) : (
                            <div className="flex flex-col gap-1.5">
                              <select
                                aria-label={`Destino de ${linha.nome}`}
                                className={estiloInput}
                                value={
                                  acao.tipo === "ignorar" ? "ignorar" : acao.tipo === "criar" ? "criar" : String(acao.alunoId)
                                }
                                onChange={(e) => definirAcao(indice, e.target.value)}
                              >
                                {correspondencia?.alternativas.map((alternativa) => (
                                  <option key={alternativa.aluno_id} value={alternativa.aluno_id}>
                                    {alternativa.nome} ({alternativa.similaridade}%)
                                  </option>
                                ))}
                                <option value="criar">Criar aluno novo…</option>
                                <option value="ignorar">Ignorar esta linha</option>
                              </select>
                              {acao.tipo === "criar" && (
                                <select
                                  aria-label={`Turma para ${linha.nome}`}
                                  className={estiloInput}
                                  value={acao.turmaId ?? ""}
                                  onChange={(e) =>
                                    setAcoes((atuais) =>
                                      atuais.map((a, i) =>
                                        i === indice ? { tipo: "criar", turmaId: Number(e.target.value) } : a,
                                      ),
                                    )
                                  }
                                >
                                  {turmas.map((turma) => (
                                    <option key={turma.id} value={turma.id}>{turma.nome}</option>
                                  ))}
                                </select>
                              )}
                            </div>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

          {erro && <div className="p-4"><Mensagem tipo="erro">{erro}</Mensagem></div>}
          <div className="flex flex-wrap items-center justify-end gap-3 border-t border-zinc-200 px-4 py-3 dark:border-zinc-800">
            <span className="mr-auto text-sm font-medium">
              {totalSelecionados > 0
                ? `${totalSelecionados} de ${linhasValidas.length} aluno(s) serão importados.`
                : "Deseja importar estes dados?"}
            </span>
            {naoEncontrados.length > 0 && totalSelecionados < linhasValidas.length && turmas.length > 0 && (
              <Botao
                variante="neutro"
                onClick={() => turmaAlvo && criarTodosNaoEncontrados(turmaAlvo)}
              >
                Criar não encontrados
              </Botao>
            )}
            <Botao variante="neutro" onClick={() => setAnalise(null)} disabled={ocupado}>
              Não, voltar
            </Botao>
            <Botao onClick={confirmar} disabled={ocupado || totalSelecionados === 0}>
              {ocupado ? "Importando..." : "Sim, importar"}
            </Botao>
          </div>
        </Card>
      )}

      <PageHeader titulo="Histórico" descricao="Toda importação fica registrada com autor, quantidade e tempo (PRD §15)." />
      <Card>
        {historico === null ? (
          <Carregando />
        ) : historico.length === 0 ? (
          <Vazio titulo="Nenhuma importação ainda" descricao="O histórico aparecerá aqui após a primeira importação." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm tabular-nums">
              <thead>
                <tr className="border-b border-zinc-200 text-left text-xs uppercase tracking-wide text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
                  <th className="px-4 py-2 font-medium"><History size={13} className="inline" /> Data</th>
                  <th className="px-4 py-2 font-medium">Plataforma</th>
                  <th className="px-4 py-2 font-medium">Origem</th>
                  <th className="px-4 py-2 text-right font-medium">Alunos</th>
                  <th className="px-4 py-2 text-right font-medium">Erros</th>
                  <th className="hidden px-4 py-2 font-medium md:table-cell">Por</th>
                </tr>
              </thead>
              <tbody>
                {historico.map((item) => (
                  <tr key={item.id} className="border-b border-zinc-100 last:border-0 dark:border-zinc-800/60">
                    <td className="px-4 py-2.5">{dataHora(item.created_at)}</td>
                    <td className="px-4 py-2.5">
                      <Badge tom="destaque">{item.plataforma === "matific" ? "Matific" : "Elefante"}</Badge>
                    </td>
                    <td className="px-4 py-2.5 text-xs text-zinc-500 dark:text-zinc-400">{item.tipo}</td>
                    <td className="px-4 py-2.5 text-right">{item.qtd_alunos}</td>
                    <td className="px-4 py-2.5 text-right">{item.qtd_erros || "—"}</td>
                    <td className="hidden px-4 py-2.5 text-zinc-500 dark:text-zinc-400 md:table-cell">{item.usuario_nome ?? "—"}</td>
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
