/**
 * Revisões de identidade (rota /revisoes-identidade).
 *
 * Quando uma importação ou sincronização (Matific / Elefante Letrado) NÃO
 * consegue decidir com segurança de quem são os dados de uma linha, o backend
 * não associa nem cria nada: guarda a linha inteira na fila de revisão
 * (`RevisaoIdentidade`). Esta tela é onde o gestor vê essas pendências e decide.
 *
 * A tela NÃO decide identidade. Ela só mostra o que o backend guardou (nome
 * recebido, conta da plataforma, turma, motivo, candidatos e dados) e envia a
 * escolha EXPLÍCITA do gestor aos endpoints já existentes:
 *   GET  /escolas/{id}/importacoes/revisoes[?situacao=]
 *   POST /escolas/{id}/importacoes/revisoes/{rev}/resolver  {aluno_id} | {criar_em_turma_id}
 *   POST /escolas/{id}/importacoes/revisoes/{rev}/descartar {motivo}
 * Vincular, transferir a conta da plataforma, aplicar os dados e auditar é
 * tudo feito pelo backend; depois de cada ação a fila é relida dele.
 */
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  RefreshCw,
  Search,
  Trash2,
  UserCheck,
  UserPlus,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import { Link } from "react-router-dom";

import {
  Badge,
  Botao,
  Campo,
  Card,
  Carregando,
  Drawer,
  Mensagem,
  Modal,
  PageHeader,
  Vazio,
  estiloInput,
} from "../components/ui";
import { useApp } from "../context/AppContext";
import { useApi } from "../hooks/useApi";
import { useMutation } from "../hooks/useMutation";
import { ApiError, api } from "../lib/api";
import { dataHora, numero } from "../lib/formato";
import type { PaginaAlunos, Turma } from "../lib/types";

// ── Contrato do backend (schemas/importacao.py) ───────────────────────────

/** Candidato como o backend o descreveu NO MOMENTO da decisão. */
export interface CandidatoRevisao {
  aluno_id: number;
  nome: string;
  status: string;
  turma: string | null;
}

export interface RevisaoIdentidade {
  id: number;
  plataforma: string;
  formato: string;
  id_externo: string | null;
  nome_recebido: string;
  turma_informada: string | null;
  turma_id: number | null;
  motivo: string;
  motivo_texto: string;
  candidatos: CandidatoRevisao[];
  linhas: Record<string, unknown>[];
  contexto: Record<string, unknown>;
  origem: string;
  importacao_id: number | null;
  ocorrencias: number;
  status: string;
  aluno_escolhido_id: number | null;
  resolvida_por_id: number | null;
  resolvida_em: string | null;
  resolucao: Record<string, unknown> | null;
  created_at: string;
  atualizada_em: string;
}

export interface ResolucaoRevisao {
  revisao: RevisaoIdentidade;
  aluno_id: number;
  revisoes_resolvidas: number[];
  importacoes: number[];
  avisos: string[];
}

type Situacao = "pendente" | "resolvida" | "descartada" | "todas";
type FiltroPlataforma = "todas" | "matific" | "elefante";

/** Para onde vão os dados: um aluno existente, ou uma ficha nova numa turma. */
type Destino =
  | { tipo: "aluno"; alunoId: number; nome: string; turma: string | null; status: string | null }
  | { tipo: "novo"; turmaId: number; turmaNome: string };

type Feedback = { tipo: "ok" | "erro"; texto: string; detalhes?: string[] };

// ── Rótulos ─────────────────────────────────────────────────────────────

/** O backend devolve no máximo este número de revisões por consulta. */
const LIMITE_LISTA = 500;

const NOME_PLATAFORMA: Record<string, string> = {
  matific: "Matific",
  elefante: "Elefante Letrado",
};

const ROTULO_IDENTIDADE: Record<string, string> = {
  matific: "UUID do Matific",
  elefante: "studentId do Elefante",
};

const ROTULO_SITUACAO: Record<string, string> = {
  pendente: "Pendente",
  resolvida: "Resolvida",
  descartada: "Descartada",
};

const ROTULO_FORMATO: Record<string, string> = {
  resumo: "Resumo do aluno",
  leituras: "Leituras (livro a livro)",
};

const ROTULO_ORIGEM: Record<string, string> = {
  sincronizacao: "Sincronização automática",
  importacao: "Importação manual",
};

/** Situação da ficha do candidato (o `status` do aluno no backend). */
const STATUS_FICHA: Record<string, { texto: string; tom: "ok" | "alerta" | "neutro" }> = {
  ativo: { texto: "Ficha ativa", tom: "ok" },
  arquivado: { texto: "Ficha arquivada", tom: "alerta" },
  fora_lista_piloto: { texto: "Fora da Lista Piloto", tom: "alerta" },
  excluido: { texto: "Ficha excluída", tom: "neutro" },
};

