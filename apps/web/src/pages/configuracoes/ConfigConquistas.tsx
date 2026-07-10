/**
 * Configurações → Conquistas — nada de critério fixo no código.
 *
 * O administrador cria, edita, reordena, ativa/desativa e remove
 * conquistas. Ao salvar, as regras passam a valer imediatamente para
 * todos os alunos: XP, mural, biblioteca, perfil e painel público.
 */
import { ArrowDown, ArrowLeft, ArrowUp, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import {
  Badge,
  Botao,
  Campo,
  Card,
  Carregando,
  Mensagem,
  Modal,
  PageHeader,
  estiloInput,
} from "../../components/ui";
import { useApp } from "../../context/AppContext";
import { useApi } from "../../hooks/useApi";
import { ApiError, api } from "../../lib/api";
import { BadgeRaridade, NOME_PLATAFORMA } from "../BibliotecaConquistas";

interface Definicao {
  codigo: string;
  nome: string;
  icone: string;
  descricao: string;
  objetivo: string;
  indicador: string;
  limite: number;
  plataforma: string;
  xp: number;
  raridade: string;
  ativa: boolean;
  criada_em: string;
}

interface InfoIndicador {
  rotulo: string;
  plataforma: string;
  unidade: string;
}

interface Definicoes {
  conquistas: Definicao[];
  indicadores: Record<string, InfoIndicador>;
  raridades: Record<string, string>;
  xp_sugerido: Record<string, number>;
}

const NOVA: Definicao = {
  codigo: "", nome: "", icone: "🏅", descricao: "", objetivo: "",
  indicador: "livros_unicos", limite: 10, plataforma: "", xp: 100,
  raridade: "comum", ativa: true, criada_em: "",
};

export default function ConfigConquistas() {
  const { escolaId } = useApp();
  const [lista, setLista] = useState<Definicao[]>([]);
  const [alterado, setAlterado] = useState(false);
  const [emEdicao, setEmEdicao] = useState<{ indice: number | null; item: Definicao } | null>(null);
  const [mensagem, setMensagem] = useState<{ tipo: "ok" | "erro"; texto: string } | null>(null);
  const [salvando, setSalvando] = useState(false);

  // Leitura única das definições — o hook cuida de cancelamento, timeout e retry.
  const { dados, erro } = useApi<Definicoes>(
    escolaId ? `/escolas/${escolaId}/gamificacao/conquistas/definicoes` : null,
    {
      // Semeia a lista editável a cada busca bem-sucedida.
      aoSucesso: (resposta) => {
        setLista(resposta.conquistas);
        setAlterado(false);
      },
    },
  );

  function alterar(nova: Definicao[]) {
    setLista(nova);
    setAlterado(true);
  }

  function mover(indice: number, direcao: -1 | 1) {
    const destino = indice + direcao;
    if (destino < 0 || destino >= lista.length) return;
    const nova = [...lista];
    [nova[indice], nova[destino]] = [nova[destino], nova[indice]];
    alterar(nova);
  }

  async function salvar() {
    if (!escolaId) return;
    setSalvando(true);
    setMensagem(null);
    try {
      const resposta = await api<{ mensagem: string; conquistas: Definicao[] }>(
        `/escolas/${escolaId}/gamificacao/conquistas/definicoes`,
        { method: "PUT", body: JSON.stringify({ conquistas: lista }) },
      );
      setLista(resposta.conquistas);
      setAlterado(false);
      setMensagem({ tipo: "ok", texto: resposta.mensagem });
    } catch (excecao) {
      setMensagem({
        tipo: "erro",
        texto: excecao instanceof ApiError ? excecao.message : "Não foi possível salvar.",
      });
    } finally {
      setSalvando(false);
    }
  }

  const edicao = emEdicao?.item ?? null;
  const infoIndicador = edicao ? dados?.indicadores[edicao.indicador] : null;
  const edicaoValida =
    edicao !== null && edicao.nome.trim().length >= 2 && edicao.limite > 0 && edicao.xp >= 0;

  function confirmarEdicao() {
    if (!emEdicao || !edicaoValida || !edicao) return;
    const item = { ...edicao, nome: edicao.nome.trim() };
    if (emEdicao.indice === null) alterar([...lista, item]);
    else alterar(lista.map((atual, i) => (i === emEdicao.indice ? item : atual)));
    setEmEdicao(null);
  }

  return (
    <div className="space-y-6">
      <div>
        <Link
          to="/configuracoes"
          className="mb-3 inline-flex items-center gap-1.5 text-sm text-zinc-500 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100"
        >
          <ArrowLeft size={15} /> Configurações
        </Link>
        <PageHeader
          titulo="Conquistas"
          descricao="Crie e ajuste as medalhas da escola — critérios, XP, raridade e ordem — sem tocar no código. Novas conquistas valem na hora."
          acoes={
            <div className="flex gap-2">
              <Botao variante="neutro" onClick={() => setEmEdicao({ indice: null, item: { ...NOVA } })}>
                <Plus size={15} /> Nova conquista
              </Botao>
              <Botao onClick={salvar} disabled={!alterado || salvando}>
                {salvando ? "Salvando..." : "Salvar alterações"}
              </Botao>
            </div>
          }
        />
      </div>

      {mensagem && <Mensagem tipo={mensagem.tipo}>{mensagem.texto}</Mensagem>}
      {alterado && (
        <Mensagem tipo="erro">
          Há alterações não salvas — clique em “Salvar alterações” para aplicá-las.
        </Mensagem>
      )}

      <Card>
        {erro ? (
          <Mensagem tipo="erro">{erro.message}</Mensagem>
        ) : dados === null ? (
          <Carregando />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-zinc-200 text-left text-xs uppercase tracking-wide text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
                  <th className="px-3 py-2 font-medium">Ordem</th>
                  <th className="px-3 py-2 font-medium">Conquista</th>
                  <th className="hidden px-3 py-2 font-medium md:table-cell">Critério</th>
                  <th className="px-3 py-2 text-right font-medium">XP</th>
                  <th className="hidden px-3 py-2 font-medium sm:table-cell">Raridade</th>
                  <th className="hidden px-3 py-2 font-medium lg:table-cell">Plataforma</th>
                  <th className="px-3 py-2 font-medium">Ativa</th>
                  <th className="px-3 py-2 text-right font-medium">Ações</th>
                </tr>
              </thead>
              <tbody>
                {lista.map((conquista, indice) => (
                  <tr
                    key={`${conquista.codigo}-${indice}`}
                    className={`border-b border-zinc-100 last:border-0 dark:border-zinc-800/60 ${conquista.ativa ? "" : "opacity-50"}`}
                  >
                    <td className="px-3 py-2">
                      <div className="flex items-center gap-0.5">
                        <button aria-label="Subir" className="rounded p-1 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-700 disabled:opacity-30 dark:hover:bg-zinc-800" disabled={indice === 0} onClick={() => mover(indice, -1)}>
                          <ArrowUp size={14} />
                        </button>
                        <button aria-label="Descer" className="rounded p-1 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-700 disabled:opacity-30 dark:hover:bg-zinc-800" disabled={indice === lista.length - 1} onClick={() => mover(indice, 1)}>
                          <ArrowDown size={14} />
                        </button>
                      </div>
                    </td>
                    <td className="px-3 py-2">
                      <span className="mr-2 text-lg leading-none">{conquista.icone}</span>
                      <span className="font-medium">{conquista.nome}</span>
                    </td>
                    <td className="hidden px-3 py-2 text-xs text-zinc-500 dark:text-zinc-400 md:table-cell">
                      {dados.indicadores[conquista.indicador]?.rotulo ?? conquista.indicador} ≥ {conquista.limite}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums font-medium text-amber-600 dark:text-amber-400">
                      {conquista.xp}
                    </td>
                    <td className="hidden px-3 py-2 sm:table-cell">
                      <BadgeRaridade raridade={conquista.raridade} rotulo={dados.raridades[conquista.raridade]} />
                    </td>
                    <td className="hidden px-3 py-2 text-zinc-500 dark:text-zinc-400 lg:table-cell">
                      {NOME_PLATAFORMA[conquista.plataforma] ?? conquista.plataforma}
                    </td>
                    <td className="px-3 py-2">
                      <input
                        type="checkbox"
                        aria-label={`Ativar ${conquista.nome}`}
                        className="h-4 w-4 rounded border-zinc-300 accent-indigo-600"
                        checked={conquista.ativa}
                        onChange={(e) =>
                          alterar(lista.map((atual, i) =>
                            i === indice ? { ...atual, ativa: e.target.checked } : atual))
                        }
                      />
                    </td>
                    <td className="px-3 py-2">
                      <div className="flex justify-end gap-1">
                        <button
                          className="text-xs font-medium text-indigo-600 hover:underline dark:text-indigo-400"
                          onClick={() => setEmEdicao({ indice, item: { ...conquista } })}
                        >
                          editar
                        </button>
                        <button
                          aria-label={`Remover ${conquista.nome}`}
                          className="ml-1 rounded p-1 text-zinc-400 hover:bg-red-50 hover:text-red-600 dark:hover:bg-red-500/10"
                          onClick={() => alterar(lista.filter((_, i) => i !== indice))}
                        >
                          <Trash2 size={14} />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <p className="text-xs text-zinc-500 dark:text-zinc-400">
        Desativar esconde a conquista dos alunos sem apagar a regra. Remover exclui a
        definição da lista (o histórico de auditoria permanece). A ordem da tabela é a
        ordem de exibição em todo o sistema.
      </p>

      {/* --- Editor --- */}
      <Modal
        titulo={emEdicao?.indice === null ? "Nova conquista" : `Editar ${edicao?.nome ?? ""}`}
        aberto={emEdicao !== null}
        aoFechar={() => setEmEdicao(null)}
      >
        {edicao && dados && (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div className="sm:col-span-2">
              <Campo rotulo="Nome *">
                <input className={estiloInput} value={edicao.nome} autoFocus
                       onChange={(e) => setEmEdicao({ ...emEdicao!, item: { ...edicao, nome: e.target.value } })} />
              </Campo>
            </div>
            <Campo rotulo="Ícone (emoji)">
              <input className={estiloInput} value={edicao.icone} maxLength={8}
                     onChange={(e) => setEmEdicao({ ...emEdicao!, item: { ...edicao, icone: e.target.value } })} />
            </Campo>
            <Campo rotulo="Raridade">
              <select
                className={estiloInput}
                value={edicao.raridade}
                onChange={(e) => {
                  const raridade = e.target.value;
                  setEmEdicao({
                    ...emEdicao!,
                    item: { ...edicao, raridade, xp: dados.xp_sugerido[raridade] ?? edicao.xp },
                  });
                }}
              >
                {Object.entries(dados.raridades).map(([chave, rotulo]) => (
                  <option key={chave} value={chave}>{rotulo}</option>
                ))}
              </select>
            </Campo>
            <div className="sm:col-span-2">
              <Campo rotulo="Descrição (aparece no cartão da conquista)">
                <input className={estiloInput} value={edicao.descricao} maxLength={300}
                       onChange={(e) => setEmEdicao({ ...emEdicao!, item: { ...edicao, descricao: e.target.value } })} />
              </Campo>
            </div>
            <div className="sm:col-span-2">
              <Campo rotulo="Objetivo pedagógico (opcional)">
                <input className={estiloInput} value={edicao.objetivo} maxLength={300}
                       onChange={(e) => setEmEdicao({ ...emEdicao!, item: { ...edicao, objetivo: e.target.value } })} />
              </Campo>
            </div>
            <Campo rotulo="Critério (o que é medido)">
              <select
                className={estiloInput}
                value={edicao.indicador}
                onChange={(e) =>
                  setEmEdicao({ ...emEdicao!, item: { ...edicao, indicador: e.target.value, plataforma: "" } })
                }
              >
                {Object.entries(dados.indicadores).map(([chave, info]) => (
                  <option key={chave} value={chave}>{info.rotulo}</option>
                ))}
              </select>
            </Campo>
            <Campo rotulo={`Quantidade necessária${infoIndicador ? ` (${infoIndicador.unidade})` : ""}`}>
              <input className={estiloInput} type="number" min={1} value={edicao.limite}
                     onChange={(e) => setEmEdicao({ ...emEdicao!, item: { ...edicao, limite: Number(e.target.value) } })} />
            </Campo>
            <Campo rotulo="XP concedido">
              <input className={estiloInput} type="number" min={0} value={edicao.xp}
                     onChange={(e) => setEmEdicao({ ...emEdicao!, item: { ...edicao, xp: Number(e.target.value) } })} />
            </Campo>
            <div className="flex items-end pb-2">
              <label className="flex cursor-pointer items-center gap-2 text-sm">
                <input type="checkbox" className="h-4 w-4 rounded border-zinc-300 accent-indigo-600"
                       checked={edicao.ativa}
                       onChange={(e) => setEmEdicao({ ...emEdicao!, item: { ...edicao, ativa: e.target.checked } })} />
                Conquista ativa
              </label>
            </div>
            <div className="sm:col-span-2">
              <p className="text-xs text-zinc-500 dark:text-zinc-400">
                Plataforma: <Badge tom="destaque">{NOME_PLATAFORMA[infoIndicador?.plataforma ?? "geral"]}</Badge>{" "}
                (definida pelo critério escolhido)
              </p>
            </div>
            <div className="flex justify-end gap-2 sm:col-span-2">
              <Botao variante="neutro" onClick={() => setEmEdicao(null)}>Cancelar</Botao>
              <Botao disabled={!edicaoValida} onClick={confirmarEdicao}>
                {emEdicao?.indice === null ? "Adicionar" : "Aplicar"}
              </Botao>
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}
