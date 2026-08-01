/**
 * "Fundir duplicatas" de alunos — detecção automática + revisão + fusão em lote.
 *
 * Nada funde sozinho: o sistema PROPÕE pares (nome idêntico/subconjunto/
 * abreviação, sempre da MESMA turma) e o gestor confirma cada um por caixa de
 * seleção. As de alta confiança vêm marcadas; as de "revisar" vêm DESMARCADAS
 * (mais conservador — a regra do dono é: pior fundir errado do que deixar
 * duplicado). Antes de aplicar, uma confirmação clara e explícita.
 */
import { AlertTriangle, UsersRound } from "lucide-react";
import { useEffect, useState } from "react";

import { ApiError, api } from "../lib/api";
import { Botao, Carregando, Mensagem, Modal, Vazio } from "./ui";

interface Impacto {
  leituras: number;
  snapshots_matific: number;
  snapshots_elefante: number;
  eventos: number;
  notas: number;
  plataformas: string[];
}
interface CandidatoAluno {
  loser_id: number;
  manter_id: number;
  apagar: string;
  manter: string;
  turma: string;
  confianca: "alta" | "revisar";
  motivo: "nome_identico" | "subconjunto" | "abreviacao" | "variante";
  impacto: Impacto;
}
interface PreviaAlunos {
  candidatos: CandidatoAluno[];
  total: number;
  revisar: number;
}
interface ResultadoFusao {
  fundidos: number;
  falhas: { loser_id: number; motivo: string }[];
  mensagem: string;
}

const NOME_PLATAFORMA: Record<string, string> = {
  matific: "Matific",
  elefante: "Elefante Letrado",
};

/** Resumo do que será movido do duplicado para o principal. */
function resumoImpacto(i: Impacto): string {
  const partes: string[] = [];
  if (i.plataformas.length) {
    partes.push(i.plataformas.map((p) => NOME_PLATAFORMA[p] ?? p).join(" + "));
  }
  if (i.leituras) partes.push(`${i.leituras} leitura(s)`);
  const registros = i.snapshots_matific + i.snapshots_elefante;
  if (registros) partes.push(`${registros} registro(s) de plataforma`);
  if (i.notas) partes.push(`${i.notas} nota(s)`);
  return partes.length ? partes.join(" · ") : "sem dados vinculados";
}

function motivoTexto(c: CandidatoAluno): string {
  if (c.motivo === "nome_identico") return "nome idêntico, mesma turma";
  if (c.motivo === "abreviacao") return "nome abreviado do mais completo";
  if (c.motivo === "variante") return "variação de grafia do mesmo nome";
  return "nome contido no nome mais completo";
}

