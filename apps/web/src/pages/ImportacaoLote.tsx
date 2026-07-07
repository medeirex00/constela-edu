/**
 * Importação em LOTE de relatórios individuais (Elefante Letrado).
 *
 * O usuário arrasta/seleciona dezenas ou centenas de PDFs (um por aluno) e o
 * sistema processa cada um de forma INDEPENDENTE — o erro em um arquivo nunca
 * interrompe os demais. Fluxo em quatro etapas:
 *
 *   1. Seleção    — arrastar/escolher os PDFs (acumula, remove individual).
 *   2. Análise    — cada PDF vai ao /analisar; barra "Analisando X de N".
 *                   O aluno é identificado pelo NOME DO ARQUIVO (prioridade),
 *                   depois pelo conteúdo; a turma vem do cabeçalho.
 *   3. Conferência— um cartão por arquivo (✅/⚠️/❌) com aluno e turma. Botão
 *                   "Corrigir" abre o painel lateral (turma → aluno). "Ignorar"
 *                   pula o arquivo.
 *   4. Importação — só os arquivos válidos vão ao /confirmar (recalcular=false);
 *                   barra "Processando X de N"; UM /recalcular ao final.
 *
 * Ao fim, um relatório: enviados, importados, corrigidos, ignorados, erros e
 * tempo total.
 */
import {
  AlertTriangle,
  Ban,
  BookMarked,
  CheckCircle2,
  Clock,
  FileText,
  Pencil,
  Play,
  RotateCcw,
  UploadCloud,
  Users,
  X,
  XCircle,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useMemo, useRef, useState, type DragEvent } from "react";

import SeletorAlunoDrawer from "../components/SeletorAlunoDrawer";
import { Badge, Botao, Card } from "../components/ui";
import { api, apiUpload } from "../lib/api";
import { acharTurmaPorNome } from "../lib/nomes";
import type { Aluno, Analise, Turma } from "../lib/types";

type Fase = "selecao" | "analisando" | "conferencia" | "importando" | "relatorio";
type StatusItem = "ok" | "alerta" | "pendente" | "erro";

type AcaoItem =
  | { tipo: "importar"; alunoId: number }
  | { tipo: "criar"; turmaId: number }
  | { tipo: "corrigir" };

interface ItemLote {
  id: string;
  nome: string; // nome do arquivo
  arquivo: File;
  analise: Analise | null;
  status: StatusItem;
  origem: string; // arquivo | conteudo | nenhum
  alunoNome: string;
  turmaNome: string;
  totalLivros: number;
  acao: AcaoItem;
  detalhe: string;
  corrigido: boolean;
  ignorado: boolean;
  resultado?: "importado" | "erro" | "ignorado" | "pendente";
}

const VISUAL: Record<StatusItem, { Icone: LucideIcon; cor: string; chip: string; rotulo: string }> = {
  ok: {
    Icone: CheckCircle2,
    cor: "text-emerald-600 dark:text-emerald-400",
    chip: "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300",
    rotulo: "Pronto",
  },
  alerta: {
    Icone: AlertTriangle,
    cor: "text-amber-600 dark:text-amber-400",
    chip: "bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300",
    rotulo: "Confira",
  },
  pendente: {
    Icone: AlertTriangle,
    cor: "text-orange-600 dark:text-orange-400",
    chip: "bg-orange-100 text-orange-700 dark:bg-orange-500/15 dark:text-orange-300",
    rotulo: "Ação necessária",
  },
  erro: {
    Icone: XCircle,
    cor: "text-red-600 dark:text-red-400",
    chip: "bg-red-100 text-red-700 dark:bg-red-500/15 dark:text-red-300",
    rotulo: "Não identificado",
  },
};

/** true quando o arquivo tem um destino resolvido e será enviado ao confirmar. */
function importavel(item: ItemLote): boolean {
  return !item.ignorado && (item.acao.tipo === "importar" || item.acao.tipo === "criar");
}

