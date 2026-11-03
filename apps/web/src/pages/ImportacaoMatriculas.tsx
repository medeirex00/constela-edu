/**
 * Importação da PLANILHA DE MATRÍCULAS da escola ("Lista Piloto").
 *
 * O usuário envia UM Excel (.xls ou .xlsx) com uma aba por turma; o sistema
 * mostra a prévia (turmas + alunos detectados, marcando as que já existem) e,
 * ao confirmar, cria as turmas que faltam e matricula os alunos no ano ativo,
 * guardando nº de chamada, nascimento e a ficha cadastral completa.
 *
 * Identidade v2: passo a passo (planilha → conferência → confirmação), área de
 * soltar o arquivo (a mesma linguagem do lote), indicadores da prévia e a
 * confirmação com o resumo ANTES de gravar.
 */
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  FileSpreadsheet,
  RefreshCw,
  School,
  UploadCloud,
  UserMinus,
  UserPlus,
  Users,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useRef, useState, type DragEvent } from "react";
import { useNavigate } from "react-router-dom";

import { PassosImportacao } from "../components/PassosImportacao";
import {
  Badge, Botao, Card, Chip, Confirmacao, IconePastel, Mensagem, Vazio, classesTabela, type TomPastel,
} from "../components/ui";
import { apiUpload } from "../lib/api";

interface MatriculaTurma {
  nome: string;
  ano_escolar: string;
  turno: string | null;
  professor: string;
  sed: string;
  total_alunos: number;
  ja_existe: boolean;
  exemplos: string[];
}
interface MatriculasAnalise {
  escola_detectada: string;
  ano_letivo: number | null;
  total_turmas: number;
  total_alunos: number;
  total_registros: number;
  alunos_novos: number;
  alunos_atualizar: number;
  turmas_existentes: number;
  turmas: MatriculaTurma[];
  avisos: string[];
}
interface MatriculasResultado {
  mensagem: string;
  turmas_criadas: number;
  alunos_criados: number;
  alunos_atualizados: number;
  alunos_fora_lista?: number;
  avisos: string[];
}

const PASSOS = ["Enviar a planilha", "Conferir turmas e alunos", "Confirmar e gravar"] as const;
/** Quantos avisos aparecem de cara (o resto fica a um clique, com a contagem). */
const AVISOS_VISIVEIS = 8;

/** Bloco de indicador pequeno (número grande + rótulo), dentro de um cartão. */
function Indicador({ icone, tom, valor, rotulo }: { icone: LucideIcon; tom: TomPastel; valor: number; rotulo: string }) {
  return (
    <div className="flex items-center gap-3 rounded-2xl bg-zinc-50 p-4 dark:bg-zinc-800/50">
      <IconePastel icone={icone} tom={tom} tamanho="sm" />
      <div className="min-w-0">
        <p className="text-2xl font-bold leading-none tabular-nums text-zinc-900 dark:text-white">{valor}</p>
        <p className="mt-1 text-xs font-medium text-zinc-600 dark:text-zinc-300">{rotulo}</p>
      </div>
    </div>
  );
}

/** Lista de avisos: os primeiros à vista e o resto a um clique, COM a contagem
 *  (antes, a lista era cortada em 8 sem dizer que havia mais). */
function ListaAvisos({ avisos }: { avisos: string[] }) {
  const [todos, setTodos] = useState(false);
  if (avisos.length === 0) return null;
  const mostrados = todos ? avisos : avisos.slice(0, AVISOS_VISIVEIS);
  const ocultos = avisos.length - mostrados.length;
  return (
    <div className="rounded-2xl border border-ouro-200 bg-ouro-50 px-4 py-3 text-xs text-zinc-800 dark:border-ouro-400/25 dark:bg-ouro-400/10 dark:text-zinc-100">
      <p className="mb-1.5 flex items-center gap-1.5 font-semibold">
        <AlertTriangle size={14} aria-hidden className="text-ouro-700 dark:text-ouro-300" />
        {avisos.length} aviso{avisos.length === 1 ? "" : "s"} da planilha
      </p>
      <ul className="list-inside list-disc space-y-0.5">
        {mostrados.map((a, i) => <li key={i}>{a}</li>)}
      </ul>
      {avisos.length > AVISOS_VISIVEIS && (
        <button
          type="button"
          aria-expanded={todos}
          className="mt-2 font-semibold text-indigo-700 underline underline-offset-2 dark:text-indigo-300"
          onClick={() => setTodos((v) => !v)}
        >
          {todos ? "Mostrar só os primeiros" : `Ver mais ${ocultos} aviso${ocultos === 1 ? "" : "s"}`}
        </button>
      )}
    </div>
  );
}

