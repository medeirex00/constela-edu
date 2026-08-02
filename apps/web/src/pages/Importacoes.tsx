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
  FileUp,
  History,
  Layers,
  Pencil,
  Sparkles,
  UserPlus,
  Users,
  XCircle,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";

import ImportacaoMatriculas from "./ImportacaoMatriculas";
import SeletorAlunoDrawer from "../components/SeletorAlunoDrawer";
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
import { useImportacaoLote } from "../context/ImportacaoLoteContext";
import { useApi } from "../hooks/useApi";
import { api, apiUpload } from "../lib/api";
import { dataHora } from "../lib/formato";
import { acharTurmaPorNome, normalizar } from "../lib/nomes";
import ImportacaoLote from "./ImportacaoLote";
import type { Aluno, Analise, Importacao, LinhaAnalise, ResultadoImportacao, Turma } from "../lib/types";

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

/** Como o nome do aluno foi identificado (define ícone, cor e texto do card). */
const METODO_IDENTIFICACAO: Record<
  string,
  { Icone: LucideIcon; cor: string; corTexto: string; classe: string; texto: string }
> = {
  arquivo: {
    Icone: CheckCircle2,
    cor: "text-emerald-600 dark:text-emerald-400",
    corTexto: "text-emerald-700 dark:text-emerald-300",
    classe: "border-emerald-200 bg-emerald-50/60 dark:border-emerald-500/20 dark:bg-emerald-500/5",
    texto: "Aluno identificado pelo nome do arquivo",
  },
  conteudo: {
    Icone: AlertTriangle,
    cor: "text-amber-600 dark:text-amber-400",
    corTexto: "text-amber-700 dark:text-amber-300",
    classe: "border-amber-200 bg-amber-50/60 dark:border-amber-500/20 dark:bg-amber-500/5",
    texto: "Aluno identificado pelo conteúdo do PDF",
  },
  nenhum: {
    Icone: XCircle,
    cor: "text-red-600 dark:text-red-400",
    corTexto: "text-red-700 dark:text-red-300",
    classe: "border-red-200 bg-red-50/60 dark:border-red-500/20 dark:bg-red-500/5",
    texto: "Não foi possível identificar o aluno automaticamente",
  },
};

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

type Acao =
  | { tipo: "importar"; alunoId: number; alunoNome?: string; turmaNome?: string; manual?: boolean }
  | { tipo: "criar"; turmaId: number | null }
  // Turma lida do relatório que AINDA NÃO EXISTE: a confirmação a cria e
  // matricula o aluno nela (primeiro import sem cadastrar turmas antes).
  | { tipo: "criar_nova" }
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

/** Agrupa as linhas da análise por aluno (nome + turma do relatório). No
 *  relatório individual, as centenas de linhas de livros viram um único
 *  grupo. A turma entra na chave porque o leaderboard do Matific abrevia os
 *  nomes ("MARIA J") e alunos DIFERENTES de turmas diferentes colidem — num
 *  grupo só, o mês de um deles seria descartado em silêncio. */
