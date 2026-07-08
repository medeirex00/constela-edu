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
  Pencil,
  RotateCcw,
  Trash2,
  TriangleAlert,
} from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { api, ApiError } from "../lib/api";
import type { Aluno, Turma } from "../lib/types";
import MenuSuspenso, { ItemMenu } from "./MenuSuspenso";
import { Botao, Campo, Mensagem, Modal, estiloInput } from "./ui";

type Janela = "editar" | "excluir" | "permanente" | null;

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
  const [turmas, setTurmas] = useState<Turma[]>([]);
  const [turmaId, setTurmaId] = useState<number | "">("");
  const [turmaOriginal, setTurmaOriginal] = useState<number | "">("");
  const [ocupado, setOcupado] = useState(false);
  const [erro, setErro] = useState("");

  useEffect(() => {
    api<Turma[]>(`/escolas/${escolaId}/turmas`)
      .then((lista) => {
        setTurmas(lista);
        const atual = lista.find((t) => t.nome === aluno.turma)?.id ?? "";
        setTurmaId(atual);
        setTurmaOriginal(atual);
      })
      .catch(() => setTurmas([]));
  }, [escolaId, aluno.turma]);

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
            {turmas.map((t) => <option key={t.id} value={t.id}>{t.nome}</option>)}
          </select>
        </Campo>
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
