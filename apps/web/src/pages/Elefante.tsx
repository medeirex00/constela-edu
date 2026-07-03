/** Módulo Elefante Letrado (PRD §56): leitura, questões e níveis por aluno. */
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
import { dataHora, numero, tempoLeitura } from "../lib/formato";
import type { ElefanteAluno } from "../lib/types";

function niveisParaTexto(niveis: Record<string, number>): string {
  return Object.entries(niveis)
    .map(([codigo, quantidade]) => `${codigo}:${quantidade}`)
    .join(", ");
}

function textoParaNiveis(texto: string): Record<string, number> {
  const pares = texto.matchAll(/([A-Za-z]{1,2})\s*[:=]\s*(\d+)/g);
  const niveis: Record<string, number> = {};
  for (const [, codigo, quantidade] of pares) {
    niveis[codigo.toUpperCase()] = Number(quantidade);
  }
  return niveis;
}

export default function Elefante() {
  const { escolaId, usuario } = useApp();
  const podeEditar = usuario?.is_global || ["admin", "coordenador"].includes(usuario?.cargo ?? "");

  const [linhas, setLinhas] = useState<ElefanteAluno[] | null>(null);
  const [editando, setEditando] = useState<ElefanteAluno | null>(null);
  const [formulario, setFormulario] = useState({
    tempo_leitura_min: 0,
    questoes_tentativas: 0,
    questoes_acertos: 0,
    niveis_texto: "",
    motivo: "",
  });
  const [erro, setErro] = useState("");
  const [salvando, setSalvando] = useState(false);

  const carregar = useCallback(() => {
    if (!escolaId) return;
    api<ElefanteAluno[]>(`/escolas/${escolaId}/elefante`).then(setLinhas).catch(() => setLinhas([]));
  }, [escolaId]);

  useEffect(carregar, [carregar]);

  function abrirEdicao(linha: ElefanteAluno) {
    setEditando(linha);
    setFormulario({
      tempo_leitura_min: linha.tempo_leitura_min,
      questoes_tentativas: linha.questoes_tentativas,
      questoes_acertos: linha.questoes_acertos,
      niveis_texto: niveisParaTexto(linha.livros_por_nivel),
      motivo: "",
    });
    setErro("");
  }

  async function salvar() {
    if (!escolaId || !editando) return;
    setSalvando(true);
    setErro("");
    try {
      await api(`/escolas/${escolaId}/elefante/${editando.aluno_id}`, {
        method: "PUT",
        body: JSON.stringify({
          tempo_leitura_min: formulario.tempo_leitura_min,
          questoes_tentativas: formulario.questoes_tentativas,
          questoes_acertos: formulario.questoes_acertos,
          livros_por_nivel: textoParaNiveis(formulario.niveis_texto),
          motivo: formulario.motivo || null,
        }),
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
        titulo="Elefante Letrado"
        descricao="Livros únicos, tempo de leitura e questões por aluno. Releituras nunca pontuam novamente."
      />
      <Card>
        {linhas === null ? (
          <Carregando />
        ) : linhas.length === 0 ? (
          <Vazio titulo="Nenhum aluno ativo" descricao="Cadastre alunos ou importe um relatório do Elefante Letrado." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm tabular-nums">
              <thead>
                <tr className="border-b border-zinc-200 text-left text-xs uppercase tracking-wide text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
                  <th className="px-4 py-2 font-medium">Aluno</th>
                  <th className="hidden px-4 py-2 font-medium md:table-cell">Turma</th>
                  <th className="px-4 py-2 text-right font-medium">Livros</th>
                  <th className="hidden px-4 py-2 font-medium sm:table-cell">Níveis</th>
                  <th className="px-4 py-2 text-right font-medium">Tempo</th>
                  <th className="px-4 py-2 text-right font-medium">Questões</th>
                  <th className="px-4 py-2 text-right font-medium">Acertos</th>
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
                    <td className="px-4 py-2.5 text-right">{numero(linha.livros_unicos)}</td>
                    <td className="hidden px-4 py-2.5 text-xs text-zinc-500 dark:text-zinc-400 sm:table-cell">
                      {niveisParaTexto(linha.livros_por_nivel) || "—"}
                    </td>
                    <td className="px-4 py-2.5 text-right">{tempoLeitura(linha.tempo_leitura_min)}</td>
                    <td className="px-4 py-2.5 text-right">{numero(linha.questoes_tentativas)}</td>
                    <td className="px-4 py-2.5 text-right">
                      {numero(linha.questoes_acertos)}
                      {linha.questoes_tentativas > 0 && (
                        <span className="ml-1 text-xs text-zinc-400">
                          ({Math.round((linha.questoes_acertos / linha.questoes_tentativas) * 100)}%)
                        </span>
                      )}
                    </td>
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

      <Modal titulo={`Editar Elefante Letrado — ${editando?.nome ?? ""}`} aberto={editando !== null} aoFechar={() => setEditando(null)}>
        <div className="space-y-3">
          <Campo rotulo="Livros por nível (ex.: AA:2, D:1) — os livros únicos são a soma">
            <input
              className={estiloInput} placeholder="AA:2, D:1"
              value={formulario.niveis_texto}
              onChange={(e) => setFormulario({ ...formulario, niveis_texto: e.target.value })}
            />
          </Campo>
          <Campo rotulo="Tempo de leitura (minutos)">
            <input
              type="number" min={0} className={estiloInput} value={formulario.tempo_leitura_min}
              onChange={(e) => setFormulario({ ...formulario, tempo_leitura_min: Number(e.target.value) })}
            />
          </Campo>
          <div className="grid grid-cols-2 gap-3">
            <Campo rotulo="Questões (tentativas)">
              <input
                type="number" min={0} className={estiloInput} value={formulario.questoes_tentativas}
                onChange={(e) => setFormulario({ ...formulario, questoes_tentativas: Number(e.target.value) })}
              />
            </Campo>
            <Campo rotulo="Acertos">
              <input
                type="number" min={0} className={estiloInput} value={formulario.questoes_acertos}
                onChange={(e) => setFormulario({ ...formulario, questoes_acertos: Number(e.target.value) })}
              />
            </Campo>
          </div>
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
