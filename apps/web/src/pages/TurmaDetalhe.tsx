/**
 * Painel administrativo da turma: gestão completa dos alunos.
 *
 * Lista os alunos da turma com busca, ordenação e seleção múltipla. Cada
 * aluno tem um menu de ações (Visualizar, Editar, Transferir, Arquivar,
 * Excluir) e há uma barra de ações em massa. A exclusão comum é lógica
 * (reversível); a exclusão PERMANENTE apaga o aluno e todos os dados
 * vinculados e exige uma confirmação extra. Após cada ação, as contagens,
 * o ranking e as estatísticas se atualizam sozinhos (sem recarregar a página).
 */
import {
  Archive,
  ArrowLeft,
  ArrowRightLeft,
  BookOpen,
  Calculator,
  Clock,
  Eye,
  Pencil,
  RotateCcw,
  Search,
  Trash2,
  TriangleAlert,
  Users,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import MenuSuspenso, { ItemMenu } from "../components/MenuSuspenso";
import {
  Badge,
  Botao,
  Campo,
  Card,
  Carregando,
  Mensagem,
  Modal,
  StatCard,
  Vazio,
  estiloInput,
} from "../components/ui";
import { useApp } from "../context/AppContext";
import { api, ApiError } from "../lib/api";
import { nota as fmtNota, numero, tempoLeitura } from "../lib/formato";
import type { AlunoGestao, Turma } from "../lib/types";

interface ResumoTurma {
  turma: { id: number; nome: string; ano_escolar: string };
  total_alunos: number;
  media_geral: number;
  media_matific: number;
  media_elefante: number;
  indicadores: Record<string, number>;
}

const ORDENACOES = [
  { valor: "nome", rotulo: "Nome (A–Z)" },
  { valor: "data", rotulo: "Data de cadastro" },
  { valor: "desempenho", rotulo: "Desempenho" },
  { valor: "chamada", rotulo: "Nº de chamada" },
  { valor: "serie", rotulo: "Série" },
];

const STATUS_BADGE: Record<string, { tom: "neutro" | "alerta"; texto: string }> = {
  arquivado: { tom: "neutro", texto: "Arquivado" },
  excluido: { tom: "alerta", texto: "Na lixeira" },
};

type Acao =
  | { tipo: "editar"; alvo: AlunoGestao }
  | { tipo: "transferir"; ids: number[]; rotulo: string }
  | { tipo: "excluir"; ids: number[]; rotulo: string }
  | { tipo: "permanente"; ids: number[]; rotulo: string };

/** Menu de ações (kebab ⋮) de um aluno. */
function MenuAcoes({ aluno, aoEscolher }: {
  aluno: AlunoGestao;
  aoEscolher: (acao: string) => void;
}) {
  const inativo = aluno.status !== "ativo";

  return (
    <MenuSuspenso ariaLabel={`Ações de ${aluno.nome}`} largura="w-52">
      {(fechar) => {
        const escolher = (acao: string) => () => { fechar(); aoEscolher(acao); };
        return (
          <>
            <ItemMenu icone={<Eye size={15} />} rotulo="Visualizar" onClick={escolher("visualizar")} />
            <ItemMenu icone={<Pencil size={15} />} rotulo="Editar" onClick={escolher("editar")} />
            <ItemMenu icone={<ArrowRightLeft size={15} />} rotulo="Transferir de turma" onClick={escolher("transferir")} />
            {inativo ? (
              <ItemMenu icone={<RotateCcw size={15} />} rotulo="Reativar" onClick={escolher("reativar")} />
            ) : (
              <ItemMenu icone={<Archive size={15} />} rotulo="Arquivar" onClick={escolher("arquivar")} />
            )}
            <div className="my-1 border-t border-zinc-100 dark:border-zinc-800" />
            <ItemMenu icone={<Trash2 size={15} />} rotulo="Excluir" destrutiva onClick={escolher("excluir")} />
            <ItemMenu icone={<TriangleAlert size={15} />} rotulo="Excluir permanentemente" destrutiva onClick={escolher("permanente")} />
          </>
        );
      }}
    </MenuSuspenso>
  );
}

function Avatar({ aluno }: { aluno: AlunoGestao }) {
  return (
    <span className="flex h-8 w-8 shrink-0 items-center justify-center overflow-hidden rounded-full bg-indigo-100 text-xs font-semibold text-indigo-700 dark:bg-indigo-500/20 dark:text-indigo-300">
      {aluno.foto_url ? (
        <img src={aluno.foto_url} alt="" className="h-full w-full object-cover" />
      ) : (
        aluno.nome.slice(0, 1).toUpperCase()
      )}
    </span>
  );
}

export default function TurmaDetalhe() {
  const { id } = useParams();
  const { escolaId } = useApp();
  const navegar = useNavigate();

  const [resumo, setResumo] = useState<ResumoTurma | null>(null);
  const [alunos, setAlunos] = useState<AlunoGestao[] | null>(null);
  const [turmas, setTurmas] = useState<Turma[]>([]);
  const [erroTurma, setErroTurma] = useState(false);

  const [busca, setBusca] = useState("");
  const [ordenar, setOrdenar] = useState("nome");
  const [incluirInativos, setIncluirInativos] = useState(false);
  const [selecionados, setSelecionados] = useState<Set<number>>(new Set());

  const [acao, setAcao] = useState<Acao | null>(null);
  const [ocupado, setOcupado] = useState(false);
  const [aviso, setAviso] = useState<{ tipo: "ok" | "erro"; texto: string } | null>(null);

  const base = `/escolas/${escolaId}/turmas/${id}`;

  const carregarResumo = useCallback(() => {
    if (!escolaId || !id) return;
    api<ResumoTurma>(`${base}/resumo`).then(setResumo).catch(() => setErroTurma(true));
  }, [escolaId, id, base]);

  const carregarAlunos = useCallback(() => {
    if (!escolaId || !id) return;
    const params = new URLSearchParams({ ordenar });
    if (busca.trim()) params.set("busca", busca.trim());
    if (incluirInativos) params.set("incluir_inativos", "true");
    api<AlunoGestao[]>(`${base}/alunos?${params}`)
      .then(setAlunos)
      .catch(() => setAlunos([]));
  }, [escolaId, id, base, ordenar, busca, incluirInativos]);

  useEffect(() => { carregarResumo(); }, [carregarResumo]);
  useEffect(() => {
    if (!escolaId) return;
    api<Turma[]>(`/escolas/${escolaId}/turmas`).then(setTurmas).catch(() => setTurmas([]));
  }, [escolaId]);

  // Busca com debounce; ordenação/filtro recarregam na hora.
  useEffect(() => {
    const t = window.setTimeout(carregarAlunos, busca ? 300 : 0);
    return () => window.clearTimeout(t);
  }, [carregarAlunos, busca]);

  function avisar(tipo: "ok" | "erro", texto: string) {
    setAviso({ tipo, texto });
    window.setTimeout(() => setAviso(null), 6000);
  }

  /** Recarrega tudo (lista + contagens + ranking) sem recarregar a página. */
  function recarregar() {
    carregarAlunos();
    carregarResumo();
    setSelecionados(new Set());
  }

  async function executar(caminho: string, corpo: unknown, sucesso: string) {
    setOcupado(true);
    try {
      const r = await api<{ mensagem?: string; afetados?: number }>(caminho, {
        method: "POST",
        body: JSON.stringify(corpo),
      });
      avisar("ok", r?.mensagem ?? sucesso);
      setAcao(null);
      recarregar();
    } catch (e) {
      avisar("erro", e instanceof ApiError ? e.message : "Não foi possível concluir a ação.");
    } finally {
      setOcupado(false);
    }
  }

  /** Ação de status/transferência (individual ou em massa). */
  function aplicarAcao(tipo: "arquivar" | "reativar" | "excluir" | "transferir", ids: number[], turmaId?: number) {
    const rotulos = {
      arquivar: "Aluno(s) arquivado(s).",
      reativar: "Aluno(s) reativado(s).",
      excluir: "Aluno(s) excluído(s).",
      transferir: "Aluno(s) transferido(s).",
    };
    executar(`/escolas/${escolaId}/alunos/acoes`,
      { aluno_ids: ids, acao: tipo, turma_id: turmaId ?? null }, rotulos[tipo]);
  }

  function aoEscolherNoMenu(aluno: AlunoGestao, escolha: string) {
    if (escolha === "visualizar") return navegar(`/alunos/${aluno.id}`);
    if (escolha === "editar") return setAcao({ tipo: "editar", alvo: aluno });
    if (escolha === "transferir") return setAcao({ tipo: "transferir", ids: [aluno.id], rotulo: aluno.nome });
    if (escolha === "excluir") return setAcao({ tipo: "excluir", ids: [aluno.id], rotulo: aluno.nome });
    if (escolha === "permanente") return setAcao({ tipo: "permanente", ids: [aluno.id], rotulo: aluno.nome });
    // arquivar / reativar são reversíveis → aplica direto
    if (escolha === "arquivar" || escolha === "reativar") aplicarAcao(escolha, [aluno.id]);
  }

  const lista = alunos ?? [];
  const todosSelecionados = lista.length > 0 && lista.every((a) => selecionados.has(a.id));
  const idsSelecionados = useMemo(() => [...selecionados], [selecionados]);

  function alternarTodos() {
    setSelecionados(todosSelecionados ? new Set() : new Set(lista.map((a) => a.id)));
  }
  function alternarUm(id: number) {
    setSelecionados((atual) => {
      const prox = new Set(atual);
      if (prox.has(id)) prox.delete(id);
      else prox.add(id);
      return prox;
    });
  }

  if (erroTurma) return <Vazio titulo="Turma não encontrada" />;
  if (!resumo) return <Carregando />;

  return (
    <div className="space-y-6">
      <div>
        <Link to="/turmas" className="mb-3 inline-flex items-center gap-1.5 text-sm text-zinc-500 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100">
          <ArrowLeft size={15} /> Turmas
        </Link>
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-xl font-semibold tracking-tight">{resumo.turma.nome}</h1>
          <Badge tom="destaque">{resumo.turma.ano_escolar}</Badge>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatCard icone={<Users size={15} />} rotulo="Alunos" valor={numero(resumo.total_alunos)} />
        <StatCard icone={<Calculator size={15} />} rotulo="Média geral" valor={fmtNota(resumo.media_geral)}
                  detalhe={`Matific ${fmtNota(resumo.media_matific)} · Leitura ${fmtNota(resumo.media_elefante)}`} />
        <StatCard icone={<BookOpen size={15} />} rotulo="Livros lidos" valor={numero(resumo.indicadores.livros_unicos ?? 0)} />
        <StatCard icone={<Clock size={15} />} rotulo="Tempo de leitura" valor={tempoLeitura(resumo.indicadores.tempo_leitura_min ?? 0)} />
      </div>

      {aviso && <Mensagem tipo={aviso.tipo}>{aviso.texto}</Mensagem>}

      <Card>
        {/* Barra de ferramentas: busca, ordenação, filtro */}
        <div className="flex flex-wrap items-center gap-3 border-b border-zinc-200 px-4 py-3 dark:border-zinc-800">
          <h3 className="text-sm font-semibold">Alunos da turma</h3>
          <label className="relative ml-auto block w-full sm:w-56">
            <Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-zinc-400" />
            <input
              className={`${estiloInput} pl-8`}
              placeholder="Pesquisar aluno..."
              value={busca}
              onChange={(e) => setBusca(e.target.value)}
            />
          </label>
          <select className={`${estiloInput} w-auto`} value={ordenar} onChange={(e) => setOrdenar(e.target.value)} aria-label="Ordenar por">
            {ORDENACOES.map((o) => <option key={o.valor} value={o.valor}>{o.rotulo}</option>)}
          </select>
          <label className="flex cursor-pointer items-center gap-2 text-sm text-zinc-600 dark:text-zinc-300">
            <input type="checkbox" className="h-4 w-4 rounded border-zinc-300 accent-indigo-600"
                   checked={incluirInativos} onChange={(e) => setIncluirInativos(e.target.checked)} />
            Mostrar arquivados
          </label>
        </div>

        {/* Barra de ações em massa */}
        {selecionados.size > 0 && (
          <div className="flex flex-wrap items-center gap-2 border-b border-indigo-200 bg-indigo-50/70 px-4 py-2.5 text-sm dark:border-indigo-500/20 dark:bg-indigo-500/10">
            <span className="font-medium text-indigo-800 dark:text-indigo-200">
              {selecionados.size} selecionado{selecionados.size === 1 ? "" : "s"}
            </span>
            <div className="ml-auto flex flex-wrap items-center gap-2">
              <Botao variante="neutro" onClick={() => setAcao({ tipo: "transferir", ids: idsSelecionados, rotulo: `${selecionados.size} alunos` })}>
                <ArrowRightLeft size={14} /> Transferir
              </Botao>
              <Botao variante="neutro" onClick={() => aplicarAcao("arquivar", idsSelecionados)}>
                <Archive size={14} /> Arquivar
              </Botao>
              <Botao variante="neutro" className="!border-red-300 !text-red-600 hover:!bg-red-50 dark:!border-red-500/30 dark:!text-red-400 dark:hover:!bg-red-500/10"
                     onClick={() => setAcao({ tipo: "excluir", ids: idsSelecionados, rotulo: `${selecionados.size} alunos` })}>
                <Trash2 size={14} /> Excluir
              </Botao>
              <Botao variante="neutro" className="!border-red-300 !text-red-600 hover:!bg-red-50 dark:!border-red-500/30 dark:!text-red-400 dark:hover:!bg-red-500/10"
                     onClick={() => setAcao({ tipo: "permanente", ids: idsSelecionados, rotulo: `${selecionados.size} alunos` })}>
                <TriangleAlert size={14} /> Excluir permanentemente
              </Botao>
              <button className="rounded-md p-1.5 text-zinc-500 hover:bg-zinc-200/60 dark:hover:bg-zinc-700/60" aria-label="Limpar seleção" onClick={() => setSelecionados(new Set())}>
                <X size={15} />
              </button>
            </div>
          </div>
        )}

        {alunos === null ? (
          <Carregando />
        ) : lista.length === 0 ? (
          <Vazio titulo={busca ? "Nenhum aluno encontrado" : "Turma sem alunos"}
                 descricao={busca ? "Ajuste a pesquisa." : "Adicione alunos ou importe dados das plataformas."} />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-zinc-200 text-left text-xs uppercase tracking-wide text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
                  <th className="w-10 px-4 py-2">
                    <input type="checkbox" aria-label="Selecionar todos" className="h-4 w-4 rounded border-zinc-300 accent-indigo-600"
                           checked={todosSelecionados} onChange={alternarTodos} />
                  </th>
                  <th className="px-2 py-2 font-medium">Aluno</th>
                  <th className="px-2 py-2 text-center font-medium">Nº</th>
                  <th className="px-2 py-2 text-right font-medium">Desempenho</th>
                  <th className="w-12 px-4 py-2"></th>
                </tr>
              </thead>
              <tbody>
                {lista.map((aluno) => {
                  const marcado = selecionados.has(aluno.id);
                  const badge = STATUS_BADGE[aluno.status];
                  return (
                    <tr key={aluno.id}
                        className={`border-b border-zinc-100 last:border-0 dark:border-zinc-800/60 ${
                          marcado ? "bg-indigo-50/50 dark:bg-indigo-500/5" : ""
                        } ${aluno.status !== "ativo" ? "opacity-60" : ""}`}>
                      <td className="px-4 py-2.5">
                        <input type="checkbox" aria-label={`Selecionar ${aluno.nome}`} className="h-4 w-4 rounded border-zinc-300 accent-indigo-600"
                               checked={marcado} onChange={() => alternarUm(aluno.id)} />
                      </td>
                      <td className="px-2 py-2.5">
                        <div className="flex items-center gap-2.5">
                          <Avatar aluno={aluno} />
                          <div className="min-w-0">
                            <Link to={`/alunos/${aluno.id}`} className="block truncate font-medium hover:text-indigo-600 dark:hover:text-indigo-400">
                              {aluno.nome}
                            </Link>
                            <div className="flex items-center gap-1.5">
                              {badge && <Badge tom={badge.tom}>{badge.texto}</Badge>}
                              {aluno.created_at && (
                                <span className="text-xs text-zinc-400">
                                  desde {new Date(aluno.created_at).toLocaleDateString("pt-BR")}
                                </span>
                              )}
                            </div>
                          </div>
                        </div>
                      </td>
                      <td className="px-2 py-2.5 text-center tabular-nums text-zinc-500 dark:text-zinc-400">
                        {aluno.numero_chamada ?? "—"}
                      </td>
                      <td className="px-2 py-2.5 text-right tabular-nums">
                        {aluno.nota_geral != null ? (
                          <span className="inline-flex items-center gap-1.5">
                            <span className="font-semibold">{fmtNota(aluno.nota_geral)}</span>
                            {aluno.posicao != null && <span className="text-xs text-zinc-400">{aluno.posicao}º</span>}
                          </span>
                        ) : (
                          <span className="text-xs text-zinc-400">sem nota</span>
                        )}
                      </td>
                      <td className="px-4 py-2.5 text-right">
                        <MenuAcoes aluno={aluno} aoEscolher={(escolha) => aoEscolherNoMenu(aluno, escolha)} />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {/* --- Modais ------------------------------------------------------- */}
      {acao?.tipo === "editar" && (
        <ModalEditar
          aluno={acao.alvo}
          ocupado={ocupado}
          aoFechar={() => setAcao(null)}
          aoSalvar={async (campos) => {
            setOcupado(true);
            try {
              await api(`/escolas/${escolaId}/alunos/${acao.alvo.id}`, {
                method: "PATCH", body: JSON.stringify(campos),
              });
              avisar("ok", "Aluno atualizado.");
              setAcao(null);
              recarregar();
            } catch (e) {
              avisar("erro", e instanceof ApiError ? e.message : "Falha ao salvar.");
            } finally {
              setOcupado(false);
            }
          }}
        />
      )}

      {acao?.tipo === "transferir" && (
        <ModalTransferir
          rotulo={acao.rotulo}
          turmas={turmas.filter((t) => t.id !== Number(id))}
          ocupado={ocupado}
          aoFechar={() => setAcao(null)}
          aoConfirmar={(turmaId) => aplicarAcao("transferir", acao.ids, turmaId)}
        />
      )}

      {acao?.tipo === "excluir" && (
        <Modal titulo="Excluir aluno" aberto aoFechar={() => setAcao(null)}>
          <p className="text-sm text-zinc-600 dark:text-zinc-300">
            Tem certeza de que deseja excluir <strong>{acao.rotulo}</strong>? O(s) aluno(s)
            sai(em) das listas e rankings. Os dados são mantidos e podem ser restaurados
            depois — para apagar tudo de vez, use “Excluir permanentemente”.
          </p>
          <div className="mt-5 flex justify-end gap-2">
            <Botao variante="neutro" onClick={() => setAcao(null)} disabled={ocupado}>Cancelar</Botao>
            <Botao className="!bg-red-600 hover:!bg-red-500" disabled={ocupado}
                   onClick={() => aplicarAcao("excluir", acao.ids)}>
              {ocupado ? "Excluindo..." : "Excluir"}
            </Botao>
          </div>
        </Modal>
      )}

      {acao?.tipo === "permanente" && (
        <ModalPermanente
          rotulo={acao.rotulo}
          quantidade={acao.ids.length}
          ocupado={ocupado}
          aoFechar={() => setAcao(null)}
          aoConfirmar={(confirmacao) =>
            executar(`/escolas/${escolaId}/alunos/excluir-permanente`,
              { aluno_ids: acao.ids, confirmacao }, "Alunos excluídos permanentemente.")}
        />
      )}
    </div>
  );
}

/** Modal de edição do cadastro do aluno. */
function ModalEditar({ aluno, ocupado, aoFechar, aoSalvar }: {
  aluno: AlunoGestao;
  ocupado: boolean;
  aoFechar: () => void;
  aoSalvar: (campos: { nome: string; numero_chamada: number | null }) => void;
}) {
  const [nome, setNome] = useState(aluno.nome);
  const [chamada, setChamada] = useState(aluno.numero_chamada?.toString() ?? "");
  return (
    <Modal titulo="Editar aluno" aberto aoFechar={aoFechar}>
      <div className="space-y-4">
        <Campo rotulo="Nome">
          <input className={estiloInput} value={nome} onChange={(e) => setNome(e.target.value)} />
        </Campo>
        <Campo rotulo="Nº de chamada">
          <input className={estiloInput} inputMode="numeric" value={chamada}
                 onChange={(e) => setChamada(e.target.value.replace(/\D/g, ""))} />
        </Campo>
      </div>
      <div className="mt-5 flex justify-end gap-2">
        <Botao variante="neutro" onClick={aoFechar} disabled={ocupado}>Cancelar</Botao>
        <Botao disabled={ocupado || nome.trim().length < 2}
               onClick={() => aoSalvar({ nome: nome.trim(), numero_chamada: chamada ? Number(chamada) : null })}>
          {ocupado ? "Salvando..." : "Salvar"}
        </Botao>
      </div>
    </Modal>
  );
}

/** Modal para transferir aluno(s) para outra turma. */
function ModalTransferir({ rotulo, turmas, ocupado, aoFechar, aoConfirmar }: {
  rotulo: string;
  turmas: Turma[];
  ocupado: boolean;
  aoFechar: () => void;
  aoConfirmar: (turmaId: number) => void;
}) {
  const [turmaId, setTurmaId] = useState<number | null>(turmas[0]?.id ?? null);
  return (
    <Modal titulo="Transferir de turma" aberto aoFechar={aoFechar}>
      <p className="mb-4 text-sm text-zinc-600 dark:text-zinc-300">
        Escolha a turma de destino para <strong>{rotulo}</strong>.
      </p>
      <Campo rotulo="Turma de destino">
        <select className={estiloInput} value={turmaId ?? ""} onChange={(e) => setTurmaId(Number(e.target.value))}>
          {turmas.length === 0 && <option value="">Nenhuma outra turma disponível</option>}
          {turmas.map((t) => <option key={t.id} value={t.id}>{t.nome}</option>)}
        </select>
      </Campo>
      <div className="mt-5 flex justify-end gap-2">
        <Botao variante="neutro" onClick={aoFechar} disabled={ocupado}>Cancelar</Botao>
        <Botao disabled={ocupado || !turmaId} onClick={() => turmaId && aoConfirmar(turmaId)}>
          {ocupado ? "Transferindo..." : "Transferir"}
        </Botao>
      </div>
    </Modal>
  );
}

/** Modal de exclusão PERMANENTE — dupla confirmação (digitar EXCLUIR). */
function ModalPermanente({ rotulo, quantidade, ocupado, aoFechar, aoConfirmar }: {
  rotulo: string;
  quantidade: number;
  ocupado: boolean;
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
            {quantidade === 1 ? <><strong>{rotulo}</strong> será removido</> : <><strong>{rotulo}</strong> serão removidos</>} por
            completo: cadastro, histórico, importações, leituras, dados da Matific e do
            Elefante Letrado, rankings, XP, medalhas e conquistas. Não há como desfazer.
          </p>
        </div>
      </div>
      <div className="mt-4">
        <Campo rotulo="Digite EXCLUIR para confirmar">
          <input className={estiloInput} value={texto} onChange={(e) => setTexto(e.target.value)}
                 placeholder="EXCLUIR" autoComplete="off" />
        </Campo>
      </div>
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