export default function ModalAlunosDuplicados({ escolaId, aoFechar, aoConcluir }: {
  escolaId: number;
  aoFechar: () => void;
  aoConcluir: () => void;
}) {
  const [previa, setPrevia] = useState<PreviaAlunos | null>(null);
  const [selecionados, setSelecionados] = useState<Set<number>>(new Set());
  const [resultado, setResultado] = useState<ResultadoFusao | null>(null);
  const [confirmando, setConfirmando] = useState(false);
  const [erro, setErro] = useState("");
  const [ocupado, setOcupado] = useState(false);

  useEffect(() => {
    let vivo = true;
    api<PreviaAlunos>(`/escolas/${escolaId}/alunos/duplicados`)
      .then((r) => {
        if (!vivo) return;
        setPrevia(r);
        // "alta" já vem marcada; "revisar" DESMARCADA (o gestor confirma).
        setSelecionados(new Set(
          r.candidatos.filter((c) => c.confianca === "alta").map((c) => c.loser_id)));
      })
      .catch((e) => {
        if (vivo) setErro(e instanceof ApiError ? e.message : "Não foi possível carregar.");
      });
    return () => { vivo = false; };
  }, [escolaId]);

  function alternar(id: number) {
    setConfirmando(false);
    setSelecionados((atual) => {
      const nova = new Set(atual);
      if (nova.has(id)) nova.delete(id);
      else nova.add(id);
      return nova;
    });
  }

  /** Marca (ou desmarca) TODOS os pares de uma lista de uma vez — o "selecionar
   *  todos" que evita clicar um a um numa escola com muitas duplicatas. */
  function marcarVarios(ids: number[], marcar: boolean) {
    setConfirmando(false);
    setSelecionados((atual) => {
      const nova = new Set(atual);
      for (const id of ids) {
        if (marcar) nova.add(id);
        else nova.delete(id);
      }
      return nova;
    });
  }

  async function fundir() {
    setOcupado(true);
    setErro("");
    try {
      const r = await api<ResultadoFusao>(
        `/escolas/${escolaId}/alunos/duplicados/corrigir`,
        {
          method: "POST",
          body: JSON.stringify({ loser_ids: [...selecionados], confirmacao: "FUNDIR" }),
        },
      );
      setResultado(r);
      aoConcluir();   // recarrega a lista de alunos por trás
    } catch (e) {
      setErro(e instanceof ApiError ? e.message : "Não foi possível fundir.");
      setConfirmando(false);
    } finally {
      setOcupado(false);
    }
  }

  const grupos: { chave: "alta" | "revisar"; rotulo: string; itens: CandidatoAluno[] }[] = [
    {
      chave: "alta", rotulo: "🟢 Alta confiança",
      itens: previa?.candidatos.filter((c) => c.confianca === "alta") ?? [],
    },
    {
      chave: "revisar", rotulo: "🟡 Revisar — pode ser outra criança",
      itens: previa?.candidatos.filter((c) => c.confianca === "revisar") ?? [],
    },
  ];

  return (
    <Modal titulo="Fundir duplicatas de alunos" aberto aoFechar={aoFechar}>
      {resultado !== null ? (
        // --- Resultado ---
        <>
          <Mensagem tipo="ok">
            {resultado.fundidos} aluno(s) unificado(s).
            {resultado.falhas.length > 0
              && ` ${resultado.falhas.length} não pôde(ram) ser fundido(s).`}
          </Mensagem>
          {resultado.falhas.length > 0 && (
            <ul className="mt-3 space-y-1 text-xs text-amber-600 dark:text-amber-400">
              {resultado.falhas.map((f) => (
                <li key={f.loser_id}>• Cadastro {f.loser_id}: {f.motivo}</li>
              ))}
            </ul>
          )}
          <div className="mt-4 flex justify-end">
            <Botao onClick={aoFechar}>Fechar</Botao>
          </div>
        </>
      ) : previa === null && !erro ? (
        <div className="mt-2"><Carregando /></div>
      ) : previa && previa.total === 0 ? (
        <Vazio titulo="Nenhuma duplicata encontrada"
               descricao="Não achei alunos duplicados (mesmo nome/começo de nome na mesma turma)." />
      ) : (
        // --- Prévia + confirmação ---
        <>
          <p className="text-sm text-zinc-600 dark:text-zinc-300">
            Encontrei <strong>{previa?.total}</strong> possível(is) duplicata(s).
            Marque as que são a <strong>mesma criança</strong> — vou manter o cadastro
            com o nome mais completo e juntar nele todos os dados (Matific, Elefante,
            leituras, histórico), sem perder nada.
          </p>

          <div className="mt-3 max-h-72 space-y-3 overflow-y-auto pr-1">
            {grupos.filter((g) => g.itens.length > 0).map((grupo) => {
              const ids = grupo.itens.map((c) => c.loser_id);
              const todosMarcados = ids.every((id) => selecionados.has(id));
              return (
              <div key={grupo.chave}>
                <div className="mb-1 flex items-center justify-between">
                  <p className="text-xs font-semibold uppercase tracking-wide text-zinc-400">
                    {grupo.rotulo} ({grupo.itens.length})
                  </p>
                  <button
                    type="button"
                    onClick={() => marcarVarios(ids, !todosMarcados)}
                    className="text-xs font-medium text-indigo-600 hover:underline dark:text-indigo-400"
                  >
                    {todosMarcados ? "Desmarcar todos" : "Selecionar todos"}
                  </button>
                </div>
                <div className="space-y-1.5">
                  {grupo.itens.map((c) => {
                    const marcado = selecionados.has(c.loser_id);
                    return (
                      <label
                        key={c.loser_id}
                        className={`flex cursor-pointer items-start gap-3 rounded-lg border p-2.5 transition-colors ${
                          marcado
                            ? "border-indigo-400 bg-indigo-50 dark:border-indigo-500 dark:bg-indigo-500/10"
                            : "border-zinc-200 hover:border-zinc-300 dark:border-zinc-700 dark:hover:border-zinc-600"
                        }`}
                      >
                        <input
                          type="checkbox"
                          className="mt-0.5 h-4 w-4 rounded border-zinc-300 accent-indigo-600"
                          checked={marcado}
                          onChange={() => alternar(c.loser_id)}
                        />
                        <span className="min-w-0 flex-1 text-sm">
                          <span>
                            Unir <strong>{c.apagar}</strong> → <strong>{c.manter}</strong>{" "}
                            <span className="text-xs text-zinc-500 dark:text-zinc-400">
                              · {c.turma}
                            </span>
                          </span>
                          {c.confianca === "revisar" && (
                            <span className="mt-0.5 block text-xs text-amber-600 dark:text-amber-400">
                              ⚠ confira: “{c.apagar}” pode ser outra criança ({motivoTexto(c)})
                            </span>
                          )}
                          <span className="mt-0.5 block text-xs text-zinc-500 dark:text-zinc-400">
                            Será movido: {resumoImpacto(c.impacto)}
                          </span>
                        </span>
                      </label>
                    );
                  })}
                </div>
              </div>
              );
            })}
          </div>

          {erro && <div className="mt-3"><Mensagem tipo="erro">{erro}</Mensagem></div>}

          {confirmando ? (
            <div className="mt-4 rounded-lg border border-red-300 bg-red-50 p-3 dark:border-red-500/40 dark:bg-red-500/10">
              <p className="flex items-start gap-2 text-sm text-red-700 dark:text-red-300">
                <AlertTriangle size={16} className="mt-0.5 shrink-0" />
                <span>
                  Isto vai fundir <strong>{selecionados.size}</strong> par(es) de cadastros
                  num único aluno cada. Os dados são consolidados no principal.
                  <strong> Esta ação é irreversível.</strong>
                </span>
              </p>
              <div className="mt-3 flex justify-end gap-2">
                <Botao variante="neutro" onClick={() => setConfirmando(false)} disabled={ocupado}>
                  Voltar
                </Botao>
                <Botao className="!bg-red-600 hover:!bg-red-500" onClick={fundir} disabled={ocupado}>
                  <UsersRound size={15} /> {ocupado ? "Fundindo..." : "Confirmar fusão"}
                </Botao>
              </div>
            </div>
          ) : (
            <div className="mt-4 flex justify-end gap-2">
              <Botao variante="neutro" onClick={aoFechar} disabled={ocupado}>Cancelar</Botao>
              <Botao
                className="!bg-red-600 hover:!bg-red-500"
                disabled={ocupado || selecionados.size === 0}
                onClick={() => setConfirmando(true)}
              >
                <UsersRound size={15} /> Unir {selecionados.size} selecionada(s)
              </Botao>
            </div>
          )}
        </>
      )}
    </Modal>
  );
}
