/**
 * Gestão de Turmas — cadastro manual, edição, arquivamento e exclusão.
 *
 * A turma criada aqui fica imediatamente disponível em todo o sistema:
 * filtros, cadastro de alunos, importações, rankings e relatórios usam a
 * mesma listagem GET /turmas. Excluir é bloqueado pela API enquanto houver
 * alunos vinculados — arquivar é o caminho que preserva o histórico.
 */
import { Archive, ArchiveRestore, LayoutGrid, Pencil, Plus, Trash2 } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
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
  Vazio,
  estiloInput,
} from "../components/ui";
import { useApp } from "../context/AppContext";
import { limparCacheApi, useApi } from "../hooks/useApi";
import { ApiError, api } from "../lib/api";
import type { Professor, Turma, TurmaPayload } from "../lib/types";

const TURNOS = [
  { valor: "manha", rotulo: "Manhã" },
  { valor: "tarde", rotulo: "Tarde" },
  { valor: "noite", rotulo: "Noite" },
  { valor: "integral", rotulo: "Integral" },
] as const;

function rotuloTurno(valor: string | null): string {
  return TURNOS.find((t) => t.valor === valor)?.rotulo ?? "—";
}

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
    return <p className="mt-1 text-xs text-red-600 dark:text-red-400">{erros[campo]}</p>;
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

      <div className="mt-4 flex justify-end gap-2">
        <Botao variante="neutro" onClick={aoFechar} disabled={salvando}>
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
    <Modal titulo="Criar várias turmas" aberto={aberto} aoFechar={aoFechar}>
      <p className="mb-3 text-sm text-zinc-600 dark:text-zinc-300">
        Marque as turmas que a escola tem — tudo é criado de uma vez no ano
        letivo {anoLetivo}. Depois ajuste turno, capacidade e professor turma a
        turma, se precisar.
      </p>
      <div className="overflow-x-auto">
        <table className="w-full text-center text-sm">
          <thead>
            <tr>
              <th className="px-2 py-1.5 text-left text-xs font-medium uppercase tracking-wide text-zinc-500 dark:text-zinc-400">Ano</th>
              {LETRAS_GRADE.map((letra) => (
                <th key={letra} className="px-2 py-1.5 text-xs font-medium uppercase tracking-wide text-zinc-500 dark:text-zinc-400">{letra}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {ANOS_GRADE.map((ano) => (
              <tr key={ano} className="border-t border-zinc-100 dark:border-zinc-800/60">
                <td className="px-2 py-1.5 text-left font-medium">{ano}º Ano</td>
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
                        className={`h-9 w-full rounded-lg border text-sm font-medium transition-colors ${
                          jaExiste
                            ? "cursor-not-allowed border-zinc-200 bg-zinc-100 text-zinc-400 dark:border-zinc-800 dark:bg-zinc-800/60 dark:text-zinc-600"
                            : marcada
                              ? "border-indigo-600 bg-indigo-600 text-white"
                              : "border-zinc-300 text-zinc-600 hover:border-indigo-400 hover:text-indigo-600 dark:border-zinc-700 dark:text-zinc-300"
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
            <option value="manha">Manhã</option>
            <option value="tarde">Tarde</option>
            <option value="noite">Noite</option>
            <option value="integral">Integral</option>
          </select>
        </Campo>
      </div>

      {erro && <div className="mt-3"><Mensagem tipo="erro">{erro}</Mensagem></div>}
      <div className="mt-5 flex items-center justify-end gap-2">
        <span className="mr-auto text-sm text-zinc-500 dark:text-zinc-400">
          {marcadas.size} turma{marcadas.size === 1 ? "" : "s"} selecionada{marcadas.size === 1 ? "" : "s"}
        </span>
        <Botao variante="neutro" onClick={aoFechar} disabled={criando}>Cancelar</Botao>
        <Botao onClick={criar} disabled={criando || marcadas.size === 0}>
          {criando ? "Criando..." : `Criar ${marcadas.size} turma${marcadas.size === 1 ? "" : "s"}`}
        </Botao>
      </div>
    </Modal>
  );
}

export default function Turmas() {
  const { escolaId, escolaAtual } = useApp();
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

  const estiloAcao =
    "rounded-md p-1.5 text-zinc-500 transition-colors hover:bg-zinc-100 hover:text-zinc-800 dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-zinc-100";

  return (
    <div>
      <PageHeader
        titulo="Turmas"
        descricao="Cadastre, edite e organize as turmas da escola."
        acoes={
          <div className="flex flex-wrap gap-2">
            <Botao variante="neutro" onClick={() => setVariasAberto(true)}>
              <LayoutGrid size={16} /> Criar várias
            </Botao>
            <Botao onClick={abrirNova}>
              <Plus size={16} /> Adicionar Turma
            </Botao>
          </div>
        }
      />

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

      {mensagem && (
        <div className="mb-4">
          <Mensagem tipo={mensagem.tipo}>{mensagem.texto}</Mensagem>
        </div>
      )}

      <label className="mb-3 flex w-fit cursor-pointer items-center gap-2 text-sm text-zinc-600 dark:text-zinc-300">
        <input
          type="checkbox"
          className="h-4 w-4 rounded border-zinc-300 accent-indigo-600"
          checked={mostrarTodas}
          onChange={(e) => setMostrarTodas(e.target.checked)}
        />
        Mostrar turmas arquivadas e de outros anos letivos
      </label>

      {selecionadas.size > 0 && (
        <div className="mb-3 flex flex-wrap items-center gap-3 rounded-lg border border-indigo-200 bg-indigo-50 px-4 py-2.5 dark:border-indigo-900/60 dark:bg-indigo-950/40">
          <span className="text-sm font-medium text-indigo-800 dark:text-indigo-200">
            {selecionadas.size} turma{selecionadas.size === 1 ? "" : "s"} selecionada
            {selecionadas.size === 1 ? "" : "s"}
          </span>
          <div className="ml-auto flex items-center gap-2">
            <Botao variante="neutro" onClick={() => setSelecionadas(new Set())}>
              Limpar seleção
            </Botao>
            <Botao
              className="!bg-red-600 hover:!bg-red-500"
              onClick={() => {
                setErroMassa(null);
                setConfirmaApagarDados(false);
                setExclusaoMassaAberta(true);
              }}
            >
              <Trash2 size={16} /> Excluir selecionadas
            </Botao>
          </div>
        </div>
      )}

      <Card>
        {carregandoTurmas ? (
          <Carregando />
        ) : erroTurmas ? (
          <Vazio titulo="Não foi possível carregar" descricao={erroTurmas.message} />
        ) : visiveis.length === 0 ? (
          <Vazio
            titulo="Nenhuma turma cadastrada"
            descricao="Use o botão “+ Adicionar Turma” para criar a primeira."
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-zinc-200 text-left text-xs uppercase tracking-wide text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
                  <th className="w-10 px-4 py-2 font-medium">
                    <input
                      ref={selectAllRef}
                      type="checkbox"
                      className="h-4 w-4 rounded border-zinc-300 accent-indigo-600"
                      checked={todasSelecionadas}
                      onChange={alternarTodas}
                      aria-label="Selecionar todas as turmas visíveis"
                      title="Selecionar todas"
                    />
                  </th>
                  <th className="px-4 py-2 font-medium">Turma</th>
                  <th className="px-4 py-2 font-medium">Série</th>
                  <th className="hidden px-4 py-2 font-medium sm:table-cell">Turno</th>
                  <th className="hidden px-4 py-2 font-medium md:table-cell">Professor</th>
                  <th className="px-4 py-2 font-medium">Alunos</th>
                  <th className="hidden px-4 py-2 font-medium sm:table-cell">Ano letivo</th>
                  <th className="px-4 py-2 font-medium">Situação</th>
                  <th className="px-4 py-2 text-right font-medium">Ações</th>
                </tr>
              </thead>
              <tbody>
                {visiveis.map((turma) => (
                  <tr
                    key={turma.id}
                    className={`border-b border-zinc-100 last:border-0 dark:border-zinc-800/60 ${
                      selecionadas.has(turma.id) ? "bg-indigo-50/60 dark:bg-indigo-950/30" : ""
                    }`}
                  >
                    <td className="px-4 py-2.5">
                      <input
                        type="checkbox"
                        className="h-4 w-4 rounded border-zinc-300 accent-indigo-600"
                        checked={selecionadas.has(turma.id)}
                        onChange={() => alternarSelecao(turma.id)}
                        aria-label={`Selecionar turma ${turma.nome}`}
                      />
                    </td>
                    <td className="px-4 py-2.5">
                      <Link
                        to={`/turmas/${turma.id}`}
                        className="font-medium hover:text-indigo-600 dark:hover:text-indigo-400"
                      >
                        {turma.nome}
                      </Link>
                    </td>
                    <td className="px-4 py-2.5 text-zinc-500 dark:text-zinc-400">
                      {turma.ano_escolar}
                    </td>
                    <td className="hidden px-4 py-2.5 text-zinc-500 dark:text-zinc-400 sm:table-cell">
                      {rotuloTurno(turma.turno)}
                    </td>
                    <td className="hidden px-4 py-2.5 text-zinc-500 dark:text-zinc-400 md:table-cell">
                      {turma.professor_nome ?? "—"}
                    </td>
                    <td className="px-4 py-2.5 tabular-nums text-zinc-600 dark:text-zinc-300">
                      {turma.total_alunos}
                      {turma.capacidade_maxima ? ` / ${turma.capacidade_maxima}` : ""}
                    </td>
                    <td className="hidden px-4 py-2.5 tabular-nums text-zinc-500 dark:text-zinc-400 sm:table-cell">
                      {turma.ano_letivo}
                    </td>
                    <td className="px-4 py-2.5">
                      {turma.status === "ativa" ? (
                        <Badge tom="ok">Ativa</Badge>
                      ) : (
                        <Badge>Arquivada</Badge>
                      )}
                    </td>
                    <td className="px-4 py-2.5">
                      <div className="flex justify-end gap-1">
                        <button
                          title="Editar"
                          aria-label={`Editar turma ${turma.nome}`}
                          className={estiloAcao}
                          onClick={() => abrirEdicao(turma)}
                        >
                          <Pencil size={15} />
                        </button>
                        <button
                          title={turma.status === "ativa" ? "Arquivar" : "Reativar"}
                          aria-label={`${turma.status === "ativa" ? "Arquivar" : "Reativar"} turma ${turma.nome}`}
                          className={estiloAcao}
                          onClick={() => alternarArquivo(turma)}
                        >
                          {turma.status === "ativa" ? (
                            <Archive size={15} />
                          ) : (
                            <ArchiveRestore size={15} />
                          )}
                        </button>
                        <button
                          title="Excluir"
                          aria-label={`Excluir turma ${turma.nome}`}
                          className={`${estiloAcao} hover:text-red-600 dark:hover:text-red-400`}
                          onClick={() => {
                            setErroExclusao(null);
                            setConfirmaApagarDados(false);
                            setParaExcluir(turma);
                          }}
                        >
                          <Trash2 size={15} />
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
          return (
            <>
              <p className="text-sm text-zinc-600 dark:text-zinc-300">
                Excluir a turma <strong>{paraExcluir?.nome}</strong> ({paraExcluir?.ano_letivo})?
                Esta ação é definitiva e não pode ser desfeita.
              </p>

              {temAlunos ? (
                <>
                  <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800 dark:border-amber-900/60 dark:bg-amber-950/30 dark:text-amber-200">
                    Esta turma tem <strong>{matriculas} aluno(s)</strong> matriculado(s). Escolha o
                    que fazer:
                    <ul className="mt-1.5 list-disc space-y-0.5 pl-5">
                      <li>
                        <strong>Excluir só a turma</strong> — indisponível enquanto houver alunos.
                        Mova/remova os alunos antes, ou use “Arquivar” para preservar o histórico.
                      </li>
                      <li>
                        <strong>Excluir turma + alunos e dados</strong> — apaga a turma e também os
                        alunos com todos os seus dados (leituras, notas, conquistas, snapshots). Um
                        aluno que também esteja em outra turma é apenas desvinculado desta.
                      </li>
                    </ul>
                  </div>
                  <label className="mt-3 flex cursor-pointer items-start gap-2 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800 dark:border-red-900/60 dark:bg-red-950/30 dark:text-red-200">
                    <input
                      type="checkbox"
                      className="mt-0.5 h-4 w-4 rounded border-red-300 accent-red-600"
                      checked={confirmaApagarDados}
                      onChange={(e) => setConfirmaApagarDados(e.target.checked)}
                    />
                    <span>
                      Entendo que os alunos desta turma e <strong>todos os seus dados</strong> serão
                      apagados permanentemente. Sem volta.
                    </span>
                  </label>
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

              <div className="mt-4 flex flex-wrap justify-end gap-2">
                <Botao variante="neutro" onClick={() => setParaExcluir(null)} disabled={excluindo}>
                  Cancelar
                </Botao>
                {temAlunos ? (
                  <>
                    <Botao
                      variante="neutro"
                      disabled
                      title="A turma tem alunos — mova/remova os alunos ou use “turma + alunos e dados”."
                    >
                      Excluir só a turma
                    </Botao>
                    <Botao
                      className="!bg-red-600 hover:!bg-red-500"
                      onClick={() => excluir(true)}
                      disabled={excluindo || !confirmaApagarDados}
                    >
                      {excluindo ? "Excluindo..." : "Excluir turma + alunos e dados"}
                    </Botao>
                  </>
                ) : (
                  <Botao
                    className="!bg-red-600 hover:!bg-red-500"
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

        <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800 dark:border-amber-900/60 dark:bg-amber-950/30 dark:text-amber-200">
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
            </li>
          </ul>
        </div>

        {matriculasNasSelecionadas > 0 && (
          <label className="mt-3 flex cursor-pointer items-start gap-2 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800 dark:border-red-900/60 dark:bg-red-950/30 dark:text-red-200">
            <input
              type="checkbox"
              className="mt-0.5 h-4 w-4 rounded border-red-300 accent-red-600"
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

        <div className="mt-4 flex flex-wrap justify-end gap-2">
          <Botao
            variante="neutro"
            onClick={() => setExclusaoMassaAberta(false)}
            disabled={excluindo}
          >
            Cancelar
          </Botao>
          <Botao variante="neutro" onClick={() => excluirMassa(false)} disabled={excluindo}>
            {excluindo ? "Excluindo..." : "Excluir só as turmas"}
          </Botao>
          {/* O caminho destrutivo só aparece quando há alunos a apagar (conta
              crua). Assim um número desatualizado/zero nunca dispara com_alunos
              sem a confirmação — se surgirem alunos depois, o backend mantém as
              turmas (bloqueadas) via "Excluir só as turmas". */}
          {matriculasNasSelecionadas > 0 && (
            <Botao
              className="!bg-red-600 hover:!bg-red-500"
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