/** O que o gestor precisa decidir em cada motivo (o motivo em si vem do backend). */
const ORIENTACAO: Record<string, string> = {
  candidatos_multiplos: "Mais de um aluno pode ser o dono destes dados. Escolha qual é.",
  correspondencia_insegura:
    "O nome parece com o de um aluno, mas não o bastante para vincular sozinho. Confirme se é a mesma criança.",
  homonimo_em_outra_sala:
    "Há aluno com este nome em outra turma. Se a criança mudou de sala, vincule; se é outra criança, crie uma ficha nova.",
  nome_casa_em_outra_sala:
    "O nome corresponde a um aluno de outra turma. Se é a mesma criança, vincule; se não, crie uma ficha nova.",
  identidade_de_ficha_inativa:
    "A conta da plataforma já é de uma ficha inativa. Vincular aplica os dados, mas o aluno só volta ao ranking quando for reativado.",
  ficha_inativa:
    "O único candidato está com a ficha inativa. Vincular aplica os dados, mas o aluno só volta ao ranking quando for reativado.",
  identidade_de_outro_aluno:
    "A conta da plataforma já está ligada a outro aluno. Vincular a outra ficha transfere a conta.",
  outra_identidade_na_plataforma:
    "O aluno encontrado já tem outra conta nesta plataforma. Confirme se é a mesma criança antes de vincular.",
  ra_repetido: "O RA recebido aponta para mais de um aluno. Escolha qual é o dono destes dados.",
  turma_ambigua:
    "Mais de uma turma cadastrada corresponde à sala do relatório. Se a criança não tem ficha, crie-a na turma certa.",
  turma_nao_cadastrada:
    "A turma do relatório não existe no cadastro. Se a criança já tem ficha, busque-a; se não, crie-a numa turma existente.",
  sem_turma:
    "O relatório não informa a turma. Se a criança já tem ficha, busque-a; se não, crie-a na turma certa.",
};

/** Rótulos dos dados que ficaram aguardando (chaves de `linhas`). */
const ROTULOS_DADOS: Record<string, string> = {
  estrelas: "Estrelas",
  atividades: "Atividades",
  pontuacao_media: "Pontuação média",
  livros_unicos: "Livros lidos",
  tempo_leitura_min: "Tempo de leitura (min)",
  questoes_tentativas: "Questões respondidas",
  questoes_acertos: "Questões certas",
  livros_por_nivel: "Livros por nível",
  livro: "Livro",
  nivel: "Nível",
  genero: "Gênero",
  data: "Data",
  tempo_livro_min: "Tempo no livro (min)",
};

/** Chaves de CONTEXTO/identidade da linha (turma, série, nome, contas da plataforma):
 *  já aparecem em "Identidade recebida" — não são dado de desempenho a aplicar. */
const CAMPOS_OCULTOS = new Set([
  "turma_relatorio", "turma", "serie", "nome", "nome_abrev",
  "matific_uuid", "elefante_student_id", "elefante_id",
]);

// ── Utilitários de exibição (nada aqui decide identidade) ───────────────

/** "2026-08-01T00:00:00" → "01/08/2026" sem converter fuso (é a data do relatório). */
function dataDoIso(valor: unknown): string | null {
  const texto = typeof valor === "string" ? valor : "";
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(texto);
  return m ? `${m[3]}/${m[2]}/${m[1]}` : null;
}

function periodoDa(rev: RevisaoIdentidade): string | null {
  const inicio = dataDoIso(rev.contexto?.periodo_inicio);
  const fim = dataDoIso(rev.contexto?.periodo_fim);
  if (inicio && fim) return `${inicio} a ${fim}`;
  return inicio ?? fim ?? null;
}

function textoDoValor(chave: string, valor: unknown): string {
  if (valor === null || valor === undefined || valor === "") return "—";
  if (typeof valor === "number") return numero(valor);
  if (chave === "data") return dataDoIso(valor) ?? String(valor);
  if (typeof valor === "object") {
    return Object.entries(valor as Record<string, unknown>)
      .map(([k, v]) => `${k.replace(/^faixa:/, "")}: ${String(v)}`)
      .join(" · ");
  }
  return String(valor);
}

/** Série (ano escolar) de uma turma cadastrada — só quando o backend a informa. */
function serieDa(turmas: Turma[], turmaId: number | null, turmaNome: string | null): string | null {
  const turma = turmas.find((t) => (turmaId != null ? t.id === turmaId : t.nome === turmaNome));
  return turma?.ano_escolar ?? null;
}

function plural(n: number, um: string, varios: string): string {
  return `${numero(n)} ${n === 1 ? um : varios}`;
}

/** Mensagem de erro, com o que fazer em seguida (401/403 ganham orientação). */
function mensagemDeErro(erro: ApiError): string {
  if (erro.status === 401) return "Sua sessão expirou. Entre novamente para continuar.";
  if (erro.status === 403) return `Você não tem permissão para esta ação. ${erro.message}`.trim();
  return erro.message;
}

// ── Página ──────────────────────────────────────────────────────────────

