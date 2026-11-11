/**
 * Painel administrativo da turma: gestão completa dos alunos.
 *
 * Lista os alunos da turma com busca, ordenação e seleção múltipla. Cada
 * aluno tem um menu de ações (Visualizar, Editar, Transferir, Novo cartão do
 * Quest, Arquivar, Excluir) e há uma barra de ações em massa. A exclusão comum
 * é lógica (reversível); a exclusão PERMANENTE apaga o aluno e todos os dados
 * vinculados e exige uma confirmação extra. Após cada ação, as contagens,
 * o ranking e as estatísticas se atualizam sozinhos (sem recarregar a página).
 *
 * “Transferir de turma” manda ``turma_origem_id`` (esta turma): a API move só a
 * matrícula do ano ativo que está nela. Em turma de OUTRO ano letivo a lista é
 * histórico (matrícula daquele ano) e transferir moveria a matrícula do ano
 * ativo, da turma atual da criança — a tela não oferece a ação e orienta
 * arquivar (a API recusa com 409).
 */
import {
  Archive,
  ArrowLeft,
  ArrowRightLeft,
  BookOpen,
  Calculator,
  Clock,
  Eye,
  Info,
  LogOut,
  Pencil,
  Rocket,
  RotateCcw,
  Trash2,
  TriangleAlert,
  Users,
  X,
} from "lucide-react";
import { baixarCartaoDoAluno, baixarCartoesDaTurma } from "@constela/quest-core";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import MenuSuspenso, { ItemMenu } from "../components/MenuSuspenso";
import { TabelaRolavel } from "../components/TabelaRolavel";
import {
  AvatarAluno,
  BotaoContornoPerigo,
  CabecalhoCartao,
  CampoBusca,
  EsqueletoLista,
  PilulaSituacao,
  SelectNativo,
  estiloCheckbox,
} from "../components/PessoasUi";
import {
  BarraProgresso,
  Botao,
  Campo,
  Card,
  Chip,
  Erro,
  IconePastel,
  Interruptor,
  Mensagem,
  Modal,
  Skeleton,
  StatCard,
  Vazio,
  classesTabela,
  estiloInput,
} from "../components/ui";
import { useApp } from "../context/AppContext";
import { useApi } from "../hooks/useApi";
import { api, ApiError } from "../lib/api";
import { dataDia, nota as fmtNota, numero, tempoLeitura } from "../lib/formato";
import type { AlunoGestao, Turma } from "../lib/types";

interface ResumoTurma {
  turma: { id: number; nome: string; ano_escolar: string };
  total_alunos: number;
  media_geral: number;
  media_matific: number;
  media_elefante: number;
  indicadores: Record<string, number>;
  // Campos da Arquitetura 2 (services/evolucao.py). Opcionais: um servidor antigo
  // não os manda e a tela volta ao formato de antes.
  contratadas?: string[];
  n_leitura?: number;
  n_matematica?: number;
  dimensoes_com_dados?: string[];
  adocao_leitura?: number;
  adocao_matematica?: number;
  nao_aferidos?: number;
}

const ORDENACOES = [
  { valor: "nome", rotulo: "Nome (A–Z)" },
  { valor: "data", rotulo: "Data de cadastro" },
  { valor: "desempenho", rotulo: "Desempenho" },
  { valor: "chamada", rotulo: "Nº de chamada" },
  { valor: "serie", rotulo: "Série" },
];

const STATUS_BADGE: Record<string, { tom: "neutro" | "alerta" | "erro"; texto: string }> = {
  arquivado: { tom: "neutro", texto: "Arquivado" },
  excluido: { tom: "erro", texto: "Na lixeira" },
  fora_lista_piloto: { tom: "alerta", texto: "Fora da lista piloto" },
  transferido: { tom: "neutro", texto: "Transferido" },
};

type Acao =
  | { tipo: "editar"; alvo: AlunoGestao }
  | { tipo: "transferir"; ids: number[]; rotulo: string }
  | { tipo: "excluir"; ids: number[]; rotulo: string }
  | { tipo: "permanente"; ids: number[]; rotulo: string }
  | { tipo: "cartao_quest"; alvo: AlunoGestao };

