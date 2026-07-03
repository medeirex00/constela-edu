/** Módulo Matific (PRD §55): dados atuais por aluno com edição manual auditada. */
import { Pencil } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import {
  Botao,
  Campo,
  Card,
  Carregando,
  Mensagem,
  Modal,
  PageHeader,
  Vazio,
  estiloInput,
} from "../components/ui";
import { useApp } from "../context/AppContext";
import { api } from "../lib/api";
import { dataHora, nota, numero } from "../lib/formato";
import type { MatificAluno } from "../lib/types";

export default function Matific() {
  const { escolaId, usuario } = useApp();
  const podeEditar = usuario?.is_global || ["admin", "coordenador"].includes(usuario?.cargo ?? "");

  const [linhas, setLinhas] = useState<MatificAluno[] | null>(null);
  const [editando, setEditando] = useState<MatificAluno | null>(null);
  const [formulario, setFormulario] = useState({ atividades: 0, estrelas: 0, pontuacao_media: 0, motivo: "" });
  const [erro, setErro] = useState("");
  const [salvando, setSalvando] = useState(false);

  const carregar = useCallback(() => {
    if (!escolaId) return;
    api<MatificAluno[]>(`/escolas/${escolaId}/matific`).then(setLinhas).catch(() => setLinhas([]));
  }, [escolaId]);

  useEffect(carregar, [carregar]);

  function abrirEdicao(linha: MatificAluno) {
    setEditando(linha);
    setFormulario({
      atividades: linha.atividades,
      estrelas: linha.estrelas,
      pontuacao_media: linha.pontuacao_media,
      motivo: "",
    });
    setErro("");
  }

  async function salvar() {
    if (!escolaId || !editando) return;
    setSalvando(true);
    setErro("");
    try {
      await api(`/escolas/${escolaId}/matific/${editando.aluno_id}`, {
        method: "PUT",
        body: JSON.stringify({ ...formulario, motivo: formulario.motivo || null }),
      });
      setEditando(null);
      carregar();
    } catch (excecao) {
      setErro(excecao instanceof Error ? excecao.message : "Não foi possível salvar.");
    } finally {
      setSalvando(false);
    }
  }

  return (
    <div>
      <PageHeader
        titulo="Matific"
        descricao="Estado atual de cada aluno na plataforma. Edições manuais geram novo registro e ficam no log de auditoria."
      />
      <Card>
        {linhas === null ? (
          <Carregando />
        ) : linhas.length === 0 ? (
          <Vazio titulo="Nenhum aluno ativo" descricao="Cadastre alunos ou importe um relatório da Matific." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm tabular-nums">
              <thead>
                <tr className="border-b border-zinc-200 text-left text-xs uppercase tracking-wide text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
                  <th className="px-4 py-2 font-medium">Aluno</th>
                  <th className="hidden px-4 py-2 font-medium md:table-cell">Turma</th>
                  <th className="px-4 py-2 text-right font-medium">Atividades</th>
                  <th className="px-4 py-2 text-right font-medium">Estrelas</th>
                  <th className="px-4 py-2 text-right font-medium">Média</th>
                  <th className="hidden px-4 py-2 font-medium lg:table-cell">Atualizado em</th>
                  {podeEditar && <th className="px-4 py-2" />}
                </tr>
              </thead>
              <tbody>
                {linhas.map((linha) => (
                  <tr key={linha.aluno_id} className="border-b border-zinc-100 last:border-0 dark:border-zinc-800/60">
                    <td className="px-4 py-2.5">
                      <Link to={`/alunos/${linha.aluno_id}`} className="font-medium hover:text-indigo-600 dark:hover:text-indigo-400">
                        {linha.nome}
                      </Link>
                    </td>
                    <td className="hidden px-4 py-2.5 text-zinc-500 dark:text-zinc-400 md:table-cell">{linha.turma}</td>
                    <td className="px-4 py-2.5 text-right">{numero(linha.atividades)}</td>
                    <td className="px-4 py-2.5 text-right">{numero(linha.estrelas)}</td>
                    <td className="px-4 py-2.5 text-right">{nota(linha.pontuacao_media)}</td>
                    <td className="hidden px-4 py-2.5 text-xs text-zinc-500 dark:text-zinc-400 lg:table-cell">
                      {dataHora(linha.data_referencia)}
                    </td>
                    {podeEditar && (
                      <td className="px-4 py-2.5 text-right">
                        <button
                          aria-label={`Editar dados de ${linha.nome}`}
                          className="rounded-lg p-1.5 text-zinc-500 hover:bg-zinc-100 hover:text-zinc-800 dark:hover:bg-zinc-800 dark:hover:text-zinc-200"
                          onClick={() => abrirEdicao(linha)}
                        >
                          <Pencil size={15} />
                        </button>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Modal titulo={`Editar Matific — ${editando?.nome ?? ""}`} aberto={editando !== null} aoFechar={() => setEditando(null)}>
        <div className="space-y-3">
          <Campo rotulo="Atividades finalizadas">
            <input
              type="number" min={0} className={estiloInput} value={formulario.atividades}
              onChange={(e) => setFormulario({ ...formulario, atividades: Number(e.target.value) })}
            />
          </Campo>
          <Campo rotulo="Estrelas">
            <input
              type="number" min={0} className={estiloInput} value={formulario.estrelas}
              onChange={(e) => setFormulario({ ...formulario, estrelas: Number(e.target.value) })}
            />
          </Campo>
          <Campo rotulo="Pontuação média (0–100)">
            <input
              type="number" min={0} max={100} step="0.1" className={estiloInput} value={formulario.pontuacao_media}
              onChange={(e) => setFormulario({ ...formulario, pontuacao_media: Number(e.target.value) })}
            />
          </Campo>
          <Campo rotulo="Motivo da edição (fica no log de auditoria)">
            <input
              className={estiloInput} placeholder="Ex.: correção de erro do relatório"
              value={formulario.motivo}
              onChange={(e) => setFormulario({ ...formulario, motivo: e.target.value })}
            />
          </Campo>
          {erro && <Mensagem tipo="erro">{erro}</Mensagem>}
          <div className="flex justify-end gap-2 pt-1">
            <Botao variante="neutro" onClick={() => setEditando(null)} disabled={salvando}>Cancelar</Botao>
            <Botao onClick={salvar} disabled={salvando}>{salvando ? "Salvando..." : "Salvar e recalcular"}</Botao>
          </div>
        </div>
      </Modal>
    </div>
  );
}