export default function ImportacaoMatriculas({ escolaId, aoConcluir, aoAvancar }: {
  escolaId: number;
  aoConcluir: () => void;
  /** Quando embutido no assistente de onboarding: avança o passo em vez de
   *  navegar para o painel de integrações. Sem timer automático (WCAG 3.2.5). */
  aoAvancar?: () => void;
}) {
  const [arquivo, setArquivo] = useState<File | null>(null);
  const [analise, setAnalise] = useState<MatriculasAnalise | null>(null);
  const [resultado, setResultado] = useState<MatriculasResultado | null>(null);
  const [ocupado, setOcupado] = useState(false);
  const [erro, setErro] = useState("");
  const [confirmando, setConfirmando] = useState(false);
  const [arrastando, setArrastando] = useState(false);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const navigate = useNavigate();
  const avancar = aoAvancar ?? (() => navigate("/sincronizacao"));

  async function enviar(caminho: string, comArquivo: File) {
    const dados = new FormData();
    dados.append("arquivo", comArquivo);
    return apiUpload(`/escolas/${escolaId}/importacoes/matriculas/${caminho}`, dados);
  }

  function escolher(f: File | null) {
    setArquivo(f);
    setErro("");
  }

  function aoSoltar(e: DragEvent) {
    e.preventDefault();
    setArrastando(false);
    escolher(e.dataTransfer.files?.[0] ?? null);
  }

  async function analisar() {
    if (!arquivo) return;
    setOcupado(true); setErro(""); setResultado(null);
    try {
      setAnalise(await enviar("analisar", arquivo) as MatriculasAnalise);
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Não foi possível ler a planilha.");
    } finally {
      setOcupado(false);
    }
  }

  async function confirmar() {
    if (!arquivo) return;
    setOcupado(true); setErro("");
    try {
      const r = await enviar("confirmar", arquivo) as MatriculasResultado;
      setResultado(r);
      setAnalise(null);
      setArquivo(null);
      aoConcluir();
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Não foi possível importar.");
    } finally {
      setOcupado(false);
      setConfirmando(false);
    }
  }

  function recomecar() {
    setAnalise(null); setResultado(null); setArquivo(null); setErro("");
    if (inputRef.current) inputRef.current.value = "";
  }

  // Etapa REAL do fluxo: 0 envio, 1 conferência, 2 confirmação aberta, 3 feito.
  const etapa = resultado ? PASSOS.length : analise ? (confirmando ? 2 : 1) : 0;
  const turmasNovas = analise ? analise.turmas.filter((t) => !t.ja_existe).length : 0;

  return (
    <div className="space-y-5">
      <Card className="px-6 py-4">
        <PassosImportacao passos={PASSOS} atual={etapa} rotulo="Etapas da importação da Lista Piloto" />
      </Card>

      {resultado ? (
        <Card className="p-6">
          <div className="flex items-start gap-4">
            <IconePastel icone={CheckCircle2} tom="verde" tamanho="lg" />
            <div className="min-w-0">
              <p className="text-[15px] font-semibold text-zinc-900 dark:text-white">{resultado.mensagem}</p>
              <div className="mt-3 flex flex-wrap gap-2 text-xs">
                <Badge tom="ok">{resultado.turmas_criadas} turma(s) criada(s)</Badge>
                <Badge tom="ok">{resultado.alunos_criados} aluno(s) novo(s)</Badge>
                <Badge tom="neutro">{resultado.alunos_atualizados} atualizado(s)</Badge>
                {(resultado.alunos_fora_lista ?? 0) > 0 && (
                  <Badge tom="alerta">
                    {resultado.alunos_fora_lista} fora da lista piloto
                  </Badge>
                )}
              </div>
              {(resultado.alunos_fora_lista ?? 0) > 0 && (
                <p className="mt-3 text-xs text-ouro-700 dark:text-ouro-300">
                  {resultado.alunos_fora_lista} aluno(s) não constam mais na lista e
                  foram marcados como <strong>fora da lista piloto</strong> — continuam
                  cadastrados (nada foi apagado). Reative, transfira ou arquive cada um
                  quando quiser, na turma correspondente.
                </p>
              )}
              {resultado.avisos.length > 0 && (
                <div className="mt-3">
                  <ListaAvisos avisos={resultado.avisos} />
                </div>
              )}
            </div>
          </div>
          <div className="mt-5 flex flex-wrap items-center gap-2.5 border-t border-zinc-100 pt-5 dark:border-zinc-800">
            <Botao onClick={avancar}>
              {aoAvancar ? "Continuar" : "Configurar integrações da escola"}
              <ArrowRight size={16} aria-hidden />
            </Botao>
            <Botao variante="secundario" onClick={recomecar}>Importar outra planilha</Botao>
          </div>
        </Card>
      ) : !analise ? (
        <Card className="p-6">
          <div className="mb-5 flex items-start gap-4">
            <IconePastel icone={FileSpreadsheet} tom="violeta" tamanho="lg" />
            <p className="min-w-0 text-sm text-zinc-600 dark:text-zinc-300">
              Envie a planilha da escola com <strong>uma aba por turma</strong> (a
              "Lista Piloto"). O sistema reconhece as turmas, os alunos e todos os
              dados de cada um — cria as salas que ainda não existem e matricula os
              alunos. Nada é gravado antes da sua confirmação. Aceita <strong>.xls</strong> e <strong>.xlsx</strong>.
            </p>
          </div>
          <div
            onDragOver={(e) => { e.preventDefault(); setArrastando(true); }}
            onDragLeave={() => setArrastando(false)}
            onDrop={aoSoltar}
            className={`flex flex-col items-center justify-center rounded-2xl border-2 border-dashed px-6 py-9 text-center transition-colors ${
              arrastando
                ? "border-indigo-500 bg-indigo-50 dark:bg-indigo-500/10"
                : "border-zinc-300 bg-zinc-50/70 dark:border-zinc-700 dark:bg-zinc-800/30"
            }`}
          >
            <UploadCloud size={30} aria-hidden className="text-indigo-500" />
            {arquivo ? (
              <p className="mt-3 flex items-center gap-2 break-all text-sm font-semibold text-zinc-900 dark:text-white">
                <FileSpreadsheet size={16} aria-hidden className="shrink-0 text-emerald-600" />
                {arquivo.name}
              </p>
            ) : (
              <p className="mt-3 text-sm font-semibold text-zinc-800 dark:text-zinc-100">
                Arraste a planilha aqui ou escolha o arquivo
              </p>
            )}
            <input
              ref={inputRef}
              type="file"
              aria-label="Planilha de matrículas da escola (.xls ou .xlsx)"
              accept=".xls,.xlsx,.xlsm"
              className="hidden"
              onChange={(e) => escolher(e.target.files?.[0] ?? null)}
            />
            <Botao variante="secundario" tamanho="sm" className="mt-4" onClick={() => inputRef.current?.click()}>
              <FileSpreadsheet size={14} aria-hidden /> {arquivo ? "Trocar planilha" : "Escolher planilha"}
            </Botao>
          </div>
          {erro && <div className="mt-4"><Mensagem tipo="erro">{erro}</Mensagem></div>}
          <div className="mt-5 flex justify-end">
            <Botao disabled={!arquivo || ocupado} onClick={analisar}>
              {ocupado ? "Lendo a planilha..." : "Analisar planilha"}
            </Botao>
          </div>
        </Card>
      ) : (
        <Card className="overflow-hidden">
          <div className="flex flex-wrap items-center gap-3 px-6 pb-4 pt-5">
            <IconePastel icone={School} tom="violeta" />
            <div className="min-w-0">
              <p className="text-[17px] font-semibold text-zinc-900 dark:text-white">
                {analise.escola_detectada || "Escola"}
                {analise.ano_letivo ? ` · ${analise.ano_letivo}` : ""}
              </p>
              <p className="text-xs text-zinc-500 dark:text-zinc-400">
                {analise.total_turmas} turma(s) · {analise.total_alunos} aluno(s)
                {analise.total_registros > analise.total_alunos
                  ? ` (${analise.total_registros} registros — alguns em mais de uma turma)`
                  : ""}
              </p>
            </div>
          </div>

          {/* auto-fit: o componente também vive no Drawer estreito de Integrações e no
              assistente — as colunas seguem a largura do cartão, não a da tela. */}
          <div className="grid grid-cols-[repeat(auto-fit,minmax(10.5rem,1fr))] gap-3 px-6 pb-4">
            <Indicador icone={School} tom="violeta" valor={turmasNovas} rotulo="turma(s) nova(s)" />
            <Indicador icone={UserPlus} tom="verde" valor={analise.alunos_novos} rotulo="aluno(s) novo(s)" />
            <Indicador icone={RefreshCw} tom="azul" valor={analise.alunos_atualizar} rotulo="a atualizar" />
            <Indicador icone={Users} tom="neutro" valor={analise.turmas_existentes} rotulo="turma(s) já existente(s)" />
          </div>

          {analise.avisos.length > 0 && (
            <div className="px-6 pb-4">
              <ListaAvisos avisos={analise.avisos} />
            </div>
          )}

          {analise.turmas.length === 0 ? (
            <Vazio
              icone={FileSpreadsheet}
              titulo="Nenhuma turma encontrada na planilha"
              descricao="Confira se é a Lista Piloto da escola, com uma aba por turma, e envie de novo."
            />
          ) : (
            <div className={classesTabela.moldura}>
              <table className={classesTabela.tabela}>
                <thead>
                  <tr>
                    <th className={classesTabela.th}>Turma</th>
                    <th className={`hidden sm:table-cell ${classesTabela.th}`}>Turno</th>
                    <th className={`hidden md:table-cell ${classesTabela.th}`}>Professor(a)</th>
                    <th className={`${classesTabela.th} text-right`}>Alunos</th>
                    <th className={classesTabela.th}>Situação</th>
                  </tr>
                </thead>
                <tbody>
                  {analise.turmas.map((t, i) => (
                    <tr key={`${t.nome}-${i}`} className={classesTabela.tr}>
                      <td className={classesTabela.td}>
                        <Chip>{t.nome}</Chip>
                        <div className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">{t.exemplos.slice(0, 3).join(", ")}{t.total_alunos > 3 ? "…" : ""}</div>
                      </td>
                      <td className={`hidden sm:table-cell ${classesTabela.td} capitalize text-zinc-500 dark:text-zinc-400`}>{t.turno ?? "—"}</td>
                      <td className={`hidden md:table-cell ${classesTabela.td} text-zinc-500 dark:text-zinc-400`}>{t.professor || "—"}</td>
                      <td className={`${classesTabela.td} text-right font-bold tabular-nums text-zinc-900 dark:text-white`}>{t.total_alunos}</td>
                      <td className={classesTabela.td}>
                        <Badge tom={t.ja_existe ? "neutro" : "ok"}>
                          {t.ja_existe ? "já existe" : "nova"}
                        </Badge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {erro && <div className="px-6 pt-4"><Mensagem tipo="erro">{erro}</Mensagem></div>}
          <div className="mt-2 flex flex-wrap justify-end gap-2.5 border-t border-zinc-100 bg-zinc-50/60 px-6 py-4 dark:border-zinc-800 dark:bg-zinc-800/30">
            <Botao variante="secundario" onClick={recomecar} disabled={ocupado}>Escolher outro arquivo</Botao>
            <Botao onClick={() => setConfirmando(true)} disabled={ocupado || analise.turmas.length === 0}>
              {ocupado ? "Importando..." : `Criar turmas e matricular ${analise.total_alunos} aluno(s)`}
            </Botao>
          </div>

          {/* Confirmação ANTES de gravar: o efeito, com os números da prévia. */}
          <Confirmacao
            titulo="Gravar a Lista Piloto?"
            aberto={confirmando}
            aoFechar={() => setConfirmando(false)}
            aoConfirmar={() => { void confirmar(); }}
            rotuloConfirmar={ocupado ? "Gravando..." : "Gravar matrículas"}
            ocupado={ocupado}
          >
            <ul className="space-y-1.5">
              <li className="flex items-center gap-2">
                <School size={15} aria-hidden className="shrink-0 text-indigo-600" />
                {turmasNovas} turma(s) nova(s) criada(s)
              </li>
              <li className="flex items-center gap-2">
                <UserPlus size={15} aria-hidden className="shrink-0 text-emerald-600" />
                {analise.alunos_novos} aluno(s) novo(s) matriculado(s)
              </li>
              <li className="flex items-center gap-2">
                <RefreshCw size={15} aria-hidden className="shrink-0 text-sky-600" />
                {analise.alunos_atualizar} aluno(s) já cadastrado(s) atualizado(s)
              </li>
              <li className="flex items-start gap-2">
                <UserMinus size={15} aria-hidden className="mt-0.5 shrink-0 text-ouro-700 dark:text-ouro-300" />
                <span>
                  Nas turmas desta planilha, quem veio de uma Lista Piloto anterior e não consta nesta é
                  marcado como fora da lista piloto — continua cadastrado (nada é apagado). As outras
                  turmas não mudam.
                </span>
              </li>
            </ul>
          </Confirmacao>
        </Card>
      )}
    </div>
  );
}