/** Entrega um PDF baixado ao navegador como download. */
function salvarArquivo(blob: Blob, nomeArquivo: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = nomeArquivo;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

/** Menu de ações (kebab ⋮) de um aluno. */
function MenuAcoes({ aluno, aoEscolher, podeApagarAlunos, podeTransferir }: {
  aluno: AlunoGestao;
  aoEscolher: (acao: string) => void;
  /** “Excluir permanentemente” só para o Admin Global (D19). */
  podeApagarAlunos: boolean;
  /** “Transferir de turma” some no painel de turma de OUTRO ano letivo: a lista
   * mostra a matrícula daquele ano (histórico) e transferir moveria a do ano
   * ativo, que está na turma atual da criança (a API também recusa, 409). */
  podeTransferir: boolean;
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
            {podeTransferir && (
              <ItemMenu icone={<ArrowRightLeft size={15} />} rotulo="Transferir de turma" onClick={escolher("transferir")} />
            )}
            {/* Cartão perdido ou em mãos erradas: código e QR novos, o antigo para de
                entrar (a folha "só do professor" manda aqui). Ficha inativa: só revoga. */}
            <ItemMenu icone={<Rocket size={15} />}
                      rotulo={inativo ? "Revogar cartão do Quest" : "Novo cartão do Quest"}
                      onClick={escolher("cartao_quest")} />
            {inativo ? (
              <ItemMenu icone={<RotateCcw size={15} />} rotulo="Reativar" onClick={escolher("reativar")} />
            ) : (
              <>
                <ItemMenu icone={<Archive size={15} />} rotulo="Arquivar" onClick={escolher("arquivar")} />
                <ItemMenu icone={<LogOut size={15} />} rotulo="Marcar como transferido"
                          onClick={escolher("marcar_transferido")} />
              </>
            )}
            <div className="my-1 border-t border-zinc-100 dark:border-zinc-800" />
            <ItemMenu icone={<Trash2 size={15} />} rotulo="Excluir" destrutiva onClick={escolher("excluir")} />
            {podeApagarAlunos && (
              <ItemMenu icone={<TriangleAlert size={15} />} rotulo="Excluir permanentemente" destrutiva onClick={escolher("permanente")} />
            )}
          </>
        );
      }}
    </MenuSuspenso>
  );
}

/**
 * Detalhe da "Média geral": só as dimensões CONTRATADAS e, entre elas, só as que
 * têm aluno aferido (n > 0) levam número — as outras dizem "—". O servidor
 * devolve 0.0 para dimensão sem contrato ou sem aferido; mostrar "Matific 0,0"
 * seria um zero falso. Sem os campos (servidor antigo), o formato de antes.
 */
function detalheMedia(resumo: ResumoTurma): string {
  if (!resumo.contratadas) {
    return `Matific ${fmtNota(resumo.media_matific)} · Leitura ${fmtNota(resumo.media_elefante)}`;
  }
  const partes: string[] = [];
  if (resumo.contratadas.includes("leitura")) {
    partes.push(`Leitura ${resumo.n_leitura ? fmtNota(resumo.media_elefante) : "—"}`);
  }
  if (resumo.contratadas.includes("matematica")) {
    partes.push(`Matific ${resumo.n_matematica ? fmtNota(resumo.media_matific) : "—"}`);
  }
  return partes.join(" · ");
}