/** Lê a análise de um PDF e decide status + ação, sem intervenção do usuário. */
function montarItem(arquivo: File, indice: number, analise: Analise, turmas: Turma[]): ItemLote {
  const base = { id: `${indice}-${arquivo.name}`, nome: arquivo.name, arquivo, analise, corrigido: false, ignorado: false };
  const linhasValidas = analise.linhas.filter((l) => l.erros.length === 0);
  const nome = analise.linhas.find((l) => l.nome)?.nome ?? "";
  const origem = analise.origem_nome || "nenhum";
  const corresp = analise.linhas.find((l) => l.correspondencia)?.correspondencia ?? null;
  const totalLivros = analise.linhas.filter((l) => l.dados?.livro).length;
  const turmaId = acharTurmaPorNome(turmas, analise.turma_detectada);
  const turmaNome = turmas.find((t) => t.id === turmaId)?.nome ?? analise.turma_detectada ?? "";

  // ❌ Não deu para identificar o aluno (nem pelo arquivo, nem pelo conteúdo).
  if (!nome || origem === "nenhum") {
    return {
      ...base, status: "erro", origem, alunoNome: nome, turmaNome, totalLivros,
      acao: { tipo: "corrigir" },
      detalhe: "Não foi possível identificar o aluno pelo nome do arquivo nem pelo conteúdo.",
    };
  }
  // ❌ Arquivo sem dados de leitura aproveitáveis.
  if (linhasValidas.length === 0) {
    return {
      ...base, status: "erro", origem, alunoNome: nome, turmaNome, totalLivros,
      acao: { tipo: "corrigir" },
      detalhe: "Nenhum registro de leitura válido neste arquivo.",
    };
  }
  // ✅/⚠️ Casou com um aluno já cadastrado.
  if (corresp?.aluno_id && (corresp.status === "exato" || corresp.status === "provavel")) {
    const baixa = corresp.status === "provavel";
    return {
      ...base, status: baixa ? "alerta" : "ok", origem, totalLivros,
      alunoNome: corresp.aluno_nome ?? nome, turmaNome,
      acao: { tipo: "importar", alunoId: corresp.aluno_id },
      detalhe: baixa ? `Correspondência provável (${corresp.similaridade ?? "?"}%). Confira o aluno.` : "",
    };
  }
  // ✅ Não estava cadastrado, mas a turma do relatório é conhecida: cria automático.
  if (turmaId) {
    return {
      ...base, status: "ok", origem, alunoNome: nome, turmaNome, totalLivros,
      acao: { tipo: "criar", turmaId },
      detalhe: "Aluno novo — será criado nesta turma.",
    };
  }
  // ⚠️ Nome lido, mas sem cadastro e sem turma para criar: precisa de correção.
  return {
    ...base, status: "pendente", origem, alunoNome: nome, turmaNome: "", totalLivros,
    acao: { tipo: "corrigir" },
    detalhe: "Aluno não encontrado. Escolha a turma e o aluno em “Corrigir”.",
  };
}

