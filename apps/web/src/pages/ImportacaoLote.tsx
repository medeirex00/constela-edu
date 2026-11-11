/**
 * Importação em LOTE — visão da tela.
 *
 * Todo o estado e o processamento vivem no ImportacaoLoteContext (global):
 * a análise/importação continuam rodando se o usuário navegar para outras
 * telas, e um indicador flutuante (Layout) mostra o progresso. Esta página
 * apenas exibe o estado atual e dispara as ações.
 *
 * Identidade v2: passo a passo no topo (arquivos → análise → conferência →
 * gravação), itens da conferência como linhas com ícone em quadrado pastel e o
 * relatório final em blocos de indicador. "Importar todos" pede confirmação
 * (com o resumo do que vai ser gravado) antes de gravar.
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
  UserPlus,
  Users,
  X,
  XCircle,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type DragEvent } from "react";

import { PassosImportacao } from "../components/PassosImportacao";
import SeletorAlunoDrawer from "../components/SeletorAlunoDrawer";
import {
  Badge,
  Botao,
  BotaoIcone,
  Campo,
  Card,
  Confirmacao,
  IconePastel,
  estiloInput,
  type TomPastel,
} from "../components/ui";
import { useApp } from "../context/AppContext";
import {
  importavel,
  useImportacaoLote,
  type EstadoRecalculo,
  type ItemLote,
  type StatusItem,
} from "../context/ImportacaoLoteContext";
import {
  dataDoRelatorioValida,
  diaPorExtenso,
  exigeDataDoRelatorio,
  hojeEmBrasilia,
  primeiroDiaDoRelatorio,
  problemaDaDataDoRelatorio,
} from "../lib/dataRelatorio";
import { acharTurmaPorNome } from "../lib/nomes";

const VISUAL: Record<StatusItem, { Icone: LucideIcon; tom: TomPastel; chip: string; rotulo: string }> = {
  ok: {
    Icone: CheckCircle2,
    tom: "verde",
    chip: "bg-emerald-50 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300",
    rotulo: "Pronto",
  },
  alerta: {
    Icone: AlertTriangle,
    tom: "ambar",
    chip: "bg-ouro-50 text-ouro-700 dark:bg-ouro-400/15 dark:text-ouro-300",
    rotulo: "Confira",
  },
  pendente: {
    Icone: AlertTriangle,
    tom: "ambar",
    chip: "bg-orange-50 text-orange-700 dark:bg-orange-500/15 dark:text-orange-300",
    rotulo: "Ação necessária",
  },
  erro: {
    Icone: XCircle,
    tom: "rosa",
    chip: "bg-rose-50 text-rose-700 dark:bg-rose-500/15 dark:text-rose-300",
    rotulo: "Não identificado",
  },
};

/** As etapas do lote, na ordem do contexto (seleção → … → relatório). */
const PASSOS_LOTE = ["Escolher arquivos", "Análise", "Conferência", "Gravação"] as const;
const ETAPA_DA_FASE: Record<string, number> = {
  selecao: 0, analisando: 1, conferencia: 2, importando: 3, relatorio: 4,
};