export default function RevisoesIdentidade() {
  const { escolaId } = useApp();
  const [situacao, setSituacao] = useState<Situacao>("pendente");
  const [plataforma, setPlataforma] = useState<FiltroPlataforma>("todas");
  const [abertaId, setAbertaId] = useState<number | null>(null);
  const [feedback, setFeedback] = useState<Feedback | null>(null);
  // O painel não pode fechar (Esc/fundo) com uma ação em voo — o resultado do
  // backend chegaria a um painel desmontado e a fila não seria relida — nem com
  // uma confirmação aberta (Esc fecha a confirmação, não a revisão inteira).
  const [fechamentoBloqueado, setFechamentoBloqueado] = useState(false);

  const base = escolaId ? `/escolas/${escolaId}/importacoes/revisoes` : null;
  // Pendentes: sempre (dão o contador). As demais situações só quando filtradas.
  const pendentes = useApi<RevisaoIdentidade[]>(base);
  const outras = useApi<RevisaoIdentidade[]>(
    base && situacao !== "pendente" ? `${base}?situacao=${situacao}` : null);
  const turmasApi = useApi<Turma[]>(escolaId ? `/escolas/${escolaId}/turmas` : null);
  const turmas = turmasApi.dados ?? [];

  const lista = situacao === "pendente" ? pendentes : outras;
  const itens = (lista.dados ?? []).filter(
    (r) => plataforma === "todas" || r.plataforma === plataforma);
  const nPendentes = pendentes.dados?.length ?? null;
  const aberta = abertaId == null
    ? null
    : [...(pendentes.dados ?? []), ...(outras.dados ?? [])].find((r) => r.id === abertaId) ?? null;

  function recarregarFila() {
    pendentes.recarregar();
    if (situacao !== "pendente") outras.recarregar();
  }

  function aoResolver(res: ResolucaoRevisao, destino: Destino, rev: RevisaoIdentidade) {
    const quem = destino.tipo === "aluno" ? destino.nome : `uma ficha nova (${destino.turmaNome})`;
    const juntas = res.revisoes_resolvidas.length > 1
      ? ` ${plural(res.revisoes_resolvidas.length - 1, "outra revisão", "outras revisões")} da mesma identidade foram resolvidas junto.`
      : "";
    setFeedback({
      tipo: "ok",
      texto: destino.tipo === "aluno"
        ? `Revisão resolvida: os dados de “${rev.nome_recebido}” foram vinculados a ${quem}.${juntas}`
        : `Revisão resolvida: ${quem} foi criada para “${rev.nome_recebido}” e recebeu os dados.${juntas}`,
      detalhes: res.avisos,
    });
    setAbertaId(null);
    recarregarFila();
  }

  function aoDescartar(rev: RevisaoIdentidade) {
    setFeedback({
      tipo: "ok",
      texto: `Revisão descartada: os dados de “${rev.nome_recebido}” não foram associados a nenhum aluno.`,
    });
    setAbertaId(null);
    recarregarFila();
  }

  /** A revisão mudou de situação no servidor (resolvida/descartada por outra pessoa). */
  function aoDesatualizar(mensagem: string) {
    setFeedback({ tipo: "erro", texto: mensagem });
    setAbertaId(null);
    recarregarFila();
  }

  if (!escolaId) {
    return (
      <Vazio titulo="Selecione uma escola"
        descricao="Escolha uma escola para ver as revisões de identidade dela." />
    );
  }

  const contador = nPendentes === null
    ? null
    : nPendentes >= LIMITE_LISTA
      ? `${numero(LIMITE_LISTA)}+ pendências`
      : nPendentes === 0 ? "Nenhuma pendência" : plural(nPendentes, "pendência", "pendências");

  return (
    <div className="space-y-5">
      <PageHeader
        titulo="Revisões de identidade"
        descricao="Linhas de importação que não foram associadas a nenhum aluno porque a correspondência não era segura. Nada foi criado nem vinculado até você decidir."
        acoes={
          <div className="flex flex-wrap items-center gap-2">
            {contador && (
              <Badge tom={nPendentes ? "alerta" : "ok"}>{contador}</Badge>
            )}
            <Botao variante="neutro" onClick={recarregarFila} disabled={lista.carregando}>
              <RefreshCw size={15} /> Atualizar
            </Botao>
          </div>
        }
      />

      {feedback && (
        <Mensagem tipo={feedback.tipo}>
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <p>{feedback.texto}</p>
              {feedback.detalhes && feedback.detalhes.length > 0 && (
                <ul className="mt-1 list-inside list-disc text-xs">
                  {feedback.detalhes.map((d, i) => <li key={`${i}-${d}`}>{d}</li>)}
                </ul>
              )}
            </div>
            <button type="button" aria-label="Fechar aviso" className="shrink-0 text-xs underline"
              onClick={() => setFeedback(null)}>
              Fechar
            </button>
          </div>
        </Mensagem>
      )}

      <div className="flex flex-wrap items-end gap-3">
        <div className="w-full sm:w-48">
          <Campo rotulo="Situação">
            <select className={estiloInput} value={situacao}
              onChange={(e) => setSituacao(e.target.value as Situacao)}>
              <option value="pendente">Pendentes</option>
              <option value="resolvida">Resolvidas</option>
              <option value="descartada">Descartadas</option>
              <option value="todas">Todas</option>
            </select>
          </Campo>
        </div>
        <div className="w-full sm:w-48">
          <Campo rotulo="Plataforma">
            <select className={estiloInput} value={plataforma}
              onChange={(e) => setPlataforma(e.target.value as FiltroPlataforma)}>
              <option value="todas">Todas</option>
              <option value="matific">Matific</option>
              <option value="elefante">Elefante Letrado</option>
            </select>
          </Campo>
        </div>
      </div>

      {lista.erro && (
        lista.dados ? (
          <Mensagem tipo="erro">Não foi possível atualizar a lista: {mensagemDeErro(lista.erro)}</Mensagem>
        ) : (
          <Vazio
            titulo={lista.erro.status === 403
              ? "Sem permissão para ver as revisões de identidade"
              : "Não foi possível carregar as revisões de identidade"}
            descricao={mensagemDeErro(lista.erro)}
            acao={<Botao variante="neutro" onClick={recarregarFila}>Tentar de novo</Botao>}
          />
        )
      )}

      {situacao !== "pendente" && pendentes.erro && (
        <Mensagem tipo="erro">
          Não foi possível atualizar o contador de pendências: {mensagemDeErro(pendentes.erro)}
        </Mensagem>
      )}

      {lista.carregando && !lista.dados && !lista.erro && <Carregando texto="Carregando revisões…" />}
      {lista.carregando && lista.dados && (
        <p role="status" className="text-xs text-zinc-500 dark:text-zinc-400">Atualizando lista…</p>
      )}

      {lista.dados && !lista.carregando && itens.length === 0 && (
        <Card>
          <Vazio
            titulo={situacao === "pendente" && plataforma === "todas"
              ? "Nenhuma revisão pendente"
              : "Nenhuma revisão com estes filtros"}
            descricao={situacao === "pendente" && plataforma === "todas"
              ? "Quando uma importação ou sincronização não conseguir decidir com segurança de quem são os dados, a linha aparece aqui."
              : "Troque a situação ou a plataforma para ver outras revisões."}
          />
        </Card>
      )}

      {itens.length > 0 && (
        <ul className="space-y-3" aria-label="Revisões de identidade">
          {itens.map((rev) => (
            <ItemRevisao key={rev.id} rev={rev} turmas={turmas} aoAbrir={() => setAbertaId(rev.id)} />
          ))}
        </ul>
      )}

      <Drawer titulo="Revisão de identidade" aberto={aberta !== null}
        aoFechar={() => { if (!fechamentoBloqueado) setAbertaId(null); }}>
        {aberta && escolaId && (
          <DetalheRevisao
            key={aberta.id}
            escolaId={escolaId}
            rev={aberta}
            turmas={turmas}
            turmasCarregando={turmasApi.carregando}
            turmasErro={turmasApi.erro}
            aoResolver={aoResolver}
            aoDescartar={aoDescartar}
            aoDesatualizar={aoDesatualizar}
            aoBloquearFechamento={setFechamentoBloqueado}
          />
        )}
      </Drawer>
    </div>
  );
}

