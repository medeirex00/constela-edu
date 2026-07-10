/**
 * Ações de gestão de UM aluno, reutilizáveis em qualquer tela (lista de
 * Alunos, ficha do aluno): menu ⋮ com Visualizar, Editar dados (nome,
 * nº de chamada, nascimento, observações E turma), Arquivar/Reativar,
 * Excluir (reversível) e Excluir permanentemente (dupla confirmação).
 * Usa os endpoints já existentes do painel da turma.
 */
import {
  Archive,
  Eye,
  Merge,
  Pencil,
  RotateCcw,
  Search,
  Trash2,
  TriangleAlert,
} from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { useApi } from "../hooks/useApi";
import { api, ApiError } from "../lib/api";
import type { Aluno, PaginaAlunos, Turma } from "../lib/types";
import MenuSuspenso, { ItemMenu } from "./MenuSuspenso";
import { Botao, Campo, Mensagem, Modal, estiloInput } from "./ui";

type Janela = "editar" | "fundir" | "excluir" | "permanente" | null;

export default function AcoesAluno({ aluno, escolaId, aoMudar, aoExcluir, mostrarVisualizar = true }: {
  aluno: Aluno;
  escolaId: number;
  /** Chamado após qualquer alteração (para a tela recarregar os dados). */
  aoMudar: () => void;
  /** Chamado após exclusão (ex.: sair da ficha do aluno). */
  aoExcluir?: () => void;
  mostrarVisualizar?: boolean;
}) {
  const navegar = useNavigate();
  const [janela, setJanela] = useState<Janela>(null);
  const [ocupado, setOcupado] = useState(false);
  const [erro, setErro] = useState("");
  const inativo = aluno.status !== "ativo";

  async function acaoStatus(acao: "arquivar" | "reativar" | "excluir") {
    setOcupado(true);
    setErro("");
    try {
      await api(`/escolas/${escolaId}/alunos/acoes`, {
        method: "POST",
        body: JSON.stringify({ aluno_ids: [aluno.id], acao }),
      });
      setJanela(null);
      if (acao === "excluir") aoExcluir?.();
      aoMudar();
    } catch (e) {
      setErro(e instanceof ApiError ? e.message : "Não foi possível concluir a ação.");
    } finally {
      setOcupado(false);
    }
  }

  async function excluirPermanente(confirmacao: string) {
    setOcupado(true);
    setErro("");
    try {
      await api(`/escolas/${escolaId}/alunos/excluir-permanente`, {
        method: "POST",
        body: JSON.stringify({ aluno_ids: [aluno.id], confirmacao }),
      });
      setJanela(null);
      aoExcluir?.();
      aoMudar();
    } catch (e) {
      setErro(e instanceof ApiError ? e.message : "Não foi possível excluir.");
    } finally {
      setOcupado(false);
    }
  }

  return (
    <>
      <MenuSuspenso ariaLabel={`Ações de ${aluno.nome}`}>
        {(fechar) => {
          const escolher = (agir: () => void) => () => { fechar(); agir(); };
          return (
            <>
              {mostrarVisualizar && (
                <ItemMenu icone={<Eye size={15} />} rotulo="Visualizar"
                          onClick={escolher(() => navegar(`/alunos/${aluno.id}`))} />
              )}
              <ItemMenu icone={<Pencil size={15} />} rotulo="Editar dados"
                        onClick={escolher(() => setJanela("editar"))} />
              {/* Fundir só entre alunos ativos (o backend também recusa inativos). */}
              {!inativo && (
                <ItemMenu icone={<Merge size={15} />} rotulo="Fundir com outro aluno"
                          onClick={escolher(() => setJanela("fundir"))} />
              )}
              {inativo ? (
                <ItemMenu icone={<RotateCcw size={15} />} rotulo="Reativar"
                          onClick={escolher(() => acaoStatus("reativar"))} />
              ) : (
                <ItemMenu icone={<Archive size={15} />} rotulo="Arquivar"
                          onClick={escolher(() => acaoStatus("arquivar"))} />
              )}
              <div className="my-1 border-t border-zinc-100 dark:border-zinc-800" />
              <ItemMenu icone={<Trash2 size={15} />} rotulo="Excluir" destrutiva
                        onClick={escolher(() => setJanela("excluir"))} />
              <ItemMenu icone={<TriangleAlert size={15} />} rotulo="Excluir permanentemente" destrutiva
                        onClick={escolher(() => setJanela("permanente"))} />
            </>
          );
        }}
      </MenuSuspenso>

      {janela === "editar" && (
        <ModalEditarAluno
          aluno={aluno}
          escolaId={escolaId}
          aoFechar={() => setJanela(null)}
          aoSalvo={() => { setJanela(null); aoMudar(); }}
        />
      )}

      {janela === "fundir" && (
        <ModalFundir
          aluno={aluno}
          escolaId={escolaId}
          aoFechar={() => setJanela(null)}
          aoConcluir={(removeuAtual) => {
            setJanela(null);
            if (removeuAtual) aoExcluir?.();
            aoMudar();
          }}
        />
      )}

      {janela === "excluir" && (
        <Modal titulo="Excluir aluno" aberto aoFechar={() => setJanela(null)}>
          <p className="text-sm text-zinc-600 dark:text-zinc-300">
            Tem certeza de que deseja excluir <strong>{aluno.nome}</strong>? O aluno sai
            das listas e rankings; os dados são mantidos e podem ser restaurados depois.
            Para apagar tudo de vez, use “Excluir permanentemente”.
          </p>
          {erro && <div className="mt-3"><Mensagem tipo="erro">{erro}</Mensagem></div>}
          <div className="mt-5 flex justify-end gap-2">
            <Botao variante="neutro" onClick={() => setJanela(null)} disabled={ocupado}>Cancelar</Botao>
            <Botao className="!bg-red-600 hover:!bg-red-500" disabled={ocupado}
                   onClick={() => acaoStatus("excluir")}>
              {ocupado ? "Excluindo..." : "Excluir"}
            </Botao>
          </div>
        </Modal>
      )}

      {janela === "permanente" && (
        <ModalPermanenteUm
          nome={aluno.nome}
          ocupado={ocupado}
          erro={erro}
          aoFechar={() => setJanela(null)}
          aoConfirmar={excluirPermanente}
        />
      )}
    </>
  );
}