function BarraProgresso({ atual, total, rotulo }: { atual: number; total: number; rotulo: string }) {
  const pct = total > 0 ? Math.round((atual / total) * 100) : 0;
  return (
    <div>
      <div className="mb-2 flex items-center justify-between text-sm">
        <span className="font-medium">{rotulo}</span>
        <span className="tabular-nums text-zinc-500 dark:text-zinc-400">{atual} de {total} · {pct}%</span>
      </div>
      <div className="h-2.5 w-full overflow-hidden rounded-full bg-zinc-200 dark:bg-zinc-800">
        <div
          className="h-full rounded-full bg-indigo-600 transition-all duration-300"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

export default function ImportacaoLote({
  escolaId,
  turmas,
  aoConcluir,
}: {
  escolaId: number;
  turmas: Turma[];
  aoConcluir?: () => void;
}) {
  const [fase, setFase] = useState<Fase>("selecao");
  const [arquivos, setArquivos] = useState<File[]>([]);
  const [itens, setItens] = useState<ItemLote[]>([]);
  const [progresso, setProgresso] = useState({ atual: 0, total: 0 });
  const [editando, setEditando] = useState<string | null>(null);
  const [arrastando, setArrastando] = useState(false);
  const [tempoMs, setTempoMs] = useState(0);
  const inputRef = useRef<HTMLInputElement | null>(null);

  // --- Seleção de arquivos ---------------------------------------------------
  function adicionar(novos: FileList | File[]) {
    const pdfs = Array.from(novos).filter(
      (f) => f.name.toLowerCase().endsWith(".pdf") || f.type === "application/pdf",
    );
    setArquivos((atuais) => {
      const chaves = new Set(atuais.map((f) => `${f.name}:${f.size}`));
      const mesclados = [...atuais];
      for (const f of pdfs) {
        const chave = `${f.name}:${f.size}`;
        if (!chaves.has(chave)) {
          chaves.add(chave);
          mesclados.push(f);
        }
      }
      return mesclados;
    });
  }

  function removerArquivo(indice: number) {
    setArquivos((atuais) => atuais.filter((_, i) => i !== indice));
  }

  function onDrop(e: DragEvent) {
    e.preventDefault();
    setArrastando(false);
    if (e.dataTransfer.files?.length) adicionar(e.dataTransfer.files);
  }

  // --- Etapa 2: análise (uma requisição por arquivo, com progresso real) -----
  async function analisarTodos() {
    if (arquivos.length === 0) return;
    setFase("analisando");
    setItens([]);
    const total = arquivos.length;
    const acumulados: ItemLote[] = [];
    for (let i = 0; i < total; i++) {
      const arquivo = arquivos[i];
      setProgresso({ atual: i, total });
      let item: ItemLote;
      try {
        const dados = new FormData();
        dados.append("arquivo", arquivo);
        const analise = await apiUpload<Analise>(`/escolas/${escolaId}/importacoes/analisar`, dados);
        item = montarItem(arquivo, i, analise, turmas);
      } catch (e) {
        item = {
          id: `${i}-${arquivo.name}`, nome: arquivo.name, arquivo, analise: null,
          status: "erro", origem: "nenhum", alunoNome: "", turmaNome: "", totalLivros: 0,
          acao: { tipo: "corrigir" }, corrigido: false, ignorado: false,
          detalhe: e instanceof Error ? e.message : "Falha ao ler o PDF.",
        };
      }
      acumulados.push(item);
      setItens([...acumulados]); // conferência vai se preenchendo ao vivo
    }
    setProgresso({ atual: total, total });
    setFase("conferencia");
  }

  // --- Conferência: ações por arquivo ----------------------------------------
  function alternarIgnorar(id: string) {
    setItens((atuais) =>
      atuais.map((it) => (it.id === id ? { ...it, ignorado: !it.ignorado } : it)),
    );
  }

  function vincular(aluno: Aluno, turmaNome: string) {
    if (!editando) return;
    setItens((atuais) =>
      atuais.map((it) =>
        it.id === editando
          ? {
              ...it, status: "ok", alunoNome: aluno.nome, turmaNome,
              acao: { tipo: "importar", alunoId: aluno.id },
              corrigido: true, ignorado: false,
              detalhe: "Aluno definido manualmente.",
            }
          : it,
      ),
    );
    setEditando(null);
  }

  // --- Etapa 4: importação (só válidos) + recálculo único ---------------------
  async function importarTodos() {
    const alvo = itens.filter(importavel);
    if (alvo.length === 0) return;
    setFase("importando");
    const inicio = Date.now();
    const total = alvo.length;
    const mapa = new Map(itens.map((it) => [it.id, { ...it }] as [string, ItemLote]));
    let feitos = 0;
    for (const it of alvo) {
      setProgresso({ atual: feitos, total });
      try {
        const linhas = it
          .analise!.linhas.filter((l) => l.erros.length === 0)
          .map((l) => ({
            nome: l.nome,
            dados: l.dados,
            aluno_id: it.acao.tipo === "importar" ? it.acao.alunoId : null,
            criar_em_turma_id: it.acao.tipo === "criar" ? it.acao.turmaId : null,
          }));
        await api(`/escolas/${escolaId}/importacoes/confirmar`, {
          method: "POST",
          body: JSON.stringify({
            plataforma: it.analise!.plataforma,
            formato: it.analise!.formato,
            tipo: it.analise!.tipo,
            arquivo_token: it.analise!.arquivo_token,
            arquivo_nome: it.analise!.arquivo_nome,
            linhas,
            recalcular: false,
          }),
        });
        mapa.get(it.id)!.resultado = "importado";
      } catch {
        mapa.get(it.id)!.resultado = "erro";
      }
      feitos += 1;
      setProgresso({ atual: feitos, total });
      setItens([...mapa.values()]);
    }
    // Marca os que ficaram de fora (ignorados / ainda pendentes de correção).
    for (const it of mapa.values()) {
      if (it.resultado) continue;
      it.resultado = it.ignorado ? "ignorado" : "pendente";
    }
    // Um único recálculo ao final (evita dezenas de recálculos na turma toda).
    try {
      await api(`/escolas/${escolaId}/importacoes/recalcular`, { method: "POST" });
    } catch {
      /* dados já gravados; o recálculo pode ser refeito na próxima importação */
    }
    setTempoMs(Date.now() - inicio);
    setItens([...mapa.values()]);
    setFase("relatorio");
    aoConcluir?.();
  }

  function recomecar() {
    setArquivos([]);
    setItens([]);
    setProgresso({ atual: 0, total: 0 });
    setTempoMs(0);
    setFase("selecao");
  }

  // --- Estatísticas para os controles ----------------------------------------
  const prontos = useMemo(() => itens.filter(importavel), [itens]);
  const precisam = itens.filter((it) => !it.ignorado && !importavel(it));
  const ignorados = itens.filter((it) => it.ignorado);
  const itemEmEdicao = itens.find((it) => it.id === editando) ?? null;
  const turmaInicialDrawer =
    itemEmEdicao?.analise ? acharTurmaPorNome(turmas, itemEmEdicao.analise.turma_detectada) : null;

  // ---------------------------------------------------------------------------
  return (
    <div className="mb-6 space-y-4">
      {fase === "selecao" && (
        <Card className="p-5">
          <div
            onDragOver={(e) => {
              e.preventDefault();
              setArrastando(true);
            }}
            onDragLeave={() => setArrastando(false)}
            onDrop={onDrop}
            className={`flex flex-col items-center justify-center rounded-xl border-2 border-dashed px-6 py-10 text-center transition-colors ${
              arrastando
                ? "border-indigo-500 bg-indigo-50 dark:bg-indigo-500/10"
                : "border-zinc-300 bg-zinc-50/50 dark:border-zinc-700 dark:bg-zinc-800/30"
            }`}
          >
            <UploadCloud size={38} className="text-indigo-500" />
            <p className="mt-3 text-base font-medium">Arraste os relatórios em PDF aqui</p>
            <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">
              Selecione todos os relatórios individuais de uma turma de uma só vez — dezenas ou centenas.
            </p>
            <input
              ref={inputRef}
              type="file"
              accept=".pdf"
              multiple
              className="hidden"
              onChange={(e) => {
                if (e.target.files) adicionar(e.target.files);
                e.target.value = "";
              }}
            />
            <Botao variante="neutro" className="mt-4" onClick={() => inputRef.current?.click()}>
              <FileText size={15} /> Escolher arquivos
            </Botao>
          </div>

          {arquivos.length > 0 && (
            <div className="mt-4">
              <div className="mb-2 flex items-center justify-between">
                <p className="text-sm font-medium">
                  {arquivos.length} arquivo{arquivos.length === 1 ? "" : "s"} selecionado
                  {arquivos.length === 1 ? "" : "s"}
                </p>
                <button
                  className="text-xs font-medium text-zinc-500 hover:text-red-600 dark:text-zinc-400"
                  onClick={() => setArquivos([])}
                >
                  Limpar tudo
                </button>
              </div>
              <div className="max-h-56 overflow-y-auto rounded-lg border border-zinc-200 dark:border-zinc-800">
                <ul className="divide-y divide-zinc-100 dark:divide-zinc-800/60">
                  {arquivos.map((f, i) => (
                    <li key={`${f.name}:${f.size}`} className="flex items-center gap-2 px-3 py-2 text-sm">
                      <FileText size={14} className="shrink-0 text-zinc-400" />
                      <span className="min-w-0 flex-1 truncate">{f.name}</span>
                      <span className="shrink-0 tabular-nums text-xs text-zinc-400">
                        {(f.size / 1024).toFixed(0)} KB
                      </span>
                      <button
                        aria-label={`Remover ${f.name}`}
                        className="shrink-0 rounded p-1 text-zinc-400 hover:bg-zinc-100 hover:text-red-600 dark:hover:bg-zinc-800"
                        onClick={() => removerArquivo(i)}
                      >
                        <X size={14} />
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
              <div className="mt-4 flex justify-end">
                <Botao onClick={analisarTodos} disabled={arquivos.length === 0}>
                  <Play size={15} /> Analisar {arquivos.length} arquivo{arquivos.length === 1 ? "" : "s"}
                </Botao>
              </div>
            </div>
          )}
        </Card>
      )}

      {fase === "analisando" && (
        <Card className="p-6">
          <BarraProgresso
            atual={progresso.atual}
            total={progresso.total}
            rotulo={`Analisando ${progresso.atual} de ${progresso.total} arquivos...`}
          />
          <p className="mt-3 text-sm text-zinc-500 dark:text-zinc-400">
            Cada relatório é lido de forma independente. Isso pode levar alguns segundos por arquivo.
          </p>
        </Card>
      )}

      {(fase === "conferencia" || fase === "importando") && (
        <Card>
          <div className="flex flex-wrap items-center gap-2 border-b border-zinc-200 px-4 py-3 dark:border-zinc-800">
            <Users size={16} className="text-zinc-400" />
            <span className="text-sm font-medium">Conferência da importação</span>
            <Badge tom="ok">{prontos.length} pronto{prontos.length === 1 ? "" : "s"}</Badge>
            {precisam.length > 0 && <Badge tom="alerta">{precisam.length} para corrigir</Badge>}
            {ignorados.length > 0 && <Badge>{ignorados.length} ignorado{ignorados.length === 1 ? "" : "s"}</Badge>}
          </div>

          {fase === "importando" && (
            <div className="border-b border-zinc-200 px-4 py-4 dark:border-zinc-800">
              <BarraProgresso
                atual={progresso.atual}
                total={progresso.total}
                rotulo={`Processando ${progresso.atual} de ${progresso.total} arquivos...`}
              />
            </div>
          )}

          <div className="max-h-[60vh] space-y-2 overflow-y-auto p-4">
            {itens.map((it) => {
              const v = VISUAL[it.status];
              const emImport = fase === "importando";
              return (
                <div
                  key={it.id}
                  className={`rounded-xl border p-3.5 transition-opacity ${
                    it.ignorado
                      ? "border-zinc-200 bg-zinc-50 opacity-60 dark:border-zinc-800 dark:bg-zinc-800/30"
                      : "border-zinc-200 dark:border-zinc-800"
                  }`}
                >
                  <div className="flex flex-wrap items-start gap-3">
                    <v.Icone size={20} className={`mt-0.5 shrink-0 ${v.cor}`} />
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="truncate text-sm font-medium">{it.nome}</span>
                        <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${v.chip}`}>
                          {it.ignorado ? "Ignorado" : v.rotulo}
                        </span>
                        {emImport && it.resultado === "importado" && (
                          <span className="inline-flex items-center gap-1 text-xs font-medium text-emerald-600 dark:text-emerald-400">
                            <CheckCircle2 size={13} /> importado
                          </span>
                        )}
                        {emImport && it.resultado === "erro" && (
                          <span className="inline-flex items-center gap-1 text-xs font-medium text-red-600 dark:text-red-400">
                            <XCircle size={13} /> falhou
                          </span>
                        )}
                      </div>
                      <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-sm text-zinc-600 dark:text-zinc-300">
                        {it.alunoNome ? (
                          <span className="font-medium">Aluno: {it.alunoNome}</span>
                        ) : (
                          <span className="text-zinc-400">Aluno não identificado</span>
                        )}
                        {it.turmaNome && <span>· Turma: {it.turmaNome}</span>}
                        {it.acao.tipo === "criar" && <span className="text-amber-600 dark:text-amber-400">· novo</span>}
                        {it.totalLivros > 0 && (
                          <span className="inline-flex items-center gap-1 text-zinc-500 dark:text-zinc-400">
                            <BookMarked size={12} /> {it.totalLivros} livro{it.totalLivros === 1 ? "" : "s"}
                          </span>
                        )}
                      </p>
                      {it.detalhe && !it.ignorado && (
                        <p className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">{it.detalhe}</p>
                      )}
                    </div>

                    {fase === "conferencia" && (
                      <div className="flex shrink-0 items-center gap-1.5">
                        {it.analise && (
                          <Botao variante="neutro" onClick={() => setEditando(it.id)}>
                            <Pencil size={14} /> Corrigir
                          </Botao>
                        )}
                        <button
                          aria-label={it.ignorado ? "Restaurar arquivo" : "Ignorar arquivo"}
                          title={it.ignorado ? "Restaurar" : "Ignorar"}
                          className="rounded-lg border border-zinc-200 p-2 text-zinc-500 transition-colors hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800"
                          onClick={() => alternarIgnorar(it.id)}
                        >
                          {it.ignorado ? <RotateCcw size={14} /> : <Ban size={14} />}
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>

          {fase === "conferencia" && (
            <div className="flex flex-wrap items-center justify-end gap-3 border-t border-zinc-200 px-4 py-3 dark:border-zinc-800">
              <span className="mr-auto text-sm text-zinc-600 dark:text-zinc-300">
                {prontos.length > 0
                  ? `${prontos.length} arquivo(s) serão importados.`
                  : "Nenhum arquivo pronto — corrija os pendentes para continuar."}
                {precisam.length > 0 && ` ${precisam.length} ainda precisam de correção.`}
              </span>
              <Botao variante="neutro" onClick={recomecar}>Recomeçar</Botao>
              <Botao onClick={importarTodos} disabled={prontos.length === 0}>
                <CheckCircle2 size={15} /> Importar todos ({prontos.length})
              </Botao>
            </div>
          )}
        </Card>
      )}

      {fase === "relatorio" && (
        <RelatorioFinal itens={itens} tempoMs={tempoMs} aoRecomecar={recomecar} />
      )}

      <SeletorAlunoDrawer
        escolaId={escolaId}
        aberto={editando !== null}
        turmas={turmas}
        turmaInicial={turmaInicialDrawer}
        nomePdf={itemEmEdicao ? `${itemEmEdicao.nome}${itemEmEdicao.alunoNome ? ` — ${itemEmEdicao.alunoNome}` : ""}` : ""}
        aoFechar={() => setEditando(null)}
        aoConfirmar={vincular}
      />
    </div>
  );
}

/** Resumo final: cartões com os totais + a lista dos que ficaram de fora. */
function RelatorioFinal({
  itens,
  tempoMs,
  aoRecomecar,
}: {
  itens: ItemLote[];
  tempoMs: number;
  aoRecomecar: () => void;
}) {
  const enviados = itens.length;
  const importados = itens.filter((i) => i.resultado === "importado");
  const corrigidos = importados.filter((i) => i.corrigido);
  const ignorados = itens.filter((i) => i.resultado === "ignorado");
  const erros = itens.filter((i) => i.resultado === "erro");
  const pendentes = itens.filter((i) => i.resultado === "pendente");
  const naoImportados = [...erros, ...pendentes];

  const seg = Math.round(tempoMs / 1000);
  const tempo = seg < 60 ? `${seg}s` : `${Math.floor(seg / 60)}min ${seg % 60}s`;

  const cartoes: { rotulo: string; valor: number; cor: string; extra?: string }[] = [
    { rotulo: "Enviados", valor: enviados, cor: "text-zinc-900 dark:text-zinc-100" },
    {
      rotulo: "Importados",
      valor: importados.length,
      cor: "text-emerald-600 dark:text-emerald-400",
      extra: corrigidos.length > 0 ? `${corrigidos.length} corrigido(s) à mão` : undefined,
    },
    { rotulo: "Ignorados", valor: ignorados.length, cor: "text-zinc-500 dark:text-zinc-400" },
    { rotulo: "Não resolvidos", valor: pendentes.length, cor: "text-amber-600 dark:text-amber-400" },
    { rotulo: "Erros", valor: erros.length, cor: "text-red-600 dark:text-red-400" },
  ];

  return (
    <Card>
      <div className="flex items-center gap-2 border-b border-zinc-200 px-4 py-3 dark:border-zinc-800">
        <CheckCircle2 size={18} className="text-emerald-600" />
        <span className="text-sm font-medium">Importação em lote concluída</span>
        <span className="ml-auto inline-flex items-center gap-1 text-sm text-zinc-500 dark:text-zinc-400">
          <Clock size={14} /> {tempo}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-3 p-4 sm:grid-cols-5">
        {cartoes.map((c) => (
          <div key={c.rotulo} className="rounded-xl border border-zinc-200 p-3 text-center dark:border-zinc-800">
            <p className={`text-2xl font-semibold tabular-nums ${c.cor}`}>{c.valor}</p>
            <p className="mt-0.5 text-xs font-medium text-zinc-500 dark:text-zinc-400">{c.rotulo}</p>
            {c.extra && <p className="mt-0.5 text-[11px] text-zinc-400">{c.extra}</p>}
          </div>
        ))}
      </div>

      {naoImportados.length > 0 && (
        <div className="border-t border-zinc-200 px-4 py-3 dark:border-zinc-800">
          <p className="mb-2 text-sm font-medium text-amber-700 dark:text-amber-300">
            {naoImportados.length} arquivo(s) não foram importados:
          </p>
          <ul className="space-y-1 text-sm text-zinc-600 dark:text-zinc-300">
            {naoImportados.map((it) => (
              <li key={it.id} className="flex items-start gap-2">
                {it.resultado === "erro" ? (
                  <XCircle size={15} className="mt-0.5 shrink-0 text-red-500" />
                ) : (
                  <AlertTriangle size={15} className="mt-0.5 shrink-0 text-amber-500" />
                )}
                <span className="min-w-0">
                  <span className="font-medium">{it.nome}</span>
                  {it.detalhe && <span className="text-zinc-500 dark:text-zinc-400"> — {it.detalhe}</span>}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="flex justify-end gap-3 border-t border-zinc-200 px-4 py-3 dark:border-zinc-800">
        <Botao onClick={aoRecomecar}>
          <UploadCloud size={15} /> Nova importação em lote
        </Botao>
      </div>
    </Card>
  );
}