// ── Item da lista ────────────────────────────────────────────────────────

function ItemRevisao({ rev, turmas, aoAbrir }: {
  rev: RevisaoIdentidade;
  turmas: Turma[];
  aoAbrir: () => void;
}) {
  const serie = serieDa(turmas, rev.turma_id, null);
  const periodo = periodoDa(rev);
  return (
    <li>
      <Card className="p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0 flex-1 space-y-1.5">
            <div className="flex flex-wrap items-center gap-2">
              <p className="truncate text-sm font-semibold">{rev.nome_recebido}</p>
              <Badge tom="destaque">{NOME_PLATAFORMA[rev.plataforma] ?? rev.plataforma}</Badge>
              {rev.status !== "pendente" && (
                <Badge tom={rev.status === "resolvida" ? "ok" : "neutro"}>
                  {ROTULO_SITUACAO[rev.status] ?? rev.status}
                </Badge>
              )}
            </div>
            <dl className="grid grid-cols-1 gap-x-6 gap-y-0.5 text-xs text-zinc-600 dark:text-zinc-300 sm:grid-cols-2">
              {rev.id_externo && (
                <Linha rotulo="Identidade">
                  <span className="break-all font-mono">{rev.id_externo}</span>
                </Linha>
              )}
              <Linha rotulo="Turma informada">{rev.turma_informada || "não informada"}</Linha>
              {serie && <Linha rotulo="Série">{serie}</Linha>}
              {periodo && <Linha rotulo="Período">{periodo}</Linha>}
              <Linha rotulo="Última ocorrência">{dataHora(rev.atualizada_em)}</Linha>
              {rev.ocorrencias > 1 && (
                <Linha rotulo="Ocorrências">{plural(rev.ocorrencias, "vez", "vezes")}</Linha>
              )}
            </dl>
            <p className="flex items-start gap-1.5 text-xs text-amber-700 dark:text-amber-300">
              <AlertTriangle size={13} className="mt-0.5 shrink-0" />
              <span>Motivo: {rev.motivo_texto || rev.motivo}</span>
            </p>
          </div>
          <Botao variante="neutro" onClick={aoAbrir} aria-label={`Ver revisão de ${rev.nome_recebido}`}>
            Ver revisão <ArrowRight size={15} />
          </Botao>
        </div>
      </Card>
    </li>
  );
}

function Linha({ rotulo, children }: { rotulo: string; children: ReactNode }) {
  return (
    <div className="flex min-w-0 gap-1.5">
      <dt className="shrink-0 text-zinc-500 dark:text-zinc-400">{rotulo}:</dt>
      <dd className="min-w-0">{children}</dd>
    </div>
  );
}

function Bloco({ titulo, children }: { titulo: string; children: ReactNode }) {
  return (
    <section aria-label={titulo} className="space-y-2">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
        {titulo}
      </h3>
      {children}
    </section>
  );
}

// ── Detalhe ─────────────────────────────────────────────────────────────