/** Edição COMPLETA do cadastro: nome, nº de chamada, nascimento, observações e
 *  TURMA (trocar a turma transfere a matrícula do ano ativo). */
export function ModalEditarAluno({ aluno, escolaId, aoFechar, aoSalvo }: {
  aluno: Aluno;
  escolaId: number;
  aoFechar: () => void;
  aoSalvo: () => void;
}) {
  const [nome, setNome] = useState(aluno.nome);
  const [chamada, setChamada] = useState(aluno.numero_chamada?.toString() ?? "");
  const [nascimento, setNascimento] = useState(aluno.data_nascimento ?? "");
  const [observacoes, setObservacoes] = useState(aluno.observacoes ?? "");
  const { dados: turmas, erro: erroTurmas } = useApi<Turma[]>(`/escolas/${escolaId}/turmas`);
  const [turmaId, setTurmaId] = useState<number | "">("");
  const [turmaOriginal, setTurmaOriginal] = useState<number | "">("");
  const [ocupado, setOcupado] = useState(false);
  const [erro, setErro] = useState("");

  // Quando as turmas chegam, pré-seleciona a turma atual do aluno.
  useEffect(() => {
    if (!turmas) return;
    const atual = turmas.find((t) => t.nome === aluno.turma)?.id ?? "";
    setTurmaId(atual);
    setTurmaOriginal(atual);
  }, [turmas, aluno.turma]);

  async function salvar() {
    setOcupado(true);
    setErro("");
    try {
      await api(`/escolas/${escolaId}/alunos/${aluno.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          nome: nome.trim(),
          numero_chamada: chamada ? Number(chamada) : null,
          data_nascimento: nascimento || null,
          observacoes: observacoes.trim() || null,
        }),
      });
      // Turma mudou → transfere a matrícula do ano ativo.
      if (turmaId !== "" && turmaId !== turmaOriginal) {
        await api(`/escolas/${escolaId}/alunos/acoes`, {
          method: "POST",
          body: JSON.stringify({ aluno_ids: [aluno.id], acao: "transferir", turma_id: turmaId }),
        });
      }
      aoSalvo();
    } catch (e) {
      setErro(e instanceof ApiError ? e.message : "Não foi possível salvar.");
    } finally {
      setOcupado(false);
    }
  }

  return (
    <Modal titulo="Editar aluno" aberto aoFechar={aoFechar}>
      <div className="space-y-4">
        <Campo rotulo="Nome">
          <input className={estiloInput} value={nome} onChange={(e) => setNome(e.target.value)} />
        </Campo>
        <div className="grid grid-cols-2 gap-3">
          <Campo rotulo="Nº de chamada">
            <input className={estiloInput} inputMode="numeric" value={chamada}
                   onChange={(e) => setChamada(e.target.value.replace(/\D/g, ""))} />
          </Campo>
          <Campo rotulo="Data de nascimento">
            <input type="date" className={estiloInput} value={nascimento}
                   onChange={(e) => setNascimento(e.target.value)} />
          </Campo>
        </div>
        <Campo rotulo="Turma">
          <select className={estiloInput} value={turmaId}
                  onChange={(e) => setTurmaId(e.target.value ? Number(e.target.value) : "")}>
            <option value="">— sem turma —</option>
            {(turmas ?? []).map((t) => <option key={t.id} value={t.id}>{t.nome}</option>)}
          </select>
        </Campo>
        {/* Não engole o erro: avisa se as turmas não puderam ser carregadas. */}
        {erroTurmas && (
          <Mensagem tipo="erro">Não foi possível carregar as turmas: {erroTurmas.message}</Mensagem>
        )}
        <Campo rotulo="Observações">
          <textarea className={`${estiloInput} min-h-[70px]`} value={observacoes}
                    onChange={(e) => setObservacoes(e.target.value)} />
        </Campo>
      </div>
      {erro && <div className="mt-3"><Mensagem tipo="erro">{erro}</Mensagem></div>}
      <div className="mt-5 flex justify-end gap-2">
        <Botao variante="neutro" onClick={aoFechar} disabled={ocupado}>Cancelar</Botao>
        <Botao disabled={ocupado || nome.trim().length < 2} onClick={salvar}>
          {ocupado ? "Salvando..." : "Salvar"}
        </Botao>
      </div>
    </Modal>
  );
}

/** Funde dois cadastros do MESMO aluno (duplicados). Busca o outro cadastro,
 *  deixa escolher qual fica como principal e combina Matific + Elefante +
 *  leituras num só. Irreversível → confirmação "FUNDIR". */
export function ModalFundir({ aluno, escolaId, aoFechar, aoConcluir }: {
  aluno: Aluno;
  escolaId: number;
  aoFechar: () => void;
  /** removeuAtual = true quando o aluno aberto foi o absorvido (sai da tela). */
  aoConcluir: (removeuAtual: boolean) => void;
}) {
  const [busca, setBusca] = useState("");
  const [buscaAtrasada, setBuscaAtrasada] = useState("");
  const [outro, setOutro] = useState<Aluno | null>(null);
  const [manterAtual, setManterAtual] = useState(true); // qual fica como principal
  const [confirmacao, setConfirmacao] = useState("");
  const [ocupado, setOcupado] = useState(false);
  const [erro, setErro] = useState("");

  // Atrasa (debounce) a busca para não consultar a API a cada tecla.
  useEffect(() => {
    const t = window.setTimeout(() => setBuscaAtrasada(busca.trim()), 250);
    return () => window.clearTimeout(t);
  }, [busca]);

  // Só busca com termo válido e enquanto nenhum cadastro foi escolhido.
  const buscaAtiva = !outro && buscaAtrasada.length >= 2;
  const { dados: pagina, erro: erroBusca, carregando: carregandoBusca } = useApi<PaginaAlunos>(
    buscaAtiva
      ? `/escolas/${escolaId}/alunos?busca=${encodeURIComponent(buscaAtrasada)}&por_pagina=8`
      : null,
  );
  const resultados = buscaAtiva ? (pagina?.itens ?? []).filter((a) => a.id !== aluno.id) : [];

  const principal = manterAtual ? aluno : outro;
  const absorvido = manterAtual ? outro : aluno;
  const liberado = outro && confirmacao.trim().toUpperCase() === "FUNDIR";

  async function fundir() {
    if (!principal || !absorvido) return;
    setOcupado(true);
    setErro("");
    try {
      await api(`/escolas/${escolaId}/alunos/fundir`, {
        method: "POST",
        body: JSON.stringify({
          manter_id: principal.id, remover_id: absorvido.id,
          confirmacao: confirmacao.trim(),
        }),
      });
      aoConcluir(absorvido.id === aluno.id);
    } catch (e) {
      setErro(e instanceof ApiError ? e.message : "Não foi possível fundir.");
    } finally {
      setOcupado(false);
    }
  }

  return (
    <Modal titulo="Fundir aluno duplicado" aberto aoFechar={aoFechar}>
      <p className="text-sm text-zinc-600 dark:text-zinc-300">
        Encontre o outro cadastro da <strong>mesma pessoa</strong>. Os dados dos
        dois (Matific, Elefante Letrado, leituras e matrículas) serão combinados
        em <strong>um só</strong>, e o cadastro absorvido será removido.
      </p>

      {!outro ? (
        <div className="mt-3">
          <div className="relative">
            <Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-zinc-400" />
            <input
              className={`${estiloInput} pl-8`}
              placeholder="Buscar o cadastro duplicado pelo nome..."
              value={busca}
              onChange={(e) => setBusca(e.target.value)}
              autoFocus
            />
          </div>
          {resultados.length > 0 && (
            <ul className="mt-2 max-h-56 overflow-y-auto rounded-lg border border-zinc-200 dark:border-zinc-700">
              {resultados.map((a) => (
                <li key={a.id}>
                  <button
                    className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-sm hover:bg-zinc-100 dark:hover:bg-zinc-800"
                    onClick={() => setOutro(a)}
                  >
                    <span className="font-medium">{a.nome}</span>
                    <span className="text-xs text-zinc-400">{a.turma ?? "sem turma"}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
          {/* Não engole o erro: mostra a falha da busca em vez de "nada encontrado". */}
          {erroBusca && (
            <div className="mt-2"><Mensagem tipo="erro">Não foi possível buscar: {erroBusca.message}</Mensagem></div>
          )}
          {buscaAtiva && !carregandoBusca && !erroBusca && resultados.length === 0 && (
            <p className="mt-2 text-xs text-zinc-400">Nenhum outro aluno encontrado.</p>
          )}
        </div>
      ) : (
        <>
          <div className="mt-3 space-y-2 rounded-lg border border-zinc-200 p-3 dark:border-zinc-700">
            <div className="flex items-center justify-between gap-2 text-sm">
              <span>
                <span className="text-zinc-500 dark:text-zinc-400">Fica como principal: </span>
                <strong>{principal?.nome}</strong>
                {principal?.turma && <span className="text-zinc-400"> · {principal.turma}</span>}
              </span>
              <button className="text-xs font-medium text-indigo-600 hover:underline dark:text-indigo-400"
                      onClick={() => setManterAtual((v) => !v)}>
                trocar
              </button>
            </div>
            <div className="text-sm">
              <span className="text-zinc-500 dark:text-zinc-400">Será absorvido e removido: </span>
              <strong>{absorvido?.nome}</strong>
              {absorvido?.turma && <span className="text-zinc-400"> · {absorvido.turma}</span>}
            </div>
            <button className="text-xs text-zinc-500 hover:underline dark:text-zinc-400"
                    onClick={() => { setOutro(null); setConfirmacao(""); setManterAtual(true); }}>
              ← escolher outro cadastro
            </button>
          </div>
          <div className="mt-3">
            <Campo rotulo="Digite FUNDIR para confirmar">
              <input className={estiloInput} value={confirmacao} autoComplete="off"
                     placeholder="FUNDIR"
                     onChange={(e) => setConfirmacao(e.target.value)} />
            </Campo>
          </div>
        </>
      )}

      {erro && <div className="mt-3"><Mensagem tipo="erro">{erro}</Mensagem></div>}
      <div className="mt-5 flex justify-end gap-2">
        <Botao variante="neutro" onClick={aoFechar} disabled={ocupado}>Cancelar</Botao>
        <Botao disabled={ocupado || !liberado} onClick={fundir}>
          <Merge size={15} /> {ocupado ? "Fundindo..." : "Fundir cadastros"}
        </Botao>
      </div>
    </Modal>
  );
}

function ModalPermanenteUm({ nome, ocupado, erro, aoFechar, aoConfirmar }: {
  nome: string;
  ocupado: boolean;
  erro: string;
  aoFechar: () => void;
  aoConfirmar: (confirmacao: string) => void;
}) {
  const [texto, setTexto] = useState("");
  const liberado = texto.trim().toUpperCase() === "EXCLUIR";
  return (
    <Modal titulo="Excluir permanentemente" aberto aoFechar={aoFechar}>
      <div className="flex items-start gap-3 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800 dark:border-red-500/20 dark:bg-red-500/10 dark:text-red-200">
        <TriangleAlert size={18} className="mt-0.5 shrink-0" />
        <div>
          <p className="font-semibold">Esta ação é irreversível.</p>
          <p className="mt-1">
            <strong>{nome}</strong> será removido por completo: cadastro, histórico,
            leituras, dados do Matific e do Elefante Letrado, rankings, XP e conquistas.
          </p>
        </div>
      </div>
      <div className="mt-4">
        <Campo rotulo="Digite EXCLUIR para confirmar">
          <input className={estiloInput} value={texto} onChange={(e) => setTexto(e.target.value)}
                 placeholder="EXCLUIR" autoComplete="off" />
        </Campo>
      </div>
      {erro && <div className="mt-3"><Mensagem tipo="erro">{erro}</Mensagem></div>}
      <div className="mt-5 flex justify-end gap-2">
        <Botao variante="neutro" onClick={aoFechar} disabled={ocupado}>Cancelar</Botao>
        <Botao className="!bg-red-600 hover:!bg-red-500" disabled={ocupado || !liberado}
               onClick={() => aoConfirmar(texto.trim())}>
          <TriangleAlert size={15} /> {ocupado ? "Excluindo..." : "Excluir para sempre"}
        </Botao>
      </div>
    </Modal>
  );
}
