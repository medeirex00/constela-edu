/**
 * Importações (PRD §15–§16, §50–§52): envio de PDF ou texto colado,
 * prévia com erros ANTES de gravar e correspondência de nomes.
 *
 * A prévia é AGRUPADA por aluno: o relatório individual do Elefante (uma
 * linha por livro) vira UMA entrada ("N livros lidos"). A turma lida do
 * cabeçalho do PDF é usada para casar/criar o aluno sem intervenção manual.
 */
import {
  AlertTriangle,
  BookMarked,
  CheckCircle2,
  ChevronRight,
  FileUp,
  History,
  Pencil,
  Search,
  Sparkles,
  UserCheck,
  UserPlus,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";

import {
  Badge,
  Botao,
  Campo,
  Card,
  Carregando,
  Drawer,
  Mensagem,
  PageHeader,
  Vazio,
  estiloInput,
} from "../components/ui";
import { useApp } from "../context/AppContext";
import { api, apiUpload } from "../lib/api";
import { dataHora } from "../lib/formato";
import type {
  Aluno,
  Analise,
  Importacao,
  LinhaAnalise,
  PaginaAlunos,
  ResultadoImportacao,
  Turma,
} from "../lib/types";

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

const OCULTAR_NA_PREVIA = new Set(["turma_relatorio", "livro", "nivel", "genero", "data", "tempo_livro_min"]);

function resumoDados(dados: Record<string, unknown>): string {
  return Object.entries(dados)
    .filter(([chave]) => !OCULTAR_NA_PREVIA.has(chave))
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

function normalizar(nome: string): string {
  return nome
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();
}

type Acao =
  | { tipo: "importar"; alunoId: number; alunoNome?: string; turmaNome?: string; manual?: boolean }
  | { tipo: "criar"; turmaId: number | null }
  | { tipo: "ignorar" };

interface Grupo {
  chave: string;
  nome: string;
  indices: number[]; // índices das linhas originais deste aluno
  correspondencia: LinhaAnalise["correspondencia"];
  resumo: string;
  totalLivros: number; // > 0 no relatório individual (uma linha por livro)
  todasComErro: boolean;
}

/** Agrupa as linhas da análise por aluno (nome normalizado). No relatório
 *  individual, as centenas de linhas de livros viram um único grupo. */
function agrupar(analise: Analise): Grupo[] {
  const mapa = new Map<string, Grupo>();
  const ordem: string[] = [];
  analise.linhas.forEach((linha, indice) => {
    const chave = normalizar(linha.nome) || `#${indice}`;
    let g = mapa.get(chave);
    if (!g) {
      g = {
        chave,
        nome: linha.nome,
        indices: [],
        correspondencia: linha.correspondencia,
        resumo: "",
        totalLivros: 0,
        todasComErro: true,
      };
      mapa.set(chave, g);
      ordem.push(chave);
    }
    g.indices.push(indice);
    if (linha.erros.length === 0) g.todasComErro = false;
    if (linha.dados.livro) g.totalLivros += 1;
  });
  for (const chave of ordem) {
    const g = mapa.get(chave)!;
    const primeira = analise.linhas[g.indices[0]];
    g.resumo = g.totalLivros > 0
      ? `${g.totalLivros} livro${g.totalLivros === 1 ? "" : "s"} lido${g.totalLivros === 1 ? "" : "s"}`
      : resumoDados(primeira.dados) || "—";
  }
  return ordem.map((c) => mapa.get(c)!);
}

/** Painel lateral: escolher a turma, achar o aluno (busca + alfabética) e
 *  confirmar o vínculo do relatório individual. */
function SeletorAlunoDrawer({
  escolaId,
  aberto,
  turmas,
  turmaInicial,
  nomePdf,
  aoFechar,
  aoConfirmar,
}: {
  escolaId: number;
  aberto: boolean;
  turmas: Turma[];
  turmaInicial: number | null;
  nomePdf: string;
  aoFechar: () => void;
  aoConfirmar: (aluno: Aluno, turmaNome: string) => void;
}) {
  const [turmaId, setTurmaId] = useState<number | null>(turmaInicial);
  const [alunos, setAlunos] = useState<Aluno[] | null>(null);
  const [busca, setBusca] = useState("");
  const [selecionado, setSelecionado] = useState<Aluno | null>(null);

  useEffect(() => {
    if (aberto) {
      setTurmaId(turmaInicial ?? turmas[0]?.id ?? null);
      setBusca("");
      setSelecionado(null);
    }
  }, [aberto, turmaInicial, turmas]);

  useEffect(() => {
    if (!aberto || !turmaId) {
      setAlunos(null);
      return;
    }
    setAlunos(null);
    api<PaginaAlunos>(`/escolas/${escolaId}/alunos?turma_id=${turmaId}&por_pagina=100`)
      .then((r) => setAlunos(r.itens))
      .catch(() => setAlunos([]));
  }, [aberto, turmaId, escolaId]);

  const turmaNome = turmas.find((t) => t.id === turmaId)?.nome ?? "";
  const filtrados = (alunos ?? [])
    .filter((a) => normalizar(a.nome).includes(normalizar(busca)))
    .sort((a, b) => a.nome.localeCompare(b.nome, "pt-BR"));

  return (
    <Drawer titulo="Alterar aluno" aberto={aberto} aoFechar={aoFechar}>
      {selecionado ? (
        <div className="space-y-4">
          <p className="text-sm text-zinc-600 dark:text-zinc-300">
            Este relatório será vinculado ao aluno:
          </p>
          <Card className="p-4">
            <p className="text-lg font-semibold tracking-tight">{selecionado.nome}</p>
            <p className="mt-0.5 text-sm text-zinc-500 dark:text-zinc-400">Turma: {turmaNome}</p>
          </Card>
          <p className="text-xs text-zinc-500 dark:text-zinc-400">
            As leituras, a pontuação e todo o histórico do PDF passarão a pertencer a este aluno.
          </p>
          <div className="flex justify-end gap-2">
            <Botao variante="neutro" onClick={() => setSelecionado(null)}>Cancelar</Botao>
            <Botao onClick={() => aoConfirmar(selecionado, turmaNome)}>
              <UserCheck size={15} /> Confirmar
            </Botao>
          </div>
        </div>
      ) : (
        <div className="space-y-4">
          <div>
            <p className="mb-2 text-xs font-medium uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
              Aluno do relatório (PDF)
            </p>
            <p className="text-sm font-medium">{nomePdf || "—"}</p>
          </div>

          <Campo rotulo="1. Selecione a turma">
            <select
              className={estiloInput}
              value={turmaId ?? ""}
              onChange={(e) => setTurmaId(Number(e.target.value))}
            >
              {turmas.length === 0 && <option value="">Nenhuma turma cadastrada</option>}
              {turmas.map((turma) => (
                <option key={turma.id} value={turma.id}>{turma.nome}</option>
              ))}
            </select>
          </Campo>

          <div>
            <p className="mb-1.5 text-sm font-medium text-zinc-700 dark:text-zinc-300">2. Escolha o aluno</p>
            <label className="relative block">
              <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-zinc-400" />
              <input
                className={`${estiloInput} pl-9`}
                placeholder="Pesquisar por nome..."
                value={busca}
                onChange={(e) => setBusca(e.target.value)}
              />
            </label>
          </div>

          <div className="max-h-[45vh] overflow-y-auto rounded-lg border border-zinc-200 dark:border-zinc-800">
            {alunos === null ? (
              <Carregando />
            ) : filtrados.length === 0 ? (
              <p className="py-8 text-center text-sm text-zinc-400">
                {busca ? "Nenhum aluno encontrado." : "Turma sem alunos."}
              </p>
            ) : (
              <ul className="divide-y divide-zinc-100 dark:divide-zinc-800/60">
                {filtrados.map((aluno) => (
                  <li key={aluno.id}>
                    <button
                      className="flex w-full items-center gap-3 px-3 py-2.5 text-left transition-colors hover:bg-zinc-50 dark:hover:bg-zinc-800/60"
                      onClick={() => setSelecionado(aluno)}
                    >
                      <span className="flex h-8 w-8 shrink-0 items-center justify-center overflow-hidden rounded-full bg-indigo-100 text-xs font-semibold text-indigo-700 dark:bg-indigo-500/20 dark:text-indigo-300">
                        {aluno.foto_url ? (
                          <img src={aluno.foto_url} alt="" className="h-full w-full object-cover" />
                        ) : (
                          aluno.nome.slice(0, 1).toUpperCase()
                        )}
                      </span>
                      <span className="min-w-0 flex-1 truncate text-sm font-medium">{aluno.nome}</span>
                      <ChevronRight size={15} className="shrink-0 text-zinc-300 dark:text-zinc-600" />
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}
    </Drawer>
  );
}

export default function Importacoes() {
  const { escolaId, usuario } = useApp();
  const podeImportar = usuario?.is_global || ["admin", "coordenador"].includes(usuario?.cargo ?? "");

  const [texto, setTexto] = useState("");
  const [plataforma, setPlataforma] = useState("");
  const [arquivo, setArquivo] = useState<File | null>(null);
  const inputArquivo = useRef<HTMLInputElement | null>(null);

  const [analise, setAnalise] = useState<Analise | null>(null);
  const [acoes, setAcoes] = useState<Acao[]>([]); // uma ação por GRUPO
  const [turmas, setTurmas] = useState<Turma[]>([]);
  const [turmaEmMassa, setTurmaEmMassa] = useState<number | null>(null);
  const [editarGrupo, setEditarGrupo] = useState<number | null>(null);
  const [historico, setHistorico] = useState<Importacao[] | null>(null);
  const [ocupado, setOcupado] = useState(false);
  const [erro, setErro] = useState("");
  const [resultado, setResultado] = useState<ResultadoImportacao | null>(null);

  const grupos = useMemo(() => (analise ? agrupar(analise) : []), [analise]);

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

  // Palavras genéricas que NÃO distinguem uma turma de outra da mesma série.
  const GENERICOS = new Set(["ano", "serie", "série", "anual", "manha", "manhã", "tarde", "noite", "integral", "turma", "de", "do", "da"]);

  /** Turma cujo nome bate com a lida do PDF (para criar/casar automático).
   *  Exige que os tokens DISTINTIVOS (a letra da turma, o número da série)
   *  coincidam e que a correspondência seja ÚNICA — senão "5 Ano B" casaria
   *  por engano com "5 Ano A". */
  function turmaDoRelatorio(nomeDetectado: string): number | null {
    if (!nomeDetectado) return null;
    const limpar = (s: string) => normalizar(s).replace(/[ºª°]/g, "");
    const alvo = limpar(nomeDetectado);
    const exata = turmas.find((t) => limpar(t.nome) === alvo);
    if (exata) return exata.id;

    const distintivos = alvo.split(" ").filter((t) => t.length > 0 && !GENERICOS.has(t));
    if (distintivos.length === 0) return null;
    const candidatas = turmas.filter((t) => {
      const nome = ` ${limpar(t.nome)} `;
      // todos os tokens distintivos da turma detectada devem aparecer
      return distintivos.every((tk) => nome.includes(` ${tk} `) || nome.includes(tk));
    });
    return candidatas.length === 1 ? candidatas[0].id : null; // só se for única
  }

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

      // Ação inicial POR GRUPO, já usando a turma lida do PDF.
      const turmaId = turmaDoRelatorio(resposta.turma_detectada);
      setTurmaEmMassa(turmaId ?? turmas[0]?.id ?? null);
      const gruposIniciais = agrupar(resposta);
      setAcoes(
        gruposIniciais.map((g): Acao => {
          if (g.todasComErro) return { tipo: "ignorar" };
          const c = g.correspondencia;
          if (c?.aluno_id && (c.status === "exato" || c.status === "provavel")) {
            return { tipo: "importar", alunoId: c.aluno_id, alunoNome: c.aluno_nome ?? g.nome };
          }
          // Aluno novo: cria na turma detectada automaticamente (sem intervenção)
          if (turmaId) return { tipo: "criar", turmaId };
          return { tipo: "ignorar" };
        }),
      );
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
      // Expande cada grupo de volta para as linhas originais do aluno.
      const linhas = grupos.flatMap((grupo, gi) => {
        const acao = acoes[gi];
        if (!acao || acao.tipo === "ignorar") return [];
        return grupo.indices
          .map((i) => analise.linhas[i])
          .filter((linha) => linha.erros.length === 0)
          .map((linha) => ({
            nome: linha.nome,
            dados: linha.dados,
            aluno_id: acao.tipo === "importar" ? acao.alunoId : null,
            criar_em_turma_id: acao.tipo === "criar" ? acao.turmaId : null,
          }));
      });
      if (linhas.length === 0) {
        setErro(
          naoEncontrados.length > 0 && turmas.length === 0
            ? "Os alunos deste relatório ainda não estão cadastrados e não há turmas. Crie uma turma primeiro."
            : "Nenhum aluno marcado para importar. Escolha um destino para cada aluno.",
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

  function definirAcao(gi: number, valor: string) {
    setAcoes((atuais) =>
      atuais.map((acao, i) => {
        if (i !== gi) return acao;
        if (valor === "ignorar") return { tipo: "ignorar" };
        if (valor === "criar") return { tipo: "criar", turmaId: turmaAlvo ?? turmas[0]?.id ?? null };
        return { tipo: "importar", alunoId: Number(valor) };
      }),
    );
  }

  function criarTodosNaoEncontrados(turmaId: number) {
    setAcoes((atuais) =>
      atuais.map((acao, i) => {
        const g = grupos[i];
        if (g && !g.todasComErro && g.correspondencia?.status === "nao_encontrado") {
          return { tipo: "criar", turmaId };
        }
        return acao;
      }),
    );
  }

  /** Vincula o relatório (grupo em edição) ao aluno escolhido no drawer. */
  function vincularAluno(aluno: Aluno, turmaNome: string) {
    if (editarGrupo === null) return;
    setAcoes((atuais) =>
      atuais.map((a, i) =>
        i === editarGrupo
          ? { tipo: "importar", alunoId: aluno.id, alunoNome: aluno.nome, turmaNome, manual: true }
          : a,
      ),
    );
    setEditarGrupo(null);
  }

  /** Como o vínculo do grupo será exibido no card de identificação. */
  function descreverVinculo(gi: number) {
    const g = grupos[gi];
    const acao = acoes[gi];
    if (!g || !acao) return null;
    if (acao.tipo === "importar") {
      const c = g.correspondencia;
      const manual = acao.manual || acao.alunoId !== c?.aluno_id;
      const baixa = !manual && c?.status === "provavel";
      return {
        tom: (manual || !baixa ? "ok" : "alerta") as "ok" | "alerta",
        titulo: manual
          ? "Aluno definido por você"
          : baixa
            ? "Aluno identificado com baixa confiança"
            : "Aluno identificado",
        nome: acao.alunoNome ?? g.nome,
        turma: acao.turmaNome ?? analise?.turma_detectada ?? "",
        detalhe: baixa && c?.similaridade ? `correspondência de ${c.similaridade}%` : "",
      };
    }
    if (acao.tipo === "criar") {
      const turma = turmas.find((t) => t.id === acao.turmaId)?.nome ?? "";
      return {
        tom: "alerta" as const,
        titulo: "Aluno novo — será criado",
        nome: g.nome,
        turma,
        detalhe: "não encontrado no cadastro",
      };
    }
    return {
      tom: "alerta" as const,
      titulo: "Nenhum aluno vinculado",
      nome: g.nome,
      turma: "",
      detalhe: "escolha um aluno para importar",
    };
  }

  const tomCorrespondencia = { exato: "ok", provavel: "alerta", nao_encontrado: "neutro" } as const;
  const rotuloCorrespondencia = {
    exato: "Encontrado",
    provavel: "Confirme o aluno",
    nao_encontrado: "Aluno novo",
  } as const;

  // Estatísticas (por grupo) para os controles e a contagem final.
  const gruposValidos = grupos.filter((g) => !g.todasComErro);
  const naoEncontrados = grupos.filter(
    (g) => !g.todasComErro && g.correspondencia?.status === "nao_encontrado",
  );
  const totalSelecionados = grupos.filter((g, i) => !g.todasComErro && acoes[i]?.tipo !== "ignorar").length;
  const turmaAlvo = turmaEmMassa ?? turmas[0]?.id ?? null;

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
            {analise.formato === "leituras" && <Badge>relatório individual</Badge>}
            {analise.estrategia === "posicional" && <Badge tom="alerta">colunas por posição — confira</Badge>}
          </div>

          <div className="border-b border-zinc-200 bg-indigo-50/50 px-4 py-3 text-sm dark:border-zinc-800 dark:bg-indigo-500/5">
            <p className="font-medium text-indigo-800 dark:text-indigo-300">
              {analise.mensagem_deteccao || "Arquivo analisado."}
            </p>
            <p className="mt-0.5 text-zinc-600 dark:text-zinc-300">
              {gruposValidos.length} aluno{gruposValidos.length === 1 ? "" : "s"} ·{" "}
              {analise.total_linhas} registro{analise.total_linhas === 1 ? "" : "s"}
              {analise.turma_detectada && (
                <> · turma <strong>{analise.turma_detectada}</strong></>
              )}
              {analise.total_erros === 0 && analise.total_avisos === 0
                ? " · nenhum problema detectado"
                : ` · ${analise.total_erros} erro(s), ${analise.total_avisos} aviso(s)`}
            </p>
          </div>

          {analise.erros_gerais.length > 0 && (
            <div className="space-y-2 p-4">
              {analise.erros_gerais.map((mensagem) => (
                <Mensagem key={mensagem} tipo="erro">{mensagem}</Mensagem>
              ))}
            </div>
          )}

          {/* Relatório individual: identificação do aluno em destaque + trocar */}
          {analise.formato === "leituras" && grupos.length > 0 && (
            <div className="space-y-3 p-4">
              {grupos.map((grupo, gi) => {
                const info = descreverVinculo(gi);
                if (!info) return null;
                const alta = info.tom === "ok";
                return (
                  <div
                    key={grupo.chave}
                    className={`rounded-xl border p-4 ${
                      alta
                        ? "border-emerald-200 bg-emerald-50/60 dark:border-emerald-500/20 dark:bg-emerald-500/5"
                        : "border-amber-200 bg-amber-50/60 dark:border-amber-500/20 dark:bg-amber-500/5"
                    }`}
                  >
                    <div className="flex flex-wrap items-start gap-3">
                      {alta ? (
                        <CheckCircle2 size={22} className="mt-0.5 shrink-0 text-emerald-600 dark:text-emerald-400" />
                      ) : (
                        <AlertTriangle size={22} className="mt-0.5 shrink-0 text-amber-600 dark:text-amber-400" />
                      )}
                      <div className="min-w-0 flex-1">
                        <p className={`text-xs font-semibold uppercase tracking-wide ${alta ? "text-emerald-700 dark:text-emerald-300" : "text-amber-700 dark:text-amber-300"}`}>
                          {info.titulo}
                        </p>
                        <p className="mt-0.5 text-lg font-semibold tracking-tight">{info.nome}</p>
                        <p className="mt-0.5 text-sm text-zinc-600 dark:text-zinc-400">
                          {[
                            info.turma && `Turma: ${info.turma}`,
                            grupo.totalLivros > 0 && `${grupo.totalLivros} livro${grupo.totalLivros === 1 ? "" : "s"}`,
                            info.detalhe,
                          ]
                            .filter(Boolean)
                            .join(" · ")}
                        </p>
                      </div>
                      <Botao variante="neutro" onClick={() => setEditarGrupo(gi)}>
                        <Pencil size={15} /> Alterar aluno
                      </Botao>
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          {/* Ação em massa: criar de uma vez os alunos ainda não cadastrados */}
          {analise.formato !== "leituras" && naoEncontrados.length > 0 && (
            <div className="flex flex-wrap items-center gap-2 border-b border-amber-200 bg-amber-50 px-4 py-3 text-sm dark:border-amber-500/20 dark:bg-amber-500/10">
              <UserPlus size={16} className="text-amber-600 dark:text-amber-400" />
              <span className="text-amber-800 dark:text-amber-200">
                <strong>{naoEncontrados.length}</strong> aluno(s) novo(s)
                {analise.turma_detectada && turmaDoRelatorio(analise.turma_detectada)
                  ? " — já marcados para criar na turma do relatório."
                  : "."}
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
                  <Botao variante="neutro" onClick={() => turmaAlvo && criarTodosNaoEncontrados(turmaAlvo)}>
                    <UserPlus size={15} /> Criar todos nesta turma
                  </Botao>
                </div>
              )}
            </div>
          )}

          {analise.formato !== "leituras" && grupos.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-zinc-200 text-left text-xs uppercase tracking-wide text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
                    <th className="px-4 py-2 font-medium">Aluno no relatório</th>
                    <th className="px-4 py-2 font-medium">Dados</th>
                    <th className="px-4 py-2 font-medium">Correspondência</th>
                    <th className="px-4 py-2 font-medium">Destino</th>
                  </tr>
                </thead>
                <tbody>
                  {grupos.map((grupo, gi) => {
                    const acao = acoes[gi] ?? { tipo: "ignorar" as const };
                    const correspondencia = grupo.correspondencia;
                    const primeira = analise.linhas[grupo.indices[0]];
                    return (
                      <tr key={grupo.chave} className="border-b border-zinc-100 align-top last:border-0 dark:border-zinc-800/60">
                        <td className="px-4 py-2.5 font-medium">
                          {grupo.nome || <em className="text-zinc-400">sem nome</em>}
                        </td>
                        <td className="px-4 py-2.5 text-xs text-zinc-600 dark:text-zinc-300">
                          {grupo.totalLivros > 0 ? (
                            <span className="inline-flex items-center gap-1">
                              <BookMarked size={12} /> {grupo.resumo}
                            </span>
                          ) : (
                            grupo.resumo
                          )}
                          {primeira.avisos.map((mensagem) => (
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
                          {grupo.todasComErro ? (
                            <span className="text-xs text-zinc-400">sem dados válidos — não será importado</span>
                          ) : (
                            <div className="flex flex-col gap-1.5">
                              <select
                                aria-label={`Destino de ${grupo.nome}`}
                                className={estiloInput}
                                value={acao.tipo === "ignorar" ? "ignorar" : acao.tipo === "criar" ? "criar" : String(acao.alunoId)}
                                onChange={(e) => definirAcao(gi, e.target.value)}
                              >
                                {correspondencia?.alternativas.map((alternativa) => (
                                  <option key={alternativa.aluno_id} value={alternativa.aluno_id}>
                                    {alternativa.nome}
                                    {alternativa.turma ? ` — ${alternativa.turma}` : ""} ({alternativa.similaridade}%)
                                  </option>
                                ))}
                                <option value="criar">Criar aluno novo…</option>
                                <option value="ignorar">Ignorar</option>
                              </select>
                              {acao.tipo === "criar" && (
                                <select
                                  aria-label={`Turma para ${grupo.nome}`}
                                  className={estiloInput}
                                  value={acao.turmaId ?? ""}
                                  onChange={(e) =>
                                    setAcoes((atuais) =>
                                      atuais.map((a, i) =>
                                        i === gi ? { tipo: "criar", turmaId: Number(e.target.value) } : a,
                                      ),
                                    )
                                  }
                                >
                                  {turmas.length === 0 && <option value="">Crie uma turma primeiro</option>}
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
                ? `${totalSelecionados} de ${gruposValidos.length} aluno(s) serão importados.`
                : "Deseja importar estes dados?"}
            </span>
            <Botao variante="neutro" onClick={() => setAnalise(null)} disabled={ocupado}>
              Não, voltar
            </Botao>
            <Botao onClick={confirmar} disabled={ocupado || totalSelecionados === 0}>
              {ocupado ? "Importando..." : "Sim, importar"}
            </Botao>
          </div>

          {escolaId && (
            <SeletorAlunoDrawer
              escolaId={escolaId}
              aberto={editarGrupo !== null}
              turmas={turmas}
              turmaInicial={turmaDoRelatorio(analise.turma_detectada)}
              nomePdf={editarGrupo !== null ? grupos[editarGrupo]?.nome ?? "" : ""}
              aoFechar={() => setEditarGrupo(null)}
              aoConfirmar={vincularAluno}
            />
          )}
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