function DetalheRevisao({
  escolaId, rev, turmas, turmasCarregando, turmasErro,
  aoResolver, aoDescartar, aoDesatualizar, aoBloquearFechamento,
}: {
  escolaId: number;
  rev: RevisaoIdentidade;
  turmas: Turma[];
  turmasCarregando: boolean;
  turmasErro: ApiError | null;
  aoResolver: (res: ResolucaoRevisao, destino: Destino, rev: RevisaoIdentidade) => void;
  aoDescartar: (rev: RevisaoIdentidade) => void;
  aoDesatualizar: (mensagem: string) => void;
  aoBloquearFechamento: (bloqueado: boolean) => void;
}) {
  const [destino, setDestino] = useState<Destino | null>(null);
  const [descartando, setDescartando] = useState(false);
  const [justificativa, setJustificativa] = useState("");
  const [turmaNova, setTurmaNova] = useState("");
  const pendente = rev.status === "pendente";
  const base = `/escolas/${escolaId}/importacoes/revisoes/${rev.id}`;

  /** 409/404: a revisão já não está pendente no servidor — fecha e relê a fila. */
  function tratarDesatualizada(erro: ApiError) {
    if (erro.status === 409 || erro.status === 404) {
      aoDesatualizar(`${erro.message} A lista foi atualizada com a situação atual.`);
    }
  }

  const resolver = useMutation(
    (d: Destino) => api<ResolucaoRevisao>(`${base}/resolver`, {
      method: "POST",
      body: JSON.stringify(d.tipo === "aluno" ? { aluno_id: d.alunoId } : { criar_em_turma_id: d.turmaId }),
    }),
    {
      aoSucesso: (res, d) => aoResolver(res, d, rev),
      aoErro: tratarDesatualizada,
    },
  );
  const descartar = useMutation(
    (motivo: string) => api<RevisaoIdentidade>(`${base}/descartar`, {
      method: "POST",
      body: JSON.stringify({ motivo }),
    }),
    {
      aoSucesso: () => aoDescartar(rev),
      aoErro: tratarDesatualizada,
    },
  );

  const emVoo = resolver.enviando || descartar.enviando;
  const confirmacaoAberta = destino !== null || descartando;
  useEffect(() => {
    aoBloquearFechamento(emVoo || confirmacaoAberta);
    return () => aoBloquearFechamento(false);
  }, [emVoo, confirmacaoAberta, aoBloquearFechamento]);
  // Esc com uma confirmação aberta fecha SÓ a confirmação (nunca no meio de uma
  // ação em voo); sem confirmação, o Drawer trata o Esc e fecha o painel.
  useEffect(() => {
    if (!confirmacaoAberta) return;
    const aoTecla = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || emVoo) return;
      setDestino(null);
      setDescartando(false);
    };
    window.addEventListener("keydown", aoTecla);
    return () => window.removeEventListener("keydown", aoTecla);
  }, [confirmacaoAberta, emVoo]);
  // Foco: entra no painel ao abrir e na confirmação ao abri-la (o teclado não
  // fica navegando atrás do overlay).
  const refRaiz = useRef<HTMLDivElement>(null);
  const refVinculo = useRef<HTMLDivElement>(null);
  const refDescarte = useRef<HTMLDivElement>(null);
  useEffect(() => { refRaiz.current?.focus(); }, []);
  useEffect(() => { if (destino) refVinculo.current?.focus(); }, [destino]);
  useEffect(() => { if (descartando) refDescarte.current?.focus(); }, [descartando]);

  const rotuloId = ROTULO_IDENTIDADE[rev.plataforma] ?? "Identidade externa";
  const serie = serieDa(turmas, rev.turma_id, null);
  const periodo = periodoDa(rev);
  const dataRef = typeof rev.contexto?.data_referencia === "string" ? rev.contexto.data_referencia : null;
  const turmaEscolhida = turmas.find((t) => String(t.id) === turmaNova) ?? null;
  const orientacao = ORIENTACAO[rev.motivo];

  return (
    <div ref={refRaiz} tabIndex={-1} className="space-y-6 outline-none">
      {!pendente && <SituacaoFinal rev={rev} />}

      {/* A. IDENTIDADE RECEBIDA */}
      <Bloco titulo="Identidade recebida">
        <Card className="p-4">
          <p className="text-base font-semibold tracking-tight">{rev.nome_recebido}</p>
          <dl className="mt-2 space-y-1 text-sm">
            <Linha rotulo="Plataforma">{NOME_PLATAFORMA[rev.plataforma] ?? rev.plataforma}</Linha>
            <Linha rotulo={rotuloId}>
              {rev.id_externo
                ? <span className="break-all font-mono text-xs">{rev.id_externo}</span>
                : <span className="text-zinc-500">não informada no relatório</span>}
            </Linha>
            <Linha rotulo="Turma informada">{rev.turma_informada || "não informada"}</Linha>
            {serie && <Linha rotulo="Série">{serie}</Linha>}
            {periodo && <Linha rotulo="Período do relatório">{periodo}</Linha>}
            {dataRef && <Linha rotulo="Data de referência">{dataHora(dataRef)}</Linha>}
            <Linha rotulo="Tipo de dado">{ROTULO_FORMATO[rev.formato] ?? (rev.formato || "—")}</Linha>
            <Linha rotulo="Origem">{ROTULO_ORIGEM[rev.origem] ?? rev.origem}</Linha>
            <Linha rotulo="Recebida em">{dataHora(rev.created_at)}</Linha>
            {rev.ocorrencias > 1 && (
              <Linha rotulo="Ocorrências">
                {plural(rev.ocorrencias, "vez", "vezes")} (última em {dataHora(rev.atualizada_em)})
              </Linha>
            )}
          </dl>
          <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-100">
            <p className="font-medium">Motivo: {rev.motivo_texto || rev.motivo}</p>
            {orientacao && pendente && <p className="mt-1 text-xs">{orientacao}</p>}
          </div>
        </Card>
      </Bloco>

      {/* B. CANDIDATOS ENCONTRADOS */}
      <Bloco titulo="Candidatos encontrados">
        {rev.candidatos.length === 0 ? (
          <p className="text-sm text-zinc-500 dark:text-zinc-400">
            Nenhum aluno cadastrado corresponde a esta linha.
          </p>
        ) : (
          <>
            <ul className="space-y-2">
              {rev.candidatos.map((c) => {
                const ficha = STATUS_FICHA[c.status] ?? { texto: c.status, tom: "neutro" as const };
                const serieCand = serieDa(turmas, null, c.turma);
                return (
                  <li key={c.aluno_id}>
                    <Card className="flex flex-wrap items-center justify-between gap-3 p-3">
                      <div className="min-w-0">
                        <p className="text-sm font-medium">{c.nome}</p>
                        <p className="text-xs text-zinc-500 dark:text-zinc-400">
                          {c.turma ?? "sem turma no ano letivo"}
                          {serieCand ? ` · ${serieCand}` : ""}
                        </p>
                        <div className="mt-1"><Badge tom={ficha.tom}>{ficha.texto}</Badge></div>
                      </div>
                      {pendente && (
                        <Botao variante="neutro" disabled={resolver.enviando}
                          aria-label={`Vincular este aluno: ${c.nome}`}
                          onClick={() => {
                            resolver.limparErro();
                            setDestino({ tipo: "aluno", alunoId: c.aluno_id, nome: c.nome, turma: c.turma, status: c.status });
                          }}>
                          <UserCheck size={15} /> Vincular este aluno
                        </Botao>
                      )}
                    </Card>
                  </li>
                );
              })}
            </ul>
            <p className="text-xs text-zinc-500 dark:text-zinc-400">
              Turma e situação da ficha no momento em que a revisão foi aberta.
            </p>
          </>
        )}
        {pendente && (
          <BuscarOutroAluno
            escolaId={escolaId}
            desabilitado={resolver.enviando}
            aoEscolher={(d) => { resolver.limparErro(); setDestino(d); }}
          />
        )}
      </Bloco>

      {/* C. DADOS DA IMPORTAÇÃO */}
      <Bloco titulo="Dados que aguardam associação">
        <p className="text-xs text-zinc-500 dark:text-zinc-400">
          Se você vincular esta linha a um aluno, estes são os dados que serão aplicados a ele.
        </p>
        <DadosPendentes rev={rev} />
      </Bloco>

      {pendente && (
        <>
          {/* CRIAR NOVO ALUNO — só por escolha explícita, com turma escolhida */}
          <Bloco titulo="Criar novo aluno">
            <Card className="space-y-3 p-4">
              <p className="text-xs text-zinc-500 dark:text-zinc-400">
                Use apenas se esta criança ainda não tem ficha na escola. Uma ficha nova é criada com o
                nome recebido e passa a receber estes dados.
              </p>
              {turmasErro && turmas.length === 0 ? (
                <Mensagem tipo="erro">Não foi possível carregar as turmas: {turmasErro.message}</Mensagem>
              ) : turmasCarregando && turmas.length === 0 ? (
                <p className="text-xs text-zinc-500">Carregando turmas…</p>
              ) : turmas.length === 0 ? (
                <p className="text-sm text-amber-700 dark:text-amber-300">
                  Não há turma ativa cadastrada no ano letivo. Cadastre a turma (Lista Piloto ou Turmas)
                  antes de criar o aluno.
                </p>
              ) : (
                <Campo rotulo="Turma da ficha nova">
                  <select className={estiloInput} value={turmaNova}
                    onChange={(e) => setTurmaNova(e.target.value)}>
                    <option value="">Escolha a turma…</option>
                    {turmas.map((t) => (
                      <option key={t.id} value={String(t.id)}>{t.nome}</option>
                    ))}
                  </select>
                </Campo>
              )}
              {turmaEscolhida && (
                <dl className="space-y-0.5 text-xs">
                  <Linha rotulo="Nome">{rev.nome_recebido}</Linha>
                  <Linha rotulo="Turma">{turmaEscolhida.nome} · {turmaEscolhida.ano_escolar}</Linha>
                  {rev.id_externo && <Linha rotulo={rotuloId}>{rev.id_externo}</Linha>}
                </dl>
              )}
              <Botao variante="neutro" disabled={!turmaEscolhida || resolver.enviando}
                onClick={() => {
                  if (!turmaEscolhida) return;
                  resolver.limparErro();
                  setDestino({ tipo: "novo", turmaId: turmaEscolhida.id, turmaNome: turmaEscolhida.nome });
                }}>
                <UserPlus size={15} /> Criar novo aluno
              </Botao>
            </Card>
          </Bloco>

          {/* DESCARTAR */}
          <Bloco titulo="Descartar">
            <Card className="flex flex-wrap items-center justify-between gap-3 p-4">
              <p className="min-w-0 flex-1 text-xs text-zinc-500 dark:text-zinc-400">
                Os dados não vão para nenhum aluno. Use para linhas de teste ou de quem não é da escola.
              </p>
              <Botao variante="neutro" disabled={descartar.enviando}
                onClick={() => { descartar.limparErro(); setDescartando(true); }}>
                <Trash2 size={15} /> Descartar revisão
              </Botao>
            </Card>
          </Bloco>
        </>
      )}

      {/* Confirmação: vincular a aluno existente / criar ficha nova */}
      <Modal
        titulo={destino?.tipo === "novo" ? "Criar novo aluno?" : "Vincular a este aluno?"}
        aberto={destino !== null}
        aoFechar={() => { if (!resolver.enviando) setDestino(null); }}
      >
        {destino && (
          <div ref={refVinculo} tabIndex={-1} className="space-y-4 text-sm outline-none">
            {destino.tipo === "aluno" ? (
              <p>
                Você está vinculando esta identidade ao aluno <strong>{destino.nome}</strong>
                {destino.turma ? ` (${destino.turma})` : ""}.
              </p>
            ) : (
              <p>
                Uma ficha nova será criada para <strong>{rev.nome_recebido}</strong> na turma{" "}
                <strong>{destino.turmaNome}</strong>. Faça isso só se a criança ainda não tiver ficha na
                escola.
              </p>
            )}
            <ul className="list-inside list-disc space-y-1 text-zinc-600 dark:text-zinc-300">
              <li>
                Os dados pendentes ({ROTULO_FORMATO[rev.formato]?.toLowerCase() ?? "dados da importação"})
                serão aplicados a {destino.tipo === "aluno" ? "esta ficha" : "esta nova ficha"}.
              </li>
              {rev.id_externo && (
                <li>
                  A conta da plataforma ({rotuloId} <span className="break-all font-mono text-xs">{rev.id_externo}</span>)
                  passa a pertencer a {destino.tipo === "aluno" ? "este aluno" : "esta ficha"}; as próximas
                  sincronizações vão direto para ela.
                </li>
              )}
              {destino.tipo === "aluno" && destino.status && destino.status !== "ativo" && (
                <li>
                  A ficha está “{STATUS_FICHA[destino.status]?.texto ?? destino.status}”: o aluno só volta
                  ao ranking quando for reativado em Alunos.
                </li>
              )}
              <li>Esta ação ficará registrada na auditoria.</li>
            </ul>
            {resolver.erro && (
              <Mensagem tipo="erro">
                {resolver.erro.status === 400 && destino.tipo === "aluno"
                  ? `${resolver.erro.message} Esta ficha pode ter sido fundida, excluída ou movida: atualize a lista ou escolha outro aluno.`
                  : mensagemDeErro(resolver.erro)}
              </Mensagem>
            )}
            <div className="flex flex-wrap justify-end gap-2">
              <Botao variante="neutro" disabled={resolver.enviando} onClick={() => setDestino(null)}>
                Cancelar
              </Botao>
              <Botao disabled={resolver.enviando} onClick={() => resolver.executar(destino)}>
                {destino.tipo === "novo" ? <UserPlus size={15} /> : <CheckCircle2 size={15} />}
                {resolver.enviando
                  ? "Aplicando…"
                  : destino.tipo === "novo" ? "Confirmar criação" : "Confirmar vínculo"}
              </Botao>
            </div>
          </div>
        )}
      </Modal>

      {/* Confirmação: descartar */}
      <Modal titulo="Descartar esta revisão?" aberto={descartando}
        aoFechar={() => { if (!descartar.enviando) setDescartando(false); }}>
        <div ref={refDescarte} tabIndex={-1} className="space-y-4 text-sm outline-none">
          <p>
            Os dados desta revisão não serão associados a nenhum aluno. A decisão ficará registrada na
            auditoria.
          </p>
          <p className="text-xs text-zinc-500 dark:text-zinc-400">
            Se a mesma linha voltar numa importação futura, ela aparecerá aqui de novo.
          </p>
          <Campo rotulo="Justificativa (opcional)">
            <textarea className={estiloInput} rows={2} maxLength={300} value={justificativa}
              onChange={(e) => setJustificativa(e.target.value)} />
          </Campo>
          {descartar.erro && <Mensagem tipo="erro">{mensagemDeErro(descartar.erro)}</Mensagem>}
          <div className="flex flex-wrap justify-end gap-2">
            <Botao variante="neutro" disabled={descartar.enviando} onClick={() => setDescartando(false)}>
              Cancelar
            </Botao>
            <Botao disabled={descartar.enviando} onClick={() => descartar.executar(justificativa.trim())}>
              <Trash2 size={15} /> {descartar.enviando ? "Descartando…" : "Confirmar descarte"}
            </Botao>
          </div>
        </div>
      </Modal>
    </div>
  );
}