function agrupar(analise: Analise): Grupo[] {
  const mapa = new Map<string, Grupo>();
  const ordem: string[] = [];
  analise.linhas.forEach((linha, indice) => {
    const turma = String(linha.dados.turma_relatorio ?? "");
    const chave = `${normalizar(linha.nome) || `#${indice}`}|${normalizar(turma)}`;
    let g = mapa.get(chave);
    if (!g) {
      // Homônimos em turmas diferentes: o nome exibido ganha a turma para o
      // usuário saber qual é qual na conferência.
      const repetido = analise.linhas.some(
        (outra) => normalizar(outra.nome) === normalizar(linha.nome)
          && String(outra.dados.turma_relatorio ?? "") !== turma,
      );
      g = {
        chave,
        nome: repetido && turma ? `${linha.nome} (${turma})` : linha.nome,
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

export default function Importacoes() {
  const { escolaId, usuario } = useApp();
  // Escola VIVA: `analisar()` é assíncrona; se a escola mudar durante o upload,
  // a continuação descarta a resposta (resolvida contra o tenant anterior) em
  // vez de repovoar a prévia sob a nova escola.
  const escolaIdRef = useRef(escolaId);
  escolaIdRef.current = escolaId;
  const podeImportar = usuario?.is_global || ["admin", "coordenador"].includes(usuario?.cargo ?? "");

  const [texto, setTexto] = useState("");
  const [plataforma, setPlataforma] = useState("");
  const [arquivo, setArquivo] = useState<File | null>(null);
  const inputArquivo = useRef<HTMLInputElement | null>(null);

  const [analise, setAnalise] = useState<Analise | null>(null);
  const [acoes, setAcoes] = useState<Acao[]>([]); // uma ação por GRUPO
  const [turmaEmMassa, setTurmaEmMassa] = useState<number | null>(null);
  // Turma detectada no relatório que ainda não existe no cadastro (a
  // confirmação a cria automaticamente).
  const [turmaNova, setTurmaNova] = useState("");
  const [editarGrupo, setEditarGrupo] = useState<number | null>(null);
  const [ocupado, setOcupado] = useState(false);
  const [erro, setErro] = useState("");
  const [resultado, setResultado] = useState<ResultadoImportacao | null>(null);

  // Por padrão a página abre em "Matrículas da escola" — é por onde se importa
  // a Lista Piloto (o fluxo mais comum). Só abre em "Em lote" quando já há um
  // lote em andamento (análise/conferência/importação rodando no contexto).
  const { fase: faseLote } = useImportacaoLote();
  const [modo, setModo] = useState<"individual" | "lote" | "matriculas">(
    faseLote !== "selecao" ? "lote" : "matriculas",
  );

  const grupos = useMemo(() => (analise ? agrupar(analise) : []), [analise]);

  // Ao TROCAR de escola, descarta a análise/relatório em preparo: ele foi
  // resolvido (aluno_id/turma_id) contra a escola anterior; confirmá-lo já na
  // nova escola gravaria alunos/notas no tenant errado (isolamento por escola).
  useEffect(() => {
    setAnalise(null);
    setAcoes([]);
    setTurmaEmMassa(null);
    setTurmaNova("");
    setEditarGrupo(null);
    setResultado(null);
    setErro("");
    setArquivo(null);
    setTexto("");
    if (inputArquivo.current) inputArquivo.current.value = "";
  }, [escolaId]);

  // Leitura via arquitetura única (useApi): sem escola ainda, a fonte é `null`
  // (ocioso). O hook cuida de cancelamento, timeout e retry. O histórico expõe
  // o erro (exibido no card) em vez de engoli-lo; `recarregar` refaz a busca
  // após uma importação. As turmas alimentam seletores, então caem em [] vazio.
  const {
    dados: historico,
    erro: erroHistorico,
    recarregar: recarregarHistorico,
  } = useApi<Importacao[]>(escolaId ? `/escolas/${escolaId}/importacoes` : null);
  const { dados: turmasApi } = useApi<Turma[]>(escolaId ? `/escolas/${escolaId}/turmas` : null);
  const turmas = turmasApi ?? [];

  async function analisar() {
    if (!escolaId) return;
    const escolaDaAnalise = escolaId;
    setOcupado(true);
    setErro("");
    setResultado(null);
    try {
      const dados = new FormData();
      if (arquivo) dados.append("arquivo", arquivo);
      else dados.append("texto", texto);
      if (plataforma) dados.append("plataforma", plataforma);
      const resposta = await apiUpload<Analise>(`/escolas/${escolaId}/importacoes/analisar`, dados);
      // Trocou de escola durante o upload: descarta (o reset já limpou a tela).
      if (escolaIdRef.current !== escolaDaAnalise) return;
      setAnalise(resposta);

      // Ação inicial POR GRUPO, já usando a turma lida do relatório.
      const turmaId = acharTurmaPorNome(turmas, resposta.turma_detectada);
      setTurmaEmMassa(turmaId ?? turmas[0]?.id ?? null);
      // Turma detectada que NÃO existe no cadastro: será criada na confirmação.
      setTurmaNova(resposta.turma_detectada && !turmaId ? resposta.turma_detectada : "");
      const gruposIniciais = agrupar(resposta);
      setAcoes(
        gruposIniciais.map((g): Acao => {
          if (g.todasComErro) return { tipo: "ignorar" };
          const c = g.correspondencia;
          // Só a ALTA confiança do motor ("vinculado") e o nome EXATO único
          // pré-selecionam o vínculo. "revisar"/"provavel" (possível duplicata) e
          // "bloqueado" caem em criar (o gestor decide) e passam pelo motor seguro na
          // confirmação — grafia/similaridade parecida NUNCA vira vínculo por 1 clique.
          if (c?.aluno_id && (c.status === "vinculado" || c.status === "exato")) {
            return { tipo: "importar", alunoId: c.aluno_id, alunoNome: c.aluno_nome ?? g.nome };
          }
          // Aluno novo: cria na turma DO PRÓPRIO ALUNO — o relatório geral do
          // Matific tem alunos de várias turmas (turma_relatorio por linha);
          // se essa turma não casar, usa a turma global detectada.
          const turmaLinha = resposta.linhas[g.indices[0]]?.dados?.turma_relatorio;
          const turmaDoGrupo = acharTurmaPorNome(turmas, String(turmaLinha ?? "")) ?? turmaId;
          if (turmaDoGrupo) return { tipo: "criar", turmaId: turmaDoGrupo };
          // A turma citada no relatório ainda não existe: cria automaticamente
          // na confirmação (turma lida da linha ou do cabeçalho).
          if (turmaLinha || resposta.turma_detectada) return { tipo: "criar_nova" };
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
    const escolaDaConfirmacao = escolaId; // grava e reporta na escola de origem
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
            // Turma inexistente: manda o NOME (da linha ou do cabeçalho) — o
            // backend cria a turma uma única vez e matricula o aluno nela.
            criar_em_turma_nome:
              acao.tipo === "criar_nova"
                ? String(linha.dados.turma_relatorio ?? analise.turma_detectada ?? "") || null
                : null,
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
        `/escolas/${escolaDaConfirmacao}/importacoes/confirmar`,
        {
          method: "POST",
          body: JSON.stringify({
            plataforma: analise.plataforma,
            formato: analise.formato,
            tipo: analise.tipo,
            arquivo_token: analise.arquivo_token,
            arquivo_nome: analise.arquivo_nome,
            // "Intervalo de datas" do relatório: o backend soma os valores ao
            // acumulado e data o snapshot dentro do período.
            periodo_inicio: analise.periodo_inicio || null,
            periodo_fim: analise.periodo_fim || null,
            linhas,
          }),
        },
      );
      // Trocou de escola durante a gravação: a escrita foi p/ a escola de
      // origem (correto); não sobrepõe a tela da nova escola com o resultado.
      if (escolaIdRef.current !== escolaDaConfirmacao) return;
      setResultado(resposta);
      setAnalise(null);
      setTexto("");
      setArquivo(null);
      if (inputArquivo.current) inputArquivo.current.value = "";
      recarregarHistorico();
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
        if (valor === "criar_nova") return { tipo: "criar_nova" };
        return { tipo: "importar", alunoId: Number(valor) };
      }),
    );
  }

  /** "Aplicar a todos": todo aluno NOVO (sem vínculo com cadastro) recebe a
   *  mesma ação — criar na turma escolhida ou na turma do relatório (nova). */
  function aplicarATodosOsNovos(acao: Acao) {
    setAcoes((atuais) =>
      atuais.map((atual, i) => {
        const g = grupos[i];
        if (g && !g.todasComErro && atual.tipo !== "importar") return acao;
        return atual;
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
    if (acao.tipo === "criar_nova") {
      const turmaLinha = analise ? analise.linhas[g.indices[0]]?.dados?.turma_relatorio : "";
      return {
        tom: "alerta" as const,
        titulo: "Aluno novo — a turma do relatório será criada",
        nome: g.nome,
        turma: String(turmaLinha ?? "") || turmaNova,
        detalhe: "turma ainda não cadastrada — criada automaticamente ao importar",
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

  const tomCorrespondencia = {
    vinculado: "ok", exato: "ok",
    revisar: "alerta", provavel: "alerta", bloqueado: "destaque",
    nao_encontrado: "neutro",
  } as const;
  const rotuloCorrespondencia = {
    vinculado: "Vinculado automaticamente",
    exato: "Vinculado automaticamente",
    revisar: "Possível duplicata — requer revisão",
    provavel: "Possível duplicata — requer revisão",
    bloqueado: "Bloqueado por conflito de identidade",
    nao_encontrado: "Novo aluno",
  } as const;

  // Estatísticas (por grupo) para os controles e a contagem final.
  const gruposValidos = grupos.filter((g) => !g.todasComErro);
  // "Novos" = tudo que NÃO será vinculado automaticamente (cria por padrão):
  // aluno novo, bloqueado por conflito e possível duplicata não confirmada.
  const CRIAM = new Set(["nao_encontrado", "bloqueado", "revisar"]);
  const naoEncontrados = grupos.filter(
    (g) => !g.todasComErro && CRIAM.has(g.correspondencia?.status ?? ""),
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

      {podeImportar && (
        <div className="mb-5 inline-flex rounded-xl border border-zinc-200 bg-white p-1 dark:border-zinc-800 dark:bg-zinc-900">
          {([
            { valor: "individual", Icone: FileUp, rotulo: "Um por vez" },
            { valor: "lote", Icone: Layers, rotulo: "Em lote" },
            { valor: "matriculas", Icone: Users, rotulo: "Matrículas da escola" },
          ] as const).map(({ valor, Icone, rotulo }) => (
            <button
              key={valor}
              type="button"
              onClick={() => setModo(valor)}
              className={`inline-flex items-center gap-1.5 rounded-lg px-3.5 py-1.5 text-sm font-medium transition-colors ${
                modo === valor
                  ? "bg-indigo-600 text-white shadow-sm"
                  : "text-zinc-600 hover:bg-zinc-100 dark:text-zinc-300 dark:hover:bg-zinc-800"
              }`}
            >
              <Icone size={15} /> {rotulo}
            </button>
          ))}
        </div>
      )}

      {modo === "lote" && podeImportar && escolaId && (
        <ImportacaoLote aoConcluir={recarregarHistorico} />
      )}

      {modo === "matriculas" && podeImportar && escolaId && (
        <ImportacaoMatriculas escolaId={escolaId} aoConcluir={recarregarHistorico} />
      )}

      {modo === "individual" && resultado && (
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

      {modo === "individual" && podeImportar && !analise && (
        <Card className="mb-6 p-5">
          <div className="grid gap-4 sm:grid-cols-2">
            <Campo rotulo="Plataforma">
              <select className={estiloInput} value={plataforma} onChange={(e) => setPlataforma(e.target.value)}>
                <option value="">Detectar automaticamente</option>
                <option value="matific">Matific</option>
                <option value="elefante">Elefante Letrado</option>
              </select>
            </Campo>
            <Campo rotulo="Arquivo (PDF, Excel, TXT ou CSV)">
              <input
                ref={inputArquivo}
                type="file"
                accept=".pdf,.xlsx,.xlsm,.txt,.csv,.tsv,.json"
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

      {modo === "individual" && analise && (
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

          {/* Relatório individual: identificação do aluno em destaque + trocar.
              A cor/ícone refletem COMO o nome foi identificado (arquivo é o
              método preferencial); a linha de vínculo mostra o cadastro. */}
          {analise.formato === "leituras" && grupos.length > 0 && (
            <div className="space-y-3 p-4">
              {grupos.map((grupo, gi) => {
                const vinc = descreverVinculo(gi);
                if (!vinc) return null;
                const metodo = METODO_IDENTIFICACAO[analise.origem_nome] ?? METODO_IDENTIFICACAO.conteudo;
                return (
                  <div key={grupo.chave} className={`rounded-xl border p-4 ${metodo.classe}`}>
                    <div className="flex flex-wrap items-start gap-3">
                      <metodo.Icone size={22} className={`mt-0.5 shrink-0 ${metodo.cor}`} />
                      <div className="min-w-0 flex-1">
                        <p className={`text-xs font-semibold uppercase tracking-wide ${metodo.corTexto}`}>
                          {metodo.texto}
                        </p>
                        <p className="mt-0.5 text-lg font-semibold tracking-tight">{grupo.nome}</p>
                        <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-zinc-600 dark:text-zinc-400">
                          <span
                            className={
                              vinc.tom === "ok"
                                ? "font-medium text-emerald-700 dark:text-emerald-300"
                                : "font-medium text-amber-700 dark:text-amber-300"
                            }
                          >
                            {vinc.titulo}
                          </span>
                          {vinc.nome !== grupo.nome && <span>→ {vinc.nome}</span>}
                          {vinc.turma && <span>· Turma: {vinc.turma}</span>}
                          {grupo.totalLivros > 0 && (
                            <span>· {grupo.totalLivros} livro{grupo.totalLivros === 1 ? "" : "s"}</span>
                          )}
                          {vinc.detalhe && <span className="text-zinc-400">· {vinc.detalhe}</span>}
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
            <div className="space-y-2 border-b border-amber-200 bg-amber-50 px-4 py-3 text-sm dark:border-amber-500/20 dark:bg-amber-500/10">
              <div className="flex flex-wrap items-center gap-2">
                <UserPlus size={16} className="text-amber-600 dark:text-amber-400" />
                <span className="text-amber-800 dark:text-amber-200">
                  <strong>{naoEncontrados.length}</strong> aluno(s) novo(s)
                  {analise.turma_detectada && acharTurmaPorNome(turmas, analise.turma_detectada)
                    ? " — já marcados para criar na turma do relatório."
                    : turmaNova
                      ? ` — a turma “${turmaNova}” será criada automaticamente ao importar.`
                      : "."}
                </span>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                {turmaNova && (
                  <Botao variante="neutro" onClick={() => aplicarATodosOsNovos({ tipo: "criar_nova" })}>
                    <UserPlus size={15} /> Aplicar a todos: turma do relatório (nova)
                  </Botao>
                )}
                {turmas.length > 0 && (
                  <>
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
                    <Botao variante="neutro"
                           onClick={() => turmaAlvo && aplicarATodosOsNovos({ tipo: "criar", turmaId: turmaAlvo })}>
                      <UserPlus size={15} /> Aplicar a todos
                    </Botao>
                  </>
                )}
                {turmas.length === 0 && !turmaNova && (
                  <span className="text-amber-800 dark:text-amber-200">
                    Crie uma turma primeiro em{" "}
                    <Link to="/turmas" className="font-medium underline">Turmas</Link>.
                  </span>
                )}
              </div>
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
                              {correspondencia.aluno_nome
                               && correspondencia.status !== "nao_encontrado"
                               && correspondencia.status !== "bloqueado" && (
                                <p className="text-xs text-zinc-500 dark:text-zinc-400">
                                  → {correspondencia.aluno_nome}
                                  {correspondencia.similaridade ? ` (${correspondencia.similaridade}%)` : ""}
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
                                value={
                                  acao.tipo === "ignorar" ? "ignorar"
                                  : acao.tipo === "criar" ? "criar"
                                  : acao.tipo === "criar_nova" ? "criar_nova"
                                  : String(acao.alunoId)
                                }
                                onChange={(e) => definirAcao(gi, e.target.value)}
                              >
                                {correspondencia?.alternativas.map((alternativa) => (
                                  <option key={alternativa.aluno_id} value={alternativa.aluno_id}>
                                    {alternativa.nome}
                                    {alternativa.turma ? ` — ${alternativa.turma}` : ""} ({alternativa.similaridade}%)
                                  </option>
                                ))}
                                {(Boolean(primeira.dados.turma_relatorio) || Boolean(turmaNova)) && (
                                  <option value="criar_nova">
                                    Criar na turma do relatório ({String(primeira.dados.turma_relatorio ?? turmaNova)})
                                  </option>
                                )}
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
              turmaInicial={acharTurmaPorNome(turmas, analise.turma_detectada)}
              nomePdf={editarGrupo !== null ? grupos[editarGrupo]?.nome ?? "" : ""}
              aoFechar={() => setEditarGrupo(null)}
              aoConfirmar={vincularAluno}
            />
          )}
        </Card>
      )}

      <PageHeader titulo="Histórico" descricao="Toda importação fica registrada com autor, quantidade e tempo (PRD §15)." />
      <Card>
        {erroHistorico ? (
          <Vazio titulo="Não foi possível carregar" descricao={erroHistorico.message} />
        ) : historico === null ? (
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