function BarraDoLote({ atual, total, rotulo }: { atual: number; total: number; rotulo: string }) {
  const pct = total > 0 ? Math.round((atual / total) * 100) : 0;
  return (
    <div>
      <div className="mb-2 flex items-center justify-between gap-3 text-sm">
        <span className="font-semibold text-zinc-800 dark:text-zinc-100">{rotulo}</span>
        <span className="tabular-nums text-zinc-500 dark:text-zinc-400">{atual} de {total} · {pct}%</span>
      </div>
      <div
        role="progressbar"
        aria-label={rotulo}
        aria-valuemin={0}
        aria-valuemax={total}
        aria-valuenow={atual}
        className="h-2.5 w-full overflow-hidden rounded-full bg-zinc-100 dark:bg-zinc-800"
      >
        <div
          className="h-full rounded-full bg-gradient-to-r from-indigo-500 to-indigo-600 transition-all duration-300 motion-reduce:transition-none"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

export default function ImportacaoLote({ aoConcluir }: { aoConcluir?: () => void }) {
  const { escolaId, escolaAtual } = useApp();
  const {
    fase, arquivos, itens, progresso, tempoMs, turmas,
    adicionar, removerArquivo, limparArquivos, analisarTodos, importarTodos,
    alternarIgnorar, vincular, recomecar, recalculo, recalculando, refazerRecalculo,
    erroTurmas, recarregandoTurmas, recarregarTurmas,
  } = useImportacaoLote();

  const [editando, setEditando] = useState<string | null>(null);
  const [arrastando, setArrastando] = useState(false);
  const [confirmando, setConfirmando] = useState(false);
  // Data do relatório ("AAAA-MM-DD") para os arquivos de total acumulado — começa
  // vazia (nunca presume hoje) e zera a cada lote novo.
  const [dataRelatorio, setDataRelatorio] = useState("");
  const inputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (fase === "selecao") setDataRelatorio("");
  }, [fase]);

  // Ao concluir (relatório final), atualiza o histórico da página-mãe.
  useEffect(() => {
    if (fase === "relatorio") aoConcluir?.();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fase]);

  function onDrop(e: DragEvent) {
    e.preventDefault();
    setArrastando(false);
    if (e.dataTransfer.files?.length) adicionar(e.dataTransfer.files);
  }

  const prontos = useMemo(() => itens.filter(importavel), [itens]);
  const precisam = itens.filter((it) => !it.ignorado && !importavel(it));
  const ignorados = itens.filter((it) => it.ignorado);
  const novos = prontos.filter((it) => it.acao.tipo === "criar").length;
  // Política "bloquear" da escola (a matrícula vem da Lista Piloto): o backend
  // não cria ficha para quem não casar — a tela avisa antes de importar.
  const criacaoBloqueada = itens.some((it) => it.analise?.criacao_bloqueada_por_politica);
  const itemEmEdicao = itens.find((it) => it.id === editando) ?? null;
  // A turma em que o drawer começa: a que a prévia decidiu para o aluno novo; senão a
  // única turma cadastrada da sala do relatório (série e letra inteiras).
  const turmaInicialDrawer = itemEmEdicao?.analise
    ? itemEmEdicao.analise.linhas.find((l) => l.correspondencia)?.correspondencia?.turma_id
      ?? acharTurmaPorNome(turmas, itemEmEdicao.analise.turma_detectada)
    : null;
  // Algum arquivo pronto é total acumulado (sem "Intervalo de datas")? Então a data
  // do relatório é obrigatória — o relatório individual (leituras) não precisa.
  const exigeData = prontos.some((it) => it.analise && exigeDataDoRelatorio(it.analise));
  const hoje = hojeEmBrasilia();
  // Mínimo: 1º de janeiro do ano letivo anterior (a mesma regra do servidor).
  const anoLetivo = escolaAtual?.ano_letivo_ativo ?? null;
  const primeiroDia = primeiroDiaDoRelatorio(anoLetivo);
  const dataOk = !exigeData || dataDoRelatorioValida(dataRelatorio, undefined, anoLetivo);

  function gravar() {
    setConfirmando(false);
    void importarTodos(dataRelatorio);
  }

  return (
    <div className="mb-8 space-y-5">
      <Card className="px-6 py-4">
        <PassosImportacao passos={PASSOS_LOTE} atual={ETAPA_DA_FASE[fase] ?? 0} rotulo="Etapas da importação em lote" />
      </Card>

      {fase === "selecao" && (
        <Card className="p-6">
          <div
            onDragOver={(e) => {
              e.preventDefault();
              setArrastando(true);
            }}
            onDragLeave={() => setArrastando(false)}
            onDrop={onDrop}
            className={`flex flex-col items-center justify-center rounded-2xl border-2 border-dashed px-6 py-12 text-center transition-colors ${
              arrastando
                ? "border-indigo-500 bg-indigo-50 dark:bg-indigo-500/10"
                : "border-zinc-300 bg-zinc-50/70 dark:border-zinc-700 dark:bg-zinc-800/30"
            }`}
          >
            <IconePastel icone={UploadCloud} tom="violeta" tamanho="lg" />
            <p className="mt-4 text-[17px] font-semibold text-zinc-900 dark:text-white">Arraste os relatórios em PDF aqui</p>
            <p className="mt-1 max-w-xl text-sm text-zinc-500 dark:text-zinc-400">
              Selecione todos os relatórios individuais de uma turma de uma só vez — dezenas ou centenas.
              Você pode navegar pelo sistema enquanto a importação acontece.
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
            <Botao variante="secundario" className="mt-5" onClick={() => inputRef.current?.click()}>
              <FileText size={15} aria-hidden /> Escolher arquivos
            </Botao>
          </div>

          {arquivos.length > 0 && (
            <div className="mt-5">
              <div className="mb-2 flex items-center justify-between gap-3">
                <p className="text-sm font-semibold text-zinc-800 dark:text-zinc-100">
                  {arquivos.length} arquivo{arquivos.length === 1 ? "" : "s"} selecionado
                  {arquivos.length === 1 ? "" : "s"}
                </p>
                <Botao variante="fantasma" tamanho="sm" onClick={limparArquivos}>
                  Limpar tudo
                </Botao>
              </div>
              <div className="max-h-56 overflow-y-auto rounded-2xl border border-zinc-200 dark:border-zinc-800">
                <ul className="divide-y divide-zinc-100 dark:divide-zinc-800/60">
                  {arquivos.map((f, i) => (
                    <li key={`${f.name}:${f.size}`} className="flex items-center gap-2.5 px-4 py-2.5 text-sm">
                      <FileText size={15} aria-hidden className="shrink-0 text-indigo-500" />
                      <span className="min-w-0 flex-1 truncate" title={f.name}>{f.name}</span>
                      <span className="shrink-0 tabular-nums text-xs text-zinc-500 dark:text-zinc-400">
                        {(f.size / 1024).toFixed(0)} KB
                      </span>
                      <button
                        type="button"
                        aria-label={`Remover ${f.name}`}
                        className="shrink-0 rounded-lg p-1.5 text-zinc-500 hover:bg-rose-50 hover:text-rose-600 dark:hover:bg-rose-500/10"
                        onClick={() => removerArquivo(i)}
                      >
                        <X size={14} aria-hidden />
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
              <div className="mt-5 flex justify-end">
                <Botao onClick={analisarTodos} disabled={arquivos.length === 0}>
                  <Play size={15} aria-hidden /> Analisar {arquivos.length} arquivo{arquivos.length === 1 ? "" : "s"}
                </Botao>
              </div>
            </div>
          )}
        </Card>
      )}

      {fase === "analisando" && (
        <Card className="p-6">
          <BarraDoLote
            atual={progresso.atual}
            total={progresso.total}
            rotulo={`Analisando ${progresso.atual} de ${progresso.total} arquivos...`}
          />
          <p className="mt-3 text-sm text-zinc-500 dark:text-zinc-400">
            Pode continuar usando o sistema — a análise segue em segundo plano e o
            indicador no canto da tela mostra o andamento.
          </p>
        </Card>
      )}

      {(fase === "conferencia" || fase === "importando") && (
        <Card className="overflow-hidden">
          <div className="flex flex-wrap items-center gap-3 px-6 pb-4 pt-5">
            <IconePastel icone={Users} tom="violeta" />
            <span className="text-[17px] font-semibold text-zinc-900 dark:text-white">Conferência da importação</span>
            <Badge tom="ok">{prontos.length} pronto{prontos.length === 1 ? "" : "s"}</Badge>
            {precisam.length > 0 && <Badge tom="alerta">{precisam.length} para corrigir</Badge>}
            {ignorados.length > 0 && <Badge>{ignorados.length} ignorado{ignorados.length === 1 ? "" : "s"}</Badge>}
          </div>

          {/* As turmas da escola não carregaram: o aluno novo fica sem turma e o
              "Corrigir" não as lista. Antes a falha era engolida em silêncio. */}
          {fase === "conferencia" && erroTurmas && (
            <div className="px-6 pb-4">
              <div role="alert" className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800 dark:border-rose-500/20 dark:bg-rose-500/10 dark:text-rose-200">
                <p className="font-semibold">Não foi possível carregar as turmas da escola.</p>
                <p className="mt-0.5">
                  Sem elas, os arquivos de aluno novo ficam sem turma e “Corrigir” não mostra as
                  turmas. Detalhe: {erroTurmas}
                </p>
                <Botao variante="secundario" tamanho="sm" className="mt-3" disabled={recarregandoTurmas}
                  onClick={() => { void recarregarTurmas(); }}>
                  <RotateCcw size={14} aria-hidden /> {recarregandoTurmas ? "Carregando…" : "Tentar de novo"}
                </Botao>
              </div>
            </div>
          )}

          {criacaoBloqueada && (
            <p
              className="mx-6 mb-4 rounded-2xl border border-ouro-200 bg-ouro-50 px-4 py-2.5 text-sm text-zinc-800 dark:border-ouro-400/25 dark:bg-ouro-400/10 dark:text-zinc-100"
              role="status"
            >
              A matrícula desta escola vem da Lista Piloto: aluno sem ficha não é criado por
              esta importação — vai para Revisões de identidade, para um gestor apontar a
              ficha certa.
            </p>
          )}

          {fase === "importando" && (
            <div className="mx-6 mb-4 rounded-2xl bg-zinc-50 px-4 py-4 dark:bg-zinc-800/40">
              <BarraDoLote
                atual={progresso.atual}
                total={progresso.total}
                rotulo={`Processando ${progresso.atual} de ${progresso.total} arquivos...`}
              />
            </div>
          )}

          {/* Lista longa (centenas de PDFs): a rolagem interna só entra no desktop,
              onde a altura sobra; no tablet a página rola uma vez só. */}
          <div className="space-y-2 px-6 pb-5 lg:max-h-[60vh] lg:overflow-y-auto">
            {itens.map((it) => {
              const v = VISUAL[it.status];
              const emImport = fase === "importando";
              // Recusado pelo servidor: o motivo dele, não o texto da análise.
              const detalhe = textoDoItem(it);
              return (
                <div
                  key={it.id}
                  className={`rounded-2xl border p-4 transition-opacity ${
                    it.ignorado
                      ? "border-zinc-200 bg-zinc-50 opacity-60 dark:border-zinc-800 dark:bg-zinc-800/30"
                      : "border-zinc-200/80 bg-white dark:border-zinc-800 dark:bg-zinc-900"
                  }`}
                >
                  <div className="flex flex-wrap items-start gap-3">
                    <IconePastel icone={it.ignorado ? Ban : v.Icone} tom={it.ignorado ? "neutro" : v.tom} tamanho="sm" />
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="truncate text-sm font-semibold text-zinc-900 dark:text-white" title={it.nome}>{it.nome}</span>
                        <span className={`rounded-full px-2.5 py-0.5 text-[11px] font-semibold ${it.ignorado ? "bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300" : v.chip}`}>
                          {it.ignorado ? "Ignorado" : v.rotulo}
                        </span>
                        {emImport && it.resultado === "importado" && (
                          <span className="inline-flex items-center gap-1 text-xs font-semibold text-emerald-700 dark:text-emerald-400">
                            <CheckCircle2 size={13} aria-hidden /> importado
                          </span>
                        )}
                        {emImport && it.resultado === "erro" && (
                          <span className="inline-flex items-center gap-1 text-xs font-semibold text-rose-700 dark:text-rose-400">
                            <XCircle size={13} aria-hidden /> falhou
                          </span>
                        )}
                      </div>
                      <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-sm text-zinc-600 dark:text-zinc-300">
                        {it.alunoNome ? (
                          <span className="font-medium">Aluno: {it.alunoNome}</span>
                        ) : (
                          <span className="text-zinc-500 dark:text-zinc-400">Aluno não identificado</span>
                        )}
                        {it.turmaNome && <span>· Turma: {it.turmaNome}</span>}
                        {it.acao.tipo === "criar" && <span className="font-medium text-ouro-700 dark:text-ouro-300">· novo</span>}
                        {it.totalLivros > 0 && (
                          <span className="inline-flex items-center gap-1 text-zinc-500 dark:text-zinc-400">
                            <BookMarked size={12} aria-hidden /> {it.totalLivros} livro{it.totalLivros === 1 ? "" : "s"}
                          </span>
                        )}
                      </p>
                      {detalhe && !it.ignorado && (
                        <p className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">{detalhe}</p>
                      )}
                    </div>

                    {fase === "conferencia" && (
                      <div className="flex shrink-0 items-center gap-1.5">
                        {it.analise && (
                          <Botao variante="secundario" tamanho="sm" onClick={() => setEditando(it.id)}>
                            <Pencil size={14} aria-hidden /> Corrigir
                          </Botao>
                        )}
                        <BotaoIcone
                          rotulo={it.ignorado ? "Restaurar arquivo" : "Ignorar arquivo"}
                          className="h-9 w-9"
                          onClick={() => alternarIgnorar(it.id)}
                        >
                          {it.ignorado ? <RotateCcw size={15} aria-hidden /> : <Ban size={15} aria-hidden />}
                        </BotaoIcone>
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>

          {fase === "conferencia" && exigeData && (
            // Relatório de total acumulado no lote: os números entram NA DATA do
            // relatório (sem ela, um arquivo antigo viraria "o dado de hoje").
            <div className="mx-6 mb-4 rounded-2xl border border-ouro-200 bg-ouro-50 px-4 py-3 dark:border-ouro-400/25 dark:bg-ouro-400/10">
              <div className="max-w-xs">
                <Campo rotulo="Data dos relatórios (obrigatória)">
                  <input
                    type="date"
                    className={estiloInput}
                    value={dataRelatorio}
                    min={primeiroDia}
                    max={hoje}
                    required
                    aria-describedby="ajuda-data-relatorio-lote"
                    aria-invalid={dataRelatorio !== "" && !dataOk}
                    onChange={(e) => setDataRelatorio(e.target.value)}
                  />
                </Campo>
              </div>
              <p id="ajuda-data-relatorio-lote" className="mt-1.5 text-xs text-zinc-700 dark:text-zinc-200">
                Há relatório de total acumulado neste lote: informe o dia em que ele foi gerado na
                plataforma. Os números entram nessa data — um arquivo antigo não passa por dado de
                hoje nem apaga o que a sincronização já trouxe.
              </p>
              {dataRelatorio !== "" && !dataOk && (
                <p className="mt-1 text-xs font-semibold text-rose-700 dark:text-rose-300" role="alert">
                  {problemaDaDataDoRelatorio(dataRelatorio, undefined, anoLetivo)}
                </p>
              )}
            </div>
          )}

          {fase === "conferencia" && (
            <div className="flex flex-wrap items-center justify-end gap-3 border-t border-zinc-100 bg-zinc-50/60 px-6 py-4 dark:border-zinc-800 dark:bg-zinc-800/30">
              <span className="mr-auto text-sm text-zinc-700 dark:text-zinc-200">
                {prontos.length > 0
                  ? `${prontos.length} arquivo(s) serão importados.`
                  : "Nenhum arquivo pronto — corrija os pendentes para continuar."}
                {precisam.length > 0 && ` ${precisam.length} ainda precisam de correção.`}
                {prontos.length > 0 && !dataOk && " Informe a data dos relatórios para importar."}
              </span>
              <Botao variante="secundario" onClick={recomecar}>Recomeçar</Botao>
              <Botao onClick={() => setConfirmando(true)} disabled={prontos.length === 0 || !dataOk}>
                <CheckCircle2 size={15} aria-hidden /> Importar todos ({prontos.length})
              </Botao>
            </div>
          )}
        </Card>
      )}

      {fase === "relatorio" && (
        <RelatorioFinal itens={itens} tempoMs={tempoMs} aoRecomecar={recomecar}
          recalculo={recalculo} recalculando={recalculando} aoRefazerRecalculo={refazerRecalculo} />
      )}

      {/* Confirmação ANTES de gravar (o resumo vem da conferência na tela). */}
      <Confirmacao
        titulo={`Gravar ${prontos.length} arquivo(s)?`}
        aberto={confirmando && fase === "conferencia"}
        aoFechar={() => setConfirmando(false)}
        aoConfirmar={gravar}
        rotuloConfirmar="Gravar importação"
        desabilitado={prontos.length === 0 || !dataOk}
      >
        <ul className="space-y-1.5">
          <li className="flex items-center gap-2">
            <CheckCircle2 size={15} aria-hidden className="shrink-0 text-emerald-600" />
            {prontos.length} arquivo(s) prontos entram na importação
          </li>
          {exigeData && dataOk && (
            <li className="flex items-center gap-2">
              <Clock size={15} aria-hidden className="shrink-0 text-zinc-500" />
              Data dos relatórios de total acumulado: {diaPorExtenso(dataRelatorio)}
            </li>
          )}
          {novos > 0 && (
            <li className="flex items-center gap-2">
              <UserPlus size={15} aria-hidden className="shrink-0 text-ouro-700 dark:text-ouro-300" />
              {novos} com aluno novo{criacaoBloqueada ? " — pela política da escola, vão para Revisões de identidade" : ""}
            </li>
          )}
          {precisam.length > 0 && (
            <li className="flex items-center gap-2">
              <AlertTriangle size={15} aria-hidden className="shrink-0 text-ouro-700 dark:text-ouro-300" />
              {precisam.length} sem correção ficam de fora
            </li>
          )}
          {ignorados.length > 0 && (
            <li className="flex items-center gap-2">
              <Ban size={15} aria-hidden className="shrink-0 text-zinc-500" />
              {ignorados.length} ignorado(s) ficam de fora
            </li>
          )}
        </ul>
        <p className="text-xs">
          No fim, as notas e os rankings são recalculados. Você pode navegar pelo sistema enquanto grava.
        </p>
      </Confirmacao>

      {escolaId && (
        <SeletorAlunoDrawer
          escolaId={escolaId}
          aberto={editando !== null}
          turmas={turmas}
          turmaInicial={turmaInicialDrawer}
          nomePdf={itemEmEdicao ? `${itemEmEdicao.nome}${itemEmEdicao.alunoNome ? ` — ${itemEmEdicao.alunoNome}` : ""}` : ""}
          aoFechar={() => setEditando(null)}
          aoConfirmar={(aluno, turmaNome) => {
            if (editando) vincular(editando, aluno, turmaNome);
            setEditando(null);
          }}
        />
      )}
    </div>
  );
}

/** O texto de um arquivo: o motivo da recusa do servidor quando o /confirmar falhou;
 *  senão, o que a análise disse dele. */
function textoDoItem(it: ItemLote): string {
  return it.resultado === "erro" && it.erroImportacao ? it.erroImportacao : it.detalhe;
}

/** Resumo final: blocos com os totais + a lista dos que ficaram de fora. */
function RelatorioFinal({
  itens,
  tempoMs,
  aoRecomecar,
  recalculo = null,
  recalculando = false,
  aoRefazerRecalculo,
}: {
  itens: ItemLote[];
  tempoMs: number;
  aoRecomecar: () => void;
  recalculo?: EstadoRecalculo;
  recalculando?: boolean;
  aoRefazerRecalculo?: () => void;
}) {
  const recalculoFalhou = recalculo?.estado === "falhou";
  const enviados = itens.length;
  const importados = itens.filter((i) => i.resultado === "importado");
  const corrigidos = importados.filter((i) => i.corrigido);
  const ignorados = itens.filter((i) => i.resultado === "ignorado");
  const erros = itens.filter((i) => i.resultado === "erro");
  const pendentes = itens.filter((i) => i.resultado === "pendente");
  const naoImportados = [...erros, ...pendentes];

  const seg = Math.round(tempoMs / 1000);
  const tempo = seg < 60 ? `${seg}s` : `${Math.floor(seg / 60)}min ${seg % 60}s`;

  // Cada número com ícone e cor próprios (e o rótulo em texto: a cor não é o
  // único código). Sem comparação: não existe "lote anterior" para comparar.
  const cartoes: { rotulo: string; valor: number; icone: LucideIcon; tom: TomPastel; extra?: string }[] = [
    { rotulo: "Enviados", valor: enviados, icone: FileText, tom: "violeta" },
    {
      rotulo: "Importados",
      valor: importados.length,
      icone: CheckCircle2,
      tom: "verde",
      extra: corrigidos.length > 0 ? `${corrigidos.length} corrigido(s) à mão` : undefined,
    },
    { rotulo: "Ignorados", valor: ignorados.length, icone: Ban, tom: "neutro" },
    { rotulo: "Não resolvidos", valor: pendentes.length, icone: AlertTriangle, tom: "ambar" },
    { rotulo: "Erros", valor: erros.length, icone: XCircle, tom: "rosa" },
  ];

  return (
    <Card className="overflow-hidden">
      <div className="flex flex-wrap items-center gap-3 px-6 pb-2 pt-5">
        <IconePastel icone={recalculoFalhou ? AlertTriangle : CheckCircle2} tom={recalculoFalhou ? "ambar" : "verde"} />
        <span className="text-[17px] font-semibold text-zinc-900 dark:text-white">
          {recalculoFalhou
            ? "Importação em lote gravada, mas as notas não foram recalculadas"
            : "Importação em lote concluída"}
        </span>
        <span className="ml-auto inline-flex items-center gap-1.5 rounded-full bg-zinc-100 px-2.5 py-1 text-xs font-semibold text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">
          <Clock size={13} aria-hidden /> {tempo}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-3 px-6 py-4 md:grid-cols-3 xl:grid-cols-5">
        {cartoes.map((c) => (
          <div key={c.rotulo} className="rounded-2xl bg-zinc-50 p-4 dark:bg-zinc-800/50">
            <IconePastel icone={c.icone} tom={c.tom} tamanho="sm" />
            <p className="mt-3 text-[28px] font-bold leading-none tabular-nums text-zinc-900 dark:text-white">{c.valor}</p>
            <p className="mt-1.5 text-sm font-medium text-zinc-700 dark:text-zinc-200">{c.rotulo}</p>
            {c.extra && <p className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">{c.extra}</p>}
          </div>
        ))}
      </div>

      {recalculo?.estado === "ok" && (
        <p role="status" className="mx-6 mb-4 rounded-2xl bg-emerald-50 px-4 py-2.5 text-sm text-emerald-800 dark:bg-emerald-500/10 dark:text-emerald-200">
          Notas e rankings recalculados{recalculo.mensagem ? `: ${recalculo.mensagem}` : "."}
        </p>
      )}

      {/* O recálculo final falhou: os arquivos estão gravados, mas notas e
          rankings não mudaram. Dito com todas as letras, com como refazer. */}
      {recalculo?.estado === "falhou" && (
        <div className="px-6 pb-4">
          <div role="alert" className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800 dark:border-rose-500/20 dark:bg-rose-500/10 dark:text-rose-200">
            <p className="font-semibold">O recálculo das notas e dos rankings falhou.</p>
            <p className="mt-0.5">
              Os arquivos importados já estão gravados, mas as notas e os rankings ainda
              mostram os valores de antes. Detalhe: {recalculo.erro}
            </p>
            {aoRefazerRecalculo && (
              <Botao variante="secundario" tamanho="sm" className="mt-3" disabled={recalculando} onClick={aoRefazerRecalculo}>
                <RotateCcw size={14} aria-hidden /> {recalculando ? "Recalculando…" : "Recalcular agora"}
              </Botao>
            )}
          </div>
        </div>
      )}

      {naoImportados.length > 0 && (
        <div className="border-t border-zinc-100 px-6 py-4 dark:border-zinc-800">
          <p className="mb-2 text-sm font-semibold text-ouro-700 dark:text-ouro-300">
            {naoImportados.length} arquivo(s) não foram importados:
          </p>
          <ul className="space-y-1.5 text-sm text-zinc-700 dark:text-zinc-300">
            {naoImportados.map((it) => (
              <li key={it.id} className="flex items-start gap-2">
                {it.resultado === "erro" ? (
                  <XCircle size={15} aria-hidden className="mt-0.5 shrink-0 text-rose-500" />
                ) : (
                  <AlertTriangle size={15} aria-hidden className="mt-0.5 shrink-0 text-ouro-600" />
                )}
                <span className="min-w-0">
                  <span className="font-medium">{it.nome}</span>
                  {textoDoItem(it) && <span className="text-zinc-500 dark:text-zinc-400"> — {textoDoItem(it)}</span>}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="flex justify-end gap-3 border-t border-zinc-100 bg-zinc-50/60 px-6 py-4 dark:border-zinc-800 dark:bg-zinc-800/30">
        <Botao onClick={aoRecomecar}>
          <UploadCloud size={15} aria-hidden /> Nova importação em lote
        </Botao>
      </div>
    </Card>
  );
}