/** Resolvida/descartada: o que foi decidido (visto pelos filtros de situação). */
function SituacaoFinal({ rev }: { rev: RevisaoIdentidade }) {
  const escolhido = rev.candidatos.find((c) => c.aluno_id === rev.aluno_escolhido_id);
  const justificativa = typeof rev.resolucao?.motivo === "string" ? rev.resolucao.motivo : "";
  const criou = rev.resolucao?.acao === "criar";
  return (
    <div className="rounded-lg border border-zinc-200 bg-zinc-50 p-3 text-sm dark:border-zinc-700 dark:bg-zinc-800/50">
      <p className="font-medium">
        {rev.status === "resolvida" ? "Resolvida" : rev.status === "descartada" ? "Descartada" : rev.status}
        {rev.resolvida_em ? ` em ${dataHora(rev.resolvida_em)}` : ""}
      </p>
      {rev.status === "resolvida" && (
        <p className="mt-1 text-xs text-zinc-600 dark:text-zinc-300">
          {criou ? "Uma ficha nova foi criada" : "Vinculada"}
          {escolhido
            ? `: ${escolhido.nome}`
            : rev.aluno_escolhido_id != null ? ` (aluno nº ${rev.aluno_escolhido_id})` : ""}
          {rev.aluno_escolhido_id != null && (
            <> · <Link className="underline" to={`/alunos/${rev.aluno_escolhido_id}`}>abrir ficha</Link></>
          )}
        </p>
      )}
      {rev.status === "descartada" && justificativa && (
        <p className="mt-1 text-xs text-zinc-600 dark:text-zinc-300">Justificativa: {justificativa}</p>
      )}
    </div>
  );
}

