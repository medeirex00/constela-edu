/** Módulo Matific (PRD §55): dados atuais por aluno com edição manual auditada. */
import { Pencil } from "lucide-react";
import { useEffect, useState } from "react";
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
import { useApi } from "../hooks/useApi";
import { api } from "../lib/api";
import { dataHora, nota, numero } from "../lib/formato";
import type { MatificAluno } from "../lib/types";

/** Escala da média do Matific (a mesma do Placar da Escola) — o servidor recusa
 *  acima disso (`MatificEdicao.pontuacao_media`, ge=0 le=5). */
const MEDIA_MAXIMA = 5;

/**
 * Modal de edição isolado: o estado do formulário vive AQUI, não no componente
 * da tabela. Assim, digitar re-renderiza só o modal — e não a tabela inteira
 * (não paginada) de alunos por baixo dele. Fica montado o tempo todo; quando
 * `linha` é null o Modal não aparece, e o efeito re-semeia os campos a cada
 * abertura.
 */
function ModalEditarMatific({
  linha,
  escolaId,
  aoFechar,
  aoSalvo,
}: {
  linha: MatificAluno | null;
  escolaId: number | null;
  aoFechar: () => void;
  aoSalvo: () => void;
}) {
  const [form, setForm] = useState({ atividades: 0, estrelas: 0, pontuacao_media: 0, motivo: "" });
  // Média COMO ESTAVA ao abrir: é o que distingue "não mexi nisso" de "digitei".
  const [mediaOriginal, setMediaOriginal] = useState(0);
  const [erro, setErro] = useState("");
  const [salvando, setSalvando] = useState(false);

  useEffect(() => {
    if (linha) {
      setForm({
        atividades: linha.atividades,
        estrelas: linha.estrelas,
        pontuacao_media: linha.pontuacao_media,
        motivo: "",
      });
      setMediaOriginal(linha.pontuacao_media);
      setErro("");
    }
  }, [linha]);

  const mediaMudou = form.pontuacao_media !== mediaOriginal;
  // Registro antigo fora da escala atual (edição gravada quando o limite era
  // 100, ou base de demonstração): reenviá-lo daria 422 e travaria a correção
  // de atividades/estrelas.
  const mediaForaDaEscala = mediaOriginal > MEDIA_MAXIMA;

  async function salvar() {
    if (!escolaId || !linha) return;
    // Barra no cliente, em português: o 422 do servidor chega em inglês e sem
    // dizer qual é a escala.
    if (mediaMudou && (form.pontuacao_media < 0 || form.pontuacao_media > MEDIA_MAXIMA)) {
      setErro(`A média do Matific vai de 0 a ${MEDIA_MAXIMA} (a mesma escala do Placar da Escola).`);
      return;
    }
    setSalvando(true);
    setErro("");
    try {
      await api(`/escolas/${escolaId}/matific/${linha.aluno_id}`, {
        method: "PUT",
        body: JSON.stringify({
          atividades: form.atividades,
          estrelas: form.estrelas,
          motivo: form.motivo || null,
          // A média só viaja quando foi EDITADA: ausente, o servidor preserva a
          // gravada. É o que mantém editável um registro fora da escala, sem
          // obrigar ninguém a inventar um número de 0 a 5 no lugar do medido.
          ...(mediaMudou ? { pontuacao_media: form.pontuacao_media } : {}),
        }),
      });
      aoSalvo();
    } catch (excecao) {
      setErro(excecao instanceof Error ? excecao.message : "Não foi possível salvar.");
    } finally {
      setSalvando(false);
    }
  }

  return (
    <Modal titulo={`Editar Matific — ${linha?.nome ?? ""}`} aberto={linha !== null} aoFechar={aoFechar}>
      <div className="space-y-3">
        <Campo rotulo="Atividades finalizadas">
          <input
            type="number" min={0} className={estiloInput} value={form.atividades}
            onChange={(e) => setForm({ ...form, atividades: Number(e.target.value) })}
          />
        </Campo>
        <Campo rotulo="Estrelas">
          <input
            type="number" min={0} className={estiloInput} value={form.estrelas}
            onChange={(e) => setForm({ ...form, estrelas: Number(e.target.value) })}
          />
        </Campo>
        <Campo rotulo="Pontuação média (0 a 5)">
          <input
            type="number" min={0} max={MEDIA_MAXIMA} step="0.1" className={estiloInput}
            value={form.pontuacao_media}
            onChange={(e) => setForm({ ...form, pontuacao_media: Number(e.target.value) })}
          />
          {mediaForaDaEscala && (
            <p className="mt-1 text-xs text-amber-700 dark:text-amber-300">
              Este registro tem média {nota(mediaOriginal)}, fora da escala atual (0 a {MEDIA_MAXIMA}).
              Deixe como está para preservar o valor medido, ou digite um número de 0 a {MEDIA_MAXIMA}
              {" "}para corrigi-lo.
            </p>
          )}
        </Campo>
        <Campo rotulo="Motivo da edição (fica no log de auditoria)">
          <input
            className={estiloInput} placeholder="Ex.: correção de erro do relatório"
            value={form.motivo}
            onChange={(e) => setForm({ ...form, motivo: e.target.value })}
          />
        </Campo>
        {erro && <Mensagem tipo="erro">{erro}</Mensagem>}
        <div className="flex justify-end gap-2 pt-1">
          <Botao variante="neutro" onClick={aoFechar} disabled={salvando}>Cancelar</Botao>
          <Botao onClick={salvar} disabled={salvando}>{salvando ? "Salvando..." : "Salvar e recalcular"}</Botao>
        </div>
      </div>
    </Modal>
  );
}

export default function Matific() {
  const { escolaId, usuario } = useApp();
  const podeEditar = usuario?.is_global || ["admin", "coordenador"].includes(usuario?.cargo ?? "");

  const {
    dados: linhas,
    erro: erroLinhas,
    carregando,
    recarregar,
  } = useApi<MatificAluno[]>(escolaId ? `/escolas/${escolaId}/matific` : null);
  const [editando, setEditando] = useState<MatificAluno | null>(null);

  return (
    <div>
      <PageHeader
        titulo="Matific"
        descricao="Estado atual de cada aluno na plataforma. Edições manuais geram novo registro e ficam no log de auditoria."
      />
      <Card>
        {carregando ? (
          <Carregando />
        ) : erroLinhas ? (
          <Vazio titulo="Não foi possível carregar" descricao={erroLinhas.message} />
        ) : (linhas ?? []).length === 0 ? (
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
                {(linhas ?? []).map((linha) => (
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
                          onClick={() => setEditando(linha)}
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

      <ModalEditarMatific
        linha={editando}
        escolaId={escolaId}
        aoFechar={() => setEditando(null)}
        aoSalvo={() => {
          setEditando(null);
          recarregar();
        }}
      />
    </div>
  );
}
