/**
 * Importação da PLANILHA DE MATRÍCULAS da escola ("Lista Piloto").
 *
 * O usuário envia UM Excel (.xls ou .xlsx) com uma aba por turma; o sistema
 * mostra a prévia (turmas + alunos detectados, marcando as que já existem) e,
 * ao confirmar, cria as turmas que faltam e matricula os alunos no ano ativo,
 * guardando nº de chamada, nascimento e a ficha cadastral completa.
 */
import { ArrowRight, CheckCircle2, FileSpreadsheet, Users } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { Badge, Botao, Card, Mensagem } from "../components/ui";
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
  avisos: string[];
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
  const navigate = useNavigate();
  const avancar = aoAvancar ?? (() => navigate("/sincronizacao"));

  async function enviar(caminho: string, comArquivo: File) {
    const dados = new FormData();
    dados.append("arquivo", comArquivo);
    return apiUpload(`/escolas/${escolaId}/importacoes/matriculas/${caminho}`, dados);
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
    }
  }

  function recomecar() {
    setAnalise(null); setResultado(null); setArquivo(null); setErro("");
  }

  return (
    <div>
      {resultado ? (
        <Card className="p-5">
          <div className="flex items-start gap-2">
            <CheckCircle2 size={18} className="mt-0.5 shrink-0 text-emerald-600" />
            <div className="min-w-0">
              <p className="text-sm font-medium">{resultado.mensagem}</p>
              <div className="mt-2 flex flex-wrap gap-2 text-xs">
                <Badge tom="ok">{resultado.turmas_criadas} turma(s) criada(s)</Badge>
                <Badge tom="ok">{resultado.alunos_criados} aluno(s) novo(s)</Badge>
                <Badge tom="neutro">{resultado.alunos_atualizados} atualizado(s)</Badge>
              </div>
              {resultado.avisos.length > 0 && (
                <ul className="mt-2 list-inside list-disc text-xs text-amber-700 dark:text-amber-300">
                  {resultado.avisos.slice(0, 8).map((a, i) => <li key={i}>{a}</li>)}
                </ul>
              )}
            </div>
          </div>
          <div className="mt-4 flex flex-wrap items-center gap-2">
            <Botao onClick={avancar}>
              {aoAvancar ? "Continuar" : "Configurar integrações da escola"}
              <ArrowRight size={16} className="ml-1 inline" />
            </Botao>
            <Botao variante="neutro" onClick={recomecar}>Importar outra planilha</Botao>
          </div>
        </Card>
      ) : !analise ? (
        <Card className="p-5">
          <div className="flex items-start gap-2.5">
            <FileSpreadsheet size={18} className="mt-0.5 shrink-0 text-indigo-600 dark:text-indigo-400" />
            <p className="text-sm text-zinc-600 dark:text-zinc-300">
              Envie a planilha da escola com <strong>uma aba por turma</strong> (a
              "Lista Piloto"). O sistema reconhece as turmas, os alunos e todos os
              dados de cada um — cria as salas que ainda não existem e matricula os
              alunos. Nada é gravado antes da sua confirmação. Aceita <strong>.xls</strong> e <strong>.xlsx</strong>.
            </p>
          </div>
          <div className="mt-4">
            <input
              type="file"
              aria-label="Planilha de matrículas da escola (.xls ou .xlsx)"
              accept=".xls,.xlsx,.xlsm"
              className="block w-full text-sm file:mr-3 file:rounded-md file:border-0 file:bg-indigo-50 file:px-3 file:py-1.5 file:text-indigo-700 dark:file:bg-indigo-500/10 dark:file:text-indigo-300"
              onChange={(e) => { setArquivo(e.target.files?.[0] ?? null); setErro(""); }}
            />
          </div>
          {erro && <div className="mt-3"><Mensagem tipo="erro">{erro}</Mensagem></div>}
          <div className="mt-4">
            <Botao disabled={!arquivo || ocupado} onClick={analisar}>
              {ocupado ? "Lendo a planilha..." : "Analisar planilha"}
            </Botao>
          </div>
        </Card>
      ) : (
        <Card className="p-5">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <p className="text-sm font-medium">
                {analise.escola_detectada || "Escola"}
                {analise.ano_letivo ? ` · ${analise.ano_letivo}` : ""}
              </p>
              <p className="text-xs text-zinc-500 dark:text-zinc-400">
                {analise.total_turmas} turma(s) · {analise.total_alunos} aluno(s)
                {analise.total_registros > analise.total_alunos
                  ? ` (${analise.total_registros} registros — alguns em mais de uma turma)`
                  : ""}
              </p>
              <p className="mt-1 text-xs">
                <span className="font-medium text-emerald-600 dark:text-emerald-400">
                  {analise.alunos_novos} novo(s)
                </span>
                {" · "}
                <span className="text-zinc-500 dark:text-zinc-400">
                  {analise.alunos_atualizar} a atualizar
                </span>
                {analise.turmas_existentes > 0 && (
                  <>
                    {" · "}
                    <span className="text-amber-600 dark:text-amber-400">
                      {analise.turmas_existentes} turma(s) já existente(s)
                    </span>
                  </>
                )}
              </p>
            </div>
            <Users size={20} className="text-zinc-300 dark:text-zinc-600" />
          </div>

          {analise.avisos.length > 0 && (
            <ul className="mt-3 list-inside list-disc rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:bg-amber-500/10 dark:text-amber-200">
              {analise.avisos.slice(0, 8).map((a, i) => <li key={i}>{a}</li>)}
            </ul>
          )}

          <div className="mt-3 overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-zinc-200 text-left text-xs uppercase tracking-wide text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
                  <th className="px-3 py-2 font-medium">Turma</th>
                  <th className="hidden px-3 py-2 font-medium sm:table-cell">Turno</th>
                  <th className="hidden px-3 py-2 font-medium md:table-cell">Professor(a)</th>
                  <th className="px-3 py-2 text-right font-medium">Alunos</th>
                  <th className="px-3 py-2 font-medium">Situação</th>
                </tr>
              </thead>
              <tbody>
                {analise.turmas.map((t, i) => (
                  <tr key={`${t.nome}-${i}`} className="border-b border-zinc-100 last:border-0 dark:border-zinc-800/60">
                    <td className="px-3 py-2">
                      <div className="font-medium">{t.nome}</div>
                      <div className="text-xs text-zinc-400">{t.exemplos.slice(0, 3).join(", ")}{t.total_alunos > 3 ? "…" : ""}</div>
                    </td>
                    <td className="hidden px-3 py-2 capitalize text-zinc-500 dark:text-zinc-400 sm:table-cell">{t.turno ?? "—"}</td>
                    <td className="hidden px-3 py-2 text-zinc-500 dark:text-zinc-400 md:table-cell">{t.professor || "—"}</td>
                    <td className="px-3 py-2 text-right font-semibold tabular-nums">{t.total_alunos}</td>
                    <td className="px-3 py-2">
                      <Badge tom={t.ja_existe ? "neutro" : "ok"}>
                        {t.ja_existe ? "já existe" : "nova"}
                      </Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {erro && <div className="mt-3"><Mensagem tipo="erro">{erro}</Mensagem></div>}
          <div className="mt-4 flex flex-wrap justify-end gap-2">
            <Botao variante="neutro" onClick={recomecar} disabled={ocupado}>Escolher outro arquivo</Botao>
            <Botao onClick={confirmar} disabled={ocupado || analise.turmas.length === 0}>
              {ocupado ? "Importando..." : `Criar turmas e matricular ${analise.total_alunos} aluno(s)`}
            </Botao>
          </div>
        </Card>
      )}
    </div>
  );
}
