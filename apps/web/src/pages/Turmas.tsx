/**
 * Gestão de Turmas — cadastro manual, edição, arquivamento e exclusão.
 *
 * A turma criada aqui fica imediatamente disponível em todo o sistema:
 * filtros, cadastro de alunos, importações, rankings e relatórios usam a
 * mesma listagem GET /turmas. Excluir é bloqueado pela API enquanto houver
 * alunos vinculados — arquivar é o caminho que preserva o histórico.
 * Arquivar também é recusado pela API (409, D17) enquanto houver aluno ATIVO
 * matriculado na turma no ano letivo ativo: arquivar não encerra matrícula,
 * então quem ainda está nela é transferido antes. A tela avisa no botão e
 * mostra a mensagem da API.
 * Excluir a turma JUNTO com os alunos (apaga fichas e dados) é exclusivo do
 * Admin Global (D19): para admin/coordenador da escola a tela não oferece o
 * botão destrutivo e orienta a transferir os alunos — menos na turma de ANO
 * ANTERIOR, cujas matrículas são histórico: “Transferir de turma” move a
 * matrícula do ano ativo (da turma atual da criança), então a orientação para
 * ela é “Arquivar”.
 */
import {
  Archive,
  ArchiveRestore,
  Combine,
  LayoutGrid,
  Pencil,
  Plus,
  School,
  Trash2,
  UserX,
  Users,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";

import {
  CabecalhoCartao,
  EsqueletoLista,
  PilulaSituacao,
  estiloCheckbox,
} from "../components/PessoasUi";
import { TabelaRolavel } from "../components/TabelaRolavel";
import {
  Avatar,
  Badge,
  BarraProgresso,
  Botao,
  Campo,
  Card,
  Carregando,
  Chip,
  Erro,
  Interruptor,
  Mensagem,
  Modal,
  PageHeader,
  StatCard,
  Vazio,
  classesTabela,
  estiloInput,
} from "../components/ui";
import { useApp } from "../context/AppContext";
import { limparCacheApi, useApi } from "../hooks/useApi";
import { ApiError, api } from "../lib/api";
// Códigos e rótulos de turno vêm da fonte única do front (lib/turnos.ts) —
// os mesmos que o filtro global de turno usa nos rankings e premiações.
import { TURNOS, rotuloTurno } from "../lib/turnos";
import type { Professor, Turma, TurmaPayload } from "../lib/types";

// --- Formulário (criar e editar) --------------------------------------------

interface Rascunho {
  nome: string;
  ano_escolar: string;
  ano_letivo: string;
  professor_id: string;
  turno: string;
  capacidade_maxima: string;
  observacoes: string;
}

function rascunhoDe(turma: Turma | null, anoPadrao: number): Rascunho {
  return {
    nome: turma?.nome ?? "",
    ano_escolar: turma?.ano_escolar ?? "",
    ano_letivo: String(turma?.ano_letivo ?? anoPadrao),
    professor_id: turma?.professor_id ? String(turma.professor_id) : "",
    turno: turma?.turno ?? "",
    capacidade_maxima: turma?.capacidade_maxima ? String(turma.capacidade_maxima) : "",
    observacoes: turma?.observacoes ?? "",
  };
}

/** Validação em tempo real — devolve a mensagem de cada campo inválido. */
function validar(r: Rascunho): Partial<Record<keyof Rascunho, string>> {
  const erros: Partial<Record<keyof Rascunho, string>> = {};
  if (!r.nome.trim()) erros.nome = "Informe o nome da turma (ex.: 4º Ano A).";
  else if (r.nome.trim().length > 100) erros.nome = "Máximo de 100 caracteres.";
  if (!r.ano_escolar.trim()) erros.ano_escolar = "Informe a série (ex.: 4º Ano).";
  const ano = Number(r.ano_letivo);
  if (!r.ano_letivo || !Number.isInteger(ano) || ano < 2000 || ano > 2100) {
    erros.ano_letivo = "Ano letivo entre 2000 e 2100.";
  }
  if (!r.turno) erros.turno = "Escolha o turno.";
  if (r.capacidade_maxima) {
    const capacidade = Number(r.capacidade_maxima);
    if (!Number.isInteger(capacidade) || capacidade < 1 || capacidade > 500) {
      erros.capacidade_maxima = "Use um número inteiro entre 1 e 500.";
    }
  }
  if (r.observacoes.length > 2000) erros.observacoes = "Máximo de 2000 caracteres.";
  return erros;
}

function FormularioTurma({
  aberto,
  turma,
  escolaNome,
  anoPadrao,
  professores,
  aoFechar,
  aoSalvo,
}: {
  aberto: boolean;
  turma: Turma | null;
  escolaNome: string;
  anoPadrao: number;
  professores: Professor[];
  aoFechar: () => void;
  aoSalvo: (salva: Turma) => void;
}) {
  const { escolaId } = useApp();
  const [rascunho, setRascunho] = useState<Rascunho>(() => rascunhoDe(turma, anoPadrao));
  const [tocados, setTocados] = useState<Partial<Record<keyof Rascunho, boolean>>>({});
  const [salvando, setSalvando] = useState(false);
  const [erroApi, setErroApi] = useState<string | null>(null);

  useEffect(() => {
    if (aberto) {
      setRascunho(rascunhoDe(turma, anoPadrao));
      setTocados({});
      setErroApi(null);
    }
  }, [aberto, turma, anoPadrao]);

  const erros = useMemo(() => validar(rascunho), [rascunho]);
  const valido = Object.keys(erros).length === 0;

  function definir<K extends keyof Rascunho>(campo: K, valor: string) {
    setRascunho((atual) => ({ ...atual, [campo]: valor }));
    setTocados((atual) => ({ ...atual, [campo]: true }));
  }

  function ErroCampo({ campo }: { campo: keyof Rascunho }) {
    if (!tocados[campo] || !erros[campo]) return null;
    return <p className="mt-1 text-xs font-medium text-rose-600 dark:text-rose-400">{erros[campo]}</p>;
  }

  async function salvar() {
    setTocados({
      nome: true, ano_escolar: true, ano_letivo: true, turno: true,
      capacidade_maxima: true, observacoes: true, professor_id: true,
    });
    if (!valido || !escolaId) return;
    const payload: TurmaPayload = {
      nome: rascunho.nome.trim(),
      ano_escolar: rascunho.ano_escolar.trim(),
      ano_letivo: Number(rascunho.ano_letivo),
      professor_id: rascunho.professor_id ? Number(rascunho.professor_id) : null,
      turno: rascunho.turno || null,
      capacidade_maxima: rascunho.capacidade_maxima
        ? Number(rascunho.capacidade_maxima)
        : null,
      observacoes: rascunho.observacoes.trim() || null,
    };
    setSalvando(true);
    setErroApi(null);
    try {
      const salva = turma
        ? await api<Turma>(`/escolas/${escolaId}/turmas/${turma.id}`, {
            method: "PUT",
            body: JSON.stringify(payload),
          })
        : await api<Turma>(`/escolas/${escolaId}/turmas`, {
            method: "POST",
            body: JSON.stringify(payload),
          });
      aoSalvo(salva);
    } catch (erro) {
      setErroApi(erro instanceof ApiError ? erro.message : "Não foi possível salvar a turma.");
    } finally {
      setSalvando(false);
    }
  }

  return (
    <Modal
      titulo={turma ? `Editar turma ${turma.nome}` : "Adicionar turma"}
      aberto={aberto}
      aoFechar={aoFechar}
    >
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div className="sm:col-span-2">
          <Campo rotulo="Nome da turma *">
            <input
              className={estiloInput}
              placeholder="ex.: 4º Ano A"
              value={rascunho.nome}
              onChange={(e) => definir("nome", e.target.value)}
              autoFocus
            />
          </Campo>
          <ErroCampo campo="nome" />
        </div>

        <div>
          <Campo rotulo="Série / Ano escolar *">
            <input
              className={estiloInput}
              placeholder="ex.: 4º Ano"
              value={rascunho.ano_escolar}
              onChange={(e) => definir("ano_escolar", e.target.value)}
            />
          </Campo>
          <ErroCampo campo="ano_escolar" />
        </div>

        <div>
          <Campo rotulo="Escola">
            <input className={`${estiloInput} opacity-70`} value={escolaNome} disabled />
          </Campo>
          <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
            A turma fica vinculada à escola selecionada.
          </p>
        </div>

        <div>
          <Campo rotulo="Turno *">
            <select
              className={estiloInput}
              value={rascunho.turno}
              onChange={(e) => definir("turno", e.target.value)}
            >
              <option value="">Selecione...</option>
              {TURNOS.map((turno) => (
                <option key={turno.valor} value={turno.valor}>
                  {turno.rotulo}
                </option>
              ))}
            </select>
          </Campo>
          <ErroCampo campo="turno" />
        </div>

        <div>
          <Campo rotulo="Ano letivo *">
            <input
              className={estiloInput}
              type="number"
              min={2000}
              max={2100}
              value={rascunho.ano_letivo}
              onChange={(e) => definir("ano_letivo", e.target.value)}
            />
          </Campo>
          <ErroCampo campo="ano_letivo" />
        </div>

        <div>
          <Campo rotulo="Professor responsável (opcional)">
            <select
              className={estiloInput}
              value={rascunho.professor_id}
              onChange={(e) => definir("professor_id", e.target.value)}
            >
              <option value="">— Sem professor —</option>
              {professores.map((professor) => (
                <option key={professor.id} value={professor.id}>
                  {professor.nome}
                </option>
              ))}
            </select>
          </Campo>
        </div>

        <div>
          <Campo rotulo="Quantidade máxima de alunos (opcional)">
            <input
              className={estiloInput}
              type="number"
              min={1}
              max={500}
              placeholder="ex.: 30"
              value={rascunho.capacidade_maxima}
              onChange={(e) => definir("capacidade_maxima", e.target.value)}
            />
          </Campo>
          <ErroCampo campo="capacidade_maxima" />
        </div>

        <div className="sm:col-span-2">
          <Campo rotulo="Observações (opcional)">
            <textarea
              className={`${estiloInput} min-h-20 resize-y`}
              placeholder="ex.: Sala 12, prédio novo."
              value={rascunho.observacoes}
              onChange={(e) => definir("observacoes", e.target.value)}
            />
          </Campo>
          <ErroCampo campo="observacoes" />
        </div>
      </div>

      {erroApi && (
        <div className="mt-3">
          <Mensagem tipo="erro">{erroApi}</Mensagem>
        </div>
      )}

      <div className="mt-6 flex justify-end gap-2.5">
        <Botao variante="secundario" onClick={aoFechar} disabled={salvando}>
          Cancelar
        </Botao>
        <Botao onClick={salvar} disabled={salvando || !valido}>
          {salvando ? "Salvando..." : turma ? "Salvar alterações" : "Criar turma"}
        </Botao>
      </div>
    </Modal>
  );
}

// --- Página ------------------------------------------------------------------

const ANOS_GRADE = [1, 2, 3, 4, 5, 6, 7, 8, 9];
const LETRAS_GRADE = ["A", "B", "C", "D", "E"];

/** Criação rápida de VÁRIAS turmas: grade Ano × Letra — marque as células e
 *  tudo é criado de uma vez (turno opcional aplicado a todas). Detalhes como
 *  capacidade e professor são ajustados depois, turma a turma. */
function CriarVariasTurmas({ escolaId, anoLetivo, existentes, aberto, aoFechar, aoConcluir }: {
  escolaId: number;
  anoLetivo: number;
  existentes: Set<string>;
  aberto: boolean;
  aoFechar: () => void;
  aoConcluir: (criadas: number, puladas: number) => void;
}) {
  const [marcadas, setMarcadas] = useState<Set<string>>(new Set());
  const [turno, setTurno] = useState("");
  const [criando, setCriando] = useState(false);
  const [erro, setErro] = useState("");

  function nomeDe(ano: number, letra: string) {
    return `${ano}º Ano ${letra}`;
  }
  function alternar(ano: number, letra: string) {
    const chave = `${ano}-${letra}`;
    setMarcadas((atuais) => {
      const prox = new Set(atuais);
      if (prox.has(chave)) prox.delete(chave);
      else prox.add(chave);
      return prox;
    });
  }

  async function criar() {
    setCriando(true);
    setErro("");
    let criadas = 0;
    let puladas = 0;
    for (const chave of marcadas) {
      const [ano, letra] = chave.split("-");
      const corpo: TurmaPayload = {
        nome: nomeDe(Number(ano), letra),
        ano_escolar: `${ano}º Ano`,
        ano_letivo: anoLetivo,
        professor_id: null,
        turno: turno || null,
        capacidade_maxima: null,
        observacoes: null,
      };
      try {
        await api<Turma>(`/escolas/${escolaId}/turmas`, {
          method: "POST",
          body: JSON.stringify(corpo),
        });
        criadas += 1;
      } catch (excecao) {
        // 409 = turma já existe: pula sem interromper as demais.
        if (excecao instanceof ApiError && excecao.status === 409) puladas += 1;
        else {
          setErro(excecao instanceof ApiError ? excecao.message : "Falha ao criar turmas.");
          setCriando(false);
          return;
        }
      }
    }
    setCriando(false);
    setMarcadas(new Set());
    aoConcluir(criadas, puladas);
  }

  if (!aberto) return null;
  return (
    <Modal titulo="Criar várias turmas" aberto={aberto} aoFechar={aoFechar} largura="max-w-xl">
      <p className="mb-3 text-sm text-zinc-600 dark:text-zinc-300">
        Marque as turmas que a escola tem — tudo é criado de uma vez no ano
        letivo {anoLetivo}. Depois ajuste turno, capacidade e professor turma a
        turma, se precisar.
      </p>
      <div className="relative overflow-x-auto">
        <table className="w-full text-center text-sm">
          <thead>
            <tr>
              <th className="px-2 py-1.5 text-left text-[11px] font-semibold uppercase tracking-[0.08em] text-zinc-500 dark:text-zinc-400">Ano</th>
              {LETRAS_GRADE.map((letra) => (
                <th key={letra} className="px-2 py-1.5 text-[11px] font-semibold uppercase tracking-[0.08em] text-zinc-500 dark:text-zinc-400">{letra}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {ANOS_GRADE.map((ano) => (
              <tr key={ano}>
                <td className="whitespace-nowrap px-2 py-1 text-left font-semibold text-zinc-700 dark:text-zinc-200">{ano}º Ano</td>
                {LETRAS_GRADE.map((letra) => {
                  const jaExiste = existentes.has(nomeDe(ano, letra).toLowerCase());
                  const marcada = marcadas.has(`${ano}-${letra}`);
                  return (
                    <td key={letra} className="px-1 py-1">
                      <button
                        type="button"
                        disabled={jaExiste}
                        title={jaExiste ? "Já existe" : nomeDe(ano, letra)}
                        aria-label={`${nomeDe(ano, letra)}${jaExiste ? " (já existe)" : ""}`}
                        onClick={() => alternar(ano, letra)}
                        aria-pressed={jaExiste ? undefined : marcada}
                        className={`h-10 w-full rounded-xl border text-sm font-semibold transition-colors ${
                          jaExiste
                            ? "cursor-not-allowed border-emerald-100 bg-emerald-50 text-emerald-600 dark:border-emerald-500/20 dark:bg-emerald-500/10 dark:text-emerald-300"
                            : marcada
                              ? "border-indigo-600 bg-indigo-600 text-white shadow-pilula"
                              : "border-zinc-200 bg-white text-zinc-600 hover:border-indigo-300 hover:bg-indigo-50 hover:text-indigo-700 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300"
                        }`}
                      >
                        {jaExiste ? "✓" : letra}
                      </button>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="mt-4">
        <Campo rotulo="Turno (opcional, aplicado a todas)">
          <select className={estiloInput} value={turno} onChange={(e) => setTurno(e.target.value)}>
            <option value="">— sem turno definido —</option>
            {TURNOS.map((t) => (
              <option key={t.valor} value={t.valor}>{t.rotulo}</option>
            ))}
          </select>
        </Campo>
      </div>

      {erro && <div className="mt-3"><Mensagem tipo="erro">{erro}</Mensagem></div>}
      <div className="mt-5 flex items-center justify-end gap-2">
        <span className="mr-auto text-sm text-zinc-500 dark:text-zinc-400">
          {marcadas.size} turma{marcadas.size === 1 ? "" : "s"} selecionada{marcadas.size === 1 ? "" : "s"}
        </span>
        <Botao variante="secundario" onClick={aoFechar} disabled={criando}>Cancelar</Botao>
        <Botao onClick={criar} disabled={criando || marcadas.size === 0}>
          {criando ? "Criando..." : `Criar ${marcadas.size} turma${marcadas.size === 1 ? "" : "s"}`}
        </Botao>
      </div>
    </Modal>
  );
}

// --- Consolidação de turmas duplicadas --------------------------------------

type TurmaDup = { id: number; nome: string; turno: string | null; alunos: number };
type GrupoDup = { chave: string; ano_letivo: number; canonica: TurmaDup; duplicadas: TurmaDup[] };

/** Detecta salas cadastradas com nomes diferentes (ex.: "1 ANO A TARDE ANUAL
 *  (300302821)" e "1ºA") e, ao aplicar, migra os alunos para o nome curto e
 *  remove as duplicadas. Revisão por grupo antes de aplicar. */
function ModalTurmasDuplicadas({ escolaId, aberto, aoFechar, aoConcluir }: {
  escolaId: number;
  aberto: boolean;
  aoFechar: () => void;
  aoConcluir: (mensagem: string) => void;
}) {
  const { dados: grupos, erro, carregando } = useApi<GrupoDup[]>(
    aberto ? `/escolas/${escolaId}/turmas/duplicadas` : null);
  const [escolhidos, setEscolhidos] = useState<Set<string>>(new Set());
  const [aplicando, setAplicando] = useState(false);
  const [erroApi, setErroApi] = useState("");

  // Por padrão, todos os grupos vêm marcados (o gestor pode desmarcar).
  useEffect(() => {
    if (grupos) setEscolhidos(new Set(grupos.map((g) => g.chave)));
  }, [grupos]);

  function alternar(chave: string) {
    setEscolhidos((atuais) => {
      const prox = new Set(atuais);
      if (prox.has(chave)) prox.delete(chave);
      else prox.add(chave);
      return prox;
    });
  }

  async function aplicar() {
    const alvos = (grupos ?? []).filter((g) => escolhidos.has(g.chave));
    if (alvos.length === 0) return;
    setAplicando(true);
    setErroApi("");
    try {
      const r = await api<{ mensagem: string }>(
        `/escolas/${escolaId}/turmas/duplicadas/corrigir`,
        {
          method: "POST",
          body: JSON.stringify(alvos.map((g) => ({
            canonica_id: g.canonica.id,
            duplicada_ids: g.duplicadas.map((d) => d.id),
          }))),
        },
      );
      aoConcluir(r.mensagem);
    } catch (e) {
      setErroApi(e instanceof ApiError ? e.message : "Não foi possível consolidar as turmas.");
    } finally {
      setAplicando(false);
    }
  }

  if (!aberto) return null;
  return (
    <Modal titulo="Corrigir turmas duplicadas" aberto={aberto} aoFechar={aoFechar}>
      {carregando ? (
        <Carregando />
      ) : erro ? (
        <Mensagem tipo="erro">{erro.message}</Mensagem>
      ) : (grupos ?? []).length === 0 ? (
        <Vazio
          titulo="Nenhuma turma duplicada encontrada"
          descricao="Não há salas cadastradas com nomes diferentes que representem a mesma turma."
        />
      ) : (
        <div className="space-y-4">
          <p className="text-sm text-zinc-600 dark:text-zinc-300">
            Encontrei salas cadastradas de formas diferentes. Em cada grupo, os alunos vão para o
            nome <strong>curto e padronizado</strong> (que fica) e as versões duplicadas são
            removidas. Revise e desmarque o que não quiser mexer.
          </p>
          <div className="max-h-[52vh] space-y-2 overflow-y-auto">
            {(grupos ?? []).map((g) => (
              <label
                key={g.chave}
                className="flex cursor-pointer gap-3 rounded-2xl border border-zinc-200/80 p-3.5 transition-colors hover:border-indigo-200 hover:bg-indigo-50/40 dark:border-zinc-800 dark:hover:bg-zinc-800/40"
              >
                <input
                  type="checkbox"
                  className={`mt-0.5 ${estiloCheckbox}`}
                  checked={escolhidos.has(g.chave)}
                  onChange={() => alternar(g.chave)}
                />
                <div className="min-w-0 text-sm">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge tom="ok">Fica: {g.canonica.nome}</Badge>
                    <span className="text-xs text-zinc-500 dark:text-zinc-400">
                      {g.canonica.alunos} aluno(s) · {g.ano_letivo}
                    </span>
                  </div>
                  <p className="mt-1.5 text-xs text-zinc-500 dark:text-zinc-400">
                    Migram para ela e são removidas:
                  </p>
                  <ul className="mt-0.5 list-disc space-y-0.5 pl-5 text-zinc-600 dark:text-zinc-300">
                    {g.duplicadas.map((d) => (
                      <li key={d.id}>
                        <span className="font-medium">{d.nome}</span>{" "}
                        <span className="text-xs text-zinc-500 dark:text-zinc-400">({d.alunos} aluno(s))</span>
                      </li>
                    ))}
                  </ul>
                </div>
              </label>
            ))}
          </div>
          {erroApi && <Mensagem tipo="erro">{erroApi}</Mensagem>}
          <div className="flex justify-end gap-2">
            <Botao variante="secundario" onClick={aoFechar} disabled={aplicando}>Cancelar</Botao>
            <Botao onClick={aplicar} disabled={aplicando || escolhidos.size === 0}>
              {aplicando ? "Consolidando..." : `Consolidar ${escolhidos.size} grupo(s)`}
            </Botao>
          </div>
        </div>
      )}
    </Modal>
  );
}

export default function Turmas() {
  const { escolaId, escolaAtual, usuario } = useApp();
  // Secretaria (rede vinculada, não-global): só visualiza. O backend recusa com
  // 403 todo POST/PUT/DELETE por-escola dela (deps.escola_autorizada), então a
  // tela não mostra criar, criar várias, editar, arquivar, excluir, seleção em
  // massa nem consolidar duplicadas. Coordenador/admin operam a própria escola.
  const secretaria = !usuario?.is_global && usuario?.rede_id != null;
  const podeEditar = !secretaria;
  // Excluir turma JUNTO com os alunos (exclusão física das fichas e dados) é
  // exclusivo do Admin Global (D19 — a API responde 403 para os demais). Para
  // admin/coordenador da escola a tela não oferece esse caminho e diz por quê.
  const podeApagarAlunos = usuario?.is_global === true;
  // Listagem de turmas (todas — o filtro visível é aplicado depois, no cliente).
  const {
    dados: turmas,
    erro: erroTurmas,
    carregando: carregandoTurmas,
    recarregar: recarregarLista,
  } = useApi<Turma[]>(escolaId ? `/escolas/${escolaId}/turmas?todas=true` : null);
  // Professores para o seletor do formulário.
  const { dados: professores } = useApi<Professor[]>(
    escolaId ? `/escolas/${escolaId}/professores` : null,
  );

  // Recarrega a lista E invalida o cache de /turmas usado pelos dropdowns de
  // filtro (rankings, premiações). Assim uma turma criada/editada/arquivada
  // aqui aparece imediatamente naquelas telas.
  function recarregarTurmas() {
    limparCacheApi(`/escolas/${escolaId}/turmas`);
    recarregarLista();
  }
  const [mostrarTodas, setMostrarTodas] = useState(false);
  const [formAberto, setFormAberto] = useState(false);
  const [variasAberto, setVariasAberto] = useState(false);
  const [dedupAberto, setDedupAberto] = useState(false);
  const [emEdicao, setEmEdicao] = useState<Turma | null>(null);
  const [paraExcluir, setParaExcluir] = useState<Turma | null>(null);
  const [erroExclusao, setErroExclusao] = useState<string | null>(null);
  const [excluindo, setExcluindo] = useState(false);
  // Seleção em massa (checkbox por linha + "selecionar todas") e o modal de
  // exclusão em massa. `confirmaApagarDados` trava o caminho destrutivo (apagar
  // também os alunos e seus dados) — LGPD: dados de crianças, sem volta.
  const [selecionadas, setSelecionadas] = useState<Set<number>>(new Set());
  const [exclusaoMassaAberta, setExclusaoMassaAberta] = useState(false);
  const [erroMassa, setErroMassa] = useState<string | null>(null);
  const [confirmaApagarDados, setConfirmaApagarDados] = useState(false);
  const selectAllRef = useRef<HTMLInputElement | null>(null);
  const [mensagem, setMensagem] = useState<{ tipo: "ok" | "erro"; texto: string } | null>(null);
  const temporizador = useRef<number | null>(null);

  const anoAtivo = escolaAtual?.ano_letivo_ativo ?? new Date().getFullYear();

  function avisar(tipo: "ok" | "erro", texto: string) {
    setMensagem({ tipo, texto });
    if (temporizador.current) window.clearTimeout(temporizador.current);
    temporizador.current = window.setTimeout(() => setMensagem(null), 6000);
  }

  const visiveis = (turmas ?? []).filter(
    (turma) => mostrarTodas || (turma.status === "ativa" && turma.ano_letivo === anoAtivo),
  );

  // Seleção: "todas" refere-se às turmas VISÍVEIS (as que o usuário vê agora).
  const idsVisiveis = visiveis.map((t) => t.id);
  const todasSelecionadas =
    idsVisiveis.length > 0 && idsVisiveis.every((id) => selecionadas.has(id));
  const algumasSelecionadas = idsVisiveis.some((id) => selecionadas.has(id));
  const turmasSelecionadas = (turmas ?? []).filter((t) => selecionadas.has(t.id));
  // Matrículas CRUAS (o que a exclusão realmente enxerga — inclui alunos
  // arquivados / de outro ano). É o sinal de "há dados a apagar", não o
  // total_alunos filtrado (que subestima e deixaria passar sem confirmação).
  const matriculasNasSelecionadas = turmasSelecionadas.reduce(
    (soma, t) => soma + (t.total_matriculas ?? 0),
    0,
  );
  // Selecionadas de ANO ANTERIOR com alunos: não se esvaziam por “Transferir de
  // turma” (histórico) — a orientação para elas é arquivar.
  const anterioresComAlunos = turmasSelecionadas.filter(
    (t) => t.ano_letivo < anoAtivo && (t.total_matriculas ?? 0) > 0,
  ).length;

  // Checkbox do cabeçalho fica "traço" (indeterminado) quando só parte está marcada.
  useEffect(() => {
    if (selectAllRef.current) {
      selectAllRef.current.indeterminate = algumasSelecionadas && !todasSelecionadas;
    }
  }, [algumasSelecionadas, todasSelecionadas]);

  function alternarSelecao(id: number) {
    setSelecionadas((atuais) => {
      const prox = new Set(atuais);
      if (prox.has(id)) prox.delete(id);
      else prox.add(id);
      return prox;
    });
  }

  function alternarTodas() {
    setSelecionadas((atuais) => {
      const marcadasTodas =
        idsVisiveis.length > 0 && idsVisiveis.every((id) => atuais.has(id));
      if (marcadasTodas) {
        const prox = new Set(atuais);
        idsVisiveis.forEach((id) => prox.delete(id));
        return prox;
      }
      return new Set([...atuais, ...idsVisiveis]);
    });
  }

  function abrirNova() {
    setEmEdicao(null);
    setFormAberto(true);
  }

  function abrirEdicao(turma: Turma) {
    setEmEdicao(turma);
    setFormAberto(true);
  }

  function aoSalvo(salva: Turma) {
    setFormAberto(false);
    // Turma de outro ano letivo (ou arquivada) ficaria oculta pelo filtro
    if (salva.status !== "ativa" || salva.ano_letivo !== anoAtivo) setMostrarTodas(true);
    avisar("ok", emEdicao
      ? `Turma “${salva.nome}” atualizada com sucesso.`
      : `Turma “${salva.nome}” criada com sucesso. Ela já está disponível em filtros, importações, rankings e relatórios.`);
    recarregarTurmas();
  }

  async function alternarArquivo(turma: Turma) {
    if (!escolaId) return;
    const novoStatus = turma.status === "ativa" ? "arquivada" : "ativa";
    try {
      await api<Turma>(`/escolas/${escolaId}/turmas/${turma.id}`, {
        method: "PUT",
        body: JSON.stringify({ status: novoStatus }),
      });
      if (novoStatus === "arquivada") setMostrarTodas(true);
      avisar("ok", novoStatus === "arquivada"
        ? `Turma “${turma.nome}” arquivada — ela sai dos filtros, mas o histórico é preservado.`
        : `Turma “${turma.nome}” reativada.`);
      recarregarTurmas();
    } catch (erro) {
      avisar("erro", erro instanceof ApiError ? erro.message : "Não foi possível alterar a turma.");
    }
  }

  async function excluir(comAlunos: boolean) {
    if (!escolaId || !paraExcluir) return;
    setExcluindo(true);
    setErroExclusao(null);
    try {
      const r = await api<{ mensagem: string }>(
        `/escolas/${escolaId}/turmas/${paraExcluir.id}?com_alunos=${comAlunos}`,
        { method: "DELETE" },
      );
      avisar("ok", r.mensagem);
      setSelecionadas((atuais) => {
        const prox = new Set(atuais);
        prox.delete(paraExcluir.id);
        return prox;
      });
      setParaExcluir(null);
      setConfirmaApagarDados(false);
      recarregarTurmas();
    } catch (erro) {
      setErroExclusao(
        erro instanceof ApiError ? erro.message : "Não foi possível excluir a turma.",
      );
    } finally {
      setExcluindo(false);
    }
  }

  async function excluirMassa(comAlunos: boolean) {
    if (!escolaId || selecionadas.size === 0) return;
    setExcluindo(true);
    setErroMassa(null);
    try {
      const r = await api<{
        mensagem: string;
        excluidas: number;
        bloqueadas: number;
        alunos_excluidos: number;
      }>(`/escolas/${escolaId}/turmas/excluir`, {
        method: "POST",
        body: JSON.stringify({ turma_ids: [...selecionadas], com_alunos: comAlunos }),
      });
      avisar(r.excluidas > 0 ? "ok" : "erro", r.mensagem);
      setSelecionadas(new Set());
      setExclusaoMassaAberta(false);
      setConfirmaApagarDados(false);
      recarregarTurmas();
    } catch (erro) {
      setErroMassa(
        erro instanceof ApiError ? erro.message : "Não foi possível excluir as turmas.",
      );
    } finally {
      setExcluindo(false);
    }
  }

  // Indicadores do topo: contagens REAIS da listagem (turmas ativas do ano letivo
  // ativo — o mesmo recorte padrão da tabela).
  const ativasDoAno = (turmas ?? []).filter((t) => t.status === "ativa" && t.ano_letivo === anoAtivo);
  const alunosNasAtivas = ativasDoAno.reduce((soma, t) => soma + (t.total_alunos ?? 0), 0);
  const semTitular = ativasDoAno.filter((t) => t.professor_id == null).length;

  // No celular (< 640 px) os botões de ação ganham 40 px (alvo de toque).
  const estiloAcao =
    "grid h-9 w-9 place-items-center rounded-full text-zinc-500 transition-colors hover:bg-indigo-50 hover:text-indigo-600 max-sm:h-10 max-sm:w-10 dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-indigo-300";
  const estiloAcaoPerigo =
    "grid h-9 w-9 place-items-center rounded-full text-zinc-500 transition-colors hover:bg-rose-50 hover:text-rose-600 max-sm:h-10 max-sm:w-10 dark:text-zinc-400 dark:hover:bg-rose-500/10 dark:hover:text-rose-300";
  // Abaixo de 1280 px (tablet e notebook com a gaveta) as células ficam mais justas,
  // para a coluna Ações (editar, arquivar, excluir) caber inteira sem rolagem lateral.
  const th = classesTabela.th.replace("px-4", "px-3 xl:px-4");
  const td = classesTabela.td.replace("px-4", "px-3 xl:px-4");
  const thSelecao = classesTabela.th.replace("px-4", "pl-3 pr-1 xl:px-4");

  return (
    <div>
      <PageHeader
        titulo="Turmas"
        descricao={podeEditar
          ? "Cadastre, edite e organize as turmas da escola."
          : "Turmas da escola selecionada, só para consulta. Quem cadastra e edita é a escola."}
        acoes={podeEditar ? (
          <>
            <Botao variante="secundario" onClick={() => setDedupAberto(true)}>
              <Combine size={16} aria-hidden /> Corrigir duplicadas
            </Botao>
            <Botao variante="secundario" onClick={() => setVariasAberto(true)}>
              <LayoutGrid size={16} aria-hidden /> Criar várias
            </Botao>
            <Botao onClick={abrirNova}>
              <Plus size={16} aria-hidden /> Adicionar Turma
            </Botao>
          </>
        ) : undefined}
      />

      {escolaId && (
        <ModalTurmasDuplicadas
          escolaId={escolaId}
          aberto={dedupAberto}
          aoFechar={() => setDedupAberto(false)}
          aoConcluir={(mensagem) => {
            setDedupAberto(false);
            setSelecionadas(new Set());
            avisar("ok", mensagem);
            recarregarTurmas();
          }}
        />
      )}

      {escolaId && (
        <CriarVariasTurmas
          escolaId={escolaId}
          anoLetivo={anoAtivo}
          existentes={new Set((turmas ?? [])
            .filter((t) => t.ano_letivo === anoAtivo)
            .map((t) => t.nome.toLowerCase()))}
          aberto={variasAberto}
          aoFechar={() => setVariasAberto(false)}
          aoConcluir={(criadas, puladas) => {
            setVariasAberto(false);
            avisar("ok", `${criadas} turma(s) criada(s)` +
              (puladas > 0 ? ` (${puladas} já existiam e foram puladas).` : ".") +
              " Ajuste turno, capacidade e professor em cada turma quando quiser.");
            recarregarTurmas();
          }}
        />
      )}

      {turmas && !erroTurmas && (
        <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-3 sm:gap-5 max-sm:[&>*:last-child:nth-child(odd)]:col-span-2">
          <StatCard icone={<School size={20} />} tom="violeta" rotulo={`Turmas ativas em ${anoAtivo}`}
                    valor={String(ativasDoAno.length)} />
          <StatCard icone={<Users size={20} />} tom="teal" rotulo="Alunos nessas turmas"
                    valor={alunosNasAtivas.toLocaleString("pt-BR")}
                    detalhe="Alunos ativos matriculados no ano letivo" />
          <StatCard icone={<UserX size={20} />} tom={semTitular ? "ambar" : "verde"} rotulo="Sem professor titular"
                    valor={String(semTitular)}
                    detalhe={semTitular
                      ? (podeEditar ? "Defina o titular em “Editar”" : "Turmas ativas ainda sem titular")
                      : "Todas as turmas têm titular"} />
        </div>
      )}

      {mensagem && (
        <div className="mb-4">
          <Mensagem tipo={mensagem.tipo}>{mensagem.texto}</Mensagem>
        </div>
      )}

      {podeEditar && selecionadas.size > 0 && (
        <div className="mb-4 flex flex-wrap items-center gap-3 rounded-2xl border border-indigo-100 bg-indigo-50 px-4 py-3 dark:border-indigo-500/20 dark:bg-indigo-500/10">
          <span className="text-sm font-semibold text-indigo-800 dark:text-indigo-200">
            {selecionadas.size} turma{selecionadas.size === 1 ? "" : "s"} selecionada
            {selecionadas.size === 1 ? "" : "s"}
          </span>
          <div className="ml-auto flex items-center gap-2">
            <Botao variante="secundario" tamanho="sm" onClick={() => setSelecionadas(new Set())}>
              Limpar seleção
            </Botao>
            <Botao
              variante="perigo"
              tamanho="sm"
              onClick={() => {
                setErroMassa(null);
                setConfirmaApagarDados(false);
                setExclusaoMassaAberta(true);
              }}
            >
              <Trash2 size={14} aria-hidden /> Excluir selecionadas
            </Botao>
          </div>
        </div>
      )}

      <Card className="overflow-hidden">
        <CabecalhoCartao
          titulo={mostrarTodas ? "Todas as turmas" : `Turmas de ${anoAtivo}`}
          contagem={turmas && !erroTurmas
            ? `${visiveis.length} turma${visiveis.length === 1 ? "" : "s"}`
            : undefined}
          acoes={
            <span className="inline-flex items-center gap-2.5 text-sm text-zinc-600 dark:text-zinc-300">
              {/* O nome acessível está no próprio interruptor; o texto ao lado é só visual. */}
              <span aria-hidden className="cursor-pointer select-none" onClick={() => setMostrarTodas((v) => !v)}>
                Mostrar arquivadas e de outros anos
              </span>
              <Interruptor
                ligado={mostrarTodas}
                aoMudar={setMostrarTodas}
                rotulo="Mostrar turmas arquivadas e de outros anos letivos"
              />
            </span>
          }
        />
        {carregandoTurmas ? (
          <EsqueletoLista texto="Carregando turmas..." />
        ) : erroTurmas ? (
          <Erro descricao={erroTurmas.message} aoTentar={recarregarLista} />
        ) : visiveis.length === 0 ? (
          (turmas ?? []).length === 0 ? (
            <Vazio
              icone={School}
              titulo="Nenhuma turma cadastrada"
              descricao={podeEditar
                ? "Use o botão “Adicionar Turma” (ou “Criar várias”) para criar a primeira."
                : "Esta escola ainda não cadastrou turmas."}
            />
          ) : (
            // Existem turmas, mas todas fora do recorte padrão (arquivadas ou de
            // outro ano letivo): dizer "nenhuma cadastrada" induziria ao erro.
            <Vazio
              icone={School}
              titulo={`Nenhuma turma ativa em ${anoAtivo}`}
              descricao="As turmas cadastradas estão arquivadas ou são de outros anos letivos."
              acao={
                <Botao variante="secundario" onClick={() => setMostrarTodas(true)}>
                  Ver arquivadas e de outros anos
                </Botao>
              }
            />
          )
        ) : (
          // Celular (< 640 px): a tabela rola de lado dentro do cartão, com o aviso em
          // texto acima dela, e a coluna Ações fica presa à direita (`presa-celular`):
          // editar, arquivar e excluir aparecem sem rolar. O Professor agora vem também no
          // celular, com a rolagem (antes sumia abaixo de 768 px, sem rolagem que o
          // mostrasse); de 640 a 767 px as Ações não ficam presas, então ele segue fora
          // como antes, para a coluna Ações caber.
          <TabelaRolavel rotulo="Turmas: tabela completa">
            <table className={classesTabela.tabela}>
              <thead>
                <tr>
                  {podeEditar && (
                    <th className={`w-8 xl:w-10 ${thSelecao}`}>
                      <input
                        ref={selectAllRef}
                        type="checkbox"
                        className={estiloCheckbox}
                        checked={todasSelecionadas}
                        onChange={alternarTodas}
                        aria-label="Selecionar todas as turmas visíveis"
                        title="Selecionar todas"
                      />
                    </th>
                  )}
                  <th className={th}>Turma</th>
                  <th className={th}>Série</th>
                  <th className={`hidden max-sm:table-cell md:table-cell ${th}`}>Professor</th>
                  <th className={th}>Alunos</th>
                  {/* Ano letivo a partir de sm (como na a508768): com "arquivadas e de outros
                      anos" ligado, é o que separa duas "5º A" de anos diferentes. Abaixo de
                      xl o rótulo encurta para "Ano" (o nome completo segue no leitor de tela
                      e no title). */}
                  <th className={`hidden sm:table-cell ${th}`} title="Ano letivo">
                    Ano<span className="sr-only xl:not-sr-only xl:whitespace-nowrap"> letivo</span>
                  </th>
                  <th className={th}>Situação</th>
                  {podeEditar && <th className={`text-right ${th} presa-celular`}>Ações</th>}
                </tr>
              </thead>
              <tbody>
                {visiveis.map((turma) => {
                  // Ocupação só quando a turma tem capacidade cadastrada (dado real).
                  const ocupacao = turma.capacidade_maxima
                    ? Math.round((turma.total_alunos / turma.capacidade_maxima) * 100)
                    : null;
                  return (
                    <tr
                      key={turma.id}
                      className={`${classesTabela.tr} ${
                        selecionadas.has(turma.id) ? "bg-indigo-50/60 dark:bg-indigo-500/10" : ""
                      }`}
                    >
                      {podeEditar && (
                        <td className="py-3.5 pl-3 pr-1 xl:px-4">
                          <input
                            type="checkbox"
                            className={estiloCheckbox}
                            checked={selecionadas.has(turma.id)}
                            onChange={() => alternarSelecao(turma.id)}
                            aria-label={`Selecionar turma ${turma.nome}`}
                          />
                        </td>
                      )}
                      <td className={td}>
                        <Link
                          to={`/turmas/${turma.id}`}
                          className="whitespace-nowrap font-semibold text-zinc-900 transition-colors hover:text-indigo-600 dark:text-zinc-100 dark:hover:text-indigo-300"
                        >
                          {turma.nome}
                        </Link>
                        {/* O turno (quando há) vem sob o nome, em todas as larguras: sem coluna
                            própria, a coluna Ações cabe no tablet e o dado aparece uma vez só. */}
                        {turma.turno && (
                          <span className="mt-0.5 block whitespace-nowrap text-xs text-zinc-500 dark:text-zinc-400">
                            {rotuloTurno(turma.turno)}
                          </span>
                        )}
                      </td>
                      <td className={td}>
                        <Chip className="whitespace-nowrap">{turma.ano_escolar}</Chip>
                      </td>
                      <td className={`hidden max-sm:table-cell md:table-cell ${td}`}>
                        {turma.professor_nome ? (
                          <span className="inline-flex items-center gap-2">
                            {/* O avatar (decorativo) só a partir de xl: no tablet, o espaço
                                vai para as ações. No celular (tabela que rola) o nome fica
                                numa linha só, sem uma palavra por linha. */}
                            <Avatar nome={turma.professor_nome} chave={`prof-${turma.professor_id ?? turma.professor_nome}`} tamanho="sm" className="hidden xl:grid" />
                            <span className="text-zinc-700 max-sm:whitespace-nowrap dark:text-zinc-200">{turma.professor_nome}</span>
                          </span>
                        ) : (
                          <span className="text-zinc-500 dark:text-zinc-400">—</span>
                        )}
                      </td>
                      <td className={td}>
                        <span className="whitespace-nowrap">
                          <span className="font-semibold tabular-nums text-zinc-900 dark:text-zinc-100">
                            {turma.total_alunos}
                          </span>
                          {turma.capacidade_maxima ? (
                            <span className="tabular-nums text-zinc-500 dark:text-zinc-400"> / {turma.capacidade_maxima}</span>
                          ) : null}
                        </span>
                        {ocupacao != null && (
                          <span className="mt-1.5 flex items-center gap-2" title={`Ocupação: ${ocupacao}% da capacidade`}>
                            <BarraProgresso valor={ocupacao} tom={ocupacao > 100 ? "ambar" : "violeta"} className="w-20" />
                            <span className="text-[11px] tabular-nums text-zinc-500 dark:text-zinc-400">{ocupacao}%</span>
                          </span>
                        )}
                      </td>
                      <td className={`hidden tabular-nums text-zinc-500 sm:table-cell dark:text-zinc-400 ${td}`}>
                        {turma.ano_letivo}
                      </td>
                      <td className={td}>
                        {turma.status === "ativa" ? (
                          <PilulaSituacao tom="ok">Ativa</PilulaSituacao>
                        ) : (
                          <PilulaSituacao tom="neutro">Arquivada</PilulaSituacao>
                        )}
                      </td>
                      {podeEditar && (
                        <td className={`presa-celular py-2 pl-1 pr-2 xl:px-4 ${
                          // A célula presa tem fundo opaco: na linha marcada, o mesmo tom dela.
                          selecionadas.has(turma.id) ? "max-sm:bg-indigo-50 dark:max-sm:bg-[#24244a]" : ""
                        }`}>
                          <div className="flex justify-end gap-0.5">
                            <button
                              type="button"
                              title="Editar"
                              aria-label={`Editar turma ${turma.nome}`}
                              className={estiloAcao}
                              onClick={() => abrirEdicao(turma)}
                            >
                              <Pencil size={16} aria-hidden />
                            </button>
                            <button
                              type="button"
                              title={
                                turma.status !== "ativa"
                                  ? "Reativar"
                                  : turma.ano_letivo >= anoAtivo && turma.total_alunos > 0
                                    ? `Arquivar — antes, transfira os ${turma.total_alunos} aluno(s) ativo(s) desta turma`
                                    : "Arquivar"
                              }
                              aria-label={`${turma.status === "ativa" ? "Arquivar" : "Reativar"} turma ${turma.nome}`}
                              className={estiloAcao}
                              onClick={() => alternarArquivo(turma)}
                            >
                              {turma.status === "ativa" ? (
                                <Archive size={16} aria-hidden />
                              ) : (
                                <ArchiveRestore size={16} aria-hidden />
                              )}
                            </button>
                            <button
                              type="button"
                              title="Excluir"
                              aria-label={`Excluir turma ${turma.nome}`}
                              className={estiloAcaoPerigo}
                              onClick={() => {
                                setErroExclusao(null);
                                setConfirmaApagarDados(false);
                                setParaExcluir(turma);
                              }}
                            >
                              <Trash2 size={16} aria-hidden />
                            </button>
                          </div>
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </TabelaRolavel>
        )}
      </Card>

      <FormularioTurma
        aberto={formAberto}
        turma={emEdicao}
        escolaNome={escolaAtual?.nome ?? ""}
        anoPadrao={anoAtivo}
        professores={professores ?? []}
        aoFechar={() => setFormAberto(false)}
        aoSalvo={aoSalvo}
      />

      <Modal
        titulo="Excluir turma"
        aberto={paraExcluir !== null}
        aoFechar={() => setParaExcluir(null)}
      >
        {(() => {
          // Conta CRUA (o que a exclusão enxerga): pega alunos arquivados / de
          // outro ano que o total_alunos filtrado esconderia. É o que decide se
          // há dados a apagar — evita liberar o botão destrutivo sem confirmação.
          const matriculas = paraExcluir?.total_matriculas ?? 0;
          const temAlunos = matriculas > 0;
          // Turma de ANO ANTERIOR: as matrículas dela são histórico e não saem
          // por “Transferir de turma” (ele move a matrícula do ano ativo, da
          // turma atual da criança — a API recusa a partir do painel dela). A
          // saída é arquivar, que o D17 permite para turma de ano passado.
          const deAnoAnterior = paraExcluir != null && paraExcluir.ano_letivo < anoAtivo;
          return (
            <>
              <p className="text-sm text-zinc-600 dark:text-zinc-300">
                Excluir a turma <strong>{paraExcluir?.nome}</strong> ({paraExcluir?.ano_letivo})?
                Esta ação é definitiva e não pode ser desfeita.
              </p>

              {temAlunos ? (
                <>
                  <div className="mt-3 rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800 dark:border-amber-900/60 dark:bg-amber-950/30 dark:text-amber-200">
                    Esta turma tem <strong>{matriculas} aluno(s)</strong> matriculado(s). Escolha o
                    que fazer:
                    <ul className="mt-1.5 list-disc space-y-0.5 pl-5">
                      <li>
                        <strong>Excluir só a turma</strong> — indisponível enquanto houver alunos.
                        {deAnoAnterior ? (
                          <>
                            {" "}Como a turma é do ano letivo {paraExcluir?.ano_letivo}, use
                            “Arquivar” para tirá-la da lista: o histórico fica preservado.
                          </>
                        ) : (
                          <>
                            {" "}Mova/remova os alunos antes, ou use “Arquivar” para preservar o
                            histórico (arquivar exige que nenhum aluno ativo esteja na turma).
                          </>
                        )}
                      </li>
                      <li>
                        <strong>Excluir turma + alunos e dados</strong> — apaga a turma e também os
                        alunos com todos os seus dados (leituras, notas, conquistas, snapshots). Um
                        aluno que também esteja em outra turma é apenas desvinculado desta.
                        {!podeApagarAlunos && <> <strong>Exclusivo do Admin Global.</strong></>}
                      </li>
                    </ul>
                  </div>
                  {podeApagarAlunos ? (
                    <label className="mt-3 flex cursor-pointer items-start gap-2 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800 dark:border-red-900/60 dark:bg-red-950/30 dark:text-red-200">
                      <input
                        type="checkbox"
                        className="mt-0.5 h-4 w-4 shrink-0 rounded border-rose-300 accent-rose-600"
                        checked={confirmaApagarDados}
                        onChange={(e) => setConfirmaApagarDados(e.target.checked)}
                      />
                      <span>
                        Entendo que os alunos desta turma e <strong>todos os seus dados</strong> serão
                        apagados permanentemente. Sem volta.
                      </span>
                    </label>
                  ) : (
                    <p className="mt-3 rounded-xl border border-zinc-200 bg-zinc-50 p-3 text-sm text-zinc-700 dark:border-zinc-700 dark:bg-zinc-900/40 dark:text-zinc-300">
                      Apagar os alunos junto com a turma é exclusivo do Admin Global.{" "}
                      {deAnoAnterior ? (
                        <>
                          Esta turma é do ano letivo {paraExcluir?.ano_letivo}: as matrículas dela
                          são histórico e não saem por “Transferir de turma” (ele move a matrícula
                          do ano ativo, da turma atual do aluno). Para tirá-la da lista, use
                          “Arquivar” — o histórico fica preservado.
                        </>
                      ) : (
                        <>
                          Para excluir esta turma, abra-a e use “Transferir de turma” nos alunos;
                          depois volte aqui e exclua só a turma.
                        </>
                      )}
                    </p>
                  )}
                </>
              ) : (
                <p className="mt-2 text-sm text-zinc-500 dark:text-zinc-400">
                  A turma não tem alunos matriculados.
                </p>
              )}

              {erroExclusao && (
                <div className="mt-3">
                  <Mensagem tipo="erro">{erroExclusao}</Mensagem>
                </div>
              )}

              <div className="mt-6 flex flex-wrap justify-end gap-2.5">
                <Botao variante="secundario" onClick={() => setParaExcluir(null)} disabled={excluindo}>
                  Cancelar
                </Botao>
                {temAlunos ? (
                  <>
                    <Botao
                      variante="secundario"
                      disabled
                      title={deAnoAnterior
                        ? "A turma é de ano anterior e tem alunos — use “Arquivar” para tirá-la da lista."
                        : podeApagarAlunos
                          ? "A turma tem alunos — mova/remova os alunos ou use “turma + alunos e dados”."
                          : "A turma tem alunos — transfira os alunos para outra turma antes."}
                    >
                      Excluir só a turma
                    </Botao>
                    {podeApagarAlunos && (
                      <Botao
                        variante="perigo"
                        onClick={() => excluir(true)}
                        disabled={excluindo || !confirmaApagarDados}
                      >
                        {excluindo ? "Excluindo..." : "Excluir turma + alunos e dados"}
                      </Botao>
                    )}
                  </>
                ) : (
                  <Botao
                    variante="perigo"
                    onClick={() => excluir(false)}
                    disabled={excluindo}
                  >
                    {excluindo ? "Excluindo..." : "Sim, excluir"}
                  </Botao>
                )}
              </div>
            </>
          );
        })()}
      </Modal>

      <Modal
        titulo="Excluir turmas selecionadas"
        aberto={exclusaoMassaAberta}
        aoFechar={() => setExclusaoMassaAberta(false)}
      >
        <p className="text-sm text-zinc-600 dark:text-zinc-300">
          Você selecionou <strong>{selecionadas.size} turma(s)</strong>
          {matriculasNasSelecionadas > 0 ? (
            <>
              , com <strong>{matriculasNasSelecionadas} aluno(s)</strong> matriculado(s).
            </>
          ) : (
            <> (sem alunos matriculados).</>
          )}{" "}
          Esta ação é definitiva e não pode ser desfeita.
        </p>

        <div className="mt-3 rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800 dark:border-amber-900/60 dark:bg-amber-950/30 dark:text-amber-200">
          Escolha o que fazer:
          <ul className="mt-1.5 list-disc space-y-0.5 pl-5">
            <li>
              <strong>Excluir só as turmas</strong> — remove as turmas vazias. As que ainda têm
              alunos são <strong>mantidas</strong> (arquive ou remova os alunos antes).
            </li>
            <li>
              <strong>Excluir turmas + alunos e dados</strong> — apaga as turmas e também os alunos
              matriculados nelas, com todos os seus dados. Um aluno que também esteja em outra turma
              (não selecionada) é apenas desvinculado, não apagado. Irreversível.
              {!podeApagarAlunos && <> <strong>Exclusivo do Admin Global.</strong></>}
            </li>
          </ul>
        </div>

        {matriculasNasSelecionadas > 0 && !podeApagarAlunos && (
          <p className="mt-3 rounded-xl border border-zinc-200 bg-zinc-50 p-3 text-sm text-zinc-700 dark:border-zinc-700 dark:bg-zinc-900/40 dark:text-zinc-300">
            Apagar os alunos junto com as turmas é exclusivo do Admin Global. “Excluir só as
            turmas” remove as vazias e mantém as que têm alunos — transfira esses alunos antes.
            {anterioresComAlunos > 0 && (
              <>
                {" "}Turmas de ano anterior ({anterioresComAlunos}) não se esvaziam assim: as
                matrículas delas são histórico e “Transferir de turma” move a matrícula do ano
                ativo. Para tirá-las da lista, use “Arquivar” — o histórico fica preservado.
              </>
            )}
          </p>
        )}

        {matriculasNasSelecionadas > 0 && podeApagarAlunos && (
          <label className="mt-3 flex cursor-pointer items-start gap-2 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800 dark:border-red-900/60 dark:bg-red-950/30 dark:text-red-200">
            <input
              type="checkbox"
              className="mt-0.5 h-4 w-4 shrink-0 rounded border-rose-300 accent-rose-600"
              checked={confirmaApagarDados}
              onChange={(e) => setConfirmaApagarDados(e.target.checked)}
            />
            <span>
              Entendo que os <strong>{matriculasNasSelecionadas} aluno(s)</strong> das turmas
              selecionadas e <strong>todos os seus dados</strong> serão apagados permanentemente.
              Sem volta.
            </span>
          </label>
        )}

        {erroMassa && (
          <div className="mt-3">
            <Mensagem tipo="erro">{erroMassa}</Mensagem>
          </div>
        )}

        <div className="mt-6 flex flex-wrap justify-end gap-2.5">
          <Botao
            variante="secundario"
            onClick={() => setExclusaoMassaAberta(false)}
            disabled={excluindo}
          >
            Cancelar
          </Botao>
          <Botao variante="secundario" onClick={() => excluirMassa(false)} disabled={excluindo}>
            {excluindo ? "Excluindo..." : "Excluir só as turmas"}
          </Botao>
          {/* O caminho destrutivo só aparece quando há alunos a apagar (conta
              crua). Assim um número desatualizado/zero nunca dispara com_alunos
              sem a confirmação — se surgirem alunos depois, o backend mantém as
              turmas (bloqueadas) via "Excluir só as turmas". Só para o Admin
              Global (D19): para os demais a API responderia 403. */}
          {matriculasNasSelecionadas > 0 && podeApagarAlunos && (
            <Botao
              variante="perigo"
              onClick={() => excluirMassa(true)}
              disabled={excluindo || !confirmaApagarDados}
            >
              {excluindo ? "Excluindo..." : "Excluir turmas + alunos e dados"}
            </Botao>
          )}
        </div>
      </Modal>
    </div>
  );
}