export default function TurmaDetalhe() {
  const { id } = useParams();
  const { escolaId, escolaAtual, usuario } = useApp();
  const navegar = useNavigate();
  // Secretaria (rede vinculada, não-global): só visualiza — sem seleção em massa,
  // menu de ações, transferência nem geração de cartões (o backend também barra).
  const podeEditar = !(!usuario?.is_global && usuario?.rede_id != null);
  // Exclusão FÍSICA de aluno (apaga a ficha e todos os dados) é exclusiva do
  // Admin Global (D19 — a API responde 403 para os demais), como em Turmas.tsx:
  // para admin e coordenação da escola a tela não oferece “Excluir permanentemente”.
  const podeApagarAlunos = usuario?.is_global === true;

  const [busca, setBusca] = useState("");
  const [buscaAplicada, setBuscaAplicada] = useState("");
  const [ordenar, setOrdenar] = useState("nome");
  const [incluirInativos, setIncluirInativos] = useState(false);
  const [selecionados, setSelecionados] = useState<Set<number>>(new Set());

  const [acao, setAcao] = useState<Acao | null>(null);
  const [ocupado, setOcupado] = useState(false);
  const [aviso, setAviso] = useState<{ tipo: "ok" | "erro"; texto: string } | null>(null);

  const base = `/escolas/${escolaId}/turmas/${id}`;

  // Resumo da turma: contagens, médias e indicadores.
  const { dados: resumo, erro: erroTurma, recarregar: recarregarResumo } =
    useApi<ResumoTurma>(escolaId && id ? `${base}/resumo` : null);

  // Todas as turmas (inclusive arquivadas e de outros anos): dão o ano letivo
  // DESTA turma e, filtradas, os destinos do modal de transferência — só as
  // ativas do ano ativo, o mesmo recorte do GET /turmas padrão (array sempre
  // pronto para render).
  const { dados: turmasDados } = useApi<Turma[]>(
    escolaId ? `/escolas/${escolaId}/turmas?todas=true` : null,
  );
  const anoAtivo = escolaAtual?.ano_letivo_ativo ?? null;
  const turmas = (turmasDados ?? []).filter(
    (t) => t.status === "ativa" && (anoAtivo == null || t.ano_letivo === anoAtivo),
  );
  const estaTurma = (turmasDados ?? []).find((t) => String(t.id) === id);
  // Turma de OUTRO ano letivo: a lista mostra a matrícula daquele ano
  // (histórico), e “Transferir de turma” moveria a matrícula do ano ATIVO — a da
  // turma atual da criança, em outra sala. A tela não oferece; a API recusa (409).
  const deOutroAno = estaTurma != null && anoAtivo != null && estaTurma.ano_letivo !== anoAtivo;

  // Busca com debounce; ordenação/filtro entram na URL na hora.
  useEffect(() => {
    const t = window.setTimeout(() => setBuscaAplicada(busca), busca ? 300 : 0);
    return () => window.clearTimeout(t);
  }, [busca]);

  // Lista de alunos: a URL muda com busca/ordenação/filtro e o hook rebusca sozinho.
  const params = new URLSearchParams({ ordenar });
  if (buscaAplicada.trim()) params.set("busca", buscaAplicada.trim());
  if (incluirInativos) params.set("incluir_inativos", "true");
  const { dados: alunos, erro: erroAlunos, recarregar: recarregarAlunos } =
    useApi<AlunoGestao[]>(escolaId && id ? `${base}/alunos?${params}` : null);

  // Um temporizador de aviso por vez: o de uma ação anterior (6 s) não pode
  // apagar o aviso novo (30 s quando traz o aviso do D10), e nada dispara
  // depois que a tela sai.
  const temporizadorAviso = useRef<number | null>(null);
  useEffect(() => () => {
    if (temporizadorAviso.current != null) window.clearTimeout(temporizadorAviso.current);
  }, []);

  // Erro fica mais tempo: a recusa do D17 (reativar aluno cuja matrícula está em
  // turma arquivada, transferir para turma arquivada) explica o que fazer, e 6 s
  // não dão para ler.
  function avisar(tipo: "ok" | "erro", texto: string,
                  duracaoMs = tipo === "erro" ? 20000 : 6000) {
    if (temporizadorAviso.current != null) window.clearTimeout(temporizadorAviso.current);
    setAviso({ tipo, texto });
    temporizadorAviso.current = window.setTimeout(() => {
      temporizadorAviso.current = null;
      setAviso(null);
    }, duracaoMs);
  }

  /** Recarrega tudo (lista + contagens + ranking) sem recarregar a página. */
  function recarregar() {
    recarregarAlunos();
    recarregarResumo();
    setSelecionados(new Set());
  }

  async function executar(caminho: string, corpo: unknown, sucesso: string) {
    setOcupado(true);
    try {
      const r = await api<{ mensagem?: string; afetados?: number; avisos?: string[] }>(caminho, {
        method: "POST",
        body: JSON.stringify(corpo),
      });
      // Avisos da ação (D10: conta da plataforma que continua valendo em outra
      // escola) vão junto da mensagem e ficam mais tempo na tela.
      const avisos = r?.avisos ?? [];
      avisar("ok", [r?.mensagem ?? sucesso, ...avisos].join(" "),
             avisos.length ? 30000 : 6000);
      setAcao(null);
      recarregar();
    } catch (e) {
      avisar("erro", e instanceof ApiError ? e.message : "Não foi possível concluir a ação.");
    } finally {
      setOcupado(false);
    }
  }

  /** Ação de status/transferência (individual ou em massa). */
  function aplicarAcao(tipo: "arquivar" | "reativar" | "excluir" | "transferir" | "marcar_transferido",
                       ids: number[], turmaId?: number) {
    const rotulos = {
      arquivar: "Aluno(s) arquivado(s).",
      reativar: "Aluno(s) reativado(s).",
      excluir: "Aluno(s) excluído(s).",
      transferir: "Aluno(s) transferido(s) de turma.",
      marcar_transferido: "Aluno(s) marcado(s) como transferido(s). O histórico segue preservado.",
    };
    // Transferir A PARTIR desta turma: a API move só a matrícula do ano ativo
    // que está nela (sem criar matrícula nova) e recusa turma de outro ano letivo.
    const origem = tipo === "transferir" && id ? { turma_origem_id: Number(id) } : {};
    executar(`/escolas/${escolaId}/alunos/acoes`,
      { aluno_ids: ids, acao: tipo, turma_id: turmaId ?? null, ...origem }, rotulos[tipo]);
  }

  /** Constela Quest: gera as credenciais da turma e baixa o PDF dos cartões
   * de acesso (QR + código + PIN de figuras) para imprimir e recortar. */
  async function baixarCartoesQuest() {
    if (!escolaId || !id) return;
    setOcupado(true);
    try {
      const { blob, nomeArquivo } = await baixarCartoesDaTurma(escolaId, Number(id));
      salvarArquivo(blob, nomeArquivo);
      avisar("ok", "Cartões do Quest gerados! Imprima, recorte e entregue aos alunos.");
    } catch (e) {
      avisar("erro", e instanceof ApiError ? e.message : "Não foi possível gerar os cartões.");
    } finally {
      setOcupado(false);
    }
  }

  /** Cartão novo de UM aluno (`regenerar=true`): código e QR novos, o cartão
   * antigo e as sessões abertas com ele param de entrar; os colegas seguem com os
   * deles. Ficha inativa: a API só revoga, sem cartão novo (204, sem PDF), e
   * recusa (422) quando ela nunca teve cartão. */
  async function gerarCartaoNovoQuest(aluno: AlunoGestao) {
    if (!escolaId) return;
    setOcupado(true);
    try {
      const { blob, nomeArquivo } = await baixarCartaoDoAluno(escolaId, aluno.id, true);
      if (blob.size === 0) {
        avisar("ok", `Cartão do Quest de ${aluno.nome} revogado: o código e o QR antigos não ` +
          "entram mais. Aluno inativo não recebe cartão novo.");
      } else {
        salvarArquivo(blob, nomeArquivo);
        avisar("ok", `Cartão novo de ${aluno.nome} gerado: o antigo não entra mais. ` +
          "Imprima e entregue o novo.");
      }
      setAcao(null);
    } catch (e) {
      if (e instanceof ApiError && e.status === 422) {
        avisar("erro", `${aluno.nome} não tem cartão do Quest para revogar.`);
      } else {
        avisar("erro", e instanceof ApiError ? e.message : "Não foi possível gerar o cartão novo.");
      }
      setAcao(null);
    } finally {
      setOcupado(false);
    }
  }

  function aoEscolherNoMenu(aluno: AlunoGestao, escolha: string) {
    if (escolha === "visualizar") return navegar(`/alunos/${aluno.id}`);
    if (escolha === "editar") return setAcao({ tipo: "editar", alvo: aluno });
    if (escolha === "transferir") return setAcao({ tipo: "transferir", ids: [aluno.id], rotulo: aluno.nome });
    if (escolha === "excluir") return setAcao({ tipo: "excluir", ids: [aluno.id], rotulo: aluno.nome });
    if (escolha === "permanente" && podeApagarAlunos)
      return setAcao({ tipo: "permanente", ids: [aluno.id], rotulo: aluno.nome });
    if (escolha === "cartao_quest") return setAcao({ tipo: "cartao_quest", alvo: aluno });
    // arquivar / reativar são reversíveis → aplica direto
    if (escolha === "arquivar" || escolha === "reativar" || escolha === "marcar_transferido")
      aplicarAcao(escolha, [aluno.id]);
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

  if (!escolaId) {
    return (
      <Card>
        <Vazio icone={Users} titulo="Selecione uma escola"
               descricao="Escolha a escola no topo da tela para abrir o painel da turma." />
      </Card>
    );
  }
  if (erroTurma) {
    return (
      <Card>
        {erroTurma.status === 404 ? (
          <Vazio icone={Users} titulo="Turma não encontrada" descricao={erroTurma.message} />
        ) : (
          <Erro titulo="Não foi possível abrir a turma" descricao={erroTurma.message} aoTentar={recarregarResumo} />
        )}
      </Card>
    );
  }
  if (!resumo) {
    return (
      <div role="status" className="space-y-6">
        <span className="sr-only">Carregando...</span>
        <Skeleton className="h-4 w-20" />
        <Skeleton className="h-24 rounded-cartao" />
        <div className="grid grid-cols-2 gap-3 sm:gap-5 xl:grid-cols-4">
          {[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-32 rounded-cartao" />)}
        </div>
      </div>
    );
  }

  // Sem contrato de Leitura, livros e tempo de leitura não existem para esta rede:
  // "—" em vez de um zero. Sem o campo (servidor antigo), mostra o que veio.
  const temLeitura = !resumo.contratadas || resumo.contratadas.includes("leitura");
  const semDimensaoComDado = resumo.dimensoes_com_dados != null && resumo.dimensoes_com_dados.length === 0;
  const adocoes = (resumo.contratadas ?? []).flatMap((dimensao) => {
    const valor = dimensao === "leitura" ? resumo.adocao_leitura : dimensao === "matematica" ? resumo.adocao_matematica : undefined;
    if (valor == null) return [];
    return [{
      dimensao,
      rotulo: dimensao === "leitura" ? "Elefante Letrado" : "Matific",
      valor,
      tom: (dimensao === "leitura" ? "violeta" : "teal") as "violeta" | "teal",
    }];
  });

  // Tabela dos alunos no celular (< 640 px): células mais justas; o menu ⋮ preso à
  // direita numa coluna de 56 px e o Desempenho preso logo antes dele (right-14 = a
  // largura da coluna do menu; sem o menu, encosta na borda). A sombra fica só à
  // esquerda do Desempenho, que é a borda do bloco preso.
  const th = `${classesTabela.th} max-sm:px-3`;
  const td = `${classesTabela.td} max-sm:px-3`;
  const presaAcoes = "presa-celular max-sm:w-14 max-sm:px-2 max-sm:shadow-none dark:max-sm:shadow-none";
  const presaDesempenho = podeEditar ? "presa-celular max-sm:right-14" : "presa-celular";

  return (
    <div className="space-y-6">
      <Link
        to="/turmas"
        className="inline-flex items-center gap-1.5 text-sm font-medium text-zinc-500 transition-colors hover:text-indigo-600 dark:text-zinc-400 dark:hover:text-indigo-300"
      >
        <ArrowLeft size={15} aria-hidden /> Turmas
      </Link>

      <Card className="relative overflow-hidden p-6">
        <span
          aria-hidden
          className="pointer-events-none absolute -right-16 -top-20 h-56 w-56 rounded-full bg-teal-100/60 blur-2xl dark:bg-teal-500/10"
        />
        {/* Celular: a coluna do texto tem base de 12rem, então o botão desce para a
            linha de baixo (largura total) em vez de espremer o título palavra a palavra
            e ficar por cima do "Professor(a) …". Do sm em diante, uma linha só. */}
        <div className="relative flex flex-wrap items-center gap-4">
          <IconePastel icone={Users} tom="violeta" tamanho="lg" />
          <div className="min-w-0 flex-1 basis-[12rem]">
            <h1 className="text-2xl font-bold leading-tight tracking-tight text-zinc-900 dark:text-white sm:text-[28px]">
              {resumo.turma.nome}
            </h1>
            <div className="mt-2 flex flex-wrap items-center gap-2 text-sm text-zinc-500 dark:text-zinc-400">
              <Chip>{resumo.turma.ano_escolar}</Chip>
              {estaTurma?.professor_nome && <span>Professor(a) {estaTurma.professor_nome}</span>}
              {estaTurma && <span className="tabular-nums">· ano letivo {estaTurma.ano_letivo}</span>}
            </div>
          </div>
          {podeEditar && (
            <Botao
              variante="secundario"
              onClick={baixarCartoesQuest}
              disabled={ocupado}
              title="Gera o PDF com QR, código e senha de figuras de cada aluno"
              className="w-full sm:w-auto"
            >
              <Rocket size={16} aria-hidden /> Cartões do Quest
            </Botao>
          )}
        </div>
      </Card>

      <div className="grid grid-cols-2 gap-3 sm:gap-5 xl:grid-cols-4 max-sm:[&>*:last-child:nth-child(odd)]:col-span-2">
        <StatCard icone={<Users size={20} />} tom="violeta" rotulo="Alunos" valor={numero(resumo.total_alunos)} />
        <StatCard icone={<Calculator size={20} />} tom="ambar" rotulo="Média geral"
                  valor={semDimensaoComDado ? "—" : fmtNota(resumo.media_geral)}
                  detalhe={detalheMedia(resumo)} />
        <StatCard icone={<BookOpen size={20} />} tom="teal" rotulo="Livros lidos"
                  valor={temLeitura ? numero(resumo.indicadores.livros_unicos ?? 0) : "—"}
                  detalhe={temLeitura ? undefined : "Leitura fora do plano"} />
        <StatCard icone={<Clock size={20} />} tom="azul" rotulo="Tempo de leitura"
                  valor={temLeitura ? tempoLeitura(resumo.indicadores.tempo_leitura_min ?? 0) : "—"}
                  detalhe={temLeitura ? undefined : "Leitura fora do plano"} />
      </div>

      {/* Cobertura (adoção) por plataforma contratada — dado real do /resumo,
          ao lado do desempenho e nunca somado a ele. */}
      {adocoes.length > 0 && (
        <Card className="p-5">
          <div className="mb-4 flex flex-wrap items-baseline justify-between gap-2">
            <h2 className="text-base font-semibold tracking-tight">Uso das plataformas</h2>
            {resumo.nao_aferidos != null && resumo.nao_aferidos > 0 && (
              <p className="text-xs text-zinc-500 dark:text-zinc-400">
                {numero(resumo.nao_aferidos)} aluno{resumo.nao_aferidos === 1 ? "" : "s"} ainda sem dado em nenhuma plataforma contratada
              </p>
            )}
          </div>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            {adocoes.map((item) => (
              <div key={item.dimensao}>
                <div className="mb-1.5 flex items-baseline justify-between gap-2 text-sm">
                  <span className="font-medium text-zinc-700 dark:text-zinc-200">{item.rotulo}</span>
                  <span className="font-bold tabular-nums text-zinc-900 dark:text-white">
                    {item.valor.toLocaleString("pt-BR", { maximumFractionDigits: 1 })}%
                  </span>
                </div>
                <BarraProgresso valor={item.valor} tom={item.tom} />
                <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">dos alunos da turma com dado coletado</p>
              </div>
            ))}
          </div>
        </Card>
      )}

      {aviso && <Mensagem tipo={aviso.tipo}>{aviso.texto}</Mensagem>}

      {podeEditar && deOutroAno && estaTurma && (
        <div className="flex items-start gap-3 rounded-2xl border border-zinc-200 bg-white p-4 text-sm text-zinc-700 shadow-cartao dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300">
          <Info size={18} aria-hidden className="mt-0.5 shrink-0 text-indigo-600 dark:text-indigo-300" />
          <p>
            Turma do ano letivo <strong>{estaTurma.ano_letivo}</strong> (o ano ativo é {anoAtivo}): a
            lista mostra as matrículas daquele ano, que são histórico, e por isso “Transferir de
            turma” não aparece aqui. Para mudar a turma atual de um aluno, abra a turma dele do ano
            letivo {anoAtivo}. Para tirar esta turma da lista, use “Arquivar” em Turmas — o
            histórico fica preservado.
          </p>
        </div>
      )}

      <Card className="overflow-hidden">
        <CabecalhoCartao
          titulo="Alunos da turma"
          contagem={alunos ? `${numero(lista.length)} aluno${lista.length === 1 ? "" : "s"}` : undefined}
        />
        {/* Barra de ferramentas: busca, ordenação, filtro */}
        <div className="flex flex-wrap items-center gap-3 border-b border-zinc-100 px-5 py-3 dark:border-zinc-800">
          <CampoBusca
            rotulo="Pesquisar aluno da turma"
            placeholder="Pesquisar aluno..."
            className="w-full sm:w-64"
            value={busca}
            onChange={(e) => setBusca(e.target.value)}
          />
          <SelectNativo className="w-full sm:w-52" value={ordenar} onChange={(e) => setOrdenar(e.target.value)} aria-label="Ordenar por">
            {ORDENACOES.map((o) => <option key={o.valor} value={o.valor}>{o.rotulo}</option>)}
          </SelectNativo>
          <span className="inline-flex items-center gap-2.5 text-sm text-zinc-600 sm:ml-auto dark:text-zinc-300">
            {/* O nome acessível está no interruptor; o texto ao lado é só visual. */}
            <span aria-hidden className="cursor-pointer select-none" onClick={() => setIncluirInativos((v) => !v)}>
              Mostrar arquivados
            </span>
            <Interruptor ligado={incluirInativos} aoMudar={setIncluirInativos} rotulo="Mostrar arquivados" />
          </span>
        </div>

        {/* Barra de ações em massa */}
        {podeEditar && selecionados.size > 0 && (
          <div className="flex flex-wrap items-center gap-2 border-b border-indigo-100 bg-indigo-50 px-5 py-3 text-sm dark:border-indigo-500/20 dark:bg-indigo-500/10">
            <span className="font-semibold text-indigo-800 dark:text-indigo-200">
              {selecionados.size} selecionado{selecionados.size === 1 ? "" : "s"}
            </span>
            <div className="ml-auto flex flex-wrap items-center gap-2">
              {!deOutroAno && (
                <Botao variante="secundario" tamanho="sm" onClick={() => setAcao({ tipo: "transferir", ids: idsSelecionados, rotulo: `${selecionados.size} alunos` })}>
                  <ArrowRightLeft size={14} aria-hidden /> Transferir
                </Botao>
              )}
              <Botao variante="secundario" tamanho="sm" onClick={() => aplicarAcao("arquivar", idsSelecionados)}>
                <Archive size={14} aria-hidden /> Arquivar
              </Botao>
              <BotaoContornoPerigo
                onClick={() => setAcao({ tipo: "excluir", ids: idsSelecionados, rotulo: `${selecionados.size} alunos` })}>
                <Trash2 size={14} aria-hidden /> Excluir
              </BotaoContornoPerigo>
              {podeApagarAlunos && (
                <BotaoContornoPerigo
                  onClick={() => setAcao({ tipo: "permanente", ids: idsSelecionados, rotulo: `${selecionados.size} alunos` })}>
                  <TriangleAlert size={14} aria-hidden /> Excluir permanentemente
                </BotaoContornoPerigo>
              )}
              <button
                type="button"
                className="grid h-8 w-8 place-items-center rounded-full text-zinc-500 transition-colors hover:bg-white hover:text-zinc-800 max-sm:h-10 max-sm:w-10 dark:hover:bg-zinc-800 dark:hover:text-zinc-100"
                aria-label="Limpar seleção"
                title="Limpar seleção"
                onClick={() => setSelecionados(new Set())}
              >
                <X size={15} aria-hidden />
              </button>
            </div>
          </div>
        )}

        {erroAlunos ? (
          <Erro titulo="Não foi possível carregar os alunos" descricao={erroAlunos.message} aoTentar={recarregarAlunos} />
        ) : alunos === null ? (
          <EsqueletoLista texto="Carregando alunos..." />
        ) : lista.length === 0 ? (
          <Vazio icone={Users}
                 titulo={busca ? "Nenhum aluno encontrado" : "Turma sem alunos"}
                 descricao={busca ? "Ajuste a pesquisa." : "Adicione alunos ou importe dados das plataformas."} />
        ) : (
          // Celular (< 640 px): a tabela rola de lado dentro do cartão, com o aviso em
          // texto acima dela; o Desempenho e o menu ⋮ ficam presos à direita
          // (`presa-celular`), então a nota e as ações aparecem no primeiro olhar e o
          // Nº vem com a rolagem. O avatar (decorativo) some no celular para dar espaço
          // ao nome. Do sm em diante, a mesma tabela de antes.
          <TabelaRolavel rotulo="Alunos da turma: tabela completa">
            <table className={classesTabela.tabela}>
              <thead>
                <tr>
                  {podeEditar && (
                    <th className={`w-10 ${th}`}>
                      <input type="checkbox" aria-label="Selecionar todos" className={estiloCheckbox}
                             checked={todosSelecionados} onChange={alternarTodos} />
                    </th>
                  )}
                  <th className={th}>Aluno</th>
                  <th className={`text-center ${th}`}>Nº</th>
                  <th className={`text-right ${th} ${presaDesempenho}`}>Desempenho</th>
                  {podeEditar && <th className={`w-14 ${classesTabela.th} ${presaAcoes}`}><span className="sr-only">Ações</span></th>}
                </tr>
              </thead>
              <tbody>
                {lista.map((aluno) => {
                  const marcado = selecionados.has(aluno.id);
                  const badge = STATUS_BADGE[aluno.status];
                  return (
                    <tr key={aluno.id}
                        className={`${classesTabela.tr} ${
                          marcado ? "bg-indigo-50/60 dark:bg-indigo-500/10" : ""
                        }`}>
                      {podeEditar && (
                        <td className="px-4 py-3.5 max-sm:px-3">
                          <input type="checkbox" aria-label={`Selecionar ${aluno.nome}`} className={estiloCheckbox}
                                 checked={marcado} onChange={() => alternarUm(aluno.id)} />
                        </td>
                      )}
                      <td className={td}>
                        <div className={`flex items-center gap-3 ${aluno.status !== "ativo" ? "opacity-70" : ""}`}>
                          <span className="hidden shrink-0 sm:flex">
                            <AvatarAluno nome={aluno.nome} chave={aluno.id} foto={aluno.foto_url} />
                          </span>
                          {/* Celular: o nome quebra em até duas linhas (base de 7rem) em vez
                              de correr por baixo das colunas presas à direita. */}
                          <div className="min-w-0 max-sm:min-w-[7rem]">
                            <Link to={`/alunos/${aluno.id}`}
                                  className="block truncate font-semibold text-zinc-900 transition-colors hover:text-indigo-600 max-sm:whitespace-normal dark:text-zinc-100 dark:hover:text-indigo-300" title={aluno.nome}>
                              {aluno.nome}
                            </Link>
                            <div className="mt-0.5 flex flex-wrap items-center gap-1.5">
                              {badge && <PilulaSituacao tom={badge.tom}>{badge.texto}</PilulaSituacao>}
                              {aluno.created_at && (
                                <span className="text-xs text-zinc-500 dark:text-zinc-400">
                                  desde {dataDia(aluno.created_at)}
                                </span>
                              )}
                            </div>
                          </div>
                        </div>
                      </td>
                      <td className={`text-center tabular-nums text-zinc-500 dark:text-zinc-400 ${td}`}>
                        {aluno.numero_chamada ?? "—"}
                      </td>
                      <td className={`text-right tabular-nums ${td} ${presaDesempenho}`}>
                        {aluno.nota_geral != null ? (
                          <span className="inline-flex items-baseline gap-1.5">
                            <span className="font-bold text-zinc-900 dark:text-zinc-100">{fmtNota(aluno.nota_geral)}</span>
                            {aluno.posicao != null && <span className="text-xs text-zinc-500 dark:text-zinc-400">{aluno.posicao}º</span>}
                          </span>
                        ) : (
                          <span className="text-xs text-zinc-500 dark:text-zinc-400">sem nota</span>
                        )}
                      </td>
                      {podeEditar && (
                        <td className={`text-right ${classesTabela.td} ${presaAcoes}`}>
                          <MenuAcoes aluno={aluno} podeApagarAlunos={podeApagarAlunos}
                                     podeTransferir={!deOutroAno}
                                     aoEscolher={(escolha) => aoEscolherNoMenu(aluno, escolha)} />
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
            depois{podeApagarAlunos
              ? " — para apagar tudo de vez, use “Excluir permanentemente”."
              : ". Apagar tudo de vez é exclusivo do Admin Global."}
          </p>
          <div className="mt-6 flex justify-end gap-2.5">
            <Botao variante="secundario" onClick={() => setAcao(null)} disabled={ocupado}>Cancelar</Botao>
            <Botao variante="perigo" disabled={ocupado}
                   onClick={() => aplicarAcao("excluir", acao.ids)}>
              {ocupado ? "Excluindo..." : "Excluir"}
            </Botao>
          </div>
        </Modal>
      )}

      {acao?.tipo === "cartao_quest" && (
        <ModalCartaoQuest
          aluno={acao.alvo}
          ocupado={ocupado}
          aoFechar={() => setAcao(null)}
          aoConfirmar={() => gerarCartaoNovoQuest(acao.alvo)}
        />
      )}

      {acao?.tipo === "permanente" && podeApagarAlunos && (
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
      <div className="mt-6 flex justify-end gap-2.5">
        <Botao variante="secundario" onClick={aoFechar} disabled={ocupado}>Cancelar</Botao>
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
      <div className="mt-6 flex justify-end gap-2.5">
        <Botao variante="secundario" onClick={aoFechar} disabled={ocupado}>Cancelar</Botao>
        <Botao disabled={ocupado || !turmaId} onClick={() => turmaId && aoConfirmar(turmaId)}>
          {ocupado ? "Transferindo..." : "Transferir"}
        </Botao>
      </div>
    </Modal>
  );
}

/** Confirmação do cartão novo do Quest de um aluno: o cartão antigo para de entrar
 * (código e QR trocados). Ficha inativa: só revoga, sem cartão novo. */
function ModalCartaoQuest({ aluno, ocupado, aoFechar, aoConfirmar }: {
  aluno: AlunoGestao;
  ocupado: boolean;
  aoFechar: () => void;
  aoConfirmar: () => void;
}) {
  const inativo = aluno.status !== "ativo";
  return (
    <Modal titulo={inativo ? "Revogar cartão do Quest" : "Novo cartão do Quest"} aberto aoFechar={aoFechar}>
      {inativo ? (
        <p className="text-sm text-zinc-600 dark:text-zinc-300">
          Revogar o cartão do Quest de <strong>{aluno.nome}</strong>? O código e o QR antigos
          param de entrar e quem estiver jogando com eles sai do jogo. Como o aluno não está
          ativo, não sai cartão novo agora: se ele voltar, o cartão novo sai em “Cartões do Quest”.
        </p>
      ) : (
        <p className="text-sm text-zinc-600 dark:text-zinc-300">
          Gerar um cartão novo do Quest para <strong>{aluno.nome}</strong>? O código e o QR
          mudam: o cartão antigo para de entrar e quem estiver jogando com ele sai do jogo. Os
          colegas da turma continuam com os cartões deles. O PDF do cartão novo é baixado para
          você imprimir.
        </p>
      )}
      <div className="mt-6 flex justify-end gap-2.5">
        <Botao variante="secundario" onClick={aoFechar} disabled={ocupado}>Cancelar</Botao>
        <Botao disabled={ocupado} onClick={aoConfirmar}>
          {ocupado ? "Gerando..." : inativo ? "Revogar cartão" : "Gerar cartão novo"}
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
      <div className="flex items-start gap-3 rounded-2xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800 dark:border-rose-500/20 dark:bg-rose-500/10 dark:text-rose-200">
        <TriangleAlert size={18} aria-hidden className="mt-0.5 shrink-0" />
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
      <div className="mt-6 flex justify-end gap-2.5">
        <Botao variante="secundario" onClick={aoFechar} disabled={ocupado}>Cancelar</Botao>
        <Botao variante="perigo" disabled={ocupado || !liberado}
               onClick={() => aoConfirmar(texto.trim())}>
          <TriangleAlert size={15} aria-hidden /> {ocupado ? "Excluindo..." : "Excluir para sempre"}
        </Botao>
      </div>
    </Modal>
  );
}