/** Os dados guardados na revisão (`linhas`), como o gestor os entende. */
function DadosPendentes({ rev }: { rev: RevisaoIdentidade }) {
  const linhas = rev.linhas ?? [];
  if (linhas.length === 0) {
    return <p className="text-sm text-zinc-500 dark:text-zinc-400">Nenhum dado guardado nesta revisão.</p>;
  }
  if (rev.formato === "leituras") {
    return (
      <Card className="p-0">
        <p className="border-b border-zinc-200 px-3 py-2 text-xs font-medium dark:border-zinc-800">
          {plural(linhas.length, "leitura", "leituras")}
        </p>
        <div className="max-h-72 overflow-auto">
          <table className="w-full text-left text-xs">
            <thead className="sticky top-0 bg-white text-zinc-500 dark:bg-zinc-900 dark:text-zinc-400">
              <tr>
                <th className="px-3 py-1.5 font-medium">Livro</th>
                <th className="px-3 py-1.5 font-medium">Nível</th>
                <th className="px-3 py-1.5 font-medium">Data</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800">
              {linhas.map((l, i) => (
                <tr key={i}>
                  <td className="px-3 py-1.5">{textoDoValor("livro", l.livro)}</td>
                  <td className="px-3 py-1.5">{textoDoValor("nivel", l.nivel)}</td>
                  <td className="whitespace-nowrap px-3 py-1.5 tabular-nums">{textoDoValor("data", l.data)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    );
  }
  // Resumo/placar: é um retrato — vale a linha mais recente guardada.
  const ultima = linhas[linhas.length - 1] ?? {};
  const campos = Object.entries(ultima).filter(([k]) => !CAMPOS_OCULTOS.has(k) && !k.startsWith("_"));
  if (campos.length === 0) {
    return <p className="text-sm text-zinc-500 dark:text-zinc-400">Nenhum dado de desempenho nesta linha.</p>;
  }
  return (
    <Card className="p-4">
      <dl className="grid grid-cols-1 gap-x-6 gap-y-1 text-sm sm:grid-cols-2">
        {campos.map(([chave, valor]) => (
          <div key={chave} className="flex justify-between gap-3">
            <dt className="text-zinc-500 dark:text-zinc-400">{ROTULOS_DADOS[chave] ?? chave}</dt>
            <dd className="text-right font-medium tabular-nums">{textoDoValor(chave, valor)}</dd>
          </div>
        ))}
      </dl>
    </Card>
  );
}

/** Busca explícita de OUTRO aluno ativo da escola (quando o dono não está entre
 *  os candidatos). Só lista o que o gestor pesquisar — nada é sugerido. */
function BuscarOutroAluno({ escolaId, desabilitado, aoEscolher }: {
  escolaId: number;
  desabilitado: boolean;
  aoEscolher: (destino: Destino) => void;
}) {
  const [aberto, setAberto] = useState(false);
  const [texto, setTexto] = useState("");
  const [termo, setTermo] = useState("");
  const busca = useApi<PaginaAlunos>(
    aberto && termo.length >= 2
      ? `/escolas/${escolaId}/alunos?busca=${encodeURIComponent(termo)}&por_pagina=20`
      : null);

  function pesquisar(e: FormEvent) {
    e.preventDefault();
    setTermo(texto.trim());
  }

  if (!aberto) {
    return (
      <button type="button" className="text-xs font-medium text-indigo-600 underline dark:text-indigo-400"
        onClick={() => setAberto(true)}>
        O aluno certo não está na lista? Buscar outro aluno da escola
      </button>
    );
  }
  return (
    <Card className="space-y-3 p-3">
      <form className="flex flex-wrap items-end gap-2" onSubmit={pesquisar}>
        <div className="min-w-0 flex-1">
          <Campo rotulo="Buscar aluno pelo nome">
            <input className={estiloInput} value={texto} onChange={(e) => setTexto(e.target.value)}
              placeholder="Digite ao menos 2 letras" />
          </Campo>
        </div>
        <Botao type="submit" variante="neutro" disabled={texto.trim().length < 2}>
          <Search size={15} /> Buscar
        </Botao>
      </form>
      {busca.carregando && <p className="text-xs text-zinc-500">Buscando…</p>}
      {busca.erro && <Mensagem tipo="erro">{mensagemDeErro(busca.erro)}</Mensagem>}
      {busca.dados && busca.dados.itens.length === 0 && (
        <p className="text-xs text-zinc-500 dark:text-zinc-400">Nenhum aluno ativo encontrado com “{termo}”.</p>
      )}
      {busca.dados && busca.dados.itens.length > 0 && (
        <ul className="divide-y divide-zinc-100 dark:divide-zinc-800" aria-label="Resultado da busca">
          {busca.dados.itens.map((a) => (
            <li key={a.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
              <div className="min-w-0">
                <p className="text-sm">{a.nome}</p>
                <p className="text-xs text-zinc-500 dark:text-zinc-400">
                  {a.turma ?? "sem turma"}{a.ano_escolar ? ` · ${a.ano_escolar}` : ""}
                </p>
              </div>
              <Botao variante="neutro" disabled={desabilitado}
                aria-label={`Vincular este aluno: ${a.nome}`}
                onClick={() => aoEscolher({ tipo: "aluno", alunoId: a.id, nome: a.nome, turma: a.turma, status: a.status })}>
                <UserCheck size={15} /> Vincular este aluno
              </Botao>
            </li>
          ))}
        </ul>
      )}
      {busca.dados && busca.dados.total > busca.dados.itens.length && (
        <p className="text-xs text-zinc-500 dark:text-zinc-400">
          Mostrando {busca.dados.itens.length} de {busca.dados.total}. Refine a busca.
        </p>
      )}
    </Card>
  );
}
